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
from typing import AsyncGenerator, List, Self, Any, Dict, Type, Optional, Iterable

from adcm_aio_client.core.types import Requester


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
    async def list(self: Self) -> AsyncGenerator[List[T], Any]: ...

    @abstractmethod
    async def get(self: Self, predicate: T | None) -> AsyncGenerator[T, Any]: ...

    @abstractmethod
    async def get_or_none(self: Self, predicate: T | None) -> AsyncGenerator[T | None, Any]: ...

    @abstractmethod
    async def all(self: Self) -> AsyncGenerator[List[T], Any]: ...

    @abstractmethod
    async def iter(self: Self) -> AsyncGenerator[T, Any]: ...

    @abstractmethod
    async def filter(self: Self, predicate: T) -> AsyncGenerator[List[T], Any]: ...

    def _create_object(self, data: Dict[str, Any]) -> T:
        obj = self.__new__(self.class_type)  # Create a new instance without calling __init__
        for key, value in data.items():
            if key in self.__annotations__.keys():
                setattr(obj, key, value)
        return obj


class PaginatedAccessor[T](Accessor):
    def get_paginated_data(self, page: int, offset: int, objects: List[T]) -> List[T]:
        # Calculate start and end indices
        start_index = (page - 1) * offset
        end_index = start_index + offset

        if end_index > len(objects):
            end_index = len(objects)

        if start_index >= len(objects):
            return []

        if end_index < 0 or start_index < 0:
            return []

        # Return the slice of clusters for the requested page
        return objects[start_index:end_index]


class NonPaginatedAccessor(Accessor): ...
