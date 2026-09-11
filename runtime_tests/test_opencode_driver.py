"""Actual local HTTP transport against an explicitly synthetic OpenCode peer."""
from __future__ import annotations

import base64
import hashlib
import http.client
import io
import json
import os
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from runtime.codex_driver import (
    AuthorizedOperation,
    BindingIdentity,
    DriverJournal,
    DriverRejected,
    OutcomeUncertain,
    file_digest,
)
from runtime.opencode_driver import (
    NATIVE_GITIGNORE,
    SESSION_RULES,
    OpenCodeLaunchProfile,
    OpenCodeNativeDriver,
)
from runtime.opencode_http import HttpFailure, HttpRejected, LoopbackHttp


def test_generated_11827_openapi_supports_exact_native_paths():
    schema_path = Path(__file__).with_name("schema-1.18.27") / "opencode-openapi.json"
    data = schema_path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == (
        "6ea6c82efbff42d0131a0a72ac2d8ddcec36b0ae31547bf1424dbb1b87b729d5"
    )
    paths = json.loads(data)["paths"]
    for path in (
        "/global/health", "/session", "/session/status", "/session/{sessionID}",
        "/session/{sessionID}/message", "/session/{sessionID}/prompt_async",
        "/session/{sessionID}/abort", "/event",
    ):
        assert path in paths


def operation(label):
    return AuthorizedOperation(label, "cmd-" + label, "packet-" + label, "grant-test",
                               datetime.now(UTC) + timedelta(seconds=30))


@pytest.fixture
def profile(tmp_path):
    roots = {name: tmp_path / name for name in ("home", "config", "data", "state", "cache", "input", "tmp")}
    for path in roots.values():
        path.mkdir()
    config = roots["config"] / "opencode"
    config.mkdir()
    config_path = config / "opencode.json"
    config_path.write_text(json.dumps({
        "permission": {"*": "deny", "task": "deny"}, "default_agent": "engineer", "model": "provider/model",
        "agent": {"engineer": {"model": "provider/model", "permission": {"*": "deny", "task": "deny"}}},
    }))
    schema = tmp_path / "schema.json"
    schema.write_text('{"openapi":"3.1.0","info":{"title":"synthetic peer"}}')
    return OpenCodeLaunchProfile(
        sys.executable, file_digest(sys.executable), "1.18.27", str(schema), file_digest(schema),
        str(roots["input"]), str(roots["home"]), str(roots["config"]), str(roots["data"]),
        str(roots["state"]), str(roots["cache"]), str(roots["tmp"]), file_digest(config_path),
        "engineer", "provider", "model", {},
    )


class NativeHttpPeer:
    """Real HTTP/socket endpoint. All model, session and process facts are fixtures."""
    def __init__(self, port, password, profile):
        self.profile = profile
        self.password = password
        self.requests = []
        self.messages = []
        self.session = None
        self.busy = False
        self.closed = False
        self.drop_prompt_ack = False
        self.drop_session_ack = False
        self.hide_message = False
        self.abort_entered = threading.Event()
        self.abort_release = None
        self.redirect = False
        self.extra_sessions = []
        peer = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *args):
                pass
            def answer(self, status, value=None):
                body = b"" if value is None else json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                if status == 302:
                    self.send_header("Location", "http://example.invalid/stolen")
                self.end_headers()
                if body:
                    self.wfile.write(body)
            def dispatch(self):
                path = urlsplit(self.path).path
                expected = "Basic " + base64.b64encode(("opencode:" + password).encode()).decode()
                if self.headers.get("Authorization") != expected:
                    self.answer(401, {"error": "authentication required"})
                    return
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length else None
                peer.requests.append((self.command, path, body))
                if peer.redirect:
                    self.answer(302)
                    return
                if path == "/event":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(b'data: {"type":"server.connected","properties":{}}\n\n')
                    self.wfile.flush()
                    self.close_connection = True
                    return
                if path == "/global/health":
                    self.answer(200, {"healthy": True, "version": "1.18.27"})
                elif path == "/doc":
                    self.answer(200, json.loads(Path(profile.schema_path).read_text()))
                elif path == "/config":
                    self.answer(200, json.loads(profile.config_path.read_text()))
                elif path == "/agent":
                    self.answer(200, [{"name": "engineer", "permission": SESSION_RULES}])
                elif path == "/experimental/tool/ids":
                    self.answer(
                        200,
                        [
                            "bash",
                            "read",
                            "edit",
                            "write",
                            "glob",
                            "grep",
                            "task",
                            "webfetch",
                            "websearch",
                            "todowrite",
                        ],
                    )
                elif path == "/session" and self.command == "POST":
                    peer.session = {**body, "id": "ses_test", "directory": profile.cwd, "time": {"created": 1, "updated": 1}}
                    if peer.drop_session_ack:
                        self.close_connection = True
                        self.connection.shutdown(socket.SHUT_RDWR)
                        return
                    self.answer(200, peer.session)
                elif path == "/session" and self.command == "GET":
                    self.answer(200, ([peer.session] if peer.session else []) + peer.extra_sessions)
                elif path == "/session/ses_test":
                    self.answer(200, peer.session)
                elif path == "/session/status":
                    self.answer(200, {"ses_test": {"type": "busy"}} if peer.busy else {})
                elif path == "/session/ses_test/message":
                    self.answer(200, peer.messages)
                elif path.startswith("/session/ses_test/message/msg_"):
                    matches = [entry for entry in peer.messages if entry["info"]["id"] == path.rsplit("/", 1)[1]]
                    if peer.hide_message or not matches:
                        self.answer(404, {"error": "not found"})
                    else:
                        self.answer(200, matches[0])
                elif path == "/session/ses_test/prompt_async":
                    assert set(body) == {"messageID", "agent", "model", "parts"}
                    message_id = body["messageID"]
                    peer.messages.append({"info": {"id": message_id, "sessionID": "ses_test", "role": "user",
                                                   "time": {"created": len(peer.messages) + 1},
                                                   "agent": body["agent"], "model": body["model"]},
                                          "parts": [{"id": "prt_text", "sessionID": "ses_test", "messageID": message_id,
                                                     **body["parts"][0]}]})
                    peer.busy = True
                    if peer.drop_prompt_ack:
                        self.close_connection = True
                        self.connection.shutdown(socket.SHUT_RDWR)
                        return
                    self.answer(204)
                elif path == "/session/ses_test/abort":
                    peer.abort_entered.set()
                    if peer.abort_release:
                        peer.abort_release.wait(3)
                    peer.finish(aborted=True)
                    self.answer(200, True)
                else:
                    self.answer(404, {"error": "unknown route"})
            do_GET = dispatch
            do_POST = dispatch
        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def finish(self, aborted=False):
        parent = [entry["info"]["id"] for entry in self.messages if entry["info"]["role"] == "user"][-1]
        info = {"id": "msg_answer_" + str(len(self.messages)), "sessionID": "ses_test",
                "role": "assistant", "parentID": parent, "time": {"created": 2, "completed": 3}}
        if aborted:
            info["error"] = {"name": "MessageAbortedError", "data": {"message": "fixture"}}
        self.messages.append({"info": info, "parts": [{"id": "prt_answer", "sessionID": "ses_test",
                                                       "messageID": info["id"], "type": "text", "text": "synthetic final answer"}]})
        self.busy = False

    def close(self):
        if not self.closed:
            self.closed = True
            self.server.shutdown()
            self.server.server_close()


@pytest.fixture
def native(tmp_path, profile):
    state = SimpleNamespace(peer=None, authorization_revoked=False, launches=0)
    class ProcessDouble:
        pid = os.getpid()  # HTTP server belongs to this test process, never a real child observation.
        stdin = None
        stdout = io.BytesIO()
        stderr = io.BytesIO()
        def poll(self):
            return 0 if state.peer.closed else None
    class SupervisorDouble:
        def launch(self, argv, **kwargs):
            state.launches += 1
            port = int(argv[argv.index("--port") + 1])
            state.peer = NativeHttpPeer(port, kwargs["env"]["OPENCODE_SERVER_PASSWORD"], profile)
            state.peer.drop_session_ack = getattr(state, "drop_session_ack", False)
            state.launch_args = argv, kwargs
            return SimpleNamespace(process=ProcessDouble(), birth_ref="fixture-process-birth", containment_id="fixture-job")
        def inspect(self, owned):
            return {"verified": True, "birth_ref": owned.birth_ref, "containment_id": owned.containment_id,
                    "root_exited": state.peer.closed, "remaining_pids": [] if state.peer.closed else [os.getpid()]}
        def terminate_tree(self, owned):
            state.peer.close()
            return self.inspect(owned)
    def authorize(op, binding):
        if state.authorization_revoked:
            raise DriverRejected("current Grant revoked")
    driver = OpenCodeNativeDriver("binding", profile, DriverJournal(tmp_path / "journal.sqlite"),
                                  identity=BindingIdentity("node", "boot", "runtime", "attempt", "slot", 1),
                                  check_current=authorize, supervisor=SupervisorDouble(), readback_attempts=1)
    state.driver = driver
    try:
        yield state
    finally:
        if state.peer:
            state.peer.close()
        driver.detach_transport()


def prompts(peer):
    return [request for request in peer.requests if request[1].endswith("/prompt_async")]


def test_spawn_uses_actual_http_identity_profile_and_denies(native):
    receipt = native.driver.spawn(operation("spawn"))
    assert receipt["receipt_layer"] == "runtime_acknowledged"
    assert receipt["native_session_id"] == "ses_test"
    assert native.peer.session["permission"] == SESSION_RULES
    assert native.peer.session["metadata"]["acs_binding"]["attempt_id"] == "attempt"
    assert native.launch_args[0][1:3] == ["--pure", "serve"]
    assert native.launch_args[1]["env"]["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"
    assert prompts(native.peer) == []


def test_204_requires_real_matching_readback_before_native_ack(native):
    d = native.driver
    d.spawn(operation("spawn"))
    native.peer.hide_message = True
    original = operation("invoke")
    receipt = d.invoke(original, "allowed text")
    assert receipt["receipt_layer"] == "runtime_dispatched"
    assert receipt["native_ack_type"] == "http_204_scheduling_only"
    assert d.journal.read("invoke")["state"] == "uncertain"
    with pytest.raises(OutcomeUncertain):
        d.invoke(original, "allowed text")
    native.peer.hide_message = False
    recovered = d.reconcile(operation("observe"), "invoke")
    assert recovered["receipt_layer"] == "runtime_acknowledged"
    assert recovered["native_message_id"] == receipt["native_message_id"]
    assert len(prompts(native.peer)) == 1


def test_lost_http_ack_never_resubmits(native):
    d = native.driver
    d.spawn(operation("spawn"))
    native.peer.drop_prompt_ack = True
    original = operation("invoke")
    with pytest.raises((http.client.RemoteDisconnected, ConnectionResetError)):
        d.invoke(original, "once")
    assert d.journal.read("invoke")["state"] == "uncertain"
    with pytest.raises(OutcomeUncertain):
        d.invoke(original, "once")
    assert d.reconcile(operation("observe"), "invoke")["receipt_layer"] == "runtime_acknowledged"
    assert len(prompts(native.peer)) == 1


def test_native_message_identity_and_receipt_are_not_rebound(native):
    d = native.driver
    d.spawn(operation("spawn"))
    original = operation("invoke")
    receipt = d.invoke(original, "fixed")
    assert d.invoke(original, "fixed") == receipt
    assert d.reconcile(operation("observe"), "invoke") == receipt
    native.peer.messages[0]["parts"][0]["text"] = "changed"
    with pytest.raises(DriverRejected, match="exact authorized"):
        d.reconcile(operation("bad-readback"), "invoke")
    assert d.journal.read("invoke")["result"] == receipt


def test_current_authorization_precedes_replay_and_journal_mutation(native):
    d = native.driver
    d.spawn(operation("spawn"))
    original = operation("invoke")
    d.invoke(original, "fixed")
    before = d.journal.read("invoke")
    native.authorization_revoked = True
    with pytest.raises(DriverRejected, match="revoked"):
        d.invoke(original, "fixed")
    with pytest.raises(DriverRejected, match="revoked"):
        d.reconcile(operation("observe"), "invoke")
    assert d.journal.read("invoke") == before
    assert len(prompts(native.peer)) == 1


def test_cancel_is_exact_and_serialized_against_new_invoke(native):
    d = native.driver
    d.spawn(operation("spawn"))
    first = d.invoke(operation("first"), "first")
    native.peer.abort_release = threading.Event()
    with ThreadPoolExecutor(max_workers=2) as pool:
        cancellation = pool.submit(d.cancel, operation("cancel"), first["native_message_id"])
        assert native.peer.abort_entered.wait(2)
        second = pool.submit(d.invoke, operation("second"), "second")
        time.sleep(0.05)
        assert not second.done()
        assert len(prompts(native.peer)) == 1
        native.peer.abort_release.set()
        assert cancellation.result(3)["abort_requested"] is True
        second_receipt = second.result(3)
    with pytest.raises(DriverRejected, match="active message"):
        d.cancel(operation("stale-cancel"), first["native_message_id"])
    assert second_receipt["native_message_id"] != first["native_message_id"]
    assert len([entry for entry in native.peer.requests if entry[1].endswith("/abort")]) == 1


def test_resume_is_context_only_and_collection_is_correlated(native):
    d = native.driver
    d.spawn(operation("spawn"))
    assert d.resume(operation("resume"))["receipt_layer"] == "context_resumed"
    assert not prompts(native.peer)
    original = operation("invoke")
    receipt = d.invoke(original, "fixed")
    with pytest.raises(OutcomeUncertain):
        d.collect_result(operation("unfinished"), "invoke")
    native.peer.finish()
    result = d.collect_result(operation("finished"), "invoke")
    assert result["receipt_layer"] == "response_received"
    assert result["native_message_id"] == receipt["native_message_id"]
    assert result["assistant_text"] == ["synthetic final answer"]
    assert len(prompts(native.peer)) == 1


@pytest.mark.parametrize("field,value", [("acs_binding_id", "other"), ("acs_binding", {"node_boot_id": "new"})])
def test_session_binding_drift_is_rejected(native, field, value):
    d = native.driver
    d.spawn(operation("spawn"))
    native.peer.session["metadata"][field] = value
    with pytest.raises(DriverRejected, match="original Node"):
        d.inspect(operation("inspect"))
    assert not prompts(native.peer)


@pytest.mark.parametrize("text", ["", {"type": "file", "url": "file:///secret"}, ["subtask"]])
def test_input_is_only_nonempty_text(native, text):
    with pytest.raises(DriverRejected, match="plain text"):
        native.driver.invoke(operation("bad"), text)
    assert native.launches == 0


def test_no_tools_agent_or_file_override_surface(native):
    with pytest.raises(TypeError):
        native.driver.invoke(operation("bad"), "text", tools={"bash": True})
    with pytest.raises(TypeError):
        native.driver.invoke(operation("bad"), "text", agent="other")
    assert native.launches == 0


def test_http_redirect_and_arbitrary_path_are_rejected(native):
    d = native.driver
    d.spawn(operation("spawn"))
    for path in ("http://example.invalid/x", "//example.invalid/x", "/session/../config", "/session/ses_test?directory=other"):
        with pytest.raises(HttpRejected):
            d.client.request("GET", path)
    native.peer.redirect = True
    with pytest.raises(HttpFailure) as error:
        d.client.request("GET", "/global/health")
    assert error.value.status == 302


def test_proxy_environment_cannot_change_endpoint(native, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    assert native.driver.spawn(operation("spawn"))["native_session_id"] == "ses_test"
    assert native.driver.inspect(operation("inspect"))["status"] == {"type": "idle"}


def test_secret_not_in_journal(native):
    d = native.driver
    d.spawn(operation("spawn"))
    with d.journal._connect() as connection:
        rows = connection.execute("SELECT body FROM driver_events").fetchall()
    serialized = json.dumps(rows)
    assert native.peer.password not in serialized
    assert base64.b64encode(("opencode:" + native.peer.password).encode()).decode() not in serialized


def test_shared_attach_is_read_only(native, tmp_path):
    d = native.driver
    d.spawn(operation("spawn"))
    native.peer.closed = False
    attached = OpenCodeNativeDriver("binding", d.profile,
                                    DriverJournal(tmp_path / "attached-journal.sqlite"), identity=d.identity,
                                    check_current=lambda *_: None, readback_attempts=1)
    try:
        client = LoopbackHttp(d.client.port, native.peer.password, d.profile.cwd, lambda: True)
        assert attached.attach(operation("attach"), client, "ses_test")["receipt_layer"] == "context_observed"
        assert attached.inspect(operation("inspect"))["native_session_id"] == "ses_test"
        with pytest.raises(DriverRejected, match="exclusive"):
            attached.invoke(operation("forbidden"), "no")
        with pytest.raises(DriverRejected, match="owned"):
            attached.terminate(operation("terminate"))
    finally:
        attached.detach_transport()
    assert not native.peer.closed


def test_termination_requires_real_matching_proof(native):
    d = native.driver
    d.spawn(operation("spawn"))
    original = d.supervisor
    d.supervisor = SimpleNamespace(terminate_tree=lambda _: {"verified": True, "root_exited": True, "remaining_pids": []})
    with pytest.raises(OutcomeUncertain):
        d.terminate(operation("bad-terminate"))
    d.supervisor = original
    receipt = d.terminate(operation("good-terminate"))
    assert receipt["receipt_layer"] == "process_tree_terminated"
    assert native.peer.closed


def test_configuration_tamper_is_rejected_before_process(native):
    native.driver.profile.config_path.write_text("{}")
    with pytest.raises(DriverRejected, match="configuration changed"):
        native.driver.spawn(operation("spawn"))
    assert native.launches == 0


@pytest.mark.parametrize("key", ["HTTP_PROXY", "NODE_OPTIONS", "OPENCODE_CONFIG_CONTENT"])
def test_profile_rejects_unapproved_environment_overrides(profile, key):
    with pytest.raises(DriverRejected, match="override"):
        replace(profile, environment={key: "unapproved"}).validate()


def test_private_roots_must_be_fresh(native):
    Path(native.driver.profile.home, "existing-user-state").write_text("preserve")
    with pytest.raises(DriverRejected, match="fresh private"):
        native.driver.spawn(operation("spawn"))
    assert native.launches == 0


def test_reviewed_native_gitignore_is_data_not_an_unbounded_exception(profile):
    path = profile.config_path.parent / ".gitignore"
    path.write_bytes(NATIVE_GITIGNORE)
    profile.validate()
    path.write_bytes(NATIVE_GITIGNORE + b"\nextra")
    with pytest.raises(DriverRejected, match="approved configuration"):
        profile.validate()


def test_boot_change_and_known_native_id_change_are_rejected(native):
    d = native.driver
    d.spawn(operation("spawn"))
    receipt = d.invoke(operation("invoke"), "fixed")
    d.identity = replace(d.identity, node_boot_id="replacement-boot")
    with pytest.raises(DriverRejected, match="retired"):
        d.inspect(operation("inspect"))
    d.identity = BindingIdentity(**d._identity)
    with d.journal._connect() as connection:
        altered = {**receipt, "native_message_id": "msg_other"}
        connection.execute("UPDATE driver_operations SET result_json=? WHERE operation_id='invoke'",
                           (json.dumps(altered),))
    with pytest.raises(DriverRejected, match="known native"):
        d.reconcile(operation("reconcile"), "invoke")


def test_endpoint_ownership_failure_prevents_secret_or_request(native):
    d = native.driver
    d.spawn(operation("spawn"))
    before = len(native.peer.requests)
    d.client.verify_owner = lambda: False
    with pytest.raises(HttpRejected, match="ownership"):
        d.client.request("GET", "/global/health")
    assert len(native.peer.requests) == before


def test_lost_session_ack_uses_unique_metadata_without_second_create(native):
    d = native.driver
    native.drop_session_ack = True
    original = operation("spawn")
    with pytest.raises((http.client.RemoteDisconnected, ConnectionResetError)):
        d.spawn(original)
    assert d.session_id is None
    with pytest.raises(OutcomeUncertain):
        d.spawn(original)
    receipt = d.reconcile(operation("recover-session"), "spawn")
    assert receipt["native_session_id"] == "ses_test"
    assert receipt["native_ack_type"] == "unique_session_metadata_readback"
    assert len([value for value in native.peer.requests if value[:2] == ("POST", "/session")]) == 1
    assert prompts(native.peer) == []


def test_ambiguous_session_creation_recovery_stays_uncertain(native):
    d = native.driver
    native.drop_session_ack = True
    with pytest.raises((http.client.RemoteDisconnected, ConnectionResetError)):
        d.spawn(operation("spawn"))
    native.peer.extra_sessions = [{**native.peer.session, "id": "ses_other"}]
    with pytest.raises(OutcomeUncertain, match="unique"):
        d.reconcile(operation("recover"), "spawn")
    assert d.journal.read("spawn")["state"] == "uncertain"


def test_pre_dispatch_authorization_rejection_does_not_poison_active_message(native):
    d = native.driver
    d.spawn(operation("spawn"))
    first = d.invoke(operation("first"), "first")
    native.peer.finish()
    def authorize(op, identity):
        if op.operation_id == "blocked" and d._active_operation_id == "blocked":
            raise DriverRejected("authorization revoked before dispatch")
    d.check_current = authorize
    with pytest.raises(DriverRejected, match="revoked before"):
        d.invoke(operation("blocked"), "must not dispatch")
    assert d.journal.read("blocked")["state"] == "rejected"
    assert d._active_message == first["native_message_id"]
    assert d.invoke(operation("later"), "later authorized")["receipt_layer"] == "runtime_acknowledged"
    assert len(prompts(native.peer)) == 2


def test_cross_bound_assistant_parts_cannot_be_collected(native):
    d = native.driver
    d.spawn(operation("spawn"))
    d.invoke(operation("invoke"), "fixed")
    native.peer.finish()
    native.peer.messages[-1]["parts"][0]["messageID"] = "msg_other"
    with pytest.raises(DriverRejected, match="cross-bound"):
        d.collect_result(operation("collect"), "invoke")


def test_cancel_does_not_claim_interruption_when_naturally_completed(native):
    d = native.driver
    d.spawn(operation("spawn"))
    receipt = d.invoke(operation("invoke"), "fixed")
    native.peer.finish()
    result = d.cancel(operation("cancel"), receipt["native_message_id"])
    assert result["abort_requested"] is False
    assert result["native_terminal_outcome"] == "completed"
    assert not any(value[1].endswith("/abort") for value in native.peer.requests)


@pytest.mark.parametrize(
    "rule",
    [
        {"permission": "todowrite", "pattern": "*", "action": "allow"},
        {"permission": "read", "pattern": "*.env", "action": "allow"},
    ],
)
def test_effective_allow_after_global_deny_is_rejected(native, monkeypatch, rule):
    original_launch = native.driver.supervisor.launch

    def launch(*args, **kwargs):
        owned = original_launch(*args, **kwargs)
        handler = native.peer.server.RequestHandlerClass
        original_answer = handler.answer

        def answer(self, status, value=None):
            if urlsplit(self.path).path == "/agent":
                value = [
                    {**agent, "permission": [*agent["permission"], rule]}
                    for agent in value
                ]
            return original_answer(self, status, value)

        monkeypatch.setattr(handler, "answer", answer)
        return owned

    monkeypatch.setattr(native.driver.supervisor, "launch", launch)

    with pytest.raises(DriverRejected, match="effective allow"):
        native.driver.spawn(operation("unsafe-final-permission"))
    assert not any(
        method == "POST" and path == "/session"
        for method, path, _body in native.peer.requests
    )


def test_live_exclusive_capacity_cannot_release_its_claim(native):
    driver = native.driver
    driver.spawn(operation("spawn-owned"))
    assert driver.ownership == "exclusive_owned"
    assert driver.owned.process.poll() is None

    with pytest.raises(DriverRejected, match="terminated before detach"):
        driver.detach_transport()
    assert driver._claim_fd is not None
    assert (
        driver.terminate(operation("terminate-owned"))["receipt_layer"]
        == "process_tree_terminated"
    )


def test_authorization_denied_before_launch_is_a_rejection(native, monkeypatch):
    driver = native.driver
    original_auth = driver.check_current

    def authorize(op, binding):
        original_auth(op, binding)
        with driver.journal._connect() as connection:
            prepared = connection.execute(
                "SELECT body FROM driver_events WHERE operation_id=? "
                "AND kind='process_intent'",
                (op.operation_id,),
            ).fetchone()
        if prepared is not None:
            assert json.loads(prepared[0])["binding"] == driver._identity
            raise DriverRejected("authorization revoked before process launch")

    monkeypatch.setattr(driver, "check_current", authorize)
    op = operation("deny-before-launch")

    with pytest.raises(DriverRejected, match="before process launch"):
        driver.spawn(op)
    assert native.launches == 0
    assert driver.journal.read(op.operation_id)["state"] == "rejected"


def test_authorization_denied_before_http_send_is_a_rejection(native, monkeypatch):
    driver = native.driver
    driver.spawn(operation("spawn-before-http-denial"))
    original_auth = driver.check_current
    op = operation("deny-before-http")

    def authorize(current, binding):
        original_auth(current, binding)
        if current.operation_id != op.operation_id:
            return
        with driver.journal._connect() as connection:
            events = connection.execute(
                "SELECT body FROM driver_events WHERE operation_id=? "
                "AND kind='http_intent'",
                (op.operation_id,),
            ).fetchall()
        if any(json.loads(row[0])["method"] == "POST" for row in events):
            raise DriverRejected("authorization revoked before HTTP send")

    monkeypatch.setattr(driver, "check_current", authorize)

    with pytest.raises(DriverRejected, match="before HTTP send"):
        driver.invoke(op, "synthetic text; never sent")
    assert not any(path.endswith("/prompt_async") for _, path, _ in native.peer.requests)
    assert driver.journal.read(op.operation_id)["state"] == "rejected"
    assert driver._active_message is None
