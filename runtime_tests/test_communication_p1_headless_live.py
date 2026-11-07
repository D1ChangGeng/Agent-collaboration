"""P1-only actual SDK/TCP/OAuth/PG episode; optional P2 is not a prerequisite.

E2 protocol evidence only. Issuer and existing Native status readback are
controlled fixtures; no installed Host, real Native input or model is qualified.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

import pytest

from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_client_native_links import native as native_fixture
from runtime_tests.test_communication_native_link_live_http import PROJECT, publish, tcp_listener

comm, native = comm_fixture, native_fixture
ROOT = Path(__file__).resolve().parents[1]
PEER = "collaborator:project-alpha:slot-b"
REPLY = "P1 explicit peer reply 🧭"


def test_actual_production_sdk_p1_episode_covers22_operations_without_any_p2_calls(native, monkeypatch):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable for the actual P1-only SDK consumer")
    with tcp_listener(native, monkeypatch) as url:
        assert getattr(native.f.authority, "_communication_attachments_enabled", False) is False
        environment = {key: value for key, value in os.environ.items() if not any(
            part in key.upper() for part in ("DSN", "PGPASSWORD", "DATABASE_URL", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"))}
        environment.update(ACS_P1_TEST_URL=url, ACS_P1_TEST_BEARER="link-a", NODE_USE_ENV_PROXY="0", NO_PROXY="127.0.0.1,localhost")
        process = subprocess.Popen([node, str(ROOT / "sdk/tests/communication-p1-live-consumer.mjs")], cwd=ROOT,
            env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        incoming, stderr = queue.Queue(maxsize=32), []

        def output():
            for line in process.stdout:
                if len(line) > 65536:
                    incoming.put(None)
                    return
                incoming.put(line)
            incoming.put(None)

        def errors():
            count = 0
            for line in process.stderr:
                if count < 16384:
                    stderr.append(line[:16384 - count])
                    count += len(line)

        readers = [threading.Thread(target=output, daemon=True), threading.Thread(target=errors, daemon=True)]
        for reader in readers:
            reader.start()
        process.stdin.write(json.dumps({"type": "configuration", "project": PROJECT, "peer": PEER,
            "receiver": native.body["receiver_ref"], "nativeLink": native.body}) + "\n")
        process.stdin.flush()
        evidence, replies, revoked = None, 0, False
        try:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                try:
                    line = incoming.get(timeout=1)
                except queue.Empty:
                    continue
                assert line is not None, "P1 consumer exited before evidence: " + "".join(stderr)
                value = json.loads(line)
                assert value.get("type") != "failure", value
                if value["type"] == "result":
                    evidence = value["evidence"]
                    break
                assert value["type"] == "request" and type(value["id"]) is int
                result = {"done": True}
                if value["action"] == "publish":
                    publish(native)
                elif value["action"] == "peer_reply":
                    assert replies == 0 and not revoked
                    returned = native.f.clients["b"].call("send_message", {"project_id": PROJECT,
                        "to": value["sender"], "content": REPLY, "reply_to": [value["message_handle"]],
                        "activation": "message_only", "client_request_id": "p1-peer-" + uuid.uuid4().hex})["structuredContent"]
                    assert returned["ok"], returned
                    result = {"message_handle": returned["data"]["message_handle"]}
                    replies += 1
                else:
                    assert value["action"] == "revoke" and replies == 1 and not revoked
                    with native.f.authority._connect() as connection:
                        assert connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                            (native.f.clients["a"].service.context.grant_ref,)).rowcount == 1
                    revoked = True
                process.stdin.write(json.dumps({"id": value["id"], "result": result}) + "\n")
                process.stdin.flush()
            assert evidence is not None and replies == 1 and revoked
            assert process.wait(timeout=8) == 0
            assert evidence["p1_operations"] == 22 and evidence["p2_calls"] == 0
            assert evidence["attachment_flag_enabled"] is False and evidence["send_http_requests"] == 3
            assert evidence["replay_duplicates"] > 0 and evidence["revoked_cache_cleared"]
            ui_scope = json.loads((ROOT / "RFC_TEMP_SOURCE/ACS-Core-Stage-Agnostic-Revision-Pack-v1.1.0/contracts/ui-scope.json").read_text(encoding="utf-8"))
            required_rows = {item["id"] for item in ui_scope["features"] if item["tier"] == "P1_required" and item["authority"] != "host"}
            assert {item["id"] for item in evidence["ui_service_rows"]} == required_rows
            assert all(item["scope"] == "actual_ACS_service_operations" and item["operations"]
                and set(item["operations"]) <= set(evidence["operations"]) for item in evidence["ui_service_rows"])
            assert not any(evidence[field] for field in ("installed_host_qualified", "real_model_qualified", "public_ingress_qualified", "host_read_action_grant"))
            with native.f.authority._connect() as connection:
                assert connection.execute("SELECT count(*) FROM communication_messages").fetchone() == (3,)
                assert connection.execute("SELECT count(*) FROM communication_replies").fetchone() == (1,)
                assert connection.execute("SELECT count(*) FROM communication_native_links").fetchone() == (1,)
                assert connection.execute("SELECT count(*) FROM communication_native_link_history").fetchone() == (1,)
                assert connection.execute("SELECT count(*) FROM communication_native_link_requests").fetchone() == (1,)
                assert connection.execute("SELECT count(*) FROM outbox WHERE topic='communication.receiver.recovery'").fetchone() == (1,)
                for table in ("communication_client_drafts", "communication_client_read_state", "communication_client_preferences"):
                    assert connection.execute("SELECT count(*) FROM " + table).fetchone() == (0,)
                attachment_table = connection.execute("SELECT to_regclass('communication_attachments')").fetchone()[0]
                if attachment_table is not None:
                    assert connection.execute("SELECT count(*) FROM communication_attachments").fetchone() == (0,)
            assert not any(driver.calls for driver in native.f.drivers.values())
            evidence.update(actual_core_messages=3, actual_explicit_reply_rows=1, actual_recovery_operations=1,
                optional_p2_state_rows=0, existing_session_status_reads=len(native.reads), node_process_reaped=True)
            encoded = json.dumps(evidence, sort_keys=True)
            assert "link-a" not in encoded and url not in encoded and "postgresql://" not in encoded and "gAAAA" not in encoded
            (ROOT / ".tmp/communication-p1-live-evidence-20261106.json").write_text(encoded + "\n", encoding="utf-8")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            for pipe in (process.stdin, process.stdout, process.stderr):
                pipe.close()
            for reader in readers:
                reader.join(timeout=2)
