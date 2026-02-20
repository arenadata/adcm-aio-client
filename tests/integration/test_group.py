import asyncio

from httpx import AsyncClient, Timeout
import pytest
import pytest_asyncio

from adcm_aio_client._types import EntitySourceType
from adcm_aio_client.client import ADCMClient
from adcm_aio_client.errors import MultipleObjectsReturnedError, ObjectCreationError, ObjectDoesNotExistError
from adcm_aio_client.objects import LDAPGroup, LocalGroup, LocalUser
from tests.integration.setup_environment import DB_USER, ADCMContainer, ADCMPostgresContainer

pytestmark = [pytest.mark.asyncio]


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


async def assert_group(group: LocalGroup, expected: dict, httpx_client: AsyncClient) -> None:
    response = await httpx_client.get(f"rbac/groups/{group.id}/")
    assert response.status_code == 200

    response = response.json()
    for attr, value in expected.items():
        assert response[attr] == value


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
async def local_user(adcm_client: ADCMClient, httpx_client: AsyncClient) -> LocalUser:
    username = "test_local_user"
    response = await httpx_client.post(
        url="rbac/users/", data={"username": username, "password": username * 2}, timeout=Timeout(15.0, read=None)
    )
    assert response.status_code == 201

    user = await adcm_client.users.get(username__eq=username)
    assert isinstance(user, LocalUser)

    return user


async def test_group(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    ldap_group: LDAPGroup,
    local_user: LocalUser,
) -> None:
    await _test_create_delete_api(
        adcm_client=adcm_client, httpx_client=httpx_client, ldap_group=ldap_group, local_user=local_user
    )

    await _test_groups_node(adcm_client=adcm_client, httpx_client=httpx_client)


async def _test_create_delete_api(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    ldap_group: LDAPGroup,
    local_user: LocalUser,
) -> None:
    name = "Test-group"
    group = await adcm_client.groups.create(display_name=name, users=[local_user])

    assert isinstance(group, LocalGroup)
    expected = {
        "id": group.id,
        "name": f"{name} [local]",
        "displayName": name,
        "description": "",
        "users": [{"id": local_user.id, "username": local_user.username}],
        "type": "local",
    }
    await assert_group(group, expected, httpx_client)

    # create duplicate
    with pytest.raises(ObjectCreationError, match="rbac/groups: .*GROUP_CREATE_ERROR"):
        await adcm_client.groups.create(display_name=name)

    await group.delete()
    response = await httpx_client.get(f"rbac/groups/{group.id}/")
    assert response.status_code == 404

    with pytest.raises(AttributeError):
        await ldap_group.delete()  # pyright: ignore[reportAttributeAccessIssue]


async def _test_groups_node(adcm_client: ADCMClient, httpx_client: AsyncClient) -> None:
    await create_51_groups(httpx_client=httpx_client)
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
