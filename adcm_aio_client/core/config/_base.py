from abc import abstractmethod
from copy import deepcopy
from dataclasses import dataclass
from functools import partial
from typing import Any, Callable, Iterable, Self, Union, overload
import json

from adcm_aio_client.core.config.errors import ParameterNotFoundError, ParameterTypeError, ParameterValueTypeError
from adcm_aio_client.core.config.types import (
    AnyParameterName,
    LevelNames,
    ParameterDisplayName,
    ParameterName,
    ParameterValueOrNone,
)

type SetValueCallback = Callable[[ParameterValueOrNone], Any]

type SetNestedValueCallback = Callable[[LevelNames, ParameterValueOrNone], Any]
type SetActivationStateCallback = Callable[[LevelNames, bool], Any]


@dataclass(slots=True)
class Callbacks:
    set_value: SetNestedValueCallback
    set_activation_attribute: SetActivationStateCallback


class ValueWrapper[InnerType: ParameterValueOrNone]:
    __slots__ = ("_value", "_set_value")

    def __init__(self: Self, value: InnerType, set_value_callback: SetValueCallback) -> None:
        self._value = value
        self._set_value = set_value_callback

    @property
    def value(self: Self) -> InnerType:
        return self._value

    def set(self: Self, value: InnerType) -> Self:
        self._set_value(value)
        self._value = value
        return self


class _ParametersGroup:
    def __init__(self: Self, spec: dict, callbacks: Callbacks, previous_levels: LevelNames = ()) -> None:
        # for now we assume it's always there
        self._spec = spec["properties"]
        self._previous_levels = previous_levels
        self._callbacks = callbacks
        self._names_mapping: dict[ParameterDisplayName, ParameterName] = {}
        self._wrappers: dict[ParameterName, ParameterWrapper] = {}

    @property
    @abstractmethod
    def _current_config_level(self: Self) -> dict: ...

    @overload
    def __getitem__[InnerType: ParameterValueOrNone](
        self: Self, item: tuple[AnyParameterName, type[ValueWrapper], type[InnerType]]
    ) -> ValueWrapper[InnerType]: ...

    @overload
    def __getitem__[ExpectedType: "ParameterWrapper"](
        self: Self, item: tuple[AnyParameterName, type[ExpectedType]]
    ) -> ExpectedType: ...

    @overload
    def __getitem__(self: Self, item: AnyParameterName) -> "ParameterWrapper": ...

    def __getitem__[ExpectedType: "ParameterWrapper", ValueType: ParameterValueOrNone](
        self: Self,
        item: AnyParameterName
        | tuple[AnyParameterName, type[ExpectedType]]
        | tuple[AnyParameterName, type[ValueWrapper], type[ValueType]],
    ) -> Union[ValueWrapper[ValueType], ExpectedType, "ParameterWrapper"]:
        check_internal = False
        internal_type = None
        if isinstance(item, str):
            key = item
            expected_type = None
        elif len(item) == 2:
            key, expected_type = item
        else:
            key, _, internal_type = item
            expected_type = ValueWrapper
            check_internal = True

        level_name = self._find_technical_name(display_name=key)
        if not level_name:
            level_name = key

        initialized_wrapper = self._wrappers.get(level_name)

        if not initialized_wrapper:
            if level_name not in self._current_config_level:
                message = f"No parameter with name {key} in configuration"
                raise ParameterNotFoundError(message)

            # todo probably worth making it like "get_initialized_wrapper" and hide all cache work in here
            initialized_wrapper = self._initialize_wrapper(level_name)

            self._wrappers[level_name] = initialized_wrapper

        if expected_type is not None:
            if not isinstance(initialized_wrapper, expected_type):
                message = f"Unexpected type of {key}: {type(initialized_wrapper)}.\nExpected: {expected_type}"
                raise ParameterTypeError(message)

            if check_internal:
                if not isinstance(initialized_wrapper, ValueWrapper):
                    message = f"Internal type can be checked only for ValueWrapper, not {type(initialized_wrapper)}"
                    raise ParameterTypeError(message)

                value = initialized_wrapper.value
                if internal_type is None:
                    if value is not None:
                        message = f"Value expected to be None, not {value}"
                        raise ParameterValueTypeError(message)
                elif not isinstance(value, internal_type):
                    message = f"Unexpected type of value of {key}: {type(value)}.\nExpected: {internal_type}"
                    raise ParameterValueTypeError(message)

        return initialized_wrapper

    def _find_technical_name(self: Self, display_name: ParameterDisplayName) -> ParameterName | None:
        cached_name = self._names_mapping.get(display_name)
        if cached_name:
            return cached_name

        for name, parameter_data in self._spec.items():
            if parameter_data.get("title") == display_name:
                self._names_mapping[display_name] = name
                return name

        return None

    def _get_parameter_spec(self: Self, name: ParameterName, parameters_spec: dict | None = None) -> dict:
        value = (parameters_spec or self._spec)[name]
        if "oneOf" not in value:
            return value

        # bald search, a lot may fail,
        # but for more precise work with spec if require incapsulation in a separate handler class
        return next(entry for entry in value["oneOf"] if entry.get("type") != "null")

    def _parameter_is_group(self: Self, parameter_spec: dict) -> bool:
        return (
            # todo need to check group-like structures, because they are almost impossible to distinct from groups
            parameter_spec.get("type") == "object"
            and parameter_spec.get("additionalProperties") is False
            and parameter_spec.get("default") == {}
        )

    def _initialize_wrapper(self: Self, name: ParameterName) -> "ParameterWrapper":
        value = self._current_config_level[name]
        spec = self._get_parameter_spec(name=name)

        is_group = isinstance(value, dict) and self._parameter_is_group(parameter_spec=spec)

        if is_group:
            # value for groups isn't copied,
            # because there isn't public interface for accessing it + they can be quite huge
            level_data = value
            previous_levels = (*self._previous_levels, name)

            is_activatable = (spec["adcmMeta"].get("activation") or {}).get("isAllowChange")
            if is_activatable:
                return ActivatableGroupWrapper(
                    config_level_data=level_data, spec=spec, callbacks=self._callbacks, previous_levels=previous_levels
                )

            return RegularGroupWrapper(
                config_level_data=level_data, spec=spec, callbacks=self._callbacks, previous_levels=previous_levels
            )

        if isinstance(value, (dict, list)):
            # simple failsafe for direct `value` edit
            value = deepcopy(value)

        set_value_callback = partial(self._callbacks.set_value, (*self._previous_levels, name))

        return ValueWrapper(value=value, set_value_callback=set_value_callback)


type ParameterWrapper = ValueWrapper | RegularGroupWrapper | ActivatableGroupWrapper


class RegularGroupWrapper(_ParametersGroup):
    def __init__(
        self: Self, config_level_data: dict, spec: dict, callbacks: Callbacks, previous_levels: LevelNames
    ) -> None:
        super().__init__(spec=spec, callbacks=callbacks, previous_levels=previous_levels)
        self._data = config_level_data

    @property
    def _current_config_level(self: Self) -> dict:
        return self._data


class ActivatableGroupWrapper(RegularGroupWrapper):
    def activate(self: Self) -> Self:
        # silencing check, because protocol is position-based
        self._callbacks.set_activation_attribute(self._previous_levels, True)  # noqa: FBT003
        return self

    def deactivate(self: Self) -> Self:
        # silencing check, because protocol is position-based
        self._callbacks.set_activation_attribute(self._previous_levels, False)  # noqa: FBT003
        return self


class EditableConfig(_ParametersGroup):
    def __init__(
        self: Self,
        data: dict,
        spec: dict,
    ) -> None:
        super().__init__(
            spec=spec,
            callbacks=Callbacks(
                set_value=self._set_parameter_value, set_activation_attribute=self._set_activation_attribute
            ),
        )

        self._initial_data = data
        self._json_fields: set[tuple[ParameterName, ...]] = set()
        self._convert_payload_formated_json_fields_inplace(self._spec, self._initial_data["config"], prefix=())

        self._changed_data = None

    def to_payload(self: Self) -> dict:
        payload = deepcopy(self._current_data)
        self._convert_json_fields_to_payload_format_inplace(payload["config"])
        return payload

    @property
    def _current_data(self: Self) -> dict:
        if self._changed_data is not None:
            return self._changed_data

        return self._initial_data

    @property
    def _current_config_level(self: Self) -> dict:
        return self._current_data["config"]

    def _set_parameter_value(self: Self, names: LevelNames, value: ParameterValueOrNone) -> None:
        data = self._ensure_data_prepared_for_change()
        set_nested_config_value(config=data["config"], level_names=names, value=value)

    # protocol is position-based now, so required to silence check
    def _set_activation_attribute(self: Self, names: LevelNames, value: bool) -> None:  # noqa: FBT001
        data = self._ensure_data_prepared_for_change()

        attribute_name = level_names_to_full_name(names)

        try:
            data["adcmMeta"][attribute_name]["isActive"] = value
        except KeyError as e:
            message = (
                f"Failed to change activation attribute of {attribute_name}: not found in meta.\n"
                "Either income data is incomplete or callback for this function is prepared incorrectly."
            )
            raise RuntimeError(message) from e

    def _ensure_data_prepared_for_change(self: Self) -> dict:
        if self._changed_data is None:
            self._changed_data = deepcopy(self._initial_data)

        return self._changed_data

    def _convert_payload_formated_json_fields_inplace(
        self: Self, parameters_spec: dict, data: dict, prefix: LevelNames
    ) -> None:
        for key, value in data.items():
            parameter_spec = self._get_parameter_spec(key, parameters_spec=parameters_spec)
            level_names = (*prefix, key)
            if parameter_spec.get("format") == "json":
                set_nested_config_value(data, (key,), self._json_value_from_payload_format(value))
                self._json_fields.add(level_names)
            elif isinstance(value, dict) and self._parameter_is_group(parameter_spec):
                self._convert_payload_formated_json_fields_inplace(
                    parameters_spec=parameters_spec[key]["properties"], data=value, prefix=level_names
                )

    def _convert_json_fields_to_payload_format_inplace(self: Self, data: dict) -> None:
        for json_field_name in self._json_fields:
            change_nested_config_value(data, json_field_name, self._json_value_to_payload_format)

    def _json_value_to_payload_format(self: Self, value: ParameterValueOrNone) -> str | None:
        if value is None:
            return None

        return json.dumps(value)

    def _json_value_from_payload_format(self: Self, value: str | None) -> ParameterValueOrNone:
        if isinstance(value, str):
            return json.loads(value)

        return None


# FOREIGN SECTION
#
# these functions are heavily inspired by configuration rework in ADCM (ADCM-6034)

ROOT_PREFIX = "/"


def set_nested_config_value[T](config: dict[str, Any], level_names: LevelNames, value: T) -> T:
    group, level_name = get_group_with_value(config=config, level_names=level_names)
    group[level_name] = value
    return value


def change_nested_config_value[T](config: dict[str, Any], level_names: LevelNames, func: Callable[[Any], T]) -> T:
    group, level_name = get_group_with_value(config=config, level_names=level_names)
    group[level_name] = func(group[level_name])
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
