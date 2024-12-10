from typing import AsyncGenerator, Generator

from testcontainers.core.network import Network
import pytest
import pytest_asyncio

from adcm_aio_client.core.client import build_client
from adcm_aio_client.core.client._client import ADCMClient
from adcm_aio_client.core.types import Credentials
from tests.integration.setup_environment import (
    ADCMContainer,
    ADCMPostgresContainer,
    adcm_image_name,
    db_name,
    db_password,
    db_user,
    postgres_image_name,
)


@pytest.fixture(scope="session")
def network() -> Generator[Network, None, None]:
    with Network() as network:
        yield network


@pytest.fixture(scope="function")
def postgres(network: Network) -> Generator[ADCMPostgresContainer, None, None]:
    with ADCMPostgresContainer(postgres_image_name, network) as container:
        container.setup_postgres(db_user, db_password, db_name)
        yield container


@pytest.fixture(scope="function")
def adcm(postgres: ADCMPostgresContainer) -> Generator[ADCMContainer, None, None]:
    with ADCMContainer(adcm_image_name, postgres.network, postgres.adcm_env_kwargs) as container:
        container.setup_container()
        yield container


@pytest_asyncio.fixture(scope="function")
async def adcm_client(adcm: ADCMContainer) -> AsyncGenerator[ADCMClient, None]:
    credentials = Credentials(username="admin", password="admin")  # noqa: S106
    yield await build_client(url=adcm.url, credentials=credentials, retries=3, retry_interval=15, timeout=30)
