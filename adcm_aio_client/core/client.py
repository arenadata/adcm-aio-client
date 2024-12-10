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

from adcm_aio_client.core.objects.cm import ADCM, BundlesNode, ClustersNode, HostProvidersNode, HostsNode
from adcm_aio_client.core.requesters import BundleRetriever, BundleRetrieverInterface, DefaultRequester, Requester
from adcm_aio_client.core.types import Cert, Credentials, Verify


class ADCMClient:
    def __init__(self: Self, requester: Requester, bundle_retriever: BundleRetrieverInterface) -> None:
        self._requester = requester
        self.bundle_retriever = bundle_retriever

    @cached_property
    def clusters(self: Self) -> ClustersNode:
        return ClustersNode(path=("clusters",), requester=self._requester)

    @cached_property
    def hosts(self: Self) -> HostsNode:
        return HostsNode(path=("hosts",), requester=self._requester)

    @cached_property
    def hostproviders(self: Self) -> HostProvidersNode:
        return HostProvidersNode(path=("hostproviders",), requester=self._requester)

    @cached_property
    def adcm(self: Self) -> ADCM:
        return ADCM(requester=self._requester, data={})

    @cached_property
    def bundles(self: Self) -> BundlesNode:
        return BundlesNode(path=("bundles",), requester=self._requester, retriever=self.bundle_retriever)


async def build_client(
    url: str,
    credentials: Credentials,
    *,
    verify: Verify | None = None,  # noqa: ARG001
    cert: Cert | None = None,  # noqa: ARG001
    timeout: float = 0.5,
    retries: int = 5,
    retry_interval: float = 5.0,
) -> ADCMClient:
    requester = DefaultRequester(base_url=url, retries=retries, retry_interval=retry_interval, timeout=timeout)
    await requester.login(credentials=credentials)
    return ADCMClient(requester=requester, bundle_retriever=BundleRetriever())
