from functools import cached_property
from typing import Annotated, NotRequired, Self, TypedDict, Unpack

from pydantic import Field

from adcm_aio_client.objects._base import RootInteractiveObject
from adcm_aio_client.objects._cm import Cluster, Component, Host, HostProvider, Service
from adcm_aio_client.objects._common import Deletable, WithSaveMethod
from adcm_aio_client.objects.rbac._types import CustomRoleData
from adcm_aio_client.objects.rbac._utils import validate_kwargs
from adcm_aio_client.requesters import DefaultRequester


class _RoleKwargs(TypedDict):
    name: NotRequired[str]
    display_name: NotRequired[str]
    description: NotRequired[str]
    permissions: NotRequired[list["Permission"]]


def new(**kwargs: Unpack[_RoleKwargs]) -> CustomRoleData:
    # cast kwargs to dict to remove `TypedDict is not dict` error
    validate_kwargs(dict(kwargs), mandatory_fields=["display_name", "permissions"], obj_type_name=CustomRole.__name__)

    return CustomRoleData.model_validate(kwargs)


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

    @cached_property
    def permissions(self: Self) -> list["Permission"]:
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


class BuiltInRole(_RoleBase): ...


class CustomRole(Deletable, _RoleBase):
    def edit(self: Self, **kwargs: Unpack[_RoleKwargs]) -> "CustomRoleLazy":
        return CustomRoleLazy.model_validate({"id": self.id, "requester": self._requester, **kwargs})


class CustomRoleLazy(CustomRoleData, WithSaveMethod[CustomRole]):
    """LocalGroupData with requester, can perform group create / update operations"""

    _cls = CustomRole
    _url_part = "rbac/roles"

    requester: Annotated[DefaultRequester, Field(exclude=True)]  # pyright: ignore[reportIncompatibleVariableOverride]


class Permission(RootInteractiveObject):
    @property
    def name(self: Self) -> str:
        return self._data["name"]

    @property
    def display_name(self: Self) -> str:
        return self._data["displayName"]
