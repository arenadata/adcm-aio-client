from collections.abc import Collection
from copy import copy
from pathlib import Path
import random
import string

from httpx import AsyncClient
import pytest
import pytest_asyncio

from adcm_aio_client import Filter
from adcm_aio_client.client import ADCMClient
from adcm_aio_client.config._objects import ConfigHistoryNode, ObjectConfig
from adcm_aio_client.errors import ConflictError, MultipleObjectsReturnedError, ObjectDoesNotExistError
from adcm_aio_client.objects import Cluster, License, Service
from adcm_aio_client.objects._imports import Imports
from tests.integration.bundle import pack_bundle
from tests.integration.yaml_ext import create_yaml

pytestmark = [pytest.mark.asyncio]


def prepare_bundle_data() -> list[dict]:
    config = [
        {
            "name": "string_field",
            "type": "string",
            "default": "string_field value",
        }
    ]

    service = {
        "type": "service",
        "name": "Generated service",
        "version": 1.0,
        "config": config,
    }

    component = {"config": config}

    service_manual_add = copy(service)
    service_manual_add.update({"name": "Manual add", "license": "./service_license.txt"})

    fifty_services = []
    for i in range(50):
        service = copy(service)
        service.update({"name": f"Generated service {i + 1}"})
        fifty_services.append(service)

    service_with_component = copy(service)
    service_with_component["name"] = "Service with component"
    service_with_component["components"] = {"component_1": component}

    return [
        {
            "type": "cluster",
            "name": "Generated cluster",
            "version": 1,
        },
        *fifty_services,
        service_manual_add,
        service_with_component,
    ]


def assert_services_collection(services: Collection[Service], expected_amount: int) -> None:
    assert all(isinstance(cluster, Service) for cluster in services)
    assert len({service.id for service in services}) == expected_amount
    assert len({id(service) for service in services}) == expected_amount


@pytest_asyncio.fixture()
async def cluster_52(adcm_client: ADCMClient, tmp_path: Path) -> Cluster:
    """
    Cluster with 52 services, one not added
    """

    bundle_folder = tmp_path / "".join(random.sample(string.ascii_letters, k=6)).lower()
    config_yaml_path = bundle_folder / "config.yaml"
    create_yaml(data=prepare_bundle_data(), path=config_yaml_path)

    (bundle_folder / "service_license.txt").write_text("By using this test bundle, you agreeing to write tests well\n")

    bundle_path = pack_bundle(from_dir=bundle_folder, to=tmp_path)
    bundle = await adcm_client.bundles.create(source=bundle_path)

    cluster = await adcm_client.clusters.create(bundle=bundle, name="Test cluster 52")
    await cluster.services.add(filter_=Filter(attr="name", op="icontains", value="service"))

    return cluster


async def test_service_api(cluster_52: Cluster, httpx_client: AsyncClient) -> None:
    cluster = cluster_52
    num_services = 51

    await _test_service_create_delete_api(name="Manual add", cluster=cluster, httpx_client=httpx_client)
    await _test_services_node(cluster=cluster, num_services=num_services)

    service = await cluster.services.get(name__eq="Service with component")
    service_from_component = (await service.components.get(name__eq="component_1")).service

    service_data = await _test_service_object_api(service=service, parent_cluster=cluster)
    from_component_data = await _test_service_object_api(service=service_from_component, parent_cluster=cluster)

    assert service_data == from_component_data


async def _test_service_create_delete_api(name: str, cluster: Cluster, httpx_client: AsyncClient) -> None:
    target_service_filter = Filter(attr="name", op="eq", value=name)

    with pytest.raises(ConflictError, match="LICENSE_ERROR"):
        await cluster.services.add(filter_=target_service_filter)

    service = await cluster.services.add(filter_=target_service_filter, accept_license=True)
    assert len(service) == 1
    service = service[0]

    service_url_part = f"clusters/{cluster.id}/services/{service.id}/"
    response = await httpx_client.get(service_url_part)

    assert response.status_code == 200
    service_data = response.json()

    assert service_data["id"] == service.id
    assert service_data["name"] == name

    await service.delete()
    response = await httpx_client.get(service_url_part)
    assert response.status_code == 404


async def _test_services_node(cluster: Cluster, num_services: int) -> None:
    no_objects_msg = "^No objects found with the given filter.$"
    multiple_objects_msg = "^More than one object found.$"

    # get
    assert isinstance(await cluster.services.get(name__eq="Generated service 30"), Service)

    with pytest.raises(ObjectDoesNotExistError, match=no_objects_msg):
        await cluster.services.get(name__eq="Non-existent service")

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await cluster.services.get(name__in=["Generated service 1", "Generated service 2"])

    # get_or_none
    assert isinstance(await cluster.services.get_or_none(name__eq="Generated service 50"), Service)

    assert await cluster.services.get_or_none(name__eq="Non-existent service") is None

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await cluster.services.get_or_none(name__in=["Generated service 1", "Generated service 2"])

    # all
    all_services = await cluster.services.all()
    assert_services_collection(services=all_services, expected_amount=num_services)

    # list
    page_size = 50
    assert page_size < num_services, "check page_size or number of services"

    first_page_services = await cluster.services.list()
    assert_services_collection(services=first_page_services, expected_amount=page_size)

    # iter
    iter_services = []
    async for service in cluster.services.iter():
        iter_services.append(service)
    assert_services_collection(services=iter_services, expected_amount=num_services)

    # filter
    name_filters_data = {
        ("name__eq", "Generated service 8"): 1,
        ("name__ieq", "GeNeRaTeD SeRvIcE 18"): 1,
        ("name__ne", "Generated service 50"): num_services - 1,
        ("name__ine", "GENERATED service 50"): num_services - 1,
        ("name__in", ("Generated service 50", "Generated service 49", "GENERATED SERVICE 48", "Not a service")): 2,
        ("name__iin", ("Generated service 50", "Generated service 49", "GENERATED SERVICE 48", "Not a service")): 3,
        ("name__exclude", ("Generated service 1", "Generated service 2", "Not a service")): num_services - 2,
        ("name__iexclude", ("GENERATED SERVICE 50", "Not a service")): num_services - 1,
        ("name__contains", "38"): 1,
        ("name__contains", "Service"): 1,
        ("name__icontains", "TeD sErV"): num_services - 1,
    }
    display_name_filters_data = {  # display_names are the same as names
        (f"display_{filter_[0]}", filter_[1]): expected for filter_, expected in name_filters_data.items()
    }

    filters_data = {
        **name_filters_data,
        **display_name_filters_data,
        ("status__eq", "up"): num_services,
        ("status__eq", "down"): 0,
        ("status__in", ("down", "some status")): 0,
        ("status__in", ("up", "some status")): num_services,
        ("status__ne", "down"): num_services,
        ("status__ne", "up"): 0,
        ("status__exclude", ("excluded_status", "down")): num_services,
        ("status__exclude", ("excluded_status", "up")): 0,
        ("status__exclude", ("up", "down")): 0,
    }
    for filter_, expected in filters_data.items():
        filter_value = {filter_[0]: filter_[1]}
        services = await cluster.services.filter(**filter_value)
        assert len(services) == expected, f"Filter: {filter_value}"


async def _test_service_object_api(service: Service, parent_cluster: Cluster) -> tuple:
    assert isinstance(service_id := service.id, int)
    assert isinstance(name := service.name, str)
    assert isinstance(display_name := service.display_name, str)
    assert isinstance(_cluster := service.cluster, Cluster)
    cluster_id = _cluster.id
    assert cluster_id == parent_cluster.id
    assert isinstance(await service.license, License)
    assert isinstance(await service.components.all(), list)
    assert isinstance(await service.get_status(), str)
    assert isinstance(await service.actions.all(), list)
    assert isinstance(await service.config, ObjectConfig)
    assert isinstance(service.config_history, ConfigHistoryNode)
    assert isinstance(await service.imports, Imports)
    assert isinstance(await service.config_host_groups.all(), list)
    assert isinstance(await service.action_host_groups.all(), list)
    assert (await service.maintenance_mode).value == "off"

    return service_id, name, display_name, cluster_id
