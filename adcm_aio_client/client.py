# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from functools import cached_property
from typing import Self

from adcm_aio_client.objects import ADCM
from adcm_aio_client.objects._cm import BundlesNode, ClustersNode, HostProvidersNode, HostsNode, JobsNode
from adcm_aio_client.requesters import BundleRetrieverInterface, Requester

MIN_ADCM_VERSION = "2.5.0"


class ADCMClient:
    def __init__(
        self: Self, requester: Requester, bundle_retriever: BundleRetrieverInterface, adcm_version: str
    ) -> None:
        self._requester = requester
        self._retrieve_bundle_from_remote_url = bundle_retriever
        self._adcm_version = adcm_version

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
        return ADCM(requester=self._requester, data={}, version=self._adcm_version)

    @cached_property
    def bundles(self: Self) -> BundlesNode:
        return BundlesNode(
            path=("bundles",), requester=self._requester, retriever=self._retrieve_bundle_from_remote_url
        )

    @cached_property
    def jobs(self: Self) -> JobsNode:
        return JobsNode(path=("tasks",), requester=self._requester)
