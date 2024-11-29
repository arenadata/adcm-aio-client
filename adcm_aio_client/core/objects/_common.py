from functools import cached_property
from typing import Self

from adcm_aio_client.core.actions import ActionsAccessor
from adcm_aio_client.core.types import ADCMEntityStatus, AwareOfOwnPath, WithRequester


class Deletable(WithRequester, AwareOfOwnPath):
    async def delete(self: Self) -> None:
        await self._requester.delete(*self.get_own_path())


class WithStatus(WithRequester, AwareOfOwnPath):
    async def get_status(self: Self) -> ADCMEntityStatus:
        response = await self._requester.get(*self.get_own_path())
        return ADCMEntityStatus(response.as_dict()["status"])


class WithActions(WithRequester, AwareOfOwnPath):
    @cached_property
    def actions(self: Self) -> ActionsAccessor:
        return ActionsAccessor(parent=self, path=(*self.get_own_path(), "actions"), requester=self._requester)


# todo whole section lacking implementation (and maybe code move is required)
class WithConfig(WithRequester, AwareOfOwnPath):
    @cached_property
    def config(self: Self) -> ...: ...

    @cached_property
    def config_history(self: Self) -> ...: ...


class WithUpgrades(WithRequester, AwareOfOwnPath):
    @cached_property
    def upgrades(self: Self) -> ...: ...


class WithConfigGroups(WithRequester, AwareOfOwnPath):
    @cached_property
    def config_groups(self: Self) -> ...: ...


class WithActionHostGroups(WithRequester, AwareOfOwnPath):
    @cached_property
    def action_host_groups(self: Self) -> ...: ...
