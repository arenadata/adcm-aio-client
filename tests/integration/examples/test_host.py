import pytest

from adcm_aio_client.client import ADCMClient
from adcm_aio_client.errors import ObjectDoesNotExistError
from adcm_aio_client.objects import Cluster, Host, HostProvider

pytestmark = [pytest.mark.asyncio]


async def test_host(admin_client: ADCMClient, example_cluster: Cluster, example_hostprovider: HostProvider) -> None:
    """
    Service (`client.hosts`) API Examples:
        - creating a host
        - retrieval with filtering / all hosts
        - iteration through all hosts
        - adding host to cluster
        - turning on maintenance mode
        - refreshing host's data
        - host removal
    """

    client = admin_client
    cluster = example_cluster
    hostprovider = example_hostprovider

    # Create new host
    host = await client.hosts.create(hostprovider=hostprovider, name="Example-host")

    # Get all hosts
    all_hosts: list[Host] = await client.hosts.all()  # noqa: F841

    # Iterate through all hosts
    async for host in client.hosts.iter():  # noqa: B007
        pass

    # Get all hosts of hostprovider
    hosts: list[Host] = await client.hosts.filter(hostprovider__eq=hostprovider)

    name_not_exists = "Non-existent-host"

    # Get host or `None` if no object is found
    none_host: None = await client.hosts.get_or_none(name__eq=name_not_exists)  # pyright: ignore[reportAssignmentType]  # noqa: F841

    # Get error trying to get non-existent host
    with pytest.raises(ObjectDoesNotExistError, match="No objects found with the given filter."):
        await client.hosts.get(name__eq=name_not_exists)

    # Get all hosts, which name contains `host`
    hosts: list[Host] = await client.hosts.filter(name__contains="host")  # noqa: F841

    # Add host to cluster with allowed maintenance mode
    await cluster.hosts.add(host=host)

    # Turn on host's maintenance mode
    host_mm = await host.maintenance_mode
    await host_mm.on()

    # Sync host data with remote state
    await host.refresh()

    # Delete host after removing it from cluster
    await cluster.hosts.remove(host=host)
    await host.delete()
