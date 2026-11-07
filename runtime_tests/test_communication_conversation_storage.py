"""Real per-viewer conversation versions and source/counter lock ordering."""
from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import psycopg
import pytest

from runtime.communication_client_queries import conversation_view_id
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_client_storage import (
    ClientStateIdentity,
    adopt_client_storage,
    read_preferences,
    write_preferences,
    write_read_state,
)
from runtime.communication_client_viewer_storage import adopt_viewer_storage
from runtime.communication_conversation_storage import (
    NAME,
    TABLE,
    adopt_conversation_storage,
    prepare_conversation_write,
    register_conversation_pair,
    sync_conversation_view,
    verify_conversation_storage,
)
from runtime.errors import SchemaAdoptionError
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send

comm = comm_fixture
PROJECT = "project-alpha"
ADDRESSES = {"a": "collaborator:project-alpha:local-slot", "b": "collaborator:project-alpha:slot-b", "c": "collaborator:project-alpha:slot-c"}


def cid(f, first="a", second="b"):
    return conversation_view_id(f.authority.tenant_id, PROJECT, ADDRESSES[first], ADDRESSES[second])


def owner(f, viewer="a", peer="b"):
    current = f.clients[viewer]
    service = CommunicationClientService(current.service, current.credential_provider())
    return ClientStateIdentity(f.authority.tenant_id, PROJECT, service._viewer_actor_ref(PROJECT, ADDRESSES[viewer]), cid(f, viewer, peer))


def register(cursor, f):
    register_conversation_pair(cursor, f.authority.tenant_id, PROJECT, cid(f), ADDRESSES["a"], ADDRESSES["b"])


def sync(cursor, f, viewer="a", peer="b"):
    return sync_conversation_view(cursor, owner(f, viewer, peer), ADDRESSES[viewer], ADDRESSES[peer])


def current(f, viewer="a", peer="b"):
    with psycopg.connect(f.dsn) as connection:
        return sync(connection.cursor(), f, viewer, peer)


def rows(connection):
    return connection.execute("SELECT viewer_address,actor_ref,message_count,read_revision,preferences_revision,revision "
                              "FROM communication_conversation_versions ORDER BY viewer_address").fetchall()


@pytest.fixture
def versioned(comm):
    with psycopg.connect(comm.dsn) as connection:
        adopt_client_storage(connection)
        adopt_viewer_storage(connection)
        adopt_conversation_storage(connection)
    return comm


class NoDatabase:
    @property
    def connection(self):
        raise AssertionError("invalid pair identity must fail before storage")


def test_wrong_opaque_conversation_and_wrong_project_pair_are_rejected_before_storage():
    expected = conversation_view_id("tenant", PROJECT, ADDRESSES["a"], ADDRESSES["b"])
    with pytest.raises(ValueError):
        register_conversation_pair(NoDatabase(), "tenant", PROJECT, "wrong-cid", ADDRESSES["a"], ADDRESSES["b"])
    with pytest.raises(ValueError):
        sync_conversation_view(NoDatabase(), ClientStateIdentity("tenant", "foreign-project", "viewer", expected), ADDRESSES["a"], ADDRESSES["b"])


def test_missing_adoption_verify_is_read_only(comm):
    with psycopg.connect(comm.dsn) as connection:
        adopt_client_storage(connection)
        before = connection.execute("SELECT * FROM runtime_schema_metadata ORDER BY schema_name").fetchall()
        with pytest.raises(SchemaAdoptionError):
            verify_conversation_storage(connection)
        assert connection.execute("SELECT to_regclass(%s)", (TABLE,)).fetchone()[0] is None
        assert connection.execute("SELECT * FROM runtime_schema_metadata ORDER BY schema_name").fetchall() == before


def test_registration_has_two_empty_directions_and_idempotent_adoption_does_not_allocate_versions(versioned):
    with psycopg.connect(versioned.dsn) as connection:
        register(connection.cursor(), versioned)
        before = rows(connection)
        assert len(before) == 2
        assert all(row[1:] == (None, 0, 0, 0, 0) for row in before)
        register(connection.cursor(), versioned)
        verify_conversation_storage(connection)
        adopt_conversation_storage(connection)
        assert rows(connection) == before
        assert connection.execute("SELECT schema_version FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone() == ("1",)


@pytest.mark.parametrize("damage", ["column", "key", "hash_function", "source_trigger", "identity_guard", "hash_generation"])
def test_damaged_projection_fails_verify_and_is_not_repaired(versioned, damage):
    with psycopg.connect(versioned.dsn) as connection:
        if damage == "column":
            connection.execute("ALTER TABLE communication_conversation_versions DROP COLUMN updated_at")
        elif damage == "key":
            connection.execute("ALTER TABLE communication_conversation_versions DROP CONSTRAINT communication_conversation_versions_pkey")
        elif damage == "hash_function":
            connection.execute("ALTER FUNCTION acs_conversation_address_hash(text) SECURITY DEFINER")
        elif damage == "source_trigger":
            connection.execute("ALTER TABLE communication_messages DISABLE TRIGGER acs_conversation_messages")
        elif damage == "identity_guard":
            connection.execute("DROP TRIGGER acs_conversation_version_guard ON communication_conversation_versions")
        else:
            connection.execute("ALTER TABLE communication_conversation_versions ALTER COLUMN viewer_hash DROP EXPRESSION")
    for action in (verify_conversation_storage, adopt_conversation_storage):
        with psycopg.connect(versioned.dsn) as connection, pytest.raises(SchemaAdoptionError):
            action(connection)


def test_actual_core_messages_and_private_sources_advance_only_appropriate_viewer(versioned):
    f = versioned
    with psycopg.connect(f.dsn) as connection:
        assert sync(connection.cursor(), f) == sync(connection.cursor(), f, "b", "a") == 0
    request = send(f, activation="message_only")["data"]
    assert current(f) == current(f, "b", "a") == 1
    with psycopg.connect(f.dsn) as connection, connection.cursor() as cursor:
        reader = owner(f, "b", "a")
        prepare_conversation_write(cursor, reader, ADDRESSES["b"], ADDRESSES["a"])
        write_read_state(cursor, reader, through_message_handle=request["message_handle"], through_sequence=1,
                         expected_revision=0, client_request_id="counter-read")
    assert current(f, "b", "a") == 2 and current(f) == 1
    with psycopg.connect(f.dsn) as connection, connection.cursor() as cursor:
        reader = owner(f, "b", "a")
        prepare_conversation_write(cursor, reader, ADDRESSES["b"], ADDRESSES["a"])
        write_preferences(cursor, reader, {"muted": True}, expected_revision=0, client_request_id="counter-prefs-b")
    assert current(f, "b", "a") == 3 and current(f) == 1
    with psycopg.connect(f.dsn) as connection, connection.cursor() as cursor:
        prepare_conversation_write(cursor, owner(f), ADDRESSES["a"], ADDRESSES["b"])
        write_preferences(cursor, owner(f), {"archived": True}, expected_revision=0, client_request_id="counter-prefs-a")
    assert current(f) == 2
    send(f, "b", "a", "Second actual pair message", activation="message_only")
    with psycopg.connect(f.dsn) as connection:
        assert sync(connection.cursor(), f) == 3
        assert sync(connection.cursor(), f, "b", "a") == 4
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone()[0] == 0
    assert all(not driver.calls for driver in f.drivers.values())


def test_prepared_private_write_binds_owner_after_source_and_unprepared_write_does_not_guess(versioned):
    f = versioned
    with psycopg.connect(f.dsn) as connection, connection.cursor() as cursor:
        register(cursor, f)
        write_preferences(cursor, owner(f), {"muted": True}, expected_revision=0, client_request_id="unmapped-private")
        assert all(row[1] is None and row[-1] == 0 for row in rows(connection))
        prepare_conversation_write(cursor, owner(f, "b", "a"), ADDRESSES["b"], ADDRESSES["a"])
        write_preferences(cursor, owner(f, "b", "a"), {"archived": True}, expected_revision=0, client_request_id="prepared-private")
        selected = {row[0]: row for row in rows(connection)}
        assert selected[ADDRESSES["a"]][1] is None
        assert selected[ADDRESSES["b"]][1] == owner(f, "b", "a").actor_ref
        assert selected[ADDRESSES["b"]][-1] == 1
        assert sync(cursor, f) == 1


def test_lazy_old_data_reconciliation_preserves_history_and_prior_component_baseline(comm):
    f = comm
    send(f, activation="message_only")
    incoming = send(f, "b", "a", "Existing history before projection adoption", activation="message_only")["data"]
    with psycopg.connect(f.dsn) as connection, connection.cursor() as cursor:
        adopt_client_storage(connection)
        adopt_viewer_storage(connection)
        write_read_state(cursor, owner(f), through_message_handle=incoming["message_handle"], through_sequence=2,
                         expected_revision=0, client_request_id="historical-read")
        write_preferences(cursor, owner(f), {"muted": True}, expected_revision=0, client_request_id="historical-pref-1")
        write_preferences(cursor, owner(f), {"archived": True}, expected_revision=1, client_request_id="historical-pref-2")
        packets = connection.execute("SELECT packet_json FROM delivery_messages ORDER BY message_id").fetchall()
        adopt_conversation_storage(connection)
        assert connection.execute("SELECT count(*) FROM communication_conversation_versions").fetchone()[0] == 0
        assert sync(cursor, f) >= 5
        assert sync(cursor, f, "b", "a") >= 2
        assert connection.execute("SELECT packet_json FROM delivery_messages ORDER BY message_id").fetchall() == packets
        assert read_preferences(cursor, owner(f)) == {"muted": True, "archived": True, "revision": 2}


def test_existing_registration_and_writer_preparation_do_not_wait_on_getter_counter(versioned):
    f = versioned
    with psycopg.connect(f.dsn) as connection:
        sync(connection.cursor(), f)
    with psycopg.connect(f.dsn) as getter:
        sync(getter.cursor(), f)
        with psycopg.connect(f.dsn) as registration:
            registration.execute("SET LOCAL lock_timeout='200ms'")
            register(registration.cursor(), f)
            prepare_conversation_write(registration.cursor(), owner(f), ADDRESSES["a"], ADDRESSES["b"])


def test_getter_counter_fence_reads_old_mvcc_cell_then_writer_publishes_new_version(versioned):
    f = versioned
    send(f, "b", "a", "Actual incoming baseline", activation="message_only")
    with psycopg.connect(f.dsn) as connection, connection.cursor() as cursor:
        prepare_conversation_write(cursor, owner(f), ADDRESSES["a"], ADDRESSES["b"])
        write_preferences(cursor, owner(f), {"muted": False}, expected_revision=0, client_request_id="baseline-private")
    ready = Event()
    application = "conversation-writer-" + uuid.uuid4().hex

    def writer():
        with psycopg.connect(f.dsn, application_name=application) as connection, connection.cursor() as cursor:
            prepare_conversation_write(cursor, owner(f), ADDRESSES["a"], ADDRESSES["b"])
            ready.set()
            return write_preferences(cursor, owner(f), {"muted": True}, expected_revision=1, client_request_id="blocked-private")

    with ThreadPoolExecutor(max_workers=1) as pool, psycopg.connect(f.dsn) as getter:
        old_revision = sync(getter.cursor(), f)
        waiting = pool.submit(writer)
        assert ready.wait(timeout=3)
        try:
            with psycopg.connect(f.dsn) as observer:
                deadline = time.monotonic() + 3
                blocked = False
                while time.monotonic() < deadline:
                    row = observer.execute("SELECT wait_event_type,query FROM pg_stat_activity WHERE application_name=%s", (application,)).fetchone()
                    if row and row[0] == "Lock" and row[1].startswith("INSERT INTO communication_client_preferences"):
                        blocked = True
                        break
                    time.sleep(0.01)
                assert blocked, "the actual private-source INSERT must wait at its AFTER counter trigger"
            assert read_preferences(getter.cursor(), owner(f)) == {"muted": False, "archived": False, "revision": 1}
        finally:
            getter.commit()
        assert waiting.result(timeout=5)["muted"] is True
    with psycopg.connect(f.dsn) as connection:
        assert sync(connection.cursor(), f) > old_revision
        assert read_preferences(connection.cursor(), owner(f))["muted"] is True


def test_private_delete_recreate_and_repeated_reads_never_reset_revision(versioned):
    f = versioned
    with psycopg.connect(f.dsn) as connection, connection.cursor() as cursor:
        prepare_conversation_write(cursor, owner(f), ADDRESSES["a"], ADDRESSES["b"])
        write_preferences(cursor, owner(f), {"muted": True}, expected_revision=0, client_request_id="first-pref")
    first = current(f)
    assert current(f) == first
    with psycopg.connect(f.dsn) as connection, connection.cursor() as cursor:
        cursor.execute("DELETE FROM communication_client_preferences WHERE tenant_id=%s AND project_id=%s AND actor_ref=%s AND conversation_id=%s", owner(f).values())
    deleted = current(f)
    assert deleted > first
    with psycopg.connect(f.dsn) as connection, connection.cursor() as cursor:
        assert read_preferences(cursor, owner(f))["revision"] == 0
        prepare_conversation_write(cursor, owner(f), ADDRESSES["a"], ADDRESSES["b"])
        write_preferences(cursor, owner(f), {"archived": True}, expected_revision=0, client_request_id="recreated-pref")
    recreated = current(f)
    assert recreated > deleted and current(f) == recreated
    with psycopg.connect(f.dsn) as connection:
        assert connection.execute("SELECT preferences_revision FROM communication_conversation_versions WHERE actor_ref=%s", (owner(f).actor_ref,)).fetchone() == (1,)


def test_source_and_projection_rollback_are_atomic_and_wrong_actor_cannot_replace_owner(versioned):
    f = versioned
    with psycopg.connect(f.dsn) as connection:
        baseline = sync(connection.cursor(), f)
    with psycopg.connect(f.dsn) as connection, connection.cursor() as cursor:
        prepare_conversation_write(cursor, owner(f), ADDRESSES["a"], ADDRESSES["b"])
        write_preferences(cursor, owner(f), {"muted": True}, expected_revision=0, client_request_id="rollback-pref")
        assert sync(cursor, f) > baseline
        connection.rollback()
    with psycopg.connect(f.dsn) as connection:
        assert sync(connection.cursor(), f) == baseline
        assert read_preferences(connection.cursor(), owner(f))["revision"] == 0
    wrong = replace(owner(f), actor_ref="viewer-different-actor")
    for action in (prepare_conversation_write, sync_conversation_view):
        with pytest.raises(SchemaAdoptionError), psycopg.connect(f.dsn) as connection:
            action(connection.cursor(), wrong, ADDRESSES["a"], ADDRESSES["b"])
