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

from datetime import datetime
from itertools import chain
from operator import attrgetter
import asyncio

import pytest
import pytest_asyncio

from adcm_aio_client import Filter
from adcm_aio_client._filters import FilterValue
from adcm_aio_client._types import WithID
from adcm_aio_client.client import ADCMClient
from adcm_aio_client.host_groups._action_group import ActionHostGroup
from adcm_aio_client.objects import Bundle, Cluster, Component, Job
from adcm_aio_client.objects._common import WithActions

pytestmark = [pytest.mark.asyncio]


async def is_running(job: Job) -> bool:
    return await job.get_status() == "running"


async def run_non_blocking(target: WithActions, **filters: FilterValue) -> Job:
    action = await target.actions.get(**filters)
    action.blocking = False
    return await action.run()


async def check_job_object(job: Job, object_: WithID) -> None:
    expected_type = object_.__class__
    expected_id = object_.id

    actual_object = await job.object

    assert isinstance(actual_object, expected_type)
    assert actual_object.id == expected_id


@pytest_asyncio.fixture()
async def prepare_environment(
    adcm_client: ADCMClient,
    complex_cluster_bundle: Bundle,
    simple_hostprovider_bundle: Bundle,
) -> None:
    cluster_bundle = complex_cluster_bundle
    hostprovider_bundle = simple_hostprovider_bundle

    clusters: list[Cluster] = await asyncio.gather(
        *(adcm_client.clusters.create(cluster_bundle, f"wow-{i}") for i in range(5))
    )
    hostproviders = await asyncio.gather(
        *(adcm_client.hostproviders.create(hostprovider_bundle, f"yay-{i}") for i in range(5))
    )
    await asyncio.gather(
        *(adcm_client.hosts.create(hp, f"host-{hp.name}-{i}") for i in range(5) for hp in hostproviders)
    )
    hosts = await adcm_client.hosts.all()

    services = tuple(
        chain.from_iterable(
            await asyncio.gather(
                *(cluster.services.add(Filter(attr="name", op="eq", value="with_actions")) for cluster in clusters)
            )
        )
    )
    components = tuple(chain.from_iterable(await asyncio.gather(*(service.components.all() for service in services))))

    host_groups = await asyncio.gather(
        *(
            object_.action_host_groups.create(name=f"ahg for {object_.__class__.__name__}")
            for object_ in chain(clusters, services, components)
        )
    )

    for object_ in chain(clusters, services, components, hosts, hostproviders):
        await run_non_blocking(object_, name__eq="success")

    for group in host_groups:
        await run_non_blocking(group, name__in=["fail"])


@pytest.mark.usefixtures("prepare_environment")
@pytest.mark.parametrize("adcm_client", [{"timeout": 60}], ids=["t60"], indirect=True)
async def test_jobs_api(adcm_client: ADCMClient) -> None:
    await _test_basic_api(adcm_client)
    await _test_job_object(adcm_client)
    await _test_collection_fitlering(adcm_client)


async def _test_basic_api(adcm_client: ADCMClient) -> None:
    cluster = await adcm_client.clusters.get(name__eq="wow-4")
    service = await cluster.services.get(name__contains="action")
    component = await service.components.get(display_name__icontains="wESo")

    action = await component.actions.get(display_name__ieq="Lots of me")
    job = await action.run()
    # depending on retrieval time it's "one of"
    assert await job.get_status() in ("created", "running")
    assert job.start_time is None
    assert job.finish_time is None
    assert (await job.action).id == action.id

    await job.wait(exit_condition=is_running, timeout=30, poll_interval=1)
    assert job.start_time is None
    await job.refresh()
    assert isinstance(job.start_time, datetime)
    assert job.finish_time is None

    target = await job.object
    assert isinstance(target, Component)
    assert target.id == component.id
    assert target.service.id == component.service.id

    await job.wait(timeout=30, poll_interval=3)

    assert await job.get_status() == "success"
    assert job.finish_time is None
    await job.refresh()
    assert isinstance(job.finish_time, datetime)


async def _test_job_object(adcm_client: ADCMClient) -> None:
    cluster, *_ = await adcm_client.clusters.list(query={"limit": 1, "offset": 4})
    service = await cluster.services.get()
    component = await service.components.get(name__eq="c2")
    hostprovider, *_ = await adcm_client.hostproviders.list(query={"limit": 1, "offset": 2})
    host, *_ = await adcm_client.hosts.list(query={"limit": 1, "offset": 4})

    host_group_1 = await service.action_host_groups.get()
    host_group_2 = await component.action_host_groups.get()

    all_targets = (cluster, service, component, hostprovider, host, host_group_1, host_group_2)

    for target in all_targets:
        jobs = await adcm_client.jobs.filter(object=target)
        assert len(jobs) == 1, f"Amount of jobs is incorrect for {target}: {len(jobs)}. Expected 1"
        job = jobs[0]
        await check_job_object(job=job, object_=target)  # type: ignore


async def _test_collection_fitlering(adcm_client: ADCMClient) -> None:
    failed_jobs = 20
    services_amount = 5

    for job in await adcm_client.jobs.all():
        await job.wait(timeout=60)

    jobs = await adcm_client.jobs.list()
    assert len(jobs) == 50

    jobs = await adcm_client.jobs.all()
    total_jobs = len(jobs)
    assert total_jobs > 50

    cases = (
        # status
        ("status__eq", "failed", failed_jobs),
        ("status__ieq", "faiLed", failed_jobs),
        ("status__ne", "success", failed_jobs),
        ("status__ine", "succEss", failed_jobs),
        ("status__in", ("failed", "success"), total_jobs),
        ("status__iin", ("faIled", "sUcceSs"), total_jobs),
        ("status__exclude", ("failed", "success"), 0),
        ("status__iexclude", ("succesS",), failed_jobs),
        # name
        ("name__eq", "fail", failed_jobs),
        ("name__ieq", "FaIl", failed_jobs),
        ("name__ne", "fail", total_jobs - failed_jobs),
        ("name__ine", "FaIl", total_jobs - failed_jobs),
        ("name__in", ("success", "success_task"), total_jobs - failed_jobs),
        ("name__iin", ("sUccEss", "success_Task"), total_jobs - failed_jobs),
        ("name__exclude", ("success",), failed_jobs + 1),
        ("name__iexclude", ("success",), failed_jobs + 1),
        ("name__contains", "il", failed_jobs),
        ("name__icontains", "I", failed_jobs),
        # display_name
        ("display_name__eq", "no Way", failed_jobs),
        ("display_name__ieq", "No way", failed_jobs),
        ("display_name__ne", "no Way", total_jobs - failed_jobs),
        ("display_name__ine", "No way", total_jobs - failed_jobs),
        ("display_name__in", ("I will survive", "Lots Of me"), total_jobs - failed_jobs),
        ("display_name__iin", ("i will survive", "lots of me"), total_jobs - failed_jobs),
        ("display_name__exclude", ("I will survive",), failed_jobs + 1),
        ("display_name__iexclude", ("i will survive",), failed_jobs + 1),
        ("display_name__contains", "W", failed_jobs),
        ("display_name__icontains", "W", total_jobs - 1),
    )

    for inline_filter, value, expected_amount in cases:
        filter_ = {inline_filter: value}
        result = await adcm_client.jobs.filter(**filter_)  # type: ignore
        actual_amount = len(result)
        assert (
            actual_amount == expected_amount
        ), f"Incorrect amount for {filter_=}\nExpected: {expected_amount}\nActual: {actual_amount}"
        unique_entries = set(map(attrgetter("id"), result))
        assert len(unique_entries) == expected_amount

    cluster = await adcm_client.clusters.get(name__eq="wow-4")
    service = await cluster.services.get()
    service_ahg = await service.action_host_groups.get()

    fail_action = await service.actions.get(name__eq="fail")
    success_action = await service.actions.get(name__eq="success")

    jobs = [job async for job in adcm_client.jobs.iter(action__eq=fail_action)]
    assert len(jobs) == 5
    objects = []
    for job in jobs:
        objects.append(await job.object)
    assert all(isinstance(o, ActionHostGroup) for o in objects)
    assert any(o.id == service_ahg.id for o in objects)

    job = await adcm_client.jobs.get_or_none(action__in=(fail_action, success_action), status__eq="notexist")
    assert job is None

    jobs = await adcm_client.jobs.filter(action__ne=success_action)
    assert len(jobs) == total_jobs - services_amount

    jobs = await adcm_client.jobs.filter(action__exclude=(success_action,))
    assert len(jobs) == total_jobs - services_amount
