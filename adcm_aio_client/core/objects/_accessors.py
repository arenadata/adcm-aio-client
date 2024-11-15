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
from typing import Any, AsyncGenerator, Self

from adcm_aio_client.core.errors import MultipleObjectsReturnedError, ObjectDoesNotExistError
from adcm_aio_client.core.objects._base import InteractiveChildObject, InteractiveObject
from adcm_aio_client.core.types import Endpoint, QueryParameters, Requester, RequesterResponse


class Accessor[ReturnObject: InteractiveObject, Filter](ABC):
    class_type: type[ReturnObject]

    def __init__(self: Self, path: Endpoint, requester: Requester) -> None:
        self._path = path
        self._requester = requester

    @abstractmethod
    async def iter(self: Self) -> AsyncGenerator[ReturnObject, None]: ...

    @abstractmethod
    def _extract_results_from_response(self: Self, response: RequesterResponse) -> list[dict]: ...

    async def get(self: Self) -> ReturnObject:
        response = await self._request_endpoint(query={"offset": 0, "limit": 2})
        results = self._extract_results_from_response(response=response)

        if not results:
            raise ObjectDoesNotExistError("No objects found with the given filter.")

        if len(results) > 1:
            raise MultipleObjectsReturnedError("More than one object found.")

        return self._create_object(results[0])

    async def get_or_none(self: Self) -> ReturnObject | None:
        with suppress(ObjectDoesNotExistError):
            return await self.get()

        return None

    async def all(self: Self) -> list[ReturnObject]:
        return await self.filter()

    async def filter(self: Self) -> list[ReturnObject]:
        return [i async for i in self.iter()]

    async def list(self: Self) -> list[ReturnObject]:
        response = await self._request_endpoint(query={})
        results = self._extract_results_from_response(response)
        return [self._create_object(obj) for obj in results]

    async def _request_endpoint(self: Self, query: QueryParameters) -> RequesterResponse:
        return await self._requester.get(*self._path, query=query)

    def _create_object(self: Self, data: dict[str, Any]) -> ReturnObject:
        return self.class_type(requester=self._requester, data=data)


class PaginatedAccessor[ReturnObject: InteractiveObject, Filter](Accessor[ReturnObject, Filter]):
    async def iter(self: Self) -> AsyncGenerator[ReturnObject, None]:
        start, step = 0, 10
        while True:
            response = await self._request_endpoint(query={"offset": start, "limit": step})
            results = self._extract_results_from_response(response=response)

            if not results:
                return

            for record in results:
                yield self._create_object(record)

            start += step

    def _extract_results_from_response(self: Self, response: RequesterResponse) -> list[dict]:
        return response.as_dict()["results"]


class PaginatedChildAccessor[Parent, Child: InteractiveChildObject, Filter](PaginatedAccessor[Child, Filter]):
    def __init__(self: Self, parent: Parent, path: Endpoint, requester: Requester) -> None:
        super().__init__(path, requester)
        self._parent = parent

    def _create_object(self: Self, data: dict[str, Any]) -> Child:
        return self.class_type(parent=self._parent, requester=self._requester, data=data)


class NonPaginatedChildAccessor[Parent, Child: InteractiveChildObject, Filter](Accessor[Child, Filter]):
    def __init__(self: Self, parent: Parent, path: Endpoint, requester: Requester) -> None:
        super().__init__(path, requester)
        self._parent = parent

    async def iter(self: Self) -> AsyncGenerator[Child, None]:
        response = await self._request_endpoint(query={})
        results = self._extract_results_from_response(response=response)
        for record in results:
            yield self._create_object(record)

    def _extract_results_from_response(self: Self, response: RequesterResponse) -> list[dict]:
        return response.as_list()

    def _create_object(self: Self, data: dict[str, Any]) -> Child:
        return self.class_type(parent=self._parent, requester=self._requester, data=data)
