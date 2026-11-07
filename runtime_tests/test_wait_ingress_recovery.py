"""Isolated PostgreSQL wait reservations, including an actual dead MCP waiter."""
from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client import stdio as stdio_module
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import MCPError

from runtime.communication_dispatch import prune_expired_waits
from runtime.communication_wait_ingress import adopt_wait_ingress, reclaim_wait_ingress
from runtime.project_schema_state import verify_project_schema
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send, wait
from runtime_tests.test_surfaces import profile

comm = comm_fixture
ROOT = Path(__file__).resolve().parents[1]


def enable(f):
    with f.authority._connect() as connection:
        adopt_wait_ingress(connection)
    f.authority._wait_ingress_recovery_enabled = True
    for client in f.clients.values():
        client.service.service.authority._wait_ingress_recovery_enabled = True
    assert verify_project_schema(f.authority)


def reserve_reply(f, *, identity="lost-waiter"):
    original = send(f, activation="message_only")["data"]
    with f.authority._connect() as connection:
        connection.execute("INSERT INTO communication_waits VALUES (%s,'project-alpha',%s,%s,%s,clock_timestamp()+interval '5 seconds')",
            (f.authority.tenant_id, identity, original["from"], original["message_id"]))
    reply = send(f, "b", "a", "Explicit peer reply through a reserved result channel",
                 reply_to=[original["message_handle"]])["data"]
    return original, reply


def expire(f):
    with f.authority._connect() as connection:
        connection.execute("UPDATE communication_waits SET expires_at=clock_timestamp()-interval '1 second'")
        connection.execute("UPDATE communication_wait_ingress SET expires_at=clock_timestamp()-interval '1 second' WHERE state='reserved'")


def dispatch(f, reply):
    return f.dispatcher.dispatch({"tenant_id": f.authority.tenant_id,
        "message_id": reply["message_id"], "operation_id": reply["operation_id"]})


def test_unselected_orphan_reservation_releases_same_operation_once(comm):
    enable(comm)
    original, reply = reserve_reply(comm)
    assert dispatch(comm, reply)["status"] == "retry_wait"
    assert not comm.drivers["a"].calls
    expire(comm)
    assert reclaim_wait_ingress(comm.authority) == 1
    assert dispatch(comm, reply)["status"] == "delivered"
    assert dispatch(comm, reply)["status"] == "delivered"
    assert len(comm.drivers["a"].calls) == 1
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT state FROM communication_wait_ingress WHERE message_id=%s", (reply["message_id"],)).fetchone() == ("released",)
        assert connection.execute("SELECT operation_id FROM delivery_messages WHERE message_id=%s", (reply["message_id"],)).fetchone() == (reply["operation_id"],)
        assert connection.execute("SELECT count(*) FROM communication_replies WHERE request_id=%s AND reply_id=%s",
                                  (original["message_id"], reply["message_id"])).fetchone() == (1,)


def test_selected_result_is_never_reopened_after_lease_expiry(comm):
    enable(comm)
    original, reply = reserve_reply(comm)
    assert wait(comm, "a", original["message_handle"])["state"] == "satisfied"
    expire(comm)
    assert reclaim_wait_ingress(comm.authority) == 0
    assert dispatch(comm, reply)["status"] == "delivered"
    assert not comm.drivers["a"].calls
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT state FROM communication_wait_ingress WHERE message_id=%s", (reply["message_id"],)).fetchone() == ("selected",)
        assert connection.execute("SELECT evidence_json->>'model_consumption' FROM delivery_receipts "
            "WHERE message_id=%s AND layer='target_inbox_committed'", (reply["message_id"],)).fetchone() == ("unconfirmed",)


def test_live_wait_renewal_keeps_reservation_ahead_of_dispatch(comm):
    enable(comm)
    _original, reply = reserve_reply(comm)
    with comm.authority._connect() as connection:
        connection.execute("UPDATE communication_wait_ingress SET expires_at=clock_timestamp()-interval '1 second'")
        connection.execute("UPDATE delivery_messages SET next_attempt_at=clock_timestamp()-interval '1 second' WHERE message_id=%s", (reply["message_id"],))
        connection.execute("UPDATE communication_waits SET expires_at=clock_timestamp()+interval '15 seconds'")
    assert reclaim_wait_ingress(comm.authority) == 1
    assert dispatch(comm, reply)["status"] == "retry_wait"
    assert not comm.drivers["a"].calls
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT state,expires_at>clock_timestamp() FROM communication_wait_ingress").fetchone() == ("reserved", True)


def test_normal_dispatch_gates_renewed_waiter_without_housekeeping_first(comm):
    enable(comm)
    _original, reply = reserve_reply(comm)
    with comm.authority._connect() as connection:
        connection.execute("UPDATE communication_wait_ingress SET expires_at=clock_timestamp()-interval '1 second'")
        connection.execute("UPDATE delivery_messages SET next_attempt_at=clock_timestamp()-interval '1 second' WHERE message_id=%s", (reply["message_id"],))
        connection.execute("UPDATE communication_waits SET expires_at=clock_timestamp()+interval '15 seconds'")
    assert dispatch(comm, reply)["status"] == "retry_wait"
    assert not comm.drivers["a"].calls
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT attempts,next_attempt_at>clock_timestamp() FROM delivery_messages WHERE message_id=%s", (reply["message_id"],)).fetchone() == (0, True)


def test_tool_result_selection_during_preparation_fences_final_native_marker(comm, monkeypatch):
    enable(comm)
    original, reply = reserve_reply(comm)
    expire(comm)
    reclaim_wait_ingress(comm.authority)
    entered, release = Event(), Event()
    driver = comm.drivers["a"]
    prepare = driver.prepare

    def paused(value):
        entered.set()
        assert release.wait(10)
        return prepare(value)

    monkeypatch.setattr(driver, "prepare", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(dispatch, comm, reply)
        assert entered.wait(10)
        try:
            assert wait(comm, "a", original["message_handle"])["state"] == "satisfied"
        finally:
            release.set()
        assert running.result(timeout=10)["status"] == "delivered"
    assert not comm.drivers["a"].calls
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM delivery_receipts WHERE message_id=%s AND layer='runtime_dispatched'", (reply["message_id"],)).fetchone() == (0,)


def test_cleanup_cannot_reset_a_possible_native_dispatch(comm):
    enable(comm)
    _original, reply = reserve_reply(comm)
    expire(comm)
    reclaim_wait_ingress(comm.authority)
    assert dispatch(comm, reply)["status"] == "delivered"
    with comm.authority._connect() as connection:
        connection.execute("UPDATE delivery_messages SET state='uncertain' WHERE message_id=%s", (reply["message_id"],))
        connection.execute("UPDATE communication_wait_ingress SET state='reserved',expires_at=clock_timestamp()-interval '1 second'")
    reclaim_wait_ingress(comm.authority)
    assert dispatch(comm, reply)["status"] == "uncertain"
    assert len(comm.drivers["a"].calls) == 1


def test_legacy_active_wait_is_not_reclassified_as_definitely_unselected(comm):
    _original, reply = reserve_reply(comm)
    enable(comm)
    expire(comm)
    assert reclaim_wait_ingress(comm.authority) == 0
    assert dispatch(comm, reply)["status"] == "delivered"
    assert not comm.drivers["a"].calls


def test_explicit_adoption_and_bounded_cleanup(comm):
    enable(comm)
    for index in range(3):
        reserve_reply(comm, identity="orphan-" + str(index))
    expire(comm)
    assert reclaim_wait_ingress(comm.authority, limit=1) == 1
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM communication_wait_ingress WHERE state='reserved'").fetchone() == (2,)
    with pytest.raises(ValueError):
        reclaim_wait_ingress(comm.authority, limit=True)


def test_disabling_new_reservations_keeps_existing_ingress_reader_fence(comm):
    enable(comm)
    original, reply = reserve_reply(comm)
    for client in comm.clients.values():
        client.service.service.authority._wait_ingress_recovery_enabled = False
        assert verify_project_schema(client.service.service.authority)
    assert dispatch(comm, reply)["status"] == "retry_wait"
    assert wait(comm, "a", original["message_handle"])["state"] == "satisfied"
    expire(comm)
    assert reclaim_wait_ingress(comm.authority) == 0
    assert dispatch(comm, reply)["status"] == "delivered"
    assert not comm.drivers["a"].calls


def test_actual_waiter_dies_before_reply_and_no_reader_resumes_before_fallback(comm, tmp_path, monkeypatch):
    enable(comm)
    processes = []
    spawn = stdio_module._create_platform_compatible_process

    async def track(**kwargs):
        process = await spawn(**kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(stdio_module, "_create_platform_compatible_process", track)

    def parameters(name):
        client = comm.clients[name]
        config, environment, _secret = profile(tmp_path, dsn=comm.dsn, context=client.service.context,
            extra={"delivery_maintenance": "external", "wait_ingress_recovery": True})
        return StdioServerParameters(command=sys.executable, args=["-m", "runtime.project_entry", "--config", str(config),
            "--catalog", str(ROOT / "docs/runtime/p2-mcp-tool-contract.json"), "--profile", client.service.profile],
            env=environment, cwd=str(ROOT))

    async def exercise():
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
            async with (stdio_client(parameters("b"), errlog=errors) as bs, ClientSession(*bs, read_timeout_seconds=20) as b):
                await b.initialize()
                async with (stdio_client(parameters("a"), errlog=errors) as ass,
                            ClientSession(*ass, read_timeout_seconds=20) as a):
                    await a.initialize()
                    a_process = processes[-1]
                    sent = await a.call_tool("send_message", {"project_id": "project-alpha", "to": "collaborator:project-alpha:slot-b",
                        "content": "Waiter crash with no resumed reader", "activation": "message_only"})
                    original = sent.structured_content["data"]

                    async def observe():
                        try:
                            await a.call_tool("wait_for_response", {"project_id": "project-alpha", "handles": [original["message_handle"]],
                                                                  "timeout_seconds": 120})
                        except MCPError:
                            pass

                    waiting = asyncio.create_task(observe())
                    until = time.monotonic() + 10
                    while True:
                        with comm.authority._connect() as connection:
                            lease = connection.execute("SELECT waiter_id FROM communication_waits WHERE request_id=%s", (original["message_id"],)).fetchone()
                        if lease:
                            break
                        assert time.monotonic() < until
                        await asyncio.sleep(0.05)
                    a_process.kill()
                    await a_process.wait()
                    await waiting
                    replied = await b.call_tool("send_message", {"project_id": "project-alpha", "to": original["from"],
                        "content": "Reply while the dead waiter's lease is still live", "reply_to": [original["message_handle"]]})
                    assert not replied.is_error, replied.structured_content
                    reply = replied.structured_content["data"]
                    with comm.authority._connect() as connection:
                        assert connection.execute("SELECT state FROM communication_wait_ingress WHERE message_id=%s", (reply["message_id"],)).fetchone() == ("reserved",)
                    assert not comm.drivers["a"].calls
                    until = time.monotonic() + 10
                    while True:
                        with comm.authority._connect() as connection:
                            live = connection.execute("SELECT 1 FROM communication_waits WHERE waiter_id=%s AND expires_at>clock_timestamp()", (lease[0],)).fetchone()
                        if not live:
                            break
                        assert time.monotonic() < until
                        await asyncio.sleep(0.1)
                    prune_expired_waits(comm.authority)
                    reclaim_wait_ingress(comm.authority)
                    assert dispatch(comm, reply)["status"] == "delivered"
                    assert dispatch(comm, reply)["status"] == "delivered"
                    assert len(comm.drivers["a"].calls) == 1
        assert all(process.returncode is not None for process in processes)

    asyncio.run(exercise())
