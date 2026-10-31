"""Bounded maintenance of committed natural messages, independent of Temporal."""
from __future__ import annotations

import asyncio
import logging

from runtime.communication_faults import queue_communication_notices
from runtime.delivery import DeliveryDispatcher, DeliveryService

log = logging.getLogger(__name__)


async def maintain_communication_deliveries(service):
    authority = service.authority
    if getattr(authority, "_communication_maintenance_mode", "auto") == "external":
        return
    if not callable(getattr(authority, "_connect", None)) or not hasattr(authority, "_delivery_endpoints"):
        return  # Metadata-only HTTP use has no storage/dispatch capability.
    dispatcher = DeliveryDispatcher(DeliveryService(authority, authority._delivery_endpoints))
    authority._communication_maintenance_running = True
    try:
        while True:
            try:
                # Filter at the authority so this worker never resumes task-era
                # operations or starts an execution-result collector.
                def pending():
                    with authority._connect() as connection:
                        rows = connection.execute("SELECT tenant_id,message_id,operation_id FROM delivery_messages "
                            "WHERE tenant_id=%s AND packet_json->>'schema_version' IN ('acs-message/1','acs-notice/1') "
                            "AND state IN ('queued','retry_wait','delivering') AND next_attempt_at<=clock_timestamp() "
                            "ORDER BY created_at LIMIT 16", (authority.tenant_id,)).fetchall()
                    return [dict(zip(("tenant_id", "message_id", "operation_id"), row, strict=True)) for row in rows]
                await asyncio.to_thread(queue_communication_notices, authority)
                for identity in await asyncio.to_thread(pending):
                    await asyncio.to_thread(dispatcher.dispatch, identity)
            except Exception as error:  # noqa: BLE001 - committed messages survive a failed maintenance cycle.
                log.warning("Communication maintenance unavailable: %s", type(error).__name__)
            await asyncio.sleep(0.5)
    finally:
        authority._communication_maintenance_running = False
