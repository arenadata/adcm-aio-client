import asyncio

from httpx import AsyncClient, Timeout
import pytest
import pytest_asyncio

from adcm_aio_client._types import UserStatus, UserType
from adcm_aio_client.client import ADCMClient
from adcm_aio_client.errors import ConflictError, MultipleObjectsReturnedError, NotFoundError, ObjectDoesNotExistError
from adcm_aio_client.objects import LDAPUser, LocalUser
from tests.integration.setup_environment import DB_USER, ADCMContainer, ADCMPostgresContainer

pytestmark = [pytest.mark.asyncio]


# pyright: reportAttributeAccessIssue=false


async def get_all_users(httpx_client: AsyncClient) -> list[dict]:
    response = await httpx_client.get(url="rbac/users/")
    assert response.status_code == 200

    return response.json()["results"]


async def create_51_users_delete_others_except_admin(
    httpx_client: AsyncClient, adcm: ADCMContainer, postgres: ADCMPostgresContainer, two_groups: list[dict]
) -> None:
    """
    Creates 51 LocalUsers named User_1, ..., User_51
    Add users to groups:
      User_1, _10, ..., _19 - Group_1
      User_2, _20, ..., _29 - Group_2
    Deletes all users except just created and admin
    """

    groups = {group["displayName"]: group["id"] for group in two_groups}
    usernames = {"admin"}
    requests = []

    for i in range(1, 52, 1):
        username = f"User_{i}"
        usernames.add(username)

        data = {"username": username, "password": f"user_{i}_password"}
        if group_id := groups.get(f"Group_{str(i)[0]}"):
            data.update({"groups": [group_id]})  # pyright: ignore[reportCallIssue, reportArgumentType]

        requests.append(httpx_client.post(url="rbac/users/", data=data, timeout=Timeout(15.0, read=None)))

    await asyncio.gather(*requests, return_exceptions=False)

    usernames = ", ".join(f"'{username}'" for username in usernames)
    sql = f"""
    WITH ids AS (
        SELECT id FROM auth_user WHERE username NOT IN ({usernames})
    )
    DELETE FROM rbac_user WHERE user_ptr_id IN (SELECT id FROM ids);
    DELETE FROM auth_user WHERE username NOT IN ({usernames});
    """  # noqa: S608
    postgres.execute_statement(sql, db_user=DB_USER, db_name=adcm._db.name)


@pytest_asyncio.fixture()
async def two_groups(httpx_client: AsyncClient) -> list[dict]:
    group_keys = {"id", "name", "displayName"}
    groups = []

    for name in {"Group_1", "Group_2"}:
        response = await httpx_client.post(url="rbac/groups/", data={"display_name": name})
        assert response.status_code == 201
        groups.append({k: v for k, v in response.json().items() if k in group_keys})

    return groups


@pytest_asyncio.fixture()
async def ldap_user(
    adcm_client: ADCMClient, httpx_client: AsyncClient, adcm: ADCMContainer, postgres: ADCMPostgresContainer
) -> LDAPUser:
    username = "LDAPUser"

    response = await httpx_client.post(url="rbac/users/", data={"username": username, "password": "ldap_user_password"})
    assert response.status_code == 201
    id_ = response.json()["id"]

    sql = f"UPDATE rbac_user SET type = '{UserType.LDAP.value}' WHERE user_ptr_id = {id_};"  # noqa: S608
    postgres.execute_statement(sql, db_user=DB_USER, db_name=adcm._db.name)

    ldap_user = await adcm_client.users.get(username__eq=username)
    assert isinstance(ldap_user, LDAPUser)
    assert ldap_user._data["type"] == UserType.LDAP.value

    return ldap_user


async def test_user(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    ldap_user: LDAPUser,
    two_groups: list[dict],
    adcm: ADCMContainer,
    postgres: ADCMPostgresContainer,
) -> None:
    await _test_user_object_api(
        adcm_client=adcm_client, httpx_client=httpx_client, ldap_user=ldap_user, two_groups=two_groups
    )

    await create_51_users_delete_others_except_admin(httpx_client, adcm, postgres, two_groups)
    await _test_users_accessor(adcm_client=adcm_client, two_groups=two_groups)


async def _test_user_object_api(
    adcm_client: ADCMClient, httpx_client: AsyncClient, ldap_user: LDAPUser, two_groups: list[dict]
) -> None:
    # ldap user api
    assert isinstance(ldap_user.id, int)
    assert ldap_user.username == "LDAPUser"
    assert ldap_user.password == "*****"  # noqa: S105
    assert ldap_user.first_name == ""
    assert ldap_user.last_name == ""
    assert ldap_user.email == ""
    assert not ldap_user.is_super_user
    assert ldap_user.groups == []
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
    assert local_user.groups == []
    assert local_user.status == UserStatus.NOT_SAVED
    for field in {"username", "first_name", "last_name", "email", "is_super_user"}:
        assert getattr(local_user, field) == local_user_data[field]

    await local_user.save()

    assert isinstance(local_user.id, int)
    assert local_user.password == "*****"  # noqa: S105
    assert local_user.groups == []
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
    assert remote_local_user["groups"] == local_user.groups

    await _test_update(
        adcm_client=adcm_client,
        local_user=local_user,
        ldap_user=ldap_user,
        two_groups=two_groups,
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
    adcm_client: ADCMClient,
    local_user: LocalUser,
    ldap_user: LDAPUser,
    two_groups: list[dict],
    httpx_client: AsyncClient,
) -> None:
    _ = adcm_client
    # update LocalUser
    expected_update_data = {
        "password": "new_test_user_password",
        "firstName": "New First name",
        "lastName": "New Last name",
        "email": "new_test_user@example.com",
        "isSuperUser": True,
        "groups": [two_groups[1]["id"]],
    }

    with pytest.raises(AttributeError):
        local_user.id = 100
    with pytest.raises(AttributeError):
        local_user.username = "newusername"
    local_user.password = expected_update_data["password"]
    local_user.first_name = expected_update_data["firstName"]
    local_user.last_name = expected_update_data["lastName"]
    local_user.email = expected_update_data["email"]
    local_user.is_super_user = expected_update_data["isSuperUser"]
    local_user.groups = expected_update_data["groups"]

    assert local_user._manually_set == set(expected_update_data.keys())

    await local_user.save()

    # wrong update
    local_user.groups = [-3]
    with pytest.raises(ConflictError, match="USER_UPDATE_ERROR.*Some of groups doesn't exist"):
        await local_user.save()
    assert local_user._manually_set == {"groups"}

    # refresh should clear _manually_set fields
    await local_user.refresh()
    assert local_user._manually_set == set()

    # wrong id
    local_user._data["id"] = 9999
    with pytest.raises(NotFoundError, match="API_ERROR.*User not found"):
        await local_user.save()

    remote_local_user = [u for u in await get_all_users(httpx_client) if u["username"] == local_user.username][0]
    expected_update_data.pop("password")
    expected_update_data["groups"] = [two_groups[1]]
    remote_local_user = {k: v for k, v in remote_local_user.items() if k in expected_update_data}
    assert remote_local_user == expected_update_data

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

    ldap_user.groups = [two_groups[1]["id"]]  # TODO: it can't be changed now, but in SRS
    assert ldap_user._manually_set == {"groups"}

    with pytest.raises(ConflictError, match="USER_UPDATE_ERROR.*LDAP user's information can't be changed"):
        await ldap_user.save()
    assert ldap_user._manually_set == {"groups"}

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
    assert ldap_user.groups == []


async def _test_users_accessor(adcm_client: ADCMClient, two_groups: list[dict]) -> None:
    groups = {group["displayName"]: group["id"] for group in two_groups}
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

    num_users = 52

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
        ("username__contains", ("_", num_users - 1)),  # except admin
        ("username__icontains", ("USER", num_users - 1)),
        ("group__eq", (groups["Group_1"], 11)),
        ("group__ne", (groups["Group_2"], num_users - 11)),
        ("group__in", ([groups["Group_1"], groups["Group_2"]], 22)),
        ("group__exclude", ([groups["Group_1"], groups["Group_2"]], num_users - 22)),
    )

    for filter_key, (filter_value, expected) in filters_data:
        filter_dict = {filter_key: filter_value}
        users = await adcm_client.users.filter(**filter_dict)
        assert len(users) == expected, f"Filter: {filter_dict}"
