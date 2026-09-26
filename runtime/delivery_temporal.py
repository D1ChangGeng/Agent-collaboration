from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.worker import Worker


@workflow.defn(name="AcsCommittedDelivery")
class CommittedDeliveryWorkflow:
    """Timers and retries of one committed identity; no Agent decisions."""

    def __init__(self):
        self._state = {"status": "scheduled"}

    @workflow.run
    async def run(self, identity: dict) -> dict:
        # A bounded history also covers lease contention and Worker recovery.
        # The PostgreSQL attempt/deadline budget remains the protected authority.
        for _ in range(64):
            self._state = await workflow.execute_activity(
                "acs-delivery-attempt", identity,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1),
                                         maximum_interval=timedelta(seconds=2), maximum_attempts=3),
            )
            if self._state["status"] not in ("retry_wait", "busy"):
                return self._state
            await workflow.sleep(timedelta(seconds=self._state["retry_after_seconds"]))
        self._state = {"status": "provider_wait_budget_exhausted", "identity": identity}
        return self._state

    @workflow.query(name="state")
    def state(self) -> dict:
        return dict(self._state)


class DeliveryActivities:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher

    @activity.defn(name="acs-delivery-attempt")
    async def attempt(self, identity: dict) -> dict:
        # Actual PG + Node delivery. This is deliberately not the foundation's
        # echo activity. An activity retry cannot change its committed packet.
        dispatch = asyncio.create_task(asyncio.to_thread(self.dispatcher.dispatch, identity))
        try:
            return await asyncio.shield(dispatch)
        except asyncio.CancelledError:
            # asyncio cancellation cannot stop a running worker thread. Keep the
            # Activity alive until its durable dispatcher outcome is known, then
            # let Temporal observe cancellation. A retry can only inspect that
            # committed outcome and cannot overlap the abandoned thread.
            await asyncio.gather(dispatch, return_exceptions=True)
            raise


def delivery_worker(client, task_queue, dispatcher):
    activities = DeliveryActivities(dispatcher)
    return Worker(client, task_queue=task_queue, workflows=[CommittedDeliveryWorkflow],
                  activities=[activities.attempt])


async def submit_delivery(client, task_queue, dispatcher, identity):
    # Read from committed authority storage before submitting anything to Temporal.
    # Authentication is independently repeated at actual Inbox/invoke boundaries.
    with dispatcher.service.authority._connect() as connection, connection.cursor() as cursor:
        row = dispatcher._load(cursor, identity)
        dispatcher._authorize(cursor, row)
    payload_hash = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    workflow_id = f"acs-delivery/{identity['operation_id']}"
    try:
        handle = await client.start_workflow(
            CommittedDeliveryWorkflow.run, identity, id=workflow_id, task_queue=task_queue,
            execution_timeout=timedelta(minutes=10),
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
            memo={"acs_delivery_identity_hash": payload_hash},
        )
    except WorkflowAlreadyStartedError:
        description = await client.get_workflow_handle(workflow_id).describe()
        memo = await description.memo()
        if memo.get("acs_delivery_identity_hash") != payload_hash:
            raise ValueError("existing delivery Workflow identity differs") from None
        handle = client.get_workflow_handle(workflow_id, run_id=description.run_id)
    description = await handle.describe()

    def record_reference():
        with dispatcher.service.authority._connect() as connection, connection.cursor() as cursor:
            row = dispatcher._load(cursor, identity)
            cursor.execute(
                "SELECT provider_workflow_id,provider_run_id FROM operations WHERE tenant_id=%s "
                "AND operation_id=%s FOR UPDATE",
                (row["tenant_id"], row["operation_id"]),
            )
            provider = cursor.fetchone()
            if provider is None or provider[0] != workflow_id:
                raise ValueError("delivery Workflow reference conflicts with Domain operation")
            if provider[1] is not None and provider[1] != description.run_id:
                raise ValueError("delivery Workflow run identity changed")
            cursor.execute(
                "UPDATE operations SET provider_run_id=%s WHERE tenant_id=%s AND operation_id=%s",
                (description.run_id, row["tenant_id"], row["operation_id"]),
            )

    persist = asyncio.create_task(asyncio.to_thread(record_reference))
    try:
        await asyncio.shield(persist)
    except asyncio.CancelledError:
        # The Workflow exists by this point. Finish its same-Run Domain link so
        # cancellation cannot strand a started Run without its durable reference.
        await asyncio.gather(persist, return_exceptions=True)
        raise
    return handle
