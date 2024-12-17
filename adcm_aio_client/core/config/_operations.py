from adcm_aio_client.core.config.types import (
    ConfigSchema,
    FullConfigDifference,
    GenericConfigData,
    LevelNames,
    ValueChange,
    full_name_to_level_names,
)


# Difference
def find_config_difference(
    previous: GenericConfigData, current: GenericConfigData, schema: ConfigSchema
) -> FullConfigDifference:
    diff = FullConfigDifference(schema=schema)

    _fill_values_diff_at_level(level=(), diff=diff, previous=previous.values, current=current.values)
    _fill_attributes_diff(diff=diff, previous=previous.attributes, current=current.attributes)

    return diff


def _fill_values_diff_at_level(level: LevelNames, diff: FullConfigDifference, previous: dict, current: dict) -> None:
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

        if not (diff.schema.is_group(level_names) and isinstance(prev_value, dict) and (isinstance(cur_value, dict))):
            diff.values[level_names] = ValueChange(previous=prev_value, current=cur_value)
            continue

        _fill_values_diff_at_level(diff=diff, level=level_names, previous=prev_value, current=cur_value)


def _fill_attributes_diff(diff: FullConfigDifference, previous: dict, current: dict) -> None:
    missing = object()
    for full_name, cur_value in current.items():
        prev_value = previous.get(full_name, missing)
        if cur_value == prev_value:
            continue

        level_names = full_name_to_level_names(full_name)

        if prev_value is missing:
            prev_value = None

        diff.attributes[level_names] = ValueChange(previous=prev_value, current=cur_value)
