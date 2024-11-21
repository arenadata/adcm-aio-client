from copy import deepcopy
import json

import pytest

from adcm_aio_client.core.config._base import ActivatableGroupWrapper, EditableConfig, RegularGroupWrapper, ValueWrapper
from tests.unit.conftest import RESPONSES


@pytest.fixture()
def example_config() -> tuple[dict, dict]:
    config = json.loads((RESPONSES / "test_config_example_config.json").read_text())

    schema = json.loads((RESPONSES / "test_config_example_config_schema.json").read_text())

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

    # deepcopy, because we want our "source" to be intact
    # and unchanged by json formating
    config = EditableConfig(data=deepcopy(data), spec=schema)

    config_for_save = config.to_payload()
    assert config_for_save == data

    # Edit "root" values

    config["root_int", ValueWrapper].set(new_config["root_int"])

    # inner type won't be checked (list),
    # but here we pretend "to be 100% sure" it's `list`, not `None`
    config["root_list", ValueWrapper].set([*config["root_list", ValueWrapper, list].value, new_config["root_list"][-1]])

    root_dict = config["root_dict"]
    assert isinstance(root_dict, ValueWrapper)
    assert isinstance(root_dict.value, dict)
    root_dict.set(None)
    assert root_dict.value is None
    assert config["root_dict", ValueWrapper].value is None

    # Edit group ("nested") values

    assert isinstance(config["main"], RegularGroupWrapper)
    config["main", RegularGroupWrapper]["inner_str", ValueWrapper].set(new_config["main"]["inner_str"])

    main_group = config["main"]
    assert isinstance(main_group, RegularGroupWrapper)
    main_group["inner_dict", ValueWrapper].set(
        {**main_group["inner_dict", ValueWrapper, dict].value, "additional": "keys", "are": "welcome"}
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
    assert isinstance(config["root_json", ValueWrapper, dict].value, dict)
    config["root_json", ValueWrapper].set(["now", "I am", "cool"])

    # Type change specifics

    param = config["root_str"]
    assert isinstance(param, ValueWrapper)
    assert param.value is None

    param.set("newstring")
    assert isinstance(config["root_str", ValueWrapper].value, str)

    # Check all values are changed

    config_for_save = config.to_payload()
    assert config_for_save["config"] == new_config
    assert config_for_save["adcmMeta"] == {"/optional_group": {"isActive": True}}
