SCHEMA_TYPE = "enum"


def is_selection_group(schema: dict) -> bool:
    return bool(
        schema.get("oneOf")
        and (
            schema.get("discriminator", {}).get("propertyName") == "_selection"  # required selection group
            or any(  # not required selection group
                inner.get("discriminator", {}).get("propertyName") == "_selection" for inner in schema.get("oneOf", ())
            )
        )
    )


def get_choices(schema: dict) -> list[str | None]:
    choices = sorted([prop["title"] for prop in get_properties(schema).values()])
    if not is_required(schema):
        return [None, *choices]

    return choices


def get_properties(schema: dict) -> dict[str, dict]:
    """Returns selection_group properties dict, ignoring null choices"""

    properties = {}
    for group in schema["oneOf"]:
        if group.get("type") == "null":
            continue

        if is_required(schema=schema):
            properties.update({k: v for k, v in group["properties"].items() if k != "_selection"})
        else:
            for subgroup in group["oneOf"]:
                properties.update({k: v for k, v in subgroup["properties"].items() if k != "_selection"})

    return properties


def is_required(schema: dict) -> bool:
    return not any(group.get("type") == "null" for group in schema["oneOf"])
