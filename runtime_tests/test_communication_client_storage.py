"""Optional client state and delivery versions in real, isolated PostgreSQL.

The storage accepts an identity only after the service has authorized it. These
tests exercise persistence/CAS, not authorization or Native consumption.
"""
from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta
from threading import Barrier

import psycopg
import pytest
from psycopg import sql

from runtime.client_contracts import ClientContracts
from runtime.communication_client_storage import (
    FILE,
    MAX_DRAFT_BYTES,
    NAME,
    SHAPES,
    VERSION,
    ClientStateIdentity,
    adopt_client_storage,
    cursor_secret,
    delete_draft,
    read_contact_version,
    read_delivery_version,
    read_draft,
    read_preferences,
    read_read_state,
    verify_client_storage,
    write_draft,
    write_preferences,
    write_read_state,
)
from runtime.communication_storage import schema_definition
from runtime.delivery_models import EndpointBindingRequest
from runtime.errors import IdempotencyConflict, RevisionConflict, SchemaAdoptionError
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send
from runtime_tests.test_delivery import command

comm = comm_fixture


@pytest.fixture
def stored(comm):
    with psycopg.connect(comm.dsn) as connection:
        adopt_client_storage(connection)
    return comm


def identity(f, actor="actor-a", conversation="conversation-a"):
    return ClientStateIdentity(f.authority.tenant_id, "project-alpha", actor, conversation)


def test_schema_definition_uses_canonical_line_endings_and_its_own_version():
    raw, checksum, equivalents = schema_definition(FILE, VERSION)
    assert b"\r\n" not in raw
    assert checksum == hashlib.sha256(raw).hexdigest()
    assert (VERSION, checksum) in equivalents
    assert NAME != "acs-communication-core"


@pytest.mark.parametrize("bad", ["", " ", "x" * 513, 7, None])
@pytest.mark.parametrize("field", ["tenant_id", "project_id", "actor_ref", "conversation_id"])
def test_identity_requires_bounded_explicit_authorized_references(field, bad):
    fields = {"tenant_id": "tenant", "project_id": "project", "actor_ref": "actor", "conversation_id": "conversation"}
    fields[field] = bad
    with pytest.raises(ValueError):
        ClientStateIdentity(**fields)


class NoDatabase:
    def execute(self, *_args, **_kwargs):
        raise AssertionError("invalid input must not reach the database")


@pytest.mark.parametrize("value", [{}, {"muted": 1}, {"archived": "false"}, {"unknown": True}])
def test_invalid_preference_updates_fail_before_database(value):
    with pytest.raises(ValueError):
        write_preferences(NoDatabase(), ClientStateIdentity("t", "p", "a", "c"), value,
                          expected_revision=0, client_request_id="key")


@pytest.mark.parametrize("content,refs", [("字" * (MAX_DRAFT_BYTES // 3 + 1), []), (7, []),
                                            ("", ["ref"] * 9), ("", [None]), ("", ())],
                         ids=["utf8-overflow", "non-string", "too-many-refs", "non-string-ref", "non-list"])
def test_draft_limits_count_utf8_bytes_and_references_before_database(content, refs):
    with pytest.raises(ValueError):
        write_draft(NoDatabase(), ClientStateIdentity("t", "p", "a", "c"), content, refs,
                    expected_revision=0, client_request_id="key")


@pytest.mark.parametrize("sequence", [0, -1, True, 1.5, 2**63])
def test_read_frontier_needs_an_explicit_visible_sequence(sequence):
    with pytest.raises(ValueError):
        write_read_state(NoDatabase(), ClientStateIdentity("t", "p", "a", "c"),
                         through_message_handle="m", through_sequence=sequence,
                         expected_revision=0, client_request_id="key")


def test_missing_adoption_verification_is_read_only_and_base_still_valid(comm):
    with psycopg.connect(comm.dsn) as connection:
        before = connection.execute("SELECT * FROM runtime_schema_metadata ORDER BY schema_name").fetchall()
        with pytest.raises(SchemaAdoptionError, match="adoption required"):
            verify_client_storage(connection)
        assert all(connection.execute("SELECT to_regclass(%s)", (name,)).fetchone()[0] is None for name in SHAPES)
        assert connection.execute("SELECT * FROM runtime_schema_metadata ORDER BY schema_name").fetchall() == before
    # Optional state is never a requirement for the existing MCP surface.
    assert send(comm, activation="message_only")["ok"]


def test_explicit_adoption_is_idempotent_and_key_survives_new_connections(stored):
    with psycopg.connect(stored.dsn) as connection:
        key = cursor_secret(connection)
        assert type(key) is bytes and len(key) == 32
        before = connection.execute("SELECT * FROM communication_client_cursor_key").fetchall()
        adopt_client_storage(connection)
        verify_client_storage(connection)
        assert connection.execute("SELECT * FROM communication_client_cursor_key").fetchall() == before
        assert connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s",
                                  (NAME,)).fetchone() in schema_definition(FILE, VERSION)[2]
    with psycopg.connect(stored.dsn) as connection:
        assert cursor_secret(connection) == key


@pytest.mark.parametrize("damage", ["column", "primary_key", "trigger", "disabled_trigger", "key", "checksum"])
def test_incomplete_storage_refuses_startup_and_explicit_adopt_does_not_repair(stored, damage):
    with psycopg.connect(stored.dsn) as connection:
        if damage == "column":
            connection.execute("ALTER TABLE communication_client_preferences DROP COLUMN muted")
        elif damage == "primary_key":
            connection.execute("ALTER TABLE communication_client_preferences DROP CONSTRAINT communication_client_preferences_pkey")
        elif damage == "trigger":
            connection.execute("DROP TRIGGER acs_client_delivery_message_version ON delivery_messages")
        elif damage == "disabled_trigger":
            connection.execute("ALTER TABLE delivery_receipts DISABLE TRIGGER acs_client_delivery_receipt_version")
        elif damage == "key":
            connection.execute("DELETE FROM communication_client_cursor_key")
        else:
            connection.execute("UPDATE runtime_schema_metadata SET schema_checksum=%s WHERE schema_name=%s", ("0" * 64, NAME))
    for action in (verify_client_storage, adopt_client_storage):
        with psycopg.connect(stored.dsn) as connection, pytest.raises(SchemaAdoptionError):
            action(connection)
    with psycopg.connect(stored.dsn) as connection:
        if damage == "key":
            assert connection.execute("SELECT count(*) FROM communication_client_cursor_key").fetchone()[0] == 0


def test_unversioned_storage_is_not_guessed_or_key_rotated(stored):
    with psycopg.connect(stored.dsn) as connection:
        key = cursor_secret(connection)
        connection.execute("DELETE FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,))
    with psycopg.connect(stored.dsn) as connection, pytest.raises(SchemaAdoptionError, match="unversioned"):
        adopt_client_storage(connection)
    with psycopg.connect(stored.dsn) as connection:
        assert cursor_secret(connection) == key


def test_missing_state_defaults_and_independent_revisions(stored):
    owner = identity(stored)
    with psycopg.connect(stored.dsn) as connection, connection.cursor() as cursor:
        assert read_read_state(cursor, owner) == {"conversation_id": owner.conversation_id,
            "through_message_handle": None, "unread_override": False, "revision": 0}
        assert read_preferences(cursor, owner) == {"archived": False, "muted": False, "revision": 0}
        assert read_draft(cursor, owner) == {"content": "", "attachment_refs": [], "revision": 0, "updated_at": None}
        read = write_read_state(cursor, owner, through_message_handle="visible-message-10", through_sequence=10,
                                unread_override=True, expected_revision=0, client_request_id="read-1")
        prefs = write_preferences(cursor, owner, {"muted": True}, expected_revision=0, client_request_id="prefs-1")
        draft = write_draft(cursor, owner, "Unsent context", ["authorized-attachment"], expected_revision=0,
                            client_request_id="draft-1")
        assert read["revision"] == prefs["revision"] == draft["revision"] == 1
        for model, value in (("ReadState", read), ("Preferences", prefs), ("Draft", draft)):
            assert ClientContracts().validate(model, value) == value
        assert cursor_secret(connection).hex() not in str((read, prefs, draft))


def test_read_frontier_is_monotonic_and_manual_flag_is_independent(stored):
    owner = identity(stored)
    with psycopg.connect(stored.dsn) as connection, connection.cursor() as cursor:
        write_read_state(cursor, owner, through_message_handle="message-20", through_sequence=20,
                         expected_revision=0, client_request_id="r1", unread_override=True)
        lower = write_read_state(cursor, owner, through_message_handle="message-7", through_sequence=7,
                                 expected_revision=1, client_request_id="r2", unread_override=False)
        assert lower == {"conversation_id": owner.conversation_id, "through_message_handle": "message-20",
                         "unread_override": False, "revision": 2}
        higher = write_read_state(cursor, owner, through_message_handle="message-30", through_sequence=30,
                                  expected_revision=2, client_request_id="r3")
        assert higher["through_message_handle"] == "message-30" and not higher["unread_override"]
        with pytest.raises(ValueError, match="different messages"):
            write_read_state(cursor, owner, through_message_handle="ambiguous-message", through_sequence=30,
                             expected_revision=3, client_request_id="r4")
        assert read_read_state(cursor, owner) == higher


def test_same_key_replays_original_result_before_cas_and_changed_body_conflicts(stored):
    owner = identity(stored)
    with psycopg.connect(stored.dsn) as connection, connection.cursor() as cursor:
        first = write_preferences(cursor, owner, {"muted": True}, expected_revision=0, client_request_id="first")
        latest = write_preferences(cursor, owner, {"archived": True}, expected_revision=1, client_request_id="second")
        assert latest == {"archived": True, "muted": True, "revision": 2}
        assert write_preferences(cursor, owner, {"muted": True}, expected_revision=0, client_request_id="first") == first
        for changed_owner, changes, revision in ((owner, {"muted": False}, 0),
                (owner, {"muted": True}, 2), (replace(owner, conversation_id="other"), {"muted": True}, 0)):
            with pytest.raises(IdempotencyConflict):
                write_preferences(cursor, changed_owner, changes, expected_revision=revision, client_request_id="first")
        with pytest.raises(RevisionConflict) as conflict:
            write_preferences(cursor, owner, {"muted": False}, expected_revision=0, client_request_id="new-key")
        assert (conflict.value.expected, conflict.value.actual, conflict.value.field) == (0, 2, "If-Match")
        assert read_preferences(cursor, owner) == latest


def test_state_and_same_key_are_isolated_by_actor_and_conversation(stored):
    owner = identity(stored)
    other_actor = replace(owner, actor_ref="actor-b")
    other_conversation = replace(owner, conversation_id="conversation-b")
    with psycopg.connect(stored.dsn) as connection, connection.cursor() as cursor:
        write_preferences(cursor, owner, {"muted": True}, expected_revision=0, client_request_id="key")
        assert read_preferences(cursor, other_actor)["revision"] == 0
        assert read_preferences(cursor, other_conversation)["revision"] == 0
        assert write_preferences(cursor, other_actor, {"archived": True}, expected_revision=0,
                                 client_request_id="key") == {"archived": True, "muted": False, "revision": 1}
        assert read_preferences(cursor, owner) == {"archived": False, "muted": True, "revision": 1}


def test_draft_exact_retry_and_delete_keep_cas_tombstone(stored):
    owner = identity(stored)
    content = "字" * (MAX_DRAFT_BYTES // 3) + "a"
    with psycopg.connect(stored.dsn) as connection, connection.cursor() as cursor:
        saved = write_draft(cursor, owner, content, ["attachment"] * 8, expected_revision=0, client_request_id="save")
        deleted = delete_draft(cursor, owner, expected_revision=1, client_request_id="delete")
        assert deleted["content"] == "" and deleted["attachment_refs"] == [] and deleted["revision"] == 2
        assert write_draft(cursor, owner, content, ["attachment"] * 8, expected_revision=0, client_request_id="save") == saved
        assert delete_draft(cursor, owner, expected_revision=1, client_request_id="delete") == deleted
        with pytest.raises(RevisionConflict):
            write_draft(cursor, owner, "stale resurrection", [], expected_revision=0, client_request_id="new-save")
        assert read_draft(cursor, owner) == deleted


def test_concurrent_cas_has_one_winner_and_other_resource_does_not_conflict(stored):
    owner = identity(stored)
    ready = Barrier(2)

    def contender(key):
        with psycopg.connect(stored.dsn) as connection, connection.cursor() as cursor:
            ready.wait(timeout=5)
            try:
                return write_preferences(cursor, owner, {"muted": True}, expected_revision=0, client_request_id=key)
            except RevisionConflict:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(contender, ("left", "right")))
    assert results.count("conflict") == 1
    assert sum(type(item) is dict and item["revision"] == 1 for item in results) == 1
    with psycopg.connect(stored.dsn) as connection, connection.cursor() as cursor:
        assert write_draft(cursor, owner, "still independent", [], expected_revision=0, client_request_id="draft")["revision"] == 1


def test_transaction_rollback_discards_state_and_retry_receipt_and_preserves_message(stored):
    message = send(stored, content="Original natural message", activation="message_only")["data"]
    owner = identity(stored)
    with psycopg.connect(stored.dsn) as connection:
        before = connection.execute("SELECT packet_json,command_json,canonical_hash FROM delivery_messages WHERE message_id=%s",
                                    (message["message_id"],)).fetchone()
    with psycopg.connect(stored.dsn) as connection, connection.cursor() as cursor:
        write_draft(cursor, owner, "rolled back draft", [], expected_revision=0, client_request_id="retry-after-rollback")
        write_preferences(cursor, owner, {"muted": True}, expected_revision=0, client_request_id="rolled-back-prefs")
        connection.rollback()
    with psycopg.connect(stored.dsn) as connection, connection.cursor() as cursor:
        assert read_draft(cursor, owner)["revision"] == read_preferences(cursor, owner)["revision"] == 0
        assert connection.execute("SELECT count(*) FROM communication_client_write_keys").fetchone()[0] == 0
        assert connection.execute("SELECT packet_json,command_json,canonical_hash FROM delivery_messages WHERE message_id=%s",
                                  (message["message_id"],)).fetchone() == before
        assert write_draft(cursor, owner, "committed retry", [], expected_revision=0,
                           client_request_id="retry-after-rollback")["revision"] == 1


def test_delivery_adoption_backfill_uses_materialization_time_and_preserves_packets(comm):
    message = send(comm, activation="message_only")["data"]
    with psycopg.connect(comm.dsn) as connection:
        packet = connection.execute("SELECT packet_json FROM delivery_messages WHERE message_id=%s", (message["message_id"],)).fetchone()[0]
        before = connection.execute("SELECT clock_timestamp()").fetchone()[0]
        adopt_client_storage(connection)
        revision, updated = read_delivery_version(connection.cursor(), comm.authority.tenant_id, message["message_id"])
        after = connection.execute("SELECT clock_timestamp()").fetchone()[0]
        assert revision == 1 and before <= datetime.fromisoformat(updated) <= after
        assert connection.execute("SELECT packet_json FROM delivery_messages WHERE message_id=%s", (message["message_id"],)).fetchone()[0] == packet
        adopt_client_storage(connection)
        assert read_delivery_version(connection.cursor(), comm.authority.tenant_id, message["message_id"]) == (revision, updated)


def test_delivery_triggers_version_actual_changes_receipts_replies_and_rollback(stored):
    message = send(stored, activation="message_only")["data"]
    tenant, mid = stored.authority.tenant_id, message["message_id"]
    with psycopg.connect(stored.dsn) as connection, connection.cursor() as cursor:
        initial = read_delivery_version(cursor, tenant, mid)
        cursor.execute("UPDATE delivery_messages SET state=state WHERE tenant_id=%s AND message_id=%s", (tenant, mid))
        assert read_delivery_version(cursor, tenant, mid) == initial
        cursor.execute("UPDATE delivery_messages SET last_error='controlled fixture error' WHERE tenant_id=%s AND message_id=%s", (tenant, mid))
        changed = read_delivery_version(cursor, tenant, mid)
        assert changed[0] == initial[0] + 1 and datetime.fromisoformat(changed[1]) >= datetime.fromisoformat(initial[1])
        cursor.execute("INSERT INTO delivery_receipts(tenant_id,message_id,receipt_id,layer,evidence_json) VALUES (%s,%s,'fixture-receipt','fixture','{}')", (tenant, mid))
        assert read_delivery_version(cursor, tenant, mid)[0] == changed[0] + 1
    with psycopg.connect(stored.dsn) as connection, connection.cursor() as cursor:
        before_reply = read_delivery_version(cursor, tenant, mid)
    send(stored, "b", "a", "Explicit fixture reply", activation="message_only", reply_to=[message["message_handle"]])
    with psycopg.connect(stored.dsn) as connection, connection.cursor() as cursor:
        replied = read_delivery_version(cursor, tenant, mid)
        assert replied[0] == before_reply[0] + 1
        cursor.execute("UPDATE delivery_messages SET attempts=attempts+1 WHERE tenant_id=%s AND message_id=%s", (tenant, mid))
        assert read_delivery_version(cursor, tenant, mid)[0] == replied[0] + 1
        connection.rollback()
    with psycopg.connect(stored.dsn) as connection, connection.cursor() as cursor:
        assert read_delivery_version(cursor, tenant, mid) == replied
        with pytest.raises(LookupError, match="not been materialized"):
            read_delivery_version(cursor, "other-tenant", mid)


def test_delivery_materializer_skips_retired_task_packets(comm):
    message = send(comm, activation="message_only")["data"]
    tenant, mid = comm.authority.tenant_id, message["message_id"]
    with psycopg.connect(comm.dsn) as connection:
        connection.execute("UPDATE delivery_messages SET packet_json=jsonb_set(packet_json,'{schema_version}',%s::jsonb) WHERE message_id=%s",
                           ('"retired-task/1"', mid))
        adopt_client_storage(connection)
        connection.execute("UPDATE delivery_messages SET attempts=attempts+1 WHERE message_id=%s", (mid,))
        assert connection.execute("SELECT count(*) FROM communication_delivery_versions WHERE tenant_id=%s AND message_id=%s", (tenant, mid)).fetchone()[0] == 0


def test_delivery_wrong_trigger_source_shape_is_refused(stored):
    with psycopg.connect(stored.dsn) as connection:
        connection.execute("DROP TRIGGER acs_client_delivery_message_version ON delivery_messages")
        connection.execute(sql.SQL("CREATE TRIGGER {} AFTER UPDATE OF state ON delivery_messages FOR EACH ROW EXECUTE FUNCTION acs_client_delivery_message_version()").format(
            sql.Identifier("acs_client_delivery_message_version")))
    with psycopg.connect(stored.dsn) as connection, pytest.raises(SchemaAdoptionError, match="version trigger"):
        verify_client_storage(connection)


def test_contact_versions_are_explicitly_seeded_and_read_only(stored):
    tenant = stored.authority.tenant_id
    with psycopg.connect(stored.dsn) as connection, connection.cursor() as cursor:
        before = connection.execute("SELECT * FROM communication_contact_versions").fetchall()
        assert read_contact_version(cursor, tenant, "project-alpha") == 1
        assert read_contact_version(cursor, tenant, "project-alpha") == 1
        adopt_client_storage(connection)
        verify_client_storage(connection)
        assert connection.execute("SELECT * FROM communication_contact_versions").fetchall() == before
        with pytest.raises(LookupError, match="not been materialized"):
            read_contact_version(cursor, "foreign-tenant", "project-alpha")


@pytest.mark.parametrize("damage", ["counter", "trigger"])
def test_contact_projection_damage_requires_explicit_repair_and_is_not_regenerated(stored, damage):
    with psycopg.connect(stored.dsn) as connection:
        if damage == "counter":
            connection.execute("DELETE FROM communication_contact_versions")
        else:
            connection.execute("ALTER TABLE delivery_endpoints DISABLE TRIGGER acs_client_contact_endpoints_version")
    for action in (verify_client_storage, adopt_client_storage):
        with psycopg.connect(stored.dsn) as connection, pytest.raises(SchemaAdoptionError):
            action(connection)
    if damage == "counter":
        with psycopg.connect(stored.dsn) as connection:
            assert connection.execute("SELECT count(*) FROM communication_contact_versions").fetchone()[0] == 0


def test_actual_endpoint_bind_revoke_and_rebind_advance_contact_version(stored):
    tenant = stored.authority.tenant_id
    delivery = stored.dispatcher.service
    with psycopg.connect(stored.dsn) as connection:
        before = read_contact_version(connection.cursor(), tenant, "project-alpha")
    delivery.bind_endpoint(command(stored.authority, "message.bind", "endpoint-b", revision=1),
        EndpointBindingRequest(scope_id="local-scope", agent_slot_id="slot-b",
                               expires_at=stored.authority.canonical_now() + timedelta(hours=1)))
    with psycopg.connect(stored.dsn) as connection:
        bound = read_contact_version(connection.cursor(), tenant, "project-alpha")
        assert bound == before + 1
        connection.execute("UPDATE delivery_endpoints SET status='revoked' WHERE tenant_id=%s AND endpoint_id='endpoint-b'", (tenant,))
        revoked = read_contact_version(connection.cursor(), tenant, "project-alpha")
        assert revoked == bound + 1
    delivery.bind_endpoint(command(stored.authority, "message.bind", "endpoint-b", revision=2),
        EndpointBindingRequest(scope_id="local-scope", agent_slot_id="slot-b",
                               expires_at=stored.authority.canonical_now() + timedelta(hours=1)))
    with psycopg.connect(stored.dsn) as connection:
        assert read_contact_version(connection.cursor(), tenant, "project-alpha") == revoked + 1


def test_endpoint_delete_recreate_and_slot_aba_cannot_reset_contact_version(stored):
    tenant = stored.authority.tenant_id
    with psycopg.connect(stored.dsn) as connection, connection.cursor() as cursor:
        before = read_contact_version(cursor, tenant, "project-alpha")
        cursor.execute("WITH removed AS (DELETE FROM delivery_endpoints WHERE tenant_id=%s AND endpoint_id='endpoint-b' RETURNING *) "
                       "INSERT INTO delivery_endpoints SELECT * FROM removed", (tenant,))
        recreated = read_contact_version(cursor, tenant, "project-alpha")
        assert recreated == before + 2
        cursor.execute("UPDATE agent_slots SET status='revoked' WHERE tenant_id=%s AND agent_slot_id='slot-b'", (tenant,))
        cursor.execute("UPDATE agent_slots SET status='active' WHERE tenant_id=%s AND agent_slot_id='slot-b'", (tenant,))
        assert read_contact_version(cursor, tenant, "project-alpha") == recreated + 2
        cursor.execute("UPDATE delivery_endpoints SET status=status WHERE tenant_id=%s AND endpoint_id='endpoint-b'", (tenant,))
        assert read_contact_version(cursor, tenant, "project-alpha") == recreated + 2


def test_team_member_membership_and_supervisor_mutations_advance_contact_version(stored):
    tenant = stored.authority.tenant_id
    with psycopg.connect(stored.dsn) as connection, connection.cursor() as cursor:
        current = read_contact_version(cursor, tenant, "project-alpha")

        def advanced():
            nonlocal current
            actual = read_contact_version(cursor, tenant, "project-alpha")
            assert actual == current + 1
            current = actual

        cursor.execute("INSERT INTO collaboration_teams VALUES (%s,'project-alpha','local-scope',1,'{}')", (tenant,))
        advanced()
        cursor.execute("UPDATE collaboration_teams SET revision=2 WHERE tenant_id=%s AND project_id='project-alpha'", (tenant,))
        advanced()
        cursor.execute("INSERT INTO collaboration_team_members VALUES (%s,'project-alpha','local-scope','slot-b','agent:b','engineer','engineer','grant:b','budget','{}','active')", (tenant,))
        advanced()
        cursor.execute("UPDATE collaboration_team_members SET role='reviewer' WHERE tenant_id=%s AND project_id='project-alpha'", (tenant,))
        advanced()
        cursor.execute("DELETE FROM collaboration_team_members WHERE tenant_id=%s AND project_id='project-alpha'", (tenant,))
        advanced()
        cursor.execute("DELETE FROM collaboration_teams WHERE tenant_id=%s AND project_id='project-alpha'", (tenant,))
        advanced()
        cursor.execute("SELECT * FROM collaboration_memberships WHERE tenant_id=%s AND project_id='project-alpha' AND principal_ref='agent:b'", (tenant,))
        membership = cursor.fetchone()
        cursor.execute("DELETE FROM collaboration_memberships WHERE tenant_id=%s AND project_id='project-alpha' AND principal_ref='agent:b'", (tenant,))
        advanced()
        cursor.execute("INSERT INTO collaboration_memberships VALUES (%s,%s,%s,%s,%s,%s)", membership)
        advanced()
        cursor.execute("UPDATE collaboration_memberships SET profile='route_manager' WHERE tenant_id=%s AND project_id='project-alpha' AND principal_ref='agent:b'", (tenant,))
        advanced()
        cursor.execute("INSERT INTO communication_supervisors VALUES (%s,'project-alpha','slot-b','collaborator:project-alpha:local-slot')", (tenant,))
        advanced()
        cursor.execute("UPDATE communication_supervisors SET manager_address='collaborator:project-alpha:slot-c' WHERE tenant_id=%s AND project_id='project-alpha' AND agent_slot_id='slot-b'", (tenant,))
        advanced()
        cursor.execute("DELETE FROM communication_supervisors WHERE tenant_id=%s AND project_id='project-alpha' AND agent_slot_id='slot-b'", (tenant,))
        advanced()


def test_endpoint_rebind_invalidates_old_and_new_actual_member_projects_only(stored):
    tenant = stored.authority.tenant_id
    with psycopg.connect(stored.dsn) as connection, connection.cursor() as cursor:
        cursor.execute("INSERT INTO scopes VALUES ('contact-scope-beta',%s,'{}','active')", (tenant,))
        cursor.execute("INSERT INTO agent_slots VALUES ('contact-slot-beta',%s,'contact-scope-beta','active')", (tenant,))
        cursor.execute("INSERT INTO collaboration_projects(tenant_id,project_id,root_id,scope_id,name,context_manifest) "
                       "VALUES (%s,'project-beta','contact-root-beta','contact-scope-beta','Beta','{}')", (tenant,))
        assert read_contact_version(cursor, tenant, "project-beta") == 1
        cursor.execute("INSERT INTO collaboration_memberships VALUES (%s,'project-beta','agent:beta','grant:b','engineer','contact-slot-beta')", (tenant,))
        alpha = read_contact_version(cursor, tenant, "project-alpha")
        beta = read_contact_version(cursor, tenant, "project-beta")
        cursor.execute("UPDATE delivery_endpoints SET agent_slot_id='contact-slot-beta',scope_id='contact-scope-beta' "
                       "WHERE tenant_id=%s AND endpoint_id='endpoint-b'", (tenant,))
        assert read_contact_version(cursor, tenant, "project-alpha") == alpha + 1
        assert read_contact_version(cursor, tenant, "project-beta") == beta + 1
        cursor.execute("UPDATE delivery_endpoints SET agent_slot_id='slot-b',scope_id='local-scope' "
                       "WHERE tenant_id=%s AND endpoint_id='endpoint-b'", (tenant,))
        assert read_contact_version(cursor, tenant, "project-alpha") == alpha + 2
        assert read_contact_version(cursor, tenant, "project-beta") == beta + 2
        cursor.execute("UPDATE agent_slots SET status='revoked' WHERE tenant_id=%s AND agent_slot_id='contact-slot-beta'", (tenant,))
        assert read_contact_version(cursor, tenant, "project-alpha") == alpha + 2
        assert read_contact_version(cursor, tenant, "project-beta") == beta + 3


def test_contact_projection_ticks_roll_back_with_source_and_preserve_immutable_message(stored):
    message = send(stored, activation="message_only")["data"]
    tenant = stored.authority.tenant_id
    with psycopg.connect(stored.dsn) as connection, connection.cursor() as cursor:
        version = read_contact_version(cursor, tenant, "project-alpha")
        cursor.execute("SELECT packet_json,canonical_hash FROM delivery_messages WHERE message_id=%s", (message["message_id"],))
        original = cursor.fetchone()
        cursor.execute("UPDATE delivery_endpoints SET status='revoked' WHERE tenant_id=%s AND endpoint_id='endpoint-b'", (tenant,))
        assert read_contact_version(cursor, tenant, "project-alpha") == version + 1
        connection.rollback()
    with psycopg.connect(stored.dsn) as connection, connection.cursor() as cursor:
        assert read_contact_version(cursor, tenant, "project-alpha") == version
        assert connection.execute("SELECT status FROM delivery_endpoints WHERE tenant_id=%s AND endpoint_id='endpoint-b'", (tenant,)).fetchone() == ("active",)
        assert connection.execute("SELECT packet_json,canonical_hash FROM delivery_messages WHERE message_id=%s", (message["message_id"],)).fetchone() == original
