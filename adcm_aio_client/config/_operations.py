from contextlib import suppress

from adcm_aio_client.config._types import ConfigSchema, GenericConfigData, LevelNames, ParameterChange


# Difference
def find_config_difference(
    previous: GenericConfigData, current: GenericConfigData, schema: ConfigSchema
) -> dict[LevelNames, ParameterChange]:
    diff = {}

    for names, _ in schema.iterate_parameters():
        prev = {"value": None, "attrs": {}}
        cur = {"value": None, "attrs": {}}

        if not schema.is_group(names):
            with suppress(KeyError):
                prev["value"] = previous.get_value(names)

            with suppress(KeyError):
                cur["value"] = current.get_value(names)
        else:
            prev.pop("value")
            cur.pop("value")

        attr_key = f"/{'/'.join(names)}"
        prev["attrs"] = previous.attributes.get(attr_key, {})
        cur["attrs"] = current.attributes.get(attr_key, {})

        if prev != cur:
            diff[names] = ParameterChange(previous=prev, current=cur)

    return diff
