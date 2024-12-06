from functools import cached_property
from typing import TYPE_CHECKING, Self, Union

from adcm_aio_client.core.actions import ActionsAccessor
from adcm_aio_client.core.host_groups._common import HostGroupNode, HostInHostGroupNode
from adcm_aio_client.core.objects._base import InteractiveChildObject
from adcm_aio_client.core.objects._common import Deletable
from adcm_aio_client.core.types import AwareOfOwnPath, WithProtectedRequester

if TYPE_CHECKING:
    from adcm_aio_client.core.objects.cm import Cluster, Component, Service


class ActionHostGroup(InteractiveChildObject, Deletable):
    PATH_PREFIX = "action-host-groups"

    @property
    def name(self: Self) -> str:
        return self._data["name"]

    @property
    def description(self: Self) -> str:
        return self._data["description"]

    @cached_property
    def hosts(self: Self) -> "HostsInActionHostGroupNode":
        return HostsInActionHostGroupNode(path=(*self.get_own_path(), "hosts"), requester=self._requester)

    @cached_property
    def actions(self: Self) -> ...:
        return ActionsAccessor(parent=self, path=(*self.get_own_path(), "actions"), requester=self._requester)


class ActionHostGroupNode(HostGroupNode[Union["Cluster", "Service", "Component"], ActionHostGroup]):
    class_type = ActionHostGroup


class HostsInActionHostGroupNode(HostInHostGroupNode):
    group_type = "action"


class WithActionHostGroups(WithProtectedRequester, AwareOfOwnPath):
    @cached_property
    def action_host_groups(self: Self) -> ActionHostGroupNode:
        return ActionHostGroupNode(
            parent=self,  # pyright: ignore[reportArgumentType]  easier to ignore than fix this typing
            path=(*self.get_own_path(), "action-host-groups"),
            requester=self._requester,
        )
