from collections.abc import Iterable
from functools import reduce
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from adcm_aio_client.core.client import ADCMClient
from adcm_aio_client.core.config import ActivatableParameterGroup, Parameter, ParameterGroup
from adcm_aio_client.core.config._objects import ActivatableParameterGroupHG, HostGroupConfig, ObjectConfig, ParameterHG
from adcm_aio_client.core.config.refresh import apply_local_changes, apply_remote_changes
from adcm_aio_client.core.errors import ConfigNoParameterError
from adcm_aio_client.core.filters import Filter
from adcm_aio_client.core.objects.cm import Bundle, Cluster, Service
from tests.integration.bundle import pack_bundle
from tests.integration.conftest import BUNDLES

pytestmark = [pytest.mark.asyncio]


def get_field_value(*names: str, configs: Iterable[ObjectConfig | HostGroupConfig]) -> tuple[Any, ...]:
    return tuple(
        reduce(lambda x, y: x[y], names, config).value  # type: ignore
        for config in configs
    )


@pytest_asyncio.fixture()
async def cluster_bundle(adcm_client: ADCMClient, tmp_path: Path) -> Bundle:
    bundle_path = pack_bundle(from_dir=BUNDLES / "complex_cluster", to=tmp_path)
    return await adcm_client.bundles.create(source=bundle_path, accept_license=True)


@pytest_asyncio.fixture()
async def cluster(adcm_client: ADCMClient, cluster_bundle: Bundle) -> Cluster:
    cluster = await adcm_client.clusters.create(bundle=cluster_bundle, name="Awesome Cluster")
    await cluster.services.add(filter_=Filter(attr="name", op="eq", value="complex_config"))
    return cluster


async def get_service_with_config(cluster: Cluster) -> Service:
    return await cluster.services.get(name__eq="complex_config")


async def test_invisible_fields(cluster: Cluster) -> None:
    expected_error = ConfigNoParameterError

    service = await get_service_with_config(cluster)
    config = await service.config

    # invisible fields can't be found via `__getitem__` interface

    with pytest.raises(expected_error):
        config["cant_find"]

    group = config["A lot of text", ParameterGroup]
    with pytest.raises(expected_error):
        group["cantCme"]

    # non initialized structure-based group
    structure_group = group["sag", ParameterGroup]
    inner_group = structure_group["nested", ParameterGroup]
    with pytest.raises(expected_error):
        inner_group["tech"]

    # they aren't displayed in difference

    # this change uses "internal" implementation
    # and isn't supposed to be used in production code
    data = config.data._values
    data["very_important_flag"] = 2
    data["cant_find"] = "changed value"
    data["a_lot_of_text"]["cant_find"] = "also changed"

    await config.save()

    first_config = await service.config_history[0]
    second_config = await service.config_history[-1]

    diff = first_config.difference(second_config)
    assert len(diff._values) == 1
    assert ("very_important_flag",) in diff._values
    assert first_config.data._values["cant_find"] != second_config.data._values["cant_find"]


async def test_structure_groups(cluster: Cluster) -> None:
    service = await get_service_with_config(cluster)
    config = await service.config
    group = config["A lot of text"]
    assert isinstance(group, ParameterGroup)
    group_like = group["Group-like structure"]
    # structure with "dict" root is a group
    assert isinstance(group_like, ParameterGroup)
    assert isinstance(group_like["quantity"], Parameter)
    nested_group = group_like["nested"]
    assert isinstance(nested_group, ParameterGroup)
    nested_group["attr", Parameter].set("something")
    nested_group["op", Parameter].set("good")


async def test_config(cluster: Cluster) -> None:
    # save two configs for later refresh usage
    service = await get_service_with_config(cluster)
    config_1 = await service.config_history.current()
    config_2 = await service.config_history.current()

    # change and save

    config = await service.config

    required_value = 100
    codes_value = [{"country": "Unknown", "code": 32}]
    multiline_value = "A lot of text\nOn multiple lines\n\tAnd it's perfectly fine\n"
    secret_map_value = {"pass1": "verysecret", "pass2": "evenmoresecret"}

    field = config["Set me"]
    assert isinstance(field, Parameter)
    assert field.value is None
    field.set(required_value)
    assert field.value == required_value
    assert field.value == config["very_important_flag", Parameter].value

    field = config["country_codes"]
    # structure with "list" root is a parameter
    assert isinstance(field, Parameter)
    assert isinstance(field.value, list)
    assert all(isinstance(e, dict) for e in field.value)
    field.set(codes_value)

    group = config["A lot of text"]
    assert isinstance(group, ParameterGroup)

    field = group["big_text"]
    assert isinstance(field, Parameter)
    assert field.value is None
    field.set(multiline_value)
    assert field.value == multiline_value

    field = config["from_doc", ParameterGroup]["Map Secrets"]
    assert isinstance(field, Parameter)
    assert field.value is None
    field.set(secret_map_value)

    config["agroup", ActivatableParameterGroup].activate()

    pre_save_id = config.id

    await config.save()

    assert config.id != pre_save_id
    assert config_1.id == pre_save_id
    assert config_2.id == pre_save_id

    # check values are updated, so values are encrypted coming from server
    field = config["from_doc", ParameterGroup]["Map Secrets"]
    assert field.value.keys() == secret_map_value.keys()  # type: ignore
    assert field.value.values() != secret_map_value.values()  # type: ignore

    # refresh

    non_conflicting_value_1 = 200
    non_conflicting_value_2 = "megapass"
    conflict_value_1 = "very fun\n"
    conflict_value_2 = 43.2

    for config_ in (config_1, config_2):
        config_["Complexity Level", Parameter].set(non_conflicting_value_1)
        group_ = config_["a_lot_of_text", ParameterGroup]
        group_["pass", Parameter].set(non_conflicting_value_2)
        group_["big_text", Parameter].set(conflict_value_1)
        config_["Set me", Parameter].set(conflict_value_2)

    await config_1.refresh(strategy=apply_local_changes)

    config_ = config_1
    assert config_.id == config.id
    assert config_["Complexity Level", Parameter].value == non_conflicting_value_1
    assert config_["Set me", Parameter].value == conflict_value_2
    group_ = config_["a_lot_of_text", ParameterGroup]
    assert group_["pass", Parameter].value == non_conflicting_value_2
    assert group_["big_text", Parameter].value == conflict_value_1
    secret_map = config_["from_doc", ParameterGroup]["Map Secrets", Parameter]
    assert isinstance(secret_map.value, dict)
    assert secret_map.value.keys() == secret_map_value.keys()
    assert config_["country_codes", Parameter].value == codes_value

    await config_2.refresh(strategy=apply_remote_changes)

    config_ = config_2
    assert config_.id == config.id
    assert config_.id == config.id
    assert config_["Complexity Level", Parameter].value == non_conflicting_value_1
    assert config_["Set me", Parameter].value == required_value
    group_ = config_["a_lot_of_text", ParameterGroup]
    assert group_["pass", Parameter].value == non_conflicting_value_2
    assert group_["big_text", Parameter].value == multiline_value
    secret_map = config_["from_doc", ParameterGroup]["Map Secrets", Parameter]
    assert isinstance(secret_map.value, dict)
    assert secret_map.value.keys() == secret_map_value.keys()
    assert config_["country_codes", Parameter].value == codes_value

    # history

    config_1["agroup", ActivatableParameterGroup].deactivate()

    await config_1.save()

    assert config_1.id != config.id

    latest_config = await service.config_history[-1]
    earliest_config = await service.config_history[0]

    assert latest_config.id == config_1.id
    assert earliest_config.id == pre_save_id

    diff = latest_config.difference(earliest_config)
    # group was activated, then deactivated, so returned to initial state
    # => no diff
    assert len(diff._attributes) == 0
    # field values changed from earliest to latest
    assert len(diff._values) == 6


async def test_host_group_config(cluster: Cluster) -> None:
    service = await get_service_with_config(cluster)
    group_1 = await service.config_host_groups.create("group-1")
    group_2 = await service.config_host_groups.create("group-2")

    main_config = await service.config
    config_1 = await group_1.config
    config_2 = await group_2.config
    assert isinstance(main_config, ObjectConfig)
    assert isinstance(config_1, HostGroupConfig)
    configs = (main_config, config_1, config_2)

    assert len({c.id for c in configs}) == 3

    person_default = {"name": "Joe", "age": "24", "sex": "m"}

    values = get_field_value("Set me", configs=configs)
    assert set(values) == {None}
    values = get_field_value("A lot of text", "sag", "quantity", configs=configs)
    assert set(values) == {None}
    values = get_field_value("from_doc", "person", configs=configs)
    assert all(v == person_default for v in values)

    req_val_1, req_val_2 = 12, 44
    person_val_1 = {"name": "Boss", "age": "unknown"}
    person_val_2 = {"name": "Moss", "awesome": "yes"}

    main_config["Set me", Parameter].set(req_val_1)
    main_config["from_doc"]["person"].set(person_val_1)  # type: ignore
    main_config["Optional", ActivatableParameterGroup].activate()
    # todo fix working with structures here
    # sag = main_config["A lot of text"]["sag"]  # type: ignore
    # sag["quantity"].set(4)# type: ignore
    # sag["nested"]["attr"].set(  "foo") # type: ignore
    # sag["nested"]["op"].set(  "bar") # type: ignore

    config_1["Set me", ParameterHG].set(req_val_2)
    config_1["from_doc"]["person"].set(person_val_2)  # type: ignore
    config_1["Optional", ActivatableParameterGroupHG].desync()

    config_2["from_doc"]["person"].set(person_val_2)  # type: ignore
    config_2["Optional", ActivatableParameterGroupHG].desync()

    await main_config.save()
    await config_1.refresh(strategy=apply_local_changes)
    await config_2.refresh(strategy=apply_remote_changes)

    # todo same fix with structure
    # values = get_field_value("A lot of text", "sag", "quantity", configs=configs)
    # assert set(values) == {4}
    values = get_field_value("Set me", configs=configs)
    assert values == (req_val_1, req_val_2, req_val_1)
    main_val, c1_val, c2_val = get_field_value("from_doc", "person", configs=configs)
    assert main_val == c2_val == person_val_1
    assert c1_val == person_val_2
