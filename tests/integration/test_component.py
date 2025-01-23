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

from collections.abc import Collection
from pathlib import Path
import random
import string

import pytest
import pytest_asyncio

from adcm_aio_client import Filter
from adcm_aio_client.client import ADCMClient
from adcm_aio_client.config._objects import ConfigHistoryNode, ObjectConfig
from adcm_aio_client.errors import MultipleObjectsReturnedError, ObjectDoesNotExistError
from adcm_aio_client.objects import Cluster, Component, Service
from tests.integration.bundle import pack_bundle
from tests.integration.yaml_ext import create_yaml

pytestmark = [pytest.mark.asyncio]


def prepare_bundle_data() -> list[dict]:
    config = [{"name": "string_field", "type": "string", "default": "string_field value"}]

    component_data = {"config": config}
    fifty_components = {f"generated_component_{i + 1}": component_data for i in range(50)}
    special_component = {"special_component": component_data}

    return [
        {
            "type": "cluster",
            "name": "Generated cluster",
            "version": 1,
        },
        {
            "type": "service",
            "name": "Service",
            "version": 1.0,
            "config": config,
            "components": {**fifty_components, **special_component},
        },
    ]


def assert_components_collection(components: Collection[Component], expected_amount: int) -> None:
    assert all(isinstance(component, Component) for component in components)
    assert len({component.id for component in components}) == expected_amount
    assert len({id(component) for component in components}) == expected_amount


@pytest_asyncio.fixture()
async def service_51_components(adcm_client: ADCMClient, tmp_path: Path) -> Service:
    config_yaml_path = tmp_path / "".join(random.sample(string.ascii_letters, k=6)).lower() / "config.yaml"
    create_yaml(data=prepare_bundle_data(), path=config_yaml_path)

    bundle_path = pack_bundle(from_dir=config_yaml_path.parent, to=tmp_path)
    bundle = await adcm_client.bundles.create(source=bundle_path)
    cluster = await adcm_client.clusters.create(bundle=bundle, name="Test cluster 52")

    return (await cluster.services.add(filter_=Filter(attr="name", op="eq", value="Service")))[0]


async def test_component_api(service_51_components: Service) -> None:
    service = service_51_components
    num_components = 51

    await _test_component_node(service=service, num_components=num_components)

    component = await service.components.get(name__eq="special_component")
    await _test_component_object_api(component=component, parent_service=service)


async def _test_component_node(service: Service, num_components: int) -> None:
    no_objects_msg = "^No objects found with the given filter.$"
    multiple_objects_msg = "^More than one object found.$"

    # get
    assert isinstance(await service.components.get(name__eq="special_component"), Component)

    with pytest.raises(ObjectDoesNotExistError, match=no_objects_msg):
        await service.components.get(name__eq="some_component")

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await service.components.get(name__in=["generated_component_1", "generated_component_2"])

    # get_or_none
    assert isinstance(await service.components.get_or_none(name__eq="generated_component_30"), Component)

    assert await service.components.get_or_none(name__eq="some_component") is None

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await service.components.get_or_none(name__in=["generated_component_1", "generated_component_11"])

    # all
    all_components = await service.components.all()
    assert_components_collection(components=all_components, expected_amount=num_components)

    # list
    page_size = 50
    assert page_size < num_components, "check page_size or number of components"

    first_page_components = await service.components.list()
    assert_components_collection(components=first_page_components, expected_amount=page_size)

    # iter
    iter_components = []
    async for component in service.components.iter():
        iter_components.append(component)
    assert_components_collection(components=iter_components, expected_amount=num_components)

    # filter
    name_filters_data = {
        ("name__eq", "generated_component_8"): 1,
        ("name__ieq", "gEnErAtEd_CoMpOnEnT_18"): 1,
        ("name__ne", "generated_component_2"): num_components - 1,
        ("name__ine", "GENERATED_component_2"): num_components - 1,
        (
            "name__in",
            ("generated_component_20", "generated_component_21", "GENERATED_COMPONENT_22", "Not a component"),
        ): 2,
        (
            "name__iin",
            ("generated_component_20", "generated_component_21", "GENERATED_COMPONENT_22", "Not a component"),
        ): 3,
        ("name__exclude", ("generated_component_20", "generated_component_21", "Not a component")): num_components - 2,
        ("name__iexclude", ("GENERATED_COMPONENT_22", "Not a component")): num_components - 1,
        ("name__contains", "38"): 1,
        ("name__contains", "omponen"): num_components,
        ("name__icontains", "_coMPON"): num_components,
    }
    display_name_filters_data = {  # display_names are the same as names
        (f"display_{filter_[0]}", filter_[1]): expected for filter_, expected in name_filters_data.items()
    }

    filters_data = {
        **name_filters_data,
        **display_name_filters_data,
        ("status__eq", "up"): 0,
        ("status__eq", "down"): num_components,
        ("status__in", ("down", "some status")): num_components,
        ("status__in", ("up", "some status")): 0,
        ("status__ne", "down"): 0,
        ("status__ne", "up"): num_components,
        ("status__exclude", ("excluded_status", "down")): 0,
        ("status__exclude", ("excluded_status", "up")): num_components,
        ("status__exclude", ("up", "down")): 0,
    }
    for filter_, expected in filters_data.items():
        filter_value = {filter_[0]: filter_[1]}
        components = await service.components.filter(**filter_value)
        assert len(components) == expected, f"Filter: {filter_value}"


async def _test_component_object_api(component: Component, parent_service: Service) -> None:
    assert isinstance(component.id, int)
    assert isinstance(component.name, str)
    assert isinstance(component.display_name, str)
    assert isinstance(await component.constraint, list)
    assert isinstance(component.service, Service)
    assert isinstance(component.cluster, Cluster)
    assert component.service.id == parent_service.id
    assert component.cluster.id == parent_service.cluster.id
    assert isinstance(await component.hosts.all(), list)
    assert isinstance(await component.get_status(), str)
    assert isinstance(await component.actions.all(), list)
    assert isinstance(await component.config, ObjectConfig)
    assert isinstance(component.config_history, ConfigHistoryNode)
    assert isinstance(await component.config_host_groups.all(), list)
    assert isinstance(await component.action_host_groups.all(), list)
    assert (await component.maintenance_mode).value == "off"
