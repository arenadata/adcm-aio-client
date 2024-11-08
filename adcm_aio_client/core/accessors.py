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
from typing import AsyncGenerator, List, Self, Any, Dict, Type, Optional, Iterable, Tuple, Generator

from adcm_aio_client.core.exceptions import (
    MissingParameterException,
    ObjectDoesNotExistError,
    MultipleObjectsReturnedError,
)
from adcm_aio_client.core.mocks import MockRequester
from adcm_aio_client.core.requesters import Requester, RequesterResponse


class Filter[T]:
    def __init__(self, **predicate):
        self.predicate = predicate

    def __call__(self, object_collection: Iterable[T]):
        return get_objects(object_collection, self.predicate)

    def is_valid(self) -> bool:
        # Implement validation logic
        return bool(self.predicate)

    @staticmethod
    def is_subdictionary(small, large):
        # Iterate through each key-value pair in the smaller dictionary
        for key, value in small.items():
            # Check if the key is in the larger dictionary and the value matches
            if key not in large or large[key] != value:
                return False
        return True

    @staticmethod
    def get_objects(object_collection: Iterable[T], filter_data: Optional[dict] = None) -> List[dict]:
        return [obj for obj in object_collection if is_subdictionary(filter_data, obj.__dict__)]


class Accessor[T](ABC):
    class_type: Type[T]

    def __init__(self: Self, path: str, requester: Requester, query_params: dict = None) -> None:
        self.path = path
        self.requester = requester
        self.query_params = query_params

    @abstractmethod
    async def list(self: Self) -> List[T]: ...

    @abstractmethod
    async def get(self: Self, predicate: T | None) -> T: ...

    @abstractmethod
    async def get_or_none(self: Self, predicate: T | None) -> T | None: ...

    @abstractmethod
    async def all(self: Self) -> List[T]: ...

    @abstractmethod
    async def iter(self: Self) -> AsyncGenerator[T]: ...

    @abstractmethod
    async def filter(self: Self, predicate: T) -> List[T]: ...

    def _create_object(self, data: Dict[str, Any]) -> T:
        obj = self.__new__(self.class_type)  # Create a new instance without calling __init__
        for key, value in data.items():
            if key in self.__annotations__.keys():
                setattr(obj, key, value)
        return obj


class PaginatedAccessor[T](Accessor):
    def paginate(self, page: Optional[int] = 1, items: Optional[int] = 10) -> Generator[Tuple[int, int], None, None]:
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

    async def create(self: Self, **kwargs) -> T:
        # Simulate a request that creates a new object
        response: RequesterResponse = await MockRequester.post(self.path, kwargs)
        assert response.as_dict()["status_code"] == 201  # TODO: rework accoring to actual API response structure
        return self._create_object(kwargs)

    async def get(self, **predicate) -> T:
        if predicate:
            filter_objects = Filter(**predicate)

            if not filter_objects.is_valid():
                raise MissingParameterException("Filter parameters are missing or invalid.")

        # Simulate a request that returns objects based on a filter
        response: RequesterResponse = await MockRequester.get(self.path, self.query_params)
        objects = response.as_dict()

        if not objects:
            raise ObjectDoesNotExistError("No objects found with the given filter.")
        elif len(objects) > 1:
            raise MultipleObjectsReturnedError("More than one object found.")
        else:
            return self._create_object(objects[0])

    async def list(self: Self, offset: int = 1, limit: int = 10) -> List[T]:
        response: RequesterResponse = await MockRequester.list(
            self.path, self.query_param.update({"offset": offset, "limit": limit})
        )
        return [self._create_object(object) for object in response.as_list()]

    async def get_or_none(self: Self, predicate: T) -> T | None:
        with suppress(ObjectDoesNotExistError):
            obj = await self.get(predicate=predicate)
            if obj:
                yield obj
            else:
                yield None
        yield None  # Default yield in case of exceptions

    async def all(self: Self, page: int = 1, items: int = 10) -> List[T]:
        objects = []
        try:
            while True:
                batch = await self.list(page, items)
                objects.append(batch)
                page += 1
        except StopIteration:
            return objects

    async def iter(self: Self, offset: int = 1, limit: int = 10) -> AsyncGenerator[List[T]]:
        paginator = self.paginate(offset, limit)
        while True:
            start, end = next(paginator)
            response: RequesterResponse = await MockRequester.list(
                self.path, self.query_param.update({"offset": start, "limit": end})
            )
            if start >= len(response.as_list()):
                raise StopIteration
            yield [self._create_object(object) for object in response.as_list()]

    async def filter(self: Self, **predicate) -> List[T]:
        filter_objects = Filter(**predicate)
        if not predicate or not filter_objects.is_valid():
            raise MissingParameterException("Filter parameters are missing or invalid.")

        return [self._create_object(obj) for obj in filter_objects(await self.list())]


class NonPaginatedAccessor(Accessor): ...
