"""Actual PG wait connection lifetime, transaction release and reauthorization."""
import asyncio
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, get_ident

import pytest
from psycopg.pq import TransactionStatus

from runtime import communication, domain
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send

comm = comm_fixture


class ControlledWaitCancellation(BaseException):
    """Cancellation must keep its original exception after technical cleanup."""


@pytest.mark.parametrize("outcome", ["reply", "revoke", "cancel"])
def test_wait_reuses_only_its_request_connection_without_holding_transaction_or_caching_authority(comm, monkeypatch, outcome):
    request = send(comm, activation="message_only")["data"]
    entered, release = Event(), Event()
    state = {"thread": None, "connections": [], "observed": False}
    original_connect, original_sleep = domain.connect, communication.time.sleep

    def tracked_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        if get_ident() == state["thread"]:
            state["connections"].append(connection)
        return connection

    def paused_sleep(seconds):
        if get_ident() == state["thread"] and not state["observed"]:
            state["observed"] = True
            active = [c for c in state["connections"] if not c.closed]
            state["idle_between_polls"] = bool(active) and all(c.info.transaction_status == TransactionStatus.IDLE for c in active)
            state["backend_pid"] = active[0].info.backend_pid if active else None
            entered.set()
            assert release.wait(8)
            if outcome == "cancel":
                raise ControlledWaitCancellation
        original_sleep(seconds)

    def observe():
        state["thread"] = get_ident()
        return comm.clients["a"].call("wait_for_response", {"project_id": "project-alpha",
            "handles": [request["message_handle"]], "timeout_seconds": 8})["structuredContent"]

    monkeypatch.setattr(domain, "connect", tracked_connect)
    monkeypatch.setattr(communication.time, "sleep", paused_sleep)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(observe)
        try:
            assert entered.wait(8)
            if outcome == "reply":
                send(comm, "b", "a", "Independent reply during an observational wait",
                     reply_to=[request["message_handle"]], activation="message_only")
            elif outcome == "revoke":
                with comm.authority._connect() as connection:
                    connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                                       (comm.clients["a"].service.context.grant_ref,))
            if state["backend_pid"] is not None:
                with comm.authority._connect() as connection:
                    backend = connection.execute("SELECT state,xact_start FROM pg_stat_activity WHERE pid=%s",
                                                 (state["backend_pid"],)).fetchone()
                assert backend == ("idle", None)
        finally:
            release.set()
        if outcome == "cancel":
            with pytest.raises(ControlledWaitCancellation):
                future.result(timeout=10)
            result = None
        else:
            result = future.result(timeout=10)
    assert len(state["connections"]) == 1, "a wait request must not reopen a connection on every observation step"
    assert state["idle_between_polls"] is True
    assert all(c.closed for c in state["connections"])
    if outcome == "reply":
        assert result["state"] == "satisfied" and result["data"]["observations"][0]["reply"] is not None
    elif outcome == "revoke":
        assert result["data"]["code"] == "authorization_denied"
    assert comm.clients["a"].service.service.authority._transaction_connection is None
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM communication_waits WHERE request_id=%s",
                                  (request["message_id"],)).fetchone() == (0,)
    assert not comm.drivers["a"].calls and not comm.drivers["b"].calls


@pytest.mark.parametrize("maintenance", ["auto", "external"])
def test_actual_mcp_pending_wait_survives_concurrent_maintenance_and_receives_explicit_reply(comm, tmp_path, maintenance):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from runtime_tests.test_surfaces import profile

    root = Path(__file__).resolve().parents[1]

    def parameters(actor):
        client = comm.clients[actor]
        config, environment, _secret = profile(tmp_path, dsn=comm.dsn, context=client.service.context,
                                              extra={"delivery_maintenance": maintenance})
        return StdioServerParameters(command=sys.executable, args=["-m", "runtime.project_entry", "--config", str(config),
            "--catalog", str(root/"docs/runtime/p2-mcp-tool-contract.json"), "--profile", client.service.profile],
            env=environment, cwd=str(root))

    async def exercise():
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
            async with (stdio_client(parameters("a"), errlog=errors) as aa, ClientSession(*aa, read_timeout_seconds=20) as a,
                        stdio_client(parameters("b"), errlog=errors) as bb, ClientSession(*bb, read_timeout_seconds=20) as b):
                await a.initialize()
                await b.initialize()
                sent = await a.call_tool("send_message", {"project_id": "project-alpha", "to": "collaborator:project-alpha:slot-b",
                    "content": "Original pending wait through real MCP", "activation": "message_only"})
                assert not sent.is_error, sent.structured_content
                original = sent.structured_content["data"]
                waiting = asyncio.create_task(a.call_tool("wait_for_response", {"project_id": "project-alpha",
                    "handles": [original["message_handle"]], "timeout_seconds": 8}))
                end = time.monotonic()+8
                while True:
                    with comm.authority._connect() as connection:
                        active = connection.execute("SELECT 1 FROM communication_waits WHERE request_id=%s "
                            "AND expires_at>clock_timestamp()", (original["message_id"],)).fetchone()
                    if active:
                        break
                    assert time.monotonic() < end and not waiting.done()
                    await asyncio.sleep(0.05)
                replied = await b.call_tool("send_message", {"project_id": "project-alpha", "to": original["from"],
                    "content": "Explicit response after the first wait observation", "reply_to": [original["message_handle"]]})
                assert not replied.is_error, replied.structured_content
                observed = await waiting
                assert not observed.is_error and observed.structured_content["state"] == "satisfied", observed.structured_content
                selected = observed.structured_content["data"]["observations"][0]["reply"]
                assert selected["message_handle"] == replied.structured_content["data"]["message_handle"]
                assert original["message_handle"] in selected["reply_to"]
        assert not comm.drivers["a"].calls and not comm.drivers["b"].calls

    asyncio.run(exercise())


def test_wait_database_disconnect_keeps_original_handle_and_resumes_without_resending(comm, monkeypatch):
    request = send(comm, activation="message_only")["data"]
    entered, release = Event(), Event()
    state = {"thread": None, "connections": [], "paused": False}
    connect, sleep = domain.connect, communication.time.sleep

    def track(*args, **kwargs):
        connection = connect(*args, **kwargs)
        if get_ident() == state["thread"]:
            state["connections"].append(connection)
        return connection

    def pause(seconds):
        if get_ident() == state["thread"] and not state["paused"]:
            state["paused"] = True
            state["pid"] = state["connections"][0].info.backend_pid
            entered.set()
            assert release.wait(8)
        sleep(seconds)

    def observe():
        state["thread"] = get_ident()
        return comm.clients["a"].call("wait_for_response", {"project_id": "project-alpha",
            "handles": [request["message_handle"]], "timeout_seconds": 8})["structuredContent"]

    monkeypatch.setattr(domain, "connect", track)
    monkeypatch.setattr(communication.time, "sleep", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        waiting = pool.submit(observe)
        try:
            assert entered.wait(8)
            with comm.authority._connect() as connection:
                assert connection.execute("SELECT pg_terminate_backend(%s)", (state["pid"],)).fetchone() == (True,)
        finally:
            release.set()
        interrupted = waiting.result(timeout=10)
    assert not interrupted["ok"] and interrupted["state"] == "unknown"
    assert interrupted["data"] == {"code": "service_unavailable", "retryable": True}
    assert all(c.closed for c in state["connections"])
    reply = send(comm, "b", "a", "Explicit reply after the wait connection was lost",
                 reply_to=[request["message_handle"]], activation="message_only")["data"]
    resumed = comm.clients["a"].call("wait_for_response", {"project_id": "project-alpha",
        "handles": [request["message_handle"]], "timeout_seconds": 0})["structuredContent"]
    assert resumed["ok"] and resumed["state"] == "satisfied"
    assert resumed["data"]["observations"][0]["reply"]["message_handle"] == reply["message_handle"]
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone() == (1,)
    assert not comm.drivers["a"].calls and not comm.drivers["b"].calls
    assert comm.clients["a"].service.service.authority._transaction_connection is None
