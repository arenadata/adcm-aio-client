# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

from abc import abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import cached_property
from typing import TYPE_CHECKING, Any, Self

from asyncstdlib import cached_property as async_cached_property

from adcm_aio_client._filters import FilterByDisplayName, FilterByName, Filtering
from adcm_aio_client._types import Requester
from adcm_aio_client.config._objects import ActionConfig
from adcm_aio_client.config._types import ActionConfigData, ConfigSchema
from adcm_aio_client.errors import (
    ConflictError,
    HostNotInClusterError,
    NoConfigInActionError,
    NoMappingInActionError,
    ServerError,
    UnitExecutionError,
)
from adcm_aio_client.mapping._objects import ActionMapping
from adcm_aio_client.objects._accessors import NonPaginatedChildAccessor
from adcm_aio_client.objects._base import (
    InteractiveChildObject,
    InteractiveObject,
    convert_create_errors,
    convert_unit_execution_errors,
)

if TYPE_CHECKING:
    from adcm_aio_client.objects import Bundle, Cluster, Job


class _GenericAction(InteractiveChildObject):
    def __init__(self: Self, parent: InteractiveObject, data: dict[str, Any]) -> None:
        super().__init__(parent, data)
        self._verbose = False

    @property
    def verbose(self: Self) -> bool:
        return self._verbose

    @verbose.setter
    def verbose(self: Self, value: bool) -> bool:
        self._verbose = value
        return self._verbose

    @cached_property
    def name(self: Self) -> str:
        return self._data["name"]

    @cached_property
    def display_name(self: Self) -> str:
        return self._data["displayName"]

    @async_cached_property
    async def mapping(self: Self) -> ActionMapping:
        await self._ensure_rich_data()

        if not self._has_mapping:
            message = f"Action {self.display_name} doesn't allow mapping changes"
            raise NoMappingInActionError(message)

        cluster = await detect_cluster(owner=self._parent)
        mapping = await cluster.mapping
        entries = mapping.all()

        return ActionMapping(owner=self._parent, cluster=cluster, entries=entries)

    @async_cached_property
    async def config(self: Self) -> ActionConfig:
        await self._ensure_rich_data()

        if not self._has_config:
            message = f"Action {self.display_name} doesn't allow config changes"
            raise NoConfigInActionError(message)

        configuration = self._configuration
        data = ActionConfigData(values=configuration["config"], attributes=configuration["adcmMeta"])
        schema = ConfigSchema(spec_as_jsonschema=configuration["configSchema"])

        return ActionConfig(schema=schema, config=data, parent=self)

    @property
    def _is_full_data_loaded(self: Self) -> bool:
        return "hostComponentMapRules" in self._data

    @property
    def _has_mapping(self: Self) -> bool:
        return bool(self._mapping_rule)

    @property
    def _has_config(self: Self) -> bool:
        return bool(self._configuration)

    @property
    def _mapping_rule(self: Self) -> list[dict]:
        try:
            return self._data["hostComponentMapRules"]
        except KeyError as e:
            message = (
                "Failed to retrieve mapping rules. "
                "Most likely action was initialized with partial data."
                " Need to load all data"
            )
            raise KeyError(message) from e

    @property
    def _configuration(self: Self) -> dict:
        try:
            return self._data["configuration"]
        except KeyError as e:
            message = (
                "Failed to retrieve configuration section. "
                "Most likely action was initialized with partial data."
                " Need to load all data"
            )
            raise KeyError(message) from e

    async def _prepare_payload(self: Self) -> dict:
        await self._ensure_rich_data()

        data = {"isVerbose": self._verbose}
        if self._has_mapping:
            mapping = await self.mapping
            data |= {"hostComponentMap": mapping._to_payload()}
        if self._has_config:
            config = await self.config
            data |= {"configuration": config._to_payload()}

        return data

    async def _ensure_rich_data(self: Self) -> None:
        if self._is_full_data_loaded:
            return

        self._data = await self._retrieve_data()


class Action(_GenericAction):
    PATH_PREFIX = "actions"

    def __init__(self: Self, parent: InteractiveObject, data: dict[str, Any]) -> None:
        super().__init__(parent, data)
        self._blocking = True

    @property
    def blocking(self: Self) -> bool:
        return self._blocking

    @blocking.setter
    def blocking(self: Self, value: bool) -> bool:
        self._blocking = value
        return self._blocking

    async def run(self: Self) -> Job:
        payload = await self._prepare_payload() | {"shouldBlockObject": self._blocking}

        response = await self._requester.post(*self.get_own_path(), "run", data=payload)

        from adcm_aio_client.objects import Job

        return Job(requester=self._requester, data=response.as_dict())

    @cached_property
    def pre_process(self: Self) -> PreProcess:
        return PreProcess(requester=self._requester, action=self)


class ActionsAccessor[Parent: InteractiveObject](NonPaginatedChildAccessor[Parent, Action]):
    class_type = Action
    filtering = Filtering(FilterByName, FilterByDisplayName)


class Upgrade(_GenericAction):
    PATH_PREFIX = "upgrades"

    @property
    async def bundle(self: Self) -> Bundle:
        await self._ensure_rich_data()

        bundle_id = self._data["bundle"]["id"]

        from adcm_aio_client.objects import Bundle

        return await Bundle.with_id(requester=self._requester, object_id=bundle_id)

    async def run(self: Self) -> Job | None:
        payload = await self._prepare_payload()

        response = await self._requester.post(*self.get_own_path(), "run", data=payload)

        if response.get_status_code() == 204:
            return None

        from adcm_aio_client.objects import Job

        return Job(requester=self._requester, data=response.as_dict())


class UpgradeNode[Parent: InteractiveObject](NonPaginatedChildAccessor[Parent, Upgrade]):
    class_type = Upgrade
    filtering = Filtering(FilterByName, FilterByDisplayName)


class PreProcess:
    def __init__(
        self: Self,
        requester: Requester,
        action: Action,
    ) -> None:
        self._action = action
        self._requester = requester

    @convert_create_errors
    async def init(self: Self) -> Flow:
        process_path = *self._action.get_own_path(), Flow.PATH_PREFIX
        response = await self._requester.post(*process_path, data={})
        return Flow(parent=self._action, data=response.as_dict())

    @asynccontextmanager
    async def flow(self: Self) -> AsyncIterator[Flow]:
        flow = await self.init()
        yield flow
        await flow.complete()


class Flow(InteractiveChildObject[Action]):
    PATH_PREFIX = "processes"

    def __init__(self: Self, parent: Action, data: dict[str, Any]) -> None:
        super().__init__(parent=parent, data=data)
        self.id = self._data["id"]
        self._sync_key = self._data["syncKey"]

    async def get_state(self: Self) -> str:
        res = await self._retrieve_data()
        return res["state"]

    async def complete(self: Self) -> bool:
        try:
            await self._requester.post(
                *self.get_own_path(),
                "operation",
                data={
                    "method": "complete",
                    "params": {
                        "processSyncKey": self._sync_key,
                    },
                },
            )
        except (ConflictError, ServerError):
            return False
        return True

    @cached_property
    def units(self: Self) -> list[ConfigurationUnit | OperationUnit | MappingUnit]:
        units_mapping = {
            "configuration": ConfigurationUnit,
            "operation": OperationUnit,
            "mapping": MappingUnit,
        }

        units = []

        for stage in self._data["stages"]:
            for step in stage["steps"]:
                step_data = {
                    **step,
                    "stage": stage.get("displayName"),
                }
                unit_class = units_mapping[step["type"]]
                units.append(
                    unit_class(
                        parent=self,
                        data=step_data,
                        get_sync_key=self._get_sync_key,
                        set_synk_key=self._set_sync_key,
                        refresh_sync_key=self._refresh_sync_key,
                    )
                )
        return units

    def _set_sync_key(self: Self, value: str) -> None:
        self._sync_key = value

    def _get_sync_key(self: Self) -> str:
        return self._sync_key

    async def _refresh_sync_key(self: Self) -> str:
        resp = await self._retrieve_data()
        self._sync_key = resp["syncKey"]
        return self._sync_key


class _BaseUnit(InteractiveChildObject[Flow]):
    PATH_PREFIX = "steps"

    def __init__(
        self: Self,
        parent: Flow,
        data: dict[str, Any],
        get_sync_key: Callable[[], str],
        set_synk_key: Callable[[str], None],
        refresh_sync_key: Callable[[], Awaitable[str]],
    ) -> None:
        super().__init__(parent=parent, data=data)
        self.unit_id: int | None = self._data.get("id")
        self._get_flow_sync_key = get_sync_key
        self._set_flow_sync_key_after_execute = set_synk_key
        self._refresh_sync_key_after_job_complete = refresh_sync_key

    @cached_property
    def name(self: Self) -> str:
        return self._data["name"]

    @cached_property
    def display_name(self: Self) -> str:
        return self._data["displayName"]

    @cached_property
    def stage(self: Self) -> str:
        return self._data["stage"]

    async def get_state(self: Self) -> str:
        response = await self._retrieve_data()
        return response["state"]

    @convert_unit_execution_errors
    async def _post_operation_r(self: Self, payload: dict) -> dict:
        response = await self._requester.post(*self._parent.get_own_path(), "operation", data=payload)

        return response.as_dict()


class OperationUnit(_BaseUnit):
    async def execute(self: Self, timeout: int | None = None, poll_interval: int = 1) -> Self:
        payload = {
            "method": "submit_step",
            "params": {
                "stepId": self.id,
                "processSyncKey": self._get_flow_sync_key(),
            },
        }

        response_data = await self._post_operation_r(payload)

        self._set_flow_sync_key_after_execute(response_data["syncKey"])

        task_id = await self._get_task_id()

        from adcm_aio_client.objects import Job

        job = await Job.with_id(object_id=task_id, requester=self._requester)
        await job.wait(timeout=timeout, poll_interval=poll_interval)

        status = await job.get_status()
        if status != "success":
            raise UnitExecutionError(f'Related job (id={task_id}) finished with the status "{status}"')

        await self._refresh_sync_key_after_job_complete()

        return self

    async def skip(self: Self) -> bool:
        payload = {
            "method": "skip_step",
            "params": {
                "stepId": self.id,
                "processSyncKey": self._get_flow_sync_key(),
            },
        }
        try:
            response_data = await self._post_operation_r(payload)
        except UnitExecutionError:
            return False

        self._set_flow_sync_key_after_execute(response_data["syncKey"])
        return True

    async def _get_task_id(self: Self) -> int:
        resp = await self._retrieve_data()
        return resp["task"]["id"]


class ConfigurationUnit(_BaseUnit):
    async def execute(self: Self) -> Self:
        config_payload = (await self.config)._to_payload()
        payload = {
            "method": "submit_step",
            "params": {
                "stepId": self.id,
                "processSyncKey": self._get_flow_sync_key(),
                "configuration": config_payload,
            },
        }

        response = await self._post_operation_r(payload)

        self._set_flow_sync_key_after_execute(response["syncKey"])

        return self

    @async_cached_property
    async def config(self: Self) -> ActionConfig:
        response = (await self.requester.get(*self.get_own_path())).as_dict()["configuration"]

        schema = ConfigSchema(spec_as_jsonschema=response["configSchema"])
        data = ActionConfigData(values=response["config"], attributes=response["adcmMeta"])

        return ActionConfig(schema=schema, config=data, parent=self)


class MappingUnit(_BaseUnit):
    async def execute(self: Self, timeout: int | None = None) -> Self:
        raise NotImplementedError()


async def detect_cluster(owner: InteractiveObject) -> Cluster:
    from adcm_aio_client.objects import ActionHostGroup, Cluster, Component, Host, Service

    if isinstance(owner, ActionHostGroup):
        return await detect_cluster(owner._parent)

    if isinstance(owner, Cluster):
        return owner

    if isinstance(owner, Service | Component):
        return owner.cluster

    if isinstance(owner, Host):
        cluster = await owner.cluster
        if cluster is None:
            message = f"Host {owner.name} isn't bound to cluster " "or it's not refreshed"
            raise HostNotInClusterError(message)

        return cluster

    message = f"No cluster in hierarchy for {owner}"
    raise RuntimeError(message)
