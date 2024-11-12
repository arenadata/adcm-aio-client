# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from functools import cached_property
from typing import Literal, Protocol, Self

from adcm_aio_client.core.accessors import PaginatedAccessor
from adcm_aio_client.core.requesters import Requester
from adcm_aio_client.core.types import AwaredOfOwnPath


class WithRequester(Protocol):
    _requester: Requester

_Unset = object

class InteractiveObject:

    def __init_subclass__(cls) -> None:
        for name in cls.__annotations__:
            if name.startswith("_"):
                continue

            def retrieve_from_data(self: Self, name_: str=name, cached_name: str = f"_{name}"):
                cached = getattr(self, cached_name, _Unset)
                if cached is not _Unset:
                    return cached

                result = self._data[name_]
                setattr(self, cached_name, result)
                return result

            setattr(cls, name, property(retrieve_from_data))

    def __init__(self,
                 requester: Requester,
                 data: dict,
                 ) -> None:
        self._requester = requester
        self._data = data

class Deletable(WithRequester, AwaredOfOwnPath):

    async def delete(self) -> None:
        await self._requester.delete(*self.get_own_path())

class Cluster(InteractiveObject, Deletable):
    # own parameters
    id: int
    name: str
    description: str

    # calculatable fields
    @property
    async def status(self) -> Literal["up", "down"]:
        # reread object and update only one field
        return "down"

    # managers and accessors

#    bundle: "Bundle"
#    config: "Config"
#    mapping: "Mapping"


    @cached_property
    def services(self) ->"ServicesNode":
        return ServicesNode(requester=self._requester, parent=self)

    # own functionality

    def get_own_path(self) -> tuple[str | int, ...]:
        return ("clusters", self.id)

    async def rename(self: Self, name: str) -> Self: ...


class ClustersNode(PaginatedAccessor[Cluster]):
    def get_own_path(self):
        return ("clusters", )

    async def create(self: Self) -> Cluster: ...


class Service(InteractiveObject): ...


class ServicesNode(PaginatedAccessor[Service]):
    def __init__(self: Self, requester: Requester, parent: Cluster) -> None:
        super().__init__(requester)
        self._parent = parent

    def get_own_path(self: Self) -> tuple[str | int, ...]:
        return (*self._parent.get_own_path(), "services")


