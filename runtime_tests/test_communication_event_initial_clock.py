"""First-publication replay race on an actually admitted empty project.

The cursor always returns actual PostgreSQL results. Its first missing-clock
fetch schedules separate source, publisher and prefix-retention transactions.
Generic control intents here are synthetic registry fixtures, not permission or
Native observations from a deployment.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import psycopg
import pytest

from runtime.communication_client_storage import adopt_client_storage
from runtime.communication_event_storage import (
    EventCursorExpired,
    adopt_event_storage,
    publish_event_intents,
    purge_event_records,
    read_event_records,
    record_event_intent,
    stream_high_water,
)
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_identity_root_management import owner_client as owner_client_fixture

comm = comm_fixture
owner_client = owner_client_fixture


@pytest.fixture
def cold(comm, owner_client):
    with psycopg.connect(comm.dsn) as connection:
        adopt_client_storage(connection)
        adopt_event_storage(connection)
    project = "event-cold-" + uuid.uuid4().hex
    admitted = owner_client.call("configure_root", {"project_id": project,
        "client_request_id": "configure-" + project, "changes": {"name": "First publication race"}})["structuredContent"]
    assert admitted["ok"], admitted
    with psycopg.connect(comm.dsn) as connection:
        assert connection.execute("SELECT 1 FROM communication_event_clocks WHERE tenant_id=%s AND project_id=%s",
                                  (comm.authority.tenant_id, project)).fetchone() is None
    return SimpleNamespace(f=comm, tenant=comm.authority.tenant_id, project=project)


class ObservedCursor:
    def __init__(self, cursor, on_missing_clock=None):
        self.cursor, self.on_missing_clock = cursor, on_missing_clock
        self.queries, self.missing = [], 0
        self.clock_query = False

    def execute(self, query, args=None):
        self.queries.append(query)
        self.clock_query = query.startswith("SELECT high_water,retained_through FROM communication_event_clocks")
        return self.cursor.execute(query, args)

    def fetchone(self):
        row = self.cursor.fetchone()
        if self.clock_query and row is None:
            self.missing += 1
            if self.on_missing_clock is not None:
                callback, self.on_missing_clock = self.on_missing_clock, None
                callback()
        return row

    def fetchall(self):
        return self.cursor.fetchall()


def test_missing_initial_clock_linearizes_before_publish_and_prefix_purge(cold):
    interleaving = []

    def publish_then_purge():
        with psycopg.connect(cold.f.dsn) as source, source.cursor() as cursor:
            for number in (1, 2):
                record_event_intent(cursor, cold.tenant, cold.project,
                    source_key=f"synthetic-control-{number}", kind="permission.changed", resource_ref=None,
                    resource_revision=0, audience_kind="control",
                    payload={"reason_code": "synthetic-registry-fixture", "reset_required": True})
        with psycopg.connect(cold.f.dsn) as publisher:
            assert publish_event_intents(publisher, cold.tenant, cold.project) == 2
            events = read_event_records(publisher.cursor(), cold.tenant, cold.project, after=0)
            assert [event["sequence"] for event in events] == [1, 2]
        assert events[0]["published_at"] < events[1]["published_at"]
        with psycopg.connect(cold.f.dsn) as purger:
            assert purge_event_records(purger, cold.tenant, cold.project,
                                       before=events[1]["published_at"]) == (1, 1)
        interleaving.extend(events)

    with psycopg.connect(cold.f.dsn) as reader, reader.cursor() as cursor:
        observed = ObservedCursor(cursor, publish_then_purge)
        assert read_event_records(observed, cold.tenant, cold.project, after=0) == []
        assert observed.missing == 1 and len(interleaving) == 2
        assert all(query.lstrip().startswith("SELECT ") for query in observed.queries)
    with psycopg.connect(cold.f.dsn) as fresh:
        with pytest.raises(EventCursorExpired) as expired:
            read_event_records(fresh.cursor(), cold.tenant, cold.project, after=0)
        assert expired.value.code == "cursor_expired"
        tail = read_event_records(fresh.cursor(), cold.tenant, cold.project, after=1)
        assert len(tail) == 1 and tail[0]["event_id"] == interleaving[1]["event_id"]
        assert tail[0]["sequence"] == 2
    assert all(not driver.calls for driver in cold.f.drivers.values())


def test_nonzero_position_on_missing_clock_is_ahead_and_does_not_create_clock(cold):
    with psycopg.connect(cold.f.dsn) as connection, connection.cursor() as cursor:
        observed = ObservedCursor(cursor)
        with pytest.raises(ValueError, match="ahead"):
            read_event_records(observed, cold.tenant, cold.project, after=1)
        assert observed.missing == 1
        assert all(query.lstrip().startswith("SELECT ") for query in observed.queries)
        assert connection.execute("SELECT 1 FROM communication_event_clocks WHERE tenant_id=%s AND project_id=%s",
                                  (cold.tenant, cold.project)).fetchone() is None


def test_empty_replay_reads_never_materialize_storage_or_write_a_clock(cold):
    with psycopg.connect(cold.f.dsn) as connection, connection.cursor() as cursor:
        before = connection.execute("SELECT * FROM runtime_schema_metadata ORDER BY schema_name").fetchall()
        observed = ObservedCursor(cursor)
        assert read_event_records(observed, cold.tenant, cold.project, after=0) == []
        assert stream_high_water(observed, cold.tenant, cold.project) == 0
        assert all(query.lstrip().startswith("SELECT ") for query in observed.queries)
        assert connection.execute("SELECT * FROM runtime_schema_metadata ORDER BY schema_name").fetchall() == before
        assert connection.execute("SELECT 1 FROM communication_event_clocks WHERE tenant_id=%s AND project_id=%s",
                                  (cold.tenant, cold.project)).fetchone() is None
        assert connection.execute("SELECT count(*) FROM communication_event_stream WHERE tenant_id=%s AND project_id=%s",
                                  (cold.tenant, cold.project)).fetchone()[0] == 0
