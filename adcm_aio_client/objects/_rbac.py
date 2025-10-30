# from collections import defaultdict
# from collections.abc import Collection
# from functools import cached_property
# from typing import TYPE_CHECKING, Any, Literal, Optional, Self
# import asyncio
#
# from asyncstdlib.functools import cached_property as async_cached_property  # noqa: N813
#
# from adcm_aio_client._filters import (
#     FilterByDisplayName,
#     FilterByID,
#     FilterByName,
#     Filtering,
# )
# from adcm_aio_client._types import Requester
# from adcm_aio_client.objects._accessors import PaginatedAccessor
# from adcm_aio_client.objects._base import RootInteractiveObject
# from adcm_aio_client.objects._cm import Cluster, Component, Host, HostProvider, Service
# from adcm_aio_client.objects._common import ConfigurableSetAttrMixin, Deletable, LazyObject
# from adcm_aio_client.objects._utils import (
#     setattr_policy_groups,
#     setattr_policy_objects,
#     setattr_policy_role,
# )
#
# if TYPE_CHECKING:
#     from adcm_aio_client.client import ADCMClient
#
# pyright: reportUnnecessaryTypeIgnoreComment=false
#
# type PolicyObject = Cluster | Service | Component | HostProvider | Host
# type IDDictInternalValue = dict[Literal["id"], int]
# type ListOfIDDictsInternalValue = list[IDDictInternalValue]
# type PolicyObjectsInternalValue = list[dict[Literal["id", "type"], int | str]]
#
# # client._requester access
# # pyright: reportOptionalMemberAccess=false
# # id -> int | None override
# # pyright: reportIncompatibleVariableOverride=false
# # Any type
# # ruff: noqa: ANN401
#
#
# class Policy(Deletable, LazyObject, ConfigurableSetAttrMixin, RootInteractiveObject):
#     PATH_PREFIX = "rbac/policies"
#     _custom_setattr = {  # pyright: ignore[reportAssignmentType]
#         "role": setattr_policy_role,
#         "objects": setattr_policy_objects,
#         "groups": setattr_policy_groups,
#     }
#     _obj_cls_type_map = {
#         Cluster: "cluster",
#         Service: "service",
#         Component: "component",
#         HostProvider: "provider",
#         Host: "host",
#     }
#
#     def __init__(
#         self: Self,
#         requester: Requester | None = None,
#         data: dict[str, Any] | None = None,
#         client: Optional["ADCMClient"] = None,
#         name: str | None = None,
#         role: CustomRole | BuiltInRole | None = None,
#         objects: Collection[PolicyObject] | None = None,
#         groups: Collection[LocalGroup | LDAPGroup] | None = None,
#         description: str = "",
#     ) -> None:
#         if not any((data, requester)):
#             if not all((client, name, role, objects, groups)):
#                 raise RuntimeError(
#                     f"`client`, `name`, `role`, `objects` and `groups` "
#                     f"are mandatory to create a {self.__class__.__name__}"
#                 )
#
#             data = {
#                 "name": name,
#                 "description": description,
#                 "role": self._to_internal_value_role(role=role),  # pyright: ignore[reportArgumentType]
#                 "objects": self._to_internal_value_objects(objects=objects),  # pyright: ignore[reportArgumentType]
#                 "groups": self._to_internal_value_groups(groups=groups),  # pyright: ignore[reportArgumentType]
#             }
#             requester = client._requester
#
#         super().__init__(requester=requester, data=data)
#
#     @property
#     def name(self: Self) -> str:
#         return self._data["name"]
#
#     @name.setter
#     def name(self: Self, name: str) -> None:
#         key = "name"
#         self._data[key] = name
#         self._manually_set.add(key)
#
#     @property
#     def description(self: Self) -> str:
#         return self._data["description"]
#
#     @description.setter
#     def description(self: Self, description: str) -> None:
#         key = "description"
#         self._data[key] = description
#         self._manually_set.add(key)
#
#     @async_cached_property
#     async def role(self: Self) -> BuiltInRole | CustomRole:
#         return await RolesNode(
#             path=("rbac", "roles"), requester=self.requester
#         ).get(id__eq=self._data["role"]["id"])  # pyright: ignore[reportReturnType]
#
#     @async_cached_property
#     async def objects(self: Self) -> list[PolicyObject]:
#         _obj_type_cls_map = {v: k for k, v in self._obj_cls_type_map.items()}
#
#         cls_ids_map = defaultdict(set)
#         for obj in self._data["objects"]:
#             if (obj_type := obj["type"]) in {"service", "component"}:
#                 # TODO: now it is impossible to get service/component object from policy.objects
#                 #  since there is no info about parent objects in policy.objects field
#                 continue
#
#             obj_cls = _obj_type_cls_map[obj_type]
#             cls_ids_map[obj_cls].add(obj["id"])
#
#         coros = []
#         for cls_, ids in cls_ids_map.items():
#             coros.extend(cls_.with_id(requester=self.requester, object_id=id_) for id_ in ids)
#
#         return list(await asyncio.gather(*coros))
#
#     @async_cached_property
#     async def groups(self: Self) -> list:  # [LocalGroup | LDAPGroup]:
#         return []
#         # group_ids = [group["id"] for group in self._data["groups"]] or [-1]
#         #
#         # return await GroupsNode(path=("rbac", "groups"), requester=self.requester).filter(id__in=group_ids)
#
#     @staticmethod
#     def _postprocess_save_data(data: Any, mode: Literal["create", "update"]) -> Any:
#         _ = mode
#         if "groups" in data:
#             data["groups"] = [group["id"] for group in data["groups"]]
#
#         return data
#
#     def _to_internal_value_objects(self: Self, objects: Collection[PolicyObject]) -> PolicyObjectsInternalValue:
#         objects = self._validate_objects(objects=objects)
#
#         return [{"id": obj_.id, "type": self._obj_cls_type_map[type(obj_)]} for obj_ in objects]
#
#     def _validate_objects(self: Self, objects: Collection[PolicyObject]) -> Collection[PolicyObject]:
#         valid_types = tuple(self._obj_cls_type_map.keys())
#         if errors := [type(obj) for obj in objects if not isinstance(obj, valid_types)]:
#             _valid_types_repr = ", ".join(f"{obj.__class__.__name__}" for obj in valid_types)
#             _valid_types_repr = " or ".join(_valid_types_repr.rsplit(", ", maxsplit=1))
#             raise ValueError(f"All objects must be {_valid_types_repr}, got {errors}")
#
#         if not all(obj.id for obj in objects):
#             raise ValueError("All objects must be saved before assigning them to policy")
#
#         return objects
#
#     def _to_internal_value_role(self: Self, role: BuiltInRole | CustomRole) -> IDDictInternalValue:
#         role = self._validate_role(role=role)
#
#         return {"id": role.id}  # pyright: ignore[reportReturnType]
#
#     @staticmethod
#     def _validate_role(role: BuiltInRole | CustomRole) -> BuiltInRole | CustomRole:
#         if not isinstance(role, BuiltInRole | CustomRole):
#             raise ValueError(
#                 f"Role must be a {BuiltInRole.__name__} or {CustomRole.__name__}, got {type(role)}"
#             )  # noqa: TRY004
#
#         if not role.id:
#             raise ValueError("Role must be saved before assigning it to policy")
#
#         return role
#
#     def _to_internal_value_groups(
#           self: Self, groups: Collection[LocalGroup | LDAPGroup]
#     ) -> ListOfIDDictsInternalValue:
#         groups = self._validate_groups(groups=groups)
#
#         return [{"id": group.id} for group in groups]  # pyright: ignore[reportReturnType]
#
#     @staticmethod
#     def _validate_groups(groups: Collection[LocalGroup | LDAPGroup]) -> Collection[LocalGroup | LDAPGroup]:
#         if errors := [type(group) for group in groups if not isinstance(group, LocalGroup | LDAPGroup)]:
#             raise ValueError(f"All groups must be {LocalGroup.__name__} or {LDAPGroup.__name__}, got {errors}")
#
#         if not all(group.id for group in groups):
#             raise ValueError("All groups must be saved before assigning them to policy")
#
#         return groups
#
#
# class PoliciesNode(PaginatedAccessor[Policy]):
#     class_type = Policy
#     filtering = Filtering(FilterByName)
