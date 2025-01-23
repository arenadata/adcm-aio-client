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

from collections.abc import Collection, Iterable
from typing import TYPE_CHECKING, Self, Union

from adcm_aio_client._types import Endpoint, Requester

if TYPE_CHECKING:
    from adcm_aio_client.objects import Cluster, Service


class Imports:
    def __init__(self: Self, requester: Requester, path: Endpoint) -> None:
        self._requester = requester
        self._path = path

    async def _get_source_binds(self: Self) -> set[tuple[int, str]]:
        response = await self._requester.get(*self._path)
        data_binds = set()

        for import_data in response.as_dict()["results"]:
            binds = import_data.get("binds", [])
            for bind in binds:
                bind_id = int(bind["source"]["id"])
                bind_type = bind["source"]["type"]
                data_binds.add((bind_id, bind_type))

        return data_binds

    def _create_post_data(self: Self, binds: Iterable[tuple[int, str]]) -> list[dict[str, dict[str, int | str]]]:
        return [{"source": {"id": source[0], "type": source[1]}} for source in binds]

    def _sources_to_binds(self: Self, sources: Collection[Union["Cluster", "Service"]]) -> set[tuple[int, str]]:
        return {(s.id, s.__class__.__name__.lower()) for s in sources}

    async def add(self: Self, sources: Collection[Union["Cluster", "Service"]]) -> None:
        current_binds = await self._get_source_binds()
        sources_binds = self._sources_to_binds(sources)
        binds_to_set = current_binds.union(sources_binds)
        await self._requester.post(*self._path, data=self._create_post_data(binds_to_set))

    async def set(self: Self, sources: Collection[Union["Cluster", "Service"]]) -> None:
        binds_to_set = self._sources_to_binds(sources)
        await self._requester.post(*self._path, data=self._create_post_data(binds_to_set))

    async def remove(self: Self, sources: Collection[Union["Cluster", "Service"]]) -> None:
        current_binds = await self._get_source_binds()
        sources_binds = self._sources_to_binds(sources)
        binds_to_set = current_binds.difference(sources_binds)
        await self._requester.post(*self._path, data=self._create_post_data(binds_to_set))
