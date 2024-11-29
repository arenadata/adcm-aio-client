from functools import cached_property
from typing import Self

from adcm_aio_client.core.config import ConfigHistoryNode, ObjectConfig
from adcm_aio_client.core.config._objects import ConfigOwner
from adcm_aio_client.core.objects._base import WithProtectedRequester
from adcm_aio_client.core.actions import ActionsAccessor
from adcm_aio_client.core.types import ADCMEntityStatus, AwareOfOwnPath


class Deletable(WithProtectedRequester, AwareOfOwnPath):
    async def delete(self: Self) -> None:
        await self._requester.delete(*self.get_own_path())


class WithStatus(WithProtectedRequester, AwareOfOwnPath):
    async def get_status(self: Self) -> ADCMEntityStatus:
        response = await self._requester.get(*self.get_own_path())
        return ADCMEntityStatus(response.as_dict()["status"])


class WithActions(WithRequester, AwareOfOwnPath):
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


class WithActions(WithProtectedRequester, AwareOfOwnPath):
    @cached_property
    def actions(self: Self) -> ...: ...


class WithUpgrades(WithProtectedRequester, AwareOfOwnPath):
    @cached_property
    def upgrades(self: Self) -> ...: ...


class WithConfigGroups(WithProtectedRequester, AwareOfOwnPath):
    @cached_property
    def config_groups(self: Self) -> ...: ...


class WithActionHostGroups(WithProtectedRequester, AwareOfOwnPath):
    @cached_property
    def action_host_groups(self: Self) -> ...: ...
