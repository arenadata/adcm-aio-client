from pathlib import Path

import pytest

from adcm_aio_client import ADCMSession
from tests.integration.bundle import pack_bundle
from tests.integration.conftest import BUNDLES
from tests.integration.examples.conftest import CREDENTIALS, REQUEST_KWARGS
from tests.integration.setup_environment import ADCMContainer

pytestmark = [pytest.mark.asyncio]


@pytest.fixture()
def packed_bundle_with_license(tmp_path: Path) -> Path:
    # In regular use cases bundle already will be packed.
    # Here we do it in runtime for convenience purposes.
    return pack_bundle(from_dir=BUNDLES / "cluster_with_license", to=tmp_path)


async def test_bundle(adcm: ADCMContainer, packed_bundle_with_license: Path) -> None:
    """
    Bundle (`client.bundles`) API Examples:
        - upload from path
        - licence acceptance
        - bundle removal
        - retrieval with filtering / all bundles
    """
    async with ADCMSession(url=adcm.url, credentials=CREDENTIALS, **REQUEST_KWARGS) as client:
        all_bundles = await client.bundles.all()
        assert len(all_bundles) == 4

        # It's important for that `source` here is `pathlib.Path`,
        # otherwise it'll be treated as URL to upload bundle from.
        bundle = await client.bundles.create(source=packed_bundle_with_license, accept_license=False)

        # We could have passed `accept_license=True` instead of this.
        license_ = await bundle.license
        assert license_.state == "unaccepted"
        await license_.accept()

        same_bundle, *_ = await client.bundles.filter(name__eq="cluster_with_license")
        # Objects can be compared on equality,
        # but they aren't cached in any way, so it's different instances.
        assert bundle == same_bundle
        assert bundle is not same_bundle

        await same_bundle.delete()
