from collections.abc import Generator

import pytest_asyncio

from adcm_aio_client import Credentials
from adcm_aio_client.objects import Bundle
from tests.integration.setup_environment import ADCMContainer

REQUEST_KWARGS: dict = {"timeout": 10, "retry_interval": 1, "retry_attempts": 1}
CREDENTIALS = Credentials(username="admin", password="admin")  # noqa: S106


@pytest_asyncio.fixture()
def adcm(
    adcm: ADCMContainer,
    simple_cluster_bundle: Bundle,
    complex_cluster_bundle: Bundle,
    previous_complex_cluster_bundle: Bundle,
    simple_hostprovider_bundle: Bundle,
) -> Generator[ADCMContainer, None, None]:
    _ = simple_cluster_bundle, complex_cluster_bundle, previous_complex_cluster_bundle, simple_hostprovider_bundle
    yield adcm
