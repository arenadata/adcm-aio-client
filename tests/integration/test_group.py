from typing import ForwardRef, Optional
import asyncio

from httpx import AsyncClient, Timeout
import pytest
import pytest_asyncio

from adcm_aio_client.client import ADCMClient
from adcm_aio_client.errors import MultipleObjectsReturnedError, ObjectDoesNotExistError
from adcm_aio_client.objects.rbac import group as group_module
from adcm_aio_client.objects.rbac import user as user_module
from adcm_aio_client.objects.rbac._types import LocalGroupData, LocalUserData, SourceType
from tests.integration.setup_environment import DB_USER, ADCMContainer, ADCMPostgresContainer

# pyright: reportAttributeAccessIssue=false

pytestmark = [pytest.mark.asyncio]


async def get_all_group_names(httpx_client: AsyncClient) -> list[dict]:
    response = await httpx_client.get(url="rbac/groups/", params={"limit": 999})
    assert response.status_code == 200

    return [group["displayName"] for group in response.json()["results"]]


async def get_groups_count(httpx_client: AsyncClient) -> int:
    response = await httpx_client.get(url="rbac/groups/", params={"limit": 1})
    assert response.status_code == 200

    return response.json()["count"]


async def create_51_groups(httpx_client: AsyncClient) -> None:
    """Creates 51 groups named grp-1, grp-2, ..., grp-51"""
    requests = []
    for i in range(1, 52, 1):
        name = f"grp-{i}"

        data = {"displayName": name}
        requests.append(httpx_client.post(url="rbac/groups/", data=data, timeout=Timeout(15.0, read=None)))

    await asyncio.gather(*requests, return_exceptions=False)


@pytest_asyncio.fixture()
async def ldap_group(
    adcm_client: ADCMClient, httpx_client: AsyncClient, adcm: ADCMContainer, postgres: ADCMPostgresContainer
) -> group_module.LDAPGroup:
    """Creates a LDAP group with `admin` user"""
    group_name = "LDAP_Group"

    admin = await adcm_client.users.get(username__eq="admin")
    response = await httpx_client.post(
        url="rbac/groups/", data={"display_name": group_name, "description": "ldapgrdesc", "users": [admin.id]}
    )
    assert response.status_code == 201
    id_ = response.json()["id"]

    sql = f"UPDATE rbac_group SET type = '{SourceType.LDAP.value}' WHERE group_ptr_id = {id_};"  # noqa: S608
    postgres.execute_statement(sql, db_user=DB_USER, db_name=adcm._db.name)

    ldap_group = await adcm_client.groups.get(display_name__eq=group_name)
    assert isinstance(ldap_group, group_module.LDAPGroup)
    assert ldap_group._data["type"] == SourceType.LDAP.value

    return ldap_group


@pytest_asyncio.fixture()
async def three_users(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    adcm: ADCMContainer,
    postgres: ADCMPostgresContainer,
) -> tuple[user_module.LocalUser, LocalUserData, user_module.LDAPUser]:
    """Creates three users: local saved, local unsaved, ldap saved (unsaved ldap user can't be instantiated)"""

    url = "rbac/users/"
    username_local = "test_user_saved"
    username_ldap = "test_ldap_user_saved"
    response = await httpx_client.post(
        url=url, data={"username": username_local, "password": username_local * 2}, timeout=Timeout(15.0, read=None)
    )
    assert response.status_code == 201

    response = await httpx_client.post(
        url=url, data={"username": username_ldap, "password": username_ldap * 2}, timeout=Timeout(15.0, read=None)
    )
    assert response.status_code == 201
    ldap_user_id = response.json()["id"]

    sql = f"UPDATE rbac_user SET type = '{SourceType.LDAP.value}' WHERE user_ptr_id = {ldap_user_id};"  # noqa: S608
    postgres.execute_statement(sql, db_user=DB_USER, db_name=adcm._db.name)

    local_user_saved = await adcm_client.users.get(username__eq=username_local)
    assert isinstance(local_user_saved, user_module.LocalUser)
    assert local_user_saved._data["type"] == SourceType.LOCAL.value

    ldap_user_saved = await adcm_client.users.get(username__eq=username_ldap)
    assert isinstance(ldap_user_saved, user_module.LDAPUser)
    assert ldap_user_saved._data["type"] == SourceType.LDAP.value

    local_user_unsaved = user_module.new(username="local_user_unsaved", password="<PASSWORD>")  # noqa: S106

    return local_user_saved, local_user_unsaved, ldap_user_saved


async def test_group(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    ldap_group: group_module.LDAPGroup,
    three_users: tuple[user_module.LocalUser, LocalUserData, user_module.LDAPUser],
) -> None:
    _test_fields_contract()
    await _test_local_group_data_api(adcm_client=adcm_client, httpx_client=httpx_client, three_users=three_users)
    await _test_local_group_lazy_api(adcm_client=adcm_client, httpx_client=httpx_client, three_users=three_users)
    await _test_ldap_group_api(group=ldap_group)
    await _test_groups_node(adcm_client=adcm_client, httpx_client=httpx_client)


def _test_fields_contract() -> None:
    localgroupdata = LocalGroupData.__annotations__
    groupkwargs = group_module._GroupKwargs.__annotations__

    assert localgroupdata.pop("id").__args__ == (int | None,)

    expected_fields = {"display_name", "description", "users"}
    assert set(localgroupdata.keys()) == set(groupkwargs.keys()) == expected_fields

    assert localgroupdata.pop("users").__args__ == (Optional[list[int]],)  # noqa: UP007
    assert groupkwargs.pop("users").__args__ == (
        list[ForwardRef(user_module.LocalUser.__name__) | ForwardRef(user_module.LDAPUser.__name__)],  # noqa: UP007
    )

    for field in localgroupdata:
        kwarg_type = groupkwargs[field].__args__[0]
        localgroupdata_type = localgroupdata[field].__args__
        assert (kwarg_type | None,) == localgroupdata_type, f"{field=}, {kwarg_type=}, {localgroupdata_type=}"


async def _test_local_group_data_api(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    three_users: tuple[user_module.LocalUser, LocalUserData, user_module.LDAPUser],
) -> None:
    local_user, local_user_data, ldap_user = three_users
    group_name = "Test local group"
    assert group_name not in await get_all_group_names(httpx_client)

    with pytest.raises(ValueError, match=f'"display_name" is mandatory to create a {group_module.LocalGroup.__name__}'):
        group_module.new(description="desc")

    group = group_module.new(display_name=group_name)
    description = "New description"
    assert isinstance(group, LocalGroupData)
    group.description = description
    group.users = [local_user.id, ldap_user.id]

    with pytest.raises(AttributeError):
        await group.save()

    with pytest.raises(AttributeError):
        await group.delete()

    local_group = await adcm_client.groups.init(group)

    assert isinstance(local_group, group_module.LocalGroup)
    assert local_group.display_name in await get_all_group_names(httpx_client)

    assert isinstance(local_group.id, int)
    assert local_group.display_name == group_name
    assert local_group.description == description
    users = await local_group.users
    assert isinstance(users, list)
    assert len(users) == 2
    assert {u.__class__ for u in users} == {user_module.LocalUser, user_module.LDAPUser}
    assert {u.id for u in users} == {local_user.id, ldap_user.id}

    new_name = "New group name"
    assert new_name not in await get_all_group_names(httpx_client)

    with pytest.raises(ValueError, match='"users" must be of type LocalUser | LDAPUser'):
        local_group.edit(display_name=new_name, users=[local_user_data])  # pyright: ignore[reportArgumentType]

    edited_group = local_group.edit(display_name=new_name, users=[local_user])
    assert isinstance(edited_group, group_module.LocalGroupLazy)
    with pytest.raises(AttributeError):
        await edited_group.delete()

    saved_group = await edited_group.save()
    assert isinstance(saved_group, group_module.LocalGroup)
    assert saved_group.display_name in await get_all_group_names(httpx_client)
    users = await saved_group.users
    assert isinstance(users, list)
    assert len(users) == 1
    assert isinstance(users[0], user_module.LocalUser)
    assert users[0].id == local_user.id

    await saved_group.delete()
    assert saved_group.display_name not in await get_all_group_names(httpx_client)


async def _test_local_group_lazy_api(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    three_users: tuple[user_module.LocalUser, LocalUserData, user_module.LDAPUser],
) -> None:
    local_user, local_user_data, ldap_user = three_users
    group_name = "Test_local_group_from_node"
    assert group_name not in await get_all_group_names(httpx_client)

    with pytest.raises(ValueError, match=f'"display_name" is mandatory to create a {group_module.LocalGroup.__name__}'):
        adcm_client.groups.new(description="desc")

    with pytest.raises(ValueError, match='"users" must be of type LocalUser | LDAPUser'):
        adcm_client.groups.new(display_name=group_name, users=[local_user_data])  # pyright: ignore[reportArgumentType]

    group = adcm_client.groups.new(display_name=group_name, users=[local_user, ldap_user])
    assert isinstance(group, group_module.LocalGroupLazy)
    assert group_name not in await get_all_group_names(httpx_client)

    with pytest.raises(AttributeError):
        await group.delete()

    description = "aaaaaaa!"
    group.description = description

    saved_group = await group.save()
    assert isinstance(saved_group, group_module.LocalGroup)
    assert saved_group.display_name in await get_all_group_names(httpx_client)

    assert isinstance(saved_group.id, int)
    assert saved_group.display_name == group_name
    assert saved_group.description == description
    users = await saved_group.users
    assert isinstance(users, list)
    assert len(users) == 2
    assert {u.__class__ for u in users} == {user_module.LocalUser, user_module.LDAPUser}
    assert {u.id for u in users} == {local_user.id, ldap_user.id}

    new_name = "New group name"
    edited_group = saved_group.edit(display_name=new_name, users=[ldap_user])
    assert isinstance(edited_group, group_module.LocalGroupLazy)
    with pytest.raises(AttributeError):
        await edited_group.delete()

    saved_group = await edited_group.save()
    assert isinstance(saved_group, group_module.LocalGroup)
    assert saved_group.display_name == new_name
    assert new_name in await get_all_group_names(httpx_client)
    users = await saved_group.users
    assert isinstance(users, list)
    assert len(users) == 1
    assert isinstance(users[0], user_module.LDAPUser)
    assert users[0].id == ldap_user.id

    await saved_group.delete()
    assert saved_group.display_name not in await get_all_group_names(httpx_client)


async def _test_ldap_group_api(group: group_module.LDAPGroup) -> None:
    assert isinstance(group, group_module.LDAPGroup)
    assert isinstance(group.id, int)
    assert isinstance(group.display_name, str)
    assert isinstance(group.description, str)
    assert isinstance(await group.users, list)

    with pytest.raises(AttributeError):
        group.edit()

    with pytest.raises(AttributeError):
        group.delete()

    with pytest.raises(AttributeError):
        group.save()


async def _test_groups_node(adcm_client: ADCMClient, httpx_client: AsyncClient) -> None:
    await create_51_groups(httpx_client=httpx_client)
    num_groups = await get_groups_count(httpx_client=httpx_client)
    no_objects_msg = "^No objects found with the given filter.$"
    multiple_objects_msg = "^More than one object found.$"

    # get
    assert isinstance(await adcm_client.groups.get(display_name__eq="grp-1"), group_module.LocalGroup)

    with pytest.raises(ObjectDoesNotExistError, match=no_objects_msg):
        await adcm_client.groups.get(display_name__eq="grp-999")

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await adcm_client.groups.get(display_name__in=["grp-1", "grp-2"])

    # get_or_none
    assert isinstance(await adcm_client.groups.get_or_none(display_name__eq="grp-3"), group_module.LocalGroup)

    assert await adcm_client.groups.get_or_none(display_name__eq="NotAGroup") is None

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await adcm_client.groups.get_or_none(display_name__in=["grp-44", "grp-45"])

    # all
    all_groups = await adcm_client.groups.all()
    assert all(isinstance(group, group_module.LocalGroup | group_module.LDAPGroup) for group in all_groups)
    assert len({group.id for group in all_groups}) == num_groups
    assert len({id(group) for group in all_groups}) == num_groups

    # list
    page_size = 50
    assert page_size < num_groups, "check page_size or number of groups"

    first_page_groups = await adcm_client.groups.list()
    assert len({group.id for group in first_page_groups}) == page_size
    assert len({id(group) for group in first_page_groups}) == page_size

    # iter
    iter_groups = []
    async for group in adcm_client.groups.iter():
        iter_groups.append(group)
    assert len(iter_groups) == num_groups
    assert len({group.id for group in iter_groups}) == num_groups
    assert len({id(group) for group in iter_groups}) == num_groups

    # filter
    filters_data = (
        ("display_name__eq", ("grp-2", 1)),
        ("display_name__ne", ("grp-2", num_groups - 1)),
        ("display_name__in", (["grp-15", "grp-16", "grp-17"], 3)),
        ("display_name__exclude", (["grp-15", "grp-16", "grp-17"], num_groups - 3)),
        ("display_name__ieq", ("GRP-3", 1)),
        ("display_name__ine", ("GRP-2", num_groups - 1)),
        ("display_name__iin", (["Grp-1", "gRp-2", "grP-3"], 3)),
        ("display_name__iexclude", (["Grp-1", "gRp-2", "grP-3"], num_groups - 3)),
        ("display_name__contains", ("grp-", 51)),
        ("display_name__icontains", ("GRp-", 51)),
    )

    for filter_key, (filter_value, expected) in filters_data:
        filter_dict = {filter_key: filter_value}
        groups = await adcm_client.groups.filter(**filter_dict)
        assert len(groups) == expected, f"Filter: {filter_dict}"
