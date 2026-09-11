"""Temporal delivery lifecycle tests that do not require a Temporal server."""
from __future__ import annotations

import asyncio
from threading import Event

import pytest

from runtime.delivery_temporal import DeliveryActivities


def test_cancelled_activity_waits_for_dispatch_thread_to_finish():
    entered = Event()
    release = Event()
    finished = Event()

    class BlockingDispatcher:
        def dispatch(self, identity):
            entered.set()
            assert release.wait(5)
            finished.set()
            return {"status": "delivered", "identity": identity}

    async def exercise():
        task = asyncio.create_task(DeliveryActivities(BlockingDispatcher()).attempt({"operation_id": "op"}))
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert entered.is_set()
        task.cancel()
        await asyncio.sleep(0.05)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert finished.is_set()
