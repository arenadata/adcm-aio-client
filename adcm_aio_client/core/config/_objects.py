from copy import deepcopy
from functools import partial
from typing import Any, Callable, Coroutine, Protocol, Self, overload
import json
import asyncio

from adcm_aio_client.core.config._operations import find_config_difference
from adcm_aio_client.core.config.merge import apply_local_changes
from adcm_aio_client.core.config.types import (
    AnyParameterName,
    ConfigData,
    ConfigDifference,
    ConfigSchema,
    LevelNames,
    LocalConfigs,
    MergeStrategy,
)
from adcm_aio_client.core.errors import ConfigComparisonError, RequesterError
from adcm_aio_client.core.types import AwareOfOwnPath, WithRequesterProperty


class ConfigOwner(WithRequesterProperty, AwareOfOwnPath, Protocol): ...


# Config Entries Wrappers


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

        class_ = value_class
        if self._schema.is_group(parameter_full_name):
            class_ = a_group_class if self._schema.is_activatable_group(parameter_full_name) else group_class

        wrapper = class_(name=parameter_full_name, data=self._data, schema=self._schema)

        self._wrappers_cache[level_name] = wrapper

        return wrapper


class Value[T](_ConfigWrapper):
    @property
    def value(self: Self) -> T:
        # todo probably want to return read-only proxies for list/dict
        return self._data.get_value(parameter=self._name)

    def set(self: Self, value: Any) -> Self:  # noqa: ANN401
        self._data.set_value(parameter=self._name, value=value)
        return self


class _Desyncable(_ConfigWrapper):
    def sync(self: Self) -> Self:
        self._data.set_attribute(parameter=self._name, attribute="isSynced", value=True)
        return self

    def desync(self: Self) -> Self:
        self._data.set_attribute(parameter=self._name, attribute="isSynced", value=False)
        return self


class DesyncableValue[T](_Desyncable, Value[T]):
    def set(self: Self, value: Any) -> Self:  # noqa: ANN401
        super().set(value)
        self.desync()
        return self


class Group(_Group):
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
            item=item, value_class=Value, group_class=Group, a_group_class=ActivatableGroup
        )


class DesyncableGroup(_Group):
    @overload
    def __getitem__[ExpectedType: "DesyncableConfigEntry"](
        self: Self, item: tuple[AnyParameterName, type[ExpectedType]]
    ) -> ExpectedType: ...

    @overload
    def __getitem__(self: Self, item: AnyParameterName) -> "DesyncableConfigEntry": ...

    def __getitem__[ExpectedType: "DesyncableConfigEntry"](
        self: Self, item: AnyParameterName | tuple[AnyParameterName, type[ExpectedType]]
    ) -> "DesyncableConfigEntry":
        """
        Get config entry by given display name (or "technical" name).

        Item is either a string (name) or tuple with name on first position
        and type info at second.

        NOTE: types aren't checked, they are just helpers for users' type checking setups.
        """
        return self._find_and_wrap_config_entry(
            item=item,
            value_class=DesyncableValue,
            group_class=DesyncableGroup,
            a_group_class=DesyncableActivatableGroup,
        )


class _Activatable(_Group):
    def activate(self: Self) -> Self:
        self._data.set_attribute(parameter=self._name, attribute="isActive", value=True)
        return self

    def deactivate(self: Self) -> Self:
        self._data.set_attribute(parameter=self._name, attribute="isActive", value=False)
        return self


class ActivatableGroup(_Activatable, Group): ...


class DesyncableActivatableGroup(_Desyncable, _Activatable, Group):
    def activate(self: Self) -> Self:
        super().activate()
        self.desync()
        return self

    def deactivate(self: Self) -> Self:
        super().deactivate()
        self.desync()
        return self


class _ConfigWrapperCreator(_ConfigWrapper):
    @property
    def config(self: Self) -> ConfigData:
        return self._data

    def change_data(self: Self, new_data: ConfigData) -> ConfigData:
        self._data = new_data
        return self._data


class ObjectConfigWrapper(Group, _ConfigWrapperCreator): ...


class HostGroupConfigWrapper(DesyncableGroup, _ConfigWrapperCreator): ...


type ConfigEntry = Value | Group | ActivatableGroup
type DesyncableConfigEntry = DesyncableValue | DesyncableGroup | DesyncableActivatableGroup

# API Objects


class _GeneralConfig[T: _ConfigWrapperCreator]:
    __slots__ = ("_schema", "_parent", "_initial_config", "_current_config", "_wrapper_class")

    _wrapper_class: type[T]

    def __init__(self: Self, config: ConfigData, schema: ConfigSchema, parent: ConfigOwner) -> None:
        self._schema = schema
        self._initial_config: ConfigData = self._parse_json_fields_inplace_safe(config)
        self._current_config = self._wrapper_class(data=deepcopy(self._initial_config), schema=self._schema, name=())
        self._parent = parent

    # Public Interface (for End User)

    @property
    def id(self: Self) -> int:
        return self._initial_config.id

    @property
    def description(self: Self) -> str:
        return self._initial_config.description

    def reset(self: Self) -> Self:
        self._current_config.change_data(new_data=deepcopy(self._initial_config))
        return self

    def difference(self: Self, other: Self, *, other_is_previous: bool = True) -> ConfigDifference:
        if self.schema != other.schema:
            message = f"Schema of configuration {other.id} doesn't match schema of {self.id}"
            raise ConfigComparisonError(message)

        if other_is_previous:
            previous = other
            current = self
        else:
            previous = self
            current = other

        return find_config_difference(previous=previous.data, current=current.data, schema=self._schema)

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
        else:
            new_config = ConfigData.from_v2_response(data_in_v2_format=response.as_dict())
            self._initial_config = self._parse_json_fields_inplace_safe(new_config)
            self.reset()

        return self

    # Public For Internal Use Only

    @property
    def schema(self: Self) -> ConfigSchema:
        return self._schema

    @property
    def data(self: Self) -> ConfigData:
        return self._current_config.config

    # Private
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


class _RefreshableConfig[T: _ConfigWrapperCreator](_GeneralConfig[T]):
    async def refresh(self: Self, strategy: MergeStrategy = apply_local_changes) -> Self:
        remote_config = await retrieve_current_config(
            parent=self._parent, get_schema=partial(retrieve_schema, parent=self._parent)
        )
        if self.schema != remote_config.schema:
            message = "Can't refresh configuration after upgrade: schema is different for local and remote configs"
            raise ConfigComparisonError(message)

        local = LocalConfigs(initial=self._initial_config, changed=self._current_config.config)
        merged_config = strategy(local=local, remote=remote_config.data, schema=self._schema)

        self._initial_config = remote_config.data
        self._current_config.change_data(new_data=merged_config)

        return self


class ActionConfig(_GeneralConfig[ObjectConfigWrapper]):
    _wrapper_class = ObjectConfigWrapper

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


class ObjectConfig(_RefreshableConfig[ObjectConfigWrapper]):
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


class HostGroupConfig(_RefreshableConfig[HostGroupConfigWrapper]):
    _wrapper_class = HostGroupConfigWrapper

    @overload
    def __getitem__[ExpectedType: DesyncableConfigEntry](
        self: Self, item: tuple[AnyParameterName, type[ExpectedType]]
    ) -> ExpectedType: ...

    @overload
    def __getitem__(self: Self, item: AnyParameterName) -> DesyncableConfigEntry: ...

    def __getitem__[ExpectedType: DesyncableConfigEntry](
        self: Self, item: AnyParameterName | tuple[AnyParameterName, type[ExpectedType]]
    ) -> "DesyncableConfigEntry":
        return self._current_config[item]


class ConfigHistoryNode:
    def __init__(self: Self, parent: ConfigOwner) -> None:
        self._schema: ConfigSchema | None = None
        self._parent = parent

    async def current(self: Self) -> ObjectConfig:
        return await retrieve_current_config(parent=self._parent, get_schema=self._ensure_schema)

    async def __getitem__(self: Self, position: int) -> ObjectConfig:
        # since we don't have date in here, we sort by id
        ordering = "id"
        offset = position
        if offset < 0:
            ordering = "-id"
            # `-1` is the same as `0` in reverse order
            offset = abs(offset) - 1

        query = {"limit": 1, "offset": offset, "ordering": ordering}

        return await retrieve_config(
            parent=self._parent, get_schema=self._ensure_schema, query=query, choose_suitable_config=get_first_result
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


async def retrieve_current_config(parent: ConfigOwner, get_schema: GetSchemaFunc) -> ObjectConfig:
    # we are relying that current configuration will be
    # one of last created
    query = {"ordering": "-id", "limit": 10, "offset": 0}
    return await retrieve_config(
        parent=parent, get_schema=get_schema, query=query, choose_suitable_config=get_current_config
    )


async def retrieve_config(
    parent: ConfigOwner,
    get_schema: GetSchemaFunc,
    query: dict,
    choose_suitable_config: Callable[[list[dict]], dict],
) -> ObjectConfig:
    schema_task = asyncio.create_task(get_schema())

    path = (*parent.get_own_path(), "configs")

    config_records_response = await parent.requester.get(*path, query=query)
    config_record = choose_suitable_config(config_records_response.as_dict()["results"])

    config_data_response = await parent.requester.get(*path, config_record["id"])
    config_data = ConfigData.from_v2_response(data_in_v2_format=config_data_response.as_dict())

    schema = await schema_task

    return ObjectConfig(config=config_data, schema=schema, parent=parent)


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
