from functools import partial
from typing import TYPE_CHECKING, Annotated, NotRequired, Self, TypedDict, Union, Unpack

from asyncstdlib.functools import cached_property as async_cached_property  # noqa: N813
from pydantic import Field

from adcm_aio_client.objects._base import RootInteractiveObject, WithCachedID
from adcm_aio_client.objects._common import Deletable, WithRequesterProperty, WithSaveMethod
from adcm_aio_client.objects.rbac._types import LocalUserData, UserStatus
from adcm_aio_client.objects.rbac._utils import validate_kwargs
from adcm_aio_client.requesters import DefaultRequester

if TYPE_CHECKING:
    from adcm_aio_client.objects.rbac._group import LDAPGroup, LocalGroup


class _UserKwargs(TypedDict):
    username: NotRequired[str]
    password: NotRequired[str]
    is_super_user: NotRequired[bool]
    first_name: NotRequired[str]
    last_name: NotRequired[str]
    email: NotRequired[str]
    groups: NotRequired[list["LocalGroup"]]


def new(**kwargs: Unpack[_UserKwargs]) -> LocalUserData:
    # cast kwargs to dict to remove `TypedDict is not dict` error
    _validate_user_kwargs(dict(kwargs))

    return LocalUserData.model_validate(kwargs)


class _UserBase(WithCachedID, WithRequesterProperty):
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

    @property
    def status(self: Self) -> UserStatus:
        if self._data.get("blockingReason"):
            return UserStatus.INACTIVE

        return UserStatus.ACTIVE

    @async_cached_property
    async def groups(self: Self) -> list[Union["LocalGroup", "LDAPGroup"]]:
        from adcm_aio_client.objects.rbac._nodes import GroupsNode

        ids = [group["id"] for group in self._data["groups"]] or [-1]

        return await GroupsNode(path=("rbac", "groups"), requester=self.requester).filter(id__in=ids)

    def __str__(self: Self) -> str:
        return self.__repr__()

    def __repr__(self: Self) -> str:
        return f"<{self.__class__.__name__} #{self.id} {self.username}>"


class LocalUser(Deletable, _UserBase, RootInteractiveObject):
    def edit(self: Self, **kwargs: Unpack[_UserKwargs]) -> "LocalUserLazy":
        return LocalUserLazy.model_validate({"id": self.id, "requester": self._requester, **kwargs})


class LocalUserLazy(LocalUserData, WithSaveMethod[LocalUser]):
    """LocalUserData with requester, can perform user create / update operations"""

    _cls = LocalUser
    _url_part = "rbac/users"

    requester: Annotated[DefaultRequester, Field(exclude=True)]  # pyright: ignore[reportIncompatibleVariableOverride]


class LDAPUser(_UserBase, RootInteractiveObject):
    pass


_validate_user_kwargs = partial(
    validate_kwargs, mandatory_fields=["username", "password"], obj_type_name=LocalUser.__name__
)
