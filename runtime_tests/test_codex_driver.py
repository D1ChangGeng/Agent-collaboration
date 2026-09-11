"""Protocol/lifecycle tests against explicit wire peers, not real model evidence."""

import io
import json
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime import codex_driver as driver_module
from runtime.codex_driver import (
    AuthorizedOperation,
    BindingIdentity,
    CodexAppServerDriver,
    DriverJournal,
    DriverRejected,
    LaunchProfile,
    OutcomeUncertain,
    file_digest,
)
from runtime.codex_jsonrpc import JsonRpcClient, RpcDisconnected, RpcError, RpcTimeout

OMIT = object()


def test_request_ids_remain_reserved_after_timeout():
    release = threading.Event()

    def delayed(peer, message):
        release.wait(1)
        return {"original": True}

    peer = WirePeer(delayed)
    client = JsonRpcClient(peer.stdout, peer.stdin)
    try:
        with pytest.raises(RpcTimeout):
            client.request("first", {}, timeout=0.01, request_id="shared")
        with pytest.raises(ValueError, match="duplicate request id"):
            client.request("second", {}, request_id="shared")
        release.set()
        assert client.events.get(timeout=1)["kind"] == "late_response"
        assert [request["method"] for request in peer.requests] == ["first"]
    finally:
        release.set()
        client.close()
        peer.close()


def test_request_identity_budget_does_not_evict_old_ids():
    peer = WirePeer(lambda peer, message: {})
    client = JsonRpcClient(peer.stdout, peer.stdin, max_requests=1)
    try:
        client.request("first", {}, request_id="first")
        with pytest.raises(ValueError, match="duplicate request id"):
            client.request("reused", {}, request_id="first")
        with pytest.raises(ValueError, match="identity budget exhausted"):
            client.request("second", {}, request_id="second")
        assert len(peer.requests) == 1
    finally:
        client.close()
        peer.close()


def test_reconciliation_preserves_acknowledged_turn_identity(native):
    d = native.driver
    d.spawn(operation("spawn"))
    acknowledged = d.invoke(operation("invoke"), "immutable request")
    native.state["turns"][0]["id"] = "replacement-turn"
    with pytest.raises(DriverRejected, match="cannot replace"):
        d.reconcile(operation("reconcile"), "invoke")
    assert d.journal.read("invoke")["result"] == acknowledged
    assert native.state["turn_calls"] == 1


def test_reconciliation_of_same_ack_does_not_rewrite_receipt(native):
    d = native.driver
    d.spawn(operation("spawn"))
    acknowledged = d.invoke(operation("invoke"), "immutable request")
    assert d.reconcile(operation("reconcile"), "invoke") == acknowledged
    assert d.journal.read("invoke")["result"] == acknowledged


class WirePeer:
    """Real socket-backed JSONL streams and a deliberately synthetic native peer."""

    def __init__(self, handler):
        self.client_socket, self.server_socket = socket.socketpair()
        self.stdout = self.client_socket.makefile("rb")
        self.stdin = self.client_socket.makefile("wb")
        self.reader = self.server_socket.makefile("rb")
        self.writer = self.server_socket.makefile("wb")
        self.stderr = io.BytesIO(b"synthetic transport diagnostics")
        self.handler = handler
        self.requests, self.responses = [], []
        self.send_lock = threading.Lock()
        self.pid = 12345  # Explicit fixture ID, never an OS process observation.
        self.closed = False
        threading.Thread(target=self._serve, daemon=True).start()

    def send(self, message):
        with self.send_lock:
            self.writer.write(json.dumps(message).encode() + b"\n")
            self.writer.flush()

    def _handle(self, message):
        result = self.handler(self, message)
        if "id" in message and result is not OMIT:
            if isinstance(result, RpcError):
                self.send({"id": message["id"], "error": result.error})
            else:
                self.send({"id": message["id"], "result": result})

    def _serve(self):
        try:
            for line in self.reader:
                message = json.loads(line)
                if "method" in message:
                    self.requests.append(message)
                    threading.Thread(target=self._handle, args=(message,), daemon=True).start()
                else:
                    self.responses.append(message)
        except (OSError, ValueError):
            pass

    def poll(self):
        return 0 if self.closed else None

    def close(self):
        self.closed = True
        for sock in (self.client_socket, self.server_socket):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()


def operation(label):
    return AuthorizedOperation(
        label,
        "cmd-" + label,
        "msg-" + label,
        "grant-node",
        datetime.now(UTC) + timedelta(seconds=30),
    )


@pytest.fixture
def profile(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    config = home / "config.toml"
    config.write_text('default_permissions="test-profile"\napproval_policy="never"\n')
    schema = tmp_path / "schema.json"
    schema.write_text('{"fixture":true}')
    return LaunchProfile(
        sys.executable,
        file_digest(sys.executable),
        "0.153.2",
        str(schema),
        file_digest(schema),
        str(tmp_path),
        str(home),
        file_digest(config),
        "test-profile",
        {},
    )


@pytest.fixture
def native(tmp_path, profile, monkeypatch):
    state = {
        "turns": [],
        "drop_invoke_ack": False,
        "features": False,
        "turn_calls": 0,
        "session_creation_error": None,
    }

    def thread():
        return {
            "id": "thread-1",
            "sessionId": "session-1",
            "turns": [],
            "status": {
                "type": "active"
                if any(t["status"] == "inProgress" for t in state["turns"])
                else "idle"
            },
        }

    def handle(peer, message):
        method, params = message["method"], message.get("params", {})
        if method == "initialize":
            return {"userAgent": "codex/0.153.2", "codexHome": profile.codex_home}
        if method == "initialized":
            return OMIT
        if method in {"thread/start", "thread/resume"}:
            if method == "thread/start" and state["session_creation_error"] is not None:
                return RpcError(state["session_creation_error"])
            return {
                "thread": thread(),
                "cwd": profile.cwd,
                "approvalPolicy": "never",
                "activePermissionProfile": {"id": "test-profile"},
            }
        if method == "experimentalFeature/list":
            return {
                "data": [
                    {"name": key, "enabled": state["features"]}
                    for key in ("multi_agent", "multi_agent_v2")
                ]
            }
        if method == "thread/read":
            return {"thread": thread()}
        if method == "thread/turns/list":
            return {"data": state["turns"]}
        if method == "turn/start":
            state["turn_calls"] += 1
            turn = {
                "id": "turn-" + str(state["turn_calls"]),
                "status": "inProgress",
                "items": [
                    {
                        "id": "item-1",
                        "type": "userMessage",
                        "clientId": params["clientUserMessageId"],
                        "content": params["input"],
                    }
                ],
            }
            state["turns"].append(turn)
            peer.send({"method": "turn/started", "params": {"threadId": "thread-1", "turn": turn}})
            return OMIT if state["drop_invoke_ack"] else {"turn": turn}
        if method == "turn/interrupt":
            for turn in state["turns"]:
                if turn["id"] == params["turnId"]:
                    turn["status"] = "interrupted"
            return {}
        return RpcError({"code": -32601, "message": "fixture method missing"})

    peer = WirePeer(handle)
    launches = []

    def launch(argv, **kwargs):
        launches.append((argv, kwargs))
        return peer

    monkeypatch.setattr(driver_module.subprocess, "Popen", launch)
    identity = BindingIdentity("node", "boot-1", "runtime-1", "attempt-1", "slot", 1)
    authorizations = []

    def check(op, binding):
        authorizations.append((op.operation_id, binding.node_boot_id))

    driver = CodexAppServerDriver(
        "binding-1",
        profile,
        DriverJournal(tmp_path / "journal.db"),
        identity=identity,
        check_current=check,
        rpc_timeout=0.2,
    )
    try:
        yield SimpleNamespace(
            driver=driver,
            peer=peer,
            state=state,
            launches=launches,
            identity=identity,
            authorizations=authorizations,
        )
    finally:
        driver.detach_transport()
        peer.close()


def test_real_python_stdio_jsonl_transport():
    script = "import sys,json\nfor line in sys.stdin:\n m=json.loads(line); print(json.dumps({'id':m['id'],'result':m['params']}),flush=True)"
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    client = JsonRpcClient(process.stdout, process.stdin, stderr=process.stderr)
    try:
        assert client.request("echo", {"unicode": "真实管道"}, timeout=3) == {"unicode": "真实管道"}
    finally:
        client.close()
        process.wait(timeout=3)


def test_multiplex_errors_notifications_and_server_request():
    def handle(peer, message):
        if message["method"] == "error":
            return RpcError({"code": -32602, "message": "invalid params", "data": {"field": "x"}})
        if message["method"] == "slow":
            time.sleep(0.08)
        if message["method"] == "server-request":
            peer.send(
                {"id": "server-1", "method": "item/commandExecution/requestApproval", "params": {}}
            )
            peer.send({"method": "item/completed", "params": {"threadId": "other-thread"}})
        return message["method"]

    peer = WirePeer(handle)
    client = JsonRpcClient(peer.stdout, peer.stdin)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            slow = pool.submit(client.request, "slow", {})
            fast = pool.submit(client.request, "fast", {})
            assert fast.result(1) == "fast"
            assert slow.result(1) == "slow"
        with pytest.raises(RpcError) as error:
            client.request("error", {})
        assert error.value.error["code"] == -32602
        client.request("server-request", {})
        until = time.monotonic() + 1
        while not peer.responses and time.monotonic() < until:
            time.sleep(0.01)
        assert peer.responses[0]["error"]["code"] == -32601
        assert {event["kind"] for event in client.drain_events()} == {
            "notification",
            "server_request",
        }
        assert all("jsonrpc" not in request for request in peer.requests)
    finally:
        client.close()
        peer.close()


def test_timeout_preserves_late_response_without_retry():
    def delayed(peer, message):
        time.sleep(0.08)
        return {"turn": {"id": "late-turn"}}

    peer = WirePeer(delayed)
    client = JsonRpcClient(peer.stdout, peer.stdin)
    try:
        with pytest.raises(RpcTimeout):
            client.request("turn/start", {}, timeout=0.01, request_id="request-original")
        event = client.events.get(timeout=1)
        assert event["kind"] == "late_response"
        assert event["message"]["id"] == "request-original"
        assert len(peer.requests) == 1
    finally:
        client.close()
        peer.close()


@pytest.mark.parametrize(
    "wire", [b"not-json\n", b"[]\n", b'{"id":"x","error":null}\n', b"x" * 1000 + b"\n"]
)
def test_bad_frames_disconnect_all_pending(wire):
    peer = WirePeer(lambda *_: OMIT)
    client = JsonRpcClient(peer.stdout, peer.stdin, max_line_bytes=512)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.request, "wait", {}, timeout=1)
            peer.server_socket.sendall(wire)
            with pytest.raises(RpcDisconnected):
                pending.result(2)
    finally:
        client.close()
        peer.close()


def test_spawn_records_intent_and_effective_profile(native):
    d = native.driver
    receipt = d.spawn(operation("spawn"))
    assert receipt["thread_id"] == "thread-1" and receipt["session_id"] == "session-1"
    assert receipt["binding"]["node_boot_id"] == "boot-1"
    assert native.launches[0][0][1:] == [
        "--disable",
        "multi_agent",
        "--disable",
        "multi_agent_v2",
        "app-server",
    ]
    assert native.launches[0][1]["env"] == {"CODEX_HOME": d.profile.codex_home}
    with d.journal._connect() as conn:
        events = conn.execute("SELECT kind FROM driver_events ORDER BY sequence").fetchall()
    assert events[0] == ("process_intent",)
    assert events.index(("process_started",)) < events.index(("rpc_intent",))
    assert native.authorizations


def test_exact_invoke_replay_resume_and_cancel(native):
    d = native.driver
    d.spawn(operation("spawn"))
    call = operation("invoke")
    receipt = d.invoke(call, "authorized task")
    assert d.invoke(call, "authorized task") == receipt
    assert native.state["turn_calls"] == 1
    with pytest.raises(DriverRejected, match="different input"):
        d.invoke(call, "changed task")
    cancelled = d.cancel(operation("cancel"), receipt["turn_id"])
    assert cancelled["native_status"] == "interrupted"
    interrupt = [r for r in native.peer.requests if r["method"] == "turn/interrupt"]
    assert interrupt[0]["params"] == {"threadId": "thread-1", "turnId": receipt["turn_id"]}
    assert d.resume(operation("resume"))["receipt_layer"] == "context_resumed"
    assert native.state["turn_calls"] == 1


def test_invoke_ack_loss_reconciles_real_wire_message_not_resubmission(native):
    d = native.driver
    d.spawn(operation("spawn"))
    native.state["drop_invoke_ack"] = True
    original = operation("invoke")
    with pytest.raises(RpcTimeout):
        d.invoke(original, "one authorized task")
    assert d.journal.read("invoke")["state"] == "uncertain"
    with pytest.raises(OutcomeUncertain):
        d.invoke(original, "one authorized task")
    recovered = d.reconcile(operation("inspect"), "invoke")
    assert recovered["command_id"] == original.command_id
    assert recovered["message_id"] == original.message_id
    assert recovered["turn_id"] == "turn-1"
    assert native.state["turn_calls"] == 1


def test_ambiguous_reconciliation_remains_uncertain(native):
    d = native.driver
    d.spawn(operation("spawn"))
    native.state["drop_invoke_ack"] = True
    original = operation("invoke")
    with pytest.raises(RpcTimeout):
        d.invoke(original, "task")
    duplicate = dict(native.state["turns"][0], id="duplicate-turn")
    native.state["turns"].append(duplicate)
    with pytest.raises(OutcomeUncertain, match="unique"):
        d.reconcile(operation("inspect"), "invoke")
    assert native.state["turn_calls"] == 1


def test_busy_invoke_never_implicitly_steers(native):
    d = native.driver
    d.spawn(operation("spawn"))
    d.invoke(operation("first"), "first")
    with pytest.raises(DriverRejected, match="steering"):
        d.invoke(operation("second"), "second")
    assert native.state["turn_calls"] == 1


def test_terminate_without_supervisor_fails_closed(native):
    d = native.driver
    d.spawn(operation("spawn"))
    with pytest.raises(DriverRejected, match="containment"):
        d.terminate(operation("terminate"))
    assert not native.peer.closed


def test_current_authorization_is_rechecked_before_turn_rpc(native):
    d = native.driver
    d.spawn(operation("spawn"))

    def revoked(op, binding):
        if op.operation_id == "invoke":
            raise DriverRejected("Grant revoked")

    d.check_current = revoked
    with pytest.raises(DriverRejected, match="revoked"):
        d.invoke(operation("invoke"), "not authorized now")
    assert native.state["turn_calls"] == 0


def test_binding_lock_and_crash_intent_cannot_be_reused(native):
    d = native.driver
    with pytest.raises(DriverRejected, match="already owned"):
        CodexAppServerDriver(
            "binding-1",
            d.profile,
            d.journal,
            identity=native.identity,
            check_current=lambda *_: None,
        )
    original = operation("crashed-before-rpc")
    d.journal.begin(
        original,
        "binding-1",
        "spawn",
        {"profile": d.profile.binding(), "binding": vars(native.identity)},
    )
    with pytest.raises(OutcomeUncertain):
        d.spawn(original)
    assert native.launches == []


def test_profile_tamper_rejected_before_spawn(native):
    d = native.driver
    (Path(d.profile.codex_home) / "config.toml").write_text('approval_policy="never"')
    with pytest.raises(DriverRejected, match="configuration"):
        d.spawn(operation("spawn"))
    assert native.launches == []


def test_native_delegation_enablement_is_rejected(native):
    native.state["features"] = True
    with pytest.raises(DriverRejected, match="delegation"):
        native.driver.spawn(operation("spawn"))
    assert native.state["turn_calls"] == 0


def test_shared_attach_is_read_only(tmp_path, profile):
    def handle(peer, request):
        if request["method"] == "initialize":
            return {"userAgent": "codex/0.153.2", "codexHome": profile.codex_home}
        if request["method"] == "initialized":
            return OMIT
        if request["method"] == "thread/read":
            return {
                "thread": {
                    "id": "shared",
                    "sessionId": "shared-session",
                    "status": {"type": "idle"},
                }
            }
        return {"data": []}

    peer = WirePeer(handle)
    driver = CodexAppServerDriver(
        "shared-binding",
        profile,
        DriverJournal(tmp_path / "shared.db"),
        identity=BindingIdentity("node", "boot", "runtime", "attempt", "slot", 1),
        check_current=lambda *_: None,
    )
    try:
        driver.attach(operation("attach"), JsonRpcClient(peer.stdout, peer.stdin), "shared")
        assert driver.inspect(operation("inspect"))["thread"]["id"] == "shared"
        with pytest.raises(DriverRejected, match="exclusive"):
            driver.invoke(operation("invoke"), "must not run")
        assert not any(r["method"] == "turn/start" for r in peer.requests)
    finally:
        driver.detach_transport()
        peer.close()


def test_two_concurrent_invokes_produce_one_turn_without_steering(native):
    d = native.driver
    d.spawn(operation("spawn"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(d.invoke, operation(str(i)), "task") for i in range(2)]
        accepted, rejected = [], []
        for future in pending:
            try:
                accepted.append(future.result())
            except DriverRejected as error:
                rejected.append(error)
    assert len(accepted) == len(rejected) == 1
    assert native.state["turn_calls"] == 1
    assert d.cancel(operation("cancel"), accepted[0]["turn_id"])["native_status"] == "interrupted"


def test_terminal_output_keeps_original_operation_and_binding(native):
    d = native.driver
    d.spawn(operation("spawn"))
    original = operation("invoke")
    d.invoke(original, "task")
    native.state["turns"][0]["status"] = "completed"
    native.state["turns"][0]["items"].append(
        {"id": "answer", "type": "agentMessage", "phase": "final_answer", "text": "fixture result"}
    )
    result = d.collect_result(operation("inspect"), original.operation_id)
    assert result["receipt_layer"] == "response_received"
    assert result["operation_id"] == original.operation_id
    assert result["binding"]["attempt_id"] == "attempt-1"
    assert result["assistant_messages"][0]["text"] == "fixture result"
    assert native.state["turn_calls"] == 1


def test_disconnect_fails_outstanding_request():
    peer = WirePeer(lambda *_: OMIT)
    client = JsonRpcClient(peer.stdout, peer.stdin)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.request, "pending", {}, timeout=2)
            peer.close()
            with pytest.raises(RpcDisconnected):
                pending.result(3)
    finally:
        client.close()


def test_generated_01532_schema_supports_exact_wire_names():
    schema = json.loads(
        (
            Path(__file__).parent / "schema-0.153.2/codex_app_server_protocol.schemas.json"
        ).read_text()
    )
    v2 = schema["definitions"]["v2"]
    assert {"input", "threadId", "clientUserMessageId"} <= v2["TurnStartParams"][
        "properties"
    ].keys()
    assert set(v2["TurnInterruptParams"]["required"]) == {"threadId", "turnId"}
    assert "activePermissionProfile" in v2["ThreadStartResponse"]["properties"]
    user = next(
        item for item in v2["ThreadItem"]["oneOf"] if item["title"] == "UserMessageThreadItem"
    )
    assert "clientId" in user["properties"]


def test_owned_process_can_be_terminated_after_session_ack_loss(native):
    d = native.driver
    d.spawn(operation("spawn"))
    # Explicit supervisor test double checks routing only; OS containment is
    # exercised by the separate real Supervisor suite.
    d.thread_id = None
    d.owned.containment_id = "fixture-containment"

    class SupervisorDouble:
        def terminate_tree(self, owned):
            native.peer.close()
            return {
                "verified": True,
                "birth_ref": owned.birth_ref,
                "containment_id": owned.containment_id,
                "root_exited": True,
                "remaining_pids": [],
            }

    d.supervisor = SupervisorDouble()
    assert d.terminate(operation("terminate"))["receipt_layer"] == "process_tree_terminated"


def test_false_supervisor_proof_cannot_claim_termination(native):
    d = native.driver
    d.spawn(operation("spawn"))
    d.owned.containment_id = "fixture-containment"
    d.supervisor = SimpleNamespace(
        terminate_tree=lambda owned: {
            "verified": True,
            "birth_ref": owned.birth_ref,
            "containment_id": owned.containment_id,
            "root_exited": True,
            "remaining_pids": [],
        }
    )
    with pytest.raises(OutcomeUncertain, match="complete"):
        d.terminate(operation("terminate"))
    assert not native.peer.closed


def test_acknowledged_replay_rechecks_current_grant_without_touching_journal(native):
    d = native.driver
    d.spawn(operation("spawn"))
    original = operation("successful-invoke")
    result = d.invoke(original, "previously authorized")
    record = d.journal.read(original.operation_id)
    with d.journal._connect() as conn:
        event_count = conn.execute("SELECT count(*) FROM driver_events").fetchone()[0]
    request_count = len(native.peer.requests)

    def revoked(op, identity):
        raise DriverRejected("Grant has since been revoked")

    d.check_current = revoked
    with pytest.raises(DriverRejected, match="revoked"):
        d.invoke(original, "previously authorized")
    assert d.journal.read(original.operation_id) == record
    assert d.journal.read(original.operation_id)["result"] == result
    with d.journal._connect() as conn:
        assert conn.execute("SELECT count(*) FROM driver_events").fetchone()[0] == event_count
    assert len(native.peer.requests) == request_count
    assert native.state["turn_calls"] == 1


def test_actual_sandbox_startup_error_stays_uncertain_without_fallback(native):
    native.state["session_creation_error"] = {
        "code": -32603,
        "message": "error creating thread: fs sandbox helper failed: bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted",
    }
    original = operation("spawn")
    with pytest.raises(RpcError):
        native.driver.spawn(original)
    assert native.driver.journal.read(original.operation_id)["state"] == "uncertain"
    with pytest.raises(OutcomeUncertain):
        native.driver.spawn(original)
    methods = [r["method"] for r in native.peer.requests]
    assert methods.count("thread/start") == 1
    assert "turn/start" not in methods
    assert len(native.launches) == 1
    request = next(r for r in native.peer.requests if r["method"] == "thread/start")
    assert "sandbox" not in request["params"] and "config" not in request["params"]
