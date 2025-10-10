import re
import asyncio

from httpx import AsyncClient, Timeout
import pytest
import pytest_asyncio

from adcm_aio_client._types import EntitySourceType
from adcm_aio_client.client import ADCMClient
from adcm_aio_client.errors import MultipleObjectsReturnedError, ObjectDoesNotExistError
from adcm_aio_client.objects import LDAPGroup, LDAPUser, LocalGroup, LocalUser
from tests.integration.setup_environment import DB_USER, ADCMContainer, ADCMPostgresContainer

pytestmark = [pytest.mark.asyncio]


# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false


async def get_all_groups(httpx_client: AsyncClient) -> list[dict]:
    response = await httpx_client.get(url="rbac/groups/", params={"limit": 999})
    assert response.status_code == 200

    return response.json()["results"]


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
) -> LDAPGroup:
    """Creates a LDAP group with `admin` user"""
    group_name = "LDAP_Group"

    admin = await adcm_client.users.get(username__eq="admin")
    response = await httpx_client.post(
        url="rbac/groups/", data={"display_name": group_name, "description": "ldapgrdesc", "users": [admin.id]}
    )
    assert response.status_code == 201
    id_ = response.json()["id"]

    sql = f"UPDATE rbac_group SET type = '{EntitySourceType.LDAP.value}' WHERE group_ptr_id = {id_};"  # noqa: S608
    postgres.execute_statement(sql, db_user=DB_USER, db_name=adcm._db.name)

    ldap_group = await adcm_client.groups.get(display_name__eq=group_name)
    assert isinstance(ldap_group, LDAPGroup)
    assert ldap_group._data["type"] == EntitySourceType.LDAP.value

    return ldap_group


@pytest_asyncio.fixture()
async def three_users(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    adcm: ADCMContainer,
    postgres: ADCMPostgresContainer,
) -> tuple[LocalUser, LocalUser, LDAPUser]:
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

    sql = f"UPDATE rbac_user SET type = '{EntitySourceType.LDAP.value}' WHERE user_ptr_id = {ldap_user_id};"  # noqa: S608
    postgres.execute_statement(sql, db_user=DB_USER, db_name=adcm._db.name)

    local_user_saved = await adcm_client.users.get(username__eq=username_local)
    assert isinstance(local_user_saved, LocalUser)
    assert local_user_saved._data["type"] == EntitySourceType.LOCAL.value

    ldap_user_saved = await adcm_client.users.get(username__eq=username_ldap)
    assert isinstance(ldap_user_saved, LDAPUser)
    assert ldap_user_saved._data["type"] == EntitySourceType.LDAP.value

    local_user_unsaved = LocalUser(client=adcm_client, username="local_user_unsaved", password="<PASSWORD>")  # noqa: S106

    return local_user_saved, local_user_unsaved, ldap_user_saved


async def test_group(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    ldap_group: LDAPGroup,
    three_users: tuple[LocalUser, LocalUser, LDAPUser],
) -> None:
    await _test_object_api(
        adcm_client=adcm_client, httpx_client=httpx_client, ldap_group=ldap_group, three_users=three_users
    )

    await create_51_groups(httpx_client=httpx_client)
    await _test_groups_node(adcm_client=adcm_client, httpx_client=httpx_client)


async def _test_object_api(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    ldap_group: LDAPGroup,
    three_users: tuple[LocalUser, LocalUser, LDAPUser],
) -> None:
    group_name = "New group"
    assert group_name not in (g["displayName"] for g in await get_all_groups(httpx_client))

    create_data = {"display_name": group_name, "description": "description"}

    with pytest.raises(NotImplementedError):
        LDAPGroup(client=adcm_client, **create_data)

    with pytest.raises(AttributeError):
        await ldap_group.delete()

    assert isinstance(ldap_group.id, int)
    assert ldap_group.display_name == "LDAP_Group"
    assert ldap_group.description == "ldapgrdesc"
    ldap_group_users = await ldap_group.users
    assert len(ldap_group_users) == 1
    assert isinstance(ldap_group_users[0], LocalUser)
    assert ldap_group_users[0].username == "admin"

    local_group = LocalGroup(client=adcm_client, **create_data)

    assert local_group.id is None
    assert local_group.display_name == group_name
    assert local_group.description == create_data["description"]
    local_group_users = await local_group.users
    assert isinstance(local_group_users, list)
    assert len(local_group_users) == 0

    await local_group.save()
    await local_group.refresh()

    assert isinstance(local_group.id, int)
    assert local_group.display_name == group_name
    assert local_group.description == create_data["description"]
    local_group_users = await local_group.users
    assert isinstance(local_group_users, list)
    assert len(local_group_users) == 0
    assert group_name in (g["displayName"] for g in await get_all_groups(httpx_client))

    await _test_group_update(
        local_group=local_group, ldap_group=ldap_group, three_users=three_users, httpx_client=httpx_client
    )

    local_group_id = local_group.id
    await local_group.delete()
    assert local_group_id not in (g["id"] for g in await get_all_groups(httpx_client))


async def _test_group_update(
    local_group: LocalGroup,
    ldap_group: LDAPGroup,
    three_users: tuple[LocalUser, LocalUser, LDAPUser],
    httpx_client: AsyncClient,
) -> None:
    user_local_saved, user_local_unsaved, user_ldap_saved = three_users
    initial_groups_count = await get_groups_count(httpx_client=httpx_client)

    # update ldap group
    with pytest.raises(AttributeError):
        ldap_group.id = 9

    with pytest.raises(AttributeError):
        ldap_group.display_name = "new name"

    with pytest.raises(AttributeError):
        ldap_group.description = "new description"

    with pytest.raises(AttributeError, match="`users` attribute is not mutable"):
        ldap_group.users = [user_local_saved]

    # update local group
    remote_local_group = [
        group for group in await get_all_groups(httpx_client) if group["displayName"] == local_group.display_name
    ][0]
    assert remote_local_group["users"] == [] == await local_group.users

    with pytest.raises(AttributeError):
        local_group.id = 9

    new_display_name, new_description = "new_display_name", "new_description"
    assert local_group._manually_set == set()

    local_group.display_name = new_display_name
    local_group.description = new_description

    assert local_group._manually_set == {"displayName", "description"}
    assert local_group._data["displayName"] == new_display_name
    assert local_group._data["description"] == new_description

    with pytest.raises(ValueError, match="All users must be saved before assigning them to group"):
        local_group.users = [user_local_saved, user_local_unsaved]

    with pytest.raises(
        ValueError, match=re.escape(f"All users must be {LocalUser.__name__} or {LDAPUser.__name__}, got [{int}]")
    ):
        local_group.users = [user_local_saved, 8]

    assert local_group._manually_set == {"displayName", "description"}

    local_group.users = [user_local_saved, user_ldap_saved]
    assert local_group._manually_set == {"displayName", "description", "users"}
    assert local_group._data["users"] == [{"id": u.id} for u in [user_local_saved, user_ldap_saved]]

    await local_group.save()
    assert local_group._manually_set == set()

    remote_local_group = [
        group for group in await get_all_groups(httpx_client) if group["displayName"] == new_display_name
    ][0]
    remote_user_ids = {u["id"] for u in remote_local_group["users"]}
    expected_user_ids = {user_local_saved.id, user_ldap_saved.id}
    retrieved_user_ids = {u.id for u in await local_group.users}

    assert remote_user_ids == expected_user_ids
    assert retrieved_user_ids == set()  # before .refresh() user changes is not shown (value cached)
    assert remote_local_group["displayName"] == new_display_name == local_group.display_name
    assert remote_local_group["description"] == new_description == local_group.description

    await local_group.refresh()
    assert local_group._manually_set == set()
    retrieved_user_ids = {u.id for u in await local_group.users}

    assert remote_user_ids == expected_user_ids == retrieved_user_ids
    assert remote_local_group["displayName"] == new_display_name == local_group.display_name
    assert remote_local_group["description"] == new_description == local_group.description

    assert await get_groups_count(httpx_client=httpx_client) == initial_groups_count


async def _test_groups_node(adcm_client: ADCMClient, httpx_client: AsyncClient) -> None:
    num_groups = await get_groups_count(httpx_client=httpx_client)
    no_objects_msg = "^No objects found with the given filter.$"
    multiple_objects_msg = "^More than one object found.$"

    # get
    assert isinstance(await adcm_client.groups.get(display_name__eq="grp-1"), LocalGroup)

    with pytest.raises(ObjectDoesNotExistError, match=no_objects_msg):
        await adcm_client.groups.get(display_name__eq="grp-999")

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await adcm_client.groups.get(display_name__in=["grp-1", "grp-2"])

    # get_or_none
    assert isinstance(await adcm_client.groups.get_or_none(display_name__eq="grp-3"), LocalGroup)

    assert await adcm_client.groups.get_or_none(display_name__eq="NotAGroup") is None

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await adcm_client.groups.get_or_none(display_name__in=["grp-44", "grp-45"])

    # all
    all_groups = await adcm_client.groups.all()
    assert all(isinstance(group, LocalGroup | LDAPGroup) for group in all_groups)
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
    async for user in adcm_client.groups.iter():
        iter_groups.append(user)
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
