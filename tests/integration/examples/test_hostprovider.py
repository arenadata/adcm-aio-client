import pytest

from adcm_aio_client import ADCMSession, Credentials
from tests.integration.setup_environment import ADCMContainer

pytestmark = [pytest.mark.asyncio]


async def test_hostprovider(adcm: ADCMContainer) -> None:
    """
    Hostprovider (`client.hostproviders`) API Examples:
        - upload from path
        - retrieval with filtering / all hostproviders
        - hostprovider removal
        - creation of new hosts by hostprovider
        - retrieval a list of hosts by hostprovider with filtering / all hosts
        - upgrade of hostprovider
    """
    credentials = Credentials(username="admin", password="admin")  # noqa: S106
    async with ADCMSession(url=adcm.url, credentials=credentials) as client:
        # adding new hostprovider
        hostprovider = await client.hostproviders.create(
            bundle=await client.bundles.get(name__eq="simple_provider"), name="first provider"
        )
        second_hostprovider = await client.hostproviders.create(
            bundle=await client.bundles.get(name__eq="simple_provider"), name="second provider"
        )

        # getting full list of hostproviders
        providers = await client.hostproviders.all()
        assert len(providers) == 2

        # getting filtered list of hostproviders
        providers = await client.hostproviders.filter(name__contains="first")
        assert len(providers) == 1

        # deletion of hostprovider
        await second_hostprovider.delete()

        # adding new hosts by hostprovider
        for i in range(3):
            await client.hosts.create(hostprovider=hostprovider, name=f"host-{i}")

        # getting full list of hosts
        hosts = await hostprovider.hosts.all()
        assert len(hosts) == 3

        # getting filtered list of hosts:
        hosts = await hostprovider.hosts.filter(name__contains="host-2")
        assert len(hosts) == 1

        # running upgrade of hostprovider
        upgrade = await hostprovider.upgrades.get(name__eq="simple_provider")
        await upgrade.run()
