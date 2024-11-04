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
from typing import AsyncGenerator, List, Self

from adcm_aio_client.core.requesters import Requester


class Accessor[T](ABC):
    @abstractmethod
    async def list(self: Self) -> AsyncGenerator[List[T]]: ...

    @abstractmethod
    async def get(self: Self) -> AsyncGenerator[T]: ...

    @abstractmethod
    async def get_or_none(self: Self) -> AsyncGenerator[T | None]: ...

    @abstractmethod
    async def all(self: Self) -> AsyncGenerator[List[T]]: ...

    @abstractmethod
    async def iter(self: Self) -> AsyncGenerator[T]: ...

    @abstractmethod
    async def filter(self: Self, predicate: T) -> AsyncGenerator[List[T]]: ...


class PaginatedAccessor(Accessor):
    def __init__(self: Self, path: str, requester: Requester) -> None: ...


class NonPaginatedAccessor(Accessor): ...
