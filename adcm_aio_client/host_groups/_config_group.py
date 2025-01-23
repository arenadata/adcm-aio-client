# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from functools import cached_property
from typing import TYPE_CHECKING, Self, Union

from adcm_aio_client._filters import FilterByName, Filtering
from adcm_aio_client._types import AwareOfOwnPath, WithProtectedRequester
from adcm_aio_client.host_groups._common import HostGroupNode, HostsInHostGroupNode
from adcm_aio_client.objects._base import InteractiveChildObject
from adcm_aio_client.objects._common import Deletable, WithConfigOfHostGroup

if TYPE_CHECKING:
    from adcm_aio_client.objects import Cluster, Component, Service


class ConfigHostGroup(InteractiveChildObject, Deletable, WithConfigOfHostGroup):
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
    filtering = Filtering(FilterByName)
    # TODO: create() with `config` arg


class HostsInConfigHostGroupNode(HostsInHostGroupNode):
    group_type = "config"


class WithConfigHostGroups(WithProtectedRequester, AwareOfOwnPath):
    @cached_property
    def config_host_groups(self: Self) -> ConfigHostGroupNode:
        return ConfigHostGroupNode(
            parent=self,  # pyright: ignore[reportArgumentType]  easier to ignore than fix this typing
            path=(*self.get_own_path(), "config-groups"),
            requester=self._requester,
        )
