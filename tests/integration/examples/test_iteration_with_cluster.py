import pytest

from adcm_aio_client import ADCMSession, Credentials, Filter
from adcm_aio_client.config import Parameter
from tests.integration.examples.conftest import RETRY_ATTEMPTS, RETRY_INTERVAL, TIMEOUT
from tests.integration.setup_environment import ADCMContainer

pytestmark = [pytest.mark.asyncio]


async def test_iteration_with_cluster(adcm: ADCMContainer) -> None:
    """
    Interaction with clusters: creating, deleting, getting a list of clusters using filtering,
    configuring cluster configuration, launching actions on the cluster and updating the cluster.
    """
    url = adcm.url
    credentials = Credentials(username="admin", password="admin")  # noqa: S106

    async with ADCMSession(
        url=url, credentials=credentials, timeout=TIMEOUT, retry_attempts=RETRY_ATTEMPTS, retry_interval=RETRY_INTERVAL
    ) as client:
        clusters = await client.clusters.all()
        assert len(clusters) == 0


async def test_interaction_with_cluster(adcm: ADCMContainer) -> None:
    """
    Interaction with clusters: creating, deleting, getting a list of clusters using filtering,
    configuring cluster configuration, launching actions on the cluster and updating the cluster.
    """
    credentials = Credentials(username="admin", password="admin")  # noqa: S106
    async with ADCMSession(url=adcm.url, credentials=credentials) as client:
        simple_cluster = await client.clusters.create(
            bundle=await client.bundles.get(name__eq="Simple Cluster"), name="simple_cluster"
        )
        complex_cluster = await client.clusters.create(
            bundle=await client.bundles.get(name__eq="Some Cluster", version__eq="0.1"), name="complex_cluster"
        )

        # getting full list of clusters
        clusters = await client.clusters.all()
        assert len(clusters) == 2

        # getting filtered list of clusters
        clusters = await client.clusters.filter(name__contains="complex")
        assert len(clusters) == 1

        # deletion of cluster
        await simple_cluster.delete()

        # mapping change
        provider = await client.hostproviders.create(
            bundle=await client.bundles.get(name__eq="simple_provider"), name="simple_provider"
        )
        host_1 = await client.hosts.create(hostprovider=provider, name="host-1", cluster=complex_cluster)
        host_2 = await client.hosts.create(hostprovider=provider, name="host-2", cluster=complex_cluster)

        service, *_ = await complex_cluster.services.add(Filter(attr="name", op="eq", value="example_1"))
        service_component = await service.components.get(name__eq="first")

        cluster_mapping = await complex_cluster.mapping

        await cluster_mapping.add(component=service_component, host=(host_1, host_2))
        await cluster_mapping.save()

        # config change. The option is also available to Service, Component, Hostprovider, Host, Action
        config = await complex_cluster.config
        config["string_field_prev", Parameter].set("new string value to save")
        await config.save()

        # running of upgrade
        upgrade = await complex_cluster.upgrades.get(name__eq="Simple")
        await upgrade.run()

        # running of action. The option is also available to Service, Component, Hostprovider, Host
        action = await complex_cluster.actions.get(name__eq="success")
        await action.run()
