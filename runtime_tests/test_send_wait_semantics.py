"""Real explicit replies with a virtual observation clock, never fabricated answers.

Retired Work/receipt tests remain in fixtures/legacy-send-wait-v6.py.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import anyio

from runtime import communication as module
from runtime.mcp_runtime import McpRuntime
from runtime_tests.test_communication import call, send
from runtime_tests.test_communication import comm as comm_fixture

comm = comm_fixture


def wait_service(f, monkeypatch, *, complete_after=90, uncertain=False):
    elapsed = [0.0]
    request = send(f, activation="invoke" if uncertain else "message_only")["data"]
    if uncertain:
        def lose_ack(invocation):
            f.drivers["b"].calls.append(invocation)
            raise OSError("controlled lost native ACK")
        f.drivers["b"].invoke = lose_ack
        assert f.dispatcher.dispatch({"tenant_id": f.authority.tenant_id, "message_id": request["message_id"],
                                     "operation_id": request["operation_id"]})["status"] == "uncertain"
    original = f.clients["a"].service.execute
    sent_reply = []
    def observe(name, args, credential):
        if name == "read_message" and elapsed[0] >= complete_after and not sent_reply:
            sent_reply.append(send(f, "b", "a", "A real explicit reply", reply_to=[request["message_handle"]], activation="message_only"))
        return original(name, args, credential)
    monkeypatch.setattr(f.clients["a"].service, "execute", observe)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: elapsed[0],
        sleep=lambda _seconds: elapsed.__setitem__(0, elapsed[0]+31)))
    return request["message_handle"], elapsed


def test_default_wait_reaches_completion_after_the_previous_thirty_second_window(comm, monkeypatch):
    request, elapsed = wait_service(comm, monkeypatch)
    result = call(comm, "a", "wait_for_response", handles=[request])
    assert result["state"] == "satisfied" and elapsed[0] >= 90
    assert result["data"]["satisfied"] == [request]


def test_explicit_wait_budget_returns_pending_without_cancelling_tracking(comm, monkeypatch):
    request, _elapsed = wait_service(comm, monkeypatch)
    result = call(comm, "a", "wait_for_response", handles=[request], timeout_seconds=31)
    assert result["state"] == "timeout" and result["data"]["pending"] == [request]
    assert call(comm, "b", "read_message", handle=request)["data"]["content"]


def test_uncertain_delivery_can_still_complete_during_default_wait(comm, monkeypatch):
    request, elapsed = wait_service(comm, monkeypatch, uncertain=True)
    assert call(comm, "a", "wait_for_response", handles=[request])["state"] == "satisfied"
    assert elapsed[0] >= 90 and len(comm.drivers["b"].calls) == 1


def test_mcp_contract_exposes_optional_wait_and_business_expiry():
    runtime = McpRuntime(SimpleNamespace(), lambda: "credential")
    assert "deadline" not in runtime.input_schema("send_message")["required"]
    assert "timeout_seconds" not in runtime.input_schema("wait_for_response")["required"]
    for value in (None, 0, 31, 3600):
        runtime._validate("wait_for_response", {"project_id": "project-alpha",
            "handles": ["message:project-alpha:original"], "timeout_seconds": value})


def test_cancelled_mcp_wait_releases_its_worker_without_a_fixed_wait_deadline(comm, monkeypatch):
    done, entered = threading.Event(), threading.Event()
    request = send(comm, activation="message_only")["data"]["message_handle"]
    original = comm.clients["a"].service.execute
    def observe(name, args, credential):
        if name == "read_message":
            entered.set()
        return original(name, args, credential)
    monkeypatch.setattr(comm.clients["a"].service, "execute", observe)
    def wait():
        try:
            comm.clients["a"].service._wait({"project_id": "project-alpha", "handles": [request]},
                                           comm.clients["a"].credential_provider())
        finally:
            done.set()
    async def exercise():
        async with anyio.create_task_group() as tasks:
            async def start():
                await anyio.to_thread.run_sync(wait, abandon_on_cancel=True)
            tasks.start_soon(start)
            assert await anyio.to_thread.run_sync(entered.wait, 5)
            tasks.cancel_scope.cancel()
        with anyio.CancelScope(shield=True):
            assert await anyio.to_thread.run_sync(done.wait, 5)
    anyio.run(exercise)
    assert call(comm, "b", "read_message", handle=request)["data"]["content"]
