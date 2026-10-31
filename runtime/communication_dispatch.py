"""Bounded maintenance of committed natural messages, independent of Temporal."""

from __future__ import annotations

import asyncio
import logging

from runtime.communication_faults import queue_communication_notices
from runtime.delivery import DeliveryDispatcher, DeliveryService

log = logging.getLogger(__name__)
MAX_INFLIGHT = 4


def _pending(authority, exclude, limit):
    with authority._connect() as connection:
        rows = connection.execute(
            "SELECT tenant_id,message_id,operation_id FROM delivery_messages "
            "WHERE tenant_id=%s AND packet_json->>'schema_version' IN ('acs-message/1','acs-notice/1') "
            "AND state IN ('queued','retry_wait','delivering') AND next_attempt_at<=clock_timestamp() "
            "AND NOT (message_id=ANY(%s::text[])) ORDER BY next_attempt_at,created_at,message_id LIMIT %s",
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
    if getattr(authority, "_communication_maintenance_mode", "auto") == "external":
        return
    if not callable(getattr(authority, "_connect", None)) or not hasattr(
        authority, "_delivery_endpoints"
    ):
        return  # Metadata-only HTTP use has no storage/dispatch capability.
    dispatcher = DeliveryDispatcher(DeliveryService(authority, authority._delivery_endpoints))
    running = {}

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

    authority._communication_maintenance_running = True
    next_housekeeping = 0
    try:
        while True:
            for message_id, task in list(running.items()):
                if task.done():
                    await task
                    del running[message_id]
            if asyncio.get_running_loop().time() >= next_housekeeping:
                for operation in (prune_expired_waits, queue_communication_notices):
                    try:
                        await asyncio.to_thread(operation, authority)
                    except Exception as error:  # noqa: BLE001 - housekeeping is independent of message delivery.
                        log.warning(
                            "Communication maintenance unavailable: %s", type(error).__name__
                        )
                next_housekeeping = asyncio.get_running_loop().time() + 0.5
            try:
                available = MAX_INFLIGHT - len(running)
                if available:
                    for identity in await asyncio.to_thread(
                        _pending, authority, running, available
                    ):
                        running[identity["message_id"]] = asyncio.create_task(deliver(identity))
            except Exception as error:  # noqa: BLE001 - committed messages survive a failed maintenance cycle.
                log.warning("Communication maintenance unavailable: %s", type(error).__name__)
            if running:
                await asyncio.wait(
                    running.values(), timeout=0.5, return_when=asyncio.FIRST_COMPLETED
                )
            else:
                await asyncio.sleep(0.5)
    finally:
        for task in running.values():
            task.cancel()
        await asyncio.gather(*running.values(), return_exceptions=True)
        authority._communication_maintenance_running = False
