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
from contextlib import suppress
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional, Self, Tuple, Type

from adcm_aio_client.core.exceptions import (
    MultipleObjectsReturnedError,
    ObjectDoesNotExistError,
)
from adcm_aio_client.core.requesters import DefaultRequester


class Accessor[T, F](ABC):
    class_type: Type[T]

    def __init__(self: Self, path: tuple[str | int, ...], requester: DefaultRequester) -> None:
        self.path = path
        self.requester = requester

    @abstractmethod
    async def list(self: Self) -> List[T]: ...

    @abstractmethod
    async def get(self: Self) -> T: ...

    @abstractmethod
    async def get_or_none(self: Self) -> T | None: ...

    @abstractmethod
    async def all(self: Self) -> List[T]: ...

    @abstractmethod
    async def iter(self: Self) -> AsyncGenerator[T, None]: ...

    @abstractmethod
    async def filter(self: Self) -> List[T]: ...

    def _create_object(self: Self, data: Dict[str, Any]) -> T:
        return self.class_type(requester=self.requester, data=data)  # type: ignore


class PaginatedAccessor[T](Accessor):
    def _gen_page_indexes(
        self: Self, page: Optional[int] = 1, items: Optional[int] = 10
    ) -> Generator[Tuple[int, int], None, None]:
        """
        Generates indices for pagination slicing based on specified page number and offset.

        Args:
            page (int, optional): The starting page number for pagination. Defaults to 1.
            items (int, optional): The number of items per page. Defaults to 10.

        Yields:
            Tuple[int, int]: A tuple representing the start and end indices for slicing.
        """
        if page is None:
            page = 1
        if items is None:
            items = 10

        current_page = page

        while True:
            # Calculate the start and end indices for the current page
            start_index = (current_page - 1) * items
            end_index = current_page * items
            yield (start_index, end_index)
            current_page += 1

    async def get(self: Self) -> T:
        response = await self._list(query_params={"offset": 0, "limit": 2})
        objects = response["results"]

        if not objects:
            raise ObjectDoesNotExistError("No objects found with the given filter.")
        if len(objects) > 1:
            raise MultipleObjectsReturnedError("More than one object found.")
        return self._create_object(objects[0])

    async def _list(self: Self, query_params: dict) -> dict:
        response = await self.requester.get(*self.path, query_params=query_params)
        return response.as_dict()

    async def list(self: Self) -> List[T]:
        return [self._create_object(obj) for obj in await self._list(query_params={})]

    async def get_or_none(self: Self) -> T | None:
        with suppress(ObjectDoesNotExistError):
            obj = await self.get()
            if obj:
                return obj
        return None

    async def all(self: Self) -> List[T]:
        return await self.filter()

    async def iter(self: Self) -> AsyncGenerator[T, None]:
        start, step = 0, 10
        while True:
            response = await self._list(query_params={"offset": start, "limit": step})

            if not response["results"]:
                return

            for record in response["results"]:
                yield self._create_object(record)

            start += step

    async def filter(self: Self) -> List[T]:
        return [i async for i in self.iter()]


class NonPaginatedAccessor(Accessor): ...
