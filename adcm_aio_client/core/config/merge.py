from adcm_aio_client.core.config._operations import find_config_difference
from adcm_aio_client.core.config.types import ConfigData, ConfigSchema, LocalConfigs


def apply_local_changes(local: LocalConfigs, remote: ConfigData, schema: ConfigSchema) -> ConfigData:
    if local.initial.id == remote.id:
        return local.changed

    local_diff = find_config_difference(previous=local.initial, current=local.changed, schema=schema)
    if local_diff.is_empty:
        # no changed, nothing to apply
        return remote

    for parameter_name, value_change in local_diff.values.items():
        remote.set_value(parameter=parameter_name, value=value_change.current)

    for parameter_name, attribute_change in local_diff.attributes.items():
        if not isinstance(attribute_change, dict):
            message = f"Can't apply attribute changes of type {type(attribute_change)}, expected dict-like"
            raise TypeError(message)

        for attribute_name, value in attribute_change.current.items():
            remote.set_attribute(parameter=parameter_name, attribute=attribute_name, value=value)

    return remote


def apply_remote_changes(local: LocalConfigs, remote: ConfigData, schema: ConfigSchema) -> ConfigData:
    if local.initial.id == remote.id:
        return remote

    local_diff = find_config_difference(previous=local.initial, current=local.changed, schema=schema)
    if local_diff.is_empty:
        return remote

    remote_diff = find_config_difference(previous=local.initial, current=remote, schema=schema)

    locally_changed = set(local_diff.values.keys())
    changed_in_both = locally_changed.intersection(remote_diff.values.keys())
    changed_locally_only = locally_changed.difference(remote_diff.values.keys())

    for parameter_name in changed_in_both:
        remote.set_value(parameter=parameter_name, value=remote_diff.values[parameter_name].current)

    for parameter_name in changed_locally_only:
        remote.set_value(parameter=parameter_name, value=local_diff.values[parameter_name].current)

    locally_changed = set(local_diff.attributes.keys())
    changed_in_both = locally_changed.intersection(remote_diff.attributes.keys())
    changed_locally_only = locally_changed.difference(remote_diff.attributes.keys())

    for parameter_name in changed_in_both:
        attribute_change = remote_diff.attributes[parameter_name]
        if not isinstance(attribute_change, dict):
            message = f"Can't apply attribute changes of type {type(attribute_change)}, expected dict-like"
            raise TypeError(message)

        for attribute_name, value in attribute_change.current.items():
            remote.set_attribute(parameter=parameter_name, attribute=attribute_name, value=value)

    for parameter_name in changed_locally_only:
        attribute_change = local_diff.attributes[parameter_name]
        if not isinstance(attribute_change, dict):
            message = f"Can't apply attribute changes of type {type(attribute_change)}, expected dict-like"
            raise TypeError(message)

        for attribute_name, value in attribute_change.current.items():
            remote.set_attribute(parameter=parameter_name, attribute=attribute_name, value=value)

    return remote
