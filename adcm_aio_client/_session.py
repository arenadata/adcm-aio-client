from json import JSONDecodeError
from types import TracebackType
from typing import Self

import httpx
import adcm_version

from adcm_aio_client.core.client import ADCMClient
from adcm_aio_client.core.errors import ClientInitError, NotSupportedVersionError
from adcm_aio_client.core.requesters import BundleRetriever, DefaultRequester
from adcm_aio_client.core.types import Cert, ConnectionSecurity, Credentials, RequestPolicy, RetryPolicy, SessionInfo

MIN_ADCM_VERSION = "2.5.0"


class ADCMSession:
    def __init__(
        self: Self,
        # basics
        url: str,
        credentials: Credentials,
        # security
        verify: str | bool = True,
        cert: Cert | None = None,
        # requesting behavior
        timeout: int = 600,
        retry_attempts: int = 3,
        retry_interval: int = 1,
    ) -> None:
        self._session_info = SessionInfo(
            url=url, credentials=credentials, security=ConnectionSecurity(verify=verify, certificate=cert)
        )
        self._request_policy = RequestPolicy(
            timeout=timeout, retry=RetryPolicy(attempts=retry_attempts, interval=retry_interval)
        )

        self._http_client = None
        self._requester = None
        self._adcm_client = None

    # Context Manager

    async def __aenter__(self: Self) -> ADCMClient:
        self._http_client = await self._prepare_http_client_for_running_adcm()
        adcm_version_ = await _ensure_adcm_version_is_supported(client=self._http_client)
        self._requester = self._prepare_api_v2_requester()
        # todo think about handling errors here
        #   so at least http client will be closed properly
        await self._requester.login(self._session_info.credentials)
        self._adcm_client = self._prepare_adcm_client(version=adcm_version_)
        return self._adcm_client

    async def __aexit__(
        self: Self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        if self._requester:
            try:
                await self._requester.logout()
            except:
                if self._http_client:
                    await self._http_client.__aexit__(exc_type, exc_value, traceback)

                raise

        if self._http_client:
            await self._http_client.__aexit__(exc_type, exc_value, traceback)

    # Steps

    async def _prepare_http_client_for_running_adcm(self: Self) -> httpx.AsyncClient:
        client = httpx.AsyncClient(
            base_url=self._session_info.url,
            timeout=self._request_policy.timeout,
            verify=self._session_info.security.verify,
            cert=self._session_info.security.certificate,
        )

        try:
            await client.head("/")
        except httpx.NetworkError as e:
            message = f"Failed to connect to ADCM at URL {self._session_info.url}"
            raise ClientInitError(message) from e

        return client

    def _prepare_api_v2_requester(self: Self) -> DefaultRequester:
        if self._http_client is None:
            message = "Failed to prepare requester: HTTP client is not initialized"
            raise RuntimeError(message)

        return DefaultRequester(http_client=self._http_client, retries=self._request_policy.retry)

    def _prepare_adcm_client(self: Self, version: str) -> ADCMClient:
        if self._requester is None:
            message = "Failed to prepare ADCM client: requester is not initialized"
            raise RuntimeError(message)

        bundle_retriever = BundleRetriever()

        return ADCMClient(requester=self._requester, bundle_retriever=bundle_retriever, adcm_version=version)


async def _ensure_adcm_version_is_supported(client: httpx.AsyncClient) -> str:
    try:
        # todo check for VERY old versions if that request will raise error
        response = await client.get("/versions/")
        data = response.json()
        version = str(data["adcm"]["version"])
    except (JSONDecodeError, KeyError):
        message = (
            f"Failed to detect ADCM version at {client.base_url}. "
            f"Most likely ADCM version is lesser than {MIN_ADCM_VERSION}"
        )
        raise NotSupportedVersionError(message)

    if adcm_version.compare_adcm_versions(version, MIN_ADCM_VERSION) < 0:
        message = f"Minimal supported ADCM version is {MIN_ADCM_VERSION}. Got {adcm_version}"
        raise NotSupportedVersionError(message)

    return version
