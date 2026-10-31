"""Real default recovery worker/PG/SQLite; Native callbacks are explicit fixtures."""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time

from runtime.communication_dispatch import maintain_communication_deliveries
from runtime.delivery_models import EndpointBindingRequest
from runtime.delivery_node import LocalNodeEndpoint
from runtime.node import NodeJournal
from runtime_tests.test_communication import AcceptingDriver, call, send, wait
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_delivery import command

comm = comm_fixture


async def eventually(predicate, *, seconds=4):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return
        await asyncio.sleep(0.025)
    raise AssertionError("independent pending message did not progress")


async def stop(task):
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def test_adapter_exception_on_first_page_cannot_starve_a_later_peer(comm):
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("controlled unexpected Adapter failure before Native")

    comm.dispatcher.service.endpoints["endpoint-b"].deliver = unavailable
    requests = [send(comm, content=f"First-page failure {number}")["data"] for number in range(16)]
    healthy = send(comm, to="c", content="An independent peer must still receive")["data"]

    async def run():
        task = asyncio.create_task(
            maintain_communication_deliveries(comm.clients["a"].service.service)
        )
        try:
            await eventually(lambda: bool(comm.drivers["c"].calls), seconds=5)
        finally:
            await stop(task)

    asyncio.run(run())
    assert len(comm.drivers["c"].calls) == 1 and not comm.drivers["b"].calls
    with comm.authority._connect() as connection:
        assert connection.execute(
            "SELECT state FROM delivery_messages WHERE message_id=%s", (healthy["message_id"],)
        ).fetchone() == ("delivered",)
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone() == (17,)
        assert connection.execute(
            "SELECT count(*) FROM delivery_receipts WHERE message_id=ANY(%s) AND layer='runtime_dispatched'",
            ([item["message_id"] for item in requests],),
        ).fetchone() == (0,)


def test_held_native_ack_cannot_delay_an_independent_peer(comm):
    entered, release = threading.Event(), threading.Event()
    original = comm.drivers["b"].invoke

    def held(invocation):
        observation = original(invocation)
        entered.set()
        assert release.wait(8), "test must release its held ACK"
        return observation

    comm.drivers["b"].invoke = held
    first = send(comm, content="Hold only this target's ACK")["data"]
    second = send(comm, to="c", content="This target is independent")["data"]

    def first_finished():
        with comm.authority._connect() as connection:
            return connection.execute(
                "SELECT state FROM delivery_messages WHERE message_id=%s", (first["message_id"],)
            ).fetchone()[0] in {"delivered", "uncertain"}

    async def run():
        task = asyncio.create_task(
            maintain_communication_deliveries(comm.clients["a"].service.service)
        )
        try:
            await eventually(entered.is_set)
            await eventually(lambda: bool(comm.drivers["c"].calls), seconds=2)
            assert not release.is_set()
        finally:
            release.set()
            await eventually(first_finished)
            await stop(task)

    asyncio.run(run())
    assert len(comm.drivers["b"].calls) == len(comm.drivers["c"].calls) == 1
    with comm.authority._connect() as connection:
        assert connection.execute(
            "SELECT state FROM delivery_messages WHERE message_id=%s", (second["message_id"],)
        ).fetchone() == ("delivered",)
        assert connection.execute("SELECT to_regclass('work_items')").fetchone() == (None,)


def test_unclassified_error_after_native_marker_never_invokes_again(comm):
    original = comm.drivers["b"].invoke

    def lost_result(invocation):
        original(invocation)
        raise RuntimeError("controlled failure after the possible Native effect")

    comm.drivers["b"].invoke = lost_result
    endpoint = comm.dispatcher.service.endpoints["endpoint-b"]
    original_deliver = endpoint.deliver

    def lost_transport_result(*args, **kwargs):
        original_deliver(*args, **kwargs)
        raise RuntimeError("controlled unclassified Adapter result after Native")

    endpoint.deliver = lost_transport_result
    first = send(comm)["data"]
    send(comm, to="c")

    def uncertain():
        with comm.authority._connect() as connection:
            return connection.execute(
                "SELECT state FROM delivery_messages WHERE message_id=%s", (first["message_id"],)
            ).fetchone() == ("uncertain",)

    async def run():
        task = asyncio.create_task(
            maintain_communication_deliveries(comm.clients["a"].service.service)
        )
        try:
            await eventually(uncertain)
            await eventually(lambda: bool(comm.drivers["c"].calls))
            await asyncio.sleep(1.1)
            assert len(comm.drivers["b"].calls) == 1
        finally:
            await stop(task)

    asyncio.run(run())
    assert wait(comm, "a", first["message_handle"])["state"] == "timeout"
    with comm.authority._connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM delivery_attempts WHERE message_id=%s", (first["message_id"],)
        ).fetchone() == (1,)


def test_unclassified_pre_native_failure_uses_the_existing_attempt_budget(comm):
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("controlled temporary Adapter preparation failure")

    comm.dispatcher.service.endpoints["endpoint-b"].deliver = unavailable
    request = send(comm, content="Keep this original communication despite delivery failure")[
        "data"
    ]

    def exhausted():
        with comm.authority._connect() as connection:
            return connection.execute(
                "SELECT state FROM delivery_messages WHERE message_id=%s", (request["message_id"],)
            ).fetchone() == ("budget_exhausted",)

    async def run():
        task = asyncio.create_task(
            maintain_communication_deliveries(comm.clients["a"].service.service)
        )
        try:
            await eventually(exhausted, seconds=7)
        finally:
            await stop(task)

    asyncio.run(run())
    assert not comm.drivers["b"].calls
    assert (
        call(comm, "b", "read_message", handle=request["message_handle"])["data"]["content"]
        == "Keep this original communication despite delivery failure"
    )
    assert wait(comm, "a", request["message_handle"])["state"] == "timeout"
    with comm.authority._connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM delivery_attempts WHERE message_id=%s", (request["message_id"],)
        ).fetchone() == (3,)


def test_confirmed_native_ack_survives_an_unclassified_adapter_result(comm):
    endpoint = comm.dispatcher.service.endpoints["endpoint-b"]
    original = endpoint.deliver

    def lost_result(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("controlled lost result after a persisted Native ACK")

    endpoint.deliver = lost_result
    request = send(comm)["data"]
    identity = {
        "tenant_id": comm.authority.tenant_id,
        "message_id": request["message_id"],
        "operation_id": request["operation_id"],
    }
    result = comm.dispatcher.dispatch(identity)
    assert result["status"] == "delivered", result
    assert comm.dispatcher.dispatch(identity)["status"] == "delivered"
    assert len(comm.drivers["b"].calls) == 1
    assert wait(comm, "a", request["message_handle"])["state"] == "timeout"
    with comm.authority._connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM delivery_attempts WHERE message_id=%s", (request["message_id"],)
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM delivery_receipts WHERE message_id=%s AND layer='runtime_acknowledged'",
            (request["message_id"],),
        ).fetchone() == (1,)


def test_default_worker_bounds_inflight_native_calls_to_four(comm, tmp_path):
    from datetime import timedelta

    lock = threading.Lock()
    release, full = threading.Event(), threading.Event()
    active = peak = started = 0
    members = [
        {"agent_slot_id": f"load-{number}", "principal_ref": f"load-principal:{number}"}
        for number in range(8)
    ]
    call(comm, "a", "configure_team", prepare_native=False, members=members)
    for member in members:
        driver = AcceptingDriver()

        def held(invocation, invoke=driver.invoke):
            nonlocal active, peak, started
            observation = invoke(invocation)
            with lock:
                active += 1
                started += 1
                peak = max(peak, active)
                if active == 4:
                    full.set()
            try:
                assert release.wait(12), "test must release bounded calls"
                return observation
            finally:
                with lock:
                    active -= 1

        driver.invoke = held
        slot = member["agent_slot_id"]
        endpoint_id = "endpoint-" + slot
        endpoint = LocalNodeEndpoint(
            NodeJournal(tmp_path / (slot + ".sqlite")), "local-scope", slot, driver
        )
        comm.authority._delivery_endpoints[endpoint_id] = endpoint
        comm.dispatcher.service.endpoints[endpoint_id] = endpoint
        comm.dispatcher.service.bind_endpoint(
            command(comm.authority, "message.bind", endpoint_id),
            EndpointBindingRequest(
                scope_id="local-scope",
                agent_slot_id=slot,
                expires_at=comm.authority.canonical_now() + timedelta(minutes=5),
            ),
        )
    requests = [
        call(
            comm,
            "a",
            "send_message",
            to="collaborator:project-alpha:" + member["agent_slot_id"],
            content="Bounded independent receiver exercise",
        )["data"]
        for member in members
    ]

    def finished():
        with comm.authority._connect() as connection:
            return connection.execute(
                "SELECT count(*) FROM delivery_messages WHERE message_id=ANY(%s) AND state='delivered'",
                ([item["message_id"] for item in requests],),
            ).fetchone() == (8,)

    async def run():
        task = asyncio.create_task(
            maintain_communication_deliveries(comm.clients["a"].service.service)
        )
        try:
            await eventually(full.is_set, seconds=8)
            with lock:
                assert peak == started == 4
        finally:
            release.set()
            await eventually(finished, seconds=8)
            await stop(task)

    asyncio.run(run())
    assert peak == 4 and started == 8
