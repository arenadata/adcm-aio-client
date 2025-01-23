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

from pathlib import Path
from typing import NamedTuple
import asyncio

import pytest
import pytest_asyncio

from adcm_aio_client import Filter
from adcm_aio_client.client import ADCMClient
from adcm_aio_client.objects import Cluster, Service
from adcm_aio_client.objects._imports import Imports
from tests.integration.bundle import create_bundles_by_template, pack_bundle
from tests.integration.conftest import BUNDLES

pytestmark = [pytest.mark.asyncio]


class Context(NamedTuple):
    client: ADCMClient
    cluster_exports: list[Cluster]
    service_exports: list[Service]
    cluster_import: Cluster
    tempdir: Path


@pytest_asyncio.fixture()
async def load_cluster_exports(adcm_client: ADCMClient, tmp_path: Path) -> list[Cluster]:
    clusters = []
    bundles = await create_bundles_by_template(
        adcm_client,
        tmp_path,
        BUNDLES / "cluster_export",
        target_name="name",
        field_to_modify="cluster_export",
        new_value="cluster_export",
        number_of_bundles=10,
    )
    for i, bundle in enumerate(bundles):
        cluster = await adcm_client.clusters.create(
            bundle=bundle, name=f"cluster_export_{i}", description=f"Cluster export description {i}"
        )
        await cluster.services.add(filter_=Filter(attr="name", op="contains", value="export"))
        clusters.append(cluster)

    return clusters


@pytest_asyncio.fixture()
async def cluster_import(adcm_client: ADCMClient, tmp_path: Path) -> Cluster:
    import_bundle_path = pack_bundle(from_dir=BUNDLES / "cluster_import", to=tmp_path)
    import_bundle = await adcm_client.bundles.create(source=import_bundle_path)
    import_cluster = await adcm_client.clusters.create(
        bundle=import_bundle, name="Cluster import", description="Cluster import description"
    )
    await import_cluster.services.add(filter_=Filter(attr="name", op="contains", value="import"))

    return import_cluster


@pytest_asyncio.fixture()
async def context(
    adcm_client: ADCMClient, load_cluster_exports: list[Cluster], cluster_import: Cluster, tmp_path: Path
) -> Context:
    services_by_cluster = await asyncio.gather(*[cluster.services.all() for cluster in load_cluster_exports])
    services_exports = [service for sublist in services_by_cluster for service in sublist]

    return Context(
        client=adcm_client,
        cluster_exports=load_cluster_exports,
        cluster_import=cluster_import,
        tempdir=tmp_path,
        service_exports=services_exports,
    )


async def test_cluster_import(context: Context) -> None:
    cluster_import = context.cluster_import
    cluster_exports = context.cluster_exports
    imports = await cluster_import.imports

    await _test_imports(imports, cluster_exports)


async def test_service_import(context: Context) -> None:
    cluster_import = context.cluster_import
    cluster_exports = context.cluster_exports
    imports = await (await cluster_import.services.get(name__eq="service_import_0")).imports

    export_services = await cluster_exports[0].services.all()

    await _test_imports(imports, export_services)


async def _test_imports(imports: Imports, exports: list[Cluster] | list[Service]) -> None:
    assert len(await imports._get_source_binds()) == 0

    await imports.add([])
    assert len(await imports._get_source_binds()) == 0

    await imports.add(exports[:5])
    assert len(binds := await imports._get_source_binds()) == 5
    assert sorted([i[0] for i in binds]) == list(range(1, 6))

    await imports.add(exports)
    assert len(binds := await imports._get_source_binds()) == 10
    assert sorted([i[0] for i in binds]) == list(range(1, 11))

    await imports.remove([])
    assert len(binds := await imports._get_source_binds()) == 10
    assert sorted([i[0] for i in binds]) == list(range(1, 11))

    await imports.remove([exports[-1]])
    assert len(binds := await imports._get_source_binds()) == 9
    assert sorted([i[0] for i in binds]) == list(range(1, 10))

    await imports.remove(exports)
    assert len(await imports._get_source_binds()) == 0

    await imports.set(exports[5::])
    assert len(binds := await imports._get_source_binds()) == 5
    assert sorted([i[0] for i in binds]) == list(range(6, 11))

    await imports.set(exports[:5])
    assert len(binds := await imports._get_source_binds()) == 5
    assert sorted([i[0] for i in binds]) == list(range(1, 6))

    await imports.set([])
    assert len(await imports._get_source_binds()) == 0
