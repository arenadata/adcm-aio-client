from pathlib import Path

import pytest
import pytest_asyncio

from adcm_aio_client.core.actions._objects import ActionsAccessor
from adcm_aio_client.core.client import ADCMClient
from adcm_aio_client.core.config import ObjectConfig
from adcm_aio_client.core.errors import MultipleObjectsReturnedError, ObjectDoesNotExistError
from adcm_aio_client.core.host_groups._common import HostsInHostGroupNode
from adcm_aio_client.core.host_groups.action_group import (
    ActionHostGroup,
    ActionHostGroupNode,
    HostsInActionHostGroupNode,
)
from adcm_aio_client.core.host_groups.config_group import (
    ConfigHostGroup,
    ConfigHostGroupNode,
)
from adcm_aio_client.core.objects.cm import Bundle, Cluster, HostProvider
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


async def test_host_groups(adcm_client: ADCMClient, cluster: Cluster, hostprovider: HostProvider) -> None:
    for i in range(80):
        await adcm_client.hosts.create(name=f"test-host-{i}", hostprovider=hostprovider, cluster=cluster)

    for i in range(55):
        await cluster.action_host_groups.create(name=f"host-group-{i}", description=f"host group description {i}")
        await hostprovider.config_host_groups.create(name=f"host-group-{i}", description=f"host group description {i}")
        await cluster.config_host_groups.create(name=f"host-group-{i}", description=f"host group description {i}")

    action_host_group = await cluster.action_host_groups.get(name__eq="host-group-35")
    config_host_groups_provider = await hostprovider.config_host_groups.get(name__eq="host-group-35")
    config_host_groups_cluster = await cluster.config_host_groups.get(name__eq="host-group-35")

    await action_host_group.hosts.add(host=await cluster.hosts.filter(name__contains="test-host"))
    await config_host_groups_provider.hosts.add(host=await adcm_client.hosts.filter(name__contains="test-host"))
    await config_host_groups_cluster.hosts.add(host=await adcm_client.hosts.filter(name__contains="test-host"))

    await _test_host_group_properties(cluster.action_host_groups)
    await _test_host_group_accessors(cluster.action_host_groups)
    await _test_pagination_action_host_group(cluster.action_host_groups)

    await _test_host_group_properties(hostprovider.config_host_groups)
    await _test_host_group_accessors(hostprovider.config_host_groups)
    await _test_pagination_action_host_group(hostprovider.config_host_groups)

    await _test_host_group_properties(cluster.config_host_groups)
    await _test_host_group_accessors(cluster.config_host_groups)
    await _test_pagination_action_host_group(cluster.config_host_groups)


async def _test_host_group_properties(host_group_node: ActionHostGroupNode | ConfigHostGroupNode) -> None:
    host_group = await host_group_node.get(name__eq="host-group-35")
    assert host_group.name == "host-group-35"
    assert host_group.description == "host group description 35"

    hosts_all = await host_group.hosts.all()
    assert len(hosts_all) == 80

    if isinstance(host_group_node, ConfigHostGroupNode):
        assert isinstance(host_group, ConfigHostGroup)
        assert isinstance(await host_group.config, ObjectConfig)
        assert isinstance(host_group.hosts, HostsInHostGroupNode)
    else:
        assert isinstance(host_group, ActionHostGroup)
        assert isinstance(host_group.hosts, HostsInActionHostGroupNode)
        assert isinstance(host_group.actions, ActionsAccessor)
        actions = await host_group.actions.all()
        assert len(actions) == 6


async def _test_host_group_accessors(host_group_node: ActionHostGroupNode | ConfigHostGroupNode) -> None:
    host_group_type = ActionHostGroup if isinstance(host_group_node, ActionHostGroupNode) else ConfigHostGroup

    assert not await host_group_node.get_or_none(name__eq="host-group-350")
    assert isinstance(await host_group_node.get(name__eq="host-group-35"), host_group_type)

    with pytest.raises(ObjectDoesNotExistError):
        await host_group_node.get(name__eq="fake_host-group")

    with pytest.raises(MultipleObjectsReturnedError):
        await host_group_node.get(name__ne="fake_host-group")

    assert len(await host_group_node.all()) == 55

    action_host_group_list = await host_group_node.list(query={"limit": 2, "offset": 1})
    assert isinstance(action_host_group_list, list)
    assert len(action_host_group_list) == 2

    action_host_group_list = await host_group_node.list(query={"offset": 55})
    assert isinstance(action_host_group_list, list)
    assert len(action_host_group_list) == 0

    async for a_h_group in host_group_node.iter():
        assert isinstance(a_h_group, host_group_type)
        assert "host-group" in a_h_group.name.lower()

    assert len(await host_group_node.filter(name__contains="host-group-5")) == 6

    await (await host_group_node.get(name__eq="host-group-54")).delete()
    assert len(await host_group_node.all()) == 54


async def _test_pagination_action_host_group(host_group_node: ActionHostGroupNode | ConfigHostGroupNode) -> None:
    host_group_list = await host_group_node.list()
    assert len(host_group_list) == 50
    host_group_list = await host_group_node.list(query={"offset": 55})
    assert len(host_group_list) == 0

    host_group_list = await host_group_node.list(query={"offset": 60})
    assert len(host_group_list) == 0

    host_group_list = await host_group_node.list(query={"limit": 10})
    assert len(host_group_list) == 10

    assert len(await host_group_node.all()) == 54
    assert len(await host_group_node.filter()) == 54
