from typing import Any, Self, Unpack

from adcm_aio_client._filters import (
    ALL_OPERATIONS,
    COMMON_OPERATIONS,
    FilterBy,
    FilterByDisplayName,
    FilterByID,
    FilterByName,
    Filtering,
)
from adcm_aio_client.objects._accessors import PaginatedAccessor
from adcm_aio_client.objects.rbac._group import LDAPGroup, LocalGroup, LocalGroupLazy, _GroupKwargs
from adcm_aio_client.objects.rbac._role import BuiltInRole, CustomRole, CustomRoleLazy, Permission, _RoleKwargs
from adcm_aio_client.objects.rbac._types import CustomRoleData, LocalGroupData, LocalUserData, SourceType
from adcm_aio_client.objects.rbac._user import LDAPUser, LocalUser, LocalUserLazy, _UserKwargs
from adcm_aio_client.objects.rbac._utils import validate_kwargs


class UsersNode(PaginatedAccessor[LocalUser | LDAPUser]):
    filtering = Filtering(
        FilterByID, FilterBy("username", ALL_OPERATIONS, str), FilterBy("group", COMMON_OPERATIONS, int)
    )

    def new(self: Self, **kwargs: Unpack[_UserKwargs]) -> LocalUserLazy:
        # cast kwargs to dict to remove `TypedDict is not dict` error
        validate_kwargs(dict(kwargs), mandatory_fields=["username", "password"], obj_type_name=LocalUser.__name__)

        return LocalUserLazy.model_validate({"requester": self._requester, **kwargs})

    async def init(self: Self, user: LocalUserData) -> LocalUser:
        if not isinstance(user, LocalUserData):
            raise TypeError(f"Expected a {LocalUserData} object, got {type(user)}")

        post_data = user.model_dump(exclude_defaults=True, exclude_unset=True, by_alias=True)
        response = await self._requester.post("rbac/users/", data=post_data)

        return LocalUser(requester=self._requester, data=response.as_dict())

    def _create_object(self: Self, data: dict[str, Any]) -> LocalUser | LDAPUser:
        match data["type"]:
            case SourceType.LOCAL:
                cls_ = LocalUser
            case SourceType.LDAP:
                cls_ = LDAPUser
            case _:
                raise NotImplementedError(f"Unexpected user type: {data['type']}")

        return cls_(requester=self._requester, data=data)


class GroupsNode(PaginatedAccessor[LocalGroup | LDAPGroup]):
    filtering = Filtering(FilterByID, FilterByDisplayName)

    def new(self: Self, **kwargs: Unpack[_GroupKwargs]) -> LocalGroupLazy:
        # cast kwargs to dict to remove `TypedDict is not dict` error
        validate_kwargs(dict(kwargs), mandatory_fields=["display_name"], obj_type_name=LocalGroup.__name__)

        return LocalGroupLazy.model_validate({"requester": self._requester, **kwargs})

    async def init(self: Self, group: LocalGroupData) -> LocalGroup:
        if not isinstance(group, LocalGroupData):
            raise TypeError(f"Expected a {LocalGroupData} object, got {type(group)}")

        post_data = group.model_dump(exclude_defaults=True, exclude_unset=True, by_alias=True)
        response = await self._requester.post("rbac/groups/", data=post_data)

        return LocalGroup(requester=self._requester, data=response.as_dict())

    def _create_object(self: Self, data: dict[str, Any]) -> LocalGroup | LDAPGroup:
        match data["type"]:
            case SourceType.LOCAL:
                cls_ = LocalGroup
            case SourceType.LDAP:
                cls_ = LDAPGroup
            case _:
                raise NotImplementedError(f"Unexpected group type: {data['type']}")

        return cls_(requester=self._requester, data=data)


class RolesNode(PaginatedAccessor[BuiltInRole | CustomRole | Permission]):
    filtering = Filtering(FilterByID, FilterByName, FilterByDisplayName)

    def new(self: Self, **kwargs: Unpack[_RoleKwargs]) -> CustomRoleLazy:
        # cast kwargs to dict to remove `TypedDict is not dict` error
        validate_kwargs(
            dict(kwargs), mandatory_fields=["display_name", "permissions"], obj_type_name=CustomRole.__name__
        )

        return CustomRoleLazy.model_validate({"requester": self._requester, **kwargs})

    async def init(self: Self, role: CustomRoleData) -> CustomRole:
        if not isinstance(role, CustomRoleData):
            raise TypeError(f"Expected a {CustomRoleData} object, got {type(role)}")

        post_data = role.model_dump(exclude_defaults=True, exclude_unset=True, by_alias=True)
        response = await self._requester.post("rbac/roles/", data=post_data)

        return CustomRole(requester=self._requester, data=response.as_dict())

    def _create_object(self: Self, data: dict[str, Any]) -> BuiltInRole | CustomRole | Permission:
        if data["isBuiltIn"]:
            match data["type"]:
                case "role":
                    cls_ = BuiltInRole
                case "business":
                    cls_ = Permission
                case _:
                    raise NotImplementedError(f"Unexpected builtin role type: {data['type']}")
        else:
            cls_ = CustomRole

        return cls_(requester=self._requester, data=data)


# class PoliciesNode(PaginatedAccessor[Policy]):
#     class_type = Policy
#     filtering = Filtering(FilterByName)
