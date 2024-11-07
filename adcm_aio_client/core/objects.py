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
from contextlib import suppress
from typing import Self, Optional, AsyncGenerator, Any, List

from adcm_aio_client.core.accessors import Accessor, Filter, PaginatedAccessor
from adcm_aio_client.core.exceptions import (
    MissingParameterException,
    ObjectDoesNotExistError,
    MultipleObjectsReturnedError, InvalidArgumentError,
)
from adcm_aio_client.core.mocks import MockRequester
from adcm_aio_client.core.requesters import Requester, RequesterResponse


class BaseObject:
    id: int
    name: str


class Service(BaseObject): ...


class ServiceNode(Accessor[Service]): ...


class Cluster(BaseObject):
    def __init__(self, id: int, name: str, description: str, services: Optional[ServiceNode] = None):
        self.id = id
        self.name = name
        self.description = description
        self.services = services

    def delete(self: Self) -> None:
        # Implement delete logic
        pass

    def rename(self: Self, name: str) -> Self:
        self.name = name
        return self


class ClusterNode[Cluster](PaginatedAccessor):
    class_type = Cluster
    id: int
    name: str
    description: str
    services: Optional[ServiceNode]

    def __init__(self: Self, path: str, requester: Requester, query_params: dict = None) -> None:
        super().__init__(path, requester, query_params)
        self.class_type = eval(self.class_type.__name__)

    async def create(self: Self, **kwargs) -> Cluster:
        # Simulate a request that creates a new object
        response: RequesterResponse = await MockRequester.post(self.path, kwargs)
        assert response.as_dict()["status_code"] == 201 # TODO: rework accoring to actual API response structure
        return self._create_object(kwargs)

    async def get(self, **predicate) -> AsyncGenerator[Cluster, Any]:
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

    async def list(self: Self) -> AsyncGenerator[List[Cluster], Any]:
        response: RequesterResponse = await MockRequester.all(self.path, self.query_param)
        return [self._create_object(object) for object in response.as_list()]

    async def get_or_none(self: Self) -> AsyncGenerator[Cluster | None, Any]:
        with suppress(ObjectDoesNotExistError):
            obj = await self.get()
            if obj:
                yield obj
            else:
                yield None
        yield None  # Default yield in case of exceptions

    async def all(self: Self) -> AsyncGenerator[List[Cluster], Any]:
        return await self.list()

    async def iter(self: Self) -> AsyncGenerator[Cluster, Any]:
        pagination_count = 10
        # Simulate a request loop, retrieving objects in batches
        request_params = self.query_params.copy() if self.query_params else {}
        request_params.update(filter.to_query_dict() if filter else {})

        page = 1

        while True:
            # Adding pagination information to the request
            request_params['page'] = page

            response: RequesterResponse = await MockRequester.get(self.path, request_params)
            objects = response.as_dict()

            if not objects:
                break  # No more objects to retrieve

            object_count = len(objects)

            if object_count == 0:
                return  # No objects found

            for obj_dict in objects:
                yield self._create_object(obj_dict)

            if object_count < pagination_count:
                break  # All objects have been retrieved

            page += 1  # Move to the next page

        # Raise error if unexpected issue
        raise InvalidArgumentError("Unexpected pagination logic issue encountered.")

    async def filter(self: Self, **predicate) -> AsyncGenerator[List[Cluster], Any]:
        filter_objects = Filter(**predicate)
        if not predicate or not filter_objects.is_valid():
            raise MissingParameterException("Filter parameters are missing or invalid.")

        return filter_objects(await self.list())
