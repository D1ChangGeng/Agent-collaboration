"""Real Node SDK -> local OAuth HTTP/SSE -> isolated PostgreSQL acceptance.

The issuer and Native drivers are explicitly synthetic. This qualifies the local
headless protocol episode, not an installed host/Harness or model workflow.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import queue
import shutil
import socket
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs

import pytest
import uvicorn

from runtime.communication_client_service import CommunicationClientService
from runtime.communication_event_http import EventStreamLimits
from runtime.communication_event_storage import publish_event_intents
from runtime.project_common import parse_handle
from runtime.project_http import ProjectHttpSettings, create_http_app
from runtime_tests.test_communication import CATALOG
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_client_attachments import attached as attached_fixture
from runtime_tests.test_communication_client_oauth import config, explicit_initialize, shared
from runtime_tests.test_communication_faults import fail_b
from runtime_tests.test_project_http import IssuerFixture, claims

comm = comm_fixture
attached = attached_fixture
ROOT = Path(__file__).resolve().parents[1]
PROJECT = "project-alpha"
PEER = "collaborator:project-alpha:slot-b"
TOKEN = "headless-live-token"
REPLY = "HEADLESS_LIVE_PEER_REPLY_BODY_🧭"
ATTACHMENT_BYTES = ("HEADLESS_ATTACHMENT_PRIVATE_BYTES_汉字🧭" * 2500).encode()


def publish(f):
    with f.authority._connect() as connection:
        while publish_event_intents(connection, f.authority.tenant_id, PROJECT, limit=1000):
            pass


class ObserveLocalHttp:
    """Observe headers/counts without altering the actual OAuth app or frames."""

    def __init__(self, app):
        self.app = app
        self.event_positions = []
        self.outbound_sends = 0
        self.attachment_requests = {"reserve": 0, "upload": 0, "finalize": 0, "download": 0}

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path.endswith("/events"):
                headers = dict(scope.get("headers", ()))
                after = parse_qs(scope.get("query_string", b"").decode()).get("after_cursor", [None])[0]
                self.event_positions.append((after, headers.get(b"last-event-id", b"").decode() or None))
            elif path.endswith("/messages") and scope["method"] == "POST":
                self.outbound_sends += 1
            elif "/attachments" in path:
                if path.endswith("/attachments") and scope["method"] == "POST":
                    self.attachment_requests["reserve"] += 1
                elif path.endswith("/content") and scope["method"] == "PUT":
                    self.attachment_requests["upload"] += 1
                elif path.endswith("/finalize") and scope["method"] == "POST":
                    self.attachment_requests["finalize"] += 1
                elif path.endswith("/content") and scope["method"] == "GET":
                    self.attachment_requests["download"] += 1
        await self.app(scope, receive, send)


@contextmanager
def resource_listener(f, monkeypatch):
    import runtime.communication_event_http as event_http

    f.authority._receiver_evidence_enabled = False
    f.authority._communication_maintenance_mode = "external"
    data = config(monkeypatch, f, enabled=True).model_dump()
    data["bindings"][0].update(trusted_client=False, agent_slot_id="local-slot")
    data.update(communication_event_stream=True, authorization_refresh_seconds=5,
                communication_attachments=getattr(f.authority, "_communication_attachment_settings", None) is not None)
    settings = ProjectHttpSettings.model_validate(data)
    issuer = IssuerFixture({TOKEN: claims()})
    issuer_client = issuer.client()
    budgets = EventStreamLimits(max_events=64, max_bytes=262144, heartbeat_seconds=0.1, poll_seconds=0.05, slow_consumer_seconds=5)
    register = event_http.register_event_routes

    def trusted_test_budgets(app, **kwargs):
        return register(app, **{**kwargs, "limits": budgets})

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]
        with monkeypatch.context() as construction:
            construction.setattr(event_http, "register_event_routes", trusted_test_budgets)
            app = create_http_app(shared(f), CATALOG, settings, port=port, client=issuer_client)
        explicit_initialize(f)
        seed = fail_b(f)  # Actual pre-call refusal creates a recipient-owned notice, without Native input.
        publish(f)
        observed = ObserveLocalHttp(app)
        server = uvicorn.Server(uvicorn.Config(observed, log_level="critical", access_log=False,
                                               proxy_headers=False, lifespan="on"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            end = time.monotonic() + 8
            while not server.started and thread.is_alive() and time.monotonic() < end:
                time.sleep(0.01)
            assert server.started, "the owned local resource server did not start"
            yield SimpleNamespace(url=f"http://127.0.0.1:{port}", observed=observed, seed=seed)
        finally:
            server.should_exit = True
            thread.join(timeout=8)
            assert not thread.is_alive(), "the owned local resource server did not stop"
            asyncio.run(issuer_client.aclose())


def run_consumer(f, listener):
    executable = shutil.which("node")
    if executable is None:
        pytest.skip("Node runtime unavailable for the actual headless consumer")
    environment = {key: value for key, value in os.environ.items()
                   if not any(part in key.upper() for part in ("DSN", "PGPASSWORD", "DATABASE_URL", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"))}
    environment.update(ACS_HEADLESS_TEST_URL=listener.url, ACS_HEADLESS_TEST_BEARER=TOKEN,
        ACS_HEADLESS_TEST_PROJECT=PROJECT, ACS_HEADLESS_TEST_PEER=PEER, NODE_USE_ENV_PROXY="0", NO_PROXY="127.0.0.1,localhost")
    process = subprocess.Popen([executable, str(ROOT / "sdk/tests/communication-live-consumer.mjs")], cwd=ROOT,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1,
        env=environment, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    messages = queue.Queue(maxsize=32)
    stderr = []
    readers = []

    def read_stdout():
        for line in iter(process.stdout.readline, ""):
            if len(line) > 65536:
                messages.put(("error", "oversized_consumer_control"))
                return
            messages.put(("line", line))
        messages.put(("eof", None))

    def read_stderr():
        count = 0
        for line in iter(process.stderr.readline, ""):
            if count < 16384:
                stderr.append(line[:16384 - count])
                count += len(line)

    for target in (read_stdout, read_stderr):
        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        readers.append(thread)
    evidence = None
    peer_replies, revoked = 0, False
    deadline = time.monotonic() + 120
    try:
        while time.monotonic() < deadline:
            try:
                kind, line = messages.get(timeout=1)
            except queue.Empty:
                if process.poll() is not None:
                    break
                continue
            if kind == "eof":
                break
            assert kind == "line", "invalid headless consumer control channel"
            value = json.loads(line)
            if value.get("type") == "failure":
                pytest.fail("headless consumer failed in phase " + value.get("phase", "unknown") + " (" + str(value.get("code"))
                            + ", reason=" + str(value.get("reason")) + ", stage=" + str(value.get("stage")) + ") diagnostics="
                            + json.dumps(value.get("diagnostics", {}), sort_keys=True))
            if value.get("type") == "result":
                evidence = value["evidence"]
                break
            assert value.get("type") == "request" and type(value.get("id")) is int
            action, result = value.get("action"), {}
            if action == "publish":
                publish(f)
            elif action == "peer_reply":
                assert peer_replies == 0 and not revoked
                reference, sender = value["message_handle"], value["sender"]
                message_id = parse_handle(reference, "message", PROJECT)
                with f.authority._connect() as connection:
                    row = connection.execute("SELECT sender,recipient FROM communication_messages WHERE tenant_id=%s AND project_id=%s AND message_id=%s",
                                             (f.authority.tenant_id, PROJECT, message_id)).fetchone()
                    refs = connection.execute("SELECT packet_json->'attachment_refs' FROM delivery_messages WHERE tenant_id=%s AND message_id=%s",
                                              (f.authority.tenant_id, message_id)).fetchone()[0]
                assert row == (sender, PEER)
                assert len(refs) == 1
                source = f.clients["b"]
                participant = CommunicationClientService(source.service, source.credential_provider())
                downloaded = participant.download_attachment(PROJECT, refs[0]["attachment_id"])
                assert downloaded.data == ATTACHMENT_BYTES
                assert downloaded.sha256 == hashlib.sha256(ATTACHMENT_BYTES).hexdigest()
                returned = f.clients["b"].call("send_message", {"project_id": PROJECT, "to": sender, "content": REPLY,
                    "reply_to": [reference], "activation": "message_only", "client_request_id": "headless-peer-" + uuid.uuid4().hex})["structuredContent"]
                assert returned["ok"], "the real peer reply was rejected"
                result = {"message_handle": returned["data"]["message_handle"], "attachment_participant_read": True}
                peer_replies += 1
            elif action == "revoke_grant":
                assert peer_replies == 1 and not revoked
                with f.authority._connect() as connection:
                    updated = connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE tenant_id=%s AND grant_ref=%s",
                        (f.authority.tenant_id, f.authority.context.grant_ref)).rowcount
                assert updated == 1
                revoked = True
            else:
                pytest.fail("unsupported headless fixture coordination action")
            process.stdin.write(json.dumps({"id": value["id"], "ok": True, "result": result}) + "\n")
            process.stdin.flush()
        assert evidence is not None, "headless consumer did not complete its bounded episode"
        assert process.wait(timeout=8) == 0, "the headless consumer did not exit cleanly"
        assert peer_replies == 1 and revoked
        evidence.update(node_process_reaped=True, peer_reply_commands=peer_replies)
        return evidence
    finally:
        # The exact Popen-owned PID is the only process eligible for cleanup.
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        for pipe in (process.stdin, process.stdout, process.stderr):
            pipe.close()
        for thread in readers:
            thread.join(timeout=2)


@pytest.mark.parametrize("fault", ["replay_failure", "unexpected_snapshot", "unexpected_end", "already_satisfied_failure",
                                  "observer_deadline", "expected_revocation_snapshot"])
def test_headless_observer_preserves_fault_or_deadline_without_weakening_duplicate_proof(fault):
    """Pure observer regressions; importing the consumer starts no HTTP, DB or control reader."""
    executable = shutil.which("node")
    if executable is None:
        pytest.skip("Node runtime unavailable for the headless observer regression")
    script = r"""
import assert from 'node:assert/strict';
import {waitForObservation} from './sdk/tests/communication-live-consumer.mjs';
import {SnapshotRequiredError, StreamReplayError} from './sdk/communication-stream.ts';
const fault = process.env.ACS_HEADLESS_OBSERVER_FAULT;
const observer = {failure:null,snapshotRequired:null,completed:false};
const failure = new StreamReplayError('http_503','synthetic-original-position');
const reset = new SnapshotRequiredError('authorization_changed');
const label = 'duplicate_replay';
let duplicates = 0;
if (fault === 'already_satisfied_failure') {
  observer.failure = failure; duplicates = 1;
} else if (fault !== 'observer_deadline') {
  setImmediate(() => {
    if (fault === 'replay_failure') observer.failure = failure;
    else if (fault === 'unexpected_end') observer.completed = true;
    else {observer.snapshotRequired = reset;observer.completed = true;}
  });
}
if (fault === 'expected_revocation_snapshot') {
  await waitForObservation(() => observer.snapshotRequired !== null,'revocation_control',
    {observer,expectSnapshot:true,milliseconds:2000});
  assert.equal(duplicates,0);
} else {
  await assert.rejects(waitForObservation(() => duplicates > 0,label,
    {observer,milliseconds:fault === 'observer_deadline' ? 5 : 2000}), error => {
    if (fault === 'replay_failure' || fault === 'already_satisfied_failure') return error === failure;
    if (fault === 'unexpected_snapshot') return error === reset;
    return error.stage === label && error.code === (fault === 'unexpected_end' ? 'observer_ended' : 'stage_timeout');
  });
}
console.log(JSON.stringify({fault,cause_preserved:true,duplicate_proof_not_synthesized:true}));
"""
    environment = {key: value for key, value in os.environ.items()
                   if not any(part in key.upper() for part in ("DSN", "PGPASSWORD", "DATABASE_URL"))}
    environment["ACS_HEADLESS_OBSERVER_FAULT"] = fault
    result = subprocess.run([executable, "--input-type=module", "-"], input=script, cwd=ROOT, env=environment,
                            capture_output=True, text=True, encoding="utf-8", timeout=8, check=False,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"fault": fault, "cause_preserved": True, "duplicate_proof_not_synthesized": True}


def test_actual_node_headless_sdk_uses_live_oauth_http_sse_core_and_preserves_local_work_after_revocation(attached, monkeypatch):
    f = attached
    with resource_listener(f, monkeypatch) as listener:
        evidence = run_consumer(f, listener)
        assert listener.observed.outbound_sends == evidence["outbound_send_requests"] == 1
        assert len(listener.observed.event_positions) >= 3
        assert all(after and after == last for after, last in listener.observed.event_positions)
        evidence.update(event_cursor_headers_match=True, actual_sse_connections=len(listener.observed.event_positions))
        assert listener.observed.attachment_requests == {"reserve": 1, "upload": 1, "finalize": 1, "download": 2}
        assert evidence["production_http_client"] and evidence["attachment_reserved_uploaded_finalized"]
        assert evidence["attachment_complete_digest_download"] and evidence["attachment_message_pinned"]
        assert evidence["attachment_participant_read"] and evidence["attachment_draft_refs_preserved"]
        assert evidence["attachment_utf8_bytes"] == len(ATTACHMENT_BYTES)
        with f.authority._connect() as connection:
            assert connection.execute("SELECT count(*) FROM communication_messages").fetchone() == (3,)
            assert connection.execute("SELECT count(*) FROM communication_replies").fetchone() == (1,)
            assert connection.execute("SELECT count(*) FROM communication_client_read_state").fetchone() == (1,)
            assert connection.execute("SELECT count(*) FROM communication_client_drafts WHERE revision=2").fetchone() == (1,)
            assert connection.execute("SELECT count(*) FROM communication_client_notice_seen WHERE seen").fetchone() == (1,)
            assert connection.execute("SELECT count(*) FROM delivery_messages WHERE packet_json->>'content' LIKE %s", ("%HEADLESS_LOCAL_UNSENT_BODY%",)).fetchone() == (0,)
            saved = connection.execute("SELECT a.attachment_id,a.state,a.pinned,a.declared_bytes,a.declared_sha256 FROM communication_attachments a "
                "JOIN communication_message_attachments m USING(tenant_id,project_id,attachment_id)").fetchall()
            assert len(saved) == 1 and saved[0][1:] == ("ready", True, len(ATTACHMENT_BYTES), hashlib.sha256(ATTACHMENT_BYTES).hexdigest())
            assert connection.execute("SELECT count(*) FROM communication_attachment_chunks").fetchone() == (0,)
            assert connection.execute("SELECT attachment_refs FROM communication_client_drafts WHERE revision=2").fetchone() == ([saved[0][0]],)
        assert not any(driver.calls for driver in f.drivers.values())
        evidence.update(actual_core_messages=3, explicit_reply_rows=1, native_input_calls=0,
                        generated_agent_replies=0, local_draft_was_not_sent=True,
                        actual_attachment_operations=listener.observed.attachment_requests)
        encoded = json.dumps(evidence, sort_keys=True, ensure_ascii=False)
        assert TOKEN not in encoded and listener.url not in encoded and "postgresql://" not in encoded and "gAAAA" not in encoded
        assert evidence["host_qualified"] is False and evidence["model_qualified"] is False
        output = ROOT / ".tmp/communication-headless-attachments-live-20261106.json"
        output.write_text(encoded + "\n", encoding="utf-8")
