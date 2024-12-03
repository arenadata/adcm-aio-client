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
from adcm_aio_client.core.objects._base import InteractiveChildObject, InteractiveObject
from adcm_aio_client.core.types import Endpoint, QueryParameters, Requester, RequesterResponse

# filter for narrowing response objects
type AccessorFilter = QueryParameters | None
"""
Sometimes it's required for accessor to have "narrowing" filter
that'll be used to all outgoing requests
with greater priority to user-passed arguments.
"""


class Accessor[ReturnObject: InteractiveObject, Filters](ABC):
    class_type: type[ReturnObject]

    def __init__(self: Self, path: Endpoint, requester: Requester, accessor_filter: AccessorFilter = None) -> None:
        self._path = path
        self._requester = requester
        self._accessor_filter = accessor_filter or {}

    @abstractmethod
    async def iter(self: Self, filters: Filters | None = None) -> AsyncGenerator[ReturnObject, None]: ...

    @abstractmethod
    def _extract_results_from_response(self: Self, response: RequesterResponse) -> list[dict]: ...

    async def get(self: Self, filters: Filters | None = None) -> ReturnObject:
        query = self._prepare_query_from_filters(filters=filters)
        paging = {"offset": 0, "limit": 2}

        response = await self._request_endpoint(query=query | paging)
        results = self._extract_results_from_response(response=response)

        if not results:
            raise ObjectDoesNotExistError("No objects found with the given filter.")

        if len(results) > 1:
            raise MultipleObjectsReturnedError("More than one object found.")

        return self._create_object(results[0])

    async def get_or_none(self: Self, filters: Filters | None = None) -> ReturnObject | None:
        with suppress(ObjectDoesNotExistError):
            return await self.get(filters=filters)

        return None

    async def all(self: Self) -> list[ReturnObject]:
        return await self.filter()

    async def filter(self: Self, filters: Filters | None = None) -> list[ReturnObject]:
        return [i async for i in self.iter(filters=filters)]

    async def list(self: Self, query: QueryParameters | None = None) -> list[ReturnObject]:
        response = await self._request_endpoint(query=query or {})
        results = self._extract_results_from_response(response)
        return [self._create_object(obj) for obj in results]

    async def _request_endpoint(self: Self, query: QueryParameters) -> RequesterResponse:
        return await self._requester.get(*self._path, query=query | self._accessor_filter)

    def _create_object(self: Self, data: dict[str, Any]) -> ReturnObject:
        return self.class_type(requester=self._requester, data=data)

    # Filters section

    def _prepare_query_from_filters(self: Self, filters: Filters | None) -> QueryParameters:
        if filters is None:
            return {}

        self._validate_filters(filters)

        return self._convert_filters_to_query(filters)

    def _validate_filters(self: Self, filters: Filters) -> None:
        # todo validate filters
        ...

    def _convert_filters_to_query(self: Self, filters: Filters) -> QueryParameters:
        if not isinstance(filters, dict):
            message = f"Incorrect filters type: {type(filters)}. Only dict is allowed."
            raise NotImplementedError(message)

        query = {}

        for filter_name, value in filters.items():
            api_filter_name = self._prepare_filter_name(filter_name)
            prepared_value = self._prepare_filter_value(value)

            query[api_filter_name] = prepared_value

        return query

    def _prepare_filter_name(self: Self, name: str) -> str:
        field_name, qualifier = name.split("__", maxsplit=1)
        # capitalize
        first_word, *rest = field_name.split("_")
        field_name = f"{first_word}{''.join(map(str.capitalize, rest))}"
        return f"{field_name}__{qualifier}"

    def _prepare_filter_value(self: Self, value: Any) -> str:
        if isinstance(value, (str, int)):
            return str(value)

        if hasattr(value, "id"):
            return str(value.id)

        if isinstance(value, Iterable):
            return ",".join(map(self._prepare_filter_value, (entry for entry in value)))

        message = f"Can't convert value of type {type(value)} to string for using it in query"
        raise NotImplementedError(message)


class PaginatedAccessor[ReturnObject: InteractiveObject, Filter](Accessor[ReturnObject, Filter]):
    async def iter(self: Self, filters: Filter | None = None) -> AsyncGenerator[ReturnObject, None]:
        query = self._prepare_query_from_filters(filters=filters)

        start, step = 0, 10
        while True:
            response = await self._request_endpoint(query={**query, "offset": start, "limit": step})
            results = self._extract_results_from_response(response=response)

            if not results:
                return

            for record in results:
                yield self._create_object(record)

            start += step

    def _extract_results_from_response(self: Self, response: RequesterResponse) -> list[dict]:
        return response.as_dict()["results"]


class PaginatedChildAccessor[Parent, Child: InteractiveChildObject, Filter](PaginatedAccessor[Child, Filter]):
    def __init__(
        self: Self, parent: Parent, path: Endpoint, requester: Requester, accessor_filter: AccessorFilter = None
    ) -> None:
        super().__init__(path, requester, accessor_filter)
        self._parent = parent

    def _create_object(self: Self, data: dict[str, Any]) -> Child:
        return self.class_type(parent=self._parent, data=data)


class NonPaginatedChildAccessor[Parent, Child: InteractiveChildObject, Filter](Accessor[Child, Filter]):
    def __init__(
        self: Self, parent: Parent, path: Endpoint, requester: Requester, accessor_filter: AccessorFilter = None
    ) -> None:
        super().__init__(path, requester, accessor_filter)
        self._parent = parent

    async def iter(self: Self, filters: Filter | None = None) -> AsyncGenerator[Child, None]:
        query = self._prepare_query_from_filters(filters=filters)
        response = await self._request_endpoint(query=query)
        results = self._extract_results_from_response(response=response)
        for record in results:
            yield self._create_object(record)

    def _extract_results_from_response(self: Self, response: RequesterResponse) -> list[dict]:
        return response.as_list()

    def _create_object(self: Self, data: dict[str, Any]) -> Child:
        return self.class_type(parent=self._parent, data=data)
