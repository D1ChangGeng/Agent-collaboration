"""Runtime maintenance of already committed owner deliveries through Temporal."""
from __future__ import annotations

import asyncio

from temporalio.client import Client
from temporalio.service import RPCError

from runtime.delivery import DeliveryDispatcher, DeliveryService, DeliveryRejected
from runtime.errors import AuthorizationDenied, BusinessDeadlineExpired
from runtime.delivery_temporal import delivery_worker, submit_delivery


async def maintain_owner_deliveries(service, settings):
    authority = service.authority
    if authority.access_mode != "owner" or not settings.temporal_endpoint:
        return
    dispatcher = DeliveryDispatcher(DeliveryService(authority, authority._delivery_endpoints))
    queue = f"acs-owner:{authority.tenant_id}:{authority.context.authority_incarnation}"
    while True:
        try:
            client = await Client.connect(settings.temporal_endpoint)
            async with delivery_worker(client, queue, dispatcher):
                while True:
                    pending = await asyncio.to_thread(dispatcher.pending)
                    for identity in pending:
                        try:
                            await submit_delivery(client, queue, dispatcher, identity)
                        except (AuthorizationDenied, BusinessDeadlineExpired, DeliveryRejected):
                            # The dispatcher records this operation's own conclusive
                            # Domain outcome; unrelated management remains available.
                            await asyncio.to_thread(dispatcher.dispatch, identity)
                    await asyncio.sleep(0.5)
        except (OSError, ValueError, RuntimeError, RPCError):
            # Persistent Domain/Outbox state supplies the same operation on recovery.
            await asyncio.sleep(2)
