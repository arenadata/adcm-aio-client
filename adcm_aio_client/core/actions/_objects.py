from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING, Any, Self

from asyncstdlib import cached_property as async_cached_property

from adcm_aio_client.core.errors import HostNotInClusterError, NoMappingRulesForActionError
from adcm_aio_client.core.filters import FilterByDisplayName, FilterByName, Filtering
from adcm_aio_client.core.mapping import ActionMapping
from adcm_aio_client.core.objects._accessors import NonPaginatedChildAccessor
from adcm_aio_client.core.objects._base import InteractiveChildObject, InteractiveObject

if TYPE_CHECKING:
    from adcm_aio_client.core.objects.cm import Bundle, Cluster, Job


class Action(InteractiveChildObject):
    PATH_PREFIX = "actions"

    def __init__(self: Self, parent: InteractiveObject, data: dict[str, Any]) -> None:
        super().__init__(parent, data)
        self._verbose = False
        self._blocking = True

    @property
    def verbose(self: Self) -> bool:
        return self._verbose

    @verbose.setter
    def verbose(self: Self, value: bool) -> bool:
        self._verbose = value
        return self._verbose

    @property
    def blocking(self: Self) -> bool:
        return self._blocking

    @blocking.setter
    def blocking(self: Self, value: bool) -> bool:
        self._blocking = value
        return self._blocking

    @cached_property
    def name(self: Self) -> str:
        return self._data["name"]

    @cached_property
    def display_name(self: Self) -> str:
        return self._data["displayName"]

    async def run(self: Self) -> Job:
        from adcm_aio_client.core.objects.cm import Job

        # todo build data for config and mapping
        data = {"isVerbose": self._verbose, "isBlocking": self._blocking}
        response = await self._requester.post(*self.get_own_path(), "run", data=data)
        job = Job(requester=self._requester, data=response.as_dict())
        return job

    @async_cached_property
    async def _mapping_rule(self: Self) -> list[dict] | None:
        return (await self._rich_data)["hostComponentMapRules"]

    @async_cached_property
    async def mapping(self: Self) -> ActionMapping:
        mapping_change_allowed = await self._mapping_rule
        if not mapping_change_allowed:
            message = f"Action {self.display_name} doesn't allow mapping changes"
            raise NoMappingRulesForActionError(message)

        cluster = await detect_cluster(owner=self._parent)
        mapping = await cluster.mapping
        entries = mapping.all()

        return ActionMapping(owner=self._parent, cluster=cluster, entries=entries)

    @async_cached_property  # TODO: Config class
    async def config(self: Self) -> ...:
        return (await self._rich_data)["configuration"]

    @async_cached_property
    async def _rich_data(self: Self) -> dict:
        return (await self._requester.get(*self.get_own_path())).as_dict()


class ActionsAccessor(NonPaginatedChildAccessor):
    class_type = Action
    filtering = Filtering(FilterByName, FilterByDisplayName)


class Upgrade(Action):
    PATH_PREFIX = "upgrades"

    @property
    def bundle(self: Self) -> Bundle:
        from adcm_aio_client.core.objects.cm import Bundle

        return Bundle(requester=self._requester, data=self._data["bundle"])

    @async_cached_property  # TODO: Config class
    async def config(self: Self) -> ...:
        return (await self._rich_data)["configuration"]

    def validate(self: Self) -> bool:
        return True


class UpgradeNode(NonPaginatedChildAccessor):
    class_type = Upgrade
    filtering = Filtering(FilterByName, FilterByDisplayName)


async def detect_cluster(owner: InteractiveObject) -> Cluster:
    from adcm_aio_client.core.objects.cm import Cluster, Component, Host, Service

    if isinstance(owner, Cluster):
        return owner

    if isinstance(owner, (Service, Component)):
        return owner.cluster

    if isinstance(owner, Host):
        cluster = await owner.cluster
        if cluster is None:
            message = f"Host {owner.name} isn't bound to cluster " "or it's not refreshed"
            raise HostNotInClusterError(message)

        return cluster

    message = f"No cluster in hierarchy for {owner}"
    raise RuntimeError(message)
