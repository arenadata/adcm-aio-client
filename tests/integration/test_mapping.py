from pathlib import Path
import asyncio

import pytest
import pytest_asyncio

from adcm_aio_client.core.client import ADCMClient
from adcm_aio_client.core.filters import Filter
from adcm_aio_client.core.objects.cm import Bundle, Cluster, Host
from tests.integration.bundle import pack_bundle
from tests.integration.conftest import BUNDLES

pytestmark = [pytest.mark.asyncio]

type FiveHosts = tuple[Host, Host, Host, Host, Host]


@pytest_asyncio.fixture()
async def cluster_bundle(adcm_client: ADCMClient, tmp_path: Path) -> Bundle:
    bundle_path = pack_bundle(from_dir=BUNDLES / "complex_cluster", to=tmp_path)
    return await adcm_client.bundles.create(source=bundle_path, accept_license=True)


@pytest_asyncio.fixture()
async def hostprovider_bundle(adcm_client: ADCMClient, tmp_path: Path) -> Bundle:
    bundle_path = pack_bundle(from_dir=BUNDLES / "simple_hostprovider", to=tmp_path)
    return await adcm_client.bundles.create(source=bundle_path, accept_license=True)


@pytest_asyncio.fixture()
async def cluster(adcm_client: ADCMClient, cluster_bundle: Bundle) -> Cluster:
    cluster = await adcm_client.clusters.create(bundle=cluster_bundle, name="Awesome Cluster")
    await cluster.services.add(filter_=Filter(attr="name", op="contains", value="example"))
    return cluster


@pytest_asyncio.fixture()
async def hosts(adcm_client: ADCMClient, hostprovider_bundle: Bundle) -> FiveHosts:
    hp = await adcm_client.hostproviders.create(bundle=hostprovider_bundle, name="Awesome HostProvider")
    coros = (adcm_client.hosts.create(hostprovider=hp, name=f"host-{i}") for i in range(5))
    await asyncio.gather(*coros)
    hosts = await adcm_client.hosts.all()
    return tuple(hosts)  # type: ignore[reportReturnType]


async def test_cluster_mapping(cluster: Cluster, hosts: FiveHosts) -> None:
    mapping = await cluster.mapping

    assert len(mapping.all()) == 0
    assert len(await mapping.hosts.all()) == 0
    assert len(await mapping.components.all()) == 6

    await cluster.hosts.add(host=hosts)
    host_1, host_2, host_3, host_4, host_5 = await mapping.hosts.all()

    service_1 = await cluster.services.get(display_name__eq="First Example")
    service_2 = await cluster.services.get(name__eq="example_2")

    component_1_s1 = await service_1.components.get(name__eq="first")
    component_2_s2 = await service_2.components.get(display_name__in=["Second Component"])

    await mapping.add(component=component_1_s1, host=host_1)
    assert len(tuple(mapping.iter())) == 1

    await mapping.add(component=(component_1_s1, component_2_s2), host=(host_1, host_3, host_4))
    assert len(mapping.all()) == 6

    print(await mapping.components.filter(display_name__icontains="different"))
    print(await mapping.hosts.filter(name__in=(host_2.name, host_5.name)))

    await mapping.add(
        component=await mapping.components.filter(display_name__icontains="different"),
        host=Filter(attr="name", op="in", value=(host_2.name, host_5.name)),
    )
    assert len(mapping.all()) == 10
