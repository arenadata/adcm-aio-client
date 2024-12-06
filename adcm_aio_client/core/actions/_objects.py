from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING, Any, Self

from asyncstdlib import cached_property as async_cached_property

from adcm_aio_client.core.errors import HostNotInClusterError, NoMappingRulesForActionError
from adcm_aio_client.core.mapping import ActionMapping
from adcm_aio_client.core.objects._accessors import NonPaginatedChildAccessor
from adcm_aio_client.core.objects._base import InteractiveChildObject, InteractiveObject

if TYPE_CHECKING:
    from adcm_aio_client.core.objects.cm import Cluster


class Action(InteractiveChildObject):
    PATH_PREFIX = "actions"

    def __init__(self: Self, parent: InteractiveObject, data: dict[str, Any]) -> None:
        super().__init__(parent, data)
        self._verbose = False

    @cached_property
    def name(self: Self) -> str:
        return self._data["name"]

    @cached_property
    def display_name(self: Self) -> str:
        return self._data["displayName"]

    async def run(self: Self) -> dict:  # TODO: implement Task, return Task
        return (await self._requester.post(*self.get_own_path(), "run", data={"isVerbose": self._verbose})).as_dict()

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

    def set_verbose(self: Self) -> Self:
        self._verbose = True
        return self

    @async_cached_property  # TODO: Config class
    async def config(self: Self) -> ...:
        return (await self._rich_data)["configuration"]

    @async_cached_property
    async def _rich_data(self: Self) -> dict:
        return (await self._requester.get(*self.get_own_path())).as_dict()


class ActionsAccessor(NonPaginatedChildAccessor):
    class_type = Action


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
