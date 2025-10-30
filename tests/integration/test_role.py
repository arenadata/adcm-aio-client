from typing import cast

from httpx import AsyncClient, Timeout
import pytest
import pytest_asyncio

from adcm_aio_client.client import ADCMClient
from adcm_aio_client.errors import MultipleObjectsReturnedError, ObjectDoesNotExistError
from adcm_aio_client.objects.rbac import role as role_module
from adcm_aio_client.objects.rbac._types import CustomRoleData

# pyright: reportAttributeAccessIssue=false


pytestmark = [pytest.mark.asyncio]


async def get_roles_display_names(httpx_client: AsyncClient, **kwargs: str) -> list[str]:
    response = await httpx_client.get(url="rbac/roles/", params={"limit": 999, **kwargs})
    assert response.status_code == 200

    return [role["displayName"] for role in response.json()["results"]]


async def get_roles_count(httpx_client: AsyncClient, **kwargs: str) -> int:
    response = await httpx_client.get(url="rbac/roles/", params={"limit": 1, **kwargs})
    assert response.status_code == 200

    return response.json()["count"]


@pytest_asyncio.fixture()
async def three_roles_and_permission(
    adcm_client: ADCMClient, httpx_client: AsyncClient
) -> tuple[role_module.BuiltInRole, role_module.CustomRole, CustomRoleData, role_module.Permission]:
    """
    Returns 4 roles:
        - builtin role (builtin `role` role)
        - custom role
        - custom role unsaved
        - permission (builtin `business` role)
    """

    builtin_role = await adcm_client.roles.get(display_name__eq="Cluster Administrator")
    assert isinstance(builtin_role, role_module.BuiltInRole)

    response = await httpx_client.get("rbac/roles/", params={"type": "business", "displayName__eq": "Create cluster"})
    assert response.status_code == 200
    child_id = response.json()["results"][0]["id"]
    data = {"displayName": "Handmade role", "children": [child_id]}
    response = await httpx_client.post(url="rbac/roles/", data=data, timeout=Timeout(15.0, read=None))
    assert response.status_code == 201

    custom_role = await adcm_client.roles.get(display_name__eq="Handmade role")
    assert isinstance(custom_role, role_module.CustomRole)

    permission = await adcm_client.permissions.get(name__eq="Create cluster")
    assert isinstance(permission, role_module.Permission)

    custom_role_unsaved = role_module.new(
        display_name="Handmade role with create cluster permission",
        permissions=[permission],
    )
    assert isinstance(custom_role_unsaved, CustomRoleData)

    return builtin_role, custom_role, custom_role_unsaved, permission


async def test_role(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    three_roles_and_permission: tuple[
        role_module.BuiltInRole, role_module.CustomRole, CustomRoleData, role_module.Permission
    ],
) -> None:
    _test_fields_contract()
    await _test_custom_role_data_api(
        adcm_client=adcm_client, httpx_client=httpx_client, roles=three_roles_and_permission
    )
    await _test_custom_role_lazy_api(
        adcm_client=adcm_client, httpx_client=httpx_client, roles=three_roles_and_permission
    )
    await _test_builtin_role_api(adcm_client=adcm_client)
    await _test_permission_api(adcm_client=adcm_client)
    # await _test_roles_node(adcm_client=adcm_client, httpx_client=httpx_client)


def _test_fields_contract() -> None:
    customroledata = CustomRoleData.__annotations__
    rolekwargs = role_module._RoleKwargs.__annotations__

    assert customroledata.pop("id").__args__ == (int | None,)

    expected_fields = {"name", "display_name", "description", "permissions"}
    assert set(customroledata.keys()) == set(rolekwargs.keys()) == expected_fields

    assert customroledata.pop("permissions").__args__ == (list[int] | None,)
    assert rolekwargs.pop("permissions").__args__ == (list[role_module.Permission.__name__],)

    for field in rolekwargs:
        kwarg_type = rolekwargs[field].__args__[0]
        customroledata_type = customroledata[field].__args__
        assert (kwarg_type | None,) == customroledata_type, f"{field=}, {kwarg_type=}, {customroledata_type=}"


async def _test_custom_role_data_api(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    roles: tuple[role_module.BuiltInRole, role_module.CustomRole, CustomRoleData, role_module.Permission],
) -> None:
    builtin_role, custom_role, custom_role_unsaved, permission = roles
    role_name = "New custom role"
    assert role_name not in await get_roles_display_names(httpx_client)

    for wrong_data in ({"display_name": role_name}, {"permissions": [permission]}):
        with pytest.raises(
            ValueError,
            match=f'"display_name" and "permissions" are mandatory to create a {role_module.CustomRole.__name__}',
        ):
            # pyright did not parse wrong_data and throws incorrect errors here
            role_module.new(**wrong_data)  # pyright: ignore[reportArgumentType]

    role = role_module.new(display_name=role_name, permissions=[permission])
    description = "New description"
    assert isinstance(role, CustomRoleData)
    role.description = description

    with pytest.raises(AttributeError):
        await role.save()

    with pytest.raises(AttributeError):
        await role.delete()

    custom_role = await adcm_client.roles.init(role)

    assert isinstance(custom_role, role_module.CustomRole)
    assert custom_role.display_name in await get_roles_display_names(httpx_client)

    assert isinstance(custom_role.id, int)
    assert custom_role.name == role_name
    assert custom_role.display_name == role_name
    assert custom_role.description == description
    permissions = custom_role.permissions
    assert isinstance(permissions, list)
    assert len(permissions) == 1
    assert isinstance(permissions[0], role_module.Permission)
    assert permissions[0].id == permission.id

    new_name = "New custom role name"
    assert new_name not in await get_roles_display_names(httpx_client)

    with pytest.raises(ValueError, match=f'"permissions" must be of type {role_module.Permission.__name__}'):
        custom_role.edit(display_name=new_name, permissions=[custom_role_unsaved])  # pyright: ignore[reportArgumentType]

    new_permission = cast(role_module.Permission, await adcm_client.permissions.get(display_name__eq="Add service"))
    edited_role = custom_role.edit(display_name=new_name, permissions=[new_permission])
    assert isinstance(edited_role, role_module.CustomRoleLazy)
    with pytest.raises(AttributeError):
        await edited_role.delete()

    saved_role = await edited_role.save()
    assert isinstance(saved_role, role_module.CustomRole)
    assert saved_role.display_name in await get_roles_display_names(httpx_client)
    permissions = saved_role.permissions
    assert isinstance(permissions, list)
    assert len(permissions) == 1
    assert isinstance(permissions[0], role_module.Permission)
    assert permissions[0].id == new_permission.id

    await saved_role.delete()
    assert saved_role.display_name not in await get_roles_display_names(httpx_client)


async def _test_custom_role_lazy_api(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    roles: tuple[role_module.BuiltInRole, role_module.CustomRole, CustomRoleData, role_module.Permission],
) -> None:
    builtin_role, custom_role, custom_role_unsaved, permission = roles
    role_name = "New_custom_role_from_node"
    assert role_name not in await get_roles_display_names(httpx_client)

    for wrong_data in ({"display_name": role_name}, {"permissions": [permission]}):
        with pytest.raises(
            ValueError,
            match=f'"display_name" and "permissions" are mandatory to create a {role_module.CustomRole.__name__}',
        ):
            # pyright did not parse wrong_data and throws incorrect errors here
            adcm_client.roles.new(**wrong_data)  # pyright: ignore[reportArgumentType]

    with pytest.raises(ValueError, match=f'"permissions" must be of type {role_module.Permission.__name__}'):
        adcm_client.roles.new(display_name=role_name, permissions=[custom_role_unsaved])  # pyright: ignore[reportArgumentType]

    role = adcm_client.roles.new(display_name=role_name, permissions=[permission])
    assert isinstance(role, role_module.CustomRoleLazy)
    assert role_name not in await get_roles_display_names(httpx_client)

    with pytest.raises(AttributeError):
        await role.delete()

    description = "role description"
    role.description = description

    saved_role = await role.save()
    assert isinstance(saved_role, role_module.CustomRole)
    assert saved_role.display_name in await get_roles_display_names(httpx_client)

    assert isinstance(saved_role.id, int)
    assert saved_role.name == role_name
    assert saved_role.display_name == role_name
    assert saved_role.description == description
    permissions = saved_role.permissions
    assert isinstance(permissions, list)
    assert len(permissions) == 1
    assert isinstance(permissions[0], role_module.Permission)
    assert permissions[0].id == permission.id

    new_name = f"New{role_name}"
    edited_role = saved_role.edit(display_name=new_name)
    assert isinstance(edited_role, role_module.CustomRoleLazy)
    with pytest.raises(AttributeError):
        await edited_role.delete()

    saved_role = await edited_role.save()
    assert new_name in await get_roles_display_names(httpx_client)
    assert isinstance(saved_role, role_module.CustomRole)
    assert saved_role.display_name == new_name
    assert saved_role.name == role_name
    permissions = saved_role.permissions
    assert isinstance(permissions, list)
    assert len(permissions) == 1
    assert isinstance(permissions[0], role_module.Permission)
    assert permissions[0].id == permission.id

    await saved_role.delete()
    assert saved_role.display_name not in await get_roles_display_names(httpx_client)


async def _test_builtin_role_api(adcm_client: ADCMClient) -> None:
    builtin_role = await adcm_client.roles.get(display_name__eq="ADCM Auditor")

    assert isinstance(builtin_role, role_module.BuiltInRole)
    assert isinstance(builtin_role.id, int)
    assert isinstance(builtin_role.name, str)
    assert isinstance(builtin_role.display_name, str)
    assert isinstance(builtin_role.description, str)
    assert isinstance(builtin_role.permissions, list)

    with pytest.raises(AttributeError):
        builtin_role.edit()

    with pytest.raises(AttributeError):
        builtin_role.delete()

    with pytest.raises(AttributeError):
        builtin_role.save()


async def _test_permission_api(adcm_client: ADCMClient) -> None:
    permission = await adcm_client.permissions.get(name__eq="Map hosts")

    assert isinstance(permission, role_module.Permission)
    assert isinstance(permission.id, int)
    assert isinstance(permission.name, str)
    assert isinstance(permission.display_name, str)

    with pytest.raises(AttributeError):
        permission.edit()

    with pytest.raises(AttributeError):
        permission.delete()

    with pytest.raises(AttributeError):
        permission.save()


async def _test_roles_permissions_node(adcm_client: ADCMClient, httpx_client: AsyncClient) -> None:
    num_roles = await get_roles_count(httpx_client=httpx_client, type="role")
    num_permissions = await get_roles_count(httpx_client=httpx_client, type="business")
    no_objects_msg = "^No objects found with the given filter.$"
    multiple_objects_msg = "^More than one object found.$"

    # get role
    assert isinstance(await adcm_client.roles.get(display_name__eq="Cluster Administrator"), role_module.BuiltInRole)

    with pytest.raises(ObjectDoesNotExistError, match=no_objects_msg):
        await adcm_client.roles.get(display_name__eq="ADCM Admin")

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await adcm_client.roles.get(display_name__in=["Cluster Administrator", "Service Administrator"])

    # get permission
    assert isinstance(await adcm_client.permissions.get(display_name__eq="Create cluster"), role_module.Permission)

    with pytest.raises(ObjectDoesNotExistError, match=no_objects_msg):
        await adcm_client.permissions.get(display_name__eq="Create something")

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await adcm_client.permissions.get(display_name__in=["Create cluster", "View audit logins"])

    # get_or_none roles
    assert isinstance(
        await adcm_client.roles.get_or_none(display_name__eq="Service Administrator"), role_module.BuiltInRole
    )

    assert await adcm_client.roles.get_or_none(display_name__eq="NotARole") is None

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await adcm_client.roles.get_or_none(display_name__in=["Cluster Administrator", "Service Administrator"])

    # get_or_none permissions
    assert isinstance(
        await adcm_client.permissions.get_or_none(display_name__eq="View audit logins"), role_module.Permission
    )

    assert await adcm_client.permissions.get_or_none(display_name__eq="NotAPermission") is None

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await adcm_client.permissions.get_or_none(display_name__in=["Create cluster", "View audit logins"])

    # all roles
    all_roles = await adcm_client.roles.all()
    assert all(isinstance(role, role_module.BuiltInRole | role_module.CustomRole) for role in all_roles)
    assert len({role.id for role in all_roles}) == num_roles
    assert len({id(role) for role in all_roles}) == num_roles

    # all permissions
    all_permissions = await adcm_client.permissions.all()
    assert all(isinstance(permission, role_module.Permission) for permission in all_permissions)
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
