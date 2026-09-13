"""One original Temporal Workflow/Run for a restricted OpenCode HostNode."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from temporalio.client import Client

from runtime.delivery import DeliveryDispatcher
from runtime.delivery_temporal import delivery_worker, submit_delivery


class OpenCodeTemporalDispatcher:
    def __init__(
        self,
        dispatcher: DeliveryDispatcher,
        *,
        endpoint: str,
        namespace: str,
        task_queue: str,
        deadline: datetime,
    ) -> None:
        if endpoint != "127.0.0.1:7239" or not namespace or not task_queue:
            raise ValueError("OpenCode Temporal route is outside reviewed loopback")
        if deadline.tzinfo is None or deadline <= datetime.now(UTC):
            raise ValueError("OpenCode original Temporal deadline is invalid")
        self.dispatcher = dispatcher
        self.service = dispatcher.service
        self.endpoint = endpoint
        self.namespace = namespace
        self.task_queue = task_queue
        self.deadline = deadline
        self.last: dict[str, Any] | None = None

    def dispatch(self, identity: dict[str, str]) -> dict[str, Any]:
        if set(identity) != {"tenant_id", "message_id", "operation_id"}:
            raise ValueError("OpenCode Temporal dispatch identity is incomplete")
        remaining = (self.deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise RuntimeError("OpenCode original Temporal deadline expired")

        async def original_run():
            client = await Client.connect(self.endpoint, namespace=self.namespace)
            async with delivery_worker(client, self.task_queue, self.dispatcher):
                handle = await submit_delivery(
                    client, self.task_queue, self.dispatcher, identity
                )
                description = await handle.describe()
                result = await asyncio.wait_for(handle.result(), timeout=remaining)
                return result, handle.id, description.run_id

        result, workflow_id, provider_run_id = asyncio.run(original_run())
        if workflow_id != "acs-delivery/" + identity["operation_id"]:
            raise RuntimeError("OpenCode original Temporal Workflow differs")
        if not isinstance(result, dict) or result.get("status") not in {
            "delivered", "uncertain", "blocked", "expired", "budget_exhausted",
        }:
            raise RuntimeError("OpenCode original Temporal result is incomplete")
        self.last = {
            "identity": dict(identity),
            "workflow_id": workflow_id,
            "provider_run_id": provider_run_id,
            "result": dict(result),
        }
        return result
