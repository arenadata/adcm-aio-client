# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from collections.abc import Iterable
from itertools import chain
import asyncio

import pytest
import pytest_asyncio

from adcm_aio_client import Filter
from adcm_aio_client.client import ADCMClient
from adcm_aio_client.config import Parameter
from adcm_aio_client.mapping._types import MappingPair
from adcm_aio_client.objects import Bundle, Cluster, Host, Job

pytestmark = [pytest.mark.asyncio]

type TwoHosts = tuple[Host, Host]


async def is_success(job: Job) -> bool:
    return await job.get_status() == "success"


async def is_aborted(job: Job) -> bool:
    return await job.get_status() == "aborted"


async def is_running(job: Job) -> bool:
    return await job.get_status() == "running"


def build_name_mapping(*iterables: Iterable[MappingPair]) -> set[tuple[str, str, str]]:
    return {(c.service.name, c.name, h.name) for c, h in chain.from_iterable(iterables)}


@pytest_asyncio.fixture()
async def cluster(adcm_client: ADCMClient, complex_cluster_bundle: Bundle) -> Cluster:
    cluster = await adcm_client.clusters.create(bundle=complex_cluster_bundle, name="Awesome Cluster")
    await cluster.services.add(filter_=Filter(attr="name", op="eq", value="with_host_actions"))
    return cluster


@pytest_asyncio.fixture()
async def hosts(adcm_client: ADCMClient, simple_hostprovider_bundle: Bundle) -> TwoHosts:
    hp = await adcm_client.hostproviders.create(bundle=simple_hostprovider_bundle, name="Awesome HostProvider")
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
    component_2_s1 = await service_1.components.get(name__eq="c2")

    await mapping.add(component=component_1_s1, host=(host_1, host_2))
    assert len(tuple(mapping.iter())) == 2
    await mapping.save()

    ## run action host_action_config_hc_acl

    host_action = await host_1.actions.get(name__eq="host_action_config_hc_acl")

    action_mapping = await host_action.mapping
    await action_mapping.remove(component=component_1_s1, host=host_1)
    await action_mapping.add(component=component_2_s1, host=host_1)

    action_config = await host_action.config
    action_config["very_important_flag", Parameter].set("changed")

    job = await host_action.run()
    assert await job.get_status() in ("created", "running")
    await job.wait(exit_condition=is_success, timeout=30, poll_interval=1)

    ## check mapping after action

    cluster_alt = await adcm_client.clusters.get(name__eq=cluster.name)
    mapping_alt = await cluster_alt.mapping

    expected_mapping = build_name_mapping(((component_1_s1, host_2), (component_2_s1, host_1)))
    actual_mapping = build_name_mapping(mapping_alt.iter())
    assert actual_mapping == expected_mapping


async def test_terminate_action_with_config(cluster: Cluster, hosts: TwoHosts) -> None:
    mapping = await cluster.mapping
    await cluster.hosts.add(host=hosts)
    host_1, host_2 = await mapping.hosts.all()

    service_1 = await cluster.services.get(display_name__eq="with_host_actions")
    component_1_s1 = await service_1.components.get(name__eq="c1")
    component_2_s1 = await service_1.components.get(name__eq="c2")

    await mapping.add(component=component_1_s1, host=(host_1, host_2))
    assert len(tuple(mapping.iter())) == 2
    await mapping.save()

    ## terminate host_action_config_hc_acl

    host_1, host_2 = await mapping.hosts.all()
    host_action = await host_2.actions.get(name__eq="host_action_config_hc_acl")

    action_mapping = await host_action.mapping
    await action_mapping.remove(component=component_1_s1, host=host_2)
    await action_mapping.remove(component=component_2_s1, host=host_2)

    action_config = await host_action.config
    action_config["very_important_flag", Parameter].set("will be terminated")

    job = await host_action.run()
    await job.wait(exit_condition=is_running, timeout=10, poll_interval=1)
    await job.terminate()

    await job.wait(exit_condition=is_aborted, timeout=30, poll_interval=1)
