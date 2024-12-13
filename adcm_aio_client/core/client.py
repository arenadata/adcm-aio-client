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
from urllib.parse import urljoin

from adcm_version import compare_adcm_versions
import httpx

from adcm_aio_client.core.errors import NotSupportedVersionError, VersionRetrievalError
from adcm_aio_client.core.objects.cm import ADCM, BundlesNode, ClustersNode, HostProvidersNode, HostsNode
from adcm_aio_client.core.requesters import BundleRetriever, BundleRetrieverInterface, DefaultRequester, Requester
from adcm_aio_client.core.types import Cert, Credentials, Verify

MIN_ADCM_VERSION = "2.5.0"


class ADCMClient:
    def __init__(
        self: Self, requester: Requester, bundle_retriever: BundleRetrieverInterface, adcm_version: str
    ) -> None:
        self._requester = requester
        self.bundle_retriever = bundle_retriever
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
        return BundlesNode(path=("bundles",), requester=self._requester, retriever=self.bundle_retriever)


async def build_client(
    url: str,
    credentials: Credentials,
    *,
    verify: Verify | None = None,  # noqa: ARG001
    cert: Cert | None = None,  # noqa: ARG001
    timeout: float = 600.0,
    retries: int = 3,
    retry_interval: float = 1.0,
) -> ADCMClient:
    adcm_version = await _get_and_check_adcm_version(url=url, timeout=timeout)
    requester = DefaultRequester(base_url=url, retries=retries, retry_interval=retry_interval, timeout=timeout)
    await requester.login(credentials=credentials)
    return ADCMClient(requester=requester, bundle_retriever=BundleRetriever(), adcm_version=adcm_version)


async def _get_and_check_adcm_version(url: str, timeout: float) -> str:
    try:
        adcm_version = await _get_adcm_version(url=url, timeout=timeout)
    except VersionRetrievalError as e:
        message = f"Can't get ADCM version for {url}. Most likely ADCM version is lesser than {MIN_ADCM_VERSION}"
        raise NotSupportedVersionError(message) from e

    if compare_adcm_versions(adcm_version, MIN_ADCM_VERSION) < 0:
        message = f"Minimal supported ADCM version is {MIN_ADCM_VERSION}. Got {adcm_version}"
        raise NotSupportedVersionError(message)

    return adcm_version


async def _get_adcm_version(url: str, timeout: float) -> str:
    try:
        return (await httpx.AsyncClient(timeout=timeout).get(urljoin(url, "versions/"))).json()["adcm"]["version"]
    except Exception as e:
        raise VersionRetrievalError from e
