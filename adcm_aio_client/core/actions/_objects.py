from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING, Any, Self

from asyncstdlib import cached_property as async_cached_property

from adcm_aio_client.core.config._objects import ActionConfig
from adcm_aio_client.core.config.types import ConfigData
from adcm_aio_client.core.errors import (
    ConflictError,
    HostNotInClusterError,
    NoConfigInActionError,
    NoMappingInActionError,
    ObjectBlockedError
)
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

        await self._ensure_rich_data()

        data = {"isVerbose": self._verbose, "shouldBlockObject": self._blocking}
        if self._has_mapping:
            mapping = await self.mapping
            data |= {"hostComponentMap": mapping._to_payload()}
        if self._has_config:
            config = await self.config
            data |= {"configuration": config._to_payload()}

        try:
            response = await self._requester.post(*self.get_own_path(), "run", data=data)
        except ConflictError as e:
            if "has issue" in str(e):
                raise ObjectBlockedError(*e.args) from None
            raise

        return Job(requester=self._requester, data=response.as_dict())

    @async_cached_property
    async def mapping(self: Self) -> ActionMapping:
        await self._ensure_rich_data()

        if not self._has_mapping:
            message = f"Action {self.display_name} doesn't allow mapping changes"
            raise NoMappingInActionError(message)

        cluster = await detect_cluster(owner=self._parent)
        mapping = await cluster.mapping
        entries = mapping.all()

        return ActionMapping(owner=self._parent, cluster=cluster, entries=entries)

    @async_cached_property
    async def config(self: Self) -> ActionConfig:
        await self._ensure_rich_data()

        if not self._has_config:
            message = f"Action {self.display_name} doesn't allow config changes"
            raise NoConfigInActionError(message)

        configuration = self._configuration
        data = ConfigData.from_v2_response(data_in_v2_format=configuration)
        schema = configuration["configSchema"]

        return ActionConfig(schema=schema, config=data, parent=self)

    @property
    def _is_full_data_loaded(self: Self) -> bool:
        return "hostComponentMapRules" in self._data

    @property
    def _has_mapping(self: Self) -> bool:
        return bool(self._mapping_rule)

    @property
    def _has_config(self: Self) -> bool:
        return bool(self._configuration)

    @property
    def _mapping_rule(self: Self) -> list[dict]:
        try:
            return self._data["hostComponentMapRules"]
        except KeyError as e:
            message = (
                "Failed to retrieve mapping rules. "
                "Most likely action was initialized with partial data."
                " Need to load all data"
            )
            raise KeyError(message) from e

    @property
    def _configuration(self: Self) -> dict:
        try:
            return self._data["configuration"]
        except KeyError as e:
            message = (
                "Failed to retrieve configuration section. "
                "Most likely action was initialized with partial data."
                " Need to load all data"
            )
            raise KeyError(message) from e

    async def _ensure_rich_data(self: Self) -> None:
        if self._is_full_data_loaded:
            return

        self._data = await self._retrieve_data()


class ActionsAccessor[Parent: InteractiveObject](NonPaginatedChildAccessor[Parent, Action]):
    class_type = Action
    filtering = Filtering(FilterByName, FilterByDisplayName)


class Upgrade(Action):
    PATH_PREFIX = "upgrades"

    @property
    def bundle(self: Self) -> Bundle:
        from adcm_aio_client.core.objects.cm import Bundle

        return Bundle(requester=self._requester, data=self._data["bundle"])


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
