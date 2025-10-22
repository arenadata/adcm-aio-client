from collections import defaultdict
from collections.abc import Collection
from functools import cached_property
from typing import TYPE_CHECKING, Any, Literal, Optional, Self, Union, cast
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
from adcm_aio_client._types import EntitySourceType, Requester, UserStatus
from adcm_aio_client.objects._accessors import PaginatedAccessor
from adcm_aio_client.objects._base import RootInteractiveObject
from adcm_aio_client.objects._cm import Cluster, Component, Host, HostProvider, Service
from adcm_aio_client.objects._common import ConfigurableSetAttrMixin, Deletable, LazyObject
from adcm_aio_client.objects._utils import (
    raise_exc,
    setattr_group_users,
    setattr_policy_groups,
    setattr_policy_objects,
    setattr_policy_role,
    setattr_user_groups,
)

if TYPE_CHECKING:
    from adcm_aio_client.client import ADCMClient


type PolicyObject = Cluster | Service | Component | HostProvider | Host
type IDDictInternalValue = dict[Literal["id"], int]
type ListOfIDDictsInternalValue = list[IDDictInternalValue]
type PolicyObjectsInternalValue = list[dict[Literal["id", "type"], int | str]]

# client._requester access
# pyright: reportOptionalMemberAccess=false
# id -> int | None override
# pyright: reportIncompatibleVariableOverride=false
# Any type
# ruff: noqa: ANN401


class User(LazyObject, ConfigurableSetAttrMixin, RootInteractiveObject):
    PATH_PREFIX = "rbac/users"
    _custom_setattr = {"groups": lambda *args: raise_exc(msg="`groups` attribute is not mutable")}  # noqa: ARG005

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
        group_ids = [group["id"] for group in self._data["groups"]] or [-1]

        return await GroupsNode(
            path=("rbac", "groups"), requester=self._requester, default_query={"id__in": group_ids}
        ).all()

    @property
    def status(self: Self) -> UserStatus:
        if self.id and self._data["blockingReason"] is not None:
            return UserStatus.INACTIVE

        return UserStatus.ACTIVE

    @staticmethod
    def _postprocess_save_data(data: Any, mode: Literal["create", "update"]) -> Any:
        _ = mode
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
    _custom_setattr = {"groups": setattr_user_groups}  # noqa: ARG005

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
        if not any((data, requester)):
            if not all((client, username, password)):
                raise RuntimeError(
                    f"`client`, `username` and `password` are mandatory to create a {self.__class__.__name__}"
                )

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

    def _to_internal_value_groups(self: Self, groups: Collection["LocalGroup"] | None) -> ListOfIDDictsInternalValue:
        groups = self._validate_groups(groups)
        # id is present by this moment
        return cast(ListOfIDDictsInternalValue, [{"id": group.id} for group in groups])

    @staticmethod
    def _validate_groups(groups: Collection["LocalGroup"] | None) -> Collection["LocalGroup"]:
        if not groups:
            raise ValueError(f"All groups must be {LocalGroup.__name__}")

        if errors := [type(group) for group in groups if not isinstance(group, LocalGroup)]:
            raise ValueError(f"All groups must be {LocalGroup.__name__}, got {errors}")

        if not all(group.id for group in groups):
            raise ValueError("All groups must be saved before assigning them to user")

        return groups


class LDAPUser(User):
    def __init__(
        self: Self,
        requester: Requester | None = None,
        data: dict[str, Any] | None = None,
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        if kwargs or not (requester or data):
            raise NotImplementedError(f"{self.__class__.__name__} can't be created manually")

        super().__init__(requester=requester, data=data)


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


class Group(LazyObject, ConfigurableSetAttrMixin, RootInteractiveObject):
    PATH_PREFIX = "rbac/groups"
    _custom_setattr = {"users": lambda *args: raise_exc(msg="`users` attribute is not mutable")}  # noqa: ARG005

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

    @staticmethod
    def _postprocess_save_data(data: Any, mode: Literal["create", "update"]) -> Any:
        _ = mode
        if "users" in data:
            data["users"] = [user["id"] for user in data["users"]]

        return data


class LocalGroup(Deletable, Group):
    _custom_setattr = {"users": setattr_group_users}

    def __init__(
        self: Self,
        requester: Requester | None = None,
        data: dict[str, Any] | None = None,
        client: Optional["ADCMClient"] = None,
        display_name: str | None = None,
        description: str = "",
    ) -> None:
        if not any((data, requester)):
            if not all((client, display_name)):
                raise RuntimeError(f"`client` and `display_name` are mandatory to create a {self.__class__.__name__}")

            data = {"displayName": display_name, "description": description, "users": []}
            requester = client._requester

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

    def _to_internal_value_users(self: Self, users: Collection[LocalUser | LDAPUser]) -> ListOfIDDictsInternalValue:
        users = self._validate_users(users=users)
        # id is present by this moment
        return cast(ListOfIDDictsInternalValue, [{"id": user.id} for user in users])

    @staticmethod
    def _validate_users(users: Collection[LocalUser | LDAPUser]) -> Collection[LocalUser | LDAPUser]:
        if errors := [type(user) for user in users if not isinstance(user, LocalUser | LDAPUser)]:
            raise ValueError(f"All users must be {LocalUser.__name__} or {LDAPUser.__name__}, got {errors}")

        if not all(user.id for user in users):
            raise ValueError("All users must be saved before assigning them to group")

        return users


class LDAPGroup(Group):
    def __init__(
        self: Self,
        requester: Requester | None = None,
        data: dict[str, Any] | None = None,
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        if kwargs or not (requester or data):
            raise NotImplementedError(f"{self.__class__.__name__} can't be created manually")

        super().__init__(requester=requester, data=data)


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
        if not any((data, requester)):
            if not all((client, display_name, permissions)):
                raise RuntimeError(
                    f"`client`, `display_name` and `permissions` are mandatory to create a {self.__class__.__name__}"
                )

            data = {
                "name": display_name,
                "displayName": display_name,
                "description": description,
                "children": self._to_internal_value_permissions(permissions),
            }
            requester = client._requester

        super().__init__(requester=requester, data=data)

    def _prepare_data_for_save(self: Self, mode: Literal["create", "update"]) -> dict:
        _ = mode
        return {"displayName": self.display_name, "children": [child["id"] for child in self._data["children"]]}

    def _to_internal_value_permissions(
        self: Self, permissions: Collection[Permission] | None
    ) -> ListOfIDDictsInternalValue:
        permissions = self._validate_permissions(permissions=permissions)

        return [{"id": permission.id} for permission in permissions]

    @staticmethod
    def _validate_permissions(permissions: Collection[Permission] | None) -> Collection[Permission]:
        if not permissions or not all(isinstance(p, Permission) for p in permissions):
            raise ValueError("All permissions must be a `Permission` objects")

        return permissions


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


class Policy(Deletable, LazyObject, ConfigurableSetAttrMixin, RootInteractiveObject):
    PATH_PREFIX = "rbac/policies"
    _custom_setattr = {  # pyright: ignore[reportAssignmentType]
        "role": setattr_policy_role,
        "objects": setattr_policy_objects,
        "groups": setattr_policy_groups,
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
        if not any((data, requester)):
            if not all((client, name, role, objects, groups)):
                raise RuntimeError(
                    f"`client`, `name`, `role`, `objects` and `groups` "
                    f"are mandatory to create a {self.__class__.__name__}"
                )

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
        return await RolesNode(path=("rbac", "roles"), requester=self.requester).get(id__eq=self._data["role"]["id"])  # pyright: ignore[reportReturnType]

    @async_cached_property
    async def objects(self: Self) -> list[PolicyObject]:
        _obj_type_cls_map = {v: k for k, v in self._obj_cls_type_map.items()}

        cls_ids_map = defaultdict(set)
        for obj in self._data["objects"]:
            if (obj_type := obj["type"]) in {"service", "component"}:
                # TODO: now it is impossible to get service/component object from policy.objects
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
        group_ids = [group["id"] for group in self._data["groups"]] or [-1]

        return await GroupsNode(path=("rbac", "groups"), requester=self.requester).filter(id__in=group_ids)

    @staticmethod
    def _postprocess_save_data(data: Any, mode: Literal["create", "update"]) -> Any:
        _ = mode
        if "groups" in data:
            data["groups"] = [group["id"] for group in data["groups"]]

        return data

    def _to_internal_value_objects(self: Self, objects: Collection[PolicyObject]) -> PolicyObjectsInternalValue:
        objects = self._validate_objects(objects=objects)

        return [{"id": obj_.id, "type": self._obj_cls_type_map[type(obj_)]} for obj_ in objects]

    def _validate_objects(self: Self, objects: Collection[PolicyObject]) -> Collection[PolicyObject]:
        valid_types = tuple(self._obj_cls_type_map.keys())
        if errors := [type(obj) for obj in objects if not isinstance(obj, valid_types)]:
            _valid_types_repr = ", ".join(f"{obj.__class__.__name__}" for obj in valid_types)
            _valid_types_repr = " or ".join(_valid_types_repr.rsplit(", ", maxsplit=1))  # replace last `, ` with ` or `
            raise ValueError(f"All objects must be {_valid_types_repr}, got {errors}")

        if not all(obj.id for obj in objects):
            raise ValueError("All objects must be saved before assigning them to policy")

        return objects

    def _to_internal_value_role(self: Self, role: BuiltInRole | CustomRole) -> IDDictInternalValue:
        role = self._validate_role(role=role)

        return {"id": role.id}  # pyright: ignore[reportReturnType]

    @staticmethod
    def _validate_role(role: BuiltInRole | CustomRole) -> BuiltInRole | CustomRole:
        if not isinstance(role, BuiltInRole | CustomRole):
            raise ValueError(f"Role must be a {BuiltInRole.__name__} or {CustomRole.__name__}, got {type(role)}")  # noqa: TRY004

        if not role.id:
            raise ValueError("Role must be saved before assigning it to policy")

        return role

    def _to_internal_value_groups(self: Self, groups: Collection[LocalGroup | LDAPGroup]) -> ListOfIDDictsInternalValue:
        groups = self._validate_groups(groups=groups)

        return [{"id": group.id} for group in groups]  # pyright: ignore[reportReturnType]

    @staticmethod
    def _validate_groups(groups: Collection[LocalGroup | LDAPGroup]) -> Collection[LocalGroup | LDAPGroup]:
        if errors := [type(group) for group in groups if not isinstance(group, LocalGroup | LDAPGroup)]:
            raise ValueError(f"All groups must be {LocalGroup.__name__} or {LDAPGroup.__name__}, got {errors}")

        if not all(group.id for group in groups):
            raise ValueError("All groups must be saved before assigning them to policy")

        return groups


class PoliciesNode(PaginatedAccessor[Policy]):
    class_type = Policy
    filtering = Filtering(FilterByName)
