from adcm_aio_client import ADCMSession
from adcm_aio_client.core.mapping import ClusterMapping
from adcm_aio_client.core.objects.cm import Service, Cluster
from adcm_aio_client.core.types import Credentials
import asyncio
from pathlib import Path
from adcm_aio_client.core.filters import Filter

async def step1():
    credentials = Credentials(username="admin", password="admin")

    async with ADCMSession(url="http://127.0.0.1:8000", credentials=credentials) as client:
        cluster_bundle = await client.bundles.create(Path("/home/vasiliy/bundles/simple_bundles/simple_cluster_with_component.tar.gz"), accept_license=True)
        cluster = await client.clusters.create(bundle=cluster_bundle, name="simplest_cluster", description="Sample Cluster")
        provider_bundle = await client.bundles.create(Path("/home/vasiliy/bundles/simple_bundles/simple_provider.tar.gz"), accept_license=True)
        provider = await client.hostproviders.create(bundle=provider_bundle, name="simple_provider", description="Sample Provider")

        await client.hosts.create(hostprovider=provider, name="host-1", cluster=cluster)
        await client.hosts.create(hostprovider=provider, name="host-2", cluster=cluster)

        host1 = await client.hosts.get(name__eq="host-1")
        host2 = await client.hosts.get(name__eq="host-2")

        services = await cluster.services.add(filter_=Filter(attr="name", op="contains", value="service"))
        service1, service2 = services

        s1c1 = await service1.components.get(name__eq="component_1")
        s1c2 = await service1.components.get(name__eq="component_2")
        s2c1 = await service2.components.get(name__eq="component_1")
        s2c2 = await service2.components.get(name__eq="component_2")

        mapping: ClusterMapping = await cluster.mapping
        await mapping.add(component=[s1c1, s1c2], host=host1)
        await mapping.add(component=[s2c1, s2c2], host=host2)
        await mapping.save()


async def step2():
    credentials = Credentials(username="admin", password="admin")

    async with ADCMSession(url="http://127.0.0.1:8000", credentials=credentials) as client:
        host1 = await client.hosts.get(name__eq="h1")
        host_actions = await host1.actions.all()
        print(f"host actions: {host_actions}")
        for action in host_actions:
            print(f"host action: {action.name}")

        host_a = await host1.actions.get(name__eq="host_action_change")
        await host_a.run()


if __name__ == "__main__":
    # asyncio.run(step1())
    asyncio.run(step2())