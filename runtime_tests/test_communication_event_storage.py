"""Committed event intents and replay order using actual isolated PostgreSQL.

Events are invalidation metadata, never a duplicate of message/draft content.
Source transactions write intents only; publication owns stream serialization.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import UTC, datetime, timedelta
from threading import Event

import psycopg
import pytest

from runtime.communication_client_queries import conversation_view_id
from runtime.communication_client_storage import (
    ClientStateIdentity,
    adopt_client_storage,
    delete_draft,
    write_draft,
    write_read_state,
)
from runtime.communication_event_storage import (
    NAME,
    TABLES,
    EventCursorExpired,
    adopt_event_storage,
    publish_event_intents,
    purge_event_records,
    read_event_records,
    record_event_intent,
    stream_high_water,
    verify_event_storage,
)
from runtime.errors import IdempotencyConflict, SchemaAdoptionError
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send

comm = comm_fixture
PROJECT = "project-alpha"


@pytest.fixture
def evented(comm):
    with psycopg.connect(comm.dsn) as connection:
        adopt_client_storage(connection)
        adopt_event_storage(connection)
    return comm


def owner(f, conversation="conversation-event-test"):
    return ClientStateIdentity(f.authority.tenant_id, PROJECT,
                               f.clients["a"].service.context.principal_ref, conversation)


def draft(cursor, f, conversation, content="Unsent body must stay private"):
    return write_draft(cursor, owner(f, conversation), content, [], expected_revision=0,
                       client_request_id="draft-event-" + conversation)


def publish(f, limit=100):
    with psycopg.connect(f.dsn) as connection:
        return publish_event_intents(connection, f.authority.tenant_id, PROJECT, limit=limit)


def records(f, after=0, limit=100):
    with psycopg.connect(f.dsn) as connection:
        return read_event_records(connection.cursor(), f.authority.tenant_id, PROJECT, after=after, limit=limit)


def high(f):
    with psycopg.connect(f.dsn) as connection:
        return stream_high_water(connection.cursor(), f.authority.tenant_id, PROJECT)


def test_actual_message_reply_and_private_state_hooks_emit_metadata_only(evented):
    first = send(evented, content="PRIVATE_MESSAGE_EVENT_BODY", activation="message_only")["data"]
    reply = send(evented, "b", "a", "PRIVATE_REPLY_EVENT_BODY", activation="message_only",
                 reply_to=[first["message_handle"]])["data"]
    view = conversation_view_id(evented.authority.tenant_id, PROJECT,
        "collaborator:project-alpha:local-slot", "collaborator:project-alpha:slot-b")
    reader = ClientStateIdentity(evented.authority.tenant_id, PROJECT,
                                 evented.clients["b"].service.context.principal_ref, view)
    with psycopg.connect(evented.dsn) as connection, connection.cursor() as cursor:
        write_read_state(cursor, reader, through_message_handle=first["message_handle"], through_sequence=1,
                         expected_revision=0, client_request_id="event-read-state")
        draft(cursor, evented, view, "PRIVATE_DRAFT_EVENT_BODY")
        delete_draft(cursor, owner(evented, view), expected_revision=1, client_request_id="event-draft-delete")
    assert publish(evented) > 0
    observed = records(evented)
    kinds = [event["kind"] for event in observed]
    assert kinds.count("message.committed") == 2
    assert kinds.count("reply.linked") == 1
    assert kinds.count("read_state.changed") == 1
    assert kinds.count("draft.changed") == 2
    assert kinds.count("delivery.changed") >= 2
    committed = {event["resource_ref"] for event in observed if event["kind"] == "message.committed"}
    assert committed == {first["message_handle"], reply["message_handle"]}
    assert all("PRIVATE_" not in str(event) for event in observed)
    assert all(event["resource_revision"] >= 1 for event in observed)
    assert all(not driver.calls for driver in evented.drivers.values())


def test_source_rollback_has_no_event_and_publishing_is_read_model_only(evented):
    with psycopg.connect(evented.dsn) as connection:
        draft(connection.cursor(), evented, "rolled-back")
        connection.rollback()
    assert publish(evented) == 0
    assert high(evented) == 0 and records(evented) == []
    with psycopg.connect(evented.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM communication_client_drafts").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone()[0] == 0


def test_late_source_with_lower_intent_id_publishes_after_snapshot_without_gap(evented):
    with psycopg.connect(evented.dsn) as late_source:
        draft(late_source.cursor(), evented, "lower-reserved-id")
        with psycopg.connect(evented.dsn) as early_commit:
            draft(early_commit.cursor(), evented, "higher-committed-id")
        assert publish(evented) == 1
        boundary = high(evented)
        assert boundary == 1
        with psycopg.connect(evented.dsn) as snapshot:
            snapshot.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            assert snapshot.execute("SELECT conversation_id FROM communication_client_drafts ORDER BY conversation_id").fetchall() == [("higher-committed-id",)]
            assert stream_high_water(snapshot.cursor(), evented.authority.tenant_id, PROJECT) == boundary
            late_source.commit()
            assert publish(evented) == 1
            assert stream_high_water(snapshot.cursor(), evented.authority.tenant_id, PROJECT) == boundary
            assert snapshot.execute("SELECT count(*) FROM communication_client_drafts").fetchone()[0] == 1
        tail = records(evented, after=boundary)
        assert len(tail) == 1 and tail[0]["sequence"] == boundary + 1
        assert len({event["event_id"] for event in records(evented)}) == 2


def test_source_does_not_wait_on_publisher_stream_lock(evented):
    with ThreadPoolExecutor(max_workers=1) as pool, psycopg.connect(evented.dsn) as publisher:
        assert publish_event_intents(publisher, evented.authority.tenant_id, PROJECT) == 0

        def source():
            with psycopg.connect(evented.dsn) as connection:
                return draft(connection.cursor(), evented, "source-with-publisher-held")

        completed = pool.submit(source)
        try:
            assert completed.result(timeout=3)["revision"] == 1
        finally:
            publisher.rollback()
    assert publish(evented) == 1


def test_two_publishers_serialize_and_do_not_duplicate_committed_intents(evented):
    with psycopg.connect(evented.dsn) as connection:
        for number in range(5):
            draft(connection.cursor(), evented, f"parallel-{number}")
    ready = Event()

    def concurrent():
        with psycopg.connect(evented.dsn) as connection:
            ready.set()
            return publish_event_intents(connection, evented.authority.tenant_id, PROJECT)

    with ThreadPoolExecutor(max_workers=1) as pool, psycopg.connect(evented.dsn) as first:
        assert publish_event_intents(first, evented.authority.tenant_id, PROJECT) == 5
        waiting = pool.submit(concurrent)
        assert ready.wait(timeout=3)
        try:
            with pytest.raises(FutureTimeout):
                waiting.result(timeout=0.2)
        finally:
            first.commit()
        assert waiting.result(timeout=5) == 0
    observed = records(evented)
    assert [event["sequence"] for event in observed] == [1, 2, 3, 4, 5]
    assert len({event["event_id"] for event in observed}) == 5


def test_publisher_rollback_retries_atomically_and_committed_retry_is_noop(evented):
    with psycopg.connect(evented.dsn) as connection:
        draft(connection.cursor(), evented, "publisher-rollback")
    with psycopg.connect(evented.dsn) as connection:
        assert publish_event_intents(connection, evented.authority.tenant_id, PROJECT) == 1
        assert stream_high_water(connection.cursor(), evented.authority.tenant_id, PROJECT) == 1
        connection.rollback()
    assert high(evented) == 0 and records(evented) == []
    assert publish(evented) == 1
    committed = records(evented)
    assert publish(evented) == 0 and records(evented) == committed


def test_bounded_keyset_pages_cover_each_published_event_once(evented):
    with psycopg.connect(evented.dsn) as connection:
        for number in range(5):
            draft(connection.cursor(), evented, f"page-{number}")
    assert publish(evented, limit=2) == 2
    assert publish(evented, limit=2) == 2
    assert publish(evented, limit=2) == 1
    assert publish(evented, limit=2) == 0
    observed, after = [], 0
    while True:
        page = records(evented, after=after, limit=2)
        assert len(page) <= 2
        if not page:
            break
        observed.extend(page)
        after = page[-1]["sequence"]
    assert len(observed) == len({event["event_id"] for event in observed}) == 5
    assert after == high(evented)


def test_repeatable_snapshot_reads_source_data_and_stream_boundary_consistently(evented):
    with psycopg.connect(evented.dsn) as connection:
        draft(connection.cursor(), evented, "before-snapshot")
    assert publish(evented) == 1
    with psycopg.connect(evented.dsn) as snapshot:
        snapshot.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        source = snapshot.execute("SELECT conversation_id FROM communication_client_drafts ORDER BY conversation_id").fetchall()
        boundary = stream_high_water(snapshot.cursor(), evented.authority.tenant_id, PROJECT)
        with psycopg.connect(evented.dsn) as concurrent:
            draft(concurrent.cursor(), evented, "after-snapshot")
        assert publish(evented) == 1
        assert snapshot.execute("SELECT conversation_id FROM communication_client_drafts ORDER BY conversation_id").fetchall() == source
        assert stream_high_water(snapshot.cursor(), evented.authority.tenant_id, PROJECT) == boundary
    assert len(records(evented, after=boundary)) == 1


class NoDatabase:
    def execute(self, *_args, **_kwargs):
        raise AssertionError("invalid event input must not access PostgreSQL")


@pytest.mark.parametrize("limit", [0, -1, True, 1001])
def test_invalid_event_batch_limits_fail_before_database(limit):
    with pytest.raises(ValueError):
        publish_event_intents(NoDatabase(), "tenant", PROJECT, limit=limit)
    with pytest.raises(ValueError):
        read_event_records(NoDatabase(), "tenant", PROJECT, after=0, limit=limit)


@pytest.mark.parametrize("after", [-1, True, 1.5, 2**63])
def test_invalid_replay_positions_fail_before_database(after):
    with pytest.raises(ValueError):
        read_event_records(NoDatabase(), "tenant", PROJECT, after=after)


@pytest.mark.parametrize("before", [None, "2026-11-06", datetime(2026, 11, 6, tzinfo=UTC).replace(tzinfo=None)])
def test_retention_requires_an_explicit_aware_instant(before):
    with pytest.raises(ValueError):
        purge_event_records(NoDatabase(), "tenant", PROJECT, before=before)


def intent(cursor, f, key="generic-source", **overrides):
    values = {"source_key": key, "kind": "draft.changed", "resource_ref": "conversation-generic-event",
              "resource_revision": 1, "audience_kind": "private",
              "actor_ref": f.clients["a"].service.context.principal_ref,
              "payload": {"conversation_id": "conversation-generic-event"}}
    values.update(overrides)
    return record_event_intent(cursor, f.authority.tenant_id, PROJECT, **values)


def test_missing_event_adoption_is_read_only_and_does_not_touch_base(comm):
    with psycopg.connect(comm.dsn) as connection:
        adopt_client_storage(connection)
        before = connection.execute("SELECT * FROM runtime_schema_metadata ORDER BY schema_name").fetchall()
        with pytest.raises(SchemaAdoptionError):
            verify_event_storage(connection)
        assert connection.execute("SELECT * FROM runtime_schema_metadata ORDER BY schema_name").fetchall() == before
        assert all(connection.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0] is None for table in TABLES)
    assert send(comm, activation="message_only")["ok"]


def test_repeated_adoption_preserves_existing_stream_and_intent_receipts(evented):
    with psycopg.connect(evented.dsn) as connection:
        intent(connection.cursor(), evented)
    assert publish(evented) == 1
    before = records(evented)
    with psycopg.connect(evented.dsn) as connection:
        metadata = connection.execute("SELECT * FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone()
        verify_event_storage(connection)
        adopt_event_storage(connection)
        assert connection.execute("SELECT * FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone() == metadata
    assert records(evented) == before and publish(evented) == 0


@pytest.mark.parametrize("damage", ["column", "primary_key", "index", "trigger", "function", "high_water", "missing_stream", "published_mapping"])
def test_event_storage_tamper_refuses_verify_and_adopt_does_not_repair(evented, damage):
    with psycopg.connect(evented.dsn) as connection:
        intent(connection.cursor(), evented)
    assert publish(evented) == 1
    with psycopg.connect(evented.dsn) as connection:
        if damage == "column":
            connection.execute("ALTER TABLE communication_event_stream DROP COLUMN payload_json")
        elif damage == "primary_key":
            connection.execute("ALTER TABLE communication_event_intents DROP CONSTRAINT communication_event_intents_pkey")
        elif damage == "index":
            connection.execute("DROP INDEX communication_event_pending")
        elif damage == "trigger":
            connection.execute("ALTER TABLE communication_messages DISABLE TRIGGER acs_communication_message_events")
        elif damage == "function":
            connection.execute("ALTER FUNCTION acs_communication_message_events() SECURITY DEFINER")
        elif damage == "high_water":
            connection.execute("UPDATE communication_event_clocks SET high_water=0 WHERE tenant_id=%s AND project_id=%s", (evented.authority.tenant_id, PROJECT))
        elif damage == "missing_stream":
            connection.execute("DELETE FROM communication_event_stream")
        else:
            connection.execute("UPDATE communication_event_intents SET published_sequence=NULL")
    for action in (verify_event_storage, adopt_event_storage):
        with psycopg.connect(evented.dsn) as connection, pytest.raises(SchemaAdoptionError):
            action(connection)


def test_generic_source_key_replay_preserves_original_intent_and_changed_input_conflicts(evented):
    with psycopg.connect(evented.dsn) as connection, connection.cursor() as cursor:
        intent(cursor, evented)
        intent(cursor, evented)
        for changes in ({"resource_revision": 2}, {"actor_ref": "other-actor"},
                        {"payload": {"reason_code": "different-metadata"}}):
            with pytest.raises(IdempotencyConflict), connection.transaction():
                intent(cursor, evented, **changes)
    assert publish(evented) == 1
    first = records(evented)
    assert first[0]["audience_kind"] == "private"
    assert first[0]["actor_ref"] == evented.clients["a"].service.context.principal_ref
    with psycopg.connect(evented.dsn) as connection:
        intent(connection.cursor(), evented)
    assert publish(evented) == 0 and records(evented) == first


@pytest.mark.parametrize("bad", [
    {"kind": "invented.completed"}, {"audience_kind": "everyone"},
    {"audience_kind": "message", "sender": None, "recipient": None},
    {"audience_kind": "private", "actor_ref": None},
    {"audience_kind": "receiver", "scope_id": None},
    {"audience_kind": "notice", "recipient": None},
    {"payload": {"content": "PRIVATE_BODY"}}, {"payload": {"text": "PRIVATE_BODY"}},
])
def test_registry_audience_and_metadata_only_payload_are_enforced(evented, bad):
    with (psycopg.connect(evented.dsn) as connection, connection.cursor() as cursor,
          pytest.raises((ValueError, psycopg.errors.CheckViolation)), connection.transaction()):
        intent(cursor, evented, **bad)
    assert publish(evented) == 0 and records(evented) == []


def test_tenant_and_project_streams_are_independent_even_with_same_source_key(evented):
    tenant = evented.authority.tenant_id
    second_tenant = tenant + "-other"
    with psycopg.connect(evented.dsn) as connection, connection.cursor() as cursor:
        cursor.execute("INSERT INTO scopes VALUES ('event-scope-beta',%s,'{}','active'),('event-scope-other',%s,'{}','active')", (tenant, second_tenant))
        cursor.execute("INSERT INTO collaboration_projects(tenant_id,project_id,root_id,scope_id,name,context_manifest) "
            "VALUES (%s,'project-beta','event-root-beta','event-scope-beta','Beta','{}'),"
            "(%s,'project-alpha','event-root-other','event-scope-other','Other','{}')", (tenant, second_tenant))
        for selected_tenant, project in ((tenant, PROJECT), (tenant, "project-beta"), (second_tenant, PROJECT)):
            record_event_intent(cursor, selected_tenant, project, source_key="same-key", kind="permission.changed",
                resource_ref=None, resource_revision=0, audience_kind="control", payload={"reset_required": True})
    identities = set()
    for selected_tenant, project in ((tenant, PROJECT), (tenant, "project-beta"), (second_tenant, PROJECT)):
        with psycopg.connect(evented.dsn) as connection:
            assert publish_event_intents(connection, selected_tenant, project) == 1
            page = read_event_records(connection.cursor(), selected_tenant, project, after=0)
            assert len(page) == 1 and page[0]["sequence"] == 1
            identities.add(page[0]["event_id"])
    assert len(identities) == 3 and len(records(evented)) == 1


def test_retention_removes_only_prefix_and_keeps_floor_and_dedup_tombstones(evented):
    with psycopg.connect(evented.dsn) as connection:
        intent(connection.cursor(), evented, "retained-original")
    assert publish(evented) == 1
    with psycopg.connect(evented.dsn) as connection:
        draft(connection.cursor(), evented, "retained-tail")
    assert publish(evented) == 1
    first, last = records(evented)
    assert first["published_at"] < last["published_at"]
    with psycopg.connect(evented.dsn) as connection:
        removed, floor = purge_event_records(connection, evented.authority.tenant_id, PROJECT, before=last["published_at"])
        assert (removed, floor) == (1, first["sequence"])
        verify_event_storage(connection)
    with pytest.raises(EventCursorExpired) as expired:
        records(evented, after=0)
    assert expired.value.code == "cursor_expired"
    assert records(evented, after=floor) == [last]
    assert high(evented) == last["sequence"]
    with psycopg.connect(evented.dsn) as connection:
        intent(connection.cursor(), evented, "retained-original")
    assert publish(evented) == 0
    with psycopg.connect(evented.dsn) as connection:
        assert purge_event_records(connection, evented.authority.tenant_id, PROJECT,
                                   before=last["published_at"] + timedelta(seconds=1)) == (1, last["sequence"])
        verify_event_storage(connection)
    assert records(evented, after=last["sequence"]) == []
    with pytest.raises(EventCursorExpired):
        records(evented, after=floor)
    with psycopg.connect(evented.dsn) as connection:
        draft(connection.cursor(), evented, "after-retention")
    assert publish(evented) == 1
    assert records(evented, after=last["sequence"])[0]["sequence"] == last["sequence"] + 1


def test_unpublished_but_visible_source_can_reappear_after_snapshot_without_loss(evented):
    with psycopg.connect(evented.dsn) as source:
        draft(source.cursor(), evented, "committed-unpublished")
    with psycopg.connect(evented.dsn) as snapshot:
        snapshot.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        assert snapshot.execute("SELECT conversation_id FROM communication_client_drafts").fetchall() == [("committed-unpublished",)]
        boundary = stream_high_water(snapshot.cursor(), evented.authority.tenant_id, PROJECT)
        assert boundary == 0
        assert publish(evented) == 1
        assert stream_high_water(snapshot.cursor(), evented.authority.tenant_id, PROJECT) == 0
    tail = records(evented, after=boundary)
    assert len(tail) == 1 and tail[0]["resource_revision"] == 1


def test_empty_stream_retention_is_read_only_noop(evented):
    with psycopg.connect(evented.dsn) as connection:
        assert purge_event_records(connection, evented.authority.tenant_id, PROJECT, before=datetime.now(UTC)) == (0, 0)
    assert high(evented) == 0 and records(evented) == []
