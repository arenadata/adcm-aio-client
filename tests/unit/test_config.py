from copy import deepcopy
from typing import Self
import json

import pytest

from adcm_aio_client.core.config._objects import ActivatableGroup, ConfigOwner, Group, ObjectConfig, Value
from adcm_aio_client.core.config.types import ConfigData, ConfigSchema
from adcm_aio_client.core.objects._base import InteractiveObject
from adcm_aio_client.core.types import Endpoint, Requester
from tests.unit.conftest import RESPONSES


class DummyParent(InteractiveObject):
    def get_own_path(self: Self) -> Endpoint:
        return ("dummy",)


@pytest.fixture()
def example_config() -> tuple[dict, dict]:
    config = json.loads((RESPONSES / "test_config_example_config.json").read_text())

    schema = json.loads((RESPONSES / "test_config_example_config_schema.json").read_text())

    return config, schema


@pytest.fixture()
def dummy_parent(queue_requester: Requester) -> ConfigOwner:
    return DummyParent(data={"id": 4}, requester=queue_requester)


@pytest.fixture()
def object_config(example_config: tuple[dict, dict], dummy_parent: ConfigOwner) -> ObjectConfig:
    config_data, schema_data = example_config

    data = ConfigData.from_v2_response(data_in_v2_format=deepcopy(config_data))
    schema = ConfigSchema(spec_as_jsonschema=schema_data)

    return ObjectConfig(config=data, schema=schema, parent=dummy_parent)


def test_edit_config(example_config: tuple[dict, dict], object_config: ObjectConfig) -> None:
    data, _ = example_config

    initial_parsed_data = deepcopy(data)
    initial_parsed_data["config"]["root_json"] = json.loads(initial_parsed_data["config"]["root_json"])
    initial_parsed_data["config"]["main"]["inner_json"] = json.loads(
        initial_parsed_data["config"]["main"]["inner_json"]
    )

    new_inner_json = {
        "complex": [],
        "jsonfield": 23,
        "link": "do i look like a link to you?",
        "arguments": ["-q", "something"],
    }
    new_root_json = ["now", "I am", "cool"]

    new_config = {
        "root_int": 430,
        "root_list": ["first", "second", "third", "best thing there is"],
        "root_dict": None,
        "duplicate": "hehe",
        "root_json": new_root_json,
        "main": {
            "inner_str": "not the worst at least",
            "inner_dict": {"a": "b", "additional": "keys", "are": "welcome"},
            "inner_json": new_inner_json,
            "duplicate": 44,
        },
        "optional_group": {"param": 44.44},
        "root_str": "newstring",
    }

    # todo:
    #  - check no POST requests are performed

    config = object_config

    assert config.data.values == initial_parsed_data["config"]
    assert config.data.attributes == initial_parsed_data["adcmMeta"]

    # Edit "root" values

    config["root_int", Value].set(new_config["root_int"])

    # inner type won't be checked (list),
    # but here we pretend "to be 100% sure" it's `list`, not `None`
    config["root_list", Value].set([*config["root_list", Value[list]].value, new_config["root_list"][-1]])

    root_dict = config["root_dict"]
    assert isinstance(root_dict, Value)
    assert isinstance(root_dict.value, dict)
    root_dict.set(None)
    assert root_dict.value is None
    assert config["root_dict", Value].value is None

    # Edit group ("nested") values

    print(config.schema._groups)

    assert isinstance(config["main"], Group)
    # if we don't want type checker to bother us, we can yolo like that
    config["main"]["inner_str"].set(new_config["main"]["inner_str"])  # type: ignore

    main_group = config["main"]
    assert isinstance(main_group, Group)
    main_group["inner_dict", Value].set(
        {**main_group["inner_dict", Value[dict]].value, "additional": "keys", "are": "welcome"}
    )

    activatable_group = config["optional_group"]
    assert isinstance(activatable_group, ActivatableGroup)
    activatable_group.activate()

    # Edit JSON field

    # change value separately and set
    json_field = main_group["inner_json"]
    assert isinstance(json_field, Value)
    assert isinstance(json_field.value, dict)
    new_value = deepcopy(json_field.value)
    new_value.pop("server")
    new_value |= {"link": "do i look like a link to you?", "arguments": ["-q", "something"]}
    json_field.set(new_value)

    # swap value type with direct set
    assert isinstance(config["root_json"].value, dict)  # type: ignore
    config["root_json"].set(["now", "I am", "cool"])  # type: ignore

    # Type change specifics

    param = config["root_str"]
    assert isinstance(param, Value)
    assert param.value is None

    param.set("newstring")
    assert isinstance(config["root_str"].value, str)  # type: ignore

    # Check all values are changed

    config_for_save = config.data
    assert config_for_save.values == new_config
    assert config_for_save.attributes == {"/optional_group": {"isActive": True}}
