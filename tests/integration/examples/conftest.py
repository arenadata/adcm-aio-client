from collections.abc import Generator

import pytest_asyncio

from adcm_aio_client.objects import Bundle
from tests.integration.setup_environment import ADCMContainer

TIMEOUT = 10
RETRY_INTERVAL = 1
RETRY_ATTEMPTS = 1


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
