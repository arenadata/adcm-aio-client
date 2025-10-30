from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class SourceType(str, Enum):
    LOCAL = "local"
    LDAP = "ldap"


class _BaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)


class LocalUserData(_BaseModel):
    id: Annotated[int | None, Field(default=None, gt=0, exclude=True)]
    username: Annotated[str | None, Field(default=None)]
    password: Annotated[str | None, Field(default=None)]
    is_super_user: Annotated[bool | None, Field(default=None, serialization_alias="isSuperUser")]
    first_name: Annotated[str | None, Field(default=None, serialization_alias="firstName")]
    last_name: Annotated[str | None, Field(default=None, serialization_alias="lastName")]
    email: Annotated[str | None, Field(default=None)]
    groups: Annotated[list[int] | None, Field(default=None)]

    @field_validator("groups", mode="before")
    @classmethod
    def validate_groups(cls: type["LocalUserData"], value: Any) -> list[int]:  # noqa: ANN401
        from adcm_aio_client.objects.rbac._group import LocalGroup

        groups = list(value)
        if not all(isinstance(group, LocalGroup) for group in groups):
            raise ValueError(f'"groups" must be of type {LocalGroup.__name__}')

        return [group.id for group in groups]


class LocalGroupData(_BaseModel):
    id: Annotated[int | None, Field(default=None, gt=0, exclude=True)]
    display_name: Annotated[str | None, Field(default=None, serialization_alias="displayName")]
    description: Annotated[str | None, Field(default=None)]
    users: Annotated[list[int] | None, Field(default=None)]

    @field_validator("users", mode="before")
    @classmethod
    def validate_users(cls: type["LocalGroupData"], value: Any) -> list[int]:  # noqa: ANN401
        from adcm_aio_client.objects.rbac._user import LDAPUser, LocalUser

        users = list(value)
        if not all(isinstance(user, LocalUser | LDAPUser) for user in users):
            raise ValueError(f'"users" must be of type {LocalUser.__name__} | {LDAPUser.__name__}')

        return [user.id for user in users]


class CustomRoleData(_BaseModel):
    id: Annotated[int | None, Field(default=None, gt=0, exclude=True)]
    name: Annotated[str | None, Field(default=None)]
    display_name: Annotated[str | None, Field(default=None, serialization_alias="displayName")]
    description: Annotated[str | None, Field(default=None)]
    permissions: Annotated[list[int] | None, Field(default=None, serialization_alias="children")]

    @field_validator("permissions", mode="before")
    @classmethod
    def validate_permissions(cls: type["CustomRoleData"], value: Any) -> list[int]:  # noqa: ANN401
        from adcm_aio_client.objects.rbac._role import Permission

        permissions = list(value)
        if not all(isinstance(perm, Permission) for perm in permissions):
            raise ValueError(f'"permissions" must be of type {Permission.__name__}')

        return [perm.id for perm in permissions]
