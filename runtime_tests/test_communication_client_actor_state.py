"""Two actual Slots sharing one principal keep distinct private viewer state.

Legacy principal rows require an explicit operator ownership decision. Tests use
real configured callers and PostgreSQL; migration helpers receive a trusted
operator cursor and are never exposed as a public client action.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import replace
from types import SimpleNamespace

import psycopg
import pytest

from runtime.auth import LocalCredentialAuthenticator
from runtime.communication_client_queries import conversation_view_id
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_client_storage import (
    ClientStateIdentity,
    adopt_client_storage,
    write_draft,
    write_preferences,
    write_read_state,
)
from runtime.communication_client_viewer_storage import (
    adopt_legacy_personal_state,
    adopt_viewer_storage,
)
from runtime.domain import DomainAuthority
from runtime.errors import SchemaAdoptionError
from runtime.project_service import ProjectService
from runtime.surfaces import SharedService
from runtime_tests.test_communication import CATALOG, call
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_notification_continuity import shared_principal_clients

comm = comm_fixture
PROJECT = "project-alpha"
PRINCIPAL = "agent:shared"
ADDRESSES = {number: f"collaborator:{PROJECT}:shared-slot-{number}" for number in (1, 2)}
PERSONAL_TABLES = ("communication_client_read_state", "communication_client_preferences", "communication_client_drafts")


def facade(f, number):
    client = f.clients[f"shared-{number}"]
    return CommunicationClientService(client.service, client.credential_provider())


def scoped_identity(pair, number):
    service = facade(pair.f, number)
    return ClientStateIdentity(pair.f.authority.tenant_id, PROJECT,
        service._viewer_actor_ref(PROJECT, ADDRESSES[number]), pair.view)


@pytest.fixture
def pair(comm):
    with psycopg.connect(comm.dsn) as connection:
        adopt_client_storage(connection)
        adopt_viewer_storage(connection)
    shared_principal_clients(comm)
    sent = {}
    for source, target in ((1, 2), (2, 1)):
        sent[source] = call(comm, f"shared-{source}", "send_message", to=ADDRESSES[target],
            content=f"Actual shared-principal Slot {source} message", activation="message_only",
            client_request_id=uuid.uuid4().hex)["data"]
    view = conversation_view_id(comm.authority.tenant_id, PROJECT, ADDRESSES[1], ADDRESSES[2])
    assert view == conversation_view_id(comm.authority.tenant_id, PROJECT, ADDRESSES[2], ADDRESSES[1])
    return SimpleNamespace(f=comm, view=view, sent=sent)


def actor_rows(connection, pair, actor):
    return {table: connection.execute("SELECT to_jsonb(s) FROM " + table + " s WHERE tenant_id=%s AND project_id=%s "
        "AND actor_ref=%s AND conversation_id=%s", (pair.f.authority.tenant_id, PROJECT, actor, pair.view)).fetchall()
        for table in PERSONAL_TABLES}


def seed_legacy(pair):
    identity = ClientStateIdentity(pair.f.authority.tenant_id, PROJECT, PRINCIPAL, pair.view)
    with psycopg.connect(pair.f.dsn) as connection, connection.cursor() as cursor:
        write_read_state(cursor, identity, through_message_handle=pair.sent[2]["message_handle"], through_sequence=2,
                         expected_revision=0, client_request_id="legacy-read", unread_override=True)
        write_preferences(cursor, identity, {"archived": True}, expected_revision=0, client_request_id="legacy-prefs-1")
        write_preferences(cursor, identity, {"muted": True}, expected_revision=1, client_request_id="legacy-prefs-2")
        write_draft(cursor, identity, "Legacy draft before viewer scoping", [], expected_revision=0, client_request_id="legacy-draft-1")
        write_draft(cursor, identity, "Preserved legacy draft revision two", [], expected_revision=1, client_request_id="legacy-draft-2")
        states = actor_rows(connection, pair, PRINCIPAL)
        keys = connection.execute("SELECT to_jsonb(k) FROM communication_client_write_keys k WHERE tenant_id=%s AND actor_ref=%s ORDER BY client_request_id",
                                  (identity.tenant_id, PRINCIPAL)).fetchall()
    return states, keys


def test_same_principal_opposite_slots_isolate_read_preferences_drafts_and_raw_keys(pair):
    first, second = facade(pair.f, 1), facade(pair.f, 2)
    assert first.project_service.context.principal_ref == second.project_service.context.principal_ref == PRINCIPAL
    first_owner, second_owner = scoped_identity(pair, 1), scoped_identity(pair, 2)
    assert first_owner.actor_ref != second_owner.actor_ref
    for number, service in ((1, first), (2, second)):
        assert service.read_message(PROJECT, pair.sent[number]["message_handle"])["message"]["conversation_id"] == pair.view
        assert service.draft(PROJECT, pair.view)["revision"] == 0
        service.update_read_state(PROJECT, pair.view, {"through_message_handle": pair.sent[3 - number]["message_handle"]},
                                  expected_revision=0, client_request_id="same-raw-read-key")
        service.update_preferences(PROJECT, pair.view, {"muted": number == 1, "archived": number == 2},
                                   expected_revision=0, client_request_id="same-raw-pref-key")
        service.update_draft(PROJECT, pair.view, {"content": f"Private draft for Slot {number}", "attachment_refs": []},
                             expected_revision=0, client_request_id="same-raw-draft-key")
    assert first.read_state(PROJECT, pair.view)["through_message_handle"] == pair.sent[2]["message_handle"]
    assert second.read_state(PROJECT, pair.view)["through_message_handle"] == pair.sent[1]["message_handle"]
    assert first.preferences(PROJECT, pair.view) == {"muted": True, "archived": False, "revision": 1}
    assert second.preferences(PROJECT, pair.view) == {"muted": False, "archived": True, "revision": 1}
    assert first.draft(PROJECT, pair.view)["content"] == "Private draft for Slot 1"
    assert second.draft(PROJECT, pair.view)["content"] == "Private draft for Slot 2"
    with psycopg.connect(pair.f.dsn) as connection:
        for table in PERSONAL_TABLES:
            actors = connection.execute("SELECT actor_ref FROM " + table + " WHERE tenant_id=%s AND project_id=%s AND conversation_id=%s",
                                        (first_owner.tenant_id, PROJECT, pair.view)).fetchall()
            assert {row[0] for row in actors} == {first_owner.actor_ref, second_owner.actor_ref}


def test_same_viewer_new_device_credential_shares_state_and_exact_retry(pair):
    first = facade(pair.f, 1)
    saved = first.update_preferences(PROJECT, pair.view, {"muted": True}, expected_revision=0, client_request_id="original-device")
    token = "synthetic-second-device-" + uuid.uuid4().hex
    context = replace(first.project_service.context, credential_hash=hashlib.sha256(token.encode()).hexdigest())
    authority = DomainAuthority(pair.f.dsn, context=context)
    projects = ProjectService(SharedService(authority, LocalCredentialAuthenticator(context)), CATALOG, profile="engineer")
    second_device = CommunicationClientService(projects, token)
    assert second_device._viewer_actor_ref(PROJECT, ADDRESSES[1]) == first._viewer_actor_ref(PROJECT, ADDRESSES[1])
    assert second_device.preferences(PROJECT, pair.view) == saved
    latest = second_device.update_preferences(PROJECT, pair.view, {"archived": True}, expected_revision=1,
                                               client_request_id="second-device")
    assert first.preferences(PROJECT, pair.view) == latest
    assert second_device.update_preferences(PROJECT, pair.view, {"muted": True}, expected_revision=0,
                                             client_request_id="original-device") == saved
    assert facade(pair.f, 2).preferences(PROJECT, pair.view)["revision"] == 0


def test_private_view_updates_do_not_change_original_messages_consumption_or_replies(pair):
    with psycopg.connect(pair.f.dsn) as connection:
        packets = connection.execute("SELECT to_jsonb(m) FROM delivery_messages m ORDER BY m.message_id").fetchall()
        inbox = connection.execute("SELECT to_jsonb(i) FROM inbox_messages i ORDER BY to_jsonb(i)::text").fetchall()
        replies = connection.execute("SELECT to_jsonb(r) FROM communication_replies r").fetchall()
    for number in (1, 2):
        service = facade(pair.f, number)
        service.update_draft(PROJECT, pair.view, {"content": f"Unsent {number}", "attachment_refs": []},
                             expected_revision=0, client_request_id="private-only")
        service.update_read_state(PROJECT, pair.view, {"through_message_handle": pair.sent[3 - number]["message_handle"]},
                                  expected_revision=0, client_request_id="explicit-read")
    with psycopg.connect(pair.f.dsn) as connection:
        assert connection.execute("SELECT to_jsonb(m) FROM delivery_messages m ORDER BY m.message_id").fetchall() == packets
        assert connection.execute("SELECT to_jsonb(i) FROM inbox_messages i ORDER BY to_jsonb(i)::text").fetchall() == inbox
        assert connection.execute("SELECT to_jsonb(r) FROM communication_replies r").fetchall() == replies == []
    assert all(not driver.calls for driver in pair.f.drivers.values())


def test_ambiguous_legacy_principal_state_is_retained_and_private_views_refuse_before_choice(pair):
    states, keys = seed_legacy(pair)
    for number in (1, 2):
        service = facade(pair.f, number)
        for read in (service.read_state, service.preferences, service.draft):
            with pytest.raises(SchemaAdoptionError):
                read(PROJECT, pair.view)
        with pytest.raises(SchemaAdoptionError):
            service.update_draft(PROJECT, pair.view, {"content": "Must not hide existing legacy draft", "attachment_refs": []},
                                 expected_revision=0, client_request_id="before-decision")
    with psycopg.connect(pair.f.dsn) as connection:
        assert actor_rows(connection, pair, PRINCIPAL) == states
        assert connection.execute("SELECT to_jsonb(k) FROM communication_client_write_keys k WHERE tenant_id=%s AND actor_ref=%s ORDER BY client_request_id",
                                  (pair.f.authority.tenant_id, PRINCIPAL)).fetchall() == keys


def test_explicit_migration_chooses_one_viewer_preserves_rows_and_replay_does_not_overwrite(pair):
    states, keys = seed_legacy(pair)
    chosen = scoped_identity(pair, 1)
    with psycopg.connect(pair.f.dsn) as connection:
        adopt_legacy_personal_state(connection.cursor(), chosen, legacy_actor_ref=PRINCIPAL, decision_ref="operator-choice-slot-one")
        copied = actor_rows(connection, pair, chosen.actor_ref)
        for table in PERSONAL_TABLES:
            expected = {**states[table][0][0], "actor_ref": chosen.actor_ref}
            assert copied[table] == [(expected,)]
        assert actor_rows(connection, pair, PRINCIPAL) == states
    first, second = facade(pair.f, 1), facade(pair.f, 2)
    assert first.draft(PROJECT, pair.view)["content"] == "Preserved legacy draft revision two"
    assert first.preferences(PROJECT, pair.view) == {"muted": True, "archived": True, "revision": 2}
    assert first.read_state(PROJECT, pair.view)["unread_override"] is True
    assert second.draft(PROJECT, pair.view)["revision"] == second.preferences(PROJECT, pair.view)["revision"] == 0
    assert second.read_state(PROJECT, pair.view)["through_message_handle"] is None
    edited = first.update_draft(PROJECT, pair.view, {"content": "Edited after explicit migration", "attachment_refs": []},
                                expected_revision=2, client_request_id="after-migration")
    with psycopg.connect(pair.f.dsn) as connection:
        adopt_legacy_personal_state(connection.cursor(), chosen, legacy_actor_ref=PRINCIPAL, decision_ref="operator-choice-slot-one")
        assert actor_rows(connection, pair, PRINCIPAL) == states
        assert connection.execute("SELECT to_jsonb(k) FROM communication_client_write_keys k WHERE tenant_id=%s AND actor_ref=%s ORDER BY client_request_id",
                                  (pair.f.authority.tenant_id, PRINCIPAL)).fetchall() == keys
    assert first.draft(PROJECT, pair.view) == edited


def test_explicit_migration_rollback_is_atomic_and_keeps_views_blocked(pair):
    states, _keys = seed_legacy(pair)
    chosen = scoped_identity(pair, 1)
    with psycopg.connect(pair.f.dsn) as connection:
        adopt_legacy_personal_state(connection.cursor(), chosen, legacy_actor_ref=PRINCIPAL, decision_ref="rolled-back-choice")
        assert all(actor_rows(connection, pair, chosen.actor_ref).values())
        connection.rollback()
    with psycopg.connect(pair.f.dsn) as connection:
        assert actor_rows(connection, pair, PRINCIPAL) == states
        assert not any(actor_rows(connection, pair, chosen.actor_ref).values())
    for number in (1, 2):
        with pytest.raises(SchemaAdoptionError):
            facade(pair.f, number).draft(PROJECT, pair.view)
    with psycopg.connect(pair.f.dsn) as connection:
        adopt_legacy_personal_state(connection.cursor(), scoped_identity(pair, 2),
                                    legacy_actor_ref=PRINCIPAL, decision_ref="committed-choice-slot-two")
    assert facade(pair.f, 1).draft(PROJECT, pair.view)["revision"] == 0
    assert facade(pair.f, 2).draft(PROJECT, pair.view)["revision"] == 2


@pytest.mark.parametrize("number,decision", [(1, "different-ref"), (2, "original-ref"), (2, "different-ref")])
def test_recorded_migration_refuses_changed_choice_or_decision_ref(pair, number, decision):
    seed_legacy(pair)
    chosen = scoped_identity(pair, 1)
    with psycopg.connect(pair.f.dsn) as connection:
        adopt_legacy_personal_state(connection.cursor(), chosen, legacy_actor_ref=PRINCIPAL, decision_ref="original-ref")
    with pytest.raises(SchemaAdoptionError), psycopg.connect(pair.f.dsn) as connection:
        adopt_legacy_personal_state(connection.cursor(), scoped_identity(pair, number),
                                    legacy_actor_ref=PRINCIPAL, decision_ref=decision)
    assert facade(pair.f, 1).draft(PROJECT, pair.view)["revision"] == 2
    assert facade(pair.f, 2).draft(PROJECT, pair.view)["revision"] == 0


def test_existing_destination_conflict_rolls_back_copies_before_conflicting_resource(pair):
    chosen = scoped_identity(pair, 1)
    with psycopg.connect(pair.f.dsn) as connection:
        write_preferences(connection.cursor(), chosen, {"muted": False}, expected_revision=0,
                           client_request_id="already-scoped-state")
    states, _keys = seed_legacy(pair)
    with pytest.raises(SchemaAdoptionError), psycopg.connect(pair.f.dsn) as connection:
        adopt_legacy_personal_state(connection.cursor(), chosen, legacy_actor_ref=PRINCIPAL, decision_ref="conflicting-destination")
    with psycopg.connect(pair.f.dsn) as connection:
        assert actor_rows(connection, pair, PRINCIPAL) == states
        chosen_rows = actor_rows(connection, pair, chosen.actor_ref)
        assert chosen_rows["communication_client_read_state"] == []
        assert chosen_rows["communication_client_drafts"] == []
        assert chosen_rows["communication_client_preferences"][0][0]["revision"] == 1
    with pytest.raises(SchemaAdoptionError):
        facade(pair.f, 1).draft(PROJECT, pair.view)


def test_adopted_legacy_writer_is_fenced_and_original_rows_and_receipts_remain(pair):
    states, keys = seed_legacy(pair)
    chosen = scoped_identity(pair, 1)
    with psycopg.connect(pair.f.dsn) as connection:
        adopt_legacy_personal_state(connection.cursor(), chosen, legacy_actor_ref=PRINCIPAL, decision_ref="retire-old-writer")
    old = ClientStateIdentity(chosen.tenant_id, PROJECT, PRINCIPAL, pair.view)
    with psycopg.connect(pair.f.dsn) as connection:
        with pytest.raises(psycopg.errors.RaiseException, match="retired_personal_viewer_identity"), connection.transaction():
            write_draft(connection.cursor(), old, "Retired writer must not fork the adopted draft", [],
                        expected_revision=2, client_request_id="retired-writer-new-key")
        assert actor_rows(connection, pair, PRINCIPAL) == states
        assert connection.execute("SELECT to_jsonb(k) FROM communication_client_write_keys k WHERE tenant_id=%s AND actor_ref=%s ORDER BY client_request_id",
                                  (chosen.tenant_id, PRINCIPAL)).fetchall() == keys
    assert facade(pair.f, 1).draft(PROJECT, pair.view)["content"] == "Preserved legacy draft revision two"
