from abc import ABC
from collections import defaultdict
from dataclasses import dataclass, field
from functools import reduce
from typing import Any, Callable, Iterable, NamedTuple, Protocol, Self

# External Section
# these functions are heavily inspired by configuration rework in ADCM (ADCM-6034)


type ParameterName = str
type ParameterDisplayName = str
type AnyParameterName = ParameterName | ParameterDisplayName

type LevelNames = tuple[ParameterName, ...]
type ParameterFullName = str
"""
Name inclusing all level names joined with (and prefixed by) `/`
"""

ROOT_PREFIX = "/"


def set_nested_config_value[T](config: dict[str, Any], level_names: LevelNames, value: T) -> T:
    group, level_name = get_group_with_value(config=config, level_names=level_names)
    group[level_name] = value
    return value


def change_nested_config_value[T](config: dict[str, Any], level_names: LevelNames, func: Callable[[Any], T]) -> T:
    group, level_name = get_group_with_value(config=config, level_names=level_names)
    group[level_name] = func(group[level_name])
    return group[level_name]


def get_nested_config_value(config: dict[str, Any], level_names: LevelNames) -> Any:  # noqa: ANN401
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


def full_name_to_level_names(full: ParameterFullName) -> tuple[ParameterName, ...]:
    return tuple(filter(bool, full.split("/")))


def ensure_full_name(name: str) -> str:
    if not name.startswith(ROOT_PREFIX):
        return f"{ROOT_PREFIX}{name}"

    return name


# External Section End


class GenericConfigData(ABC):  # noqa: B024
    __slots__ = ("_values", "_attributes")

    def __init__(self: Self, values: dict, attributes: dict) -> None:
        self._values = values
        self._attributes = attributes

    @property
    def values(self: Self) -> dict:
        return self._values

    @property
    def attributes(self: Self) -> dict:
        return self._attributes

    def get_value(self: Self, parameter: LevelNames) -> Any:  # noqa: ANN401
        return get_nested_config_value(config=self._values, level_names=parameter)

    def set_value[T](self: Self, parameter: LevelNames, value: T) -> T:
        return set_nested_config_value(config=self._values, level_names=parameter, value=value)

    def get_attribute(self: Self, parameter: LevelNames, attribute: str) -> bool:
        full_name = level_names_to_full_name(parameter)
        return self._attributes[full_name][attribute]

    def set_attribute(self: Self, parameter: LevelNames, attribute: str, value: bool) -> bool:  # noqa: FBT001
        full_name = level_names_to_full_name(parameter)
        self._attributes[full_name][attribute] = value
        return value


class ActionConfigData(GenericConfigData):
    __slots__ = GenericConfigData.__slots__


class ConfigData(GenericConfigData):
    __slots__ = ("id", "description", "_values", "_attributes")

    def __init__(self: Self, id: int, description: str, values: dict, attributes: dict) -> None:  # noqa: A002
        self.id = id
        self.description = description
        super().__init__(values=values, attributes=attributes)

    @classmethod
    def from_v2_response(cls: type[Self], data_in_v2_format: dict) -> Self:
        return cls(
            id=int(data_in_v2_format["id"]),
            description=str(data_in_v2_format["description"]),
            values=data_in_v2_format["config"],
            attributes=data_in_v2_format["adcmMeta"],
        )


@dataclass(slots=True)
class ValueChange:
    previous: Any
    current: Any


def recursive_defaultdict() -> defaultdict:
    return defaultdict(recursive_defaultdict)


@dataclass(slots=True)
class ConfigDifference:
    schema: "ConfigSchema"
    values: dict[LevelNames, ValueChange] = field(default_factory=dict)
    attributes: dict[LevelNames, ValueChange] = field(default_factory=dict)

    @property
    def is_empty(self: Self) -> bool:
        return not bool(self.values or self.attributes)

    def __str__(self: Self) -> str:
        values_nested = self._to_nested_dict(self.values)
        attributes_nested = self._to_nested_dict(self.attributes)

        if not (values_nested or attributes_nested):
            return "No Changes"

        values_repr = f"Changed Values:\n{values_nested}" if values_nested else ""
        attributes_repr = f"Changed Attributes:\n{attributes_nested}" if attributes_nested else ""

        return "\n\n".join((values_repr, attributes_repr))

    def _to_nested_dict(self: Self, changes: dict[LevelNames, ValueChange]) -> dict:
        result = recursive_defaultdict()

        for names, change in changes.items():
            changes_tuple = (change.previous, change.current)

            if len(names) == 1:
                result[names[0]] = changes_tuple
                continue

            *groups, name = names
            group_node = reduce(dict.__getitem__, groups, result)
            group_node[name] = changes_tuple

        return result


class ConfigSchema:
    def __init__(self: Self, spec_as_jsonschema: dict) -> None:
        self._raw = spec_as_jsonschema

        self._jsons: set[LevelNames] = set()
        self._groups: set[LevelNames] = set()
        self._activatable_groups: set[LevelNames] = set()
        self._display_name_map: dict[tuple[LevelNames, ParameterDisplayName], ParameterName] = {}
        self._param_map: dict[LevelNames, dict] = {}

        self._analyze_schema()

    def __eq__(self: Self, value: object) -> bool:
        if not isinstance(value, ConfigSchema):
            return NotImplemented

        this_name_type_mapping = self._retrieve_name_type_mapping()
        other_name_type_mapping = value._retrieve_name_type_mapping()

        return this_name_type_mapping == other_name_type_mapping

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

    def get_default(self: Self, parameter_name: LevelNames) -> Any:  # noqa: ANN401
        param_spec = self._param_map[parameter_name]
        if not self.is_group(parameter_name):
            return param_spec.get("default", None)

        return {child_name: self.get_default((*parameter_name, child_name)) for child_name in param_spec["properties"]}

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
            self._param_map[level_names] = param_spec

    def _retrieve_name_type_mapping(self: Self) -> dict[LevelNames, str]:
        return {
            level_names: param_spec.get("type", "enum")
            for level_names, param_spec in self._iterate_parameters(object_schema=self._raw)
        }

    def _iterate_parameters(self: Self, object_schema: dict) -> Iterable[tuple[LevelNames, dict]]:
        for level_name, optional_attrs in object_schema["properties"].items():
            attributes = self._unwrap_optional(optional_attrs)

            yield (level_name,), attributes

            if is_group_v2(attributes):
                for inner_level, inner_optional_attrs in self._iterate_parameters(attributes):
                    inner_attributes = self._unwrap_optional(inner_optional_attrs)
                    yield (level_name, *inner_level), inner_attributes

    def _unwrap_optional(self: Self, attributes: dict) -> dict:
        if "oneOf" not in attributes:
            return attributes

        # bald search, a lot may fail,
        # but for more precise work with spec if require incapsulation in a separate handler class
        return next(entry for entry in attributes["oneOf"] if entry.get("type") != "null")


def is_group_v2(attributes: dict) -> bool:
    # todo need to check group-like structures, because they are almost impossible to distinct from groups
    return (
        attributes.get("type") == "object" and attributes.get("additionalProperties") is False
        #        and attributes.get("default") == {}
    )


def is_activatable_v2(attributes: dict) -> bool:
    return (attributes["adcmMeta"].get("activation") or {}).get("isAllowChange", False)


def is_json_v2(attributes: dict) -> bool:
    return attributes.get("format") == "json"


class LocalConfigs(NamedTuple):
    initial: ConfigData
    changed: ConfigData


class ConfigRefreshStrategy(Protocol):
    def __call__(self: Self, local: LocalConfigs, remote: ConfigData, schema: ConfigSchema) -> ConfigData:
        """
        `remote` may be changed according to strategy, so it shouldn't be "read-only"/"initial"
        """
        ...
