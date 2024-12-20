from datetime import datetime
from itertools import chain
import asyncio

import pytest
import pytest_asyncio

from adcm_aio_client.core.client import ADCMClient
from adcm_aio_client.core.filters import Filter, FilterValue
from adcm_aio_client.core.objects._common import WithActions
from adcm_aio_client.core.objects.cm import Bundle, Cluster, Component, Job

pytestmark = [pytest.mark.asyncio]


async def run_non_blocking(target: WithActions, **filters: FilterValue) -> Job:
    action = await target.actions.get(**filters)
    action.blocking = False
    return await action.run()


@pytest_asyncio.fixture()
async def prepare_environment(
    adcm_client: ADCMClient,
    complex_cluster_bundle: Bundle,
    simple_hostprovider_bundle: Bundle,
) -> list[Job]:
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

    object_jobs = asyncio.gather(
        *(
            run_non_blocking(object_, name__eq="success")
            for object_ in chain(clusters, services, components, hosts, hostproviders)
        )
    )

    group_jobs = asyncio.gather(*(run_non_blocking(group, name__in=["fail"]) for group in host_groups))

    return await object_jobs + await group_jobs


@pytest.mark.usefixtures("prepare_environment")
async def test_jobs_api(adcm_client: ADCMClient) -> None:
    await _test_basic_api(adcm_client)
    await _test_job_object(adcm_client)
    await _test_collection_fitlering(adcm_client)


async def is_running(job: Job) -> bool:
    return await job.get_status() == "running"


async def _test_basic_api(adcm_client: ADCMClient) -> None:
    # fields: id, name, display_name, start_time, finish_time
    # properties: object, action
    # methods: get_status, wait, terminate
    # refresh (with wait)
    cluster, *_ = await adcm_client.clusters.list(query={"limit": 1, "offset": 3})
    service = await cluster.services.get(name__contains="action")
    component = await service.components.get(display_name__icontains="wESo")

    action = await component.actions.get(display_name__ieq="Lots of me")
    job = await action.run()
    # depending on retrieval time it's "one of"
    assert await job.get_status() in ("created", "running")
    assert job.start_time is None
    assert job.finish_time is None
    assert (await job.action).id == action.id

    await job.wait(exit_condition=is_running, timeout=5, poll_interval=1)
    assert job.start_time is None
    await job.refresh()
    assert isinstance(job.start_time, datetime)
    assert job.finish_time is None

    target = await job.object
    assert isinstance(target, Component)
    assert target.id == component.id
    assert target.service.id == component.service.id

    await job.wait(timeout=10, poll_interval=1)

    assert await job.get_status() == "success"
    assert job.finish_time is None
    await job.refresh()
    assert isinstance(job.finish_time, datetime)


async def _test_job_object(adcm_client: ADCMClient) -> None:
    # filter by object
    # detect object from Job
    ...


async def _test_collection_fitlering(adcm_client: ADCMClient) -> None:
    # filters: status, name, display_name, action
    # special filter: object
    ...
