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

from collections.abc import Iterable
from functools import reduce
from typing import Any
import asyncio

from httpx import AsyncClient
import pytest
import pytest_asyncio

from adcm_aio_client import Filter
from adcm_aio_client.client import ADCMClient
from adcm_aio_client.config import (
    ActivatableParameterGroup,
    ActivatableParameterGroupHG,
    Parameter,
    ParameterGroup,
    ParameterHG,
    apply_local_changes,
    apply_remote_changes,
)
from adcm_aio_client.config._objects import HostGroupConfig, ObjectConfig
from adcm_aio_client.errors import ConfigNoParameterError, ConflictError
from adcm_aio_client.host_groups._config_group import ConfigHostGroup
from adcm_aio_client.objects import Bundle, Cluster, Host, Service

pytestmark = [pytest.mark.asyncio]


def get_field_value(*names: str, configs: Iterable[ObjectConfig | HostGroupConfig]) -> tuple[Any, ...]:
    return tuple(
        reduce(lambda x, y: x[y], names, config).value  # type: ignore
        for config in configs
    )


async def get_service_with_config(cluster: Cluster) -> Service:
    return await cluster.services.get(name__eq="complex_config")


async def get_object_config(obj: Service | ConfigHostGroup, httpx_client: AsyncClient) -> tuple[dict, dict]:
    url = "/".join(map(str, (*obj.get_own_path(), "configs", "")))
    response = await httpx_client.get(url=url, params={"ordering": "-id", "limit": 2})
    assert response.status_code == 200

    for result in response.json()["results"]:
        if result["isCurrent"]:
            cfg_id = result["id"]
            break
    else:
        raise RuntimeError("Can't find current config")

    response = await httpx_client.get(url=f"{url}{cfg_id}/")
    assert response.status_code == 200

    response = response.json()
    assert response["isCurrent"]

    return response["config"], response["adcmMeta"]


async def refresh_and_get_configs(*objects: Service | ConfigHostGroup) -> list[ObjectConfig | HostGroupConfig]:
    configs = []
    for obj in objects:
        await obj.refresh()
        configs.append(await obj.config)

    return configs


@pytest_asyncio.fixture()
async def cluster(adcm_client: ADCMClient, complex_cluster_bundle: Bundle) -> Cluster:
    cluster = await adcm_client.clusters.create(bundle=complex_cluster_bundle, name="Awesome Cluster")
    await cluster.services.add(filter_=Filter(attr="name", op="eq", value="complex_config"))
    return cluster


async def test_config_history(cluster: Cluster) -> None:
    config = await cluster.config
    for i in range(50):
        await config.save(description=f"config-{i}")

    first_to_last = await asyncio.gather(*(cluster.config_history[i] for i in range(51)))
    last_to_first = await asyncio.gather(*(cluster.config_history[-(i + 1)] for i in range(51)))

    assert len(first_to_last) == len(last_to_first) == 51
    assert first_to_last[-1].id == config.id
    assert last_to_first[0].id == config.id

    first_to_last_ids = [c.id for c in first_to_last]
    last_to_first_ids = [c.id for c in last_to_first]

    assert first_to_last_ids == list(reversed(last_to_first_ids))


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
    assert len(diff._diff) == 1
    assert ("very_important_flag",) in diff._diff
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
    assert len(diff._diff) == 6


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
    complexity_default = 4
    complexity_changed = 10
    person_val_1 = {"name": "Boss", "age": "unknown"}
    person_val_2 = {"name": "Moss", "awesome": "yes"}
    strange_val_1 = {"custom": [1, 2, 3]}
    strange_val_2 = [1, {"something": "else"}]
    strange_val_3 = ["something", "strange", 43, {"happenning": "here"}]

    main_config["Set me", Parameter].set(req_val_1)
    main_config["from_doc"]["person"].set(person_val_1)  # type: ignore
    main_config["more"]["strange"].set(strange_val_1)  # type: ignore
    main_config["Optional", ActivatableParameterGroup].activate()
    main_config["complexity_level", Parameter].set(complexity_changed)
    sag = main_config["A lot of text"]["sag"]  # type: ignore
    sag["quantity"].set(4)  # type: ignore
    sag["nested"]["attr"].set("foo")  # type: ignore
    sag["nested"]["op"].set("bar")  # type: ignore

    config_1["Set me", ParameterHG].set(req_val_2)
    config_1["from_doc"]["person"].set(person_val_2)  # type: ignore
    config_1["more"]["strange"].set(strange_val_2)  # type: ignore
    config_1["Optional", ActivatableParameterGroupHG].desync()
    config_1["complexity_level", ParameterHG].desync()

    config_2["from_doc"]["person"].set(person_val_2)  # type: ignore
    config_2["more"]["strange"].set(strange_val_3)  # type: ignore
    config_2["Optional", ActivatableParameterGroupHG].desync()
    config_2["complexity_level", ParameterHG].desync()

    await main_config.save()
    await config_1.refresh(strategy=apply_local_changes)
    await config_2.refresh(strategy=apply_remote_changes)

    config_1["A lot of text"]["sag"]["nested"]["op"].sync().desync()  # type: ignore
    values = get_field_value("A lot of text", "sag", "quantity", configs=configs)
    assert set(values) == {4}
    values = get_field_value("Set me", configs=configs)
    assert values == (req_val_1, req_val_2, req_val_1)
    values = get_field_value("more", "strange", configs=configs)
    assert values == (strange_val_1, strange_val_2, strange_val_1)
    main_val, c1_val, c2_val = get_field_value("from_doc", "person", configs=configs)
    assert main_val == c2_val == person_val_1
    assert c1_val == person_val_2
    values = get_field_value("complexity_level", configs=configs)
    assert values == (complexity_changed, complexity_default, complexity_changed)
    # since attributes are compared as a whole, desync is considered a change
    # => priority of local change
    assert not config_1.data.attributes["/complexity_level"]["isSynchronized"]
    assert not config_1.data.attributes["/agroup"]["isActive"]
    assert not config_1.data.attributes["/agroup"]["isSynchronized"]
    # the opposite situation when we "desynced", but changes overriten
    assert config_2.data.attributes["/complexity_level"]["isSynchronized"]
    assert config_2.data.attributes["/agroup"]["isActive"]
    assert config_2.data.attributes["/agroup"]["isSynchronized"]

    await config_1.save()
    await config_2.save()

    param: ParameterHG = config_1["more"]["strange"]  # type: ignore
    assert param.value == strange_val_2
    param.sync()
    assert param.value == strange_val_2
    await config_1.save()
    # param most likely will have strange data,
    # so it's correct to re-read it
    param: ParameterHG = config_1["more"]["strange"]  # type: ignore
    # bit of ADCM logic: sync parameter shipped from object's config
    assert param.value == strange_val_1


async def test_config_two_sessions(
    second_adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    cluster: Cluster,
    simple_hostprovider_bundle: Bundle,
) -> None:
    provider = await second_adcm_client.hostproviders.create(bundle=simple_hostprovider_bundle, name="Test HP")
    host = await second_adcm_client.hosts.create(hostprovider=provider, name="Test-host", cluster=cluster)

    # get two copies of the same object with different clients
    service_name = "complex_config"
    service_1 = await cluster.services.get(name__eq=service_name)
    service_2 = await (await second_adcm_client.clusters.get(name__eq=cluster.name)).services.get(name__eq=service_name)

    assert type(service_1) is type(service_2)
    assert service_1.id == service_2.id
    assert id(service_1._requester) != id(service_2._requester)

    component = await service_1.components.get(name__eq="component1")
    mapping = await cluster.mapping
    await mapping.add(component=component, host=host)
    await mapping.save()

    # set required field
    cfg = await service_1.config
    cfg["Set me", Parameter].set(True)
    await cfg.save()

    # tests
    await two_sessions_case_1(service_1, service_2, httpx_client=httpx_client)
    await two_sessions_case_2(service_1, service_2, httpx_client=httpx_client)
    await two_sessions_case_3(service_1, service_2, httpx_client=httpx_client)
    await two_sessions_case_4(service_1, service_2, httpx_client=httpx_client)
    await two_sessions_case_5(service_1, service_2, httpx_client=httpx_client)
    await two_sessions_case_6(service_1, service_2, host=host)
    await two_sessions_case_7(service_1, service_2, httpx_client=httpx_client)
    await two_sessions_case_8(service_1, service_2, httpx_client=httpx_client)
    await two_sessions_case_9(service_1, service_2, httpx_client=httpx_client)


async def two_sessions_case_1(obj1: Service, obj2: Service, httpx_client: AsyncClient) -> None:
    """
    user 1: set value (same as initial), save config;
    user 2: set value (same as initial), refresh (apply remote)
    """

    cfg1, cfg2 = await refresh_and_get_configs(obj1, obj2)
    assert isinstance(cfg1, ObjectConfig) and isinstance(cfg2, ObjectConfig)

    remote_config, _ = await get_object_config(obj1, httpx_client)
    field_display_name = "Complexity Level"
    field_name = "complexity_level"
    value = remote_config[field_name]

    field1 = cfg1[field_display_name, Parameter]
    field2 = cfg2[field_display_name, Parameter]

    # user 1
    field1.set(value)
    await cfg1.save()

    # user 2
    field2.set(value)
    await cfg2.refresh(strategy=apply_remote_changes)

    remote_config, _ = await get_object_config(obj1, httpx_client)
    assert (
        remote_config[field_name]
        == value
        == cfg1[field_display_name, Parameter].value
        == cfg2[field_display_name, Parameter].value
    )


async def two_sessions_case_2(obj1: Service, obj2: Service, httpx_client: AsyncClient) -> None:
    """
    user 1: activate group, set field1's value, save config;
    user 2: activate group, set field2's value, refresh (apply local); save config
    """

    cfg1, cfg2 = await refresh_and_get_configs(obj1, obj2)
    assert isinstance(cfg1, ObjectConfig) and isinstance(cfg2, ObjectConfig)

    agr_display_name = "Optional"
    agr_name = "agroup"
    field1 = "justhere"
    value1 = 3
    field2 = "field2"
    value2 = 6

    # user 1
    gr1 = cfg1[agr_display_name, ActivatableParameterGroup]
    gr1.activate()
    gr1[field1, Parameter].set(value1)
    await cfg1.save()

    remote_config, _ = await get_object_config(obj1, httpx_client)
    assert (
        cfg1[agr_name, ActivatableParameterGroup][field1, Parameter].value == value1 == remote_config[agr_name][field1]
    )

    # user 2
    gr2 = cfg2[agr_display_name, ActivatableParameterGroup]
    gr2.activate()
    gr2[field2, Parameter].set(value2)
    await cfg2.refresh(strategy=apply_local_changes)

    assert cfg2[agr_name, ActivatableParameterGroup][field1, Parameter].value == value1
    assert cfg2[agr_name, ActivatableParameterGroup][field2, Parameter].value == value2

    await cfg2.save()

    remote_cfg, _ = await get_object_config(obj1, httpx_client)
    assert (
        cfg2[agr_display_name, ActivatableParameterGroup][field1, Parameter].value
        == value1
        == remote_cfg[agr_name][field1]
    )
    assert (
        cfg2[agr_display_name, ActivatableParameterGroup][field2, Parameter].value
        == value2
        == remote_cfg[agr_name][field2]
    )


async def two_sessions_case_3(obj1: Service, obj2: Service, httpx_client: AsyncClient) -> None:
    """
    user 1: config group: desync field, set field value1;
    user 2: object: set field value2, save config
    user1: config group: save config
    """
    # create_config group
    chg = await obj2.config_host_groups.create(name="Service CHG")

    object_cfg, chg_cfg = await refresh_and_get_configs(obj1, chg)
    assert isinstance(object_cfg, ObjectConfig) and isinstance(chg_cfg, HostGroupConfig)

    field = "complexity_level"
    value1 = 0
    value2 = 1
    initial = 4

    remote_obj_cfg, _ = await get_object_config(obj1, httpx_client)
    remote_chg_cfg, _ = await get_object_config(chg, httpx_client)
    assert (
        remote_obj_cfg[field]
        == remote_chg_cfg[field]
        == initial
        == object_cfg[field, Parameter].value
        == chg_cfg[field, ParameterHG].value
    )

    # user 1
    field1 = chg_cfg[field, ParameterHG]
    field1.desync()
    field1.set(value1)

    # user 2
    field2 = object_cfg[field, Parameter]
    field2.set(value2)
    await object_cfg.save()

    # user 1
    await chg_cfg.save()

    remote_object_cfg, _ = await get_object_config(obj1, httpx_client)
    remote_chg_cfg, _ = await get_object_config(chg, httpx_client)

    assert remote_chg_cfg[field] == value1 == chg_cfg[field, ParameterHG].value
    assert remote_object_cfg[field] == value2 == object_cfg[field, Parameter].value


async def two_sessions_case_4(obj1: Service, obj2: Service, httpx_client: AsyncClient) -> None:
    """
    user 1: set field1 - value1, field2 - value2, field3 - value3;
    user 2: set field1 - value3, save config
    user 1: refresh (apply local)
    """

    cfg1, cfg2 = await refresh_and_get_configs(obj1, obj2)
    assert isinstance(cfg1, ObjectConfig) and isinstance(cfg2, ObjectConfig)

    field1 = "complexity_level"
    field2 = "very_important_flag"
    field3 = "int_field"
    initial1 = 1
    initial2 = True
    initial3 = None
    value1 = 90
    value2 = False
    value3 = 5

    remote_cfg, _ = await get_object_config(obj1, httpx_client)
    assert remote_cfg[field1] == initial1
    assert remote_cfg[field2] == initial2
    assert remote_cfg[field3] == initial3

    # user 1
    cfg1[field1, Parameter].set(value1)
    cfg1[field2, Parameter].set(value2)
    cfg1[field3, Parameter].set(value3)

    # user 2
    cfg2[field1, Parameter].set(value3)
    await cfg2.save()

    # user 1
    await cfg1.refresh(strategy=apply_local_changes)

    assert cfg1[field1, Parameter].value == value1
    assert cfg1[field2, Parameter].value == value2
    assert cfg1[field3, Parameter].value == value3

    remote_cfg, _ = await get_object_config(obj1, httpx_client)
    assert remote_cfg[field1] == value3 == cfg2[field1, Parameter].value
    assert remote_cfg[field2] == initial2 == cfg2[field2, Parameter].value
    assert remote_cfg[field3] == initial3 == cfg2[field3, Parameter].value


async def two_sessions_case_5(obj1: Service, obj2: Service, httpx_client: AsyncClient) -> None:
    """
    user 1: set field1 - value1, field2 - value2, field3 - value3;
    user 2: set field1 - value3, field2 - value2, field3 - value4, save config
    user 1: refresh (apply remote)
    """
    field1 = "complexity_level"
    field2 = "int_field"
    field3 = "int_field2"
    initial1 = 5
    initial2 = None
    initial3 = None
    value1 = 20
    value2 = 30
    value3 = 40
    value4 = 50

    remote_cfg, _ = await get_object_config(obj1, httpx_client)
    assert remote_cfg[field1] == initial1
    assert remote_cfg[field2] == initial2
    assert remote_cfg[field3] == initial3

    cfg1, cfg2 = await refresh_and_get_configs(obj1, obj2)
    assert isinstance(cfg1, ObjectConfig) and isinstance(cfg2, ObjectConfig)

    # user 1
    cfg1[field1, Parameter].set(value1)
    cfg1[field2, Parameter].set(value2)
    cfg1[field3, Parameter].set(value3)

    # user 2
    cfg2[field1, Parameter].set(value3)
    cfg2[field2, Parameter].set(value2)
    cfg2[field3, Parameter].set(value4)
    await cfg2.save()

    # user 1
    await cfg1.refresh(strategy=apply_remote_changes)
    remote_cfg, _ = await get_object_config(obj1, httpx_client)

    assert cfg1[field1, Parameter].value == value3 == remote_cfg[field1]
    assert cfg1[field2, Parameter].value == value2 == remote_cfg[field2]
    assert cfg1[field3, Parameter].value == value4 == remote_cfg[field3]


async def two_sessions_case_6(obj1: Service, obj2: Service, host: Host) -> None:
    """
    user 1: map host to chg1;
    user 2: map host to chg2, get error
    """

    chg1 = await obj1.config_host_groups.create(name="Service CHG 1")
    chg2 = await obj2.config_host_groups.create(name="Service CHG 2")
    assert id(chg1._requester) != id(chg2._requester)

    # user 1
    await chg1.hosts.add(host=host)

    # user 2
    with pytest.raises(ExceptionGroup) as exc:
        await chg2.hosts.add(host=host)
    assert exc.group_contains(ConflictError, match="GROUP_CONFIG_HOST_ERROR")


async def two_sessions_case_7(obj1: Service, obj2: Service, httpx_client: AsyncClient) -> None:
    """
    user 1: in CHG: desync field, set field - value1;
    user 2: in object: set field - value2, save cfg;
    user 1: in CHG: reset cfg, save
    """

    chg = await obj1.config_host_groups.get(name__eq="Service CHG 2")
    chg_cfg, obj_cfg = await refresh_and_get_configs(chg, obj2)
    assert isinstance(chg_cfg, HostGroupConfig) and isinstance(obj_cfg, ObjectConfig)

    field = "int_field2"
    value1 = 55
    value2 = 66

    # user 1
    field1 = chg_cfg[field, ParameterHG]
    field1.desync()
    field1.set(value1)

    # user 2
    field2 = obj_cfg[field, Parameter]
    field2.set(value2)
    await obj_cfg.save()

    # user 1
    chg_cfg.reset()
    await chg_cfg.save()

    remote_cfg, _ = await get_object_config(chg, httpx_client)
    assert chg_cfg[field, ParameterHG].value == value2 == remote_cfg[field]


async def two_sessions_case_8(obj1: Service, obj2: Service, httpx_client: AsyncClient) -> None:
    """
    cluster with service, service CHG, deactivated group in service cfg
    user 1: in CHG: set group.field - value1, save cfg;
    user 2: in CGH: set group.field - value2, refresh cfg (apply local)
    """

    # prepare
    chg_name = "Service CHG 3"
    chg1 = await obj1.config_host_groups.create(name=chg_name)
    chg2 = await obj2.config_host_groups.get(name__eq=chg_name)

    remote_cfg, remote_meta = await get_object_config(obj1, httpx_client)
    group = "agroup"
    gr_field = "justhere"
    value1 = 100
    value2 = 200
    initial = remote_cfg[group][gr_field]
    assert len({initial, value1, value2}) == 3  # ensure no duplicate values

    obj_cfg = await obj1.config
    assert obj_cfg.data.attributes["/agroup"]["isActive"] is True
    assert remote_meta[f"/{group}"]["isActive"] is True

    obj_cfg[group, ActivatableParameterGroup].deactivate()
    await obj_cfg.save()
    _, remote_meta = await get_object_config(obj1, httpx_client)
    assert obj_cfg.data.attributes["/agroup"]["isActive"] is False
    assert remote_meta[f"/{group}"]["isActive"] is False

    await chg1.refresh()
    chg_cfg1 = await chg1.config
    await chg2.refresh()
    chg_cfg2 = await chg2.config

    assert isinstance(chg_cfg1, HostGroupConfig) and isinstance(chg_cfg2, HostGroupConfig)
    assert chg_cfg1.id == chg_cfg2.id
    assert type(chg_cfg1._parent) is type(chg_cfg2._parent) and chg_cfg1._parent.id == chg_cfg2._parent.id  # pyright: ignore[reportAttributeAccessIssue]
    assert id(chg_cfg1._parent._requester) != id(chg_cfg2._parent._requester)  # pyright: ignore[reportAttributeAccessIssue]

    # user 1
    group1 = chg_cfg1[group, ActivatableParameterGroupHG]
    assert isinstance(group1, ActivatableParameterGroupHG)

    field1 = group1[gr_field, ParameterHG]
    assert isinstance(field1, ParameterHG)
    assert field1._data.attributes[f"/{group}/{gr_field}"]["isSynchronized"]

    field1.set(value1)
    assert not field1._data.attributes[f"/{group}/{gr_field}"]["isSynchronized"]

    await chg_cfg1.save()

    remote_cfg, remote_meta = await get_object_config(chg1, httpx_client)
    assert (
        chg_cfg1[group, ActivatableParameterGroupHG][gr_field, ParameterHG].value
        == value1
        == remote_cfg[group][gr_field]
    )

    # user 2
    group2 = chg_cfg2[group, ActivatableParameterGroupHG]
    group2[gr_field, ParameterHG].set(value2)

    await chg_cfg2.refresh(strategy=apply_local_changes)

    assert chg_cfg2[group, ActivatableParameterGroupHG][gr_field, ParameterHG].value == value2


async def two_sessions_case_9(obj1: Service, obj2: Service, httpx_client: AsyncClient) -> None:
    """
    cluster with service, service CHG, deactivated group in service cfg
    user 1: in CHG: set group.field - value1, save cfg;
    user 2: in CGH: set group.field - value2, refresh cfg (apply remote)
    """

    # prepare
    chg_name = "Service CHG 3"
    chg1 = await obj1.config_host_groups.get(name__eq=chg_name)
    chg2 = await obj2.config_host_groups.get(name__eq=chg_name)

    remote_cfg, remote_meta = await get_object_config(obj1, httpx_client)
    group = "agroup"
    gr_field = "justhere"
    value1 = 111
    value2 = 222
    initial = remote_cfg[group][gr_field]
    assert len({initial, value1, value2}) == 3  # ensure no duplicate values

    obj_cfg = await obj1.config
    obj_cfg[group, ActivatableParameterGroup].deactivate()
    await obj_cfg.save()

    await chg1.refresh()
    chg_cfg1 = await chg1.config
    await chg2.refresh()
    chg_cfg2 = await chg2.config

    assert isinstance(chg_cfg1, HostGroupConfig) and isinstance(chg_cfg2, HostGroupConfig)
    assert chg_cfg1.id == chg_cfg2.id
    assert type(chg_cfg1._parent) is type(chg_cfg2._parent) and chg_cfg1._parent.id == chg_cfg2._parent.id  # pyright: ignore[reportAttributeAccessIssue]
    assert id(chg_cfg1._parent._requester) != id(chg_cfg2._parent._requester)  # pyright: ignore[reportAttributeAccessIssue]

    # user 1
    chg_cfg1[group, ActivatableParameterGroupHG][gr_field, ParameterHG].set(value1)
    await chg_cfg1.save()

    remote_cfg, _ = await get_object_config(chg1, httpx_client)
    assert (
        chg_cfg1[group, ActivatableParameterGroupHG][gr_field, ParameterHG].value
        == value1
        == remote_cfg[group][gr_field]
    )

    # user 2
    group2 = chg_cfg2[group, ActivatableParameterGroupHG]
    group2[gr_field, ParameterHG].set(value2)

    await chg_cfg2.refresh(strategy=apply_remote_changes)

    assert chg_cfg2[group, ActivatableParameterGroupHG][gr_field, ParameterHG].value == value1
