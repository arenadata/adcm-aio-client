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

from collections.abc import Callable, Coroutine, Iterable
from typing import TYPE_CHECKING
import asyncio

from adcm_aio_client.mapping._types import ComponentCache, HostCache, MappingPair, PayloadMappingEntries

if TYPE_CHECKING:
    pass


def _run_task_if_objects_are_missing(
    method: Callable[[dict], Coroutine], missing_objects: set[int]
) -> asyncio.Task | None:
    if not missing_objects:
        return None

    ids_str = ",".join(map(str, missing_objects))
    # limit in case there are more than 1 page of objects
    records_amount = len(missing_objects)
    query = {"id__in": ids_str, "limit": records_amount}

    return asyncio.create_task(method(query))


def _to_cache_entries(entries: Iterable[MappingPair]) -> tuple[HostCache, ComponentCache]:
    hosts = {}
    components = {}
    for component, host in entries:
        components[component.id] = component
        hosts[host.id] = host

    return hosts, components


def _calculate_base_mapping_entries(
    cluster_mapping_pairs: list[MappingPair],
    previous_cu_delta: dict[str, PayloadMappingEntries],
) -> PayloadMappingEntries:
    cluster_mapping_entries = [
        {"hostId": host.id, "componentId": component.id} for component, host in cluster_mapping_pairs
    ]

    removed_entries = {(entry["hostId"], entry["componentId"]) for entry in previous_cu_delta["remove"]}
    seen_entries = set()
    base_mapping_entries = []

    for entry in [*cluster_mapping_entries, *previous_cu_delta["add"]]:
        entry_key = (entry["hostId"], entry["componentId"])
        if entry_key in removed_entries or entry_key in seen_entries:
            continue

        seen_entries.add(entry_key)
        base_mapping_entries.append(entry)

    return base_mapping_entries
