"""Exact P1 GWT cases on actual isolated Core/PG and mounted OAuth/TCP.

T055/T056 use the same admitted Slot identities through the existing MCP and
REST paths. T045 overlaps a real message transaction with a real RR snapshot.
Native inspection, where configured by the shared fixture, remains controlled.
No Native process/model/production service is contacted.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx

from runtime.communication_client_service import CommunicationClientService
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send
from runtime_tests.test_communication_client_native_links import native as native_fixture
from runtime_tests.test_communication_client_snapshot import ADDRESSES, client, publish
from runtime_tests.test_communication_client_snapshot import snapshots as snapshots_fixture
from runtime_tests.test_communication_native_link_live_http import tcp_listener

comm, native, snapshots = comm_fixture, native_fixture, snapshots_fixture
PROJECT = "project-alpha"
BASE = "/api/communication/v1/projects/" + PROJECT


def test_t055_same_actor_mcp_and_http_equivalent_send_share_domain_identity_and_defaults(native, monkeypatch):
    f, text = native.f, "Same A equivalent natural message 🧭"
    via_mcp = send(f, "a", "b", text, activation="message_only")["data"]
    with tcp_listener(native, monkeypatch) as url, httpx.Client(base_url=url, trust_env=False, timeout=15) as http:
        response = http.post(BASE + "/messages", headers={"Authorization": "Bearer link-a",
            "Idempotency-Key": "t055-equivalent-http"}, json={"to": ADDRESSES["b"], "content": text,
            "activation": "message_only"})
        assert response.status_code == 201, response.text
        via_http = response.json()
    own = client(f)
    left = own.read_message(PROJECT, via_mcp["message_handle"])["message"]
    right = own.read_message(PROJECT, via_http["message"]["message_handle"])["message"]
    assert left["sender"] == right["sender"] == ADDRESSES["a"]
    assert left["to"] == right["to"] == ADDRESSES["b"]
    assert left["content"] == right["content"] and left["reply_to"] == right["reply_to"] == []
    assert left["conversation_id"] == right["conversation_id"]
    with f.authority._connect() as connection:
        rows = connection.execute("SELECT packet_json FROM delivery_messages WHERE message_id=ANY(%s) ORDER BY message_id",
            ([via_mcp["message_id"], via_http["message"]["message_handle"].rsplit(":", 1)[1]],)).fetchall()
        assert len(rows) == 2
        for field in ("schema_version", "project_id", "sender", "recipient", "target_scope_id", "target_agent_slot_id",
                      "content", "activation", "response_mode", "reply_to"):
            assert rows[0][0][field] == rows[1][0][field], field
        assert connection.execute("SELECT count(*) FROM delivery_attempts").fetchone() == (0,)


def test_t056_ordinary_agent_cannot_use_http_recovery_to_bypass_mcp_manager_policy(native, monkeypatch):
    f = native.f
    rejected = f.clients["b"].call("configure_team", {"project_id": PROJECT,
        "prepare_native": False, "members": [{"agent_slot_id": "slot-b", "display_name": "Unapproved change"}]})["structuredContent"]
    assert rejected["ok"] is False
    with f.authority._connect() as connection:
        before = connection.execute("SELECT count(*) FROM outbox WHERE topic='communication.receiver.recovery'").fetchone()[0]
        teams = connection.execute("SELECT revision,definition FROM collaboration_teams ORDER BY scope_id").fetchall()
    with tcp_listener(native, monkeypatch) as url, httpx.Client(base_url=url, trust_env=False, timeout=15) as http:
        response = http.post(BASE + "/receivers/" + native.body["receiver_ref"] + "/actions",
            headers={"Authorization": "Bearer link-b", "Idempotency-Key": "t056-manager-denied"},
            json={"action": "prepare_receiver", "expected_revision": native.body["expected_binding_epoch"],
                "reason": "An ordinary Slot cannot prepare management capacity"})
        assert response.status_code == 403, response.text
        assert response.json()["error"]["effect_state"] == "none"
    with f.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM outbox WHERE topic='communication.receiver.recovery'").fetchone()[0] == before
        assert connection.execute("SELECT revision,definition FROM collaboration_teams ORDER BY scope_id").fetchall() == teams
    assert native.reads == []


def test_t045_p1_message_commit_overlaps_real_rr_cut_and_all_postcut_messages_replay(snapshots, monkeypatch):
    f, own = snapshots, client(snapshots)
    cut_started, writer_entered = Event(), Event()
    original_contacts = CommunicationClientService.contacts
    original_send = f.clients["b"].service._send_message
    rr_cuts = []

    def sending(*args, **kwargs):
        cursor = args[1]
        assert cursor.connection.closed is False
        writer_entered.set()  # Actual public MCP call has entered its PG transaction.
        return original_send(*args, **kwargs)

    def contacts(facade, project, **kwargs):
        result = original_contacts(facade, project, **kwargs)
        connection = getattr(facade.authority, "_transaction_connection", None)
        if connection is not None and connection.execute("SHOW transaction_isolation").fetchone() == ("repeatable read",):
            rr_cuts.append(True)
            cut_started.set()
            assert writer_entered.wait(5), "writer must overlap the actual RR cut"
        return result

    monkeypatch.setattr(f.clients["b"].service, "_send_message", sending)
    monkeypatch.setattr(CommunicationClientService, "contacts", contacts)

    def during_snapshot():
        assert cut_started.wait(8)
        return send(f, "b", "a", "Concurrent P1 message", activation="message_only")["data"]

    with ThreadPoolExecutor(max_workers=1) as pool:
        writing = pool.submit(during_snapshot)
        captured = own.snapshot(PROJECT)
        concurrent = writing.result(timeout=15)
    assert rr_cuts and writer_entered.is_set()
    after = send(f, "b", "a", "Guaranteed after final P1 cut", activation="message_only")["data"]
    publish(f)
    replay = own.event_batch(PROJECT, after_cursor=captured["after_cursor"])
    committed = {e["resource_ref"] for e in replay.events if e["kind"] == "message.committed"}
    assert after["message_handle"] in committed
    captured_messages = {row["last_message_handle"] for row in captured["conversations"]}
    assert concurrent["message_handle"] in captured_messages | committed
    assert not any(driver.calls for driver in f.drivers.values())
    with f.authority._connect() as connection:
        for table in ("communication_client_read_state", "communication_client_preferences", "communication_client_drafts"):
            assert connection.execute("SELECT count(*) FROM " + table).fetchone() == (0,)
