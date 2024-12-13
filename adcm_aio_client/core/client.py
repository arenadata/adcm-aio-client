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

from dataclasses import dataclass
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


@dataclass(slots=True, frozen=True)
class RetryPolicy:
    max_attempts: int
    interval: float


@dataclass(slots=True, frozen=True)
class RequestPolicy:
    timeout: float
    retry: RetryPolicy


@dataclass(slots=True, frozen=True)
class SSLPolicy:
    verify: Verify | None
    cert: Cert | None


@dataclass(slots=True, frozen=True)
class ADCMConnection:
    url: str
    credentials: Credentials
    ssl: SSLPolicy


class ADCMClientSession:
    def __init__(
        self: Self,
        url: str,
        credentials: Credentials,
        *,
        verify: Verify | None = None,  # noqa: ARG001
        cert: Cert | None = None,  # noqa: ARG001
        timeout: float = 600.0,
        retries: int = 3,
        retry_interval: float = 1.0,
    ) -> None:
        self._request_policy = RequestPolicy(
            timeout=timeout, retry=RetryPolicy(max_attempts=retries, interval=retry_interval)
        )
        self._adcm_connection = ADCMConnection(
            url=url, credentials=credentials, ssl=SSLPolicy(verify=verify, cert=cert)
        )

    async def __aenter__(self):
        self._http_client = await self._build_http_client_for_accessible_url()
        # check out failing something below (like version check) and if aexit should be called
        await self._http_client.__aenter__()
        adcm_version = await self._retrieve_adcm_version(self._http_client)
        adcm_version = self._check_adcm_version(adcm_version)

        requester = DefaultRequester(base_url=url, retries=retries, retry_interval=retry_interval, timeout=timeout)
        await requester.login(credentials=credentials)

        bundle_retriever = BundleRetriever()
        adcm_client = ADCMClient(requester=requester, bundle_retriever=bundle_retriever, adcm_version=adcm_version)

        return adcm_client

    async def __aexit__(self, exc_type, exc, tb):
        # logout
        await self._http_client.__aexit__(exc_type, exc, tb)

    async def _build_http_client_for_accessible_url(self: Self) -> httpx.AsyncClient: ...

    async def _retrieve_adcm_version(self: Self, client: httpx.AsyncClient) -> str | None:
        versions_url = urljoin(self._adcm_connection.url, "versions/")

        try:
            response = await client.get(versions_url)
            data = response.json()
            return str(data["adcm"]["version"])
        except:
            # good place for logging what's actually happened
            return None

    def _check_adcm_version(self: Self, adcm_version: str | None) -> str:
        if adcm_version is None:
            message = (
                f"Failed to detect ADCM version at {self._adcm_connection.url}. "
                f"Most likely ADCM version is lesser than {MIN_ADCM_VERSION}"
            )
            raise NotSupportedVersionError(message)

        if compare_adcm_versions(adcm_version, MIN_ADCM_VERSION) < 0:
            message = f"Minimal supported ADCM version is {MIN_ADCM_VERSION}. Got {adcm_version}"
            raise NotSupportedVersionError(message)

        return adcm_version

    async def _get_and_check_adcm_version(self: Self, url: str, timeout: float) -> str:
        versions_url = urljoin(url, "versions/")

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(versions_url)

            data = response.json()
            adcm_version = data["adcm"]["version"]
        except VersionRetrievalError as e:
            message = f"Can't get ADCM version for {url}. Most likely ADCM version is lesser than {MIN_ADCM_VERSION}"
            raise NotSupportedVersionError(message) from e

        if compare_adcm_versions(adcm_version, MIN_ADCM_VERSION) < 0:
            message = f"Minimal supported ADCM version is {MIN_ADCM_VERSION}. Got {adcm_version}"
            raise NotSupportedVersionError(message)

        return adcm_version


async def build_client(
    url: str,
    credentials: Credentials,
    *,
    verify: Verify | None = None,  # noqa: ARG001
    cert: Cert | None = None,  # noqa: ARG001
    timeout: float = 1.5,
    retries: int = 5,
    retry_interval: float = 5.0,
) -> ADCMClient:
    adcm_version = await _get_and_check_adcm_version(url=url, timeout=timeout)
    requester = DefaultRequester(base_url=url, retries=retries, retry_interval=retry_interval, timeout=timeout)
    await requester.login(credentials=credentials)
    return ADCMClient(requester=requester, bundle_retriever=BundleRetriever(), adcm_version=adcm_version)
