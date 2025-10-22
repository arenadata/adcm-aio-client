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

from abc import abstractmethod
from collections.abc import Callable
from functools import cached_property
from typing import Any, Literal, Self

from asyncstdlib.functools import cached_property as async_cached_property  # noqa: N813

from adcm_aio_client._types import Refreshable
from adcm_aio_client.actions._objects import ActionsAccessor, UpgradeNode
from adcm_aio_client.config._objects import ConfigHistoryNode, ConfigOwner, HostGroupConfig, ObjectConfig
from adcm_aio_client.objects._base import AwareOfOwnPath, MaintenanceMode, WithProtectedRequester, WithRequesterProperty
from adcm_aio_client.objects._imports import Imports


class Deletable(WithProtectedRequester, AwareOfOwnPath):
    async def delete(self: Self) -> None:
        await self._requester.delete(*self.get_own_path())


class WithStatus(WithProtectedRequester, AwareOfOwnPath):
    async def get_status(self: Self) -> str:
        response = await self._requester.get(*self.get_own_path())
        return response.as_dict()["status"]


class WithActions(WithProtectedRequester, AwareOfOwnPath):
    @cached_property
    def actions(self: Self) -> ActionsAccessor:
        # `WithActions` can actually be InteractiveObject, but it isn't required
        # based on usages, so for now it's just ignore
        return ActionsAccessor(parent=self, path=(*self.get_own_path(), "actions"), requester=self._requester)  # type: ignore[reportArgumentType]


class WithConfig(ConfigOwner):
    @async_cached_property
    async def config(self: Self) -> ObjectConfig:
        return await self.config_history.current()

    @cached_property
    def config_history(self: Self) -> ConfigHistoryNode[ObjectConfig]:
        return ConfigHistoryNode(parent=self, as_type=ObjectConfig)


class WithConfigOfHostGroup(ConfigOwner):
    @async_cached_property
    async def config(self: Self) -> HostGroupConfig:
        return await self.config_history.current()

    @cached_property
    def config_history(self: Self) -> ConfigHistoryNode[HostGroupConfig]:
        return ConfigHistoryNode(parent=self, as_type=HostGroupConfig)


class WithUpgrades(WithProtectedRequester, AwareOfOwnPath):
    @cached_property
    def upgrades(self: Self) -> UpgradeNode:
        return UpgradeNode(parent=self, path=(*self.get_own_path(), "upgrades"), requester=self._requester)  # type: ignore[reportTypeArgument]


class WithMaintenanceMode(WithProtectedRequester, AwareOfOwnPath):
    @async_cached_property
    async def maintenance_mode(self: Self) -> MaintenanceMode:
        maintenance_mode = MaintenanceMode(self._data["maintenanceMode"], self._requester, self.get_own_path())  # pyright: ignore[reportAttributeAccessIssue]
        self._data["maintenanceMode"] = maintenance_mode.value  # pyright: ignore[reportAttributeAccessIssue]
        return maintenance_mode


class WithJobStatus(WithProtectedRequester, AwareOfOwnPath):
    async def get_job_status(self: Self) -> str:
        response = await self._requester.get(*self.get_own_path())
        return response.as_dict()["status"]


class WithImports(WithProtectedRequester, AwareOfOwnPath):
    @async_cached_property
    async def imports(self: Self) -> Imports:
        return Imports(requester=self._requester, path=(*self.get_own_path(), "imports"))


class LazyObject(WithRequesterProperty, AwareOfOwnPath, Refreshable):
    def __init__(self: Self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        self._manually_set = set()

    @property
    def id(self: Self) -> int | None:
        """May be `None` if object was created manually and not saved yet"""
        return self._data.get("id")

    async def save(self: Self) -> None:
        if self.id is None:  # create
            url = (self.PATH_PREFIX,)  # pyright: ignore[reportAttributeAccessIssue]
            method = self.requester.post
            data = self._prepare_data_for_save(mode="create")
        else:  # update
            url = self.get_own_path()
            method = self.requester.patch
            data = self._prepare_data_for_save(mode="update")

        response = await method(*url, data=data)
        self._data = response.as_dict()
        self._manually_set.clear()

    async def refresh(self: Self) -> Self:
        self._manually_set.clear()
        return await super().refresh()  # pyright: ignore[reportAbstractUsage]

    @abstractmethod
    def _prepare_data_for_save(self: Self, mode: Literal["create", "update"]) -> dict: ...


class ConfigurableSetAttrMixin:
    _custom_setattr: dict[str, Callable[[Self, str, Any], Any]]

    def __setattr__(self: Self, key: str, value: Any) -> None:  # noqa: ANN401
        if key in self._custom_setattr:
            self._custom_setattr[key](self, key, value)
        else:
            super().__setattr__(key, value)
