from collections import defaultdict
from collections.abc import Collection
from functools import cached_property
from typing import TYPE_CHECKING, Any, Self, Union
import asyncio

from asyncstdlib.functools import cached_property as async_cached_property  # noqa: N813

from adcm_aio_client._filters import (
    ALL_OPERATIONS,
    COMMON_OPERATIONS,
    FilterBy,
    FilterByDisplayName,
    FilterByID,
    FilterByName,
    Filtering,
)
from adcm_aio_client._types import EntitySourceType, UserStatus
from adcm_aio_client.objects._accessors import PaginatedAccessor
from adcm_aio_client.objects._base import RootInteractiveObject, convert_create_errors
from adcm_aio_client.objects._cm import Cluster, Component, Host, HostProvider, Service
from adcm_aio_client.objects._common import Deletable

if TYPE_CHECKING:
    pass


type PolicyObject = Cluster | Service | Component | HostProvider | Host


class _UserBase(RootInteractiveObject):
    PATH_PREFIX = "rbac/users"

    @property
    def username(self: Self) -> str:
        return self._data["username"]

    @property
    def first_name(self: Self) -> str:
        return self._data["firstName"]

    @property
    def last_name(self: Self) -> str:
        return self._data["lastName"]

    @property
    def email(self: Self) -> str:
        return self._data["email"]

    @property
    def is_super_user(self: Self) -> bool:
        return self._data["isSuperUser"]

    @async_cached_property
    async def groups(self: Self) -> list[Union["LocalGroup", "LDAPGroup"]]:
        group_ids = [group["id"] for group in self._data["groups"]] or [-1]

        return await GroupsNode(path=("rbac", "groups"), requester=self._requester).filter(id__in=group_ids)

    @property
    def status(self: Self) -> UserStatus:
        if self.id and self._data["blockingReason"] is not None:
            return UserStatus.INACTIVE

        return UserStatus.ACTIVE

    def __str__(self: Self) -> str:
        return f"<{self.__class__.__name__} #{self.id} {self.username}>"

    def __repr__(self: Self) -> str:
        return self.__str__()


class LocalUser(Deletable, _UserBase):
    pass


class LDAPUser(_UserBase):
    pass


class UsersNode(PaginatedAccessor[LocalUser | LDAPUser]):
    filtering = Filtering(
        FilterByID, FilterBy("username", ALL_OPERATIONS, str), FilterBy("group", COMMON_OPERATIONS, int)
    )

    def _create_object(self: Self, data: dict[str, Any]) -> LocalUser | LDAPUser:
        match data["type"]:
            case EntitySourceType.LOCAL:
                cls_ = LocalUser
            case EntitySourceType.LDAP:
                cls_ = LDAPUser
            case _:
                raise NotImplementedError(f"Unexpected user type: {data['type']}")

        return cls_(requester=self._requester, data=data)

    @convert_create_errors
    async def create(
        self: Self,
        username: str,
        password: str,
        is_super_user: bool = False,  # noqa: FBT001, FBT002
        first_name: str = "",
        last_name: str = "",
        email: str = "",
        groups: Collection["LocalGroup"] | None = None,
    ) -> LocalUser:
        data = {
            "username": username,
            "password": password,
            "firstName": first_name,
            "lastName": last_name,
            "email": email,
            "isSuperUser": is_super_user,
            "groups": [group.id for group in groups or []],
        }

        response = await self._requester.post(*self._path, data=data)
        return LocalUser(requester=self._requester, data=response.as_dict())


class _GroupBase(RootInteractiveObject):
    PATH_PREFIX = "rbac/groups"

    @property
    def display_name(self: Self) -> str:
        return self._data["displayName"]

    @property
    def description(self: Self) -> str:
        return self._data["description"]

    @async_cached_property
    async def users(self: Self) -> list[LocalUser | LDAPUser]:
        user_ids = [user["id"] for user in self._data["users"]] or [-1]

        return await UsersNode(path=("rbac", "users"), requester=self._requester).filter(id__in=user_ids)


class LocalGroup(Deletable, _GroupBase):
    pass


class LDAPGroup(_GroupBase):
    pass


class GroupsNode(PaginatedAccessor[LocalGroup | LDAPGroup]):
    filtering = Filtering(FilterByID, FilterByDisplayName)

    def _create_object(self: Self, data: dict[str, Any]) -> LocalGroup | LDAPGroup:
        match data["type"]:
            case EntitySourceType.LOCAL:
                cls_ = LocalGroup
            case EntitySourceType.LDAP:
                cls_ = LDAPGroup
            case _:
                raise NotImplementedError(f"Unexpected group type: {data['type']}")

        return cls_(requester=self._requester, data=data)

    @convert_create_errors
    async def create(
        self: Self, display_name: str, description: str = "", users: list[LocalUser] | None = None
    ) -> LocalGroup:
        data = {"displayName": display_name, "description": description, "users": [user.id for user in users or []]}

        response = await self._requester.post(*self._path, data=data)
        return LocalGroup(requester=self._requester, data=response.as_dict())


class _RoleBase(RootInteractiveObject):
    PATH_PREFIX = "rbac/roles"

    @property
    def name(self: Self) -> str:
        return self._data["name"]

    @property
    def display_name(self: Self) -> str:
        return self._data["displayName"]

    @property
    def description(self: Self) -> str:
        return self._data["description"]


class Permission(_RoleBase):
    """`business` type builtin roles"""


class _Role(_RoleBase):
    @property
    def permissions(self: Self) -> list[Permission]:
        return [Permission(requester=self._requester, data=child_data) for child_data in self._data["children"]]

    @cached_property
    def _parametrized_by_type(self: Self) -> list[type[Cluster | Service | Component | HostProvider | Host]]:
        types_map = {
            "cluster": Cluster,
            "service": Service,
            "component": Component,
            "provider": HostProvider,
            "host": Host,
        }

        return [types_map[type_] for type_ in self._data.get("parametrizedByType", [])]


class BuiltInRole(_Role):
    pass


class CustomRole(Deletable, _Role):
    pass


class RolesNode(PaginatedAccessor[BuiltInRole | CustomRole | Permission]):
    filtering = Filtering(FilterByID, FilterByName, FilterByDisplayName)

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

    @convert_create_errors
    async def create(
        self: Self, display_name: str, permissions: list[Permission] | None = None, description: str = ""
    ) -> CustomRole:
        data = {
            "displayName": display_name,
            "children": [permission.id for permission in permissions or []],
            "description": description,
        }

        response = await self._requester.post(*self._path, data=data)
        return CustomRole(requester=self._requester, data=response.as_dict())


class Policy(Deletable, RootInteractiveObject):
    PATH_PREFIX = "rbac/policies"
    _obj_type_cls_map = {
        "cluster": Cluster,
        "service": Service,
        "component": Component,
        "provider": HostProvider,
        "host": Host,
    }

    @property
    def name(self: Self) -> str:
        return self._data["name"]

    @property
    def description(self: Self) -> str:
        return self._data["description"]

    @async_cached_property
    async def role(self: Self) -> BuiltInRole | CustomRole:
        return await RolesNode(path=("rbac", "roles"), requester=self.requester).get(id__eq=self._data["role"]["id"])  # pyright: ignore[reportReturnType]

    @async_cached_property
    async def objects(self: Self) -> list[PolicyObject]:
        cls_ids_map = defaultdict(set)
        for obj in self._data["objects"]:
            if (obj_type := obj["type"]) in {"service", "component"}:
                # TODO: now it is impossible to get service/component object from policy.objects
                #  since there is no info about parent objects in policy.objects field
                continue

            obj_cls = self._obj_type_cls_map[obj_type]
            cls_ids_map[obj_cls].add(obj["id"])

        coros = []
        for cls_, ids in cls_ids_map.items():
            coros.extend(cls_.with_id(requester=self.requester, object_id=id_) for id_ in ids)

        return list(await asyncio.gather(*coros))

    @async_cached_property
    async def groups(self: Self) -> list[LocalGroup | LDAPGroup]:
        group_ids = [group["id"] for group in self._data["groups"]] or [-1]

        return await GroupsNode(path=("rbac", "groups"), requester=self.requester).filter(id__in=group_ids)


class PoliciesNode(PaginatedAccessor[Policy]):
    class_type = Policy
    filtering = Filtering(FilterByName)
    _obj_cls_type_map = {
        Cluster: "cluster",
        Service: "service",
        Component: "component",
        HostProvider: "provider",
        Host: "host",
    }

    @convert_create_errors
    async def create(
        self: Self,
        name: str,
        role: CustomRole | BuiltInRole,
        groups: list[LocalGroup | LDAPGroup],
        objects: list[PolicyObject] | None = None,
        description: str = "",
    ) -> Policy:
        data = {
            "name": name,
            "role": {"id": role.id},
            "objects": [{"id": obj.id, "type": self._obj_cls_type_map[obj.__class__]} for obj in objects or []],
            "groups": [group.id for group in groups],
            "description": description,
        }

        response = await self._requester.post(*self._path, data=data)
        return Policy(requester=self._requester, data=response.as_dict())
