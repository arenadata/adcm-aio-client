import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

from adcm_aio_client.core.client import ADCMClient
from adcm_aio_client.core.filters import Filter
from adcm_aio_client.core.config import Parameter
from adcm_aio_client.core.objects.cm import Bundle, Cluster, Host
from tests.integration.bundle import pack_bundle
from tests.integration.conftest import BUNDLES

type TwoHosts = tuple[Host, Host]


pytestmark = [pytest.mark.asyncio]

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
    await cluster.services.add(filter_=Filter(attr="name", op="eq", value="with_host_actions"))
    return cluster


@pytest_asyncio.fixture()
async def hosts(adcm_client: ADCMClient, hostprovider_bundle: Bundle) -> TwoHosts:
    hp = await adcm_client.hostproviders.create(bundle=hostprovider_bundle, name="Awesome HostProvider")
    coros = (adcm_client.hosts.create(hostprovider=hp, name=f"host-{i+1}") for i in range(2))
    await asyncio.gather(*coros)
    hosts = await adcm_client.hosts.all()
    return tuple(hosts)  # type: ignore[reportReturnType]


async def test_run_action_with_mapping_and_config(adcm_client: ADCMClient, cluster: Cluster, hosts: TwoHosts) -> None:
    mapping = await cluster.mapping

    assert len(mapping.all()) == 0
    assert len(await mapping.hosts.all()) == 0
    assert len(await mapping.components.all()) == 2

    await cluster.hosts.add(host=hosts)
    host_1, host_2 = await mapping.hosts.all()

    service_1 = await cluster.services.get(display_name__eq="with_host_actions")
    component_1_s1 = await service_1.components.get(name__eq="c1")

    await mapping.add(component=component_1_s1, host=(host_1, host_2))
    assert len(tuple(mapping.iter())) == 2
    await mapping.save()

    # cluster_action = await cluster.actions.get(name__eq="fail")
    # await cluster_action.run()

    # host_action = await host_1.actions.all()
    # print(f"ACTIONS: {host_action}")
    # for action in host_action:
    #     print(action.name)

    host_action = await host_1.actions.get(name__eq="host_action_config")

    config = await component_1_s1.config
    field = config["very_important_flag"].value
    # print(f"field conf IS: {field}")



    task_config = await host_action.config
    print(f"task conf IS: {task_config}")


    # task_config = await host_action.config["very_important_flag"]
    # task_config.set("changed")


    job = await host_action.run()
    # new_config = {
    #     "new_important_flag": "changed",
    # }
    # await host_action.config(new_config)
    #
    # await host_action.run()

    # assert mapping.all() == []

