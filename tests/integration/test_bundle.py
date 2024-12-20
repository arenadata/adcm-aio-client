from pathlib import Path
from unittest.mock import AsyncMock
import os

import pytest
import pytest_asyncio

from adcm_aio_client.core.client import ADCMClient
from adcm_aio_client.core.errors import ObjectDoesNotExistError
from adcm_aio_client.core.objects.cm import Bundle
from adcm_aio_client.core.requesters import BundleRetrieverInterface, DefaultRequester
from tests.integration.bundle import create_bundles_by_template, pack_bundle
from tests.integration.conftest import BUNDLES

pytestmark = [pytest.mark.asyncio]


@pytest_asyncio.fixture()
async def load_bundles(adcm_client: ADCMClient, tmp_path: Path) -> list[Bundle]:
    created_bundles = []
    for folder_path in BUNDLES.iterdir():
        folder_path = BUNDLES / folder_path
        if folder_path.is_dir():
            (tmp_path / folder_path.name).mkdir()
            bundle_path = pack_bundle(from_dir=folder_path, to=(tmp_path / folder_path))
            created_bundle = await adcm_client.bundles.create(source=bundle_path, accept_license=False)
            created_bundles.append(created_bundle)

    return created_bundles


async def test_bundle(adcm_client: ADCMClient, load_bundles: list[Bundle], tmp_path: Path) -> None:  # noqa: ARG001
    await _test_bundle_create_delete(adcm_client, tmp_path)
    await _test_bundle_properties(adcm_client)
    await _test_bundle_accessors(adcm_client)
    await _test_pagination(adcm_client, tmp_path)


async def _test_bundle_create_delete(adcm_client: ADCMClient, tmp_path: Path) -> None:
    bundle = await adcm_client.bundles.get(name__eq="cluster_with_license")
    assert bundle.license.state == "unaccepted"
    await bundle.delete()

    bundle_path = pack_bundle(from_dir=BUNDLES / "cluster_with_license", to=tmp_path)
    bundle = await adcm_client.bundles.create(source=bundle_path, accept_license=True)

    assert bundle.license.state == "accepted"

    await _test_download_external_bundle_success()


async def _test_bundle_accessors(adcm_client: ADCMClient) -> None:
    bundle = await adcm_client.bundles.get(name__eq="cluster_with_license")
    assert isinstance(bundle, Bundle)
    assert bundle.name == "cluster_with_license"

    with pytest.raises(ObjectDoesNotExistError):
        await adcm_client.bundles.get(name__eq="fake_bundle")

    assert not await adcm_client.bundles.get_or_none(name__eq="fake_bundle")
    assert isinstance(await adcm_client.bundles.get_or_none(name__contains="cluster_with"), Bundle)

    bundles_list = await adcm_client.bundles.list()
    bundles_all = await adcm_client.bundles.all()
    assert isinstance(bundles_list, list)
    assert len(bundles_all) == len(bundles_list) == len(os.listdir(BUNDLES))

    bundles_list = await adcm_client.bundles.list(query={"limit": 2, "offset": 1})
    assert isinstance(bundles_list, list)
    assert len(bundles_list) == 2

    bundles_list = await adcm_client.bundles.list(query={"offset": len(os.listdir(BUNDLES)) + 1})
    assert isinstance(bundles_list, list)
    assert len(bundles_list) == 0

    async for b in adcm_client.bundles.iter(name__icontains="cluster"):
        assert isinstance(b, Bundle)
        assert "cluster" in b.name.lower()

    assert len(await adcm_client.bundles.filter(name__icontains="cluster")) < len(os.listdir(BUNDLES))


async def _test_bundle_properties(adcm_client: ADCMClient) -> None:
    bundle = await adcm_client.bundles.get(name__eq="cluster_with_license")
    assert bundle.name == "cluster_with_license"
    assert bundle.license.state == "accepted"
    assert "LICENSE AGREEMENT" in bundle.license.text
    assert bundle.version == "2.0"
    assert bundle.signature_status == "absent"
    assert bundle.edition == "enterprise"

    await bundle.license.accept()
    await bundle.refresh()
    assert bundle.license.state == "accepted"


async def _test_download_external_bundle_success() -> None:
    mock_requester = AsyncMock(spec=DefaultRequester)
    mock_retriever = AsyncMock(spec=BundleRetrieverInterface)
    url = "http://example.com/bundle.tar.gz"

    mock_retriever.download_external_bundle = AsyncMock(return_value=b"bundle content")

    adcm_client = ADCMClient(requester=mock_requester, bundle_retriever=mock_retriever, adcm_version="1.0")

    await adcm_client.bundles.create(source=url, accept_license=False)

    mock_retriever.download_external_bundle.assert_awaited_once_with(url)


async def _test_pagination(adcm_client: ADCMClient, tmp_path: Path) -> None:
    await create_bundles_by_template(
        adcm_client,
        tmp_path,
        BUNDLES / "simple_hostprovider",
        target_name="name",
        field_to_modify="simple_provider",
        new_value="new_value",
        number_of_bundles=55,
    )
    bundles_list = await adcm_client.bundles.list()
    assert len(bundles_list) == 50

    bundles_list = await adcm_client.bundles.list(query={"offset": 55})
    assert len(bundles_list) == 5

    bundles_list = await adcm_client.bundles.list(query={"offset": 60})
    assert len(bundles_list) == 0

    bundles_list = await adcm_client.bundles.list(query={"limit": 10})
    assert len(bundles_list) == 10

    assert len(await adcm_client.bundles.all()) == 60
    assert len(await adcm_client.bundles.filter()) == 60
