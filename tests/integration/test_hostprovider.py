from pathlib import Path

import pytest
import pytest_asyncio

from adcm_aio_client.core.actions import ActionsAccessor, UpgradeNode
from adcm_aio_client.core.client import ADCMClient
from adcm_aio_client.core.config import (
    ConfigHistoryNode,
    ObjectConfig,
)
from adcm_aio_client.core.errors import MultipleObjectsReturnedError, ObjectDoesNotExistError
from adcm_aio_client.core.objects.cm import Bundle, HostProvider
from tests.integration.bundle import pack_bundle
from tests.integration.conftest import BUNDLES

pytestmark = [pytest.mark.asyncio]


@pytest_asyncio.fixture()
async def hostprovider_bundle(adcm_client: ADCMClient, tmp_path: Path) -> Bundle:
    bundle_path = pack_bundle(from_dir=BUNDLES / "complex_provider", to=tmp_path)
    return await adcm_client.bundles.create(source=bundle_path)


async def test_hostprovider(adcm_client: ADCMClient, hostprovider_bundle: Bundle) -> None:
    await _test_hostprovider_properties(adcm_client, hostprovider_bundle)
    await _test_hostprovider_accessors(adcm_client, hostprovider_bundle)
    await _test_pagination(adcm_client, hostprovider_bundle)


async def _test_hostprovider_properties(adcm_client: ADCMClient, hostprovider_bundle: Bundle) -> None:
    hostprovider = await adcm_client.hostproviders.create(
        bundle=hostprovider_bundle, name="Hostprovider name", description="Hostprovider description"
    )
    assert hostprovider.display_name == "complex_provider"
    assert hostprovider.name == "Hostprovider name"
    assert hostprovider.description == "Hostprovider description"
    assert isinstance(hostprovider.actions, ActionsAccessor)
    assert isinstance(await hostprovider.config, ObjectConfig)
    assert isinstance(hostprovider.config_history, ConfigHistoryNode)
    assert isinstance(hostprovider.upgrades, UpgradeNode)
    hosts = await hostprovider.hosts.all()
    assert len(hosts) == 0


async def _test_hostprovider_accessors(adcm_client: ADCMClient, hostprovider_bundle: Bundle) -> None:
    for new_host_provider in ["hostprovider-1", "hostprovider-2", "hostprovider-3"]:
        await adcm_client.hostproviders.create(
            bundle=hostprovider_bundle, name=new_host_provider, description=new_host_provider
        )

    hostprovider = await adcm_client.hostproviders.get(name__eq="hostprovider-1")
    assert isinstance(hostprovider, HostProvider)
    assert hostprovider.name == "hostprovider-1"

    with pytest.raises(ObjectDoesNotExistError):
        await adcm_client.hostproviders.get(name__eq="fake_hostprovider")

    with pytest.raises(MultipleObjectsReturnedError):
        await adcm_client.hostproviders.get(name__icontains="pr")

    assert not await adcm_client.hostproviders.get_or_none(name__eq="fake_hostprovider")
    assert isinstance(await adcm_client.hostproviders.get_or_none(name__contains="hostprovider-1"), HostProvider)

    assert len(await adcm_client.hostproviders.all()) == len(await adcm_client.hostproviders.list()) == 4

    hostproviders_list = await adcm_client.hostproviders.list(query={"limit": 2, "offset": 1})
    assert isinstance(hostproviders_list, list)
    assert len(hostproviders_list) == 2

    hostproviders_list = await adcm_client.hostproviders.list(query={"offset": 4})
    assert isinstance(hostproviders_list, list)
    assert len(hostproviders_list) == 0

    async for hp in adcm_client.hostproviders.iter():
        assert isinstance(hp, HostProvider)
        assert "hostprovider" in hp.name.lower()

    assert len(await adcm_client.hostproviders.filter(bundle__eq=hostprovider_bundle)) == 4

    await hostprovider.delete()


async def _test_pagination(adcm_client: ADCMClient, bundle: Bundle) -> None:
    for i in range(55):
        await adcm_client.hostproviders.create(bundle=bundle, name=f"Hostprovider name {i}")

    hostproviders_list = await adcm_client.hostproviders.list()
    assert len(hostproviders_list) == 50

    hostproviders_list = await adcm_client.hostproviders.list(query={"offset": 55})
    assert len(hostproviders_list) == 3

    hostproviders_list = await adcm_client.hostproviders.list(query={"offset": 60})
    assert len(hostproviders_list) == 0

    hostproviders_list = await adcm_client.hostproviders.list(query={"limit": 10})
    assert len(hostproviders_list) == 10

    assert len(await adcm_client.hostproviders.all()) == 58
    assert len(await adcm_client.hostproviders.filter()) == 58
