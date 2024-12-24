from pathlib import Path

import pytest
import pytest_asyncio

from adcm_aio_client.core.actions import ActionsAccessor
from adcm_aio_client.core.client import ADCMClient
from adcm_aio_client.core.errors import MultipleObjectsReturnedError, ObjectDoesNotExistError
from adcm_aio_client.core.filters import Filter
from adcm_aio_client.core.objects.cm import (
    Bundle,
    Cluster,
    Host,
    HostProvider,
)
from tests.integration.bundle import pack_bundle
from tests.integration.conftest import BUNDLES

pytestmark = [pytest.mark.asyncio]


@pytest_asyncio.fixture()
async def cluster_bundle(adcm_client: ADCMClient, tmp_path: Path) -> Bundle:
    bundle_path = pack_bundle(from_dir=BUNDLES / "complex_cluster", to=tmp_path)
    return await adcm_client.bundles.create(source=bundle_path)


@pytest_asyncio.fixture()
async def cluster(adcm_client: ADCMClient, cluster_bundle: Bundle) -> Cluster:
    return await adcm_client.clusters.create(bundle=cluster_bundle, name="Cluster", description="Cluster description")


@pytest_asyncio.fixture()
async def hostprovider_bundle(adcm_client: ADCMClient, tmp_path: Path) -> Bundle:
    bundle_path = pack_bundle(from_dir=BUNDLES / "complex_provider", to=tmp_path)
    return await adcm_client.bundles.create(source=bundle_path)


@pytest_asyncio.fixture()
async def hostprovider(adcm_client: ADCMClient, hostprovider_bundle: Bundle) -> HostProvider:
    return await adcm_client.hostproviders.create(
        bundle=hostprovider_bundle, name="Hostprovider name", description="Hostprovider description"
    )


async def test_host(adcm_client: ADCMClient, hostprovider: HostProvider, cluster: Cluster) -> None:
    await _test_host_properties(adcm_client, hostprovider, cluster)
    await _test_host_accessors(adcm_client, hostprovider, cluster)
    await _test_pagination(adcm_client, hostprovider, cluster)


async def _test_host_properties(adcm_client: ADCMClient, hostprovider: HostProvider, cluster: Cluster) -> None:
    await adcm_client.hosts.create(name="test-host", description="host description", hostprovider=hostprovider)
    await cluster.hosts.add(host=await adcm_client.hosts.get(name__eq="test-host"))

    host = await adcm_client.hosts.get()
    assert host.name == "test-host"
    assert (await host.hostprovider).name == hostprovider.name
    assert (await host.cluster).name == cluster.name  # pyright: ignore[reportOptionalMemberAccess]
    assert isinstance(host.actions, ActionsAccessor)
    assert await host.get_status() == "down"
    assert (await host.maintenance_mode).value == "off"


async def _test_host_accessors(adcm_client: ADCMClient, hostprovider: HostProvider, cluster: Cluster) -> None:
    for new_host in ["host-1", "host-2", "host-3"]:
        await adcm_client.hosts.create(name=new_host, description="host description", hostprovider=hostprovider)

    host = await adcm_client.hosts.get(name__eq="host-1")
    assert isinstance(host, Host)
    assert host.name == "host-1"

    with pytest.raises(ObjectDoesNotExistError):
        await adcm_client.hosts.get(name__eq="fake_host")

    with pytest.raises(MultipleObjectsReturnedError):
        await adcm_client.hosts.get(name__contains="host")

    assert not await adcm_client.hosts.get_or_none(name__eq="fake_host")
    assert isinstance(await adcm_client.hosts.get_or_none(name__contains="-1"), Host)

    assert len(await adcm_client.hosts.all()) == len(await adcm_client.hosts.list()) == 4

    hosts_list = await adcm_client.hosts.list(query={"limit": 2, "offset": 1})
    assert isinstance(hosts_list, list)
    assert len(hosts_list) == 2

    hosts_list = await adcm_client.hosts.list(query={"offset": 4})
    assert isinstance(hosts_list, list)
    assert len(hosts_list) == 0

    async for h in adcm_client.hosts.iter():
        assert isinstance(h, Host)
        assert "host" in h.name

    await cluster.hosts.add(host=await adcm_client.hosts.get(name__eq="host-1"))
    await cluster.hosts.add(host=Filter(attr="name", op="eq", value="host-2"))

    assert len(await cluster.hosts.all()) == 3

    await cluster.hosts.remove(host=await adcm_client.hosts.get(name__eq="host-1"))

    assert len(await cluster.hosts.all()) == 2

    host = await adcm_client.hosts.get(name__icontains="T-1")
    await host.delete()


async def _test_pagination(adcm_client: ADCMClient, hostprovider: HostProvider, cluster: Cluster) -> None:
    for i in range(55):
        await adcm_client.hosts.create(
            hostprovider=hostprovider,
            cluster=cluster,
            name=f"hostname-{i}",
        )

    hosts_list = await adcm_client.hosts.list()
    cluster_hosts_list = await cluster.hosts.list()
    assert len(hosts_list) == len(cluster_hosts_list) == 50

    hosts_list = await adcm_client.hosts.list(query={"offset": 55})
    cluster_hosts_list = await cluster.hosts.list(query={"offset": 55})
    assert len(hosts_list) == 3
    assert len(cluster_hosts_list) == 2

    hosts_list = await adcm_client.hosts.list(query={"offset": 60})
    cluster_hosts_list = await cluster.hosts.list(query={"offset": 60})
    assert len(hosts_list) == len(cluster_hosts_list) == 0

    hosts_list = await adcm_client.hosts.list(query={"limit": 10})
    cluster_hosts_list = await cluster.hosts.list(query={"limit": 10})
    assert len(hosts_list) == len(cluster_hosts_list) == 10

    assert len(await adcm_client.hosts.all()) == 58
    assert len(await cluster.hosts.all()) == 57

    assert len(await adcm_client.hosts.filter()) == 58
    assert len(await cluster.hosts.filter()) == 57
