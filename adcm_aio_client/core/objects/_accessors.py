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
from typing import Any, AsyncGenerator, Iterable, Self

from adcm_aio_client.core.errors import MultipleObjectsReturnedError, ObjectDoesNotExistError
from adcm_aio_client.core.filters import Filter, FilterValidator, FilterValue, filters_to_query
from adcm_aio_client.core.objects._base import InteractiveChildObject, InteractiveObject
from adcm_aio_client.core.types import Endpoint, QueryParameters, Requester, RequesterResponse

# filter for narrowing response objects
type DefaultQueryParams = QueryParameters | None


class Accessor[ReturnObject: InteractiveObject](ABC):
    CLASS: type[ReturnObject]
    _validate_filter: FilterValidator

    def __init__(self: Self, path: Endpoint, requester: Requester, default_query: DefaultQueryParams = None) -> None:
        self._path = path
        self._requester = requester
        self._default_query = default_query or {}

    @abstractmethod
    async def iter(self: Self, **filters: FilterValue) -> AsyncGenerator[ReturnObject, None]: ...

    @abstractmethod
    def _extract_results_from_response(self: Self, response: RequesterResponse) -> list[dict]: ...

    async def get(self: Self, **filters: FilterValue) -> ReturnObject:
        response = await self._request_endpoint(query={"offset": 0, "limit": 2}, filters=filters)
        results = self._extract_results_from_response(response=response)

        if not results:
            raise ObjectDoesNotExistError("No objects found with the given filter.")

        if len(results) > 1:
            raise MultipleObjectsReturnedError("More than one object found.")

        return self._create_object(results[0])

    async def get_or_none(self: Self, **filters: FilterValue) -> ReturnObject | None:
        with suppress(ObjectDoesNotExistError):
            return await self.get(**filters)

        return None

    async def all(self: Self) -> list[ReturnObject]:
        return await self.filter()

    async def filter(self: Self, **filters: FilterValue) -> list[ReturnObject]:
        return [i async for i in self.iter(**filters)]

    async def list(self: Self, query: dict | None = None) -> list[ReturnObject]:
        response = await self._request_endpoint(query=query or {})
        results = self._extract_results_from_response(response)
        return [self._create_object(obj) for obj in results]

    async def _request_endpoint(
        self: Self, query: QueryParameters, filters: dict[str, Any] | None = None
    ) -> RequesterResponse:
        parsed_filters = self._parse_inline_filters(**(filters or {}))
        filters_query = filters_to_query(filters=parsed_filters, validate=self._validate_filter)

        final_query = filters_query | query | self._default_query

        return await self._requester.get(*self._path, query=final_query)

    def _create_object(self: Self, data: dict[str, Any]) -> ReturnObject:
        return self.CLASS(requester=self._requester, data=data)

    def _parse_inline_filters(self: Self, **filters: FilterValue) -> Iterable[Filter]:
        for inline_filter, value in filters.items():
            attr, op = inline_filter.split("__", maxsplit=1)
            yield Filter(attr=attr, op=op, value=value)

    def _filters_to_inline(self: Self, *filters: Filter) -> dict:
        return {f"{f.attr}__{f.op}": f.value for f in filters}


class PaginatedAccessor[ReturnObject: InteractiveObject](Accessor[ReturnObject]):
    async def iter(self: Self, **filters: FilterValue) -> AsyncGenerator[ReturnObject, None]:
        start, step = 0, 10
        while True:
            response = await self._request_endpoint(query={"offset": start, "limit": step}, filters=filters)
            results = self._extract_results_from_response(response=response)

            if not results:
                return

            for record in results:
                yield self._create_object(record)

            start += step

    def _extract_results_from_response(self: Self, response: RequesterResponse) -> list[dict]:
        return response.as_dict()["results"]


class PaginatedChildAccessor[Parent, Child: InteractiveChildObject](PaginatedAccessor[Child]):
    def __init__(
        self: Self, parent: Parent, path: Endpoint, requester: Requester, default_query: DefaultQueryParams = None
    ) -> None:
        super().__init__(path, requester, default_query)
        self._parent = parent

    def _create_object(self: Self, data: dict[str, Any]) -> Child:
        return self.CLASS(parent=self._parent, data=data)


class NonPaginatedAccessor[Child: InteractiveObject](Accessor[Child]):
    async def iter(self: Self, **filters: FilterValue) -> AsyncGenerator[Child, None]:
        response = await self._request_endpoint(query={}, filters=filters)
        results = self._extract_results_from_response(response=response)
        for record in results:
            yield self._create_object(record)

    def _extract_results_from_response(self: Self, response: RequesterResponse) -> list[dict]:
        return response.as_list()


class NonPaginatedChildAccessor[Parent, Child: InteractiveChildObject](NonPaginatedAccessor[Child]):
    def __init__(
        self: Self, parent: Parent, path: Endpoint, requester: Requester, default_query: DefaultQueryParams = None
    ) -> None:
        super().__init__(path, requester, default_query)
        self._parent = parent

    def _create_object(self: Self, data: dict[str, Any]) -> Child:
        return self.CLASS(parent=self._parent, data=data)
