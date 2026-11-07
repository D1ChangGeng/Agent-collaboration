"""Snapshot metadata cache boundaries on actual disposable PostgreSQL.

DTO builders below are labeled serializer fixtures, not receiving capabilities
or a live directory. Authorization/consistent source projection is service work.
"""
from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime

import psycopg
import pytest

from runtime.client_contracts import ClientContractViolation
from runtime.communication_snapshot_storage import (
    NAME,
    TABLES,
    SnapshotCorrupt,
    SnapshotExpired,
    SnapshotIdentity,
    SnapshotLimits,
    SnapshotMismatch,
    SnapshotQuotaExceeded,
    adopt_snapshot_storage,
    prune_snapshot_storage,
    read_snapshot,
    read_snapshot_page,
    save_snapshot,
    snapshot_filter_digest,
    verify_snapshot_storage,
)
from runtime.errors import SchemaAdoptionError
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send

comm = comm_fixture
PROJECT = "project-alpha"


def projection():
    return {"actor": {"address": "collaborator:project-alpha:local-slot", "principal_ref": "metadata-fixture",
        "level": "agent", "agent_slot_id": "local-slot", "auth_revision": "fixture-auth", "allowed_actions": []}, "notice_count": 0}


def contact(number):
    return {"address": f"collaborator:{PROJECT}:fixture-{number}", "display_name": f"Metadata contact {number}",
        "agent_slot_id": f"fixture-{number}", "manager_handle": None, "role": None,
        "scope_handles": [], "receiver_refs": [], "is_self": False, "revision": 1}


def pages(number=2):
    return {"contacts": [contact(index) for index in range(number)], "conversations": [], "receivers": []}


def identity(f, **changes):
    selected = SnapshotIdentity(f.authority.tenant_id, PROJECT, "viewer-metadata-fixture", "fixture-auth", snapshot_filter_digest({}))
    return replace(selected, **changes)


@pytest.fixture
def cached(comm):
    with psycopg.connect(comm.dsn) as connection:
        adopt_snapshot_storage(connection)
    return comm


def saved(f, *, ttl_seconds=300, limits=None, count=2):
    with psycopg.connect(f.dsn) as connection:
        return save_snapshot(connection.cursor(), identity(f), projection(), pages(count), high_water=7,
                             ttl_seconds=ttl_seconds, limits=limits)


class NoDatabase:
    @property
    def connection(self):
        raise AssertionError("invalid metadata must fail before database use")


def test_filter_digest_is_canonical_and_snapshot_limits_are_explicit():
    assert snapshot_filter_digest({"peer": "address", "archived": False}) == snapshot_filter_digest({"archived": False, "peer": "address"})
    assert snapshot_filter_digest({}) != snapshot_filter_digest({"peer": "address"})
    for invalid in ([], "filters", None):
        with pytest.raises(ValueError):
            snapshot_filter_digest(invalid)
    for changes in ({"max_items": 0}, {"max_items": True}, {"max_bytes": 2**30}, {"max_snapshots_per_viewer": 1001}):
        with pytest.raises(ValueError):
            SnapshotLimits(**changes)


@pytest.mark.parametrize("field,value", [("tenant_id", ""), ("project_id", " "), ("viewer_key", "x" * 513),
    ("auth_revision", None), ("filter_digest", "not-a-hash")])
def test_identity_requires_explicit_bounded_owner_auth_and_filter(field, value):
    fields = {"tenant_id": "t", "project_id": "p", "viewer_key": "v", "auth_revision": "a", "filter_digest": snapshot_filter_digest({})}
    fields[field] = value
    with pytest.raises(ValueError):
        SnapshotIdentity(**fields)


@pytest.mark.parametrize("family", ["messages", "drafts", "transcripts"])
def test_message_draft_and_transcript_families_cannot_enter_cache(family):
    data = pages(0) | {family: [{"content": "Private body"}]}
    with pytest.raises(ValueError):
        save_snapshot(NoDatabase(), SnapshotIdentity("t", "p", "v", "a", snapshot_filter_digest({})), projection(), data, high_water=0)


def test_unknown_body_fields_and_incomplete_families_fail_before_writes():
    owner = SnapshotIdentity("t", "p", "v", "a", snapshot_filter_digest({}))
    invalid = pages(1)
    invalid["contacts"][0]["content"] = "Message body is not contact metadata"
    with pytest.raises(ClientContractViolation):
        save_snapshot(NoDatabase(), owner, projection(), invalid, high_water=0)
    with pytest.raises(ValueError):
        save_snapshot(NoDatabase(), owner, projection(), {"contacts": []}, high_water=0)
    with pytest.raises(ValueError):
        save_snapshot(NoDatabase(), owner, projection() | {"draft": "private"}, pages(0), high_water=0)


@pytest.mark.parametrize("limits,data", [(SnapshotLimits(max_items=1), pages(2)), (SnapshotLimits(max_bytes=1), pages(0))])
def test_oversized_snapshot_is_explicitly_rejected_before_storage(limits, data):
    with pytest.raises(SnapshotQuotaExceeded):
        save_snapshot(NoDatabase(), SnapshotIdentity("t", "p", "v", "a", snapshot_filter_digest({})),
                      projection(), data, high_water=0, limits=limits)


def test_missing_adoption_verify_is_read_only_and_base_remains_valid(comm):
    with psycopg.connect(comm.dsn) as connection:
        before = connection.execute("SELECT * FROM runtime_schema_metadata ORDER BY schema_name").fetchall()
        with pytest.raises(SchemaAdoptionError):
            verify_snapshot_storage(connection)
        assert connection.execute("SELECT * FROM runtime_schema_metadata ORDER BY schema_name").fetchall() == before
        assert all(connection.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0] is None for table in TABLES)
    assert send(comm, activation="message_only")["ok"]


def test_adoption_and_verification_are_idempotent_without_cache_writes(cached):
    meta = saved(cached)
    with psycopg.connect(cached.dsn) as connection:
        before = {table: connection.execute("SELECT to_jsonb(s) FROM " + table + " s ORDER BY to_jsonb(s)::text").fetchall() for table in TABLES}
        schema = connection.execute("SELECT * FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone()
        verify_snapshot_storage(connection)
        adopt_snapshot_storage(connection)
        assert read_snapshot(connection.cursor(), identity(cached), meta["snapshot_ref"]) == meta
        assert {table: connection.execute("SELECT to_jsonb(s) FROM " + table + " s ORDER BY to_jsonb(s)::text").fetchall() for table in TABLES} == before
        assert connection.execute("SELECT * FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone() == schema


@pytest.mark.parametrize("damage", ["column", "key", "index", "trigger", "function", "hash_check"])
def test_damaged_schema_refuses_startup_and_is_not_silently_repaired(cached, damage):
    with psycopg.connect(cached.dsn) as connection:
        if damage == "column":
            connection.execute("ALTER TABLE communication_snapshot_items DROP COLUMN resource_digest")
        elif damage == "key":
            connection.execute("ALTER TABLE communication_snapshot_items DROP CONSTRAINT communication_snapshot_items_pkey")
        elif damage == "index":
            connection.execute("DROP INDEX communication_snapshots_owner")
        elif damage == "trigger":
            connection.execute("ALTER TABLE communication_snapshots DISABLE TRIGGER acs_communication_snapshot_header_immutable")
        elif damage == "function":
            connection.execute("ALTER FUNCTION acs_communication_snapshot_immutable() SECURITY DEFINER")
        else:
            connection.execute("ALTER TABLE communication_snapshot_items DROP CONSTRAINT snapshot_item_hash")
    for action in (verify_snapshot_storage, adopt_snapshot_storage):
        with psycopg.connect(cached.dsn) as connection, pytest.raises(SchemaAdoptionError):
            action(connection)


def test_snapshot_freezes_full_metadata_with_stable_pages_beyond_first_hundred(cached):
    original, data = projection(), pages(235)
    with psycopg.connect(cached.dsn) as connection:
        meta = save_snapshot(connection.cursor(), identity(cached), original, data, high_water=123)
    assert meta["counts"] == {"contacts": 235, "conversations": 0, "receivers": 0}
    assert datetime.fromisoformat(meta["expires_at"]).tzinfo is not None
    original["notice_count"], data["contacts"][0]["display_name"] = 99, "Later live metadata"
    observed, offset = [], 0
    with psycopg.connect(cached.dsn) as connection:
        while offset is not None:
            page = read_snapshot_page(connection.cursor(), identity(cached), meta["snapshot_ref"], "contacts", offset=offset, limit=100)
            observed.extend(page["items"])
            offset = page["next_offset"]
        assert read_snapshot(connection.cursor(), identity(cached), meta["snapshot_ref"])["projection"]["notice_count"] == 0
        assert read_snapshot_page(connection.cursor(), identity(cached), meta["snapshot_ref"], "receivers")["items"] == []
    assert observed == pages(235)["contacts"]
    assert len(observed) == 235 and meta["high_water"] == 123


def test_three_typed_metadata_families_share_one_frozen_high_water(cached):
    data = pages(1)
    data["conversations"] = [{"conversation_id": "conversation-fixture", "project_id": PROJECT,
        "participants": ["collaborator:project-alpha:local-slot", "collaborator:project-alpha:fixture-peer"],
        "last_message_handle": None, "last_activity_at": None, "unread_count": 0,
        "revision": 0, "archived": False, "muted": False}]
    data["receivers"] = [{"receiver_id": "fixture-receiver", "address": "collaborator:project-alpha:fixture-peer",
        "binding_epoch": 0, "revision": 0, "native_session_ref": None,
        "capability_scope": {"adapter_id": "fixture-adapter", "adapter_version": "fixture", "harness_kind": "fixture",
            "harness_version": None, "execution_host_ref": "fixture-host", "binary_digest": None,
            "config_digest": None, "connection_epoch": 0, "provider_generation": None},
        "capabilities": [], "observations": [], "allowed_actions": []}]
    with psycopg.connect(cached.dsn) as connection:
        meta = save_snapshot(connection.cursor(), identity(cached), projection(), data, high_water=99)
        for family in data:
            assert read_snapshot_page(connection.cursor(), identity(cached), meta["snapshot_ref"], family)["items"] == data[family]
        assert meta["counts"] == {"contacts": 1, "conversations": 1, "receivers": 1}
        assert meta["high_water"] == 99


@pytest.mark.parametrize("change", [{"tenant_id": "other-tenant"}, {"project_id": "other-project"}, {"viewer_key": "other-viewer"},
                                   {"auth_revision": "renewed-auth"}, {"filter_digest": snapshot_filter_digest({"archived": True})}])
def test_snapshot_ref_cannot_cross_owner_auth_or_filters(cached, change):
    meta = saved(cached)
    with psycopg.connect(cached.dsn) as connection, pytest.raises(SnapshotMismatch):
        read_snapshot_page(connection.cursor(), identity(cached, **change), meta["snapshot_ref"], "contacts")


def test_snapshot_ref_is_random_and_exact_reads_do_not_change_cache(cached):
    first, second = saved(cached), saved(cached)
    assert first["snapshot_ref"] != second["snapshot_ref"]
    assert len(first["snapshot_ref"]) <= 512
    with psycopg.connect(cached.dsn) as connection:
        generation = connection.execute("SELECT generation FROM communication_snapshot_scopes WHERE tenant_id=%s AND project_id=%s", (cached.authority.tenant_id, PROJECT)).fetchone()[0]
        for _index in range(3):
            assert read_snapshot(connection.cursor(), identity(cached), first["snapshot_ref"]) == first
        assert connection.execute("SELECT generation FROM communication_snapshot_scopes WHERE tenant_id=%s AND project_id=%s", (cached.authority.tenant_id, PROJECT)).fetchone()[0] == generation


def test_row_immutability_and_hashes_reject_metadata_tampering(cached):
    meta = saved(cached)
    with psycopg.connect(cached.dsn) as connection:
        with pytest.raises(psycopg.errors.RaiseException, match="immutable_communication_snapshot"), connection.transaction():
            connection.execute("UPDATE communication_snapshots SET high_water=high_water+1 WHERE snapshot_ref=%s", (meta["snapshot_ref"],))
        connection.execute("ALTER TABLE communication_snapshot_items DISABLE TRIGGER acs_communication_snapshot_item_immutable")
        connection.execute("UPDATE communication_snapshot_items SET resource_json=jsonb_set(resource_json,'{display_name}','\"Tampered metadata\"') WHERE snapshot_ref=%s AND item_index=0", (meta["snapshot_ref"],))
        connection.execute("ALTER TABLE communication_snapshot_items ENABLE TRIGGER acs_communication_snapshot_item_immutable")
    with psycopg.connect(cached.dsn) as connection, pytest.raises(SnapshotCorrupt):
        read_snapshot_page(connection.cursor(), identity(cached), meta["snapshot_ref"], "contacts")


def test_missing_page_item_is_an_integrity_failure_not_false_completion(cached):
    meta = saved(cached)
    with psycopg.connect(cached.dsn) as connection:
        connection.execute("DELETE FROM communication_snapshot_items WHERE snapshot_ref=%s AND item_index=0", (meta["snapshot_ref"],))
    with psycopg.connect(cached.dsn) as connection, pytest.raises(SnapshotCorrupt):
        read_snapshot_page(connection.cursor(), identity(cached), meta["snapshot_ref"], "contacts")
    with psycopg.connect(cached.dsn) as connection, pytest.raises(SchemaAdoptionError):
        verify_snapshot_storage(connection)


def test_quota_rejection_is_atomic_and_keeps_existing_snapshot(cached):
    limits = SnapshotLimits(max_snapshots_per_viewer=1)
    with psycopg.connect(cached.dsn) as connection:
        first = save_snapshot(connection.cursor(), identity(cached), projection(), pages(), high_water=1, limits=limits)
        before = connection.execute("SELECT generation FROM communication_snapshot_scopes WHERE tenant_id=%s AND project_id=%s", (cached.authority.tenant_id, PROJECT)).fetchone()[0]
        with pytest.raises(SnapshotQuotaExceeded):
            save_snapshot(connection.cursor(), identity(cached), projection(), pages(), high_water=2, limits=limits)
        assert connection.execute("SELECT count(*) FROM communication_snapshots").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM communication_snapshot_items").fetchone()[0] == 2
        assert connection.execute("SELECT generation FROM communication_snapshot_scopes WHERE tenant_id=%s AND project_id=%s", (cached.authority.tenant_id, PROJECT)).fetchone()[0] == before
        assert read_snapshot(connection.cursor(), identity(cached), first["snapshot_ref"]) == first


@pytest.mark.parametrize("dimension", ["project_count", "viewer_bytes", "project_bytes"])
def test_project_and_viewer_storage_budgets_are_enforced_across_captures(cached, dimension):
    first = saved(cached)
    with psycopg.connect(cached.dsn) as connection:
        size = connection.execute("SELECT total_bytes FROM communication_snapshots WHERE snapshot_ref=%s", (first["snapshot_ref"],)).fetchone()[0]
        if dimension == "project_count":
            limits = SnapshotLimits(max_snapshots_per_project=1)
        elif dimension == "viewer_bytes":
            limits = SnapshotLimits(max_bytes_per_viewer=size)
        else:
            limits = SnapshotLimits(max_bytes_per_project=size)
        selected = identity(cached, viewer_key="second-viewer") if dimension.startswith("project") else identity(cached)
        with pytest.raises(SnapshotQuotaExceeded):
            save_snapshot(connection.cursor(), selected, projection(), pages(), high_water=1, limits=limits)
        assert connection.execute("SELECT count(*) FROM communication_snapshots").fetchone()[0] == 1


def test_repeatable_read_concurrent_quota_admission_requires_fresh_transaction(cached):
    limits = SnapshotLimits(max_snapshots_per_viewer=1)
    with psycopg.connect(cached.dsn) as first, psycopg.connect(cached.dsn) as stale:
        for connection in (first, stale):
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            assert connection.execute("SELECT count(*) FROM communication_snapshots").fetchone()[0] == 0
        save_snapshot(first.cursor(), identity(cached), projection(), pages(), high_water=1, limits=limits)
        first.commit()
        with pytest.raises(psycopg.errors.SerializationFailure):
            save_snapshot(stale.cursor(), identity(cached), projection(), pages(), high_water=2, limits=limits)
        stale.rollback()
        with pytest.raises(SnapshotQuotaExceeded):
            save_snapshot(stale.cursor(), identity(cached), projection(), pages(), high_water=2, limits=limits)
    with psycopg.connect(cached.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM communication_snapshots").fetchone()[0] == 1


def test_outer_transaction_rollback_removes_entire_snapshot(cached):
    with psycopg.connect(cached.dsn) as connection:
        meta = save_snapshot(connection.cursor(), identity(cached), projection(), pages(), high_water=1)
        connection.rollback()
    with psycopg.connect(cached.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM communication_snapshots").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM communication_snapshot_items").fetchone()[0] == 0
        with pytest.raises(SnapshotExpired):
            read_snapshot(connection.cursor(), identity(cached), meta["snapshot_ref"])


def test_ttl_and_bounded_pruning_delete_cache_only_preserving_authority_history(cached):
    original = send(cached, content="Authority history survives snapshot cleanup", activation="message_only")["data"]
    expired = [saved(cached, ttl_seconds=1), saved(cached, ttl_seconds=1)]
    live = saved(cached)
    with psycopg.connect(cached.dsn) as connection:
        source = connection.execute("SELECT packet_json FROM delivery_messages WHERE message_id=%s", (original["message_id"],)).fetchone()[0]
    time.sleep(1.1)
    with psycopg.connect(cached.dsn) as connection:
        with pytest.raises(SnapshotExpired):
            read_snapshot(connection.cursor(), identity(cached), expired[0]["snapshot_ref"])
        assert prune_snapshot_storage(connection, tenant_id=cached.authority.tenant_id, project_id=PROJECT, limit=1) == 1
        assert connection.execute("SELECT count(*) FROM communication_snapshots").fetchone()[0] == 2
        assert prune_snapshot_storage(connection, tenant_id=cached.authority.tenant_id, project_id=PROJECT, limit=1) == 1
        assert prune_snapshot_storage(connection, limit=1) == 0
        assert read_snapshot(connection.cursor(), identity(cached), live["snapshot_ref"]) == live
        assert connection.execute("SELECT packet_json FROM delivery_messages WHERE message_id=%s", (original["message_id"],)).fetchone()[0] == source
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone()[0] == 1


def test_invalid_ttl_and_page_budget_are_rejected_without_partial_cache(cached):
    with psycopg.connect(cached.dsn) as connection:
        for ttl in (0, 301, True):
            with pytest.raises(ValueError):
                save_snapshot(connection.cursor(), identity(cached), projection(), pages(), high_water=0, ttl_seconds=ttl)
        meta = save_snapshot(connection.cursor(), identity(cached), projection(), pages(), high_water=0)
        for params in ({"offset": -1}, {"limit": 0}, {"limit": 101}):
            with pytest.raises(ValueError):
                read_snapshot_page(connection.cursor(), identity(cached), meta["snapshot_ref"], "contacts", **params)
        with pytest.raises(ValueError):
            read_snapshot_page(connection.cursor(), identity(cached), meta["snapshot_ref"], "messages")
        assert connection.execute("SELECT count(*) FROM communication_snapshots").fetchone()[0] == 1
