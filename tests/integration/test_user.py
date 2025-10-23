import re
import asyncio

from httpx import AsyncClient, Timeout
import pytest
import pytest_asyncio

from adcm_aio_client._types import EntitySourceType, UserStatus
from adcm_aio_client.client import ADCMClient
from adcm_aio_client.errors import ConflictError, MultipleObjectsReturnedError, NotFoundError, ObjectDoesNotExistError
from adcm_aio_client.objects import LDAPGroup, LDAPUser, LocalGroup, LocalUser
from tests.integration.setup_environment import DB_USER, ADCMContainer, ADCMPostgresContainer

pytestmark = [pytest.mark.asyncio]


# pyright: reportAttributeAccessIssue=false


async def get_all_users(httpx_client: AsyncClient) -> list[dict]:
    response = await httpx_client.get(url="rbac/users/", params={"limit": 999})
    assert response.status_code == 200

    return response.json()["results"]


async def create_51_users(httpx_client: AsyncClient, groups: dict[str, int]) -> None:
    """
    Creates 51 LocalUsers named User_1, ..., User_51
    Add users to groups:
      User_1, _10, ..., _19 - Test local group
      User_2, _20, ..., _29 - Another test local group
    """

    groups = {"1": groups["Test local group"], "2": groups["Another test local group"]}
    requests = []
    for i in range(1, 52, 1):
        username = f"User_{i}"

        data = {"username": username, "password": f"user_{i}_password"}
        if group_id := groups.get(str(i)[0]):
            data.update({"groups": [group_id]})  # pyright: ignore[reportCallIssue, reportArgumentType]

        requests.append(httpx_client.post(url="rbac/users/", data=data, timeout=Timeout(15.0, read=None)))

    await asyncio.gather(*requests, return_exceptions=False)


@pytest_asyncio.fixture()
async def three_groups(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    adcm: ADCMContainer,
    postgres: ADCMPostgresContainer,
) -> tuple[LocalGroup, LocalGroup, LDAPGroup]:
    """Creates three groups: local saved, local unsaved, ldap saved (unsaved ldap group can't be instantiated)"""

    url = "rbac/groups/"
    local_group_name = "Test local group"
    ldap_group_name = "Test ldap group"

    response = await httpx_client.post(
        url=url, data={"display_name": local_group_name}, timeout=Timeout(15.0, read=None)
    )
    assert response.status_code == 201

    local_group_saved = await adcm_client.groups.get(display_name__eq=local_group_name)
    assert isinstance(local_group_saved, LocalGroup)
    assert local_group_saved._data["type"] == EntitySourceType.LOCAL.value

    response = await httpx_client.post(
        url=url, data={"display_name": ldap_group_name}, timeout=Timeout(15.0, read=None)
    )
    assert response.status_code == 201
    ldap_group_id = response.json()["id"]

    sql = f"UPDATE rbac_group SET type = '{EntitySourceType.LDAP.value}' WHERE group_ptr_id = {ldap_group_id};"  # noqa: S608
    postgres.execute_statement(sql, db_user=DB_USER, db_name=adcm._db.name)

    ldap_group_saved = await adcm_client.groups.get(display_name__eq=ldap_group_name)
    assert isinstance(ldap_group_saved, LDAPGroup)
    assert ldap_group_saved._data["type"] == EntitySourceType.LDAP.value

    local_group_unsaved = LocalGroup(client=adcm_client, display_name="Another test local group")

    return local_group_saved, local_group_unsaved, ldap_group_saved


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
    three_groups: tuple[LocalGroup, LocalGroup, LDAPGroup],
) -> None:
    await _test_user_object_api(
        adcm_client=adcm_client, httpx_client=httpx_client, ldap_user=ldap_user, three_groups=three_groups
    )

    local_group_saved, local_group_unsaved, *_ = three_groups
    await local_group_unsaved.save()  # create group
    assert isinstance(local_group_unsaved.id, int)
    groups: dict[str, int] = {group.display_name: group.id for group in (local_group_saved, local_group_unsaved)}  # pyright: ignore[reportAssignmentType]

    await create_51_users(httpx_client=httpx_client, groups=groups)
    await _test_users_accessor(adcm_client=adcm_client, httpx_client=httpx_client, groups=groups)


async def _test_user_object_api(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    ldap_user: LDAPUser,
    three_groups: tuple[LocalGroup, LocalGroup, LDAPGroup],
) -> None:
    # ldap user api
    assert isinstance(ldap_user.id, int)
    assert ldap_user.username == "LDAPUser"
    assert ldap_user.password == "*****"  # noqa: S105
    assert ldap_user.first_name == ""
    assert ldap_user.last_name == ""
    assert ldap_user.email == ""
    assert not ldap_user.is_super_user
    assert await ldap_user.groups == []
    assert ldap_user.status == UserStatus.ACTIVE

    # create
    local_user_data = {
        "username": "test_user",
        "password": "test_user_password",
        "is_super_user": False,
        "first_name": "First name",
        "last_name": "Last name",
        "email": "test_user@example.com",
    }
    all_users = await get_all_users(httpx_client=httpx_client)
    assert local_user_data["username"] not in (user["username"] for user in all_users)

    with pytest.raises(NotImplementedError):
        LDAPUser(client=adcm_client, **local_user_data)

    local_user = LocalUser(client=adcm_client, **local_user_data)
    assert local_user.id is None
    assert local_user.password == "*****"  # noqa: S105
    assert await local_user.groups == []
    assert local_user.status == UserStatus.ACTIVE
    for field in {"username", "first_name", "last_name", "email", "is_super_user"}:
        assert getattr(local_user, field) == local_user_data[field]

    await local_user.save()

    assert isinstance(local_user.id, int)
    assert local_user.password == "*****"  # noqa: S105
    assert await local_user.groups == []
    assert local_user.status == UserStatus.ACTIVE
    for field in {"username", "first_name", "last_name", "email", "is_super_user"}:
        assert getattr(local_user, field) == local_user_data[field]

    remote_local_user = [u for u in await get_all_users(httpx_client) if u["username"] == local_user.username][0]
    assert remote_local_user["id"] == local_user.id
    assert remote_local_user["username"] == local_user.username
    assert remote_local_user["firstName"] == local_user.first_name
    assert remote_local_user["lastName"] == local_user.last_name
    assert remote_local_user["email"] == local_user.email
    assert remote_local_user["isSuperUser"] == local_user.is_super_user
    assert remote_local_user["groups"] == await local_user.groups

    await _test_update(
        local_user=local_user,
        ldap_user=ldap_user,
        three_groups=three_groups,
        httpx_client=httpx_client,
    )

    local_user._data["id"] = remote_local_user["id"]  # return original id; refresh
    await local_user.refresh()

    # delete
    await local_user.delete()
    all_users = await get_all_users(httpx_client=httpx_client)
    assert local_user_data["username"] not in (user["username"] for user in all_users)

    # delete non-existent
    local_user._data["id"] = 9999
    with pytest.raises(NotFoundError, match="API_ERROR.*404"):
        await local_user.delete()

    # delete ldap user
    with pytest.raises(AttributeError):
        ldap_user.delete()


async def _test_update(
    local_user: LocalUser,
    ldap_user: LDAPUser,
    three_groups: tuple[LocalGroup, LocalGroup, LDAPGroup],
    httpx_client: AsyncClient,
) -> None:
    local_group_saved, local_group_unsaved, ldap_group_saved = three_groups
    # update LocalUser
    expected_update_data = {
        "password": "new_test_user_password",
        "firstName": "New First name",
        "lastName": "New Last name",
        "email": "new_test_user@example.com",
        "isSuperUser": True,
    }
    groups_correct = [local_group_saved]
    groups_incorrect = (
        (
            [local_group_saved, local_group_unsaved],
            (ValueError, "All groups must be saved before assigning them to user"),
        ),
        (
            [local_group_saved, 7],
            (
                ValueError,
                re.escape(f"All groups must be {LocalGroup.__name__}, got {[int]}"),
            ),
        ),
    )

    with pytest.raises(AttributeError):
        local_user.id = 100
    with pytest.raises(AttributeError):
        local_user.username = "newusername"
    local_user.password = expected_update_data["password"]
    local_user.first_name = expected_update_data["firstName"]
    local_user.last_name = expected_update_data["lastName"]
    local_user.email = expected_update_data["email"]
    local_user.is_super_user = expected_update_data["isSuperUser"]

    for value, (err_cls, err_msg) in groups_incorrect:
        with pytest.raises(err_cls, match=err_msg):
            local_user.groups = value

    assert local_user._manually_set == {"password", "firstName", "lastName", "email", "isSuperUser"}

    local_user.groups = groups_correct
    assert local_user._manually_set == {"password", "firstName", "lastName", "email", "isSuperUser", "groups"}

    await local_user.save()
    assert await local_user.groups == []  # value is cached, refresh needed

    await local_user.refresh()
    assert local_user._manually_set == set()
    remote_local_user = [u for u in await get_all_users(httpx_client) if u["username"] == local_user.username][0]

    assert local_user._manually_set == set()
    remote_groups = {g["id"] for g in remote_local_user["groups"]}
    retrieved_groups = {g.id for g in await local_user.groups}
    expected_groups = {g.id for g in groups_correct}
    assert remote_groups == retrieved_groups == expected_groups
    assert local_user.password == "*****"  # noqa: S105
    assert remote_local_user["firstName"] == local_user.first_name == expected_update_data["firstName"]
    assert remote_local_user["lastName"] == local_user.last_name == expected_update_data["lastName"]
    assert remote_local_user["email"] == local_user.email == expected_update_data["email"]
    assert remote_local_user["isSuperUser"] == local_user.is_super_user == expected_update_data["isSuperUser"]

    # wrong id
    local_user._data["id"] = 9999
    with pytest.raises(NotFoundError, match="API_ERROR.*User not found"):
        await local_user.save()

    # LDAPUser
    with pytest.raises(AttributeError):
        ldap_user.id = 100
    with pytest.raises(AttributeError):
        ldap_user.username = "123"
    with pytest.raises(AttributeError):
        ldap_user.password = "123"  # noqa: S105
    with pytest.raises(AttributeError):
        ldap_user.first_name = "123"
    with pytest.raises(AttributeError):
        ldap_user.last_name = "123"
    with pytest.raises(AttributeError):
        ldap_user.email = "123"
    with pytest.raises(AttributeError):
        ldap_user.is_super_user = True
    with pytest.raises(AttributeError):
        ldap_user.groups = [local_group_saved]

    with pytest.raises(ConflictError, match="USER_UPDATE_ERROR.*LDAP user's information can't be changed"):
        await ldap_user.save()

    assert ldap_user._manually_set == set()
    await ldap_user.refresh()
    assert ldap_user._manually_set == set()

    remote_ldap_user = [u for u in await get_all_users(httpx_client) if u["username"] == ldap_user.username][0]
    assert ldap_user.id == remote_ldap_user["id"]
    assert ldap_user.username == remote_ldap_user["username"]
    assert ldap_user.password == "*****"  # noqa: S105
    assert ldap_user.first_name == remote_ldap_user["firstName"]
    assert ldap_user.last_name == remote_ldap_user["lastName"]
    assert ldap_user.email == remote_ldap_user["email"]
    assert not ldap_user.is_super_user
    assert await ldap_user.groups == []


async def _test_users_accessor(adcm_client: ADCMClient, httpx_client: AsyncClient, groups: dict[str, int]) -> None:
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
        ("group__eq", (groups["Test local group"], 11)),
        ("group__ne", (groups["Another test local group"], num_users - 11)),
        ("group__in", ([groups["Test local group"], groups["Another test local group"]], 22)),
        ("group__exclude", ([groups["Test local group"], groups["Another test local group"]], num_users - 22)),
    )

    for filter_key, (filter_value, expected) in filters_data:
        filter_dict = {filter_key: filter_value}
        users = await adcm_client.users.filter(**filter_dict)
        assert len(users) == expected, f"Filter: {filter_dict}"
