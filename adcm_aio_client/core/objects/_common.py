from functools import cached_property
from typing import Self

from adcm_aio_client.core.objects._base import AwareOfOwnPath, WithRequester
from adcm_aio_client.core.types import ADCMEntityStatus


class Deletable(WithRequester, AwareOfOwnPath):
    async def delete(self: Self) -> None:
        await self._requester.delete(*self.get_own_path())


class HasStatus(WithRequester, AwareOfOwnPath):
    async def get_status(self: Self) -> ADCMEntityStatus:
        response = await self._requester.get(*self.get_own_path())
        return ADCMEntityStatus(response.as_dict()["status"])


# todo whole section lacking implementation (and maybe code move is required)
class WithConfig(WithRequester, AwareOfOwnPath):
    @cached_property
    def config(self: Self) -> ...: ...

    @cached_property
    def config_history(self: Self) -> ...: ...


class WithActions(WithRequester, AwareOfOwnPath):
    @cached_property
    def actions(self: Self) -> ...: ...


class WithUpgrades(WithRequester, AwareOfOwnPath):
    @cached_property
    def upgrades(self: Self) -> ...: ...


class WithConfigGroups(WithRequester, AwareOfOwnPath):
    @cached_property
    def config_groups(self: Self) -> ...: ...


class WithActionHostGroups(WithRequester, AwareOfOwnPath):
    @cached_property
    def action_host_groups(self: Self) -> ...: ...
