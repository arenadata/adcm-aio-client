from typing import NamedTuple

from httpx import AsyncClient
import pytest
import pytest_asyncio

from adcm_aio_client import Filter
from adcm_aio_client.client import ADCMClient
from adcm_aio_client.errors import ConflictError
from adcm_aio_client.objects import Bundle, Component, Host, Service

pytestmark = [pytest.mark.asyncio]


class Context(NamedTuple):
    client: ADCMClient
    httpx_client: AsyncClient
    service: Service
    first_component: Component
    second_component: Component
    host_1: Host
    host_2: Host
    # second set of objects with defined MM actions
    service_2: Service
    first_component_2: Component
    host_3: Host


async def get_object_mm(obj: Service | Component | Host, httpx_client: AsyncClient) -> str:
    url = "/".join(map(str, (*obj.get_own_path(), "")))
    response = await httpx_client.get(url=url)
    assert response.status_code == 200

    return response.json()["maintenanceMode"]


@pytest_asyncio.fixture()
async def context(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    complex_cluster_bundle: Bundle,
    previous_complex_cluster_bundle: Bundle,
    simple_hostprovider_bundle: Bundle,
) -> Context:
    cluster = await adcm_client.clusters.create(bundle=complex_cluster_bundle, name="Test cluster with mm")

    service = await cluster.services.add(filter_=Filter(attr="name", op="eq", value="example_1"))
    assert len(service) == 1
    service = service[0]

    provider = await adcm_client.hostproviders.create(bundle=simple_hostprovider_bundle, name="Test simple provider")
    host_1 = await adcm_client.hosts.create(hostprovider=provider, name="host-1", cluster=cluster)
    host_2 = await adcm_client.hosts.create(hostprovider=provider, name="host-2", cluster=cluster)

    first_component = await service.components.get(name__eq="first")
    mapping = await cluster.mapping
    await mapping.add(component=first_component, host=(host_1, host_2))
    await mapping.save()

    second_component = await service.components.get(name__eq="second")

    # with mm actions
    cluster_2 = await adcm_client.clusters.create(bundle=previous_complex_cluster_bundle, name="Test cluster 2 with mm")
    service_2 = await cluster_2.services.add(filter_=Filter(attr="name", op="eq", value="example_1"))
    assert len(service_2) == 1
    service_2 = service_2[0]
    first_component_2 = await service_2.components.get(name__eq="first")

    host_3 = await adcm_client.hosts.create(hostprovider=provider, name="host-3", cluster=cluster_2)

    mapping_2 = await cluster_2.mapping
    await mapping_2.add(component=first_component_2, host=host_3)
    await mapping_2.save()

    return Context(
        client=adcm_client,
        httpx_client=httpx_client,
        service=service,
        first_component=first_component,
        second_component=second_component,
        host_1=host_1,
        host_2=host_2,
        service_2=service_2,
        first_component_2=first_component_2,
        host_3=host_3,
    )


async def test_maintenance_mode(context: Context) -> None:
    for obj in [context.service, context.second_component, context.host_2]:
        await _test_direct_maintenance_mode_change(obj=obj, httpx_client=context.httpx_client)

    await _test_indirect_mm_change(context=context)

    for obj in [context.service_2, context.first_component_2, context.host_3]:
        await _test_change_mm_via_action(obj=obj, adcm_client=context.client, httpx_client=context.httpx_client)

    await _test_mm_effects_on_mapping(context=context)


async def _test_direct_maintenance_mode_change(obj: Service | Component | Host, httpx_client: AsyncClient) -> None:
    mm = await obj.maintenance_mode

    remote_mm = await get_object_mm(obj=obj, httpx_client=httpx_client)
    assert remote_mm == "off" == mm.value

    await mm.on()
    remote_mm = await get_object_mm(obj=obj, httpx_client=httpx_client)
    assert remote_mm == "on" == mm.value

    await mm.off()
    remote_mm = await get_object_mm(obj=obj, httpx_client=httpx_client)
    assert remote_mm == "off" == mm.value


async def _test_indirect_mm_change(context: Context) -> None:
    # objects in mapping hierarchy
    host_1, host_2, component, service = context.host_1, context.host_2, context.first_component, context.service

    # turn on mm on host
    await (await host_1.maintenance_mode).on()

    await service.refresh()
    assert (await service.maintenance_mode).value == "off" == await get_object_mm(service, context.httpx_client)
    await component.refresh()
    assert (await component.maintenance_mode).value == "off" == await get_object_mm(component, context.httpx_client)

    # turn on mm on all hosts
    await (await host_2.maintenance_mode).on()

    await service.refresh()
    assert (await service.maintenance_mode).value == "on" == await get_object_mm(service, context.httpx_client)
    await component.refresh()
    assert (await component.maintenance_mode).value == "on" == await get_object_mm(component, context.httpx_client)

    await (await host_1.maintenance_mode).off()
    await (await host_2.maintenance_mode).off()

    # turn on mm on component
    await (await component.maintenance_mode).on()

    await host_1.refresh()
    assert (await host_1.maintenance_mode).value == "off" == await get_object_mm(host_1, context.httpx_client)
    await host_2.refresh()
    assert (await host_2.maintenance_mode).value == "off" == await get_object_mm(host_2, context.httpx_client)
    await service.refresh()
    assert (await service.maintenance_mode).value == "off" == await get_object_mm(service, context.httpx_client)

    await (await component.maintenance_mode).off()

    # turn on mm on all components
    all_components = await service.components.all()
    for component_object in all_components:
        await (await component_object.maintenance_mode).on()

    await host_1.refresh()
    assert (await host_1.maintenance_mode).value == "off" == await get_object_mm(host_1, context.httpx_client)
    await host_2.refresh()
    assert (await host_2.maintenance_mode).value == "off" == await get_object_mm(host_2, context.httpx_client)
    await service.refresh()
    assert (await service.maintenance_mode).value == "on" == await get_object_mm(service, context.httpx_client)

    for component_object in all_components:
        await (await component_object.maintenance_mode).off()

    # turn on mm on service
    await (await service.maintenance_mode).on()

    await host_1.refresh()
    assert (await host_1.maintenance_mode).value == "off" == await get_object_mm(host_1, context.httpx_client)
    await host_2.refresh()
    assert (await host_2.maintenance_mode).value == "off" == await get_object_mm(host_2, context.httpx_client)

    for component_obj in await service.components.all():
        assert (
            (await component_obj.maintenance_mode).value
            == "on"
            == await get_object_mm(component_obj, context.httpx_client)
        )

    await (await service.maintenance_mode).off()


async def _test_change_mm_via_action(
    obj: Service | Component | Host, adcm_client: ADCMClient, httpx_client: AsyncClient
) -> None:
    if isinstance(obj, Host):
        turn_on_name = "adcm_host_turn_on_maintenance_mode"
        turn_off_name = "adcm_host_turn_off_maintenance_mode"
    else:
        turn_on_name = "adcm_turn_on_maintenance_mode"
        turn_off_name = "adcm_turn_off_maintenance_mode"

    # check initial mm state
    mm = await obj.maintenance_mode
    assert mm.value == "off" == await get_object_mm(obj, httpx_client)

    # turn mm on via action
    await mm.on()
    assert mm.value == "changing"

    mm_task = await adcm_client.jobs.get(object=obj, name__eq=turn_on_name)
    await mm_task.wait(timeout=30, poll_interval=1)

    await obj.refresh()
    mm = await obj.maintenance_mode
    assert mm.value == "on" == await get_object_mm(obj, httpx_client)

    # turn mm off via action
    await mm.off()
    assert mm.value == "changing"

    mm_task = await adcm_client.jobs.get(object=obj, name__eq=turn_off_name)
    await mm_task.wait(timeout=30, poll_interval=1)

    await obj.refresh()
    mm = await obj.maintenance_mode
    assert mm.value == "off" == await get_object_mm(obj, httpx_client)


async def _test_mm_effects_on_mapping(context: Context) -> None:
    cluster, component, host_1, host_2 = (
        context.service.cluster,
        context.first_component,
        context.host_1,
        context.host_2,
    )
    mapping = await cluster.mapping

    # prepare: component, host_1 mapped to component and in mm, host_2 in cluster
    mapping.empty()
    await mapping.add(component=component, host=host_1)
    await mapping.save()

    await (await host_1.maintenance_mode).on()

    # test unmap host_1 in mm
    await cluster.refresh()
    mapping = await cluster.mapping
    await mapping.remove(component=component, host=host_1)
    await mapping.save()

    # test map host_2 not in mm
    await cluster.refresh()
    mapping = await cluster.mapping
    await mapping.add(component=component, host=host_2)
    await mapping.save()

    # prepare: component, host_1, host_2 in cluster, not mapped, host_1 in mm
    mapping.empty()
    await mapping.save()

    # test map host_1 in mm
    await cluster.refresh()
    mapping = await cluster.mapping
    await mapping.add(component=component, host=host_1)
    with pytest.raises(ConflictError, match="You can't save hc with hosts in maintenance mode"):
        await mapping.save()

    # test map host_2 not in mm
    await cluster.refresh()
    mapping = await cluster.mapping
    await mapping.add(component=component, host=host_2)
    await mapping.save()
