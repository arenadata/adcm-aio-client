from collections.abc import Collection
from typing import Any


def validate_kwargs(kwargs: dict[str, Any], mandatory_fields: Collection[str], obj_type_name: str) -> None:
    _to_be_form = "is" if len(mandatory_fields) == 1 else "are"

    if not all(kwargs.get(field) for field in mandatory_fields):
        kw_repr = ", ".join(f'"{field}"' for field in mandatory_fields)
        kw_repr = " and ".join(kw_repr.rsplit(", ", maxsplit=1))

        raise ValueError(f"{kw_repr} {_to_be_form} mandatory to create a {obj_type_name}")
