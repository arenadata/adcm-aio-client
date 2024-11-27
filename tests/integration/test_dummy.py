import logging

import pytest

from adcm_aio_client.core.client import ADCMClient

logging.basicConfig(level=logging.DEBUG)


@pytest.mark.asyncio
@pytest.mark.skip(reason="the docker hub is unavailable currently")
async def test_clusters_page(adcm_client: ADCMClient) -> None:
    clusters = await adcm_client.clusters.list()

    assert len(clusters) == 0
