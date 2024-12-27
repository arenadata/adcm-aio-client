from pathlib import Path
from typing import NamedTuple

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


class Expected(NamedTuple):
    name: str
    description: str
    provider_id: int
    cluster_id: int
    status: str = "down"
    maintenance_mode: str = "off"


@pytest_asyncio.fixture()
async def cluster(adcm_client: ADCMClient, complex_cluster_bundle: Bundle) -> Cluster:
    return await adcm_client.clusters.create(
        bundle=complex_cluster_bundle, name="Cluster", description="Cluster description"
    )


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
    expected = Expected(name="test-host", description="description", cluster_id=cluster.id, provider_id=hostprovider.id)

    await adcm_client.hosts.create(name=expected.name, description=expected.description, hostprovider=hostprovider)
    host = await adcm_client.hosts.get(name__eq=expected.name)
    await cluster.hosts.add(host=host)
    await host.refresh()

    await _test_host_properties(host, expected)
    await _test_host_accessors(adcm_client, hostprovider, cluster)
    await _test_pagination(adcm_client, hostprovider, cluster)


async def test_host_objects(
    adcm_client: ADCMClient, hostprovider_bundle: Bundle, complex_cluster_bundle: Bundle
) -> None:
    """Testing similarity, accessibility of attributes of host objects got from different sources"""

    host_name = "Target-test-host"
    provider = await adcm_client.hostproviders.create(bundle=hostprovider_bundle, name="New provider")
    await adcm_client.hosts.create(hostprovider=provider, name=host_name)
    target_host = await adcm_client.hosts.get(name__eq=host_name)

    cluster = await adcm_client.clusters.create(
        bundle=complex_cluster_bundle, name="Cluster with hosts", description="descr"
    )
    service = (await cluster.services.add(Filter(attr="name", op="eq", value="example_1")))[0]
    component = await service.components.get(name__eq="first")

    await cluster.hosts.add(host=target_host)
    await target_host.refresh()

    mapping = await cluster.mapping
    await mapping.add(component=component, host=target_host)
    await mapping.save()

    chg = await cluster.config_host_groups.create(name="chg", hosts=[target_host])
    ahg = await cluster.action_host_groups.create(name="ahg", hosts=[target_host])

    expected = Expected(name=host_name, description="", cluster_id=cluster.id, provider_id=provider.id)
    from_chg = await chg.hosts.get(name__eq=expected.name)
    await _test_host_properties(from_chg, expected)
    from_ahg = await ahg.hosts.get(name__eq=expected.name)
    await _test_host_properties(from_ahg, expected)
    from_mapping = await mapping.hosts.get(name__eq=expected.name)
    await _test_host_properties(from_mapping, expected)
    from_cluster = await cluster.hosts.get(name__eq=expected.name)
    await _test_host_properties(from_cluster, expected)
    from_component = await component.hosts.get(name__eq=expected.name)
    await _test_host_properties(from_component, expected)
    from_provider = await provider.hosts.get(name__eq=expected.name)
    await _test_host_properties(from_provider, expected)

    assert (
        target_host.id
        == from_chg.id
        == from_ahg.id
        == from_mapping.id
        == from_cluster.id
        == from_component.id
        == from_provider.id
    )


async def _test_host_properties(host: Host, expected: Expected) -> None:
    assert host.name == expected.name
    assert (await host.hostprovider).id == expected.provider_id
    assert (host_cluster := await host.cluster) is not None
    assert host_cluster.id == expected.cluster_id
    assert isinstance(host.actions, ActionsAccessor)
    assert await host.get_status() == expected.status
    assert (await host.maintenance_mode).value == expected.maintenance_mode


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
