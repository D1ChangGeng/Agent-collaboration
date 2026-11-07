"""Conversation views and personal REST routes over disposable PostgreSQL.

OAuth introspection and Native drivers are controlled fixtures. These tests use
the actual ClientService/HTTP app and never contact a model or deployment.
"""
from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from runtime.client_contracts import ClientContracts
from runtime.communication_client_queries import conversation_view_id
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_client_storage import adopt_client_storage
from runtime.communication_http import CommunicationHttpError
from runtime.errors import IdempotencyConflict, NotFound, RevisionConflict
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send
from runtime_tests.test_communication_client_oauth import app_for, config, explicit_initialize
from runtime_tests.test_project_http import IssuerFixture, claims

comm = comm_fixture
PROJECT = "project-alpha"
PREFIX = "/api/communication/v1"
ADDRESSES = {"a": "collaborator:project-alpha:local-slot",
             "b": "collaborator:project-alpha:slot-b", "c": "collaborator:project-alpha:slot-c"}
CONTRACTS = ClientContracts()


def client(f, actor="a"):
    current = f.clients[actor]
    return CommunicationClientService(current.service, current.credential_provider())


@pytest.fixture
def views(comm):
    with comm.authority._connect() as connection:
        adopt_client_storage(connection)
    return comm


def domain_counts(f):
    with f.authority._connect() as connection:
        return {table: connection.execute("SELECT count(*) FROM " + table).fetchone()[0]
                for table in ("communication_messages", "delivery_messages", "delivery_attempts", "communication_replies",
                              "domain_events", "outbox")}


def test_simultaneous_first_messages_share_one_conversation_and_preserve_both_authoritative_messages(views):
    f = views
    with ThreadPoolExecutor(max_workers=2) as pool:
        left = pool.submit(send, f, "a", "b", "First from A", activation="message_only")
        right = pool.submit(send, f, "b", "a", "First from B", activation="message_only")
        accepted = [left.result(timeout=15)["data"], right.result(timeout=15)["data"]]
    first = client(f, "a").conversations(PROJECT)["items"]
    second = client(f, "b").conversations(PROJECT)["items"]
    assert len(first) == len(second) == 1
    assert first[0]["conversation_id"] == second[0]["conversation_id"]
    assert first[0]["participants"] == second[0]["participants"] == sorted((ADDRESSES["a"], ADDRESSES["b"]))
    messages = client(f, "a").messages(PROJECT)["items"]
    assert {m["message_handle"] for m in messages} == {m["message_handle"] for m in accepted}
    assert sorted(m["conversation_sequence"] for m in messages) == ["1", "2"]
    assert not any(driver.calls for driver in f.drivers.values())


def test_empty_resolve_uses_real_contact_without_materializing_domain_conversation_or_native(views):
    f, own = views, client(views)
    before = domain_counts(f)
    resolved = own.resolve_conversation(PROJECT, peer=ADDRESSES["b"])
    CONTRACTS.validate("Conversation", resolved)
    assert resolved["participants"] == sorted((ADDRESSES["a"], ADDRESSES["b"]))
    assert resolved["last_message_handle"] is resolved["last_activity_at"] is None
    assert resolved["unread_count"] == resolved["revision"] == 0
    assert own.conversation(PROJECT, resolved["conversation_id"]) == resolved
    assert own.conversations(PROJECT)["items"] == []
    assert domain_counts(f) == before and not any(driver.calls for driver in f.drivers.values())


def test_t041_empty_view_then_first_message_keeps_the_same_unique_conversation(views):
    f, own = views, client(views)
    empty = own.resolve_conversation(PROJECT, peer=ADDRESSES["b"])
    assert own.conversations(PROJECT)["items"] == []
    sent = send(f, content="First authoritative message after empty resolve", activation="message_only")["data"]
    current = own.conversation(PROJECT, empty["conversation_id"])
    assert current["conversation_id"] == empty["conversation_id"]
    assert current["participants"] == empty["participants"]
    assert current["last_message_handle"] == sent["message_handle"]
    for actor in ("a", "b"):
        projected = client(f, actor).conversations(PROJECT)["items"]
        assert len(projected) == 1 and projected[0]["conversation_id"] == empty["conversation_id"]
    history = own.messages(PROJECT, conversation_id=empty["conversation_id"])["items"]
    assert [item["message_handle"] for item in history] == [sent["message_handle"]]
    assert not any(driver.calls for driver in f.drivers.values())


def test_self_foreign_project_and_known_foreign_pair_refs_do_not_grant_membership(views):
    f, own = views, client(views)
    with pytest.raises(CommunicationHttpError) as self_pair:
        own.resolve_conversation(PROJECT, peer=ADDRESSES["a"])
    assert self_pair.value.status_code == 409
    with pytest.raises(CommunicationHttpError) as foreign_project:
        own.resolve_conversation(PROJECT, peer="collaborator:another-project:slot-b")
    assert foreign_project.value.status_code == 400 and foreign_project.value.code == "invalid_argument"
    with pytest.raises(NotFound):
        own.resolve_conversation(PROJECT, peer="collaborator:project-alpha:unknown")
    private = send(f, "b", "c", "Private unrelated conversation", activation="message_only")["data"]
    foreign = conversation_view_id(f.authority.tenant_id, PROJECT, ADDRESSES["b"], ADDRESSES["c"])
    assert own.project_service.profile == "root_manager"
    for method in (own.conversation, own.draft, own.preferences, own.read_state):
        with pytest.raises(NotFound):
            method(PROJECT, foreign)
    assert own.conversations(PROJECT)["items"] == []
    with f.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM communication_client_write_keys").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM communication_messages WHERE message_id=%s", (private["message_id"],)).fetchone() == (1,)


def test_conversation_snapshot_orders_recent_activity_excludes_late_arrivals_and_binds_actor_filters(views):
    f, own = views, client(views)
    send(f, "a", "b", "First pair entry", activation="message_only")
    old_c = send(f, "a", "c", "Second pair entry", activation="message_only")["data"]
    recent_b = send(f, "b", "a", "Latest before snapshot", activation="message_only")["data"]
    first = own.conversations(PROJECT, limit=1)
    assert [item["last_message_handle"] for item in first["items"]] == [recent_b["message_handle"]]
    assert first["page"]["next_cursor"] and first["page"]["snapshot_id"]
    late_c = send(f, "c", "a", "Late pair activity", activation="message_only")["data"]
    tail = own.conversations(PROJECT, limit=1, cursor=first["page"]["next_cursor"])
    CONTRACTS.validate("ConversationPage", tail)
    assert [item["last_message_handle"] for item in tail["items"]] == [old_c["message_handle"]]
    assert tail["page"]["next_cursor"] is None
    anchored_tail = own.conversations(PROJECT, limit=1, cursor=first["page"]["next_cursor"],
                                      snapshot_id=first["page"]["snapshot_id"])
    assert anchored_tail["items"] == tail["items"]
    assert anchored_tail["page"]["snapshot_id"] == first["page"]["snapshot_id"]
    assert own.conversations(PROJECT, limit=1, snapshot_id=first["page"]["snapshot_id"])["items"] == first["items"]
    assert own.conversations(PROJECT, limit=1)["items"][0]["last_message_handle"] == late_c["message_handle"]
    for query in (
        lambda: client(f, "b").conversations(PROJECT, limit=1, cursor=first["page"]["next_cursor"]),
        lambda: own.conversations(PROJECT, limit=1, cursor=first["page"]["next_cursor"], include_archived=True),
        lambda: own.conversations(PROJECT, limit=1, cursor=first["page"]["next_cursor"][:-2] + "xx"),
        lambda: own.conversations(PROJECT, limit=1, snapshot_id=first["page"]["next_cursor"]),
        lambda: own.conversations(PROJECT, limit=1, cursor=first["page"]["next_cursor"],
                                  snapshot_id=first["page"]["next_cursor"]),
    ):
        with pytest.raises(CommunicationHttpError) as rejected:
            query()
        assert rejected.value.code == "cursor_invalid" and rejected.value.status_code == 409


def test_unread_count_uses_pair_local_frontier_and_remains_private_to_each_actor(views):
    f = views
    incoming = send(f, "a", "b", "First incoming", activation="message_only")["data"]
    send(f, "a", "c", "Unrelated global gap", activation="message_only")
    send(f, "b", "a", "Opposite direction within pair", activation="message_only")
    send(f, "c", "a", "Another global gap", activation="message_only")
    latest = send(f, "a", "b", "Second incoming", activation="message_only")["data"]
    own, other = client(f, "b"), client(f, "a")
    view = own.resolve_conversation(PROJECT, peer=ADDRESSES["a"])["conversation_id"]
    assert own.conversation(PROJECT, view)["unread_count"] == 2
    assert other.conversation(PROJECT, view)["unread_count"] == 1
    own.update_read_state(PROJECT, view, {"through_message_handle": latest["message_handle"]},
                          expected_revision=0, client_request_id="read-pair-frontier")
    assert own.conversation(PROJECT, view)["unread_count"] == 0
    assert other.conversation(PROJECT, view)["unread_count"] == 1
    with f.authority._connect() as connection:
        assert connection.execute("SELECT through_sequence FROM communication_client_read_state").fetchone() == (3,)
    unread = own.update_read_state(PROJECT, view, {"through_message_handle": incoming["message_handle"], "unread_override": True},
                                   expected_revision=1, client_request_id="mark-pair-unread")
    assert unread["through_message_handle"] == latest["message_handle"]
    assert own.conversation(PROJECT, view)["unread_count"] == 1
    assert other.read_state(PROJECT, view)["revision"] == 0
    assert not any(driver.calls for driver in f.drivers.values())


def test_archive_and_mute_filter_only_current_actor_and_include_archived_restores_view(views):
    f, own = views, client(views)
    send(f, "a", "b", "Archive this pair", activation="message_only")
    send(f, "a", "c", "Keep this pair", activation="message_only")
    view = own.resolve_conversation(PROJECT, peer=ADDRESSES["b"])["conversation_id"]
    before = domain_counts(f)
    own.update_preferences(PROJECT, view, {"archived": True, "muted": True}, expected_revision=0, client_request_id="archive-pair")
    assert view not in {item["conversation_id"] for item in own.conversations(PROJECT)["items"]}
    all_views = own.conversations(PROJECT, include_archived=True)["items"]
    archived = next(item for item in all_views if item["conversation_id"] == view)
    assert len(all_views) == 2 and archived["archived"] and archived["muted"]
    peer = client(f, "b").conversation(PROJECT, view)
    assert not peer["archived"] and not peer["muted"]
    assert domain_counts(f) == before


def test_draft_before_first_message_has_independent_cas_keys_and_does_not_send(views):
    f, own = views, client(views)
    view = own.resolve_conversation(PROJECT, peer=ADDRESSES["b"])["conversation_id"]
    before = domain_counts(f)
    body = {"content": "Unsent context before first message", "attachment_refs": []}
    saved = own.update_draft(PROJECT, view, body, expected_revision=0, client_request_id="before-first-send")
    assert saved["revision"] == 1 and saved["updated_at"] is not None
    assert own.update_draft(PROJECT, view, body, expected_revision=0, client_request_id="before-first-send") == saved
    with pytest.raises(IdempotencyConflict):
        own.update_draft(PROJECT, view, {**body, "content": "Changed intent"}, expected_revision=0, client_request_id="before-first-send")
    with pytest.raises(RevisionConflict):
        own.update_draft(PROJECT, view, body, expected_revision=0, client_request_id="different-write")
    assert own.draft(PROJECT, view) == saved and client(f, "b").draft(PROJECT, view)["revision"] == 0
    assert own.conversation(PROJECT, view)["last_message_handle"] is None
    assert domain_counts(f) == before
    with f.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM communication_client_write_keys").fetchone() == (1,)
    assert not any(driver.calls for driver in f.drivers.values())


def test_real_oauth_http_personal_routes_enforce_quoted_versions_and_independent_200_409_writes(comm, monkeypatch):
    f = comm
    cfg = config(monkeypatch, f, enabled=True)

    async def exercise():
        async with IssuerFixture({"valid": claims()}).client() as issuer_client:
            app = app_for(f, cfg, issuer_client)
            explicit_initialize(f)
            async with (app.router.lifespan_context(app),
                httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765",
                                  headers={"Authorization": "Bearer valid"}) as http):
                base = PREFIX + f"/projects/{PROJECT}/conversations"
                resolved = await http.get(base + "/resolve", params={"with": ADDRESSES["b"]})
                assert resolved.status_code == 200, resolved.text
                view = resolved.json()["conversation_id"]
                target = base + "/" + view
                body = {"content": "HTTP draft before first send", "attachment_refs": []}
                for version in (None, "0", 'W/"0"', '"*"', '"01"', '"-1"', '"9223372036854775807"'):
                    headers = {"Idempotency-Key": "invalid-header"}
                    if version is not None:
                        headers["If-Match"] = version
                    rejected = await http.put(target + "/draft", headers=headers, json=body)
                    assert rejected.status_code == 400, rejected.text
                duplicate_version = await http.put(target + "/draft", json=body,
                    headers=[("If-Match", '"0"'), ("If-Match", '"0"'), ("Idempotency-Key", "duplicate-header")])
                assert duplicate_version.status_code == 400
                saved = await http.put(target + "/draft", headers={"If-Match": '"0"', "Idempotency-Key": "http-draft"}, json=body)
                assert saved.status_code == 200, saved.text
                CONTRACTS.validate("Draft", saved.json())
                assert saved.json()["revision"] == 1
                replay = await http.put(target + "/draft", headers={"If-Match": '"0"', "Idempotency-Key": "http-draft"}, json=body)
                assert replay.status_code == 200 and replay.json() == saved.json()
                stale = await http.put(target + "/draft", headers={"If-Match": '"0"', "Idempotency-Key": "http-stale"}, json=body)
                assert stale.status_code == 409 and stale.json()["error"]["code"] == "revision_conflict"
                conflict = await http.put(target + "/draft", headers={"If-Match": '"0"', "Idempotency-Key": "http-draft"},
                                          json={**body, "content": "Different intent"})
                assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "idempotency_conflict"
                preferences = await http.put(target + "/preferences", headers={"If-Match": '"0"', "Idempotency-Key": "http-prefs"},
                                             json={"archived": True, "muted": True})
                assert preferences.status_code == 200 and preferences.json()["revision"] == 1
                assert (await http.get(target + "/preferences")).json() == preferences.json()
                sent = await http.post(PREFIX + f"/projects/{PROJECT}/messages", headers={"Idempotency-Key": "http-first-message"},
                    json={"to": ADDRESSES["b"], "content": "Actual first message", "activation": "message_only"})
                assert sent.status_code == 201, sent.text
                value = sent.json()["message"]
                replied = f.clients["b"].call("send_message", {"project_id": PROJECT, "to": value["sender"],
                    "content": "Actual incoming peer reply", "reply_to": [value["message_handle"]],
                    "activation": "message_only", "client_request_id": uuid.uuid4().hex})["structuredContent"]
                assert replied["ok"], replied
                read = await http.put(target + "/read-state", headers={"If-Match": '"0"', "Idempotency-Key": "http-read"},
                                      json={"through_message_handle": replied["data"]["message_handle"]})
                assert read.status_code == 200 and read.json()["revision"] == 1, read.text
                assert (await http.get(target + "/read-state")).json() == read.json()
                assert view not in {item["conversation_id"] for item in (await http.get(base)).json()["items"]}
                included = await http.get(base, params={"include_archived": "true"})
                assert included.status_code == 200 and included.json()["items"][0]["conversation_id"] == view
                deleted = await http.delete(target + "/draft", headers={"If-Match": '"1"', "Idempotency-Key": "http-delete"})
                assert deleted.status_code == 200 and deleted.json()["revision"] == 2 and deleted.json()["content"] == ""
                assert (await http.get(target + "/draft")).json() == deleted.json()
                foreign = await http.get(base + "/resolve", params={"with": "collaborator:another-project:slot-b"})
                assert foreign.status_code in {400, 404}, foreign.text

    asyncio.run(exercise())
    assert not any(driver.calls for driver in f.drivers.values())
