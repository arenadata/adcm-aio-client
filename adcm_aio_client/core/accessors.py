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
from typing import AsyncGenerator, List, Self, Any, Dict, Type, Optional, Tuple, Generator

from adcm_aio_client.core.exceptions import (
    ObjectDoesNotExistError,
    MultipleObjectsReturnedError,
)
from adcm_aio_client.core.requesters import HTTPXRequesterResponse, DefaultRequester


class Accessor[T, F](ABC):
    class_type: Type[T]

    def __init__(self: Self, path: str, requester: DefaultRequester, query_params: dict = None) -> None:
        self.path = path
        self.requester = requester
        self.query_params = query_params
        self.filter_object = F()

    @abstractmethod
    async def list(self: Self) -> List[T]: ...

    @abstractmethod
    async def get(self: Self, predicate: T | None) -> T: ...

    @abstractmethod
    async def get_or_none(self: Self, predicate: T | None) -> T | None: ...

    @abstractmethod
    async def all(self: Self) -> List[T]: ...

    @abstractmethod
    async def iter(self: Self) -> AsyncGenerator[T, Self]: ...

    @abstractmethod
    async def filter(self: Self, predicate: T) -> List[T]: ...

    def _create_object(self, data: Dict[str, Any]) -> T:
        obj = self.__new__(self.class_type)  # Create a new instance without calling __init__
        for key, value in data.items():
            if key in self.__annotations__.keys():
                setattr(obj, key, value)
        return obj


class PaginatedAccessor[T](Accessor):
    def _gen_page_indixes(
        self, page: Optional[int] = 1, items: Optional[int] = 10
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

    async def get(self, **predicate) -> T:
        response: HTTPXRequesterResponse = await self.requester.get(self.path, query_params=self.query_params)
        objects = response.as_list()

        if not objects:
            raise ObjectDoesNotExistError("No objects found with the given filter.")
        elif len(objects) > 1:
            raise MultipleObjectsReturnedError("More than one object found.")
        else:
            return self._create_object(objects[0])

    async def list(self: Self) -> List[T]:
        response: HTTPXRequesterResponse = await self.requester.get(self.path, query_params=self.query_params)
        return [self._create_object(obj) for obj in response.as_list()]

    async def get_or_none(self: Self, predicate: T) -> T | None:
        with suppress(ObjectDoesNotExistError):
            obj = await self.get(predicate=predicate)
            if obj:
                return obj
        return None

    async def all(self: Self) -> List[T]:
        all_objects = []

        async for result in self.iter():
            all_objects.append(result)

        return all_objects

    async def iter(self: Self) -> AsyncGenerator[T, Self]:
        paginator = self._gen_page_indixes(self.query_params["offset"], self.query_params["limit"])
        while True:
            start, end = next(paginator)
            response: HTTPXRequesterResponse = await self.requester.get(self.path, query_params=self.query_params)

            if start >= len(response.as_list()):
                raise StopIteration
            yield [self._create_object(obj) for obj in response.as_list()]

    async def filter(self: Self, **predicate) -> List[T]:
        return self.filter_object(**predicate)


class NonPaginatedAccessor(Accessor): ...
