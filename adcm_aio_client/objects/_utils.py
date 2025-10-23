from collections.abc import Collection
from typing import TYPE_CHECKING, Literal, Union

if TYPE_CHECKING:
    from adcm_aio_client.objects._rbac import (
        BuiltInRole,
        CustomRole,
        LDAPGroup,
        LDAPUser,
        LocalGroup,
        LocalUser,
        Policy,
        PolicyObject,
    )


def raise_exc(exc: type[Exception] = AttributeError, msg: str = "") -> None:
    raise exc(msg)


def setattr_user_groups(
    self: "LocalUser", key: Literal["groups"], value: Collection[Union["LocalGroup", "LDAPGroup"]]
) -> None:
    self._data[key] = self._to_internal_value_groups(value)  # pyright: ignore[reportArgumentType]
    self._manually_set.add(key)


def setattr_group_users(
    self: "LocalGroup", key: Literal["users"], value: Collection[Union["LocalUser", "LDAPUser"]]
) -> None:
    self._data[key] = self._to_internal_value_users(value)
    self._manually_set.add(key)


def setattr_policy_role(self: "Policy", key: Literal["role"], value: Union["BuiltInRole", "CustomRole"]) -> None:
    self._data[key] = self._to_internal_value_role(value)
    self._manually_set.add(key)


def setattr_policy_objects(self: "Policy", key: Literal["objects"], value: Collection["PolicyObject"]) -> None:
    self._data[key] = self._to_internal_value_objects(value)
    self._manually_set.add(key)


def setattr_policy_groups(
    self: "Policy", key: Literal["groups"], value: Collection[Union["LocalGroup", "LDAPGroup"]]
) -> None:
    self._data[key] = self._to_internal_value_groups(value)
    self._manually_set.add(key)
