from collections import defaultdict
from collections.abc import Collection
from functools import cached_property
from typing import TYPE_CHECKING, Any, Literal, Optional, Self, Union
import asyncio

from asyncstdlib.functools import cached_property as async_cached_property  # noqa: N813

from adcm_aio_client._filters import (
    ALL_OPERATIONS,
    COMMON_OPERATIONS,
    FilterBy,
    FilterByDisplayName,
    FilterByName,
    Filtering,
)
from adcm_aio_client._types import EntitySourceType, Requester, UserStatus
from adcm_aio_client.objects._accessors import PaginatedAccessor
from adcm_aio_client.objects._base import RootInteractiveObject
from adcm_aio_client.objects._cm import Cluster, Component, Host, HostProvider, Service
from adcm_aio_client.objects._common import ConfigurableSetAttrMixin, Deletable, LazyObject

if TYPE_CHECKING:
    from adcm_aio_client.client import ADCMClient


type PolicyObject = Cluster | Service | Component | HostProvider | Host
type PolicyGroupsInternalValue = list[dict[Literal["id"], int]]
type PolicyRoleInternalValue = dict[Literal["id"], int]
type PolicyObjectsInternalValue = list[dict[Literal["id", "type"], int | str]]


def _raise(exc: type[Exception] = AttributeError, msg: str = "") -> None:
    raise exc(msg)


def _setattr_user_groups(self: "User", key: str, value: Collection[Union["LocalGroup", "LDAPGroup"]]) -> None:
    if errors := [type(group) for group in value if not isinstance(group, LocalGroup | LDAPGroup)]:
        raise ValueError(f"All groups must be {LocalGroup.__name__} or {LDAPGroup.__name__}, got {errors}")

    if not all(group.id for group in value):
        raise ValueError("All groups must be saved before assigning them to user")

    self._data[key] = [{"id": group.id} for group in value]
    self._manually_set.add(key)


class User(LazyObject, ConfigurableSetAttrMixin, RootInteractiveObject):
    PATH_PREFIX = "rbac/users"
    _custom_setattr = {"groups": _setattr_user_groups}  # noqa: ARG005

    @property
    def id(self: Self) -> int | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """May be `None` if User was created manually and not saved yet"""
        return self._data.get("id")

    @property
    def username(self: Self) -> str:
        return self._data["username"]

    @property
    def password(self: Self) -> str:
        return "*" * 5

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
        group_ids = ",".join(str(group["id"]) for group in self._data["groups"]) or "-1"
        return list(
            await GroupsNode(
                path=("rbac", "groups"), requester=self._requester, default_query={"id__in": group_ids}
            ).all()
        )

    @property
    def status(self: Self) -> UserStatus:
        if self._data["blockingReason"] is not None:
            return UserStatus.INACTIVE

        return UserStatus.ACTIVE

    def _prepare_data_for_save(self: Self, mode: Literal["create", "update"]) -> dict:
        match mode:
            case "create":
                data = self._data
            case "update":
                data = {key: value for key, value in self._data.items() if key in self._manually_set}
            case _:
                raise ValueError(f"Unknown mode {mode}")

        if "groups" in data:
            data["groups"] = [group["id"] for group in data["groups"]]

        return data

    @property
    def _repr(self: Self) -> str:
        return f"<{self.__class__.__name__} #{self.id} {self.username}>"

    def __str__(self: Self) -> str:
        return self._repr

    def __repr__(self: Self) -> str:
        return self._repr


class LocalUser(Deletable, User):
    def __init__(
        self: Self,
        requester: Requester | None = None,
        client: Optional["ADCMClient"] = None,
        data: dict[str, Any] | None = None,
        username: str | None = None,
        password: str | None = None,
        is_super_user: bool = False,  # noqa: FBT001, FBT002
        first_name: str = "",
        last_name: str = "",
        email: str = "",
    ) -> None:
        if not data and not requester:
            if all((username, password)) and client:
                data = {
                    "username": username,
                    "password": password,
                    "isSuperUser": is_super_user,
                    "firstName": first_name,
                    "lastName": last_name,
                    "email": email,
                    "groups": [],
                    "blockingReason": None,
                }
                requester = client._requester

            else:
                raise RuntimeError("`client`, `username` and `password` are mandatory to create a local user")

        super().__init__(requester=requester, data=data)

    @User.password.setter
    def password(self: Self, password: str) -> None:
        key = "password"
        self._data[key] = password
        self._manually_set.add(key)

    @User.first_name.setter
    def first_name(self: Self, first_name: str) -> None:
        key = "firstName"
        self._data[key] = first_name
        self._manually_set.add(key)

    @User.last_name.setter
    def last_name(self: Self, last_name: str) -> None:
        key = "lastName"
        self._data[key] = last_name
        self._manually_set.add(key)

    @User.email.setter
    def email(self: Self, email: str) -> None:
        key = "email"
        self._data[key] = email
        self._manually_set.add(key)

    @User.is_super_user.setter
    def is_super_user(self: Self, is_super_user: bool) -> None:  # noqa: FBT001
        key = "isSuperUser"
        self._data[key] = is_super_user
        self._manually_set.add(key)


class LDAPUser(User):
    def __init__(
        self: Self,
        requester: Requester | None = None,
        data: dict[str, Any] | None = None,
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        _ = args, kwargs
        if data is None:
            raise NotImplementedError("Can't manually create a LDAP user")

        super().__init__(requester=requester, data=data)


class UsersNode(PaginatedAccessor[LocalUser | LDAPUser]):
    filtering = Filtering(FilterBy("username", ALL_OPERATIONS, str), FilterBy("group", COMMON_OPERATIONS, int))

    def _create_object(self: Self, data: dict[str, Any]) -> LocalUser | LDAPUser:
        match data["type"]:
            case EntitySourceType.LOCAL:
                cls_ = LocalUser
            case EntitySourceType.LDAP:
                cls_ = LDAPUser
            case _:
                raise NotImplementedError(f"Unexpected user type: {data['type']}")

        return cls_(requester=self._requester, data=data)


class Group(LazyObject, ConfigurableSetAttrMixin, RootInteractiveObject):
    PATH_PREFIX = "rbac/groups"
    _custom_setattr = {"users": lambda *args: _raise(msg="`users` attribute is not mutable")}  # noqa: ARG005

    @property
    def id(self: Self) -> int | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        return self._data.get("id")

    @property
    def display_name(self: Self) -> str:
        return self._data["displayName"]

    @property
    def description(self: Self) -> str:
        return self._data["description"]

    @async_cached_property
    async def users(self: Self) -> list[LocalUser | LDAPUser]:
        user_ids = ",".join(str(user["id"]) for user in self._data["users"]) or "-1"
        return list(
            await UsersNode(path=("rbac", "users"), requester=self._requester, default_query={"id__in": user_ids}).all()
        )

    def _prepare_data_for_save(self: Self, mode: Literal["create", "update"]) -> dict:
        match mode:
            case "create":
                data = self._data
            case "update":
                data = {key: value for key, value in self._data.items() if key in self._manually_set}
            case _:
                raise ValueError(f"Unknown mode {mode}")

        if "users" in data:
            data["users"] = [user["id"] for user in data["users"]]

        return data


def _setattr_group_users(self: "LocalGroup", key: str, value: Collection[LocalUser | LDAPUser]) -> None:
    if errors := [type(user) for user in value if not isinstance(user, LocalUser | LDAPUser)]:
        raise ValueError(f"All users must be {LocalUser.__name__} or {LDAPUser.__name__}, got {errors}")

    if not all(user.id for user in value):
        raise ValueError("All users must be saved before assigning them to group")

    self._data[key] = [{"id": user.id} for user in value]
    self._manually_set.add(key)


class LocalGroup(Deletable, Group):
    _custom_setattr = {"users": _setattr_group_users}

    def __init__(
        self: Self,
        requester: Requester | None = None,
        data: dict[str, Any] | None = None,
        client: Optional["ADCMClient"] = None,
        display_name: str | None = None,
        description: str = "",
    ) -> None:
        if not data and not requester:
            if client and display_name:
                data = {"displayName": display_name, "description": description, "users": []}
                requester = client._requester
            else:
                raise RuntimeError("`client` and `display_name` are mandatory to create a local group")

        super().__init__(requester=requester, data=data)

    @Group.display_name.setter
    def display_name(self: Self, display_name: str) -> None:
        key = "displayName"
        self._data[key] = display_name
        self._manually_set.add(key)

    @Group.description.setter
    def description(self: Self, description: str) -> None:
        key = "description"
        self._data[key] = description
        self._manually_set.add(key)


class LDAPGroup(Group):
    def __init__(
        self: Self,
        requester: Requester | None = None,
        data: dict[str, Any] | None = None,
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        _ = args, kwargs
        if data is None:
            raise NotImplementedError("Can't manually create a LDAP group")

        super().__init__(requester=requester, data=data)


class GroupsNode(PaginatedAccessor[LocalGroup | LDAPGroup]):
    filtering = Filtering(FilterByDisplayName)

    def _create_object(self: Self, data: dict[str, Any]) -> LocalGroup | LDAPGroup:
        match data["type"]:
            case EntitySourceType.LOCAL:
                cls_ = LocalGroup
            case EntitySourceType.LDAP:
                cls_ = LDAPGroup
            case _:
                raise NotImplementedError(f"Unexpected group type: {data['type']}")

        return cls_(requester=self._requester, data=data)


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

    def __init__(
        self: Self,
        requester: Requester | None = None,
        data: dict[str, Any] | None = None,
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        if kwargs or not (requester or data):
            raise NotImplementedError(f"{self.__class__.__name__} can't be created manually")

        super().__init__(requester=requester, data=data)  # pyright: ignore [reportArgumentType]


class Role(_RoleBase):
    @cached_property
    def permissions(self: Self) -> list[Permission]:
        return [Permission(requester=self.requester, data=child_data) for child_data in self._data["children"]]

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


class BuiltInRole(Role):
    def __init__(
        self: Self,
        requester: Requester | None = None,
        data: dict[str, Any] | None = None,
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        if kwargs or not (requester or data):
            raise NotImplementedError(f"{self.__class__.__name__} can't be created manually")

        super().__init__(requester=requester, data=data)  # pyright: ignore [reportArgumentType]


class CustomRole(Deletable, LazyObject, Role):
    def __init__(
        self: Self,
        requester: Requester | None = None,
        data: dict[str, Any] | None = None,
        client: Optional["ADCMClient"] = None,
        display_name: str | None = None,
        permissions: list["Permission"] | None = None,
        description: str = "",
    ) -> None:
        if not data and not requester:
            if client and display_name and permissions:
                if not all(isinstance(p, Permission) for p in permissions):
                    raise ValueError("All permissions must be a `Permission` objects")

                data = {"displayName": display_name, "description": description, "children": permissions}
                requester = client._requester

            else:
                raise RuntimeError("`client`, `display_name` and `permissions` are mandatory to create a custom role")

        super().__init__(requester=requester, data=data)

    @property
    def id(self: Self) -> int | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        return self._data.get("id")

    @property
    def name(self: Self) -> str | None:  # pyright: ignore[reportIncompatibleMethodOverride]
        return self._data.get("name")

    def _prepare_data_for_save(self: Self, mode: Literal["create", "update"]) -> dict:
        _ = mode
        return {"displayName": self.display_name, "children": [child.id for child in self._data["children"]]}


class RolesNode(PaginatedAccessor[BuiltInRole | CustomRole | Permission]):
    filtering = Filtering(FilterByName, FilterByDisplayName)

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


def _setattr_policy_role(self: "Policy", key: Literal["role"], value: BuiltInRole | CustomRole) -> None:
    self._data[key] = self._to_internal_value_role(value)
    self._manually_set.add(key)


def _setattr_policy_objects(self: "Policy", key: Literal["objects"], value: Collection[PolicyObject]) -> None:
    self._data[key] = self._to_internal_value_objects(value)
    self._manually_set.add(key)


def _setattr_policy_groups(self: "Policy", key: Literal["groups"], value: Collection[LocalGroup | LDAPGroup]) -> None:
    self._data[key] = self._to_internal_value_groups(value)
    self._manually_set.add(key)


class Policy(Deletable, LazyObject, ConfigurableSetAttrMixin, RootInteractiveObject):
    PATH_PREFIX = "rbac/policies"
    _custom_setattr = {  # pyright: ignore[reportAssignmentType]
        "role": _setattr_policy_role,
        "objects": _setattr_policy_objects,
        "groups": _setattr_policy_groups,
    }
    _obj_cls_type_map = {
        Cluster: "cluster",
        Service: "service",
        Component: "component",
        HostProvider: "provider",
        Host: "host",
    }

    def __init__(
        self: Self,
        requester: Requester | None = None,
        data: dict[str, Any] | None = None,
        client: Optional["ADCMClient"] = None,
        name: str | None = None,
        role: CustomRole | BuiltInRole | None = None,
        objects: Collection[PolicyObject] | None = None,
        groups: Collection[LocalGroup | LDAPGroup] | None = None,
        description: str = "",
    ) -> None:
        if not data and not requester:
            if not (client and all((name, role, objects, groups))):
                raise RuntimeError("`client`, `name`, `role`, `objects` and `groups` are mandatory to create a policy")

            data = {
                "name": name,
                "description": description,
                "role": self._to_internal_value_role(role=role),  # pyright: ignore[reportArgumentType]
                "objects": self._to_internal_value_objects(objects=objects),  # pyright: ignore[reportArgumentType]
                "groups": self._to_internal_value_groups(groups=groups),  # pyright: ignore[reportArgumentType]
            }
            requester = client._requester

        super().__init__(requester=requester, data=data)

    @property
    def id(self: Self) -> int | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        return self._data.get("id")

    @property
    def name(self: Self) -> str:
        return self._data["name"]

    @name.setter
    def name(self: Self, name: str) -> None:
        key = "name"
        self._data[key] = name
        self._manually_set.add(key)

    @property
    def description(self: Self) -> str:
        return self._data["description"]

    @description.setter
    def description(self: Self, description: str) -> None:
        key = "description"
        self._data[key] = description
        self._manually_set.add(key)

    @async_cached_property
    async def role(self: Self) -> BuiltInRole | CustomRole:
        return await RolesNode(  # pyright: ignore[reportReturnType]
            path=("rbac", "roles"), requester=self.requester, default_query={"id__eq": self._data["role"]["id"]}
        ).get()

    @async_cached_property  # TODO:
    async def objects(self: Self) -> list[PolicyObject]:
        _obj_type_cls_map = {v: k for k, v in self._obj_cls_type_map.items()}

        cls_ids_map = defaultdict(set)
        for obj in self._data["objects"]:
            if (obj_type := obj["type"]) in {"service", "component"}:
                # TODO: now it is impossible to get service/somponent object from policy.objects
                #  since there is no info about parent objects in policy.objects field
                continue

            obj_cls = _obj_type_cls_map[obj_type]
            cls_ids_map[obj_cls].add(obj["id"])

        coros = []
        for cls_, ids in cls_ids_map.items():
            coros.extend(cls_.with_id(requester=self.requester, object_id=id_) for id_ in ids)

        return list(await asyncio.gather(*coros))

    @async_cached_property
    async def groups(self: Self) -> list[LocalGroup | LDAPGroup]:
        group_ids = ",".join(str(group["id"]) for group in self._data["groups"]) or "-1"

        return list(
            await GroupsNode(
                path=("rbac", "groups"), requester=self.requester, default_query={"id__in": group_ids}
            ).all()
        )

    def _prepare_data_for_save(self: Self, mode: Literal["create", "update"]) -> dict:
        match mode:
            case "create":
                data = self._data
            case "update":
                data = {key: value for key, value in self._data.items() if key in self._manually_set}
            case _:
                raise ValueError(f"Unknown mode {mode}")

        if "groups" in data:
            data["groups"] = [group["id"] for group in data["groups"]]

        return data

    def _to_internal_value_objects(self: Self, objects: Collection[PolicyObject]) -> PolicyObjectsInternalValue:
        self._validate_objects(objects=objects)

        return [{"id": obj_.id, "type": self._obj_cls_type_map[type(obj_)]} for obj_ in objects]

    def _validate_objects(self: Self, objects: Collection[PolicyObject]) -> None:
        valid_types = tuple(self._obj_cls_type_map.keys())
        if errors := [type(obj) for obj in objects if not isinstance(obj, valid_types)]:
            _valid_types_repr = ", ".join(f"{obj.__class__.__name__}" for obj in valid_types)
            _valid_types_repr = " or ".join(_valid_types_repr.rsplit(", ", maxsplit=1))  # replace last `, ` with ` or `
            raise ValueError(f"All objects must be {_valid_types_repr}, got {errors}")

        if not all(obj.id for obj in objects):
            raise ValueError("All objects must be saved before assigning them to policy")

    def _to_internal_value_role(self: Self, role: BuiltInRole | CustomRole) -> PolicyRoleInternalValue:
        self._validate_role(role=role)

        return {"id": role.id}  # pyright: ignore[reportReturnType]

    @staticmethod
    def _validate_role(role: BuiltInRole | CustomRole) -> None:
        if not isinstance(role, BuiltInRole | CustomRole):
            raise ValueError(f"Role must be a {BuiltInRole.__name__} or {CustomRole.__name__}, got {type(role)}")  # noqa: TRY004

        if not role.id:
            raise ValueError("Role must be saved before assigning it to policy")

    def _to_internal_value_groups(self: Self, groups: Collection[LocalGroup | LDAPGroup]) -> PolicyGroupsInternalValue:
        self._validate_groups(groups=groups)

        return [{"id": group.id} for group in groups]  # pyright: ignore[reportReturnType]

    @staticmethod
    def _validate_groups(groups: Collection[LocalGroup | LDAPGroup]) -> None:
        if errors := [type(group) for group in groups if not isinstance(group, LocalGroup | LDAPGroup)]:
            raise ValueError(f"All groups must be {LocalGroup.__name__} or {LDAPGroup.__name__}, got {errors}")

        if not all(group.id for group in groups):
            raise ValueError("All groups must be saved before assigning them to policy")


class PoliciesNode(PaginatedAccessor[Policy]):
    class_type = Policy
    filtering = Filtering(FilterByName)
