from collections.abc import AsyncGenerator, Generator

import pytest_asyncio

from adcm_aio_client import ADCMSession, Credentials
from adcm_aio_client.client import ADCMClient
from adcm_aio_client.objects import Bundle, Cluster, Host
from tests.integration.setup_environment import ADCMContainer

REQUEST_KWARGS: dict = {"timeout": 10, "retry_interval": 1, "retry_attempts": 1}
CREDENTIALS = Credentials(username="admin", password="admin")  # noqa: S106


@pytest_asyncio.fixture()
def adcm(
    adcm: ADCMContainer,
    simple_cluster_bundle: Bundle,
    complex_cluster_bundle: Bundle,
    previous_complex_cluster_bundle: Bundle,
    simple_hostprovider_bundle: Bundle,
) -> Generator[ADCMContainer, None, None]:
    _ = simple_cluster_bundle, complex_cluster_bundle, previous_complex_cluster_bundle, simple_hostprovider_bundle
    yield adcm


@pytest_asyncio.fixture()
async def admin_client(adcm: ADCMContainer) -> AsyncGenerator[ADCMClient, None]:
    async with ADCMSession(url=adcm.url, credentials=CREDENTIALS, **REQUEST_KWARGS) as client:
        yield client


@pytest_asyncio.fixture()
async def example_cluster(admin_client: ADCMClient) -> AsyncGenerator[Cluster, None]:
    cluster_bundle = await admin_client.bundles.get(name__eq="Some Cluster", version__eq="1")
    cluster = await admin_client.clusters.create(bundle=cluster_bundle, name="Example cluster")

    yield cluster

    await cluster.delete()


@pytest_asyncio.fixture()
async def three_hosts(admin_client: ADCMClient, simple_hostprovider_bundle: Bundle) -> list[Host]:
    provider = await admin_client.hostproviders.create(bundle=simple_hostprovider_bundle, name="Hostprovider")
    names = {"host-1", "host-2", "host-3"}
    for name in names:
        await admin_client.hosts.create(hostprovider=provider, name=name)

    return await admin_client.hosts.filter(name__in=names)
