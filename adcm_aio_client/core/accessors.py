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

from abc import ABC, abstractmethod
from typing import Self

from adcm_aio_client.core.requesters import Requester


class Accessor[T](ABC):
    _requester: Requester

    @abstractmethod
    def get_own_path(self: Self) -> tuple[str | int, ...]: ...

    @abstractmethod
    async def list(self: Self) -> ...: ...

    @abstractmethod
    async def get(self: Self) -> ...: ...

    @abstractmethod
    async def get_or_none(self: Self) -> ...: ...

    @abstractmethod
    async def all(self: Self) -> ...: ...

    @abstractmethod
    async def iter(self: Self) -> ...: ...

    @abstractmethod
    async def filter(self: Self, predicate: T) -> ...: ...


class PaginatedAccessor[T](Accessor[T]):
    def __init__(self: Self, requester: Requester) -> None: ...


class NonPaginatedAccessor[T](Accessor[T]): ...
