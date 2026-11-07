"""Snapshot/version regressions on actual disposable PostgreSQL and local HTTP.

The issuer and Native driver are explicit fixtures. Thread pauses surround local
SQL reads only; no receiver call or HTTP request runs under a test-held DB lock.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from threading import Event

import httpx
import pytest

from runtime.communication_client_queries import conversation_view_id
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_client_storage import adopt_client_storage, read_delivery_version
from runtime.communication_http import CommunicationHttpError
from runtime.project_http import ProjectHttpSettings
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send
from runtime_tests.test_communication_client_oauth import app_for, config, explicit_initialize
from runtime_tests.test_project_http import IssuerFixture, claims

comm = comm_fixture
PROJECT = "project-alpha"
PREFIX = "/api/communication/v1"
ADDRESS_A = "collaborator:project-alpha:local-slot"
ADDRESS_B = "collaborator:project-alpha:slot-b"


def client(f, actor="a"):
    current = f.clients[actor]
    return CommunicationClientService(current.service, current.credential_provider())


@pytest.fixture
def consistent(comm):
    with comm.authority._connect() as connection:
        adopt_client_storage(connection)
    return comm


@asynccontextmanager
async def oauth_http(f, monkeypatch, *, bound_agent=False):
    cfg = config(monkeypatch, f, enabled=True)
    if bound_agent:
        # Operator-established Agent binding for reading that real Agent's
        # existing messages; request bodies never select this identity.
        data = cfg.model_dump()
        data["bindings"][0].update(trusted_client=False, agent_slot_id="local-slot")
        cfg = ProjectHttpSettings.model_validate(data)
    async with IssuerFixture({"valid": claims()}).client() as issuer_client:
        app = app_for(f, cfg, issuer_client)
        explicit_initialize(f)
        async with (app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765",
                              headers={"Authorization": "Bearer valid"}) as http):
            yield http


def test_combined_long_message_filters_produce_reusable_bounded_http_page_tokens(consistent, monkeypatch):
    f = consistent
    slot = "long-contact-" + "b" * 115  # Maximum legal 128-character project identifier.
    peer = "collaborator:" + PROJECT + ":" + slot
    with f.authority._connect() as connection:
        connection.execute("INSERT INTO agent_slots(agent_slot_id,tenant_id,scope_id,status) VALUES (%s,%s,'local-scope','active')",
                           (slot, f.authority.tenant_id))
        connection.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,scope_id,permissions,expires_at) "
            "SELECT 'grant:long-contact',tenant_id,'agent:long-contact',authority_id,authority_incarnation,scope_id,permissions,expires_at "
            "FROM grants WHERE tenant_id=%s AND grant_ref='grant:b'", (f.authority.tenant_id,))
        connection.execute("INSERT INTO collaboration_memberships(tenant_id,project_id,principal_ref,grant_ref,profile,agent_slot_id) "
            "VALUES (%s,%s,'agent:long-contact','grant:long-contact','engineer',%s)", (f.authority.tenant_id, PROJECT, slot))
    references = []
    for text in ("Long-filter message one", "Long-filter message two"):
        result = f.clients["a"].call("send_message", {"project_id": PROJECT, "to": peer, "content": text,
            "activation": "message_only", "client_request_id": uuid.uuid4().hex})["structuredContent"]
        assert result["ok"], result
        references.append(result["data"]["message_handle"])
    conversation = conversation_view_id(f.authority.tenant_id, PROJECT, ADDRESS_A, peer)
    params = {"limit": 1, "with": peer, "conversation_id": conversation, "direction": "outgoing"}
    first = client(f).messages(PROJECT, **params)
    page = first["page"]
    assert page["next_cursor"] and len(page["next_cursor"]) <= 2048
    assert page["snapshot_id"] and len(page["snapshot_id"]) <= 512

    async def exercise():
        async with oauth_http(f, monkeypatch, bound_agent=True) as http:
            target = PREFIX + f"/projects/{PROJECT}/messages"
            cross_binding = await http.get(target, params={**params, "snapshot_id": page["snapshot_id"]})
            assert cross_binding.status_code == 409 and cross_binding.json()["error"]["code"] == "cursor_invalid", cross_binding.text
            initial_http = await http.get(target, params=params)
            assert initial_http.status_code == 200, initial_http.text
            http_page = initial_http.json()["page"]
            assert http_page["snapshot_id"] and len(http_page["snapshot_id"]) <= 512
            assert http_page["next_cursor"] and len(http_page["next_cursor"]) <= 2048
            replay = await http.get(target, params={**params, "snapshot_id": http_page["snapshot_id"]})
            assert replay.status_code == 200, replay.text
            assert [item["message_handle"] for item in replay.json()["items"]] == [references[0]]
            tail = await http.get(target, params={**params, "cursor": http_page["next_cursor"], "snapshot_id": http_page["snapshot_id"]})
            assert tail.status_code == 200, tail.text
            assert [item["message_handle"] for item in tail.json()["items"]] == [references[1]]
            assert tail.json()["page"]["next_cursor"] is None

    asyncio.run(exercise())
    assert not any(driver.calls for driver in f.drivers.values())


def test_message_snapshot_keeps_original_reply_metadata_while_fresh_read_sees_late_explicit_reply(consistent):
    f, own = consistent, client(consistent)
    original = send(f, activation="message_only")["data"]
    first = own.messages(PROJECT, peer=ADDRESS_B)
    original_view = first["items"][0]
    assert original_view["revision"] == 1 and original_view["first_reply_handle"] is None
    reply = send(f, "b", "a", "A later explicit reply", activation="message_only",
                 reply_to=[original["message_handle"]])["data"]
    fixed = own.messages(PROJECT, peer=ADDRESS_B, snapshot_id=first["page"]["snapshot_id"])
    assert fixed["items"] == [original_view]
    current = own.read_message(PROJECT, original["message_handle"])
    assert current["message"]["revision"] == 2
    assert current["message"]["first_reply_handle"] == reply["message_handle"]
    assert current["first_reply"]["message_handle"] == current["message"]["first_reply_handle"]
    assert current["first_reply"]["content"]["text"] == "A later explicit reply"


@pytest.mark.parametrize("change", ["archive", "read"])
def test_private_metadata_change_invalidates_old_conversation_snapshot_instead_of_mixing_views(consistent, change):
    f, own = consistent, client(consistent)
    send(f, "a", "b", "Own pair", activation="message_only")
    incoming = send(f, "b", "a", "Incoming pair", activation="message_only")["data"]
    send(f, "a", "c", "Other own pair", activation="message_only")
    view = own.resolve_conversation(PROJECT, peer=ADDRESS_B)["conversation_id"]
    before = own.conversations(PROJECT, limit=1, include_archived=True)
    assert before["page"]["next_cursor"] and len(before["page"]["snapshot_id"]) <= 512
    if change == "archive":
        own.update_preferences(PROJECT, view, {"archived": True}, expected_revision=0, client_request_id="archive-after-page")
    else:
        own.update_read_state(PROJECT, view, {"through_message_handle": incoming["message_handle"]},
                              expected_revision=0, client_request_id="read-after-page")
    for token in ({"cursor": before["page"]["next_cursor"]}, {"snapshot_id": before["page"]["snapshot_id"]}):
        with pytest.raises(CommunicationHttpError) as rejected:
            own.conversations(PROJECT, limit=1, include_archived=True, **token)
        assert rejected.value.status_code == 409 and rejected.value.code == "cursor_invalid"
    fresh = own.conversations(PROJECT, include_archived=True)
    actual = next(item for item in fresh["items"] if item["conversation_id"] == view)
    assert actual["archived"] is (change == "archive")
    assert actual["unread_count"] == (1 if change == "archive" else 0)


def test_private_state_change_during_page_returns_conflict_without_partial_mixed_metadata(consistent, monkeypatch):
    f, own = consistent, client(consistent)
    send(f, "a", "b", "One own pair", activation="message_only")
    send(f, "a", "c", "Second own pair", activation="message_only")
    entered, release = Event(), Event()
    first_view = []
    original = own._conversation_view

    def pause_after_first_view(*args, **kwargs):
        value = original(*args, **kwargs)
        if not entered.is_set():
            first_view.append(value["conversation_id"])
            entered.set()
            assert release.wait(5), "local private-state writer did not release the reader"
        return value

    monkeypatch.setattr(own, "_conversation_view", pause_after_first_view)
    with ThreadPoolExecutor(max_workers=1) as pool:
        reading = pool.submit(own.conversations, PROJECT, include_archived=True)
        try:
            assert entered.wait(5)
            client(f).update_preferences(PROJECT, first_view[0], {"muted": True},
                                          expected_revision=0, client_request_id="during-page")
        finally:
            release.set()
        with pytest.raises(CommunicationHttpError) as rejected:
            reading.result(timeout=10)
    assert rejected.value.status_code == 409 and rejected.value.code == "cursor_invalid"
    assert next(item for item in client(f).conversations(PROJECT)["items"]
                if item["conversation_id"] == first_view[0])["muted"] is True


def freeze_first_version_read(service, monkeypatch):
    locked, release = Event(), Event()
    observation = {}
    original = service._lock_delivery_version

    def pause(cursor, *args):
        version = original(cursor, *args)
        if not locked.is_set():
            observation.update(pid=cursor.connection.info.backend_pid, version=version[0])
            locked.set()
            assert release.wait(5), "local version reader was not released"
        return version

    monkeypatch.setattr(service, "_lock_delivery_version", pause)
    return locked, release, observation


def assert_writer_waits_for_reader(f, reader_pid, writing):
    # PostgreSQL proves a real competing writer is blocked by this read, rather
    # than relying on a scheduler delay to claim the shared fence was exercised.
    end = time.monotonic() + 3
    with f.authority._connect() as connection:
        connection.autocommit = True
        while time.monotonic() < end:
            if connection.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity "
                "WHERE %s=ANY(pg_blocking_pids(pid)))", (reader_pid,)).fetchone()[0]:
                return
            if writing.done():
                writing.result()
                pytest.fail("the writer committed while the reader's view was still frozen")
            time.sleep(0.02)
    pytest.fail("the competing database writer never reached the version fence")


def test_delivery_receipts_and_revision_are_from_same_view_during_real_dispatch_race(consistent, monkeypatch):
    f, own = consistent, client(consistent)
    original = send(f)["data"]
    before = own.delivery(PROJECT, original["message_handle"])
    locked, release, observed = freeze_first_version_read(own, monkeypatch)
    identity = {"tenant_id": f.authority.tenant_id, "message_id": original["message_id"], "operation_id": original["operation_id"]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        reading = pool.submit(own.delivery, PROJECT, original["message_handle"])
        try:
            assert locked.wait(5)
            writing = pool.submit(f.dispatcher.dispatch, identity)
            assert_writer_waits_for_reader(f, observed["pid"], writing)
            assert not f.drivers["b"].calls
        finally:
            release.set()
        frozen = reading.result(timeout=10)
        assert writing.result(timeout=10)["status"] == "delivered"
    assert frozen == before and frozen["revision"] == observed["version"]
    fresh = own.delivery(PROJECT, original["message_handle"])
    with f.authority._connect() as connection, connection.cursor() as cursor:
        revision, _updated = read_delivery_version(cursor, f.authority.tenant_id, original["message_id"])
    assert fresh["revision"] == revision and fresh["revision"] > frozen["revision"]
    assert fresh["target_inbox_committed"] and fresh["native"]["state"] == "accepted"
    assert fresh["native"]["evidence_ref"] and len(f.drivers["b"].calls) == 1


def test_explicit_reply_writer_cannot_split_nested_reply_from_message_metadata(consistent, monkeypatch):
    f, own = consistent, client(consistent)
    original = send(f, activation="message_only")["data"]
    locked, release, observed = freeze_first_version_read(own, monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reading = pool.submit(own.read_message, PROJECT, original["message_handle"])
        try:
            assert locked.wait(5)
            writing = pool.submit(send, f, "b", "a", "Concurrent explicit reply", activation="message_only",
                                  reply_to=[original["message_handle"]])
            assert_writer_waits_for_reader(f, observed["pid"], writing)
        finally:
            release.set()
        frozen = reading.result(timeout=10)
        reply = writing.result(timeout=10)["data"]
    assert frozen["first_reply"] is None and frozen["message"]["first_reply_handle"] is None
    assert frozen["message"]["revision"] == 1
    fresh = own.read_message(PROJECT, original["message_handle"])
    assert fresh["message"]["revision"] == 2
    assert fresh["first_reply"]["message_handle"] == fresh["message"]["first_reply_handle"] == reply["message_handle"]
    assert not any(driver.calls for driver in f.drivers.values())


def test_http_transaction_rejections_have_no_effect_and_postcommit_projection_failure_keeps_commit(consistent, monkeypatch):
    f = consistent

    async def exercise():
        async with oauth_http(f, monkeypatch) as http:
            base = PREFIX + f"/projects/{PROJECT}/conversations"
            resolved = await http.get(base + "/resolve", params={"with": ADDRESS_B})
            assert resolved.status_code == 200, resolved.text
            view = resolved.json()["conversation_id"]
            target = base + "/" + view
            malformed = await http.put(target + "/read-state", json={"through_message_handle": "message:another-project:unknown"},
                headers={"If-Match": '"0"', "Idempotency-Key": "malformed-incoming"})
            assert malformed.status_code == 400 and malformed.json()["error"]["effect_state"] == "none", malformed.text
            saved = await http.put(target + "/preferences", json={"muted": True},
                headers={"If-Match": '"0"', "Idempotency-Key": "preference-key"})
            assert saved.status_code == 200, saved.text
            for key, body, code in (("new-stale-key", {"muted": False}, "revision_conflict"),
                                    ("preference-key", {"muted": False}, "idempotency_conflict")):
                rejected = await http.put(target + "/preferences", json=body,
                    headers={"If-Match": '"0"', "Idempotency-Key": key})
                assert rejected.status_code == 409 and rejected.json()["error"]["code"] == code, rejected.text
                assert rejected.json()["error"]["effect_state"] == "none"
            original = CommunicationClientService.update_draft

            def commit_then_break_projection(self, *args, **kwargs):
                result = original(self, *args, **kwargs)
                return {**result, "revision": "controlled-invalid-output"}

            body = {"content": "Private draft survived commit", "attachment_refs": []}
            with monkeypatch.context() as fault:
                fault.setattr(CommunicationClientService, "update_draft", commit_then_break_projection)
                failed = await http.put(target + "/draft", json=body,
                    headers={"If-Match": '"0"', "Idempotency-Key": "committed-draft-key"})
            assert failed.status_code == 503 and failed.json()["error"]["effect_state"] == "committed", failed.text
            assert body["content"] not in failed.text and "controlled-invalid-output" not in failed.text
            retry = await http.put(target + "/draft", json=body,
                headers={"If-Match": '"0"', "Idempotency-Key": "committed-draft-key"})
            assert retry.status_code == 200 and retry.json()["revision"] == 1 and retry.json()["content"] == body["content"]
            assert (await http.get(target + "/preferences")).json() == saved.json()

    asyncio.run(exercise())
    with f.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM communication_client_write_keys").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone() == (0,)
    assert not any(driver.calls for driver in f.drivers.values())
