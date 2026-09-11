from __future__ import annotations

import asyncio
import json
import os
import uuid

import pytest

from runtime.temporal import TemporalAdapter, TemporalUnavailable


class ControlledWorker:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.stopped = asyncio.Event()
        self.calls = 0
        self.fail_once = False

    async def run(self) -> None:
        await self.stopped.wait()

    async def shutdown(self) -> None:
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("injected shutdown failure")
        self.stopped.set()


def attach_worker(adapter: TemporalAdapter, worker: ControlledWorker) -> asyncio.Task[None]:
    adapter._client = object()
    adapter._worker = worker
    adapter._worker_task = asyncio.create_task(worker.run())
    return adapter._worker_task


def test_cancelled_close_retains_worker_and_coalesces_other_waiters() -> None:
    async def scenario() -> None:
        adapter = TemporalAdapter()
        worker = ControlledWorker()
        run = attach_worker(adapter, worker)
        first = asyncio.create_task(adapter.close())
        await worker.entered.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert adapter._worker is worker
        assert adapter._worker_task is run and not run.done()
        assert adapter._close_task is not None and not adapter._close_task.done()
        with pytest.raises(TemporalUnavailable, match="already owns"):
            await adapter.connect()
        second = asyncio.create_task(adapter.close())
        third = asyncio.create_task(adapter.close())
        await asyncio.sleep(0)
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        worker.release.set()
        await asyncio.wait_for(third, 2)
        assert worker.calls == 1
        assert run.done()
        assert adapter._worker is None and adapter._worker_task is None
        assert adapter._client is None
        await adapter.close()

    asyncio.run(scenario())


def test_shutdown_failure_retains_references_for_explicit_retry() -> None:
    async def scenario() -> None:
        adapter = TemporalAdapter()
        worker = ControlledWorker()
        worker.fail_once = True
        worker.release.set()
        run = attach_worker(adapter, worker)
        with pytest.raises(RuntimeError, match="injected shutdown failure"):
            await adapter.close()
        assert adapter._worker is worker and adapter._worker_task is run
        assert not run.done() and adapter._client is not None
        await adapter.close()
        assert worker.calls == 2 and run.done()
        assert adapter._worker is None and adapter._client is None

    asyncio.run(scenario())


def test_terminal_worker_failure_releases_stopped_capacity() -> None:
    async def scenario() -> None:
        adapter = TemporalAdapter()
        worker = ControlledWorker()
        worker.release.set()

        async def failed_run() -> None:
            await worker.stopped.wait()
            raise RuntimeError("injected run failure")

        adapter._client = object()
        adapter._worker = worker
        run = adapter._worker_task = asyncio.create_task(failed_run())
        with pytest.raises(RuntimeError, match="injected run failure"):
            await adapter.close()
        assert run.done() and worker.stopped.is_set()
        assert adapter._worker is None and adapter._worker_task is None
        assert adapter._client is None
        await adapter.close()

    asyncio.run(scenario())


def test_cancelled_worker_is_observed_before_references_are_released() -> None:
    async def scenario() -> None:
        adapter = TemporalAdapter()
        worker = ControlledWorker()
        worker.release.set()
        run = attach_worker(adapter, worker)
        run.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run
        await adapter.close()
        assert worker.stopped.is_set()
        assert adapter._worker_task is None and adapter._worker is None

    asyncio.run(scenario())


def test_real_worker_shutdown_survives_cancelled_waiter(monkeypatch: pytest.MonkeyPatch) -> None:
    endpoint = os.environ.get("ACS_P1_TEMPORAL_ENDPOINT")
    namespace = os.environ.get("ACS_P1_TEMPORAL_NAMESPACE")
    if not endpoint or not namespace:
        pytest.skip("NOT_RUN: isolated Temporal endpoint and namespace required")

    async def scenario() -> None:
        identity = uuid.uuid4().hex
        adapter = TemporalAdapter(endpoint, namespace=namespace, task_queue=f"close-{identity}")
        await adapter.connect()
        operation_id = f"management-close-{identity}"
        payload = {"scenario": "real-worker-close-cancellation", "operation_id": operation_id}
        try:
            operation = await adapter.submit_operation(operation_id, payload)
        except BaseException:
            await adapter.close()
            raise
        worker, run = adapter._worker, adapter._worker_task
        entered, release = asyncio.Event(), asyncio.Event()
        original_shutdown = worker.shutdown

        async def delayed_shutdown() -> None:
            entered.set()
            await release.wait()
            await original_shutdown()

        monkeypatch.setattr(worker, "shutdown", delayed_shutdown)
        closing = asyncio.create_task(adapter.close())
        try:
            await asyncio.wait_for(entered.wait(), 5)
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
            assert adapter._worker is worker and adapter._worker_task is run
            assert run is not None and not run.done()
        finally:
            release.set()
            await asyncio.wait_for(adapter.close(), 30)
        assert run.done() and not run.cancelled()
        assert adapter._worker is None and adapter._worker_task is None
        reader = TemporalAdapter(endpoint, namespace=namespace)
        await reader.connect(start_worker=False)
        try:
            replay = await reader.submit_operation(operation_id, payload)
            assert replay.run_id == operation.run_id
            assert replay.result == operation.result
            print(json.dumps({"scenario": "real-worker-close-cancellation", "operation_id": operation_id, "run_id": operation.run_id, "replay_run_id": replay.run_id, "worker_task_done": run.done(), "references_released": adapter._worker is None}))
        finally:
            await reader.close()

    asyncio.run(scenario())
