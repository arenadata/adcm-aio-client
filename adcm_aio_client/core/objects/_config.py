from typing import Any, Callable, Iterable, Protocol, Self
from copy import deepcopy
from operator import itemgetter
from collections import deque

import asyncio

from adcm_aio_client.core.types import AwareOfOwnPath, Requester

class MergeStrategy(Protocol):
    ...

class ConfigDiff:
    ...

# External Section
# these functions are heavily inspired by configuration rework in ADCM (ADCM-6034)

ROOT_PREFIX = "/"

type ParameterName = str
type ParameterDisplayName = str
type AnyParameterName = ParameterName | ParameterDisplayName

type LevelNames = tuple[ParameterName, ...]


def set_nested_config_value[T](config: dict[str, Any], level_names: LevelNames, value: T) -> T:
    group, level_name = get_group_with_value(config=config, level_names=level_names)
    group[level_name] = value
    return value


def change_nested_config_value[T](config: dict[str, Any], level_names: LevelNames, func: Callable[[Any], T]) -> T:
    group, level_name = get_group_with_value(config=config, level_names=level_names)
    group[level_name] = func(group[level_name])
    return group[level_name]

def get_nested_config_value(config: dict[str, Any], level_names: LevelNames) -> Any:
    group, level_name = get_group_with_value(config=config, level_names=level_names)
    return group[level_name]

def get_group_with_value(config: dict[str, Any], level_names: LevelNames) -> tuple[dict[str, Any], ParameterName]:
    return _get_group_with_value(config=config, level_names=level_names)


def _get_group_with_value(
    config: dict[str, Any], level_names: Iterable[ParameterName]
) -> tuple[dict[str, Any], ParameterName]:
    level_name, *rest = level_names
    if not rest:
        return config, level_name

    return _get_group_with_value(config=config[level_name], level_names=rest)


def level_names_to_full_name(levels: LevelNames) -> str:
    return ensure_full_name("/".join(levels))


def ensure_full_name(name: str) -> str:
    if not name.startswith(ROOT_PREFIX):
        return f"{ROOT_PREFIX}{name}"

    return name
# External Section End

def is_group_v2(attributes: dict) -> bool:
    ...

def is_activatable_v2(attributes: dict) -> bool:
    ...

def is_json_v2(attributes: dict) -> bool:
    ...

class ConfigSchema:
    def __init__(self: Self, spec_as_jsonschema: dict) -> None:
        self._raw = spec_as_jsonschema

        self._jsons: set[LevelNames] =set() 
        self._groups: set[LevelNames] = set()
        self._activatable_groups: set[LevelNames] = set()
        self._display_name_map: dict[tuple[LevelNames, ParameterDisplayName], ParameterName] = {}

        self._analyze_schema()

    @property
    def json_fields(self: Self) -> set[LevelNames]:
        return self._jsons

    def is_group(self: Self, parameter_name: LevelNames) -> bool:
        return parameter_name in self._groups

    def is_activatable_group(self: Self, parameter_name: LevelNames) -> bool:
        return parameter_name in self._activatable_groups

    def get_level_name(self: Self, group: LevelNames, display_name: ParameterDisplayName) -> ParameterName | None:
        key = (group, display_name)
        return self._display_name_map.get(key)


    def _analyze_schema(self: Self) -> None:
        for level_names, param_spec in self._iterate_parameters(object_schema=self._raw):
            if is_group_v2(param_spec):
                self._groups.add(level_names)

                if is_activatable_v2(param_spec):
                    self._activatable_groups.add(level_names)
            elif is_json_v2(param_spec):
                self._jsons.add(level_names)

            *group, own_level_name =  level_names
            display_name = param_spec["title"]
            self._display_name_map[tuple(group), display_name] = own_level_name

    def _iterate_parameters(self: Self, object_schema: dict) -> Iterable[tuple[LevelNames, dict]]:
        for level_name, parameter in object_schema["properties"].items():
            is_group = is_group_v2(parameter)
            if is_group:
                for inner_level, inner_parameter in self._iterate_parameters(parameter):
                    yield (level_name, *inner_level), inner_parameter
            else:
                yield level_name, parameter
                
class ConfigData:
    __slots__ = ("id", "description", "_config", "_attributes")

    def __init__(self: Self, data_in_v2_format: dict) -> None:
        self._config = data_in_v2_format["config"]
        self._attributes = data_in_v2_format["adcmMeta"]
        self.id = data_in_v2_format["id"]
        self.description = data_in_v2_format["description"]

    def get_value(self: Self, parameter: LevelNames) -> Any:
        return get_nested_config_value(config=self._config, level_names=parameter)
    
    def set_value[T](self: Self, parameter: LevelNames, value: T) -> T:
        return set_nested_config_value(config=self._config, level_names=parameter, value=value)

    def get_attribute(self: Self, parameter: LevelNames, attribute: str) -> Any:
        full_name = level_names_to_full_name(parameter)
        return self._attributes[full_name][attribute]

    def set_attribute[T](self: Self, parameter: LevelNames, attribute: str, value: T) -> T:
        full_name = level_names_to_full_name(parameter)
        self._attributes[full_name][attribute] = value
        return value


class _ConfigWrapper:

    def __init__(self: Self, 
                 data: ConfigData,
                 schema: ConfigSchema,
                 name: LevelNames, 
                 ) -> None:
        self._name = name
        self._schema = schema
        self._data = data

class _Group(_ConfigWrapper):

    def __getitem__(self: Self, item) -> "ConfigEntry":
        ...


class Value[T](_ConfigWrapper):
    
    @property
    def value(self: Self) -> T:
        # todo probably want to return read-only proxies for list/dict
        return self._data.get_value(parameter=self._name)

    def set(self: Self, value: Any) -> Self:
        self._data.set_value(parameter=self._name, value=value)
        return self

class Group(_Group):
    ...

class ActivatableGroup(Group):

    def activate(self: Self) -> Self:
        self._data.set_attribute(parameter=self._name, attribute="isActive", value=True)
        return self

    def deactivate(self: Self) -> Self:
        self._data.set_attribute(parameter=self._name, attribute="isActive", value=False)
        return self

class ConfigWrapper(Group):
    ...

type ConfigEntry = Value | Group | ActivatableGroup


class ObjectConfig:
    def __init__(self, config: ConfigData, schema: ConfigSchema) -> None:
        self._schema = schema
        # parse config?
        self._initial_config = self._parse_json_fields_inplace_safe(config)
        self._editable_config = self._init_editable_config(self._initial_config)

    # Public Interface (for End User)

    @property
    def id(self: Self) -> int:
        return int(self._initial_config.id)

    @property
    def description(self: Self) -> str:
        return str(self._initial_config.description)

    def reset(self: Self) -> Self:
        self._init_editable_config(self._initial_config)
        return self

    def difference(self: Self, other: Self) -> ConfigDiff:
        # todo
        ...
    
    async def save(self: Self) -> Self:
        # todo
        return self
    

    async def  refresh(self: Self, strategy: MergeStrategy) -> Self:
        # todo
        return self

    def __getitem__(self, item: AnyParameterName) -> ConfigEntry:
        return self._editable_config[item]

    # Public For Internal Use Only

    # Private
    def _parse_json_fields_inplace_safe(self: Self, config: ConfigData) -> ConfigData:
        # todo        
        return config

    def _init_editable_config(self: Self, source_config: ConfigData) -> ConfigWrapper:
        self._editable_config = ConfigWrapper(data=deepcopy(source_config), schema=self._schema, name=())
        return self._editable_config

class ConfigHistoryNode:
    def __init__(self, parent: AwareOfOwnPath, requester: Requester) -> None:
        self._schema: ConfigSchema | None = None
        self._parent = parent
        self._requester = requester

    async def current(self: Self) -> ObjectConfig:
        # we are relying that current configuration will be 
        # one of last created
        query = {"ordering": "-id", "limit": 10, "offset": 0}
        return await self._retrieve_config(query=query, choose_suitable_config=get_current_config)

    async def __getitem__(self: Self, position: int) -> ObjectConfig:
        # since we don't have date in here, we sort by id
        ordering = "id" 
        offset = position
        if offset < 0:
            ordering = "-id"
            offset = abs(offset)

        query = {"limit": 1, "offset": offset, "ordering": ordering}

        return await self._retrieve_config(query=query, choose_suitable_config=get_first_result)

    async def _ensure_schema(self: Self) -> ConfigSchema:
        if self._schema is not None:
            return self._schema

        response = await self._requester.get(*self._parent.get_own_path(), "config-schema")
        schema = ConfigSchema(spec_as_jsonschema=response.as_dict())
        self._schema = schema
        return schema
    
    async def _retrieve_config(self: Self, query: dict, choose_suitable_config: Callable[[list[dict]], dict]) -> ObjectConfig:
        schema_task = asyncio.create_task(self._ensure_schema())

        path = (*self._parent.get_own_path(), "configs")

        config_records_response = await self._requester.get(*path, query=query)
        config_record = choose_suitable_config(config_records_response.as_dict()["results"])

        config_data_response = await self._requester.get(*path, config_record["id"])
        config_data = ConfigData(data_in_v2_format=config_data_response.as_dict())

        schema = await schema_task

        return ObjectConfig(config=config_data, schema=schema)





def get_first_result(results: list[dict]) -> dict:
    try:
        return results[0]
    except KeyError:
        message = "Configuration can't be found"
        raise RuntimeError(message)

def get_current_config(results: list[dict]) -> dict:
    for config in results:
        if config["isCurrent"]:
            return config

    message = "Failed to determine current configuraiton"
    raise RuntimeError(message)
