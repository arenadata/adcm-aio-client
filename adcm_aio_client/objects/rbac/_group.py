from collections.abc import Collection
from typing import TYPE_CHECKING, Annotated, NotRequired, Self, TypedDict, Union, Unpack

from asyncstdlib.functools import cached_property as async_cached_property  # noqa: N813
from pydantic import Field

from adcm_aio_client.objects._base import RootInteractiveObject, WithCachedID, WithRequesterProperty
from adcm_aio_client.objects._common import Deletable, WithSaveMethod
from adcm_aio_client.objects.rbac._types import LocalGroupData
from adcm_aio_client.requesters import DefaultRequester

if TYPE_CHECKING:
    from adcm_aio_client.objects.rbac._user import LDAPUser, LocalUser


class _GroupKwargs(TypedDict):
    display_name: NotRequired[str | None]
    description: NotRequired[str | None]
    users: NotRequired[Collection[Union["LocalUser", "LDAPUser"]] | None]


def new(**kwargs: Unpack[_GroupKwargs]) -> LocalGroupData:
    if not kwargs.get("display_name"):
        raise ValueError('"display_name" is mandatory to create a group')

    return LocalGroupData.model_validate(kwargs)


class _GroupBase(WithCachedID, WithRequesterProperty):
    PATH_PREFIX = "rbac/groups"

    @property
    def display_name(self: Self) -> str:
        return self._data["displayName"]

    @property
    def description(self: Self) -> str:
        return self._data["description"]

    @async_cached_property
    async def users(self: Self) -> list[Union["LocalUser", "LDAPUser"]]:
        from adcm_aio_client.objects.rbac._nodes import UsersNode

        ids = [user["id"] for user in self._data["users"]] or [-1]

        return await UsersNode(path=("rbac", "users"), requester=self.requester).filter(id__in=ids)


class LocalGroup(Deletable, _GroupBase, RootInteractiveObject):
    def edit(self: Self, **kwargs: Unpack[_GroupKwargs]) -> "LocalGroupLazy":
        return LocalGroupLazy.model_validate({"id": self.id, "requester": self._requester, **kwargs})


class LocalGroupLazy(LocalGroupData, WithSaveMethod[LocalGroup]):
    """LocalGroupData with requester, can perform group create / update operations"""

    _cls = LocalGroup
    _url_part = "rbac/groups"

    requester: Annotated[DefaultRequester, Field(exclude=True)]  # pyright: ignore[reportIncompatibleVariableOverride]


class LDAPGroup(_GroupBase, RootInteractiveObject):
    pass
