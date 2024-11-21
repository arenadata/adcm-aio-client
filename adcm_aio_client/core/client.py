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

from functools import cached_property
from typing import Self

from adcm_aio_client.core.objects.cm import ClustersNode, HostProvidersNode, HostsNode
from adcm_aio_client.core.requesters import Requester
from adcm_aio_client.core.types import AuthToken, Cert, Credentials, Verify


class ADCMClient:
    def __init__(self: Self, requester: Requester) -> None:
        self._requester = requester

    @cached_property
    def clusters(self: Self) -> ClustersNode:
        return ClustersNode(path=("clusters",), requester=self._requester)

    @cached_property
    def hosts(self: Self) -> HostsNode:
        return HostsNode(path=("hosts",), requester=self._requester)

    @cached_property
    def hostproviders(self: Self) -> HostProvidersNode:
        return HostProvidersNode(path=("hostproviders",), requester=self._requester)


async def build_client(
    url: str | list[str],
    credentials: Credentials | AuthToken,
    *,
    verify: Verify | None = None,
    cert: Cert | None = None,
    timeout: int | None = None,
    retries: int | None = None,
) -> ADCMClient: ...
