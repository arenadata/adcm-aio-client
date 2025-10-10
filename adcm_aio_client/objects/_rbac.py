from collections.abc import Collection
from typing import TYPE_CHECKING, Any, Literal, Optional, Self, Union

from asyncstdlib.functools import cached_property as async_cached_property  # noqa: N813

from adcm_aio_client._filters import ALL_OPERATIONS, COMMON_OPERATIONS, FilterBy, FilterByDisplayName, Filtering
from adcm_aio_client._types import EntitySourceType, Requester, UserStatus
from adcm_aio_client.objects._accessors import PaginatedAccessor
from adcm_aio_client.objects._base import RootInteractiveObject
from adcm_aio_client.objects._common import ConfigurableSetAttrMixin, Deletable, LazyObject

if TYPE_CHECKING:
    from adcm_aio_client.client import ADCMClient


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
        if self.id is None:
            return UserStatus.NOT_SAVED

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
