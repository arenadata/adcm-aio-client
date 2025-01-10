from typing import NamedTuple

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

pytestmark = [pytest.mark.asyncio]


class Expected(NamedTuple):
    name: str
    description: str
    provider_id: int
    cluster_id: int | None
    status: str = "down"
    maintenance_mode: str = "off"


@pytest_asyncio.fixture()
async def cluster(adcm_client: ADCMClient, complex_cluster_bundle: Bundle) -> Cluster:
    return await adcm_client.clusters.create(
        bundle=complex_cluster_bundle, name="Cluster", description="Cluster description"
    )


@pytest_asyncio.fixture()
async def hostprovider(adcm_client: ADCMClient, complex_hostprovider_bundle: Bundle) -> HostProvider:
    return await adcm_client.hostproviders.create(
        bundle=complex_hostprovider_bundle, name="Hostprovider name", description="Hostprovider description"
    )


async def test_host(adcm_client: ADCMClient, hostprovider: HostProvider, cluster: Cluster) -> None:
    for i in range(55):
        await adcm_client.hosts.create(
            hostprovider=hostprovider,
            name=f"test-host-{i}",
        )

    expected = Expected(name="test-host-0", description="", cluster_id=cluster.id, provider_id=hostprovider.id)
    host = await adcm_client.hosts.get(name__eq=expected.name)
    await cluster.hosts.add(host=host)
    await host.refresh()

    await _test_host_properties(host, expected)
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

    expected = Expected(name="test-host-0", description="", cluster_id=cluster.id, provider_id=hostprovider.id)
    await _test_host_properties(await config_host_group.hosts.get(name__eq=expected.name), expected)
    await _test_host_properties(await action_host_group.hosts.get(name__eq=expected.name), expected)

    assert len(await config_host_group.hosts.all()) == 80
    assert len(await action_host_group.hosts.all()) == 80


async def test_host_objects(
    adcm_client: ADCMClient, complex_hostprovider_bundle: Bundle, complex_cluster_bundle: Bundle
) -> None:
    """Testing similarity, accessibility of attributes of host objects got from different sources"""

    host_name = "Target-test-host"
    provider = await adcm_client.hostproviders.create(bundle=complex_hostprovider_bundle, name="New provider")
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
    assert isinstance(host.id, int)
    assert host.name == expected.name
    assert isinstance(host_cluster := await host.cluster, Cluster)
    assert host_cluster.id == expected.cluster_id
    assert isinstance(host.actions, ActionsAccessor)
    assert isinstance(await host.actions.all(), list)
    assert await host.get_status() == expected.status
    assert (await host.hostprovider).id == expected.provider_id
    assert (await host.maintenance_mode).value == expected.maintenance_mode


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
