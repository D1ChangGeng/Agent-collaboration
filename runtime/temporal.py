from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError
from temporalio.worker import Worker

TEMPORAL_SDK_AVAILABLE = True


class TemporalUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TemporalOperation:
    operation_id: str
    workflow_id: str
    run_id: str
    status: str
    result: dict[str, Any]


def canonical_payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


if TEMPORAL_SDK_AVAILABLE:

    @activity.defn(name="acs-p1-submitted-operation")
    async def submitted_operation_activity(payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "committed", "payload": dict(payload)}

    @workflow.defn(name="AcsP1SubmittedOperation")
    class SubmittedOperationWorkflow:
        def __init__(self) -> None:
            self._state: dict[str, Any] = {"status": "running"}

        @workflow.run
        async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
            self._state = {"status": "running", "payload": dict(payload)}
            result = await workflow.execute_activity(
                submitted_operation_activity,
                dict(payload),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            self._state = dict(result)
            return dict(result)

        @workflow.query(name="state")
        def state(self) -> dict[str, Any]:
            return dict(self._state)

else:
    SubmittedOperationWorkflow = None  # type: ignore[assignment,misc]


class TemporalAdapter:
    def __init__(
        self,
        endpoint: str | None = None,
        *,
        namespace: str | None = None,
        task_queue: str = "acs-p1-operations",
        worker_identity: str = "acs-p1-runtime",
    ) -> None:
        self.endpoint = endpoint or os.getenv("ACS_P1_TEMPORAL_ENDPOINT", "")
        self.namespace = namespace or os.getenv("ACS_P1_TEMPORAL_NAMESPACE", "")
        self.task_queue = task_queue
        self.worker_identity = worker_identity
        self._client: Any = None
        self._worker: Any = None
        self._worker_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None

    @property
    def client(self) -> Any:
        if self._client is None:
            raise TemporalUnavailable("TemporalAdapter is not connected")
        return self._client

    async def connect(self, *, start_worker: bool = True) -> None:
        if (
            self._client is not None
            or self._worker is not None
            or self._worker_task is not None
            or (self._close_task is not None and not self._close_task.done())
        ):
            raise TemporalUnavailable("TemporalAdapter already owns a connection or worker")
        if not TEMPORAL_SDK_AVAILABLE:
            raise TemporalUnavailable("temporalio SDK is not installed")
        if not self.endpoint or not self.namespace:
            raise TemporalUnavailable("ACS_P1_TEMPORAL_ENDPOINT and ACS_P1_TEMPORAL_NAMESPACE are required")
        try:
            self._client = await Client.connect(self.endpoint, namespace=self.namespace)
            if start_worker:
                self._worker = Worker(
                    self._client,
                    task_queue=self.task_queue,
                    workflows=[SubmittedOperationWorkflow],
                    activities=[submitted_operation_activity],
                    identity=self.worker_identity,
                )
                self._worker_task = asyncio.create_task(self._worker.run())
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            await self.close()
            raise
        except (RPCError, RuntimeError, TypeError, ValueError) as exc:
            await self.close()
            raise TemporalUnavailable(f"unable to connect to Temporal at {self.endpoint}") from exc

    async def submit_operation(
        self,
        operation_id: str,
        payload: dict[str, Any],
        *,
        wait: bool = True,
    ) -> TemporalOperation | Any:
        if not operation_id:
            raise ValueError("operation_id must not be empty")
        payload_copy = dict(payload)
        payload_hash = canonical_payload_hash(payload_copy)
        memo = {"acs_p1_payload_hash": payload_hash}
        try:
            handle = await self.client.start_workflow(
                SubmittedOperationWorkflow.run,
                payload_copy,
                id=operation_id,
                task_queue=self.task_queue,
                execution_timeout=timedelta(minutes=5),
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
                retry_policy=RetryPolicy(maximum_attempts=1),
                memo=memo,
            )
        except WorkflowAlreadyStartedError:
            handle = await self._existing_handle(operation_id, payload_hash)
        except (RPCError, RuntimeError, TypeError, ValueError) as exc:
            raise TemporalUnavailable(f"Temporal operation {operation_id} failed to start") from exc
        try:
            if not wait:
                return handle
            result = await handle.result()
            run_id = (
                getattr(handle, "result_run_id", None)
                or getattr(handle, "first_execution_run_id", None)
                or getattr(handle, "run_id", None)
            )
            if not run_id:
                raise TemporalUnavailable("Temporal returned no run identifier")
            return TemporalOperation(
                operation_id=operation_id,
                workflow_id=handle.id,
                run_id=run_id,
                status=str(result.get("status", "unknown")),
                result=dict(result),
            )
        except TemporalUnavailable:
            raise
        except (RuntimeError, TypeError, ValueError) as exc:
            raise TemporalUnavailable(f"Temporal operation {operation_id} failed") from exc

    async def _existing_handle(self, operation_id: str, payload_hash: str) -> Any:
        try:
            description = await self.client.get_workflow_handle(operation_id).describe()
            memo = await description.memo()
        except (RPCError, RuntimeError, TypeError, ValueError) as exc:
            raise TemporalUnavailable(f"Temporal operation {operation_id} cannot be recovered") from exc
        existing_hash = memo.get("acs_p1_payload_hash")
        if not isinstance(existing_hash, str) or existing_hash != payload_hash:
            raise TemporalUnavailable(f"Temporal operation {operation_id} conflicts with existing input")
        return self.client.get_workflow_handle(operation_id, run_id=description.run_id)

    async def readback(self, operation_id: str) -> dict[str, Any]:
        try:
            handle = self.client.get_workflow_handle(operation_id)
            return dict(await handle.query("state"))
        except (RPCError, RuntimeError):
            try:
                description = await self.client.get_workflow_handle(operation_id).describe()
                completed = self.client.get_workflow_handle(operation_id, run_id=description.run_id)
                result = await completed.result()
                return dict(result)
            except (RPCError, RuntimeError, TypeError, ValueError) as result_exc:
                raise TemporalUnavailable(f"Temporal operation {operation_id} is unavailable") from result_exc

    async def close(self) -> None:
        if self._close_task is None or self._close_task.done():
            self._close_task = asyncio.create_task(self._shutdown_owned_worker())
            # A caller may be cancelled before shutdown finishes. Retain the
            # task for recovery and observe its error even without a waiter.
            self._close_task.add_done_callback(self._observe_shutdown)
        await asyncio.shield(self._close_task)

    @staticmethod
    def _observe_shutdown(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    async def _shutdown_owned_worker(self) -> None:
        worker = self._worker
        task = self._worker_task
        if worker is not None:
            await worker.shutdown()
        try:
            if task is not None:
                await task
        except asyncio.CancelledError:
            if task is None or not task.cancelled():
                raise
        finally:
            # Shutdown has completed. A terminal run error still propagates,
            # but must not permanently retain already-stopped capacity.
            if task is None or task.done():
                self._worker = None
                self._worker_task = None
                self._client = None
