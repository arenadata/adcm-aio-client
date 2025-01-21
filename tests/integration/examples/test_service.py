import pytest

from adcm_aio_client import Filter
from adcm_aio_client.errors import ObjectDoesNotExistError
from adcm_aio_client.objects import Cluster, Component, Host, Service

pytestmark = [pytest.mark.asyncio]


async def test_service(example_cluster: Cluster, three_hosts: list[Host]) -> None:
    cluster = example_cluster
    host_1, host_2, host_3 = sorted(three_hosts, key=lambda host: host.name)

    # Add services "example_1" and "example_2" using Filter
    await cluster.services.add(filter_=Filter(attr="name", op="iin", value=["Example_1", "example_2"]))

    # Add service with all it's dependencies
    # Services "service_with_requires_my_service" and "my_service" will be added
    await cluster.services.add(
        filter_=Filter(attr="name", op="eq", value="service_with_requires_my_service"), with_dependencies=True
    )

    # Add service and accept license
    await cluster.services.add(filter_=Filter(attr="name", op="eq", value="with_license"), accept_license=True)

    # Get all cluster's services
    all_added_services: list[Service] = await cluster.services.all()  # noqa: F841

    # iterate through all cluster's services
    async for service in cluster.services.iter():  # noqa: B007
        pass

    # Remove services from cluster. Leave single "example_1" service
    for service in await cluster.services.filter(
        name__in=["example_2", "service_with_requires_my_service", "my_service", "with_license"]
    ):
        await service.delete()

    # Get non-existent (already removed) service "example_2"
    none_service: None = await cluster.services.get_or_none(name__eq="example_2")  # pyright: ignore[reportAssignmentType]  # noqa: F841

    # Get "example_1" service using case-insensitive filter by display_name
    service = await cluster.services.get(display_name__ieq="first example")  # actual display_name is "First Example"

    # Turn on service's maintenance mode
    service_mm = await service.maintenance_mode
    await service_mm.on()

    # Sync service's data with remote state
    await service.refresh()

    # Get all service's components
    all_components: list[Component] = await service.components.all()  # noqa: F841

    # Get specific component
    component = await service.components.get(name__eq="first")

    # Prepare data: add 3 hosts to cluster, map two of them to component
    await cluster.hosts.add(host=[host_1, host_2, host_3])
    mapping = await cluster.mapping
    await mapping.add(component=component, host=[host_1, host_2])
    await mapping.save()

    # Get all component's hosts
    component_hosts: list[Host] = await component.hosts.all()  # noqa: F841

    # Get specific host, mapped to this component
    host_2_from_component = await component.hosts.get(name__eq=host_2.name)  # noqa: F841

    # Trying to get host_3 from component, get error: host_3 is not mapped to component
    with pytest.raises(ObjectDoesNotExistError, match="No objects found with the given filter."):
        host_3_from_component = await component.hosts.get(name__eq=host_3.name)  # noqa: F841

    # Turn on maintenance mode on component
    await (await component.maintenance_mode).on()

    # Sync component's data with remote state
    await component.refresh()
