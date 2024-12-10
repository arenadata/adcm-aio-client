from pathlib import Path
from typing import AsyncGenerator, Generator
import random
import string

from testcontainers.core.network import Network
import pytest
import pytest_asyncio

from adcm_aio_client.core.client import ADCMClient, build_client
from adcm_aio_client.core.types import Credentials
from tests.integration.setup_environment import (
    DB_USER,
    ADCMContainer,
    ADCMPostgresContainer,
    DatabaseInfo,
    adcm_image_name,
    postgres_image_name,
)

BUNDLES = Path(__file__).parent / "bundles"


@pytest.fixture(scope="session")
def network() -> Generator[Network, None, None]:
    with Network() as network:
        yield network


@pytest.fixture(scope="session")
def postgres(network: Network) -> Generator[ADCMPostgresContainer, None, None]:
    with ADCMPostgresContainer(image=postgres_image_name, network=network) as container:
        yield container


@pytest.fixture(scope="function")
def adcm(network: Network, postgres: ADCMPostgresContainer) -> Generator[ADCMContainer, None, None]:
    suffix = "".join(random.sample(string.ascii_letters, k=6)).lower()
    db = DatabaseInfo(name=f"adcm_{suffix}", host=postgres.name)
    postgres.execute_statement(f"CREATE DATABASE {db.name} OWNER {DB_USER}")

    with ADCMContainer(image=adcm_image_name, network=network, db=db) as container:
        yield container

    postgres.execute_statement(f"DROP DATABASE {db.name}")


@pytest_asyncio.fixture(scope="function")
async def adcm_client(adcm: ADCMContainer) -> AsyncGenerator[ADCMClient, None]:
    credentials = Credentials(username="admin", password="admin")  # noqa: S106
    yield await build_client(url=adcm.url, credentials=credentials, retries=1, retry_interval=1, timeout=10)
