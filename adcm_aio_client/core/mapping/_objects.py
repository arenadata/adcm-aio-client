from __future__ import annotations

from collections.abc import Generator
from copy import copy
from functools import cached_property
from typing import TYPE_CHECKING, Any, Iterable, Self

from adcm_aio_client.core.mapping.refresh import apply_local_changes
from adcm_aio_client.core.mapping.types import LocalMappings, MappingEntry, MappingPair, MappingRefreshStrategy
from adcm_aio_client.core.objects._accessors import NonPaginatedAccessor
from adcm_aio_client.core.types import ComponentID, HostID, Requester

if TYPE_CHECKING:
    from adcm_aio_client.core.objects.cm import Cluster, Component, Host, HostsAccessor, Service

#    @async_cached_property
#    async def _cluster_path(self: Self) -> Endpoint:
#        from adcm_aio_client.core.objects.cm import Cluster, Service, Component, Host
#
#        cluster_id = None
#
#        if isinstance(self._owner, Cluster):
#            cluster_id = self._owner.id
#        elif isinstance(self._owner, Service):
#            cluster_id = self._owner.cluster.id
#        elif isinstance(self._owner, Component):
#            cluster_id = self._owner.cluster.id
#        elif isinstance(self._owner, Host):
#            cluster = await self._owner.cluster
#            if cluster is None:
#                message = f"Host {self._owner.name} isn't bound to cluster ""or it's not refreshed"
#                raise HostNotInCluster(message)
#
#            cluster_id = cluster.id
#
#        if cluster_id is None:
#            message = f"No cluster in hierarchy for {self._owner}"
#            raise RuntimeError(message)
#
#        return "clusters", cluster_id


class ComponentsMappingNode(NonPaginatedAccessor[Component, None]):
    def __new__(cls: type[Self], cluster: Cluster, requester: Requester) -> Self:
        if not hasattr(cls, "class_type"):
            from adcm_aio_client.core.objects.cm import Component

            cls.class_type = Component

        class_ = super().__new__(cls)

        return class_

    def __init__(self: Self, cluster: Cluster, requester: Requester) -> None:
        path = (*cluster.get_own_path(), "mapping", "components")
        super().__init__(path=path, requester=requester, accessor_filter=None)
        self._cluster = cluster

    def _create_object(self: Self, data: dict[str, Any]) -> Component:
        from adcm_aio_client.core.objects.cm import Service

        # service data here should be enough,
        # when not, we should use lazy objects
        # or request services (means it should be async) + caches
        service = Service(parent=self._cluster, data=data["service"])
        return self.class_type(parent=service, data=data)


class ActionMapping:
    def __init__(
        self: Self, owner: Cluster | Service | Component | Host, cluster: Cluster, entries: Iterable[MappingPair]
    ) -> None:
        self._owner = owner
        self._cluster = cluster
        self._requester = self._owner.requester

        self._components: dict[ComponentID, Component] = {}
        self._hosts: dict[HostID, Host] = {}

        self._initial: set[MappingEntry] = set()

        for component, host in entries:
            self._components[component.id] = component
            self._hosts[host.id] = host
            self._initial.add(MappingEntry(host_id=host.id, component_id=component.id))

        self._current: set[MappingEntry] = copy(self._initial)

    def empty(self: Self) -> Self:
        self._current.clear()
        return self

    def all(self: Self) -> list[MappingPair]:
        return list(self.iter())

    def iter(self: Self) -> Generator[MappingPair, None, None]:
        for entry in self._current:
            yield (self._components[entry.component_id], self._hosts[entry.host_id])

    async def add(self: Self, component: Component | Iterable[Component], host: Host | Iterable[Host]) -> Self:
        components, hosts = self._ensure_collections(component=component, host=host)
        to_add = self._to_entries(components=components, hosts=hosts)

        self._current |= to_add

        return self

    async def remove(self: Self, component: Component | Iterable[Component], host: Host | Iterable[Host]) -> Self:
        components, hosts = self._ensure_collections(component=component, host=host)
        to_remove = self._to_entries(components=components, hosts=hosts)

        self._current -= to_remove

        return self

    @cached_property
    def components(self: Self) -> ComponentsMappingNode:
        return ComponentsMappingNode(cluster=self._cluster, requester=self._owner.requester)

    @cached_property
    def hosts(self: Self) -> HostsAccessor:
        from adcm_aio_client.core.objects.cm import HostsAccessor

        cluster_path = self._cluster.get_own_path()

        return HostsAccessor(path=cluster_path, requester=self._owner.requester)

    def _ensure_collections(
        self: Self, component: Component | Iterable[Component], host: Host | Iterable[Host]
    ) -> tuple[Iterable[Component], Iterable[Host]]:
        if isinstance(component, Component):
            component = (component,)

        if isinstance(host, Host):
            host = (host,)

        return component, host

    def _to_entries(self: Self, components: Iterable[Component], hosts: Iterable[Host]) -> set[MappingEntry]:
        return {MappingEntry(host_id=host.id, component_id=component.id) for host in hosts for component in components}

    def _to_payload(self: Self) -> list[dict]:
        return [{"componentId": entry.component_id, "hostId": entry.host_id} for entry in self._current]


class ClusterMapping(ActionMapping):
    def __init__(self: Self, owner: Cluster, entries: Iterable[MappingPair]) -> None:
        super().__init__(owner=owner, cluster=owner, entries=entries)

    async def save(self: Self) -> Self:
        data = self._to_payload()

        await self._requester.post(*self._cluster.get_own_path(), "mapping", data=data)

        self._initial = copy(self._current)

        return self

    async def refresh(self: Self, strategy: MappingRefreshStrategy = apply_local_changes) -> Self:
        response = await self._requester.get(*self._cluster.get_own_path(), "mapping")
        remote = {MappingEntry(**entry) for entry in response.as_list()}

        local = LocalMappings(initial=self._initial, current=self._current)
        merged_mapping = strategy(local=local, remote=remote)

        # todo ensure all hosts and components exist in caches
        self._initial = merged_mapping
        self._current = copy(merged_mapping)

        return self
