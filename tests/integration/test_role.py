from typing import cast
import asyncio

from httpx import AsyncClient, Timeout
import pytest

from adcm_aio_client.client import ADCMClient
from adcm_aio_client.errors import MultipleObjectsReturnedError, ObjectDoesNotExistError
from adcm_aio_client.objects import BuiltInRole, CustomRole, Permission

pytestmark = [pytest.mark.asyncio]


async def create_51_custom_role(httpx_client: AsyncClient) -> None:
    response = await httpx_client.get("rbac/roles/", params={"type": "business", "displayName__eq": "Create cluster"})
    assert response.status_code == 200

    child_id = response.json()["results"][0]["id"]
    requests = []
    for i in range(1, 52, 1):
        data = {"displayName": f"Custom role {i}", "children": [child_id]}
        requests.append(httpx_client.post(url="rbac/roles/", data=data, timeout=Timeout(15.0, read=None)))

    await asyncio.gather(*requests, return_exceptions=False)


async def get_roles_count(httpx_client: AsyncClient, **kwargs: str) -> int:
    response = await httpx_client.get(url="rbac/roles/", params={"limit": 1, **kwargs})
    assert response.status_code == 200

    return int(response.json()["count"])


async def assert_role(role: CustomRole, expected: dict, httpx_client: AsyncClient) -> None:
    response = await httpx_client.get(f"rbac/roles/{role.id}/")
    assert response.status_code == 200

    response = response.json()
    for attr, value in expected.items():
        assert response[attr] == value


async def test_role(adcm_client: ADCMClient, httpx_client: AsyncClient) -> None:
    await _test_create_delete_api(adcm_client, httpx_client)
    await _test_roles_node(adcm_client, httpx_client)


async def _test_create_delete_api(adcm_client: ADCMClient, httpx_client: AsyncClient) -> None:
    permission = cast(Permission, await adcm_client.permissions.get(display_name__eq="Create cluster"))
    with pytest.raises(AttributeError):
        await permission.delete()  # pyright: ignore[reportAttributeAccessIssue]

    role = await adcm_client.roles.create(display_name="Test role", permissions=[permission], description="123")

    assert isinstance(role, CustomRole)
    expected = {
        "id": role.id,
        "name": role.display_name,
        "displayName": role.display_name,
        "isBuiltIn": False,
        "isAnyCategory": False,
        "categories": [],
        "type": "role",
        "parametrizedByType": [],
        "description": "123",
        "children": [
            {
                "id": permission.id,
                "name": permission.name,
                "displayName": permission.display_name,
                "isBuiltIn": True,
                "isAnyCategory": False,
                "categories": [],
                "type": "business",
            }
        ],
    }
    await assert_role(role, expected, httpx_client)

    await role.delete()
    response = await httpx_client.get(f"rbac/roles/{role.id}/")
    assert response.status_code == 404

    builtin_role = await adcm_client.roles.get(display_name__eq="Cluster Administrator")
    with pytest.raises(AttributeError):
        await builtin_role.delete()  # pyright: ignore[reportAttributeAccessIssue]


async def _test_roles_node(adcm_client: ADCMClient, httpx_client: AsyncClient) -> None:
    await create_51_custom_role(httpx_client)

    num_roles = await get_roles_count(httpx_client=httpx_client, type="role")
    num_permissions = await get_roles_count(httpx_client=httpx_client, type="business")
    no_objects_msg = "^No objects found with the given filter.$"
    multiple_objects_msg = "^More than one object found.$"

    # get role
    assert isinstance(await adcm_client.roles.get(display_name__eq="Cluster Administrator"), BuiltInRole)

    with pytest.raises(ObjectDoesNotExistError, match=no_objects_msg):
        await adcm_client.roles.get(display_name__eq="ADCM Admin")

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await adcm_client.roles.get(display_name__in=["Cluster Administrator", "Service Administrator"])

    # get permission
    assert isinstance(await adcm_client.permissions.get(display_name__eq="Create cluster"), Permission)

    with pytest.raises(ObjectDoesNotExistError, match=no_objects_msg):
        await adcm_client.permissions.get(display_name__eq="Create something")

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await adcm_client.permissions.get(display_name__in=["Create cluster", "View audit logins"])

    # get_or_none roles
    assert isinstance(await adcm_client.roles.get_or_none(display_name__eq="Service Administrator"), BuiltInRole)

    assert await adcm_client.roles.get_or_none(display_name__eq="NotARole") is None

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await adcm_client.roles.get_or_none(display_name__in=["Cluster Administrator", "Service Administrator"])

    # get_or_none permissions
    assert isinstance(await adcm_client.permissions.get_or_none(display_name__eq="View audit logins"), Permission)

    assert await adcm_client.permissions.get_or_none(display_name__eq="NotAPermission") is None

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await adcm_client.permissions.get_or_none(display_name__in=["Create cluster", "View audit logins"])

    # all roles
    all_roles = await adcm_client.roles.all()
    assert all(isinstance(role, BuiltInRole | CustomRole) for role in all_roles)
    assert len({role.id for role in all_roles}) == num_roles
    assert len({id(role) for role in all_roles}) == num_roles

    # all permissions
    all_permissions = await adcm_client.permissions.all()
    assert all(isinstance(permission, Permission) for permission in all_permissions)
    assert len({permission.id for permission in all_permissions}) == num_permissions
    assert len({id(permission) for permission in all_permissions}) == num_permissions

    page_size = 50
    # list roles
    assert page_size < num_roles, "check page_size or number of roles"

    first_page_roles = await adcm_client.roles.list()
    assert len({role.id for role in first_page_roles}) == page_size
    assert len({id(role) for role in first_page_roles}) == page_size

    # list permissions
    assert page_size < num_permissions, "check page_size or number of permissions"

    first_page_permissions = await adcm_client.permissions.list()
    assert len({permission.id for permission in first_page_permissions}) == page_size
    assert len({id(permission) for permission in first_page_permissions}) == page_size

    # iter roles
    iter_roles = []
    async for role in adcm_client.roles.iter():
        iter_roles.append(role)
    assert len(iter_roles) == num_roles
    assert len({role.id for role in iter_roles}) == num_roles
    assert len({id(role) for role in iter_roles}) == num_roles

    # iter permissions
    iter_permissions = []
    async for role in adcm_client.permissions.iter():
        iter_permissions.append(role)
    assert len(iter_permissions) == num_permissions
    assert len({permission.id for permission in iter_permissions}) == num_permissions
    assert len({id(permission) for permission in iter_permissions}) == num_permissions

    # filter roles
    _filters_data_by_name = (
        ("name__eq", ("Cluster Administrator", 1)),
        ("name__ne", ("Cluster Administrator", num_roles - 1)),
        ("name__in", (["Cluster Administrator", "Service Administrator", "Provider Administrator"], 3)),
        (
            "name__exclude",
            (["Cluster Administrator", "Service Administrator", "Provider Administrator"], num_roles - 3),
        ),
        ("name__ieq", ("ADCM USER", 1)),
        ("name__ine", ("adcm User", num_roles - 1)),
        ("name__iin", (["Cluster ADMINISTRATOR", "Service ADMINISTRATOR", "Provider ADMINISTRATOR"], 3)),
        (
            "name__iexclude",
            (["Cluster Administrator", "Service ADMINISTRATOR", "Provider ADMINISTRATOR"], num_roles - 3),
        ),
        ("name__contains", ("ADMINISTRATOR", 0)),
        ("name__icontains", ("ADMINISTRATOR", 3)),
    )
    filters_data_roles = (
        *((f"display_{filter_}", value) for filter_, value in _filters_data_by_name),
        *_filters_data_by_name,
    )

    for filter_key, (filter_value, expected) in filters_data_roles:
        filter_dict = {filter_key: filter_value}
        role = await adcm_client.roles.filter(**filter_dict)
        assert len(role) == expected, f"Role filter: {filter_dict}"

    # filter permissions
    _permission_filter_values = (
        ("Create cluster", 1),
        ("Create cluster", num_permissions - 1),
        (["Create cluster", "View audit logins", "Add service"], 3),
        (["Create cluster", "View audit logins", "Add service"], num_permissions - 3),
        ("CREATE CLUSTER", 1),
        ("CREATE CLUSTER", num_permissions - 1),
        (["CREATE CLUSTER", "VIEW AUDIT LOGINS", "ADD SERVICE"], 3),
        (["CREATE CLUSTER", "VIEW AUDIT LOGINS", "ADD SERVICE"], num_permissions - 3),
        ("adcm", 0),
        ("adcm", 1),  # Edit ADCM settings
    ) * 2
    filters_data_permissions = (
        (role_filter[0], new_fvalue)
        for role_filter, new_fvalue in zip(filters_data_roles, _permission_filter_values, strict=True)
    )

    for filter_key, (filter_value, expected) in filters_data_permissions:
        filter_dict = {filter_key: filter_value}
        role = await adcm_client.permissions.filter(**filter_dict)
        assert len(role) == expected, f"Permission filter: {filter_dict}"
