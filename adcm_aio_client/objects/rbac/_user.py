from functools import cached_property
from typing import Any, Self, Unpack

from asyncstdlib.functools import cached_property as async_cached_property  # noqa: N813

from adcm_aio_client._filters import ALL_OPERATIONS, COMMON_OPERATIONS, FilterBy, FilterByID, Filtering
from adcm_aio_client.objects._accessors import PaginatedAccessor
from adcm_aio_client.objects._base import RootInteractiveObject
from adcm_aio_client.objects._common import Deletable
from adcm_aio_client.objects.rbac._types import LocalUserData, LocalUserLazy, SourceType, UserKwargs, UserStatus


def new_user(**kwargs: Unpack[UserKwargs]) -> LocalUserData:
    if not all((kwargs.get("username"), kwargs.get("password"))):
        raise ValueError('"username" and "password" are mandatory to create a user')

    return LocalUserData.model_validate(kwargs)


class _UserBase:
    PATH_PREFIX = "rbac/users"
    _data: dict

    @cached_property
    def id(self: Self) -> int:
        # it's the default behavior, without id many things can't be done
        return int(self._data["id"])

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

    @property
    def status(self: Self) -> UserStatus:
        if self._data.get("blockingReason"):
            return UserStatus.INACTIVE

        return UserStatus.ACTIVE

    @async_cached_property
    async def groups(self: Self) -> list:  # TODO: list[Union["LocalGroup", "LDAPGroup"]]
        return []
        # group_ids = [group["id"] for group in self._data["groups"]] or [-1]
        #
        # return await GroupsNode(path=("rbac", "groups"), requester=self._requester).filter(id__in=group_ids)

    @property
    def _repr(self: Self) -> str:
        return f"<{self.__class__.__name__} #{self.id} {self.username}>"

    def __str__(self: Self) -> str:
        return self._repr

    def __repr__(self: Self) -> str:
        return self._repr


class LocalUser(Deletable, _UserBase, RootInteractiveObject):
    def edit(self: Self, **kwargs: Unpack[UserKwargs]) -> LocalUserLazy:
        return LocalUserLazy(**{"id": self.id, "requester": self._requester, **kwargs})


class LDAPUser(_UserBase, RootInteractiveObject):
    pass


class UsersNode(PaginatedAccessor[LocalUser | LDAPUser]):
    filtering = Filtering(
        FilterByID, FilterBy("username", ALL_OPERATIONS, str), FilterBy("group", COMMON_OPERATIONS, int)
    )

    def new(self: Self, **kwargs: Unpack[UserKwargs]) -> LocalUserLazy:
        if not all((kwargs.get("username"), kwargs.get("password"))):
            raise ValueError('"username" and "password" are mandatory to create a user')

        return LocalUserLazy(**{"requester": self._requester, **kwargs})

    async def init(self: Self, user: LocalUserData) -> LocalUser:
        if not isinstance(user, LocalUserData):
            raise TypeError(f"Expected a {LocalUserData} object, got {type(user)}")

        post_data = user.model_dump(exclude={"id"}, exclude_defaults=True, exclude_unset=True)
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
