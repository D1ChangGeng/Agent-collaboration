"""Local maintenance of actual committed events and metadata caches on PG.

External delivery mode never admits Native work. These tests use disposable
Roots and explicit source intents; no browser, HTTP stream, model or production
contact participates in publication, retention or cache cleanup.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import runtime.communication_dispatch as maintenance
import runtime.communication_event_storage as event_storage
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_client_storage import adopt_client_storage
from runtime.communication_client_viewer_storage import adopt_viewer_storage
from runtime.communication_event_storage import (
    adopt_event_storage,
    maintain_event_publication,
    maintain_event_retention,
    publish_event_intents,
    purge_event_records,
    record_event_intent,
)
from runtime.communication_snapshot_storage import (
    SnapshotIdentity,
    adopt_snapshot_storage,
    prune_snapshot_storage,
    save_snapshot,
    snapshot_filter_digest,
)
from runtime.delivery import DeliveryDispatcher
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send
from runtime_tests.test_identity_root_management import accepted
from runtime_tests.test_identity_root_management import owner_client as owner_client_fixture

comm = comm_fixture
owner_client = owner_client_fixture
PROJECT = "project-alpha"


class NoDatabase:
    _communication_maintenance_mode = "external"

    def __init__(self):
        self._delivery_endpoints = {}

    def _connect(self):
        pytest.fail("disabled maintenance opened a database or attempted adoption")


def test_disabled_and_unadopted_maintenance_is_no_sql_and_claims_no_active_recovery():
    authority = NoDatabase()
    assert maintain_event_publication(authority) == 0
    assert maintain_event_retention(authority) == 0
    assert maintenance.prune_client_snapshots(authority) == 0
    asyncio.run(maintenance.maintain_communication_deliveries(SimpleNamespace(authority=authority)))
    assert not getattr(authority, "_communication_event_maintenance_running", False)
    assert not getattr(authority, "_communication_maintenance_running", False)


@pytest.mark.parametrize("operation,arguments", [
    (maintain_event_publication, {"project_limit": 0}),
    (maintain_event_publication, {"batch_limit": True}),
    (maintain_event_retention, {"project_limit": 65}),
    (maintain_event_retention, {"retention_seconds": False}),
])
def test_maintenance_budgets_fail_before_database_use(operation, arguments):
    authority = NoDatabase()
    authority._communication_event_storage_available = True
    with pytest.raises(ValueError):
        operation(authority, **arguments)


@pytest.fixture
def maintained(comm):
    with comm.authority._connect() as connection:
        adopt_client_storage(connection)
        adopt_viewer_storage(connection)
        adopt_event_storage(connection)
        adopt_snapshot_storage(connection)
    # Previously adopted storage must keep being maintained even when no UI
    # enables or connects to the optional client ingress.
    comm.authority._communication_event_storage_available = True
    comm.authority._communication_snapshot_storage_available = True
    comm.authority._communication_maintenance_mode = "external"
    return comm


def core_history(f):
    tables = ("operations", "outbox", "domain_events", "delivery_messages", "delivery_receipts", "delivery_attempts",
              "communication_messages", "communication_replies", "communication_client_read_state", "communication_client_drafts")
    with f.authority._connect() as connection:
        return {table: connection.execute("SELECT md5(COALESCE(string_agg(to_jsonb(t)::text,',' ORDER BY to_jsonb(t)::text),'')) FROM "
                                          + table + " t").fetchone()[0] for table in tables}


def intent(f, key, *, project=PROJECT):
    # A committed trusted control-plane invalidation, never fabricated content.
    with f.authority._connect() as connection:
        record_event_intent(connection.cursor(), f.authority.tenant_id, project, source_key=key,
            kind="resync.required", resource_ref=None, resource_revision=0, audience_kind="control", payload={"reset_required": True})


def published(f, project=PROJECT):
    with f.authority._connect() as connection:
        row = connection.execute("SELECT high_water,retained_through FROM communication_event_clocks WHERE tenant_id=%s AND project_id=%s",
                                 (f.authority.tenant_id, project)).fetchone()
    return row or (0, 0)


def publish_all(f, project=PROJECT):
    with f.authority._connect() as connection:
        while publish_event_intents(connection, f.authority.tenant_id, project, limit=1000):
            pass


def age_stream(f, *, project=PROJECT):
    with f.authority._connect() as connection:
        connection.execute("UPDATE communication_event_stream SET published_at=clock_timestamp()-interval '8 days' "
                           "WHERE tenant_id=%s AND project_id=%s", (f.authority.tenant_id, project))


def save_cache(f, *, ttl_seconds):
    # Controlled fixture capture: publish committed source intents before the
    # single-writer metadata read and cache save. No UI owns this housekeeping.
    publish_all(f)
    source = f.clients["a"]
    own = CommunicationClientService(source.service, source.credential_provider())
    current = own.event_current(PROJECT)
    identity = SnapshotIdentity(f.authority.tenant_id, PROJECT, current["viewer_key"], current["auth_revision"], snapshot_filter_digest({}))
    projection = {"actor": own.profile(), "notice_count": 0}
    pages = {"contacts": own.contacts(PROJECT)["items"], "conversations": own.conversations(PROJECT)["items"],
             "receivers": own.receivers(PROJECT)["items"]}
    with f.authority._connect() as connection:
        return save_snapshot(connection.cursor(), identity, projection, pages, high_water=published(f)[0], ttl_seconds=ttl_seconds)


def cache_exists(f, reference):
    with f.authority._connect() as connection:
        return connection.execute("SELECT 1 FROM communication_snapshots WHERE snapshot_ref=%s", (reference,)).fetchone() is not None


async def until(predicate, task, *, seconds=6):
    stop = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < stop:
        if task.done():
            await task
            pytest.fail("maintenance exited before its durable work completed")
        if await asyncio.to_thread(predicate):
            return
        await asyncio.sleep(0.025)
    pytest.fail("bounded maintenance did not reach the expected committed state")


def forbid_delivery_and_native(f, monkeypatch):
    monkeypatch.setattr(DeliveryDispatcher, "dispatch", lambda *_args, **_kwargs: pytest.fail("external maintenance dispatched Native work"))
    monkeypatch.setattr(maintenance, "_pending", lambda *_args, **_kwargs: pytest.fail("external maintenance selected delivery work"))
    for endpoint in f.authority._delivery_endpoints.values():
        monkeypatch.setattr(endpoint, "prepare_runtime", lambda: pytest.fail("event maintenance prepared Native runtime"))
        monkeypatch.setattr(endpoint, "inspect_runtime", lambda: pytest.fail("event maintenance inspected Native runtime"))
        monkeypatch.setattr(endpoint, "receiver_snapshot", lambda _binding: pytest.fail("event maintenance probed Native evidence"))


def test_external_loop_publishes_prunes_and_expires_cache_without_dispatch_or_recovery_claim(maintained, monkeypatch):
    f = maintained
    cached = save_cache(f, ttl_seconds=1)
    intent(f, "old-event-before-external-loop")
    publish_all(f)
    age_stream(f)
    message = send(f, activation="invoke")["data"]
    before = core_history(f)
    forbid_delivery_and_native(f, monkeypatch)

    async def exercise():
        task = asyncio.create_task(maintenance.maintain_communication_deliveries(f.clients["a"].service.service))
        try:
            await until(lambda: published(f)[0] > 1 and published(f)[1] == 1 and not cache_exists(f, cached["snapshot_ref"]), task)
            assert f.authority._communication_event_maintenance_running
            assert not f.authority._communication_maintenance_running
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    asyncio.run(exercise())
    assert not f.authority._communication_event_maintenance_running and not f.authority._communication_maintenance_running
    assert core_history(f) == before and not any(driver.calls for driver in f.drivers.values())
    with f.authority._connect() as connection:
        assert connection.execute("SELECT state,attempts FROM delivery_messages WHERE message_id=%s", (message["message_id"],)).fetchone() == ("queued", 0)


def test_publisher_round_robin_serves_later_project_despite_hot_first_project(maintained, owner_client):
    f, other = maintained, "project-maintenance-z"
    accepted(owner_client, "configure_root", project_id=other, client_request_id="maintenance-second-root",
             changes={"name": "Other independent maintenance Root"}, prepare_native=False)
    for number in range(5):
        intent(f, "hot-source-" + str(number))
    intent(f, "cold-source", project=other)
    before = core_history(f)
    assert maintain_event_publication(f.authority, project_limit=1, batch_limit=1) == 1
    assert published(f)[0] == 1 and published(f, other)[0] == 0
    intent(f, "new-hot-source")
    assert maintain_event_publication(f.authority, project_limit=1, batch_limit=1) == 1
    assert published(f)[0] == 1 and published(f, other)[0] == 1
    assert maintain_event_publication(f.authority, project_limit=1, batch_limit=1) == 1
    assert published(f)[0] == 2
    assert core_history(f) == before and not any(driver.calls for driver in f.drivers.values())


@pytest.mark.parametrize("phase", ["publication", "retention"])
def test_failed_first_project_does_not_skip_independent_second_project_in_same_batch(maintained, owner_client, monkeypatch, phase):
    f, other = maintained, "project-maintenance-z"
    accepted(owner_client, "configure_root", project_id=other, client_request_id="maintenance-independent-root",
             changes={"name": "Independent maintenance Root"}, prepare_native=False)
    intent(f, "first-project-failure")
    intent(f, "second-project-progress", project=other)
    if phase == "retention":
        publish_all(f)
        publish_all(f, other)
        age_stream(f)
        age_stream(f, project=other)
    before = core_history(f)
    failures = []
    name = "publish_event_intents" if phase == "publication" else "purge_event_records"
    original = getattr(event_storage, name)

    def first_unavailable(connection, tenant, project, **kwargs):
        if project == PROJECT:
            failures.append(project)
            raise OSError("controlled first-project maintenance failure")
        return original(connection, tenant, project, **kwargs)

    monkeypatch.setattr(event_storage, name, first_unavailable)
    if phase == "publication":
        assert maintain_event_publication(f.authority, project_limit=2) == 1
        assert published(f)[0] == 0 and published(f, other)[0] == 1
    else:
        assert maintain_event_retention(f.authority, project_limit=2) == 1
        assert published(f) == (1, 0) and published(f, other) == (1, 1)
    assert failures == [PROJECT]
    assert core_history(f) == before and not any(driver.calls for driver in f.drivers.values())


def test_retention_is_bounded_and_keeps_published_intent_tombstones(maintained):
    f = maintained
    for number in range(5):
        intent(f, "bounded-old-event-" + str(number))
    publish_all(f)
    age_stream(f)
    before = core_history(f)
    with f.authority._connect() as connection:
        intent_rows = connection.execute("SELECT event_id,published_sequence FROM communication_event_intents ORDER BY intent_id").fetchall()
        cutoff = connection.execute("SELECT clock_timestamp()-interval '7 days'").fetchone()[0]
        assert purge_event_records(connection, f.authority.tenant_id, PROJECT, before=cutoff, limit=2) == (2, 2)
    assert published(f) == (5, 2)
    with f.authority._connect() as connection:
        assert connection.execute("SELECT sequence FROM communication_event_stream ORDER BY sequence").fetchall() == [(3,), (4,), (5,)]
        cutoff = connection.execute("SELECT clock_timestamp()-interval '7 days'").fetchone()[0]
        assert purge_event_records(connection, f.authority.tenant_id, PROJECT, before=cutoff, limit=2) == (2, 4)
        assert purge_event_records(connection, f.authority.tenant_id, PROJECT, before=cutoff, limit=2) == (1, 5)
    intent(f, "bounded-old-event-0")
    assert maintain_event_publication(f.authority) == 0
    with f.authority._connect() as connection:
        assert connection.execute("SELECT event_id,published_sequence FROM communication_event_intents ORDER BY intent_id").fetchall() == intent_rows
    assert published(f) == (5, 5) and core_history(f) == before


def test_default_seven_day_retention_removes_only_the_contiguous_expired_prefix(maintained):
    f = maintained
    for number in range(4):
        intent(f, "age-prefix-" + str(number))
    publish_all(f)
    with f.authority._connect() as connection:
        connection.execute("UPDATE communication_event_stream SET published_at=clock_timestamp()-interval '8 days' WHERE sequence IN (1,3)")
        connection.execute("UPDATE communication_event_stream SET published_at=clock_timestamp()-interval '6 days' WHERE sequence=2")
    assert maintain_event_retention(f.authority, project_limit=1) == 1
    assert published(f) == (4, 1)
    with f.authority._connect() as connection:
        assert connection.execute("SELECT sequence FROM communication_event_stream ORDER BY sequence").fetchall() == [(2,), (3,), (4,)]
    assert maintain_event_retention(f.authority, project_limit=1) == 0


def test_purge_rollback_preserves_caller_transaction_message_history_and_native_count(maintained):
    f = maintained
    send(f, activation="message_only")
    publish_all(f)
    age_stream(f)
    before, boundary = core_history(f), published(f)
    with f.authority._connect() as connection:
        cutoff = connection.execute("SELECT clock_timestamp()").fetchone()[0]
        assert purge_event_records(connection, f.authority.tenant_id, PROJECT, before=cutoff, limit=1)[0] == 1
        connection.rollback()
    assert published(f) == boundary and core_history(f) == before
    assert not any(driver.calls for driver in f.drivers.values())


def test_snapshot_cleanup_prunes_only_expired_cache_and_preserves_caller_rollback(maintained):
    f = maintained
    send(f, activation="message_only")
    current, expired = save_cache(f, ttl_seconds=300), save_cache(f, ttl_seconds=1)
    before = core_history(f)

    async def expires():
        deadline = asyncio.get_running_loop().time() + 4
        while datetime.now(UTC) < datetime.fromisoformat(expired["expires_at"]):
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0.025)

    asyncio.run(expires())
    with f.authority._connect() as connection:
        assert prune_snapshot_storage(connection, tenant_id=f.authority.tenant_id, limit=1) == 1
        connection.rollback()
    assert cache_exists(f, expired["snapshot_ref"])
    assert maintenance.prune_client_snapshots(f.authority) == 1
    assert not cache_exists(f, expired["snapshot_ref"]) and cache_exists(f, current["snapshot_ref"])
    assert core_history(f) == before and not any(driver.calls for driver in f.drivers.values())


def test_publisher_failure_does_not_stop_retention_cleanup_or_independent_source_operations(maintained, monkeypatch):
    f = maintained
    cached = save_cache(f, ttl_seconds=1)
    intent(f, "old-before-publisher-failure")
    publish_all(f)
    age_stream(f)
    failures = []

    def unavailable(_authority):
        failures.append(True)
        raise OSError("controlled local publisher failure")

    monkeypatch.setattr(maintenance, "maintain_event_publication", unavailable)
    forbid_delivery_and_native(f, monkeypatch)

    async def exercise():
        task = asyncio.create_task(maintenance.maintain_communication_deliveries(f.clients["a"].service.service))
        try:
            await until(lambda: bool(failures), task)
            committed = await asyncio.to_thread(send, f, activation="message_only")
            assert committed["ok"]
            await until(lambda: published(f)[1] == 1 and not cache_exists(f, cached["snapshot_ref"]), task)
            assert not task.done() and f.authority._communication_event_maintenance_running
            with f.authority._connect() as connection:
                assert connection.execute("SELECT count(*) FROM communication_messages").fetchone() == (1,)
                assert connection.execute("SELECT count(*) FROM communication_event_intents WHERE published_sequence IS NULL").fetchone()[0] > 0
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    asyncio.run(exercise())
    assert failures and not any(driver.calls for driver in f.drivers.values())
    assert not f.authority._communication_event_maintenance_running and not f.authority._communication_maintenance_running
