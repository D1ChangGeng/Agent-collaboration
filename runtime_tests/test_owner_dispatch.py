"""Transient provider loss does not stop the owner management service."""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from temporalio.service import RPCError, RPCStatusCode

from runtime.owner_dispatch import maintain_owner_deliveries


def test_owner_maintenance_reconnects_after_temporal_rpc_loss():
    authority=SimpleNamespace(access_mode="owner",tenant_id="owner-tenant",
        context=SimpleNamespace(authority_incarnation="owner-1"),_delivery_endpoints={})
    service=SimpleNamespace(authority=authority)
    attempts=[]
    recovered=asyncio.Event()
    async def connect(endpoint):
        attempts.append(endpoint)
        if len(attempts)==1:
            raise RPCError("fixture provider unavailable",RPCStatusCode.UNAVAILABLE,b"")
        return object()
    class Worker:
        async def __aenter__(self):
            recovered.set()
        async def __aexit__(self,*args):
            pass
    async def run():
        with patch("runtime.owner_dispatch.Client.connect",side_effect=connect), \
             patch("runtime.owner_dispatch.delivery_worker",return_value=Worker()), \
             patch("runtime.owner_dispatch.DeliveryDispatcher") as dispatcher:
            dispatcher.return_value.pending.return_value=[]
            task=asyncio.create_task(maintain_owner_deliveries(service,SimpleNamespace(temporal_endpoint="fixture:7233")))
            try:
                await asyncio.wait_for(recovered.wait(),5)
                assert len(attempts)==2
                assert not task.done()
            finally:
                task.cancel()
                await asyncio.gather(task,return_exceptions=True)
    asyncio.run(run())
