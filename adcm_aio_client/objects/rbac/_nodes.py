from typing import Any, Self, Unpack

from adcm_aio_client._filters import (
    ALL_OPERATIONS,
    COMMON_OPERATIONS,
    FilterBy,
    FilterByDisplayName,
    FilterByID,
    Filtering,
)
from adcm_aio_client.objects._accessors import PaginatedAccessor
from adcm_aio_client.objects.rbac._group import LDAPGroup, LocalGroup, LocalGroupLazy, _GroupKwargs
from adcm_aio_client.objects.rbac._types import LocalGroupData, LocalUserData, SourceType
from adcm_aio_client.objects.rbac._user import LDAPUser, LocalUser, LocalUserLazy, _UserKwargs


class UsersNode(PaginatedAccessor[LocalUser | LDAPUser]):
    filtering = Filtering(
        FilterByID, FilterBy("username", ALL_OPERATIONS, str), FilterBy("group", COMMON_OPERATIONS, int)
    )

    def new(self: Self, **kwargs: Unpack[_UserKwargs]) -> LocalUserLazy:
        if not all((kwargs.get("username"), kwargs.get("password"))):
            raise ValueError('"username" and "password" are mandatory to create a user')

        return LocalUserLazy(**{"requester": self._requester, **kwargs})

    async def init(self: Self, user: LocalUserData) -> LocalUser:
        if not isinstance(user, LocalUserData):
            raise TypeError(f"Expected a {LocalUserData} object, got {type(user)}")

        post_data = user.model_dump(exclude={"id"}, exclude_defaults=True, exclude_unset=True)
        response = await self._requester.post("rbac/users/", data=post_data)

        return LocalUser(requester=self._requester, data=response.as_dict())

    def _create_object(self: Self, data: dict[str, Any]) -> LocalUser | LDAPUser:
        match data["type"]:
            case SourceType.LOCAL:
                cls_ = LocalUser
            case SourceType.LDAP:
                cls_ = LDAPUser
            case _:
                raise NotImplementedError(f"Unexpected user type: {data['type']}")

        return cls_(requester=self._requester, data=data)


class GroupsNode(PaginatedAccessor[LocalGroup | LDAPGroup]):
    filtering = Filtering(FilterByID, FilterByDisplayName)

    def new(self: Self, **kwargs: Unpack[_GroupKwargs]) -> LocalGroupLazy:
        if not kwargs.get("display_name"):
            raise ValueError('"display_name" is mandatory to create a group')

        return LocalGroupLazy(**{"requester": self._requester, **kwargs})

    async def init(self: Self, group: LocalGroupData) -> LocalGroup:
        if not isinstance(group, LocalGroupData):
            raise TypeError(f"Expected a {LocalGroupData} object, got {type(group)}")

        post_data = group.model_dump(exclude={"id"}, exclude_defaults=True, exclude_unset=True)
        response = await self._requester.post("rbac/groups/", data=post_data)

        return LocalGroup(requester=self._requester, data=response.as_dict())

    def _create_object(self: Self, data: dict[str, Any]) -> LocalGroup | LDAPGroup:
        match data["type"]:
            case SourceType.LOCAL:
                cls_ = LocalGroup
            case SourceType.LDAP:
                cls_ = LDAPGroup
            case _:
                raise NotImplementedError(f"Unexpected group type: {data['type']}")

        return cls_(requester=self._requester, data=data)
