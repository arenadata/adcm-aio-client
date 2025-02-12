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

from collections.abc import AsyncGenerator, Generator
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin
import os
import random
import string
import tarfile

from httpx import AsyncClient
from testcontainers.core.network import Network
import pytest
import pytest_asyncio

from adcm_aio_client import ADCMSession, Credentials
from adcm_aio_client.client import ADCMClient
from adcm_aio_client.objects import Bundle
from tests.integration.bundle import pack_bundle
from tests.integration.setup_environment import (
    DB_USER,
    ADCMContainer,
    ADCMPostgresContainer,
    DatabaseInfo,
    postgres_image_name,
)

BUNDLES = Path(__file__).parent / "bundles"


################
# Infrastructure
################


@pytest.fixture(scope="session")
def network() -> Generator[Network, None, None]:
    with Network() as network:
        yield network


@pytest.fixture(scope="session")
def postgres(network: Network) -> Generator[ADCMPostgresContainer, None, None]:
    with ADCMPostgresContainer(image=postgres_image_name, network=network) as container:
        yield container


@pytest.fixture(scope="session")
def ssl_certs_dir(tmp_path_factory: pytest.TempdirFactory) -> Path:
    cert_dir = Path(tmp_path_factory.mktemp("cert"))

    exit_code = os.system(  # noqa: S605
        f"openssl req -x509 -newkey rsa:4096 -keyout {cert_dir}/key.pem -out {cert_dir}/cert.pem"
        ' -days 365 -subj "/C=RU/ST=Moscow/L=Moscow/O=Arenadata Software LLC/OU=Release/CN=ADCM"'
        f' -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" -nodes',
    )
    if exit_code != 0:
        message = "Certificate generation failed, see logs for more details"
        raise RuntimeError(message)

    return cert_dir


@pytest.fixture(scope="session")
def adcm_image(network: Network, postgres: ADCMPostgresContainer, ssl_certs_dir: Path) -> str:
    suffix = "".join(random.sample(string.ascii_letters, k=6)).lower()
    base_repo = "hub.adsw.io/adcm/adcm"
    base_tag = "develop"
    new_repo = "local/adcm"
    new_tag = f"{base_tag}-ssl-{suffix}"

    db = DatabaseInfo(name=f"adcm_{suffix}_migration", host=postgres.name)
    postgres.execute_statement(f"CREATE DATABASE {db.name} OWNER {DB_USER}")

    file = BytesIO()
    with tarfile.open(mode="w:gz", fileobj=file) as tar:
        tar.add(ssl_certs_dir, "")
    file.seek(0)
    adcm = ADCMContainer(image=f"{base_repo}:{base_tag}", network=network, db=db, migration_mode=True)

    with adcm:
        container = adcm.get_wrapped_container()
        container.put_archive("/adcm/data/conf/ssl", file.read())
        container.commit(repository=new_repo, tag=new_tag)

    return f"{new_repo}:{new_tag}"


@pytest.fixture(scope="function")
def adcm(network: Network, postgres: ADCMPostgresContainer, adcm_image: str) -> Generator[ADCMContainer, None, None]:
    suffix = "".join(random.sample(string.ascii_letters, k=6)).lower()
    db = DatabaseInfo(name=f"adcm_{suffix}", host=postgres.name)
    postgres.execute_statement(f"CREATE DATABASE {db.name} OWNER {DB_USER}")

    adcm = ADCMContainer(image=adcm_image, network=network, db=db)

    with adcm as container:
        yield container

    postgres.execute_statement(f"DROP DATABASE {db.name}")


#########
# Clients
#########


@pytest_asyncio.fixture(scope="function")
async def adcm_client(
    request: pytest.FixtureRequest, adcm: ADCMContainer, ssl_certs_dir: Path
) -> AsyncGenerator[ADCMClient, None]:
    credentials = Credentials(username="admin", password="admin")  # noqa: S106
    url = adcm.ssl_url
    extra_kwargs = getattr(request, "param", {})

    kwargs: dict = {
        "verify": str(ssl_certs_dir / "cert.pem"),
        "timeout": 10,
        "retry_interval": 1,
        "retry_attempts": 1,
    } | extra_kwargs
    async with ADCMSession(url=url, credentials=credentials, **kwargs) as client:
        yield client


@pytest_asyncio.fixture(scope="function")
async def second_adcm_client(
    request: pytest.FixtureRequest, adcm: ADCMContainer, ssl_certs_dir: Path
) -> AsyncGenerator[ADCMClient, None]:
    credentials = Credentials(username="admin", password="admin")  # noqa: S106
    url = adcm.ssl_url
    extra_kwargs = getattr(request, "param", {})

    kwargs: dict = {
        "verify": str(ssl_certs_dir / "cert.pem"),
        "timeout": 10,
        "retry_interval": 1,
        "retry_attempts": 1,
    } | extra_kwargs
    async with ADCMSession(url=url, credentials=credentials, **kwargs) as client:
        yield client


@pytest_asyncio.fixture()
async def httpx_client(adcm: ADCMContainer) -> AsyncGenerator[AsyncClient, None]:
    client = AsyncClient(base_url=urljoin(adcm.url, "api/v2/"))
    response = await client.post("login/", json={"username": "admin", "password": "admin"})
    client.headers["X-CSRFToken"] = response.cookies["csrftoken"]

    yield client

    await client.aclose()


#########
# Bundles
#########


@pytest_asyncio.fixture()
async def simple_cluster_bundle(adcm_client: ADCMClient, tmp_path: Path) -> Bundle:
    bundle_path = pack_bundle(from_dir=BUNDLES / "simple_cluster", to=tmp_path)
    return await adcm_client.bundles.create(source=bundle_path, accept_license=True)


@pytest_asyncio.fixture()
async def complex_cluster_bundle(adcm_client: ADCMClient, tmp_path: Path) -> Bundle:
    bundle_path = pack_bundle(from_dir=BUNDLES / "complex_cluster", to=tmp_path)
    return await adcm_client.bundles.create(source=bundle_path, accept_license=True)


@pytest_asyncio.fixture()
async def previous_complex_cluster_bundle(adcm_client: ADCMClient, tmp_path: Path) -> Bundle:
    bundle_path = pack_bundle(from_dir=BUNDLES / "complex_cluster_prev", to=tmp_path)
    return await adcm_client.bundles.create(source=bundle_path, accept_license=True)


@pytest_asyncio.fixture()
async def simple_hostprovider_bundle(adcm_client: ADCMClient, tmp_path: Path) -> Bundle:
    bundle_path = pack_bundle(from_dir=BUNDLES / "simple_hostprovider", to=tmp_path)
    return await adcm_client.bundles.create(source=bundle_path, accept_license=True)


@pytest_asyncio.fixture()
async def complex_hostprovider_bundle(adcm_client: ADCMClient, tmp_path: Path) -> Bundle:
    bundle_path = pack_bundle(from_dir=BUNDLES / "complex_provider", to=tmp_path)
    return await adcm_client.bundles.create(source=bundle_path, accept_license=True)
