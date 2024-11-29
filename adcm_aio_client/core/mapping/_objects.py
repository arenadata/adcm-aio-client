from collections import deque
from collections.abc import Generator
from functools import cached_property
from typing import Iterable, NamedTuple, Self

from copy import copy

from adcm_aio_client.core.mapping.refresh import MappingRefreshStrategy
from adcm_aio_client.core.types import WithID

# todo place real types
type Component = WithID
type Host = WithID

type ComponentID = int
type HostID = int

type MappingPair = tuple[Component, Host]

class MappingEntry(NamedTuple):
    host_id: HostID
    component_id: ComponentID

type HostMappingFilter = dict

class ComponentsMappingNode:
    ...

class HostsMappingNode:
    ...

class Mapping:
    def __init__(self, entries: Iterable[MappingPair]) -> None:
        self._initial: deque[MappingEntry]= deque()

        self._components: dict[ComponentID, Component] = {}
        self._hosts: dict[HostID, Host] = {}

        self._register_initial_entries(entries)

        self._current: deque[MappingEntry] = copy(self._initial)

    def save(self: Self) -> Self:
        ...

    def empty(self: Self) -> Self:
        ...

    def refresh(self: Self, strategy: MappingRefreshStrategy) -> Self:
        ...

    def all(self: Self) -> list[MappingPair]:
        return list(self.iter())

    def iter(self: Self) -> Generator[MappingPair]:
        ...


    async def add(self: Self, component: Component | Iterable[Component], host: Host | Iterable[Host] | HostMappingFilter) -> Self:
        ...

    async def remove(self: Self, component: Component | Iterable[Component], host: Host | Iterable[Host] | HostMappingFilter) -> Self:
        ...

    @cached_property
    def components(self: Self) -> ComponentsMappingNode:
        ...

    @cached_property
    def hosts(self: Self) -> HostsMappingNode:
        ...

    def _register_initial_entries(self: Self, entries: Iterable[MappingPair]) -> None:
        for component, host in entries:
            self._components[component.id] = component
            self._hosts[host.id] = host
            self._initial.append(MappingEntry(host_id=host.id, component_id=component.id))

