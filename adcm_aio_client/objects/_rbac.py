from typing import TYPE_CHECKING, Any, Optional, Self

from adcm_aio_client._filters import ALL_OPERATIONS, COMMON_OPERATIONS, FilterBy, Filtering
from adcm_aio_client._types import Requester, UserStatus, UserType
from adcm_aio_client.objects._accessors import PaginatedAccessor
from adcm_aio_client.objects._base import RootInteractiveObject
from adcm_aio_client.objects._common import Deletable

if TYPE_CHECKING:
    from adcm_aio_client.client import ADCMClient


class User(RootInteractiveObject):
    PATH_PREFIX = "rbac/users"

    def __init__(self: Self, requester: Requester | None, data: dict[str, Any]) -> None:
        super().__init__(requester=requester, data=data)  # pyright: ignore[reportArgumentType]
        self._manually_set: set[str] = set()

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

    @property
    def groups(self: Self) -> list:  # TODO
        return self._data["groups"]

    @groups.setter
    def groups(self: Self, group_ids: list[int]) -> None:
        key = "groups"
        self._data[key] = group_ids
        self._manually_set.add(key)

    @property
    def status(self: Self) -> UserStatus:
        if self.id is None:
            return UserStatus.NOT_SAVED

        if self._data["blockingReason"] is not None:
            return UserStatus.INACTIVE

        return UserStatus.ACTIVE

    async def save(self: Self) -> None:
        if self.id is None:  # create
            url = (self.PATH_PREFIX,)
            method = self.requester.post
            data = self._data
        else:  # update
            url = self.get_own_path()
            method = self.requester.patch
            data = {key: value for key, value in self._data.items() if key in self._manually_set}

        response = await method(*url, data=data)
        self._data = response.as_dict()
        self._manually_set.clear()

    async def refresh(self: Self) -> Self:
        self._manually_set.clear()
        return await super().refresh()

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

        super().__init__(requester=requester, data=data)  # pyright: ignore[reportArgumentType]

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
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        _ = kwargs
        if data is None:
            raise NotImplementedError("Can't manually create a LDAP user")

        super().__init__(requester=requester, data=data)


class UsersNode(PaginatedAccessor[LocalUser | LDAPUser]):
    filtering = Filtering(FilterBy("username", ALL_OPERATIONS, str), FilterBy("group", COMMON_OPERATIONS, int))

    def _create_object(self: Self, data: dict[str, Any]) -> LocalUser | LDAPUser:
        match data["type"]:
            case UserType.LOCAL:
                cls_ = LocalUser
            case UserType.LDAP:
                cls_ = LDAPUser
            case _:
                raise NotImplementedError(f"Unexpected user type: {data['type']}")

        return cls_(requester=self._requester, data=data)
