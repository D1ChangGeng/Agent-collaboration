from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

try:
    from temporalio import activity, workflow
    from temporalio.client import Client
    from temporalio.common import RetryPolicy
    from temporalio.worker import Worker
except ImportError:
    activity = workflow = None  # type: ignore[assignment]
    Client = RetryPolicy = Worker = None  # type: ignore[assignment,misc]

TEMPORAL_SDK_AVAILABLE = activity is not None


class TemporalUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TemporalOperation:
    operation_id: str
    workflow_id: str
    run_id: str
    status: str
    result: dict[str, Any]


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

    @property
    def client(self) -> Any:
        if self._client is None:
            raise TemporalUnavailable("TemporalAdapter is not connected")
        return self._client

    async def connect(self, *, start_worker: bool = True) -> None:
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
        except Exception as exc:
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
        try:
            handle = await self.client.start_workflow(
                SubmittedOperationWorkflow.run,
                dict(payload),
                id=operation_id,
                task_queue=self.task_queue,
                execution_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            if not wait:
                return handle
            result = await handle.result()
            run_id = getattr(handle, "result_run_id", None) or getattr(handle, "first_execution_run_id", None)
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
        except Exception as exc:
            raise TemporalUnavailable(f"Temporal operation {operation_id} failed") from exc

    async def readback(self, operation_id: str) -> dict[str, Any]:
        try:
            handle = self.client.get_workflow_handle(operation_id)
            return dict(await handle.query("state"))
        except Exception as exc:
            raise TemporalUnavailable(f"Temporal operation {operation_id} is unavailable") from exc

    async def close(self) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                return
            self._worker_task = None
        self._worker = None
        self._client = None
