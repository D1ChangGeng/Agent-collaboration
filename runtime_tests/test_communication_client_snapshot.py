"""Consistent authorized snapshots on actual PostgreSQL and local OAuth ingress.

Provider evidence and issuer responses are controlled fixtures. These tests do
not qualify a live Native Session or public ingress. Every interleaving writes
actual source rows; no fake database observations are returned.
"""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import psycopg
import pytest

import runtime.communication_client_snapshot as snapshot_module
from runtime.client_contracts import ClientContracts
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_client_storage import ClientStateIdentity, write_read_state
from runtime.communication_event_storage import publish_event_intents
from runtime.communication_http import CommunicationHttpError, _run_with_refresh
from runtime.communication_snapshot_storage import SnapshotLimits
from runtime.domain import DomainAuthority
from runtime.errors import AuthorizationDenied, InvalidToolArgument
from runtime.project_http import IntrospectionVerifier, OAuthProjectService, TokenAuthorization
from runtime.surfaces import SharedService
from runtime_tests.test_communication import CATALOG, call, send
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_client_oauth import app_for, config, explicit_initialize
from runtime_tests.test_communication_client_receivers import measured
from runtime_tests.test_notification_continuity import shared_principal_clients
from runtime_tests.test_project_http import IssuerFixture, claims, settings

comm = comm_fixture
PROJECT, PREFIX = "project-alpha", "/api/communication/v1"
ADDRESSES = {"a": "collaborator:project-alpha:local-slot", "b": "collaborator:project-alpha:slot-b", "c": "collaborator:project-alpha:slot-c"}
CONTRACTS = ClientContracts()


def client(f, actor="a"):
    current = f.clients[actor]
    return CommunicationClientService(current.service, current.credential_provider())


def flags(f):
    for current in f.clients.values():
        current.service.service.authority._communication_events_enabled = True


@pytest.fixture
def snapshots(comm):
    flags(comm)
    comm.clients["a"].service.initialize()
    return comm


def publish(f):
    with psycopg.connect(f.dsn) as connection:
        while publish_event_intents(connection, f.authority.tenant_id, PROJECT, limit=1000):
            pass


def all_frozen(service, captured, family, *, limit=1):
    result = list(captured[family])
    cursor = captured["pages"][family + "_cursor"]
    while cursor is not None:
        value = getattr(service, family)(PROJECT, limit=limit, snapshot_id=captured["snapshot_id"], cursor=cursor)
        CONTRACTS.validate({"contacts": "ContactPage", "conversations": "ConversationPage", "receivers": "ReceiverPage"}[family], value)
        assert value["page"]["snapshot_id"] == captured["snapshot_id"]
        result.extend(value["items"])
        cursor = value["page"]["next_cursor"]
    return result


def cache_count(f):
    with psycopg.connect(f.dsn) as connection:
        return connection.execute("SELECT count(*) FROM communication_snapshots").fetchone()[0]


def test_snapshot_default_off_and_invalid_page_limits_need_no_database():
    service = CommunicationClientService.__new__(CommunicationClientService)
    service.authority = SimpleNamespace(_communication_events_enabled=False)
    with pytest.raises(CommunicationHttpError) as disabled:
        service.snapshot(PROJECT)
    assert disabled.value.code == "capability_unsupported" and disabled.value.status_code == 409
    service.authority._communication_events_enabled = True
    for limit in (0, 101, True):
        with pytest.raises(InvalidToolArgument):
            service.snapshot(PROJECT, limit=limit)


def test_snapshot_schema_and_three_frozen_families_page_without_body_or_effects(snapshots):
    f, own = snapshots, client(snapshots)
    send(f, "a", "b", "PRIVATE_SNAPSHOT_MESSAGE_ONE", activation="message_only")
    send(f, "c", "a", "PRIVATE_SNAPSHOT_MESSAGE_TWO", activation="message_only")
    publish(f)
    with psycopg.connect(f.dsn) as connection:
        before = connection.execute("SELECT packet_json FROM delivery_messages ORDER BY message_id").fetchall()
    captured = own.snapshot(PROJECT, limit=1)
    CONTRACTS.validate("Snapshot", captured)
    assert captured["snapshot_id"].startswith("snapshot-")
    assert len(captured["contacts"]) == len(captured["conversations"]) == len(captured["receivers"]) == 1
    assert captured["auth_revision"] == captured["actor"]["auth_revision"]
    full = {family: all_frozen(own, captured, family) for family in ("contacts", "conversations", "receivers")}
    assert len(full["contacts"]) == len(full["receivers"]) == 3 and len(full["conversations"]) == 2
    assert "PRIVATE_SNAPSHOT_MESSAGE" not in str(captured) + str(full)
    with psycopg.connect(f.dsn) as connection:
        assert connection.execute("SELECT packet_json FROM delivery_messages ORDER BY message_id").fetchall() == before
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone()[0] == 0
    assert all(not driver.calls for driver in f.drivers.values())


def test_later_messages_replies_contact_names_and_personal_preferences_do_not_mix_into_cut(snapshots):
    f, own = snapshots, client(snapshots)
    call(f, "a", "configure_team", prepare_native=False,
         members=[{"agent_slot_id": "snapshot-name-peer", "principal_ref": "agent:snapshot-name-peer",
                   "display_name": "Name before the cut"}])
    first = send(f, "a", "b", "Before snapshot pair one", activation="message_only")["data"]
    send(f, "c", "a", "Before snapshot pair two", activation="message_only")
    captured = own.snapshot(PROJECT, limit=1)
    frozen = {family: all_frozen(own, captured, family) for family in ("contacts", "conversations", "receivers")}
    view_b = next(item["conversation_id"] for item in frozen["conversations"] if ADDRESSES["b"] in item["participants"])
    send(f, "b", "a", "Later explicit reply", activation="message_only", reply_to=[first["message_handle"]])
    send(f, "a", "c", "Later pair activity", activation="message_only")
    call(f, "a", "configure_team", prepare_native=False,
         members=[{"agent_slot_id": "snapshot-name-peer", "display_name": "Name after the cut"}])
    own.update_preferences(PROJECT, view_b, {"muted": True, "archived": True}, expected_revision=0, client_request_id="snapshot-later-prefs")
    for family, value in frozen.items():
        assert all_frozen(own, captured, family) == value
    assert any(item["display_name"] == "Name after the cut" for item in own.contacts(PROJECT)["items"])
    assert own.conversation(PROJECT, view_b)["muted"] is True


def test_real_rr_cut_keeps_source_state_and_event_boundary_from_one_view(snapshots, monkeypatch):
    f, own = snapshots, client(snapshots)
    incoming = send(f, "b", "a", "Unread before RR cut", activation="message_only")["data"]
    view = own.resolve_conversation(PROJECT, peer=ADDRESSES["b"])["conversation_id"]
    publish(f)
    selected = ClientStateIdentity(f.authority.tenant_id, PROJECT, own._viewer_actor_ref(PROJECT, ADDRESSES["a"]), view)
    original = CommunicationClientService.contacts
    interleaved, rr_cuts = [], []

    def during_cut(service, project, **kwargs):
        connection = getattr(service.authority, "_transaction_connection", None)
        result = original(service, project, **kwargs)
        if connection is not None and connection.execute("SHOW transaction_isolation").fetchone()[0] == "repeatable read":
            rr_cuts.append(True)
            assert service.project_service.service.authority is service.authority
            if not interleaved:
                with psycopg.connect(f.dsn) as writer:
                    write_read_state(writer.cursor(), selected, through_message_handle=incoming["message_handle"], through_sequence=1,
                                     expected_revision=0, client_request_id="during-real-rr-cut")
                interleaved.append(True)
        return result

    monkeypatch.setattr(CommunicationClientService, "contacts", during_cut)
    captured = own.snapshot(PROJECT)
    assert interleaved == [True]
    # The first cut cannot lock the projection counter changed after its RR
    # view began. Serialization retries capture a complete new view, rather
    # than combining the old unread value with a new projection revision.
    assert rr_cuts == [True, True]
    actual = own.conversation(PROJECT, view)
    assert captured["conversations"][0] == actual
    assert actual["unread_count"] == 0
    publish(f)
    replay = own.event_batch(PROJECT, after_cursor=captured["after_cursor"])
    assert any(event["kind"] == "read_state.changed" and event["resource_ref"] == view for event in replay.events)
    assert any(event["kind"] == "conversation.updated" and event["resource_ref"] == view
               and event["resource_revision"] == actual["revision"] for event in replay.events)


def test_provider_reads_are_outside_pg_and_limited_to_one_page_and_cache_never_reprobes(snapshots, monkeypatch):
    f, own, probes = snapshots, client(snapshots), []
    f.authority._receiver_evidence_enabled = True
    for endpoint in f.authority._delivery_endpoints.values():
        def observe(binding):
            with psycopg.connect(f.dsn) as writer:
                writer.execute("SELECT grant_ref FROM grants WHERE grant_ref=%s FOR UPDATE NOWAIT", (f.authority.context.grant_ref,))
                writer.execute("SELECT endpoint_id FROM delivery_endpoints WHERE endpoint_id=%s FOR UPDATE NOWAIT", (binding.receiver_id,))
            probes.append(binding.receiver_id)
            return measured(binding)
        monkeypatch.setattr(endpoint, "receiver_snapshot", observe)
    captured = own.snapshot(PROJECT, limit=1)
    assert probes == ["endpoint-a"]
    assert all(item["knowledge"] == "observed" for item in captured["receivers"][0]["observations"])
    for endpoint in f.authority._delivery_endpoints.values():
        monkeypatch.setattr(endpoint, "receiver_snapshot", lambda _binding: pytest.fail("frozen page reprobed provider"))
    receivers = all_frozen(own, captured, "receivers")
    assert len(receivers) == 3
    assert all(receiver["revision"] == 0 and receiver["native_session_ref"] is None for receiver in receivers[1:])
    assert all(item["knowledge"] == "unknown" and item["value"] is None
               for receiver in receivers[1:] for item in receiver["observations"])
    assert all(item["support"] == item["availability"] == "unknown"
               for receiver in receivers[1:] for item in receiver["capabilities"])
    assert probes == ["endpoint-a"]


def test_receiver_evidence_expired_at_cut_is_unknown(snapshots, monkeypatch):
    f, own = snapshots, client(snapshots)
    f.authority._receiver_evidence_enabled = True
    clock = [datetime.now(UTC)]
    monkeypatch.setattr(f.authority, "canonical_now", lambda cursor=None: clock[0])
    monkeypatch.setattr(f.authority._delivery_endpoints["endpoint-a"], "receiver_snapshot", lambda binding: measured(binding, now=clock[0], ttl_seconds=4))
    original = CommunicationClientService._snapshot_facade

    def advance(service, bound):
        clock[0] += timedelta(seconds=3)
        return original(service, bound)

    monkeypatch.setattr(CommunicationClientService, "_snapshot_facade", advance)
    captured = own.snapshot(PROJECT, limit=1)
    assert all(item["knowledge"] == "unknown" and item["value"] is None for item in captured["receivers"][0]["observations"])


def test_cached_receiver_axes_remain_at_cut_after_later_ttl_and_rebind_invalidates(snapshots, monkeypatch):
    f, own = snapshots, client(snapshots)
    f.authority._receiver_evidence_enabled = True
    clock = [datetime.now(UTC)]
    monkeypatch.setattr(f.authority, "canonical_now", lambda cursor=None: clock[0])
    endpoint = f.authority._delivery_endpoints["endpoint-a"]
    monkeypatch.setattr(endpoint, "receiver_snapshot", lambda binding: measured(binding, now=clock[0], ttl_seconds=4))
    captured = own.snapshot(PROJECT, limit=1)
    frozen = captured["receivers"][0]
    assert all(item["knowledge"] == "observed" for item in frozen["observations"])
    clock[0] += timedelta(seconds=10)
    monkeypatch.setattr(endpoint, "receiver_snapshot", lambda _binding: pytest.fail("cache refreshed Native axes"))
    assert own.receivers(PROJECT, snapshot_id=captured["snapshot_id"], limit=1)["items"] == [frozen]
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE delivery_endpoints SET revision=revision+1 WHERE endpoint_id='endpoint-a'")
    with pytest.raises(CommunicationHttpError) as invalid:
        own.receivers(PROJECT, snapshot_id=captured["snapshot_id"], limit=1)
    assert invalid.value.code == "snapshot_invalid" and invalid.value.status_code == 409


def test_current_contact_visibility_and_filter_bindings_reject_cached_pages(snapshots):
    f, own = snapshots, client(snapshots)
    captured = own.snapshot(PROJECT)
    with pytest.raises(CommunicationHttpError) as filtered:
        own.contacts(PROJECT, snapshot_id=captured["snapshot_id"], name="different")
    assert filtered.value.code == "snapshot_invalid"
    with psycopg.connect(f.dsn) as connection:
        connection.execute("DELETE FROM collaboration_memberships WHERE tenant_id=%s AND project_id=%s AND agent_slot_id='slot-c'", (f.authority.tenant_id, PROJECT))
    with pytest.raises(CommunicationHttpError) as missing:
        own.contacts(PROJECT, snapshot_id=captured["snapshot_id"])
    assert missing.value.code == "snapshot_invalid"


@pytest.mark.parametrize("change", ["grant", "scope"])
def test_live_revocation_prevents_cached_payload_disclosure(snapshots, change):
    f, own = snapshots, client(snapshots)
    captured = own.snapshot(PROJECT)
    with psycopg.connect(f.dsn) as connection:
        if change == "grant":
            connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (own.project_service.context.grant_ref,))
        else:
            connection.execute("UPDATE scopes SET status='revoked' WHERE scope_id='local-scope'")
    with pytest.raises((AuthorizationDenied, PermissionError)):
        own.contacts(PROJECT, snapshot_id=captured["snapshot_id"])


def test_same_principal_slots_cannot_reuse_each_others_snapshot(snapshots):
    f = snapshots
    shared_principal_clients(f)
    flags(f)
    first, second = client(f, "shared-1"), client(f, "shared-2")
    captured = first.snapshot(PROJECT, limit=1)
    with pytest.raises(CommunicationHttpError) as wrong_actor:
        second.contacts(PROJECT, snapshot_id=captured["snapshot_id"])
    assert wrong_actor.value.code == "snapshot_invalid" and wrong_actor.value.status_code == 409


def test_actual_oauth_scope_change_and_grant_scope_change_invalidate_cache_binding(snapshots, monkeypatch):
    f, issuer = snapshots, IssuerFixture({"snapshot-token": claims()})
    cfg = settings(monkeypatch, f.authority.context).model_copy(update={"authorization_refresh_seconds": 5})

    async def exercise():
        async with issuer.client() as issuer_client:
            verifier = IntrospectionVerifier(cfg, issuer_client)
            access = await verifier.verify_token("snapshot-token")
            context = replace(f.authority.context, credential_hash=hashlib.sha256(b"snapshot-token").hexdigest())
            authority = DomainAuthority(f.dsn, context=context)
            authority._communication_events_enabled = True
            authorization = TokenAuthorization(access, context, verifier)
            projects = OAuthProjectService(SharedService(authority, authorization), CATALOG, profile="root_manager", token_authorization=authorization)
            own = CommunicationClientService(projects, "snapshot-token")
            captured = await _run_with_refresh(authorization, own.snapshot, PROJECT, limit=1)
            issuer.tokens["snapshot-token"] = claims(scope=" ".join(scope for scope in access.scopes if scope != "runtime.read"))
            authorization.checked_at -= 6
            await authorization.refresh()
            with pytest.raises(CommunicationHttpError) as changed:
                await _run_with_refresh(authorization, own.contacts, PROJECT, snapshot_id=captured["snapshot_id"])
            assert changed.value.code == "snapshot_invalid"

    asyncio.run(exercise())
    own = client(f)
    captured = own.snapshot(PROJECT)
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE grants SET permissions=permissions-'runtime.read' WHERE grant_ref=%s", (own.project_service.context.grant_ref,))
    with pytest.raises(CommunicationHttpError) as changed:
        own.contacts(PROJECT, snapshot_id=captured["snapshot_id"])
    assert changed.value.code == "snapshot_invalid"


def test_snapshot_quota_rejects_complete_capture_without_partial_cache(snapshots):
    f, own = snapshots, client(snapshots)
    f.authority._communication_snapshot_limits = SnapshotLimits(max_items=1)
    with pytest.raises(CommunicationHttpError) as rejected:
        own.snapshot(PROJECT)
    assert rejected.value.code == "snapshot_quota_exceeded" and rejected.value.status_code == 429
    assert cache_count(f) == 0


def test_http_snapshot_schema_frozen_paging_and_expiry_410(snapshots, monkeypatch):
    f = snapshots
    cfg = config(monkeypatch, f, enabled=True).model_copy(update={"communication_event_stream": True})
    original = snapshot_module.save_snapshot

    def short_lived(*args, **kwargs):
        return original(*args, **kwargs, ttl_seconds=2)

    monkeypatch.setattr(snapshot_module, "save_snapshot", short_lived)

    async def exercise():
        async with IssuerFixture({"valid": claims()}).client() as issuer_client:
            app = app_for(f, cfg, issuer_client)
            explicit_initialize(f)
            async with (app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer valid"}) as http):
                response = await http.get(PREFIX + f"/projects/{PROJECT}/snapshot?limit=1")
                assert response.status_code == 200, response.text
                captured = CONTRACTS.validate("Snapshot", response.json())
                page = await http.get(PREFIX + f"/projects/{PROJECT}/contacts", params={"snapshot_id": captured["snapshot_id"],
                    "cursor": captured["pages"]["contacts_cursor"], "limit": 1})
                assert page.status_code == 200, page.text
                CONTRACTS.validate("ContactPage", page.json())
                await asyncio.sleep(2.1)
                expired = await http.get(PREFIX + f"/projects/{PROJECT}/contacts", params={"snapshot_id": captured["snapshot_id"]})
                assert expired.status_code == 410 and expired.json()["error"]["code"] == "snapshot_expired"
    asyncio.run(exercise())


def test_http_snapshot_quota_429_has_no_partial_cache(snapshots, monkeypatch):
    f = snapshots
    f.authority._communication_snapshot_limits = SnapshotLimits(max_items=1)
    cfg = config(monkeypatch, f, enabled=True).model_copy(update={"communication_event_stream": True})

    async def exercise():
        async with IssuerFixture({"valid": claims()}).client() as issuer_client:
            app = app_for(f, cfg, issuer_client)
            explicit_initialize(f)
            async with (app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer valid"}) as http):
                response = await http.get(PREFIX + f"/projects/{PROJECT}/snapshot")
                assert response.status_code == 429, response.text
                assert response.json()["error"]["code"] == "snapshot_quota_exceeded"
                assert response.headers["retry-after"] == "5"
    asyncio.run(exercise())
    assert cache_count(f) == 0
