from typing import NamedTuple

from httpx import AsyncClient
import pytest
import pytest_asyncio

from adcm_aio_client.core.client import ADCMClient
from adcm_aio_client.core.filters import Filter
from adcm_aio_client.core.objects.cm import Bundle, Component, Host, Service

pytestmark = [pytest.mark.asyncio]


class Context(NamedTuple):
    client: ADCMClient
    httpx_client: AsyncClient
    service: Service
    first_component: Component
    second_component: Component
    host_1: Host
    host_2: Host


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

    return Context(
        client=adcm_client,
        httpx_client=httpx_client,
        service=service,
        first_component=first_component,
        second_component=second_component,
        host_1=host_1,
        host_2=host_2,
    )


async def test_maintenance_mode(context: Context) -> None:
    for obj in {context.service, context.second_component, context.host_2}:
        await _test_direct_maintenance_mode_change(obj=obj, httpx_client=context.httpx_client)

    await _test_indirect_mm_change(context=context)


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


async def _test_change_mm_via_action(context: Context) -> None:
    pass
