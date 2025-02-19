# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple, Protocol, Self

from adcm_aio_client._types import ComponentID, HostID

if TYPE_CHECKING:
    from adcm_aio_client.objects import Component, Host


type MappingPair = tuple["Component", "Host"]


class MappingEntry(NamedTuple):
    host_id: HostID
    component_id: ComponentID


type MappingData = set[MappingEntry]


class LocalMappings(NamedTuple):
    initial: MappingData
    current: MappingData


class MappingRefreshStrategy(Protocol):
    def __call__(self: Self, local: LocalMappings, remote: MappingData) -> MappingData: ...  # noqa: ANN101
