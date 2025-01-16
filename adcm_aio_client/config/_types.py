from abc import ABC
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import reduce
from typing import Any, NamedTuple, Protocol, Self

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
class ParameterChange:
    previous: dict
    current: dict


def recursive_defaultdict() -> defaultdict:
    return defaultdict(recursive_defaultdict)


class ConfigDifference:
    __slots__ = ("_diff",)

    def __init__(self: Self, diff: dict[LevelNames, ParameterChange]) -> None:
        self._diff = diff

    def __str__(self: Self) -> str:
        if not self._diff:
            return "No Changes"

        result = recursive_defaultdict()

        for names, change in self._diff.items():
            changes_repr = self._prepare_change(previous=change.previous, current=change.current)

            if len(names) == 1:
                result[names[0]] = changes_repr
                continue

            *groups, name = names
            group_node = reduce(dict.__getitem__, groups, result)
            group_node[name] = changes_repr

        # get rid of `defaultdict` in favor of `dict`
        # may be not optimal
        print_ready_dict = self._simplify_dict(result)

        return str(print_ready_dict)

    def _prepare_change(self: Self, previous: Any, current: Any) -> tuple | dict:  # noqa: ANN401
        if not (isinstance(previous, dict) and isinstance(current, dict)):
            return (previous, current)

        dict_diff = {}

        for key, cur_value in current.items():
            prev_value = previous.get(key)
            if prev_value != cur_value:
                dict_diff[key] = self._prepare_change(previous=prev_value, current=cur_value)

        missing_in_current = set(previous.keys()).difference(current.keys())
        for key in missing_in_current:
            dict_diff[key] = self._prepare_change(previous=previous[key], current=None)

        return dict_diff

    def _simplify_dict(self: Self, dd: dict) -> dict:
        simplified = {}

        for k, v in dd.items():
            if isinstance(v, dict):
                v = self._simplify_dict(v)

            simplified[k] = v

        return simplified


class ConfigSchema:
    def __init__(self: Self, spec_as_jsonschema: dict) -> None:
        self._raw = spec_as_jsonschema

        self._jsons: set[LevelNames] = set()
        self._groups: set[LevelNames] = set()
        self._activatable_groups: set[LevelNames] = set()
        self._invisible_fields: set[LevelNames] = set()
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

    def is_invisible(self: Self, parameter_name: LevelNames) -> bool:
        return parameter_name in self._invisible_fields

    def is_visible_parameter(self: Self, parameter_name: LevelNames) -> bool:
        return parameter_name in self._param_map and not self.is_invisible(parameter_name)

    def get_level_name(self: Self, group: LevelNames, display_name: ParameterDisplayName) -> ParameterName | None:
        key = (group, display_name)
        return self._display_name_map.get(key)

    def get_default(self: Self, parameter_name: LevelNames) -> Any:  # noqa: ANN401
        param_spec = self._param_map[parameter_name]
        if not self.is_group(parameter_name):
            return param_spec.get("default", None)

        return {child_name: self.get_default((*parameter_name, child_name)) for child_name in param_spec["properties"]}

    def iterate_parameters(self: Self) -> Iterable[tuple[LevelNames, dict]]:
        yield from self._iterate_parameters(object_schema=self._raw)

    def _iterate_parameters(self: Self, object_schema: dict) -> Iterable[tuple[LevelNames, dict]]:
        for level_name, optional_attrs in object_schema["properties"].items():
            attributes = self._unwrap_optional(optional_attrs)

            yield (level_name,), attributes

            if is_group_v2(attributes):
                for inner_level, inner_optional_attrs in self._iterate_parameters(attributes):
                    inner_attributes = self._unwrap_optional(inner_optional_attrs)
                    yield (level_name, *inner_level), inner_attributes

    def _analyze_schema(self: Self) -> None:
        for level_names, param_spec in self._iterate_parameters(object_schema=self._raw):
            if is_group_v2(param_spec):
                self._groups.add(level_names)

                if is_activatable_v2(param_spec):
                    self._activatable_groups.add(level_names)

            elif is_json_v2(param_spec):
                self._jsons.add(level_names)

            if param_spec.get("adcmMeta", {}).get("isInvisible"):
                self._invisible_fields.add(level_names)

            *group, own_level_name = level_names
            display_name = param_spec["title"]
            self._display_name_map[tuple(group), display_name] = own_level_name
            self._param_map[level_names] = param_spec

    def _retrieve_name_type_mapping(self: Self) -> dict[LevelNames, str]:
        return {
            level_names: param_spec.get("type", "enum")
            for level_names, param_spec in self._iterate_parameters(object_schema=self._raw)
        }

    def _unwrap_optional(self: Self, attributes: dict) -> dict:
        if "oneOf" not in attributes:
            return attributes

        # bald search, a lot may fail,
        # but for more precise work with spec if require incapsulation in a separate handler class
        return next(entry for entry in attributes["oneOf"] if entry.get("type") != "null")


def is_group_v2(attributes: dict) -> bool:
    return attributes.get("type") == "object" and attributes.get("additionalProperties") is False


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
