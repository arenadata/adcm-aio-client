from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple, Protocol, Self

from adcm_aio_client._types import ComponentID, HostID

if TYPE_CHECKING:
    from adcm_aio_client.objects import Component, Host


type MappingPair = tuple[Component, Host]


class MappingEntry(NamedTuple):
    host_id: HostID
    component_id: ComponentID


type MappingData = set[MappingEntry]


class LocalMappings(NamedTuple):
    initial: MappingData
    current: MappingData


class MappingRefreshStrategy(Protocol):
    def __call__(self: Self, local: LocalMappings, remote: MappingData) -> MappingData: ...  # noqa: ANN101
