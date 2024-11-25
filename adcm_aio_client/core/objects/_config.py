from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Protocol, Self, overload
import json
import asyncio

from adcm_aio_client.core.errors import RequesterError
from adcm_aio_client.core.types import AwareOfOwnPath, Requester

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


def full_name_to_level_names(full: ParameterFullName) -> tuple[ParameterLevelName, ...]:
    return tuple(filter(bool, full.split("/")))


def ensure_full_name(name: str) -> str:
    if not name.startswith(ROOT_PREFIX):
        return f"{ROOT_PREFIX}{name}"

    return name


# External Section End

# Special sentinel object to mark value/attribute as missing in previous/current


@dataclass(slots=True)
class ValueChange:
    previous: Any
    current: Any


@dataclass(slots=True)
class ConfigDifference:
    values: dict[LevelNames, ValueChange] = field(default_factory=dict)
    attributes: dict[LevelNames, ValueChange] = field(default_factory=dict)

    def __str__(self) -> str:
        # todo
        ...


def find_config_difference(previous: "ConfigData", current: "ConfigData", schema: "ConfigSchema") -> ConfigDifference:
    diff = ConfigDifference()

    _fill_values_diff_at_level(level=(), diff=diff, previous=previous.values, current=current.values, schema=schema)
    _fill_attributes_diff(diff=diff, previous=previous.attributes, current=current.attributes, schema=schema)

    return diff


def _fill_values_diff_at_level(
    level: LevelNames, diff: ConfigDifference, previous: dict, current: dict, schema: "ConfigSchema"
) -> None:
    missing = object()
    for key, cur_value in current.items():
        level_names = (*level, key)
        prev_value = previous.get(key, missing)

        if prev_value is missing:
            # there may be collision between two None's, but for now we'll consider it a "special case"
            diff.values[level_names] = ValueChange(previous=None, current=cur_value)
            continue

        if cur_value == prev_value:
            continue

        if not (schema.is_group(level_names) and isinstance(prev_value, dict) and (isinstance(cur_value, dict))):
            diff.values[level_names] = ValueChange(previous=prev_value, current=cur_value)
            continue

        _fill_values_diff_at_level(diff=diff, level=level_names, previous=prev_value, current=cur_value, schema=schema)


def _fill_attributes_diff(diff: ConfigDifference, previous: dict, current: dict, schema: "ConfigSchema") -> None:
    missing = object()
    for full_name, cur_value in current.items():
        prev_value = previous.get(full_name, missing)
        if cur_value == prev_value:
            continue

        level_names = full_name_to_level_names(full_name)

        if prev_value is missing:
            prev_value = None

        diff.attributes[level_names] = ValueChange(previous=prev_value, current=cur_value)


class MergeStrategy(Protocol):
    # todo
    def __call__(
        self: Self,
        local_changes: ConfigDifference,
    ) -> "ConfigData": ...


def apply_local_changes(source: "ConfigData", changed: "ConfigData", remote: "ConfigData") -> "ConfigData":
    if source.id == remote.id:
        return changed

    # todo implement actual merge
    return changed


def apply_remote_changes(source: "ConfigData", changed: "ConfigData", remote: "ConfigData") -> "ConfigData":
    # todo implement actual merge
    return remote


class ConfigDiff: ...


def is_group_v2(attributes: dict) -> bool:
    # todo need to check group-like structures, because they are almost impossible to distinct from groups
    return (
        attributes.get("type") == "object"
        and attributes.get("additionalProperties") is False
        and attributes.get("default") == {}
    )


def is_activatable_v2(attributes: dict) -> bool:
    return (attributes["adcmMeta"].get("activation") or {}).get("isAllowChange", False)


def is_json_v2(attributes: dict) -> bool:
    return attributes.get("format") == "json"


class ConfigSchema:
    def __init__(self: Self, spec_as_jsonschema: dict) -> None:
        self._raw = spec_as_jsonschema

        self._jsons: set[LevelNames] = set()
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

            *group, own_level_name = level_names
            display_name = param_spec["title"]
            self._display_name_map[tuple(group), display_name] = own_level_name

    def _iterate_parameters(self: Self, object_schema: dict) -> Iterable[tuple[LevelNames, dict]]:
        for level_name, optional_attrs in object_schema["properties"].items():
            attributes = self._unwrap_optional(optional_attrs)
            is_group = is_group_v2(attributes)
            if is_group:
                for inner_level, inner_optional_attrs in self._iterate_parameters(attributes):
                    inner_attributes = self._unwrap_optional(inner_optional_attrs)
                    yield (level_name, *inner_level), inner_attributes
            else:
                yield level_name, attributes

    def _unwrap_optional(self: Self, attributes: dict) -> dict:
        if "oneOf" not in attributes:
            return attributes

        # bald search, a lot may fail,
        # but for more precise work with spec if require incapsulation in a separate handler class
        return next(entry for entry in attributes["oneOf"] if entry.get("type") != "null")


class ConfigData:
    __slots__ = ("id", "description", "_values", "_attributes")

    def __init__(self: Self, id: int, description: str, values: dict, attributes: dict) -> None:
        self.id = id
        self.description = description
        self._values = values
        self._attributes = attributes

    @classmethod
    def from_v2_response(cls: type[Self], data_in_v2_format: dict) -> Self:
        return cls(
            id=int(data_in_v2_format["id"]),
            description=str(data_in_v2_format["description"]),
            values=data_in_v2_format["config"],
            attributes=data_in_v2_format["adcmMeta"],
        )

    @property
    def values(self: Self) -> dict:
        return self._values

    @property
    def attributes(self: Self) -> dict:
        return self._attributes

    def get_value(self: Self, parameter: LevelNames) -> Any:
        return get_nested_config_value(config=self._values, level_names=parameter)

    def set_value[T](self: Self, parameter: LevelNames, value: T) -> T:
        return set_nested_config_value(config=self._values, level_names=parameter, value=value)

    def get_attribute(self: Self, parameter: LevelNames, attribute: str) -> Any:
        full_name = level_names_to_full_name(parameter)
        return self._attributes[full_name][attribute]

    def set_attribute[T](self: Self, parameter: LevelNames, attribute: str, value: T) -> T:
        full_name = level_names_to_full_name(parameter)
        self._attributes[full_name][attribute] = value
        return value


class _ConfigWrapper:
    __slots__ = ("_name", "_schema", "_data")

    def __init__(
        self: Self,
        name: LevelNames,
        data: ConfigData,
        schema: ConfigSchema,
    ) -> None:
        self._name = name
        self._schema = schema
        self._data = data


class _Group(_ConfigWrapper):
    @overload
    def __getitem__[ExpectedType: "ConfigEntry"](
        self: Self, item: tuple[AnyParameterName, type[ExpectedType]]
    ) -> ExpectedType: ...

    @overload
    def __getitem__(self: Self, item: AnyParameterName) -> "ConfigEntry": ...

    def __getitem__[ExpectedType: "ConfigEntry"](
        self: Self, item: AnyParameterName | tuple[AnyParameterName, type[ExpectedType]]
    ) -> "ConfigEntry":
        """
        Get config entry by given display name (or "technical" name).

        Item is either a string (name) or tuple with name on first position
        and type info at second.

        NOTE: types aren't checked, they are just helpers for users' type checking setups.
        """
        if isinstance(item, str):
            name = item
        else:
            name, *_ = item

        level_name = self._schema.get_level_name(group=self._name, display_name=name)
        if level_name is None:
            level_name = name

        parameter_full_name = (*self._name, level_name)

        class_ = Value
        if self._schema.is_group(parameter_full_name):
            class_ = ActivatableGroup if self._schema.is_activatable_group(parameter_full_name) else Group

        return class_(name=parameter_full_name, data=self._data, schema=self._schema)


class Value[T](_ConfigWrapper):
    @property
    def value(self: Self) -> T:
        # todo probably want to return read-only proxies for list/dict
        return self._data.get_value(parameter=self._name)

    def set(self: Self, value: Any) -> Self:
        self._data.set_value(parameter=self._name, value=value)
        return self


class Group(_Group): ...


class ActivatableGroup(Group):
    def activate(self: Self) -> Self:
        self._data.set_attribute(parameter=self._name, attribute="isActive", value=True)
        return self

    def deactivate(self: Self) -> Self:
        self._data.set_attribute(parameter=self._name, attribute="isActive", value=False)
        return self


class ConfigWrapper(Group):
    @property
    def config(self: Self) -> ConfigData:
        return self._data


type ConfigEntry = Value | Group | ActivatableGroup


class ObjectConfig:
    def __init__(
        self,
        config: ConfigData,
        schema: ConfigSchema,
        parent: AwareOfOwnPath,
        requester: Requester,
    ) -> None:
        self._schema = schema
        self._initial_config: ConfigData = self._parse_json_fields_inplace_safe(config)
        self._editable_config: ConfigWrapper = self._init_editable_config(self._initial_config)
        self._parent = parent
        self._requester = requester

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

    async def save(self: Self, description: str = "") -> Self:
        config_to_save = self._editable_config.config
        self._serialize_json_fields_inplace_safe(config_to_save)
        payload = {"description": description, "config": config_to_save.values, "adcmMeta": config_to_save.attributes}

        try:
            response = await self._requester.post(*self._parent.get_own_path(), "configs", data=payload)
        except RequesterError:
            # config isn't saved, no data update is in play,
            # returning "pre-saved" parsed values
            self._parse_json_fields_inplace_safe(config_to_save)
        else:
            new_config = ConfigData.from_v2_response(data_in_v2_format=response.as_dict())
            self._initial_config = self._parse_json_fields_inplace_safe(new_config)
            self.reset()

        return self

    async def refresh(self: Self, strategy: MergeStrategy = apply_local_changes) -> Self:
        remote_config = await self._retrieve_current_config()

        # todo get changes
        merged_config = strategy(local=self._editable_config.config, other=remote_config)

        self._initial_config = remote_config
        self._init_editable_config(source_config=merged_config)

        return self

    def __getitem__(self, item: AnyParameterName) -> ConfigEntry:
        return self._editable_config[item]

    # Public For Internal Use Only

    @property
    def config(self: Self) -> ConfigData:
        return self._editable_config.config

    # Private

    def _init_editable_config(self: Self, source_config: ConfigData) -> ConfigWrapper:
        # NOTE:
        #  This implementation implies that fields retrieved prior to this calle
        #  will have "working" `.set` methods, but in fact will "change nothing",
        #  which feels like correct behavior.
        self._editable_config = ConfigWrapper(data=deepcopy(source_config), schema=self._schema, name=())
        return self._editable_config

    def _parse_json_fields_inplace_safe(self: Self, config: ConfigData) -> ConfigData:
        return self._apply_to_all_json_fields(func=json.loads, when=lambda value: isinstance(value, str), config=config)

    def _serialize_json_fields_inplace_safe(self: Self, config: ConfigData) -> ConfigData:
        return self._apply_to_all_json_fields(func=json.dumps, when=lambda value: value is not None, config=config)

    def _apply_to_all_json_fields(
        self: Self, func: Callable, when: Callable[[Any], bool], config: ConfigData
    ) -> ConfigData:
        when = when
        for parameter_name in self._schema.json_fields:
            input_value = config.get_value(parameter_name)
            if when(input_value):
                parsed_value = func(input_value)
                config.set_value(parameter_name, parsed_value)

        return config

    async def _retrieve_current_config(self: Self) -> ConfigData:
        configs_path = (*self._parent.get_own_path(), "configs")

        history_response = await self._requester.get(*configs_path, query={"ordering": "-id", "limit": 5, "offset": 0})

        current_config_entry = get_current_config(results=history_response.as_dict()["results"])
        config_id = current_config_entry["id"]

        if config_id == self.id:
            return self._initial_config

        config_response = await self._requester.get(*configs_path, config_id)

        config_data = ConfigData.from_v2_response(data_in_v2_format=config_response.as_dict())

        return self._parse_json_fields_inplace_safe(config_data)


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
            # `-1` is the same as `0` in reverse order
            offset = abs(offset) - 1

        query = {"limit": 1, "offset": offset, "ordering": ordering}

        return await self._retrieve_config(query=query, choose_suitable_config=get_first_result)

    async def _ensure_schema(self: Self) -> ConfigSchema:
        if self._schema is not None:
            return self._schema

        response = await self._requester.get(*self._parent.get_own_path(), "config-schema")
        schema = ConfigSchema(spec_as_jsonschema=response.as_dict())
        self._schema = schema
        return schema

    async def _retrieve_config(
        self: Self, query: dict, choose_suitable_config: Callable[[list[dict]], dict]
    ) -> ObjectConfig:
        schema_task = asyncio.create_task(self._ensure_schema())

        path = (*self._parent.get_own_path(), "configs")

        config_records_response = await self._requester.get(*path, query=query)
        config_record = choose_suitable_config(config_records_response.as_dict()["results"])

        config_data_response = await self._requester.get(*path, config_record["id"])
        config_data = ConfigData.from_v2_response(data_in_v2_format=config_data_response.as_dict())

        schema = await schema_task

        return ObjectConfig(config=config_data, schema=schema, parent=self._parent, requester=self._requester)


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
