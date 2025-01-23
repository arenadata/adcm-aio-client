# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from pathlib import Path
from typing import NamedTuple
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from adcm_aio_client.client import ADCMClient
from adcm_aio_client.errors import ObjectDoesNotExistError
from adcm_aio_client.objects import Bundle
from adcm_aio_client.requesters import BundleRetrieverInterface, DefaultRequester
from tests.integration.bundle import create_bundles_by_template, pack_bundle
from tests.integration.conftest import BUNDLES

pytestmark = [pytest.mark.asyncio]


class Context(NamedTuple):
    client: ADCMClient
    loaded_bundles: list[Bundle]
    tempdir: Path


class Expected(NamedTuple):
    name: str
    version: str
    license_state: str
    signature_status: str
    edition: str


@pytest_asyncio.fixture()
async def load_bundles(adcm_client: ADCMClient, tmp_path: Path) -> list[Bundle]:
    created_bundles = []
    for folder_path in BUNDLES.iterdir():
        folder_path = BUNDLES / folder_path
        if folder_path.is_dir():
            target_path = tmp_path / folder_path.name
            target_path.mkdir()
            bundle_path = pack_bundle(from_dir=folder_path, to=target_path)
            created_bundle = await adcm_client.bundles.create(source=bundle_path, accept_license=False)
            created_bundles.append(created_bundle)

    return created_bundles


@pytest.fixture()
def context(adcm_client: ADCMClient, load_bundles: list[Bundle], tmp_path: Path) -> Context:
    return Context(client=adcm_client, loaded_bundles=load_bundles, tempdir=tmp_path)


async def test_bundle(context: Context) -> None:
    await _test_bundle_create_delete(context)
    await _test_download_external_bundle_success()
    expected = Expected(
        name="cluster_with_license",
        version="2.0",
        license_state="accepted",
        signature_status="absent",
        edition="enterprise",
    )
    bundle = await context.client.bundles.get(name__eq=expected.name)
    await _test_bundle_properties(bundle, expected)
    await _test_bundle_accessors(context)
    await _test_pagination(context)


async def test_bundle_objects(
    adcm_client: ADCMClient, previous_complex_cluster_bundle: Bundle, complex_cluster_bundle: Bundle
) -> None:
    """Testing similarity, accessibility of attributes of bundle objects got from different sources"""

    cluster = await adcm_client.clusters.create(bundle=previous_complex_cluster_bundle, name="Upgradable cluster")
    cluster_from_new_bundle = await adcm_client.clusters.create(bundle=complex_cluster_bundle, name="New cluster")
    upgrade = await cluster.upgrades.get(name__eq="Simple")

    expected = Expected(
        name="Some Cluster", version="1", license_state="absent", signature_status="absent", edition="community"
    )
    bundle = complex_cluster_bundle
    await _test_bundle_properties(bundle, expected)
    bundle_from_upgrade = await upgrade.bundle
    await _test_bundle_properties(bundle_from_upgrade, expected)
    bundle_from_new_cluster = await cluster_from_new_bundle.bundle
    await _test_bundle_properties(bundle_from_new_cluster, expected)

    assert bundle.id == bundle_from_upgrade.id == bundle_from_new_cluster.id


async def _test_bundle_create_delete(context: Context) -> None:
    bundle = await context.client.bundles.get(name__eq="cluster_with_license")
    assert (await bundle.license).state == "unaccepted"
    await bundle.delete()

    bundle_path = pack_bundle(from_dir=BUNDLES / "cluster_with_license", to=context.tempdir)
    bundle = await context.client.bundles.create(source=bundle_path, accept_license=True)

    assert (await bundle.license).state == "accepted"


async def _test_bundle_accessors(context: Context) -> None:
    bundles_amount = len(context.loaded_bundles)

    bundle = await context.client.bundles.get(name__eq="cluster_with_license")
    assert isinstance(bundle, Bundle)
    assert bundle.name == "cluster_with_license"

    with pytest.raises(ObjectDoesNotExistError):
        await context.client.bundles.get(name__eq="fake_bundle")

    assert not await context.client.bundles.get_or_none(name__eq="fake_bundle")
    assert isinstance(await context.client.bundles.get_or_none(name__contains="cluster_with"), Bundle)

    bundles_list = await context.client.bundles.list()
    bundles_all = await context.client.bundles.all()
    assert isinstance(bundles_list, list)
    assert len(bundles_all) == len(bundles_list) == bundles_amount

    bundles_list = await context.client.bundles.list(query={"limit": 2, "offset": 1})
    assert isinstance(bundles_list, list)
    assert len(bundles_list) == 2

    bundles_list = await context.client.bundles.list(query={"offset": bundles_amount + 1})
    assert isinstance(bundles_list, list)
    assert len(bundles_list) == 0

    async for b in context.client.bundles.iter(name__icontains="cluster"):
        assert isinstance(b, Bundle)
        assert "cluster" in b.name.lower()

    assert len(await context.client.bundles.filter(name__icontains="cluster")) < bundles_amount


async def _test_bundle_properties(bundle: Bundle, expected: Expected) -> None:
    assert bundle.name == expected.name
    assert (await bundle.license).state == expected.license_state
    if expected.license_state != "absent":
        assert "LICENSE AGREEMENT" in (await bundle.license).text
    assert bundle.version == expected.version
    assert bundle.signature_status == expected.signature_status
    assert bundle.edition == expected.edition

    if expected.license_state != "absent":
        await (await bundle.license).accept()
        await bundle.refresh()
        assert (await bundle.license).state == expected.license_state


async def _test_download_external_bundle_success() -> None:
    mock_requester = AsyncMock(spec=DefaultRequester)
    mock_retriever = AsyncMock(spec=BundleRetrieverInterface)
    url = "http://example.com/bundle.tar.gz"

    mock_retriever.download_external_bundle = AsyncMock(return_value=b"bundle content")

    adcm_client = ADCMClient(requester=mock_requester, bundle_retriever=mock_retriever, adcm_version="1.0")

    await adcm_client.bundles.create(source=url, accept_license=False)

    mock_retriever.download_external_bundle.assert_awaited_once_with(url)


async def _test_pagination(context: Context) -> None:
    adcm_client = context.client
    extra_bundles = 55
    total_bundles = len(context.loaded_bundles) + extra_bundles

    await create_bundles_by_template(
        adcm_client,
        context.tempdir,
        BUNDLES / "simple_hostprovider",
        target_name="name",
        field_to_modify="simple_provider",
        new_value="new_value",
        number_of_bundles=extra_bundles,
    )

    bundles_list = await adcm_client.bundles.list()
    assert len(bundles_list) == 50

    bundles_list = await adcm_client.bundles.list(query={"offset": extra_bundles})
    assert len(bundles_list) == len(context.loaded_bundles)

    bundles_list = await adcm_client.bundles.list(query={"offset": total_bundles})
    assert len(bundles_list) == 0

    bundles_list = await adcm_client.bundles.list(query={"limit": 10})
    assert len(bundles_list) == 10

    assert len(await adcm_client.bundles.all()) == total_bundles
    assert len(await adcm_client.bundles.filter()) == total_bundles
