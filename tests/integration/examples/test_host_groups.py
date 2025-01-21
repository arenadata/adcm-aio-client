import asyncio

import pytest

from adcm_aio_client import ADCMSession, Filter
from adcm_aio_client.config import ParameterHG
from adcm_aio_client.objects import ActionHostGroup, ConfigHostGroup
from tests.integration.examples.conftest import CREDENTIALS, REQUEST_KWARGS
from tests.integration.setup_environment import ADCMContainer

pytestmark = [pytest.mark.asyncio]


async def test_config_host_group(adcm: ADCMContainer) -> None:
    async with ADCMSession(url=adcm.url, credentials=CREDENTIALS, **REQUEST_KWARGS) as client:
        bundle = await client.bundles.get(name__eq="simple_provider")
        hostprovider = await client.hostproviders.create(bundle=bundle, name="For Hosts")
        bundle = await client.bundles.get(name__icontains="Some cluste", version__eq="1")
        cluster = await client.clusters.create(bundle=bundle, name="For CHG")
        hosts = await asyncio.gather(
            *(
                client.hosts.create(hostprovider=hostprovider, name=f"host-for-group-{i}", cluster=cluster)
                for i in range(3)
            )
        )

        # Config host groups exist for Cluster, Service, Component and HostProvider.
        # Not all hosts can be added to groups, only "related":
        # refer to documentation for more info.
        group: ConfigHostGroup = await cluster.config_host_groups.create(name="Cluster Group", hosts=hosts)

        config = await group.config
        config["string_field", ParameterHG].set("chanded value")
        await config.save()
        assert (await group.config_history[-1]).id == config.id

        assert len(await group.hosts.all()) == 3
        one_of_hosts, *_ = await group.hosts.filter(name__in=["host-for-group-1", "host-for-group-0"])
        await group.hosts.remove(host=one_of_hosts)
        assert len(await group.hosts.all()) == 2
        assert len(await cluster.hosts.all()) == 3
        await group.hosts.add(host=Filter(attr="name", op="eq", value=one_of_hosts.name))

        # Since it's there's only one group, get without parameters will work,
        # yet avoid using it like that.
        group_ = await cluster.config_host_groups.get()
        assert group_.id == group.id

        await group.delete()
        assert len(await cluster.config_host_groups.all()) == 0


async def test_action_host_group(adcm: ADCMContainer) -> None:
    async with ADCMSession(url=adcm.url, credentials=CREDENTIALS, **REQUEST_KWARGS) as client:
        bundle = await client.bundles.get(name__eq="simple_provider")
        hostprovider = await client.hostproviders.create(bundle=bundle, name="For Hosts")
        bundle = await client.bundles.get(name__icontains="Some cluste", version__eq="1")
        cluster = await client.clusters.create(bundle=bundle, name="For AHG")
        hosts = await asyncio.gather(
            *(
                client.hosts.create(hostprovider=hostprovider, name=f"host-for-group-{i}", cluster=cluster)
                for i in range(3)
            )
        )

        group: ActionHostGroup = await cluster.action_host_groups.create(name="Cluster Group")
        await group.hosts.add(host=hosts)

        # Complex actions may have own `config` and `mapping` node as all actions do
        action = await group.actions.get(display_name__contains="I will survive")
        task = await action.run()
        await task.wait(timeout=50)

        assert len(await group.hosts.all()) == 3
        one_of_hosts, *_ = await group.hosts.filter(name__in=["host-for-group-1", "host-for-group-0"])
        await group.hosts.remove(host=one_of_hosts)
        assert len(await group.hosts.all()) == 2
        assert len(await cluster.hosts.all()) == 3
        await group.hosts.add(host=Filter(attr="name", op="eq", value=one_of_hosts.name))

        # Since it's there's only one group, get without parameters will work,
        # yet avoid using it like that.
        group_ = await cluster.action_host_groups.get()
        assert group_.id == group.id

        await group.delete()
        assert len(await cluster.action_host_groups.all()) == 0
