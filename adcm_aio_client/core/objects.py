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

from typing import Self

from adcm_aio_client.core.accessors import Accessor


class BaseObject:
    id: int
    name: str


class Cluster(BaseObject):
    description: str
    services: "ServiceNode"

    def delete(self: Self) -> None: ...

    def rename(self: Self, name: str) -> Self: ...


class ClusterNode(Accessor[Cluster]):
    def create(self: Self) -> Cluster: ...


class Service(BaseObject): ...


class ServiceNode(Accessor[Service]): ...
