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
    MultipleObjectsReturnedError,
    InvalidArgumentError,
)
from adcm_aio_client.core.mocks import MockRequester
from adcm_aio_client.core.requesters import Requester, RequesterResponse


class BaseObject:
    id: int
    name: str


class BaseNode(Accessor[BaseObject]):
    def __init__(self: Self, path: str, requester: Requester, query_params: dict = None) -> None:
        super().__init__(path, requester, query_params)
        self.class_type = eval(self.class_type.__name__)


class Service(BaseObject): ...


class ServiceNode(BaseNode, PaginatedAccessor):
    id: int
    name: str
    display_name: str


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


class ClusterNode[Cluster](BaseNode, PaginatedAccessor):
    class_type = Cluster
    id: int
    name: str
    description: str
    services: Optional[ServiceNode]
