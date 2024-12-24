from pathlib import Path
from typing import NamedTuple

import pytest
import pytest_asyncio

from adcm_aio_client.core.client import ADCMClient
from adcm_aio_client.core.filters import Filter
from adcm_aio_client.core.objects.cm import Bundle
from tests.integration.bundle import pack_bundle
from tests.integration.conftest import BUNDLES

pytestmark = [pytest.mark.asyncio]

@pytest_asyncio.fixture()
async def previous_cluster_bundle(adcm_client: ADCMClient, tmp_path: Path) -> Bundle:
    bundle_path = pack_bundle(from_dir=BUNDLES / "complex_cluster_prev", to=tmp_path)
    return await adcm_client.bundles.create(source=bundle_path, accept_license=True)

class Context(NamedTuple):
    client: ADCMClient
    old_bundle: Bundle
    new_bundle: Bundle

@pytest.fixture()
def context(adcm_client: ADCMClient, previous_cluster_bundle: Bundle,
                           complex_cluster_bundle: Bundle) -> Context:
    return Context(client=adcm_client,
                   old_bundle=previous_cluster_bundle,
                   new_bundle=complex_cluster_bundle)


async def test_upgrade_api(context: Context) -> None:
    await _test_simple_upgrade(context)
    await _test_upgrade_with_config(context)
    await _test_upgrade_with_mapping(context)

async def _test_simple_upgrade(context: Context) -> None:
    cluster = await context.client.clusters.create(context.old_bundle, "for simple")
    service_1, *_ = await cluster.services.add(Filter(attr="name", op="eq", value="example_1"))
    service_2, *_ = await cluster.services.add(Filter(attr="name", op="eq", value="example_2"))
    
    assert (await cluster.bundle).id == context.old_bundle.id

    upgrade = await cluster.upgrades.get(name__eq="Simple")
    assert upgrade.name == "Simple"
    assert upgrade.display_name == "I am very simple, you know?"

    bundle_from_upgrade = await upgrade.bundle
    assert bundle_from_upgrade.id == context.new_bundle.id
    assert bundle_from_upgrade.display_name == context.new_bundle.display_name

    result = await upgrade.run()
    assert result is None

    assert (await cluster.bundle).id == context.old_bundle.id
    await cluster.refresh()
    assert (await cluster.bundle).id == context.new_bundle.id

    upgrades = await cluster.upgrades.all()
    assert upgrades == []


async def _test_upgrade_with_config(context: Context) -> None:
    ...

async def _test_upgrade_with_mapping(context: Context) -> None:
    ...

