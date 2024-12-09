from functools import cached_property
from typing import TYPE_CHECKING, Self, Union

from adcm_aio_client.core.host_groups._common import HostGroupNode, HostInHostGroupNode
from adcm_aio_client.core.objects._base import InteractiveChildObject
from adcm_aio_client.core.objects._common import Deletable, WithConfig
from adcm_aio_client.core.types import AwareOfOwnPath, WithProtectedRequester

if TYPE_CHECKING:
    from adcm_aio_client.core.objects.cm import Cluster, Component, Service


class ConfigHostGroup(InteractiveChildObject, Deletable, WithConfig):
    PATH_PREFIX = "config-groups"

    @property
    def name(self: Self) -> str:
        return self._data["name"]

    @property
    def description(self: Self) -> str:
        return self._data["description"]

    @cached_property
    def hosts(self: Self) -> "HostsInConfigHostGroupNode":
        return HostsInConfigHostGroupNode(path=(*self.get_own_path(), "hosts"), requester=self._requester)


class ConfigHostGroupNode(HostGroupNode[Union["Cluster", "Service", "Component"], ConfigHostGroup]):
    class_type = ConfigHostGroup
    # TODO: create() with `config` arg


class HostsInConfigHostGroupNode(HostInHostGroupNode):
    group_type = "config"


class WithConfigHostGroups(WithProtectedRequester, AwareOfOwnPath):
    @cached_property
    def config_host_groups(self: Self) -> ConfigHostGroupNode:
        return ConfigHostGroupNode(
            parent=self,  # pyright: ignore[reportArgumentType]  easier to ignore than fix this typing
            path=(*self.get_own_path(), "config-groups"),
            requester=self._requester,
        )
