"""Actual PG event intents/replay with current Core authorization and viewers.

Native ACKs and issuer introspection are named fixtures. Event reads must remain
pure metadata observations and do not qualify public ingress or a real Harness.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from runtime.client_contracts import ClientContracts
from runtime.communication_client_events import encode_event_cursor
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_client_storage import adopt_client_storage
from runtime.communication_client_viewer_storage import adopt_viewer_storage
from runtime.communication_event_storage import (
    adopt_event_storage,
    publish_event_intents,
    purge_event_records,
)
from runtime.communication_http import CommunicationHttpError, _run_with_refresh
from runtime.domain import DomainAuthority
from runtime.errors import AuthorizationDenied
from runtime.project_common import digest
from runtime.project_http import IntrospectionVerifier, OAuthProjectService, TokenAuthorization
from runtime.project_service import ProjectService
from runtime.surfaces import SharedService
from runtime_tests.test_communication import CATALOG, send
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_identity_root_management import accepted, actor
from runtime_tests.test_identity_root_management import owner_client as owner_client_fixture
from runtime_tests.test_project_http import IssuerFixture, claims, settings

comm = comm_fixture
owner_client = owner_client_fixture
PROJECT = "project-alpha"
PEER_B = "collaborator:project-alpha:slot-b"
PEER_C = "collaborator:project-alpha:slot-c"
CONTRACTS = ClientContracts()


@pytest.fixture
def evented(comm):
    with comm.authority._connect() as connection:
        adopt_client_storage(connection)
        adopt_viewer_storage(connection)
        adopt_event_storage(connection)
    return comm


def client(f, name="a"):
    source = f.clients[name]
    return CommunicationClientService(source.service, source.credential_provider())


def anchor(service, *, project=PROJECT, position=0):
    return service._event_transaction(project, lambda bound, cursor, _root, _command, revision:
        encode_event_cursor(cursor, bound.tenant_id, project, revision, position, anchor=True))


def position(service, token, *, kinds=None):
    selected = service._event_kinds(kinds)
    return service._event_transaction(PROJECT, lambda _bound, cursor, _root, _command, revision:
        service._decode_event_cursor(cursor, PROJECT, token, revision, selected))


def publish(f):
    total = 0
    with f.authority._connect() as connection:
        while batch := publish_event_intents(connection, f.authority.tenant_id, PROJECT, limit=1000):
            total += batch
    return total


def state(f):
    tables = ("operations", "outbox", "delivery_messages", "delivery_receipts", "communication_messages", "communication_replies",
        "communication_client_read_state", "communication_client_drafts", "communication_client_preferences",
        "communication_event_intents", "communication_event_stream", "communication_event_clocks")
    with f.authority._connect() as connection:
        return {table: connection.execute("SELECT md5(COALESCE(string_agg(to_jsonb(t)::text,',' ORDER BY to_jsonb(t)::text),'')) FROM "
                                          + table + " t").fetchone()[0] for table in tables}


def assert_events(events):
    for event in events:
        CONTRACTS.validate("Event", event)
        assert "sequence" not in event and "published_at" not in event
        assert set(event["payload"]) <= {"reason_code", "message_handle", "conversation_id", "operation_ref", "reset_required"}
        assert not {"content", "body", "draft", "transcript", "actor_ref", "sender", "recipient"}.intersection(event["payload"])


def test_actual_message_reply_and_delivery_changes_replay_as_stable_metadata_without_effects(evented, monkeypatch):
    f, own = evented, client(evented)
    start = anchor(own)
    original = send(f, content="MESSAGE_BODY_MUST_NEVER_BE_IN_EVENT", activation="invoke")["data"]
    assert f.dispatcher.dispatch({"tenant_id": f.authority.tenant_id, "message_id": original["message_id"],
                                 "operation_id": original["operation_id"]})["status"] == "delivered"
    reply = send(f, "b", "a", "REPLY_BODY_MUST_NEVER_BE_IN_EVENT", activation="message_only",
                 reply_to=[original["message_handle"]])["data"]
    assert publish(f) > 0
    before, native = state(f), len(f.drivers["b"].calls)
    for endpoint in f.authority._delivery_endpoints.values():
        monkeypatch.setattr(endpoint, "receiver_snapshot", lambda _binding: pytest.fail("event replay probed Native evidence"))
        monkeypatch.setattr(endpoint, "inspect_runtime", lambda: pytest.fail("event replay inspected Native runtime"))
        monkeypatch.setattr(endpoint, "prepare_runtime", lambda: pytest.fail("event replay prepared Native runtime"))
    first = own.event_batch(PROJECT, after_cursor=start)
    duplicate = own.event_batch(PROJECT, after_cursor=start)
    assert_events(first.events)
    assert {event["kind"] for event in first.events} >= {"message.committed", "reply.linked", "delivery.changed"}
    assert {event["resource_ref"] for event in first.events if event["kind"] == "message.committed"} == {
        original["message_handle"], reply["message_handle"]}
    linked = next(event for event in first.events if event["kind"] == "reply.linked")
    assert linked["resource_ref"] == original["message_handle"] and linked["resource_revision"] == 2
    assert any(event["payload"].get("operation_ref") == original["operation_id"] for event in first.events)
    assert [event["event_id"] for event in first.events] == [event["event_id"] for event in duplicate.events]
    assert [{key: value for key, value in event.items() if key != "cursor"} for event in first.events] == [
        {key: value for key, value in event.items() if key != "cursor"} for event in duplicate.events]
    assert own.event_current(PROJECT, expected_auth_revision=first.auth_revision)["auth_revision"] == first.auth_revision
    assert own.event_batch(PROJECT, after_cursor=first.after_cursor).events == ()
    assert "BODY_MUST_NEVER_BE_IN_EVENT" not in json.dumps(first.events)
    assert state(f) == before and len(f.drivers["b"].calls) == native == 1
    assert publish(f) == 0


def test_root_manager_cannot_observe_b_c_message_or_another_viewers_private_state(evented):
    f, manager, b, c = evented, client(evented), client(evented, "b"), client(evented, "c")
    cursors = {name: anchor(service) for name, service in (("manager", manager), ("b", b), ("c", c))}
    request = send(f, "b", "c", "B_C_PRIVATE_MESSAGE_TEXT", activation="message_only")["data"]
    view = b.resolve_conversation(PROJECT, peer=PEER_C)["conversation_id"]
    b.update_draft(PROJECT, view, {"content": "B_UNSENT_PRIVATE_DRAFT_TEXT", "attachment_refs": []},
                   expected_revision=0, client_request_id="b-private-event")
    c.update_read_state(PROJECT, view, {"through_message_handle": request["message_handle"]},
                        expected_revision=0, client_request_id="c-private-read-event")
    assert publish(f) > 0
    before = state(f)
    manager_batch = manager.event_batch(PROJECT, after_cursor=cursors["manager"])
    b_batch = b.event_batch(PROJECT, after_cursor=cursors["b"])
    c_batch = c.event_batch(PROJECT, after_cursor=cursors["c"])
    assert manager_batch.events == ()
    assert position(manager, manager_batch.after_cursor) > position(manager, cursors["manager"])
    assert {event["kind"] for event in b_batch.events} >= {"message.committed", "draft.changed"}
    assert "read_state.changed" not in {event["kind"] for event in b_batch.events}
    assert {event["kind"] for event in c_batch.events} >= {"message.committed", "read_state.changed"}
    assert "draft.changed" not in {event["kind"] for event in c_batch.events}
    assert_events((*b_batch.events, *c_batch.events))
    assert "PRIVATE_MESSAGE_TEXT" not in json.dumps((*b_batch.events, *c_batch.events))
    assert "PRIVATE_DRAFT_TEXT" not in json.dumps((*b_batch.events, *c_batch.events))
    with f.authority._connect() as connection:
        actual = connection.execute("SELECT actor_ref FROM communication_client_drafts").fetchone()[0]
    assert actual == b.event_current(PROJECT)["viewer_key"] and actual != b.project_service.context.principal_ref
    assert state(f) == before and not any(driver.calls for driver in f.drivers.values())


def test_same_principal_slots_have_distinct_actual_viewer_events_and_cursors(evented, owner_client):
    f = evented
    bindings = accepted(owner_client, "configure_team", project_id=PROJECT, client_request_id="event-viewer-slots",
        prepare_native=False, members=[{"agent_slot_id": slot, "principal_ref": "agent:event-shared", "role": "engineer"}
                                      for slot in ("event-slot-one", "event-slot-two")])["caller_bindings"]
    peers = []
    for binding in bindings:
        context = replace(f.authority.context, principal_ref=binding["principal_ref"], grant_ref=binding["grant_ref"],
                          agent_slot_id=binding["agent_slot_id"], trusted_client=False)
        source = actor(f, context, "engineer", f.clients["a"].credential_provider())
        peers.append(CommunicationClientService(source.service, source.credential_provider()))
    first, second = peers
    before = [anchor(peer) for peer in peers]
    first_view = first.resolve_conversation(PROJECT, peer=PEER_B)["conversation_id"]
    second_view = second.resolve_conversation(PROJECT, peer=PEER_B)["conversation_id"]
    first.update_draft(PROJECT, first_view, {"content": "ONLY_FIRST_SLOT_DRAFT", "attachment_refs": []},
                       expected_revision=0, client_request_id="same-client-key")
    second.update_draft(PROJECT, second_view, {"content": "ONLY_SECOND_SLOT_DRAFT", "attachment_refs": []},
                        expected_revision=0, client_request_id="same-client-key")
    assert publish(f) == 2
    one = first.event_batch(PROJECT, after_cursor=before[0])
    two = second.event_batch(PROJECT, after_cursor=before[1])
    assert [event["resource_ref"] for event in one.events] == [first_view]
    assert [event["resource_ref"] for event in two.events] == [second_view]
    assert first.event_current(PROJECT)["viewer_key"] != second.event_current(PROJECT)["viewer_key"]
    assert first.project_service.context.principal_ref == second.project_service.context.principal_ref
    with pytest.raises(CommunicationHttpError) as error:
        second.event_batch(PROJECT, after_cursor=before[0])
    assert error.value.code == "cursor_invalid"
    assert "ONLY_" not in json.dumps((*one.events, *two.events))


def test_snapshot_anchor_accepts_a_subset_but_issued_stream_cursor_is_exact_filter_bound(evented):
    f, own = evented, client(evented)
    start = anchor(own)
    send(f, activation="message_only")
    publish(f)
    batch = own.event_batch(PROJECT, after_cursor=start, kinds=["message.committed"])
    assert batch.events and {event["kind"] for event in batch.events} == {"message.committed"}
    assert own.event_batch(PROJECT, after_cursor=batch.after_cursor, kinds=["message.committed"]).events == ()
    for kinds in (None, ["delivery.changed"], ["message.committed", "delivery.changed"]):
        with pytest.raises(CommunicationHttpError) as error:
            own.event_batch(PROJECT, after_cursor=batch.after_cursor, kinds=kinds)
        assert error.value.code == "cursor_invalid"


def test_filtered_and_foreign_scans_advance_only_the_opaque_internal_replay_cursor(evented):
    f, own = evented, client(evented)
    start = anchor(own)
    send(f, "b", "c", "UNSEEN_FOREIGN_MESSAGE", activation="message_only")
    send(f, content="OWN_VISIBLE_MESSAGE", activation="message_only")
    publish(f)
    first = own.event_batch(PROJECT, after_cursor=start, kinds=["message.committed"], limit=1)
    assert first.events == () and first.has_more
    assert position(own, first.after_cursor, kinds=["message.committed"]) > 0
    cursor, visible = first.after_cursor, []
    for _attempt in range(20):
        batch = own.event_batch(PROJECT, after_cursor=cursor, kinds=["message.committed"], limit=1)
        cursor = batch.after_cursor
        visible.extend(batch.events)
        if not batch.has_more:
            break
    else:
        pytest.fail("bounded fixture replay failed to reach the stream boundary")
    assert len(visible) == 1
    assert_events(visible)
    assert "sequence" not in json.dumps(visible) and "UNSEEN_FOREIGN_MESSAGE" not in json.dumps(visible)


@pytest.mark.parametrize("change", ["grant", "scope"])
def test_live_authority_changes_invalidate_replay_and_pre_emit_revision_guard(evented, change):
    f, own = evented, client(evented)
    current, start = own.event_current(PROJECT), anchor(own)
    with f.authority._connect() as connection:
        if change == "grant":
            connection.execute("UPDATE grants SET permissions=permissions-'runtime.read' WHERE grant_ref=%s", (f.authority.context.grant_ref,))
        else:
            connection.execute("UPDATE scopes SET policy=policy||'{\"event_fixture_version\":2}'::jsonb WHERE scope_id='local-scope'")
    assert own.event_current(PROJECT)["viewer_key"] == current["viewer_key"]
    with pytest.raises(CommunicationHttpError) as error:
        own.event_current(PROJECT, expected_auth_revision=current["auth_revision"])
    assert error.value.code == "permission_changed" and error.value.status_code == 409
    with pytest.raises(CommunicationHttpError) as error:
        own.event_batch(PROJECT, after_cursor=start)
    assert error.value.code == "cursor_invalid"


@pytest.mark.parametrize("when", ["before_batch", "after_batch_before_emit"])
def test_each_batch_and_event_current_emit_guard_recheck_revocation(evented, when):
    f, own = evented, client(evented)
    start = anchor(own)
    send(f, activation="message_only")
    publish(f)
    batch = own.event_batch(PROJECT, after_cursor=start) if when == "after_batch_before_emit" else None
    if batch is not None:
        assert batch.events
    with f.authority._connect() as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (f.authority.context.grant_ref,))
    with pytest.raises(AuthorizationDenied):
        if batch is None:
            own.event_batch(PROJECT, after_cursor=start)
        else:
            own.event_current(PROJECT, expected_auth_revision=batch.auth_revision)


@pytest.mark.parametrize("change", ["actor", "project", "key"])
def test_event_cursor_never_crosses_actor_project_or_persistent_key(evented, owner_client, change):
    f, own = evented, client(evented)
    start = anchor(own)
    target, project = own, PROJECT
    if change == "actor":
        target = client(f, "b")
    elif change == "project":
        project = "project-event-other"
        # The same actual trusted Client can access both independent Root
        # namespaces. Each new Root gets its own authoritative Scope.
        target = CommunicationClientService(owner_client.service, owner_client.credential_provider())
        start = anchor(target)
        accepted(owner_client, "configure_root", project_id=project, client_request_id="event-other-project",
                 changes={"name": "Other isolated event project"}, prepare_native=False)
    else:
        with f.authority._connect() as connection:
            connection.execute("UPDATE communication_client_cursor_key SET secret=%s", (b"k" * 32,))
    with pytest.raises(CommunicationHttpError) as error:
        target.event_batch(project, after_cursor=start)
    assert error.value.code == ("cursor_expired" if change == "key" else "cursor_invalid")
    assert error.value.status_code == (410 if change == "key" else 409)


def test_retention_floor_returns_410_and_requires_a_new_snapshot_anchor(evented):
    f, own = evented, client(evented)
    start = anchor(own)
    send(f, activation="message_only")
    publish(f)
    with f.authority._connect() as connection:
        removed, floor = purge_event_records(connection, f.authority.tenant_id, PROJECT, before=datetime.now(UTC) + timedelta(minutes=1))
    assert removed > 0 and floor > 0
    with pytest.raises(CommunicationHttpError) as error:
        own.event_batch(PROJECT, after_cursor=start)
    assert error.value.code == "cursor_expired" and error.value.status_code == 410
    assert own.event_batch(PROJECT, after_cursor=anchor(own, position=floor)).events == ()


def test_actual_oauth_scope_refresh_changes_event_authorization_without_identity_guessing(evented, monkeypatch):
    f = evented
    cfg = settings(monkeypatch, f.authority.context)
    issuer = IssuerFixture({"event-token": claims()})

    async def exercise():
        async with issuer.client() as issuer_client:
            verifier = IntrospectionVerifier(cfg, issuer_client)
            access = await verifier.verify_token("event-token")
            context = replace(f.authority.context, credential_hash=hashlib.sha256(b"event-token").hexdigest())
            authority = DomainAuthority(f.dsn, context=context)
            authorization = TokenAuthorization(access, context, verifier)
            projects = OAuthProjectService(SharedService(authority, authorization), CATALOG, profile="root_manager",
                                           token_authorization=authorization)
            own = CommunicationClientService(projects, "event-token")
            current = await _run_with_refresh(authorization, own.event_current, PROJECT)
            start = await _run_with_refresh(authorization, anchor, own)
            issuer.tokens["event-token"] = claims(scope=" ".join(scope for scope in access.scopes if scope != "runtime.read"))
            authorization.checked_at -= 2
            await authorization.refresh()
            refreshed = await _run_with_refresh(authorization, own.event_current, PROJECT)
            assert refreshed["viewer_key"] == current["viewer_key"]
            with pytest.raises(CommunicationHttpError) as error:
                await _run_with_refresh(authorization, own.event_current, PROJECT, expected_auth_revision=current["auth_revision"])
            assert error.value.code == "permission_changed"
            with pytest.raises(CommunicationHttpError) as error:
                await _run_with_refresh(authorization, own.event_batch, PROJECT, after_cursor=start)
            assert error.value.code == "cursor_invalid"

    asyncio.run(exercise())


def test_event_auth_revision_includes_a_real_secondary_family_selected_route_grant(evented):
    f = evented
    scope, grant = "event-harness-scope", "grant:event-harness"
    with f.authority._connect() as connection:
        connection.execute("INSERT INTO scopes VALUES (%s,%s,'{}','active')", (scope, f.authority.tenant_id))
        connection.execute("INSERT INTO collaboration_routes(tenant_id,project_id,route_id,scope_id,definition) VALUES (%s,%s,%s,%s,'{}')",
                           (f.authority.tenant_id, PROJECT, scope, scope))
        connection.execute("INSERT INTO agent_slots VALUES ('event-harness-slot',%s,%s,'active')", (f.authority.tenant_id, scope))
        connection.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,scope_id,permissions,expires_at) "
            "SELECT %s,tenant_id,principal_ref,authority_id,authority_incarnation,%s,permissions,expires_at FROM grants WHERE grant_ref=%s",
            (grant, scope, f.authority.context.grant_ref))
        policy = connection.execute("SELECT policy FROM scopes WHERE scope_id='local-scope'").fetchone()[0]
        connection.execute("INSERT INTO grant_delegations(grant_ref,parent_grant_ref,tenant_id,command_id,parent_policy_digest) VALUES (%s,%s,%s,'event-fixture-route',%s)",
                           (grant, f.authority.context.grant_ref, f.authority.tenant_id, digest(policy)))
        connection.execute("INSERT INTO collaboration_route_grants VALUES (%s,%s,%s,%s,'root_manager',%s,'event-harness-slot')",
                           (f.authority.tenant_id, PROJECT, scope, f.authority.context.principal_ref, grant))

    class ServerSelectedHarnessRoute(ProjectService):
        # Explicit server-owned fixture selection. The original Core method
        # validates the real registered mapping, lineage and scoped permissions.
        def _authorize(self, authority, cursor, project_id, name, args):
            if name == "list_harnesses":
                args = {**args, "scope_handle": "scope:" + PROJECT + ":" + scope}
            return super()._authorize(authority, cursor, project_id, name, args)

    original = f.clients["a"]
    projects = ServerSelectedHarnessRoute(original.service.service, original.service.catalog, profile="root_manager")
    own = CommunicationClientService(projects, original.credential_provider())

    def first_family_hash():
        return own._transaction(PROJECT, "list_messages", lambda bound, cursor, _root, _command: own._cursor_binding(bound, cursor, PROJECT))

    initial_first = first_family_hash()
    initial, start = own.event_current(PROJECT), anchor(own)
    with f.authority._connect() as connection:
        connection.execute("UPDATE grants SET permissions=permissions-'runtime.invoke' WHERE grant_ref=%s", (grant,))
    assert first_family_hash() == initial_first
    assert own.event_current(PROJECT)["auth_revision"] != initial["auth_revision"]
    with pytest.raises(CommunicationHttpError) as error:
        own.event_batch(PROJECT, after_cursor=start)
    assert error.value.code == "cursor_invalid"


def test_same_bound_families_share_digest_only_within_one_current_authorization_pass(evented, monkeypatch):
    f, own = evented, client(evented)
    reads, authorized = [], []
    original_binding = own._cursor_binding
    original_authorize = own.project_service._authorize

    def binding(bound, cursor, project):
        reads.append(bound.context.grant_ref)
        return original_binding(bound, cursor, project)

    def authorize(authority, cursor, project, name, args):
        authorized.append(name)
        return original_authorize(authority, cursor, project, name, args)

    monkeypatch.setattr(own, "_cursor_binding", binding)
    monkeypatch.setattr(own.project_service, "_authorize", authorize)
    initial = own.event_current(PROJECT)
    # There is still a fresh pass before and after the callback, and every
    # family performs actual authorization in each pass. Only the identical
    # private digest query is shared within a pass, not permission or results.
    assert len(reads) == 2
    for name in ("list_messages", "read_message", "list_harnesses", "check_inbox", "list_collaborators"):
        assert authorized.count(name) == 2
    with f.authority._connect() as connection:
        connection.execute("UPDATE grants SET permissions=permissions-'runtime.read' WHERE grant_ref=%s", (f.authority.context.grant_ref,))
    updated = own.event_current(PROJECT)
    assert updated["auth_revision"] != initial["auth_revision"]
    assert len(reads) == 4  # No digest survives into another transaction/pass.
