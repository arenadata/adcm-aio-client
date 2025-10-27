from enum import Enum
from typing import TYPE_CHECKING, Annotated, NotRequired, Self, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from adcm_aio_client.requesters import DefaultRequester

if TYPE_CHECKING:
    from adcm_aio_client.objects.rbac._user import LocalUser


class UserStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class SourceType(str, Enum):
    LOCAL = "local"
    LDAP = "ldap"


class LocalUserData(BaseModel):
    id: Annotated[int | None, Field(default=None, gt=0)]
    username: Annotated[str | None, Field(default=None)]
    password: Annotated[str | None, Field(default=None)]
    is_super_user: Annotated[bool | None, Field(default=None, serialization_alias="isSuperUser")]
    first_name: Annotated[str | None, Field(default=None, serialization_alias="firstName")]
    last_name: Annotated[str | None, Field(default=None, serialization_alias="lastName")]
    email: Annotated[str | None, Field(default=None)]

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)


class LocalUserLazy(LocalUserData):
    """LocalUserData with requester, can perform user create / update operations"""

    requester: Annotated[DefaultRequester, Field(exclude=True)]

    async def save(self: Self) -> "LocalUser":
        from adcm_aio_client.objects.rbac._user import LocalUser

        if self.id:
            url = f"rbac/users/{self.id}"
            method = self.requester.patch
        else:
            url = "rbac/users"
            method = self.requester.post

        data = self.model_dump(exclude={"id"}, exclude_unset=True, exclude_defaults=True)
        response = await method(url, data=data)

        return LocalUser(requester=self.requester, data=response.as_dict())


class UserKwargs(TypedDict):
    username: NotRequired[str | None]
    password: NotRequired[str | None]
    is_super_user: NotRequired[bool | None]
    first_name: NotRequired[str | None]
    last_name: NotRequired[str | None]
    email: NotRequired[str | None]
