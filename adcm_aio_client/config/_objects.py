from collections.abc import Callable, Coroutine
from copy import deepcopy
from functools import partial
from typing import Any, Protocol, Self, overload
import json
import asyncio

from adcm_aio_client._types import AwareOfOwnPath, WithRequesterProperty
from adcm_aio_client.config import apply_local_changes
from adcm_aio_client.config._operations import find_config_difference
from adcm_aio_client.config._types import (
    ActionConfigData,
    AnyParameterName,
    ConfigData,
    ConfigDifference,
    ConfigRefreshStrategy,
    ConfigSchema,
    GenericConfigData,
    LevelNames,
    LocalConfigs,
)
from adcm_aio_client.errors import ConfigComparisonError, ConfigNoParameterError, RequesterError


class ConfigOwner(WithRequesterProperty, AwareOfOwnPath, Protocol): ...


# Config Entries Wrappers


class _ConfigWrapper:
    __slots__ = ("_name", "_schema", "_data")

    def __init__(
        self: Self,
        name: LevelNames,
        data: GenericConfigData,
        schema: ConfigSchema,
    ) -> None:
        self._name = name
        self._schema = schema
        self._data = data

    def _on_data_change(self: Self) -> None:
        pass


class _Group(_ConfigWrapper):
    __slots__ = ("_name", "_schema", "_data", "_wrappers_cache")

    def __init__(self: Self, name: LevelNames, data: ConfigData, schema: ConfigSchema) -> None:
        super().__init__(name, data, schema)
        self._wrappers_cache = {}

    def _find_and_wrap_config_entry[ValueW: _ConfigWrapper, GroupW: _ConfigWrapper, AGroupW: _ConfigWrapper](
        self: Self,
        item: AnyParameterName | tuple[AnyParameterName, type[ValueW | GroupW | AGroupW]],
        value_class: type[ValueW],
        group_class: type[GroupW],
        a_group_class: type[AGroupW],
    ) -> ValueW | GroupW | AGroupW:
        if isinstance(item, str):
            name = item
        else:
            name, *_ = item

        level_name = self._schema.get_level_name(group=self._name, display_name=name)
        if level_name is None:
            level_name = name

        cached_wrapper = self._wrappers_cache.get(level_name)
        if cached_wrapper:
            return cached_wrapper

        parameter_full_name = (*self._name, level_name)

        if not self._schema.is_visible_parameter(parameter_full_name):
            message = f"No parameter named {name}"
            if self._name:
                message = f"{message} in group {'/'.join(self._name)}"
            raise ConfigNoParameterError(message)

        class_ = value_class
        if self._schema.is_group(parameter_full_name):
            class_ = a_group_class if self._schema.is_activatable_group(parameter_full_name) else group_class

        wrapper = class_(name=parameter_full_name, data=self._data, schema=self._schema)

        self._wrappers_cache[level_name] = wrapper

        return wrapper

    def _on_data_change(self: Self) -> None:
        # need to drop caches when data is changed,
        # because each entry may already point to a different data
        # and return incorrect nodes for a search (=> can't be edited too)
        self._wrappers_cache = {}


class Parameter[T](_ConfigWrapper):
    @property
    def value(self: Self) -> T:
        # todo probably want to return read-only proxies for list/dict
        try:
            return self._data.get_value(parameter=self._name)
        except (TypeError, KeyError):
            if len(self._name) == 1:
                # not in any sort of group, should continue with exception
                raise

            return self._schema.get_default(self._name)

    def set(self: Self, value: Any) -> Self:  # noqa: ANN401
        try:
            self._data.set_value(parameter=self._name, value=value)
        except (TypeError, KeyError):
            if len(self._name) == 1:
                # not in any sort of group, should continue with exception
                raise

            self._ensure_parent_groups_are_dicts()
            self._data.set_value(parameter=self._name, value=value)

        return self

    def _ensure_parent_groups_are_dicts(self: Self) -> None:
        *groups, _ = self._name
        path = ()
        for group in groups:
            group_name = (*path, group)

            try:
                value = self._data.get_value(group_name)
            except KeyError:
                value = None

            if value is None:
                self._data.set_value(group_name, {})

            path = group_name


class _Desyncable(_ConfigWrapper):
    _SYNC_ATTR = "isSynchronized"

    def sync(self: Self) -> Self:
        return self._set(value=True)

    def desync(self: Self) -> Self:
        return self._set(value=False)

    def _set(self: Self, *, value: bool) -> Self:
        try:
            self._data.set_attribute(parameter=self._name, attribute=self._SYNC_ATTR, value=value)
        except KeyError:
            if len(self._name) == 1:
                # not a group, attribute have to exist
                raise

            # we assume that this element is a structure,
            # so we have to (de)sync it
            closest_attribute = self._find_closest_attribute(self._name)
            print(closest_attribute)
            if closest_attribute is None or not self._schema.is_group(closest_attribute):
                # it's not a structure-based group
                raise

            self._data.set_attribute(parameter=closest_attribute, attribute=self._SYNC_ATTR, value=value)

        return self

    def _find_closest_attribute(self: Self, name: LevelNames) -> LevelNames | None:
        if not name:
            return None

        prev_name = tuple(name[:-1])

        try:
            self._data.get_attribute(parameter=prev_name, attribute=self._SYNC_ATTR)
        except KeyError:
            return self._find_closest_attribute(prev_name)

        return prev_name


class ParameterHG[T](_Desyncable, Parameter[T]):
    def set(self: Self, value: Any) -> Self:  # noqa: ANN401
        super().set(value)
        self.desync()
        return self


class ParameterGroup(_Group):
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
        return self._find_and_wrap_config_entry(
            item=item, value_class=Parameter, group_class=ParameterGroup, a_group_class=ActivatableParameterGroup
        )


class ParameterGroupHG(_Group):
    @overload
    def __getitem__[ExpectedType: "ConfigEntryHG"](
        self: Self, item: tuple[AnyParameterName, type[ExpectedType]]
    ) -> ExpectedType: ...

    @overload
    def __getitem__(self: Self, item: AnyParameterName) -> "ConfigEntryHG": ...

    def __getitem__[ExpectedType: "ConfigEntryHG"](
        self: Self, item: AnyParameterName | tuple[AnyParameterName, type[ExpectedType]]
    ) -> "ConfigEntryHG":
        """
        Get config entry by given display name (or "technical" name).

        Item is either a string (name) or tuple with name on first position
        and type info at second.

        NOTE: types aren't checked, they are just helpers for users' type checking setups.
        """
        return self._find_and_wrap_config_entry(
            item=item,
            value_class=ParameterHG,
            group_class=ParameterGroupHG,
            a_group_class=ActivatableParameterGroupHG,
        )


class _Activatable(_Group):
    def activate(self: Self) -> Self:
        self._data.set_attribute(parameter=self._name, attribute="isActive", value=True)
        return self

    def deactivate(self: Self) -> Self:
        self._data.set_attribute(parameter=self._name, attribute="isActive", value=False)
        return self


class ActivatableParameterGroup(_Activatable, ParameterGroup): ...


class ActivatableParameterGroupHG(_Desyncable, _Activatable, ParameterGroup):
    def activate(self: Self) -> Self:
        super().activate()
        self.desync()
        return self

    def deactivate(self: Self) -> Self:
        super().deactivate()
        self.desync()
        return self


class _ConfigWrapperCreator[T: GenericConfigData](_ConfigWrapper):
    @property
    def config(self: Self) -> T:
        return self._data

    def change_data(self: Self, new_data: T) -> T:
        self._data = new_data
        self._on_data_change()
        return self._data


class ActionConfigWrapper(ParameterGroup, _ConfigWrapperCreator[ActionConfigData]): ...


class ObjectConfigWrapper(ParameterGroup, _ConfigWrapperCreator[ConfigData]): ...


class HostGroupConfigWrapper(ParameterGroupHG, _ConfigWrapperCreator[ConfigData]): ...


type ConfigEntry = Parameter | ParameterGroup | ActivatableParameterGroup
type ConfigEntryHG = ParameterHG | ParameterGroupHG | ActivatableParameterGroupHG

# API Objects


class _GeneralConfig[C: GenericConfigData, T: _ConfigWrapperCreator]:
    __slots__ = ("_schema", "_parent", "_initial_config", "_current_config", "_wrapper_class")

    _wrapper_class: type[T]

    def __init__(self: Self, config: C, schema: ConfigSchema, parent: ConfigOwner) -> None:
        self._schema = schema
        self._initial_config: C = self._parse_json_fields_inplace_safe(config)
        self._current_config: T = self._wrapper_class(data=deepcopy(self._initial_config), schema=self._schema, name=())
        self._parent = parent

    # Public Interface (for End User)

    def reset(self: Self) -> Self:
        self._current_config.change_data(new_data=deepcopy(self._initial_config))
        return self

    def difference(self: Self, other: Self, *, other_is_previous: bool = True) -> ConfigDifference:
        if self.schema != other.schema:
            self_repr = str(self)
            other_repr = str(other)
            message = f"Schema of configuration {other_repr} doesn't match schema of {self_repr}"
            raise ConfigComparisonError(message)

        if other_is_previous:
            previous = other
            current = self
        else:
            previous = self
            current = other

        full_diff = find_config_difference(previous=previous.data, current=current.data, schema=self._schema)
        only_visible_fields = {k: v for k, v in full_diff.items() if self._schema.is_visible_parameter(k)}
        return ConfigDifference(diff=only_visible_fields)

    # Public For Internal Use Only

    @property
    def schema(self: Self) -> ConfigSchema:
        return self._schema

    @property
    def data(self: Self) -> ConfigData:
        return self._current_config.config

    # Private
    def _parse_json_fields_inplace_safe(self: Self, config: C) -> C:
        return self._apply_to_all_json_fields(func=json.loads, when=lambda value: isinstance(value, str), config=config)

    def _serialize_json_fields_inplace_safe(self: Self, config: C) -> C:
        return self._apply_to_all_json_fields(func=json.dumps, when=lambda value: value is not None, config=config)

    def _apply_to_all_json_fields(self: Self, func: Callable, when: Callable[[Any], bool], config: C) -> C:
        for parameter_name in self._schema.json_fields:
            input_value = config.get_value(parameter_name)
            if when(input_value):
                parsed_value = func(input_value)
                config.set_value(parameter_name, parsed_value)

        return config


class _SaveableConfig[T: _ConfigWrapperCreator](_GeneralConfig[ConfigData, T]):
    def __init__(self: Self, config: ConfigData, schema: ConfigSchema, parent: ConfigOwner) -> None:
        super().__init__(config=config, schema=schema, parent=parent)

    @property
    def id(self: Self) -> int:
        return self._initial_config.id

    @property
    def description(self: Self) -> str:
        return self._initial_config.description

    async def refresh(self: Self, strategy: ConfigRefreshStrategy = apply_local_changes) -> Self:
        remote_config = await retrieve_current_config(
            parent=self._parent, get_schema=partial(retrieve_schema, parent=self._parent), as_type=self.__class__
        )
        if self.schema != remote_config.schema:
            message = "Can't refresh configuration after upgrade: schema is different for local and remote configs"
            raise ConfigComparisonError(message)

        local = LocalConfigs(initial=self._initial_config, changed=self._current_config.config)
        merged_config = strategy(local=local, remote=remote_config.data, schema=self._schema)

        self._initial_config = remote_config.data
        self._current_config.change_data(new_data=merged_config)

        return self

    async def save(self: Self, description: str = "") -> Self:
        config_to_save = self._current_config.config
        self._serialize_json_fields_inplace_safe(config_to_save)
        payload = {"description": description, "config": config_to_save.values, "adcmMeta": config_to_save.attributes}

        try:
            response = await self._parent.requester.post(*self._parent.get_own_path(), "configs", data=payload)
        except RequesterError:
            # config isn't saved, no data update is in play,
            # returning "pre-saved" parsed values
            self._parse_json_fields_inplace_safe(config_to_save)

            raise
        else:
            new_config = ConfigData.from_v2_response(data_in_v2_format=response.as_dict())
            self._initial_config = self._parse_json_fields_inplace_safe(new_config)
            self.reset()

        return self

    async def _retrieve_current_config(self: Self) -> ConfigData:
        configs_path = (*self._parent.get_own_path(), "configs")

        history_response = await self._parent.requester.get(
            *configs_path, query={"ordering": "-id", "limit": 5, "offset": 0}
        )

        current_config_entry = get_current_config(results=history_response.as_dict()["results"])
        config_id = current_config_entry["id"]

        if config_id == self.id:
            return self._initial_config

        config_response = await self._parent.requester.get(*configs_path, config_id)

        config_data = ConfigData.from_v2_response(data_in_v2_format=config_response.as_dict())

        return self._parse_json_fields_inplace_safe(config_data)


class ActionConfig(_GeneralConfig[ActionConfigData, ActionConfigWrapper]):
    _wrapper_class = ActionConfigWrapper

    @overload
    def __getitem__[ExpectedType: ConfigEntry](
        self: Self, item: tuple[AnyParameterName, type[ExpectedType]]
    ) -> ExpectedType: ...

    @overload
    def __getitem__(self: Self, item: AnyParameterName) -> ConfigEntry: ...

    def __getitem__[ExpectedType: ConfigEntry](
        self: Self, item: AnyParameterName | tuple[AnyParameterName, type[ExpectedType]]
    ) -> ConfigEntry:
        return self._current_config[item]

    def _to_payload(self: Self) -> dict:
        # don't want complexity of regular config with rollbacks on failure
        config_to_save = deepcopy(self._current_config.config)
        self._serialize_json_fields_inplace_safe(config_to_save)
        return {"config": config_to_save.values, "adcmMeta": config_to_save.attributes}


class ObjectConfig(_SaveableConfig[ObjectConfigWrapper]):
    _wrapper_class = ObjectConfigWrapper

    # todo fix typing copy-paste
    @overload
    def __getitem__[ExpectedType: ConfigEntry](
        self: Self, item: tuple[AnyParameterName, type[ExpectedType]]
    ) -> ExpectedType: ...

    @overload
    def __getitem__(self: Self, item: AnyParameterName) -> ConfigEntry: ...

    def __getitem__[ExpectedType: ConfigEntry](
        self: Self, item: AnyParameterName | tuple[AnyParameterName, type[ExpectedType]]
    ) -> ConfigEntry:
        return self._current_config[item]


class HostGroupConfig(_SaveableConfig[HostGroupConfigWrapper]):
    _wrapper_class = HostGroupConfigWrapper

    @overload
    def __getitem__[ExpectedType: ConfigEntryHG](
        self: Self, item: tuple[AnyParameterName, type[ExpectedType]]
    ) -> ExpectedType: ...

    @overload
    def __getitem__(self: Self, item: AnyParameterName) -> ConfigEntryHG: ...

    def __getitem__[ExpectedType: ConfigEntryHG](
        self: Self, item: AnyParameterName | tuple[AnyParameterName, type[ExpectedType]]
    ) -> "ConfigEntryHG":
        return self._current_config[item]


class ConfigHistoryNode[T: _SaveableConfig]:
    def __init__(self: Self, parent: ConfigOwner, as_type: type[T]) -> None:
        self._schema: ConfigSchema | None = None
        self._parent = parent
        self._config_type = as_type

    async def current(self: Self) -> T:
        return await retrieve_current_config(
            parent=self._parent, get_schema=self._ensure_schema, as_type=self._config_type
        )

    async def __getitem__(self: Self, position: int) -> T:
        # since we don't have date in here, we sort by id
        ordering = "id"
        offset = position
        if offset < 0:
            ordering = "-id"
            # `-1` is the same as `0` in reverse order
            offset = abs(offset) - 1

        query = {"limit": 1, "offset": offset, "ordering": ordering}

        return await retrieve_config(
            parent=self._parent,
            get_schema=self._ensure_schema,
            query=query,
            choose_suitable_config=get_first_result,
            as_type=self._config_type,
        )

    async def _ensure_schema(self: Self) -> ConfigSchema:
        if self._schema is not None:
            return self._schema

        self._schema = await retrieve_schema(parent=self._parent)

        return self._schema


type GetSchemaFunc = Callable[[], Coroutine[Any, Any, ConfigSchema]]


async def retrieve_schema(parent: ConfigOwner) -> ConfigSchema:
    response = await parent.requester.get(*parent.get_own_path(), "config-schema")
    return ConfigSchema(spec_as_jsonschema=response.as_dict())


async def retrieve_current_config[T: _GeneralConfig](
    parent: ConfigOwner, get_schema: GetSchemaFunc, as_type: type[T]
) -> T:
    # we are relying that current configuration will be
    # one of last created
    query = {"ordering": "-id", "limit": 10, "offset": 0}
    return await retrieve_config(
        parent=parent, get_schema=get_schema, query=query, choose_suitable_config=get_current_config, as_type=as_type
    )


async def retrieve_config[T: _GeneralConfig](
    parent: ConfigOwner,
    get_schema: GetSchemaFunc,
    query: dict,
    choose_suitable_config: Callable[[list[dict]], dict],
    as_type: type[T],
) -> T:
    schema_task = asyncio.create_task(get_schema())

    path = (*parent.get_own_path(), "configs")

    config_records_response = await parent.requester.get(*path, query=query)
    config_record = choose_suitable_config(config_records_response.as_dict()["results"])

    config_data_response = await parent.requester.get(*path, config_record["id"])
    config_data = ConfigData.from_v2_response(data_in_v2_format=config_data_response.as_dict())

    schema = await schema_task

    return as_type(config=config_data, schema=schema, parent=parent)


def get_first_result(results: list[dict]) -> dict:
    try:
        return results[0]
    except KeyError as e:
        message = "Configuration can't be found"
        raise RuntimeError(message) from e


def get_current_config(results: list[dict]) -> dict:
    for config in results:
        if config["isCurrent"]:
            return config

    message = "Failed to determine current configuraiton"
    raise RuntimeError(message)
