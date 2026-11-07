"""Bounded maintenance of committed natural messages, independent of Temporal."""

from __future__ import annotations

import asyncio
import logging

from runtime.communication_event_storage import maintain_event_publication, maintain_event_retention
from runtime.communication_faults import queue_communication_notices
from runtime.communication_snapshot_storage import prune_snapshot_storage
from runtime.communication_wait_ingress import reclaim_wait_ingress
from runtime.delivery import DeliveryDispatcher, DeliveryService

log = logging.getLogger(__name__)
MAX_INFLIGHT = 4


def prune_client_snapshots(authority):
    if not (getattr(authority, "_communication_events_enabled", False)
            or getattr(authority, "_communication_snapshot_storage_available", False)):
        return 0
    with authority._connect() as connection:
        return prune_snapshot_storage(connection, tenant_id=authority.tenant_id, limit=100)


def prune_attachment_staging(authority):
    if not getattr(authority, "_communication_attachment_storage_available", False):
        return 0
    from runtime.communication_attachment_storage import expire_attachment_staging

    with authority._connect() as connection:
        return expire_attachment_staging(connection, tenant_id=authority.tenant_id, limit=100)


def _pending(authority, exclude, limit):
    with authority._connect() as connection:
        rows = connection.execute(
            "SELECT m.tenant_id,m.message_id,m.operation_id FROM delivery_messages m JOIN outbox o "
            "USING(tenant_id,message_id,operation_id) WHERE m.tenant_id=%s AND o.topic='message.delivery' "
            "AND m.packet_json->>'schema_version' IN ('acs-message/1','acs-notice/1') "
            "AND (m.state IN ('queued','retry_wait','delivering') "
            "OR o.payload->'receiver_wake'->'lifecycle'->>'phase'='executing') AND m.next_attempt_at<=clock_timestamp() "
            "AND NOT (m.message_id=ANY(%s::text[])) ORDER BY m.next_attempt_at,m.created_at,m.message_id LIMIT %s",
            (authority.tenant_id, list(exclude), limit),
        ).fetchall()
    return [
        dict(zip(("tenant_id", "message_id", "operation_id"), row, strict=True)) for row in rows
    ]


def _pace_unobserved(authority, identity):
    """Yield a failing/busy candidate without changing its facts or dispatch fence."""
    with authority._connect() as connection:
        connection.execute(
            "UPDATE delivery_messages SET next_attempt_at=GREATEST(next_attempt_at,"
            "clock_timestamp()+retry_delay_seconds*interval '1 second') WHERE tenant_id=%s AND message_id=%s "
            "AND operation_id=%s AND state IN ('queued','retry_wait','delivering') "
            "AND packet_json->>'schema_version' IN ('acs-message/1','acs-notice/1')",
            (authority.tenant_id, identity["message_id"], identity["operation_id"]),
        )


def prune_expired_waits(authority, *, limit=64):
    """Release expired observation leases, never messages or delivery fences."""
    if type(limit) is not int or not 1 <= limit <= 256:
        raise ValueError("invalid wait cleanup bound")
    with authority._connect() as connection:
        return connection.execute(
            "WITH expired AS (SELECT tenant_id,project_id,waiter_id,request_id "
            "FROM communication_waits WHERE tenant_id=%s AND expires_at<=clock_timestamp() "
            "ORDER BY expires_at LIMIT %s FOR UPDATE SKIP LOCKED) "
            "DELETE FROM communication_waits w USING expired e WHERE "
            "(w.tenant_id,w.project_id,w.waiter_id,w.request_id)=(e.tenant_id,e.project_id,e.waiter_id,e.request_id)",
            (authority.tenant_id, limit),
        ).rowcount


async def maintain_communication_deliveries(service):
    authority = service.authority
    external = getattr(authority, "_communication_maintenance_mode", "auto") == "external"
    if external and not (getattr(authority, "_communication_events_enabled", False)
            or getattr(authority, "_communication_event_storage_available", False)
            or getattr(authority, "_communication_snapshot_storage_available", False)
            or getattr(authority, "_communication_attachment_storage_available", False)):
        return
    if not callable(getattr(authority, "_connect", None)) or not hasattr(
        authority, "_delivery_endpoints"
    ):
        return  # Metadata-only HTTP use has no storage/dispatch capability.
    dispatcher = None if external else DeliveryDispatcher(DeliveryService(authority, authority._delivery_endpoints))
    running = {}
    lifecycle_running = {}
    from runtime.receiver_lifecycle_maintenance import (
        MAX_LIFECYCLE_INFLIGHT,
        advance_lifecycle_work,
        claim_lifecycle_work,
        finish_lifecycle_work,
    )

    lifecycle_enabled = (not external and bool(getattr(authority, "_receiver_lifecycle_transports", {}))
        and getattr(authority, "_receiver_lifecycle_catalog", None) is not None)

    async def continue_lifecycle(work):
        finished = False
        try:
            await asyncio.to_thread(advance_lifecycle_work, service, work)
            finished = True
        except Exception as error:  # noqa: BLE001 - preserve the accepted operation and isolate peers.
            finished = True
            log.warning("Receiver lifecycle continuation unavailable: %s", type(error).__name__)
        finally:
            # Cancellation cannot cancel a Native request running in a thread.
            # Keep its durable lease until expiry instead of allowing overlap.
            if finished:
                try:
                    await asyncio.to_thread(finish_lifecycle_work, authority, work)
                except Exception as error:  # noqa: BLE001 - the original lease expires durably.
                    log.warning("Receiver lifecycle scheduling unavailable: %s", type(error).__name__)

    async def deliver(identity):
        try:
            result = await asyncio.to_thread(dispatcher.dispatch, identity)
            if result.get("status") != "busy":
                return
        except Exception as error:  # noqa: BLE001 - one Adapter cannot stop independent messages.
            log.warning("Communication delivery unavailable: %s", type(error).__name__)
        try:
            await asyncio.to_thread(_pace_unobserved, authority, identity)
        except Exception as error:  # noqa: BLE001 - preserve the original committed operation on DB failure.
            log.warning("Communication delivery scheduling unavailable: %s", type(error).__name__)

    authority._communication_maintenance_running = not external
    authority._communication_event_maintenance_running = True
    authority._receiver_lifecycle_maintenance_running = lifecycle_enabled
    next_housekeeping = 0
    try:
        while True:
            for message_id, task in list(running.items()):
                if task.done():
                    await task
                    del running[message_id]
            for operation_ref, task in list(lifecycle_running.items()):
                if task.done():
                    await task
                    del lifecycle_running[operation_ref]
            if asyncio.get_running_loop().time() >= next_housekeeping:
                operations = (maintain_event_publication, maintain_event_retention, prune_client_snapshots, prune_attachment_staging) if external else (
                    prune_expired_waits, reclaim_wait_ingress, queue_communication_notices, maintain_event_publication, maintain_event_retention, prune_client_snapshots, prune_attachment_staging)
                for operation in operations:
                    try:
                        await asyncio.to_thread(operation, authority)
                    except Exception as error:  # noqa: BLE001 - housekeeping is independent of message delivery.
                        log.warning(
                            "Communication maintenance unavailable: %s", type(error).__name__
                        )
                next_housekeeping = asyncio.get_running_loop().time() + 0.5
            try:
                available = 0 if external else MAX_INFLIGHT - len(running)
                if available:
                    for identity in await asyncio.to_thread(
                        _pending, authority, running, available
                    ):
                        running[identity["message_id"]] = asyncio.create_task(deliver(identity))
            except Exception as error:  # noqa: BLE001 - committed messages survive a failed maintenance cycle.
                log.warning("Communication maintenance unavailable: %s", type(error).__name__)
            try:
                slots = MAX_LIFECYCLE_INFLIGHT - len(lifecycle_running) if lifecycle_enabled else 0
                if slots:
                    work_items = await asyncio.to_thread(claim_lifecycle_work, authority,
                        exclude=lifecycle_running, limit=slots)
                    for work in work_items:
                        lifecycle_running[work.operation_ref] = asyncio.create_task(continue_lifecycle(work))
            except Exception as error:  # noqa: BLE001 - lifecycle scheduling cannot stop natural messages.
                log.warning("Receiver lifecycle scheduling unavailable: %s", type(error).__name__)
            active = [*running.values(), *lifecycle_running.values()]
            if active:
                await asyncio.wait(
                    active, timeout=0.5, return_when=asyncio.FIRST_COMPLETED
                )
            else:
                await asyncio.sleep(0.5)
    finally:
        active = [*running.values(), *lifecycle_running.values()]
        for task in active:
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)
        authority._communication_maintenance_running = False
        authority._communication_event_maintenance_running = False
        authority._receiver_lifecycle_maintenance_running = False
