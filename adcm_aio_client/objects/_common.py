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
from typing import Self

from asyncstdlib.functools import cached_property as async_cached_property  # noqa: N813

from adcm_aio_client.actions._objects import ActionsAccessor, UpgradeNode
from adcm_aio_client.config._objects import ConfigHistoryNode, ConfigOwner, HostGroupConfig, ObjectConfig
from adcm_aio_client.objects._base import AwareOfOwnPath, MaintenanceMode, WithProtectedRequester
from adcm_aio_client.objects._imports import Imports


class Deletable(WithProtectedRequester, AwareOfOwnPath):
    """
    Mixin for objects that can be deleted
    """

    async def delete(self: Self) -> None:
        """
        Delete object from ADCM. Object can't be restored and it's node accessor must have 'Deletable' mixin

        Examples:
        ```python
            cluster = await client.clusters.get(name__eq="example")
            await cluster.delete()
        ```
        """
        await self._requester.delete(*self.get_own_path())


class WithStatus(WithProtectedRequester, AwareOfOwnPath):
    """
    Mixin for objects that have status
    """

    async def get_status(self: Self) -> str:
        """
        Returns current status of object whose node accessor has 'WithStatus' mixin

        Examples:
        ```python
            cluster = await client.clusters.get(name__eq="example")
            status = await cluster.get_status()
        ```
        """
        response = await self._requester.get(*self.get_own_path())
        return response.as_dict()["status"]


class WithActions(WithProtectedRequester, AwareOfOwnPath):
    """
    Mixin for objects that have actions
    """

    @cached_property
    def actions(self: Self) -> ActionsAccessor:
        """
        Returns actions accessor for object whose node accessor ('ActionsAccessor', 'ActionHostGroupNode',
        'HostsInActionHostGroupNode') has 'WithActions' mixin

        Examples:
        ```python
            cluster = await client.clusters.get(name__eq="example")
            actions = await cluster.actions.all()
        ```
        """
        # `WithActions` can actually be InteractiveObject, but it isn't required
        # based on usages, so for now it's just ignore
        return ActionsAccessor(parent=self, path=(*self.get_own_path(), "actions"), requester=self._requester)  # type: ignore[reportArgumentType]


class WithConfig(ConfigOwner):
    """
    Mixin for objects that have config
    """

    @async_cached_property
    async def config(self: Self) -> ObjectConfig:
        """
        Returns current config of object whose node accessor has 'WithConfig' mixin. (like 'ConfigHistoryNode')

        Examples:
        ```python
            cluster = await client.clusters.get(name__eq="example")
            config = await cluster.config
        ```
        """
        return await self.config_history.current()

    @cached_property
    def config_history(self: Self) -> ConfigHistoryNode[ObjectConfig]:
        """
        Returns config history of object whose node accessor has 'WithConfig' mixin

        Examples:
        ```python
            cluster = await client.clusters.get(name__eq="example")
            history = await cluster.config_history

            current_config = await history.current()
        ```
        """
        return ConfigHistoryNode(parent=self, as_type=ObjectConfig)


class WithConfigOfHostGroup(ConfigOwner):
    """
    Mixin for objects that have 'HostGroupNode' for host group config.
    """

    @async_cached_property
    async def config(self: Self) -> HostGroupConfig:
        """
        Returns current config of object whose node accessor
        has 'WithConfigOfHostGroup' mixin. (like 'ConfigHistoryNode')

        Examples:
        ```python
            cluster = await client.clusters.get(name__eq="example")
            group = await cluster.config_host_groups.get()
            config = await group.config
        ```
        """
        return await self.config_history.current()

    @cached_property
    def config_history(self: Self) -> ConfigHistoryNode[HostGroupConfig]:
        """
        Returns config history of object whose node accessor has 'WithConfigOfHostGroup' mixin

        Examples:
        ```python
            cluster = await client.clusters.get(name__eq="example")
            group = await cluster.config_host_groups.get()
            history = await group.config_history

            current_config = await history.current()
        ```
        """
        return ConfigHistoryNode(parent=self, as_type=HostGroupConfig)


class WithUpgrades(WithProtectedRequester, AwareOfOwnPath):
    """
    Mixin for objects that have 'Upgrade'
    """

    @cached_property
    def upgrades(self: Self) -> UpgradeNode:
        """
        Node responsible for accessing 'Upgrade' objects.<br>
        Returns 'UpgradeNode' for object whose node accessor has 'WithUpgrades' mixin

        Examples:
        ```python
            cluster = await client.clusters.get(name__eq="example")
            upgrades = await cluster.upgrades
        ```
        """
        return UpgradeNode(parent=self, path=(*self.get_own_path(), "upgrades"), requester=self._requester)  # type: ignore[reportTypeArgument]


class WithMaintenanceMode(WithProtectedRequester, AwareOfOwnPath):
    """
    Mixin for objects that have maintenance mode
    """

    @async_cached_property
    async def maintenance_mode(self: Self) -> MaintenanceMode:
        """
        Returns current maintenance mode ('MaintenanceMode')
        of object whose node accessor has 'WithMaintenanceMode' mixin

        Examples:
        ```python
            cluster = await client.clusters.get(name__eq="example")
            maintenance_mode = await cluster.maintenance_mode
        ```
        """
        maintenance_mode = MaintenanceMode(self._data["maintenanceMode"], self._requester, self.get_own_path())  # pyright: ignore[reportAttributeAccessIssue]
        self._data["maintenanceMode"] = maintenance_mode.value  # pyright: ignore[reportAttributeAccessIssue]
        return maintenance_mode


class WithJobStatus(WithProtectedRequester, AwareOfOwnPath):
    """
    Mixin for objects that have job status
    """

    async def get_job_status(self: Self) -> str:
        """
        Returns current job status of object whose node accessor has 'WithJobStatus' mixin

        Examples:
        ```python
            cluster = await client.clusters.get(name__eq="example")
            action = await cluster.actions.all()[0]
            job = await action.run()
            status = await job.get_status()
        ```
        """
        response = await self._requester.get(*self.get_own_path())
        return response.as_dict()["status"]


class WithImports(WithProtectedRequester, AwareOfOwnPath):
    """
    Mixin for objects that have imports (accessor: 'Imports')
    """

    @async_cached_property
    async def imports(self: Self) -> Imports:
        """
        Returns: 'Imports' node for object whose node accessor has 'WithImports' mixin

        Examples:
        ```python
            cluster = await client.clusters.get(name__eq="example")
            imports_node = await cluster.imports
            imports = await imports_node.all()
        ```
        """
        return Imports(requester=self._requester, path=(*self.get_own_path(), "imports"))
