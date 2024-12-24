from pathlib import Path
from typing import AsyncGenerator, Generator
from urllib.parse import urljoin
import random
import string

from httpx import AsyncClient
from testcontainers.core.network import Network
import pytest
import pytest_asyncio

from adcm_aio_client._session import ADCMSession
from adcm_aio_client.core.client import ADCMClient
from adcm_aio_client.core.objects.cm import Bundle
from adcm_aio_client.core.types import Credentials
from tests.integration.bundle import pack_bundle
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
async def adcm_client(request: pytest.FixtureRequest, adcm: ADCMContainer) -> AsyncGenerator[ADCMClient, None]:
    credentials = Credentials(username="admin", password="admin")  # noqa: S106
    url = adcm.url
    extra_kwargs = getattr(request, "param", {})
    kwargs: dict = {"timeout": 10, "retry_interval": 1, "retry_attempts": 1} | extra_kwargs
    async with ADCMSession(url=url, credentials=credentials, **kwargs) as client:
        yield client


@pytest_asyncio.fixture()
async def complex_cluster_bundle(adcm_client: ADCMClient, tmp_path: Path) -> Bundle:
    bundle_path = pack_bundle(from_dir=BUNDLES / "complex_cluster", to=tmp_path)
    return await adcm_client.bundles.create(source=bundle_path, accept_license=True)


@pytest_asyncio.fixture()
async def simple_hostprovider_bundle(adcm_client: ADCMClient, tmp_path: Path) -> Bundle:
    bundle_path = pack_bundle(from_dir=BUNDLES / "simple_hostprovider", to=tmp_path)
    return await adcm_client.bundles.create(source=bundle_path, accept_license=True)

@pytest_asyncio.fixture()
async def httpx_client(adcm: ADCMContainer) -> AsyncGenerator[AsyncClient, None]:
    client = AsyncClient(base_url=urljoin(adcm.url, "api/v2/"))
    response = await client.post("login/", json={"username": "admin", "password": "admin"})
    client.headers["X-CSRFToken"] = response.cookies["csrftoken"]

    yield client

    await client.aclose()
