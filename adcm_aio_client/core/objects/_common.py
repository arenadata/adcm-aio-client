from functools import cached_property
from typing import Self

from asyncstdlib.functools import cached_property as async_cached_property  # noqa: N813

from adcm_aio_client.core.actions import ActionsAccessor, UpgradeNode
from adcm_aio_client.core.config import ConfigHistoryNode, ObjectConfig
from adcm_aio_client.core.config._objects import ConfigOwner
from adcm_aio_client.core.objects._base import AwareOfOwnPath, MaintenanceMode, WithProtectedRequester


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
        return ActionsAccessor(parent=self, path=(*self.get_own_path(), "actions"), requester=self._requester)


# todo whole section lacking implementation (and maybe code move is required)
class WithConfig(ConfigOwner):
    @cached_property
    async def config(self: Self) -> ObjectConfig:
        return await self.config_history.current()

    @cached_property
    def config_history(self: Self) -> ConfigHistoryNode:
        return ConfigHistoryNode(parent=self)


class WithUpgrades(WithProtectedRequester, AwareOfOwnPath):
    @cached_property
    def upgrades(self: Self) -> UpgradeNode:
        return UpgradeNode(parent=self, path=(*self.get_own_path(), "upgrades"), requester=self._requester)


class WithMaintenanceMode(WithProtectedRequester, AwareOfOwnPath):
    @async_cached_property
    async def maintenance_mode(self: Self) -> MaintenanceMode:
        maintenance_mode = MaintenanceMode(self._data["maintenanceMode"], self._requester, self.get_own_path())  # pyright: ignore[reportAttributeAccessIssue]
        self._data["maintenanceMode"] = maintenance_mode  # pyright: ignore[reportAttributeAccessIssue]
        return maintenance_mode


class WithJobStatus(WithProtectedRequester, AwareOfOwnPath):
    async def get_job_status(self: Self) -> str:
        response = await self._requester.get(*self.get_own_path())
        return response.as_dict()["status"]
