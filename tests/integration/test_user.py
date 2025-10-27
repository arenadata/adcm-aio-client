import asyncio

from httpx import AsyncClient, Timeout
import pytest
import pytest_asyncio

from adcm_aio_client._types import SourceType
from adcm_aio_client.client import ADCMClient
from adcm_aio_client.errors import MultipleObjectsReturnedError, ObjectDoesNotExistError
from adcm_aio_client.objects import LDAPGroup, LDAPUser, LocalGroup, LocalUser, LocalUserData, LocalUserLazy, new_user
from adcm_aio_client.objects.rbac._types import UserKwargs
from tests.integration.setup_environment import DB_USER, ADCMContainer, ADCMPostgresContainer

pytestmark = [pytest.mark.asyncio]


# pyright: reportAttributeAccessIssue=false


async def get_all_usernames(httpx_client: AsyncClient) -> list[dict]:
    response = await httpx_client.get(url="rbac/users/", params={"limit": 999})
    assert response.status_code == 200

    return [user["username"] for user in response.json()["results"]]


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
    assert local_group_saved._data["type"] == SourceType.LOCAL.value

    response = await httpx_client.post(
        url=url, data={"display_name": ldap_group_name}, timeout=Timeout(15.0, read=None)
    )
    assert response.status_code == 201
    ldap_group_id = response.json()["id"]

    sql = f"UPDATE rbac_group SET type = '{SourceType.LDAP.value}' WHERE group_ptr_id = {ldap_group_id};"  # noqa: S608
    postgres.execute_statement(sql, db_user=DB_USER, db_name=adcm._db.name)

    ldap_group_saved = await adcm_client.groups.get(display_name__eq=ldap_group_name)
    assert isinstance(ldap_group_saved, LDAPGroup)
    assert ldap_group_saved._data["type"] == SourceType.LDAP.value

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

    sql = f"UPDATE rbac_user SET type = '{SourceType.LDAP.value}' WHERE user_ptr_id = {id_};"  # noqa: S608
    postgres.execute_statement(sql, db_user=DB_USER, db_name=adcm._db.name)

    ldap_user = await adcm_client.users.get(username__eq=username)
    assert isinstance(ldap_user, LDAPUser)
    assert ldap_user._data["type"] == SourceType.LDAP.value

    return ldap_user


async def test_user(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    ldap_user: LDAPUser,
    three_groups: tuple[LocalGroup, LocalGroup, LDAPGroup],
) -> None:
    _test_misc()
    # TODO: test update user.groups after groups refactor
    await _test_local_user_data_api(adcm_client=adcm_client, httpx_client=httpx_client)
    await _test_local_user_lazy_api(adcm_client=adcm_client, httpx_client=httpx_client)
    await _test_ldap_user_api(user=ldap_user)
    await _test_users_accessor(adcm_client=adcm_client, httpx_client=httpx_client, three_groups=three_groups)


def _test_misc() -> None:
    # check that UserKwargs fields match LocalUserData fields
    localuserdata = LocalUserData.__annotations__
    id_ann = localuserdata.pop("id")
    assert id_ann.__args__ == (int | None,)

    userkwargs = UserKwargs.__annotations__

    expected_fields = {"username", "password", "is_super_user", "first_name", "last_name", "email"}
    assert set(localuserdata.keys()) == set(userkwargs.keys()) == expected_fields

    for field in expected_fields:
        kwarg_type = userkwargs[field].__args__
        localuserdata_type = localuserdata[field].__args__
        assert kwarg_type == localuserdata_type, f"{field=}, {kwarg_type=}, {localuserdata_type=}"


async def _test_local_user_data_api(adcm_client: ADCMClient, httpx_client: AsyncClient) -> None:
    username = "New_test_user"
    assert username not in await get_all_usernames(httpx_client)

    for wrong_data in ({"username": username}, {"password": username * 2}):
        with pytest.raises(ValueError, match=r"^\"username\" and \"password\" are mandatory to create a user$"):
            new_user(**wrong_data)  # pyright: ignore[reportArgumentType]

    user = new_user(username=username, password=username * 2)
    lastname = "Last Name"
    assert isinstance(user, LocalUserData)
    user.last_name = lastname

    with pytest.raises(AttributeError):
        await user.save()

    with pytest.raises(AttributeError):
        await user.delete()

    local_user = await adcm_client.users.init(user)
    assert isinstance(local_user, LocalUser)
    assert local_user.username in await get_all_usernames(httpx_client)

    assert isinstance(local_user.id, int)
    assert local_user.username == username
    assert local_user.first_name == ""
    assert local_user.last_name == lastname
    assert not local_user.is_super_user
    assert local_user.email == ""

    email = "example@mail.com"
    edited_user = local_user.edit(email=email)
    assert isinstance(edited_user, LocalUserLazy)
    with pytest.raises(AttributeError):
        await edited_user.delete()

    saved_user = await edited_user.save()
    assert isinstance(saved_user, LocalUser)
    assert saved_user.username in await get_all_usernames(httpx_client)

    await saved_user.delete()
    assert saved_user.username not in await get_all_usernames(httpx_client)


async def _test_local_user_lazy_api(adcm_client: ADCMClient, httpx_client: AsyncClient) -> None:
    username = "Test_user_from_node"
    assert username not in await get_all_usernames(httpx_client)

    for wrong_data in ({"username": username}, {"password": username * 2}):
        with pytest.raises(ValueError, match=r"^\"username\" and \"password\" are mandatory to create a user$"):
            # pyright somehow thinks that `is_super_user` field here is `str`, not `bool | None`
            adcm_client.users.new(**wrong_data)  # pyright: ignore[reportArgumentType]

    user = adcm_client.users.new(username=username, password=username * 2)
    assert isinstance(user, LocalUserLazy)
    assert username not in await get_all_usernames(httpx_client)

    with pytest.raises(AttributeError):
        await user.delete()

    email = "naw_mail@mail.com"
    user.email = email

    saved_user = await user.save()
    assert isinstance(saved_user, LocalUser)
    assert saved_user.username in await get_all_usernames(httpx_client)

    assert isinstance(saved_user.id, int)
    assert saved_user.username == username
    assert saved_user.first_name == ""
    assert saved_user.last_name == ""
    assert not saved_user.is_super_user
    assert saved_user.email == email

    firstname = "First_name"
    edited_user = saved_user.edit(first_name=firstname)
    assert isinstance(edited_user, LocalUserLazy)
    with pytest.raises(AttributeError):
        await edited_user.delete()

    saved_user = await edited_user.save()
    assert isinstance(saved_user, LocalUser)
    assert saved_user.username in await get_all_usernames(httpx_client)

    await saved_user.delete()
    assert saved_user.username not in await get_all_usernames(httpx_client)


async def _test_ldap_user_api(user: LDAPUser) -> None:
    assert isinstance(user, LDAPUser)
    assert isinstance(user.id, int)
    assert isinstance(user.username, str)
    assert isinstance(user.first_name, str)
    assert isinstance(user.last_name, str)
    assert isinstance(user.email, str)
    assert isinstance(user.is_super_user, bool)

    with pytest.raises(AttributeError):
        user.edit()

    with pytest.raises(AttributeError):
        user.delete()

    with pytest.raises(AttributeError):
        user.save()


async def _test_users_accessor(
    adcm_client: ADCMClient, httpx_client: AsyncClient, three_groups: tuple[LocalGroup, LocalGroup, LDAPGroup]
) -> None:
    # prepare groups, create users
    local_group_saved, local_group_unsaved, *_ = three_groups
    await local_group_unsaved.save()  # create group
    assert isinstance(local_group_unsaved.id, int)
    groups: dict[str, int] = {group.display_name: group.id for group in (local_group_saved, local_group_unsaved)}  # pyright: ignore[reportAssignmentType]

    await create_51_users(httpx_client=httpx_client, groups=groups)

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
