import logging

import pytest

from adcm_aio_client.core.client._client import ADCMClient

logging.basicConfig(level=logging.DEBUG)


@pytest.mark.asyncio
async def test_clusters_page(adcm_client: ADCMClient) -> None:
    clusters = await adcm_client.clusters.list()

    assert len(clusters) == 0
