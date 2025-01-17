from adcm_aio_client.config._operations import find_config_difference
from adcm_aio_client.config._types import ConfigData, ConfigSchema, LevelNames, LocalConfigs, ParameterChange


def apply_local_changes(local: LocalConfigs, remote: ConfigData, schema: ConfigSchema) -> ConfigData:
    if local.initial.id == remote.id:
        return local.changed

    local_diff = find_config_difference(previous=local.initial, current=local.changed, schema=schema)
    if not local_diff:
        # no changed, nothing to apply
        return remote

    _apply(data=remote, changes=local_diff)

    return remote


def apply_remote_changes(local: LocalConfigs, remote: ConfigData, schema: ConfigSchema) -> ConfigData:
    if local.initial.id == remote.id:
        return local.changed

    local_diff = find_config_difference(previous=local.initial, current=local.changed, schema=schema)
    if not local_diff:
        return remote

    remote_diff = find_config_difference(previous=local.initial, current=remote, schema=schema)

    changed_in_remote = set(remote_diff.keys())
    only_local_changes = {k: v for k, v in local_diff.items() if k not in changed_in_remote}

    _apply(data=remote, changes=only_local_changes)

    return remote


def _apply(data: ConfigData, changes: dict[LevelNames, ParameterChange]) -> None:
    for parameter_name, change in changes.items():
        prev_value = change.previous.get("value")
        cur_value = change.current.get("value")
        # rechecking diff, because value may be present even if nothing is different,
        # yet assigning defaults (`None`) may break data
        if prev_value != cur_value:
            data.set_value(parameter=parameter_name, value=cur_value)

        for name, value in change.current.get("attrs", {}).items():
            data.set_attribute(parameter=parameter_name, attribute=name, value=value)
