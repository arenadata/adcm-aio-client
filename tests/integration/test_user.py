import asyncio

from httpx import AsyncClient, Timeout
import pytest
import pytest_asyncio

from adcm_aio_client._types import EntitySourceType
from adcm_aio_client.client import ADCMClient
from adcm_aio_client.errors import MultipleObjectsReturnedError, ObjectDoesNotExistError
from adcm_aio_client.objects import LDAPUser, LocalGroup, LocalUser
from tests.integration.setup_environment import DB_USER, ADCMContainer, ADCMPostgresContainer

pytestmark = [pytest.mark.asyncio]


async def assert_user(user: LocalUser | LDAPUser, expected: dict, httpx_client: AsyncClient) -> None:
    response = await httpx_client.get(f"rbac/users/{user.id}/")
    assert response.status_code == 200

    response = response.json()
    for attr, value in expected.items():
        assert response[attr] == value


async def create_51_users(httpx_client: AsyncClient, local_group: LocalGroup) -> None:
    """
    Creates 51 LocalUsers named User_1, ..., User_51, add first 25 of them to local_group
    """

    requests = []
    for i in range(1, 52, 1):
        username = f"User_{i}"

        data = {"username": username, "password": f"user_{i}_password", "groups": []}
        if i <= 25:
            data["groups"] = [local_group.id]

        requests.append(httpx_client.post(url="rbac/users/", data=data, timeout=Timeout(15.0, read=None)))

    await asyncio.gather(*requests, return_exceptions=False)


@pytest_asyncio.fixture()
async def local_group(adcm_client: ADCMClient, httpx_client: AsyncClient) -> LocalGroup:
    name = "Test local group"
    response = await httpx_client.post(
        url="rbac/groups/", data={"display_name": name}, timeout=Timeout(15.0, read=None)
    )
    assert response.status_code == 201

    group = await adcm_client.groups.get(display_name__eq=name)
    assert isinstance(group, LocalGroup)

    return group


@pytest_asyncio.fixture()
async def ldap_user(
    adcm_client: ADCMClient, httpx_client: AsyncClient, adcm: ADCMContainer, postgres: ADCMPostgresContainer
) -> LDAPUser:
    username = "LDAPUser"

    response = await httpx_client.post(url="rbac/users/", data={"username": username, "password": "ldap_user_password"})
    assert response.status_code == 201
    id_ = response.json()["id"]

    sql = f"UPDATE rbac_user SET type = '{EntitySourceType.LDAP.value}' WHERE user_ptr_id = {id_};"  # noqa: S608
    postgres.execute_statement(sql, db_user=DB_USER, db_name=adcm._db.name)

    ldap_user = await adcm_client.users.get(username__eq=username)
    assert isinstance(ldap_user, LDAPUser)
    assert ldap_user._data["type"] == EntitySourceType.LDAP.value

    return ldap_user


async def test_user(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    ldap_user: LDAPUser,
    local_group: LocalGroup,
) -> None:
    await _test_create_delete_api(
        adcm_client=adcm_client, httpx_client=httpx_client, ldap_user=ldap_user, local_group=local_group
    )

    await _test_users_accessor(adcm_client=adcm_client, httpx_client=httpx_client, local_group=local_group)


async def _test_create_delete_api(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    ldap_user: LDAPUser,
    local_group: LocalGroup,
) -> None:
    username = "Test-username"
    email = "em@a.il"
    user = await adcm_client.users.create(username=username, password=username * 2, email=email, groups=[local_group])

    assert isinstance(user, LocalUser)
    expected = {
        "id": user.id,
        "username": username,
        "firstName": "",
        "lastName": "",
        "status": "active",
        "email": email,
        "type": "local",
        "isBuiltIn": False,
        "isSuperUser": False,
        "groups": [
            {
                "id": local_group.id,
                "name": f"{local_group.display_name} [local]",
                "displayName": local_group.display_name,
            }
        ],
        "blockingReason": None,
    }
    await assert_user(user, expected, httpx_client)

    await user.delete()
    response = await httpx_client.get(f"rbac/users/{user.id}/")
    assert response.status_code == 404

    with pytest.raises(AttributeError):
        await ldap_user.delete()  # pyright: ignore[reportAttributeAccessIssue]


async def _test_users_accessor(adcm_client: ADCMClient, httpx_client: AsyncClient, local_group: LocalGroup) -> None:
    await create_51_users(httpx_client=httpx_client, local_group=local_group)

    no_objects_msg = "^No objects found with the given filter.$"
    multiple_objects_msg = "^More than one object found.$"

    # get
    assert isinstance(await adcm_client.users.get(username__eq="User_30"), LocalUser)

    with pytest.raises(ObjectDoesNotExistError, match=no_objects_msg):
        await adcm_client.users.get(username__eq="User_53")

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await adcm_client.users.get(username__in=["User_1", "User_2"])

    # get_or_none
    assert isinstance(await adcm_client.users.get_or_none(username__eq="User_2"), LocalUser)

    assert await adcm_client.users.get_or_none(username__eq="NotAUser") is None

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await adcm_client.users.get_or_none(username__in=["User_1", "User_2"])

    response = await httpx_client.get("rbac/users/")
    num_users = response.json()["count"]

    # all
    all_users = await adcm_client.users.all()
    assert all(isinstance(user, LocalUser | LDAPUser) for user in all_users)
    assert len({user.id for user in all_users}) == num_users
    assert len({id(user) for user in all_users}) == num_users

    # list
    page_size = 50
    assert page_size < num_users, "check page_size or number of users"

    first_page_users = await adcm_client.users.list()
    assert len({user.id for user in first_page_users}) == page_size
    assert len({id(user) for user in first_page_users}) == page_size

    # iter
    iter_users = []
    async for user in adcm_client.users.iter():
        iter_users.append(user)
    assert len(iter_users) == num_users
    assert len({user.id for user in iter_users}) == num_users
    assert len({id(user) for user in iter_users}) == num_users

    # filter
    filters_data = (
        ("username__eq", ("User_2", 1)),
        ("username__ne", ("User_2", num_users - 1)),
        ("username__in", (["User_6", "User_7", "User_8"], 3)),
        ("username__exclude", (["User_6", "User_7", "User_8"], num_users - 3)),
        ("username__ieq", ("USER_17", 1)),
        ("username__ine", ("UseR_1", num_users - 1)),
        ("username__iin", (["USER_6", "UsEr_7", "User_8"], 3)),
        ("username__iexclude", (["USER_6", "UsEr_7", "User_8"], num_users - 3)),
        ("username__contains", ("r_3", 11)),
        ("username__icontains", ("USER", num_users - 1)),
        ("group__eq", (local_group.id, 25)),
        ("group__ne", (local_group.id, num_users - 25)),
        ("group__in", ([local_group.id], 25)),
        ("group__exclude", ([local_group.id], num_users - 25)),
    )

    for filter_key, (filter_value, expected) in filters_data:
        filter_dict = {filter_key: filter_value}
        users = await adcm_client.users.filter(**filter_dict)
        assert len(users) == expected, f"Filter: {filter_dict}"
