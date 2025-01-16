import pytest

from adcm_aio_client import ADCMSession, Credentials
from tests.integration.examples.conftest import RETRY_ATTEMPTS, RETRY_INTERVAL, TIMEOUT
from tests.integration.setup_environment import ADCMContainer

pytestmark = [pytest.mark.asyncio]


async def test_iteration_with_cluster(adcm: ADCMContainer) -> None:
    """
    Interaction with clusters: creating, deleting, getting a list of clusters using filtering,
    configuring cluster configuration, launching actions on the cluster and updating the cluster.
    """
    url = adcm.url
    credentials = Credentials(username="admin", password="admin")  # noqa: S106

    async with ADCMSession(
        url=url, credentials=credentials, timeout=TIMEOUT, retry_attempts=RETRY_ATTEMPTS, retry_interval=RETRY_INTERVAL
    ) as client:
        clusters = await client.clusters.all()
        assert len(clusters) == 0
