"""Notice metadata and private seen receipts on actual isolated PostgreSQL.

Sources come from the normal fail_b/manager notice path. Storage helpers accept
an already-authorized cursor; recipient access is still checked by ProjectService.
The interleaving cursor below schedules real PostgreSQL commits, not fake rows.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import psycopg
import pytest

from runtime.communication_client_notice_storage import (
    NAME,
    TABLES,
    NoticeStateIdentity,
    adopt_notice_storage,
    notice_page_version,
    read_notice_metadata,
    read_notice_seen,
    verify_notice_storage,
    write_notice_seen,
)
from runtime.communication_client_storage import adopt_client_storage
from runtime.communication_faults import queue_communication_notices
from runtime.errors import IdempotencyConflict, RevisionConflict, SchemaAdoptionError
from runtime_tests.test_communication import call
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_faults import fail_b

comm = comm_fixture
PROJECT = "project-alpha"
RECIPIENT = "collaborator:project-alpha:local-slot"


def configure_manager(f):
    call(f, "a", "configure_team", prepare_native=False,
         members=[{"agent_slot_id": "slot-b", "principal_ref": "agent:b"}])


def create_notice(f):
    request = fail_b(f)
    queue_communication_notices(f.authority)
    with psycopg.connect(f.dsn) as connection:
        row = connection.execute("SELECT n.sequence,r.delivery_message_id,d.operation_id FROM communication_notices n "
            "JOIN communication_notice_routes r USING(tenant_id,project_id,message_id,recipient) "
            "JOIN delivery_messages d ON d.tenant_id=r.tenant_id AND d.message_id=r.delivery_message_id "
            "WHERE n.tenant_id=%s AND n.project_id=%s AND n.message_id=%s AND n.recipient=%s",
            (f.authority.tenant_id, PROJECT, request["message_id"], RECIPIENT)).fetchone()
    assert row is not None
    identity = NoticeStateIdentity(f.authority.tenant_id, PROJECT, f.clients["a"].service.context.principal_ref,
                                   request["message_id"], RECIPIENT)
    return SimpleNamespace(f=f, identity=identity, request=request, sequence=row[0],
                           delivery_id=row[1], operation_id=row[2],
                           reference=f"notification:{PROJECT}:communication-{row[0]}")


@pytest.fixture
def noted(comm):
    with psycopg.connect(comm.dsn) as connection:
        adopt_client_storage(connection)
        adopt_notice_storage(connection)
    configure_manager(comm)
    return create_notice(comm)


def metadata(note):
    with psycopg.connect(note.f.dsn) as connection:
        return read_notice_metadata(connection.cursor(), note.identity)


def outcome(cursor, owner):
    def project(seen, private_revision, source_revision, created_at):
        cursor.execute("SELECT state,code FROM communication_notices WHERE tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s", owner.source())
        state, code = cursor.fetchone()
        cursor.execute("SELECT EXISTS(SELECT 1 FROM communication_notice_routes r JOIN delivery_receipts d "
            "ON d.tenant_id=r.tenant_id AND d.message_id=r.delivery_message_id AND d.layer='runtime_acknowledged' "
            "WHERE r.tenant_id=%s AND r.project_id=%s AND r.message_id=%s AND r.recipient=%s)", owner.source())
        return {"seen": seen, "private_revision": private_revision, "source_revision": source_revision,
                "revision": source_revision + private_revision, "created_at": created_at,
                "source_state": state, "source_code": code, "native_acknowledged": cursor.fetchone()[0]}
    return project


class NoDatabase:
    def execute(self, *_args, **_kwargs):
        raise AssertionError("invalid input must not touch storage")


@pytest.mark.parametrize("field", ["tenant_id", "project_id", "actor_ref", "message_id", "recipient"])
@pytest.mark.parametrize("bad", ["", None, 1, "x" * 513])
def test_notice_identity_requires_explicit_bounded_references(field, bad):
    fields = {"tenant_id": "t", "project_id": "p", "actor_ref": "a", "message_id": "m", "recipient": "r"}
    fields[field] = bad
    with pytest.raises(ValueError):
        NoticeStateIdentity(**fields)


@pytest.mark.parametrize("seen,revision,key", [(1, 1, "key"), (True, True, "key"),
    (True, -1, "key"), (True, 2**63, "key"), (True, 1, ""), (True, 1, "x" * 201), (True, 1, "bad\nkey")])
def test_invalid_notice_writes_fail_before_storage(seen, revision, key):
    with pytest.raises(ValueError):
        write_notice_seen(NoDatabase(), NoticeStateIdentity("t", "p", "a", "m", "r"), seen,
                          expected_revision=revision, client_request_id=key, project_result=lambda *_args: {})


def test_notice_if_match_is_part_of_request_identity(noted):
    with psycopg.connect(noted.f.dsn) as connection, connection.cursor() as cursor:
        revision, _created = read_notice_metadata(cursor, noted.identity)
        original = write_notice_seen(cursor, noted.identity, True, expected_revision=revision,
            client_request_id="versioned-intent", project_result=outcome(cursor, noted.identity))
    with psycopg.connect(noted.f.dsn) as connection, connection.cursor() as cursor:
        with pytest.raises(IdempotencyConflict):
            write_notice_seen(cursor, noted.identity, True, expected_revision=revision + 1,
                client_request_id="versioned-intent", project_result=lambda *_args: pytest.fail("changed request reexecuted"))
        assert write_notice_seen(cursor, noted.identity, True, expected_revision=revision,
            client_request_id="versioned-intent", project_result=lambda *_args: pytest.fail("exact request reexecuted")) == original


def test_notice_adoption_missing_verification_is_read_only(comm):
    with psycopg.connect(comm.dsn) as connection:
        adopt_client_storage(connection)
        before = connection.execute("SELECT * FROM runtime_schema_metadata ORDER BY schema_name").fetchall()
        with pytest.raises(SchemaAdoptionError):
            verify_notice_storage(connection)
        assert connection.execute("SELECT * FROM runtime_schema_metadata ORDER BY schema_name").fetchall() == before
        assert all(connection.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0] is None for table in TABLES)


def test_repeated_adoption_and_verification_preserve_projection_and_private_receipts(noted):
    with psycopg.connect(noted.f.dsn) as connection, connection.cursor() as cursor:
        revision, _created = read_notice_metadata(cursor, noted.identity)
        write_notice_seen(cursor, noted.identity, True, expected_revision=revision, client_request_id="original",
                          project_result=outcome(cursor, noted.identity))
        snapshots = {table: connection.execute("SELECT to_jsonb(t) FROM " + table + " t ORDER BY to_jsonb(t)::text").fetchall() for table in TABLES}
        schema = connection.execute("SELECT * FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone()
        for action in (verify_notice_storage, adopt_notice_storage, verify_notice_storage):
            action(connection)
        assert {table: connection.execute("SELECT to_jsonb(t) FROM " + table + " t ORDER BY to_jsonb(t)::text").fetchall() for table in TABLES} == snapshots
        assert connection.execute("SELECT * FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone() == schema


@pytest.mark.parametrize("damage", ["column", "seen_key", "write_key", "trigger", "trigger_columns", "index", "source_version", "delivery_version"])
def test_incomplete_notice_storage_refuses_verify_and_adopt_does_not_repair(noted, damage):
    with psycopg.connect(noted.f.dsn) as connection:
        if damage == "column":
            connection.execute("ALTER TABLE communication_client_notice_versions DROP COLUMN created_at")
        elif damage == "seen_key":
            connection.execute("ALTER TABLE communication_client_notice_seen DROP CONSTRAINT communication_client_notice_seen_pkey")
        elif damage == "write_key":
            connection.execute("ALTER TABLE communication_client_notice_write_keys DROP CONSTRAINT communication_client_notice_write_keys_pkey")
        elif damage == "trigger":
            connection.execute("ALTER TABLE communication_notices DISABLE TRIGGER acs_client_notice_source_version")
        elif damage == "trigger_columns":
            connection.execute("DROP TRIGGER acs_client_notice_source_version ON communication_notices")
            connection.execute("CREATE TRIGGER acs_client_notice_source_version AFTER INSERT OR UPDATE OF state ON communication_notices FOR EACH ROW EXECUTE FUNCTION acs_client_notice_source_version()")
        elif damage == "index":
            connection.execute("DROP INDEX communication_client_notice_page")
        elif damage == "source_version":
            connection.execute("DELETE FROM communication_client_notice_versions WHERE tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s", noted.identity.source())
        else:
            connection.execute("DELETE FROM communication_delivery_versions WHERE tenant_id=%s AND message_id=%s", (noted.identity.tenant_id, noted.delivery_id))
    for action in (verify_notice_storage, adopt_notice_storage):
        with psycopg.connect(noted.f.dsn) as connection, pytest.raises(SchemaAdoptionError):
            action(connection)


def test_legacy_notice_timestamp_remains_unknown_and_new_source_gets_actual_stamp(comm):
    with psycopg.connect(comm.dsn) as connection:
        adopt_client_storage(connection)
    configure_manager(comm)
    legacy = create_notice(comm)
    with psycopg.connect(comm.dsn) as connection:
        before = connection.execute("SELECT clock_timestamp()").fetchone()[0]
        adopt_notice_storage(connection)
        assert read_notice_metadata(connection.cursor(), legacy.identity) == (1, None)
    fresh = create_notice(comm)
    with psycopg.connect(comm.dsn) as connection:
        _revision, created_at = read_notice_metadata(connection.cursor(), fresh.identity)
        after = connection.execute("SELECT clock_timestamp()").fetchone()[0]
        assert created_at is not None and before <= datetime.fromisoformat(created_at) <= after
        assert read_notice_metadata(connection.cursor(), legacy.identity) == (1, None)


def test_public_source_and_actor_seen_revisions_both_participate_in_cas(noted):
    owner = noted.identity
    with psycopg.connect(noted.f.dsn) as connection, connection.cursor() as cursor:
        public, created = read_notice_metadata(cursor, owner)
        assert read_notice_seen(cursor, owner) == (False, 0)
        first = write_notice_seen(cursor, owner, True, expected_revision=public, client_request_id="first", project_result=outcome(cursor, owner))
        assert first["revision"] == public + 1 and first["created_at"] == created
        with pytest.raises(RevisionConflict) as stale:
            write_notice_seen(cursor, owner, False, expected_revision=public, client_request_id="stale", project_result=outcome(cursor, owner))
        assert (stale.value.expected, stale.value.actual) == (public, public + 1)
        cursor.execute("UPDATE communication_notices SET code='controlled_source_change' WHERE tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s", owner.source())
        advanced, _created = read_notice_metadata(cursor, owner)
        assert advanced == public + 1
        with pytest.raises(RevisionConflict):
            write_notice_seen(cursor, owner, False, expected_revision=public + 1, client_request_id="stale-source", project_result=outcome(cursor, owner))
        latest = write_notice_seen(cursor, owner, False, expected_revision=advanced + 1, client_request_id="latest", project_result=outcome(cursor, owner))
        assert latest["revision"] == advanced + 2 and not latest["seen"]


def test_exact_receipt_precedes_cas_and_preserves_outcome_after_real_native_ack(noted):
    owner = noted.identity
    with psycopg.connect(noted.f.dsn) as connection, connection.cursor() as cursor:
        public, _created = read_notice_metadata(cursor, owner)
        first = write_notice_seen(cursor, owner, True, expected_revision=public, client_request_id="original", project_result=outcome(cursor, owner))
        assert first["native_acknowledged"] is False
    assert noted.f.dispatcher.dispatch({"tenant_id": owner.tenant_id, "message_id": noted.delivery_id,
                                        "operation_id": noted.operation_id})["status"] == "delivered"
    assert len(noted.f.drivers["a"].calls) == 1
    with psycopg.connect(noted.f.dsn) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE communication_notices SET code='later_source_change' WHERE tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s", owner.source())
        latest_public, _created = read_notice_metadata(cursor, owner)
        assert latest_public > public
        assert outcome(cursor, owner)(True, 1, latest_public, first["created_at"])["native_acknowledged"] is True

        def never_reproject(*_args):
            raise AssertionError("exact retry must return the original stored outcome")

        assert write_notice_seen(cursor, owner, True, expected_revision=public, client_request_id="original", project_result=never_reproject) == first
        with pytest.raises(IdempotencyConflict):
            write_notice_seen(cursor, owner, False, expected_revision=public, client_request_id="original", project_result=never_reproject)
        assert read_notice_seen(cursor, owner) == (True, 1)
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone()[0] == 0
    assert len(noted.f.drivers["a"].calls) == 1


def test_actor_seen_and_keys_are_isolated_and_page_version_uses_current_actor(noted):
    owner = noted.identity
    other = replace(owner, actor_ref="another-already-authorized-subject")
    with psycopg.connect(noted.f.dsn) as connection, connection.cursor() as cursor:
        public, _created = read_notice_metadata(cursor, owner)
        page_a = notice_page_version(cursor, owner.tenant_id, owner.project_id, owner.recipient, owner.actor_ref)
        page_b = notice_page_version(cursor, owner.tenant_id, owner.project_id, owner.recipient, other.actor_ref)
        write_notice_seen(cursor, owner, True, expected_revision=public, client_request_id="shared-key", project_result=outcome(cursor, owner))
        assert read_notice_seen(cursor, owner) == (True, 1) and read_notice_seen(cursor, other) == (False, 0)
        assert notice_page_version(cursor, owner.tenant_id, owner.project_id, owner.recipient, owner.actor_ref) != page_a
        assert notice_page_version(cursor, owner.tenant_id, owner.project_id, owner.recipient, other.actor_ref) == page_b
        write_notice_seen(cursor, other, False, expected_revision=public, client_request_id="shared-key", project_result=outcome(cursor, other))
        assert read_notice_seen(cursor, other) == (False, 1) and read_notice_seen(cursor, owner) == (True, 1)
        cursor.execute("UPDATE communication_notices SET code='public_page_change' WHERE tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s", owner.source())
        assert notice_page_version(cursor, owner.tenant_id, owner.project_id, owner.recipient, other.actor_ref) != page_b


def test_storage_adoption_does_not_expand_actual_notice_recipient_acl(noted):
    allowed = call(noted.f, "a", "read_message", handle=noted.reference)["data"]
    assert allowed["source"] == "acs" and allowed["message_handle"] == noted.request["message_handle"]
    for caller in ("b", "c"):
        rejected = noted.f.clients[caller].call("read_message", {"project_id": PROJECT, "handle": noted.reference})["structuredContent"]
        assert not rejected["ok"]
    assert all(not driver.calls for driver in noted.f.drivers.values())


def test_source_route_and_delivery_ticks_are_transactional_and_noops_are_stable(noted):
    owner = noted.identity
    before = metadata(noted)
    with psycopg.connect(noted.f.dsn) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE communication_notices SET state=state,code=code WHERE tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s", owner.source())
        cursor.execute("UPDATE communication_notice_routes SET last_error=last_error WHERE tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s", owner.source())
        assert read_notice_metadata(cursor, owner) == before
        cursor.execute("UPDATE communication_notices SET state='uncertain' WHERE tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s", owner.source())
        assert read_notice_metadata(cursor, owner)[0] == before[0] + 1
        cursor.execute("UPDATE communication_notice_routes SET last_error='controlled_route_change' WHERE tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s", owner.source())
        assert read_notice_metadata(cursor, owner)[0] == before[0] + 2
        cursor.execute("UPDATE delivery_messages SET last_error='controlled_notice_delivery_change' WHERE tenant_id=%s AND message_id=%s", (owner.tenant_id, noted.delivery_id))
        assert read_notice_metadata(cursor, owner)[0] == before[0] + 3
        write_notice_seen(cursor, owner, True, expected_revision=before[0] + 3, client_request_id="rolled-back", project_result=outcome(cursor, owner))
        connection.rollback()
    assert metadata(noted) == before
    with psycopg.connect(noted.f.dsn) as connection, connection.cursor() as cursor:
        assert read_notice_seen(cursor, owner) == (False, 0)
        assert connection.execute("SELECT count(*) FROM communication_client_notice_write_keys").fetchone()[0] == 0


@pytest.mark.parametrize("missing", ["source", "delivery"])
def test_missing_materialized_metadata_fails_closed_for_reads_and_new_writes(noted, missing):
    owner = noted.identity
    with psycopg.connect(noted.f.dsn) as connection, connection.cursor() as cursor:
        if missing == "source":
            cursor.execute("DELETE FROM communication_client_notice_versions WHERE tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s", owner.source())
        else:
            cursor.execute("DELETE FROM communication_delivery_versions WHERE tenant_id=%s AND message_id=%s", (owner.tenant_id, noted.delivery_id))
        with pytest.raises(LookupError, match="not materialized"):
            read_notice_metadata(cursor, owner)
        with pytest.raises(LookupError, match="not materialized"):
            write_notice_seen(cursor, owner, True, expected_revision=1, client_request_id="missing", project_result=outcome(cursor, owner))
        assert connection.execute("SELECT count(*) FROM communication_client_notice_seen").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM communication_client_notice_write_keys").fetchone()[0] == 0


def test_route_change_between_real_pg_reads_requires_fresh_view(noted):
    owner = noted.identity

    class InterleavingCursor:
        def __init__(self, cursor):
            self.cursor, self.first_route = cursor, True
            self.route_query = False

        def execute(self, query, args=None):
            self.route_query = query.startswith("SELECT r.delivery_message_id,v.revision FROM communication_client_notice_versions")
            self.cursor.execute(query, args)

        def fetchone(self):
            row = self.cursor.fetchone()
            if self.route_query and self.first_route:
                self.first_route = False
                with psycopg.connect(noted.f.dsn) as concurrent:
                    concurrent.execute("UPDATE communication_notice_routes SET delivery_message_id=NULL WHERE tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s", owner.source())
            return row

    with psycopg.connect(noted.f.dsn) as connection, connection.cursor() as cursor:
        with pytest.raises(RevisionConflict) as changed:
            read_notice_metadata(InterleavingCursor(cursor), owner)
        assert "route changed" in changed.value.guidance.lower()
