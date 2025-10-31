from collections import defaultdict
from functools import partial
from typing import Annotated, NotRequired, Self, TypedDict, Unpack
import asyncio

from asyncstdlib.functools import cached_property as async_cached_property  # noqa: N813
from pydantic import Field

from adcm_aio_client.objects._base import RootInteractiveObject
from adcm_aio_client.objects._cm import Cluster, Host, HostProvider, Service
from adcm_aio_client.objects._common import Deletable, WithSaveMethod
from adcm_aio_client.objects.rbac._group import LDAPGroup, LocalGroup
from adcm_aio_client.objects.rbac._role import BuiltInRole, CustomRole
from adcm_aio_client.objects.rbac._types import PolicyData
from adcm_aio_client.objects.rbac._utils import validate_kwargs
from adcm_aio_client.requesters import DefaultRequester

type PolicyObject = Cluster | Service | HostProvider | Host


class _PolicyKwargs(TypedDict):
    name: NotRequired[str]
    role: NotRequired[CustomRole | BuiltInRole]
    objects: NotRequired[list[Cluster | Service | HostProvider | Host]]
    groups: NotRequired[list[LocalGroup | LDAPGroup]]
    description: NotRequired[str]


def new(**kwargs: Unpack[_PolicyKwargs]) -> PolicyData:
    # cast kwargs to dict to remove `TypedDict is not dict` error
    _validate_policy_kwargs(dict(kwargs))

    return PolicyData.model_validate(kwargs)


class Policy(Deletable, RootInteractiveObject):
    PATH_PREFIX = "rbac/policies"
    _obj_cls_type_map = {
        Cluster: "cluster",
        Service: "service",
        HostProvider: "provider",
        Host: "host",
    }

    def edit(self: Self, **kwargs: Unpack[_PolicyKwargs]) -> "PolicyLazy":
        return PolicyLazy.model_validate({"id": self.id, "requester": self._requester, **kwargs})

    @property
    def name(self: Self) -> str:
        return self._data["name"]

    @property
    def description(self: Self) -> str:
        return self._data["description"]

    @async_cached_property
    async def role(self: Self) -> BuiltInRole | CustomRole:
        from adcm_aio_client.objects.rbac._nodes import RolesNode

        return await RolesNode(path=("rbac", "roles"), requester=self._requester).get(id__eq=self._data["role"]["id"])  # pyright: ignore[reportReturnType]

    @async_cached_property
    async def objects(self: Self) -> list[PolicyObject]:
        _obj_type_cls_map = {v: k for k, v in self._obj_cls_type_map.items()}

        cls_ids_map = defaultdict(set)
        for obj in self._data["objects"]:
            if (obj_type := obj["type"]) in {"service", "component"}:
                # TODO: now it is impossible to get service/component object from policy.objects
                #  since there is no info about parent objects in policy.objects field
                continue

            obj_cls = _obj_type_cls_map[obj_type]
            cls_ids_map[obj_cls].add(obj["id"])

        coros = []
        for cls_, ids in cls_ids_map.items():
            coros.extend(cls_.with_id(requester=self._requester, object_id=id_) for id_ in ids)

        return list(await asyncio.gather(*coros))

    @async_cached_property
    async def groups(self: Self) -> list[LocalGroup | LDAPGroup]:
        from adcm_aio_client.objects.rbac._nodes import GroupsNode

        group_ids = [group["id"] for group in self._data["groups"]] or [-1]

        return await GroupsNode(path=("rbac", "groups"), requester=self._requester).filter(id__in=group_ids)


class PolicyLazy(PolicyData, WithSaveMethod[Policy]):
    """PolicyData with requester, can perform policy create / update operations"""

    _cls = Policy
    _url_part = "rbac/policies"

    requester: Annotated[DefaultRequester, Field(exclude=True)]  # pyright: ignore[reportIncompatibleVariableOverride]


_validate_policy_kwargs = partial(
    validate_kwargs, mandatory_fields=["name", "role", "objects", "groups"], obj_type_name=Policy.__name__
)
