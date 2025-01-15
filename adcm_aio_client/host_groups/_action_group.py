from functools import cached_property
from typing import TYPE_CHECKING, Self, Union

from adcm_aio_client._filters import FilterByName, Filtering
from adcm_aio_client._types import AwareOfOwnPath, WithProtectedRequester
from adcm_aio_client.host_groups._common import HostGroupNode, HostsInHostGroupNode
from adcm_aio_client.objects._base import InteractiveChildObject
from adcm_aio_client.objects._common import Deletable, WithActions

if TYPE_CHECKING:
    from adcm_aio_client.objects import Cluster, Component, Service


class ActionHostGroup(InteractiveChildObject, WithActions, Deletable):
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


class ActionHostGroupNode(HostGroupNode[Union["Cluster", "Service", "Component"], ActionHostGroup]):
    class_type = ActionHostGroup
    filtering = Filtering(FilterByName)


class HostsInActionHostGroupNode(HostsInHostGroupNode):
    group_type = "action"


class WithActionHostGroups(WithProtectedRequester, AwareOfOwnPath):
    @cached_property
    def action_host_groups(self: Self) -> ActionHostGroupNode:
        return ActionHostGroupNode(
            parent=self,  # pyright: ignore[reportArgumentType]  easier to ignore than fix this typing
            path=(*self.get_own_path(), "action-host-groups"),
            requester=self._requester,
        )
