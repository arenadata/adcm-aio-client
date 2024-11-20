from copy import deepcopy
import json

import pytest

from adcm_aio_client.core.config._base import ActivatableGroupWrapper, EditableConfig, RegularGroupWrapper, ValueWrapper


@pytest.fixture()
def example_config() -> tuple[dict, dict]:
    regular_param_schema = {}
    group_like_param_schema = {
        "parameters": {},
        "additionalProperties": False,
        "default": {},
        "adcmMeta": {},
        "type": "object",
    }
    json_like_param_schema = {"format": "json"}

    config = {
        "config": {
            "root_int": 100,
            "root_list": ["first", "second", "third"],
            "root_dict": {"k1": "v1", "k2": "v2"},
            "duplicate": "hehe",
            "root_json": json.dumps({}),
            "main": {
                "inner_str": "evil",
                "inner_dict": {"a": "b"},
                "inner_json": json.dumps({"complex": [], "jsonfield": 23, "server": "bestever"}),
                "duplicate": 44,
            },
            "optional_group": {"param": 44.44},
            "root_str": None,
        },
        "adcmMeta": {"/optional_group": {"isActive": False}},
    }
    schema = {
        "parameters": {
            **{key: regular_param_schema for key in config["config"]},
            "root_json": json_like_param_schema,
            "main": group_like_param_schema
            | {
                "parameters": {
                    **{key: regular_param_schema for key in config["config"]["main"]},
                    "inner_json": json_like_param_schema,
                }
            },
            "optional_group": group_like_param_schema
            | {"properties": {"param": regular_param_schema}, "adcmMeta": {"activation": {"isAllowChange": True}}},
        }
    }

    return config, schema


def test_config_edit_by_name(example_config: tuple[dict, dict]) -> None:
    data, schema = example_config

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
        "root_json": json.dumps(new_root_json),
        "main": {
            "inner_str": "not the worst at least",
            "inner_dict": {"a": "b", "additional": "keys", "are": "welcome"},
            "inner_json": json.dumps(new_inner_json),
            "duplicate": 44,
        },
        "optional_group": {"param": 44.44},
        "root_str": "newstring",
    }

    # todo:
    #  - check no POST requests are performed

    config = EditableConfig(data=data, spec=schema)

    config_for_save = config.to_payload()
    assert config_for_save == data
    assert config_for_save is not data

    # Edit "root" values

    config["root_int", ValueWrapper].set(new_config["root_int"])

    # inner type won't be checked (list),
    # but here we pretend "to be 100% sure" it's `list`, not `None`
    config["root_list", ValueWrapper].set([*config["root_list", ValueWrapper[list]].value, new_config["root_list"][-1]])

    root_dict = config["root_dict"]
    assert isinstance(root_dict, ValueWrapper)
    assert isinstance(root_dict.value, dict)
    root_dict.set(None)
    assert root_dict.value is None
    assert config["root_dict"] is None

    # Edit group ("nested") values

    assert isinstance(config["main"], RegularGroupWrapper)
    config["main", RegularGroupWrapper]["inner_str", ValueWrapper].set(new_config["main"]["inner_str"])

    main_group = config["main"]
    assert isinstance(main_group, RegularGroupWrapper)
    main_group["inner_dict", ValueWrapper].set(
        {**main_group["inner_dict", ValueWrapper[dict]].value, "additional": "keys", "are": "welcome"}
    )

    activatable_group = config["optional_group"]
    assert isinstance(activatable_group, ActivatableGroupWrapper)
    activatable_group.activate()

    # Edit JSON field

    # change value separately and set
    json_field = main_group["inner_json"]
    assert isinstance(json_field, ValueWrapper)
    assert isinstance(json_field.value, dict)
    new_value = deepcopy(json_field.value)
    new_value.pop("server")
    new_value |= {"link": "do i look like a link to you?", "arguments": ["-q", "something"]}
    json_field.set(new_value)

    # swap value type with direct set
    assert isinstance(config["root_json", ValueWrapper[dict]].value, dict)
    config["root_json", ValueWrapper].set(["now", "I am", "cool"])

    # Type change specifics

    param = config["root_str"]
    assert isinstance(param, ValueWrapper)
    assert isinstance(param.value, str)

    param.set(None)
    assert config["root_str"] is None
    assert isinstance(param.value, str)

    param.set("newstring")
    assert isinstance(config["root_str"], str)

    # Check all values are changed

    config_for_save = config.to_payload()
    assert config_for_save["config"] == new_config
    assert config_for_save["adcmMeta"] == {"/optional_group": {"isActive": True}}
