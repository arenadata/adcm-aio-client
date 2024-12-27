from pathlib import Path

import pytest
import pytest_asyncio

from adcm_aio_client.core.actions import ActionsAccessor
from adcm_aio_client.core.client import ADCMClient
from adcm_aio_client.core.errors import MultipleObjectsReturnedError, ObjectDoesNotExistError
from adcm_aio_client.core.filters import Filter
from adcm_aio_client.core.host_groups.action_group import HostsInActionHostGroupNode
from adcm_aio_client.core.host_groups.config_group import HostsInConfigHostGroupNode
from adcm_aio_client.core.objects.cm import (
    Bundle,
    Cluster,
    Host,
    HostProvider,
    HostsInClusterNode,
    HostsNode,
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
    for i in range(55):
        await adcm_client.hosts.create(
            hostprovider=hostprovider,
            name=f"test-host-{i}",
        )

    await cluster.hosts.add(host=await adcm_client.hosts.get(name__eq="test-host-0"))
    await _test_host_properties(adcm_client.hosts, hostprovider, cluster)
    await _test_host_accessors(adcm_client.hosts, cluster)
    await _test_pagination(adcm_client.hosts)

    await cluster.hosts.add(host=(await adcm_client.hosts.all())[2:55])

    await _test_pagination(cluster.hosts)
    host = await adcm_client.hosts.get(name__icontains="T-10")
    await cluster.hosts.remove(host)
    await host.delete()


async def test_host_in_host_group(adcm_client: ADCMClient, hostprovider: HostProvider, cluster: Cluster) -> None:
    for i in range(80):
        await adcm_client.hosts.create(name=f"test-host-{i}", hostprovider=hostprovider, cluster=cluster)

    await cluster.config_host_groups.create(name="config-host-group", description="config host group description")
    await cluster.action_host_groups.create(name="action-host-group", description="action host group description")

    config_host_group = await cluster.config_host_groups.get(name__eq="config-host-group")
    action_host_group = await cluster.action_host_groups.get(name__eq="action-host-group")
    await config_host_group.hosts.add(await cluster.hosts.filter(name__contains="test-host"))
    await action_host_group.hosts.add(await cluster.hosts.filter(name__contains="test-host"))

    await _test_host_properties(config_host_group.hosts, hostprovider, cluster)
    await _test_host_properties(action_host_group.hosts, hostprovider, cluster)

    assert len(await config_host_group.hosts.all()) == 80
    assert len(await action_host_group.hosts.all()) == 80


async def _test_host_properties(
    hosts_node: HostsInActionHostGroupNode | HostsInConfigHostGroupNode | HostsNode,
    hostprovider: HostProvider,
    cluster: Cluster,
) -> None:
    host = await hosts_node.get(name__eq="test-host-0")
    assert host.name == "test-host-0"
    assert (await host.hostprovider).name == hostprovider.name
    assert (await host.cluster).name == cluster.name  # pyright: ignore[reportOptionalMemberAccess]
    assert isinstance(host.actions, ActionsAccessor)
    assert await host.get_status() == "down"
    assert (await host.maintenance_mode).value == "off"


async def _test_host_accessors(
    hosts_node: HostsInActionHostGroupNode | HostsInConfigHostGroupNode | HostsNode, cluster: Cluster
) -> None:
    host = await hosts_node.get(name__eq="test-host-1")
    assert isinstance(host, Host)

    with pytest.raises(ObjectDoesNotExistError):
        await hosts_node.get(name__eq="fake_host")

    with pytest.raises(MultipleObjectsReturnedError):
        await hosts_node.get(name__contains="test-host")

    assert not await hosts_node.get_or_none(name__eq="fake_host")
    assert isinstance(await hosts_node.get_or_none(name__contains="-10"), Host)

    assert len(await hosts_node.list()) == 50
    assert len(await hosts_node.all()) == 55

    hosts_list = await hosts_node.list(query={"limit": 2, "offset": 53})
    assert isinstance(hosts_list, list)
    assert len(hosts_list) == 2

    hosts_list = await hosts_node.list(query={"offset": 55})
    assert isinstance(hosts_list, list)
    assert len(hosts_list) == 0

    async for h in hosts_node.iter():
        assert isinstance(h, Host)
        assert "host" in h.name

    await cluster.hosts.add(host=await hosts_node.get(name__eq="test-host-1"))
    await cluster.hosts.add(host=Filter(attr="name", op="eq", value="test-host-2"))

    assert len(await cluster.hosts.all()) == 3

    await cluster.hosts.remove(host=await hosts_node.get(name__eq="test-host-2"))

    assert len(await cluster.hosts.all()) == 2


async def _test_pagination(
    hosts_node: HostsNode | HostsInClusterNode,
) -> None:
    hosts_list = await hosts_node.list()
    assert len(hosts_list) == 50

    hosts_list = await hosts_node.list(query={"offset": 60})
    assert len(hosts_list) == 0

    hosts_list = await hosts_node.list(query={"limit": 10})
    assert len(hosts_list) == 10

    assert len(await hosts_node.all()) == 55
