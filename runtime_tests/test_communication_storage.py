"""Fresh taskless storage and additive adoption, using real disposable PostgreSQL."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from runtime.communication_storage import CORE_NAME, adopt_core
from runtime.domain import DomainAuthority
from runtime.errors import SchemaAdoptionError
from runtime.project_schema_state import ProjectSchemaAdoptionRequired, verify_project_schema
from runtime_tests.test_communication import call, send, wait
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_archive import seed_legacy
from runtime_tests.test_project_service import project as project_fixture

comm = comm_fixture
project = project_fixture
RETIRED = {
    "work_items", "attempts", "accepted_state_revisions", "leases", "effects", "evidence", "artifacts",
    "execution_receipts", "evidence_bundles", "reviews", "reviewer_assignments", "work_item_revisions",
    "native_response_observations", "native_response_consumptions", "recovery_incidents", "recovery_path_attempts",
    "human_bridge_requests", "recovery_reprobes", "human_bridge_packets", "human_bridge_normal_receipts",
    "recovery_audit_events", "recovery_command_claims", "harness_session_heads", "harness_session_bindings",
    "harness_session_result_admissions", "collaboration_work_links", "collaboration_response_tracking",
    "collaboration_response_subscriptions", "collaboration_team_budgets", "collaboration_budget_reservations",
    "collaboration_review_requests", "collaboration_inbox_consumptions", "collaboration_watches",
    "collaboration_inbox_notifications", "collaboration_watch_observations", "collaboration_handoffs",
}


def dataset(connection):
    names = [row[0] for row in connection.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() ORDER BY tablename")]
    data = {}
    for name in names:
        if name == "runtime_schema_metadata":
            continue
        rows = connection.execute(sql.SQL("SELECT to_jsonb(t) FROM {} t ORDER BY to_jsonb(t)::text").format(sql.Identifier(name))).fetchall()
        data[name] = [hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                      for row in rows]
    return data


def old_metadata(connection):
    # The historical fixture creates the exact old 1.13/project-1 tables. Only
    # metadata differs after its current adapter has explicitly adopted them.
    connection.execute("DELETE FROM runtime_schema_metadata WHERE schema_name=%s", (CORE_NAME,))
    source = Path(__file__).with_name("fixtures") / "legacy_project_schema.sql"
    checksum = hashlib.sha256(source.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    connection.execute("UPDATE runtime_schema_metadata SET schema_version='1',schema_checksum=%s "
                       "WHERE schema_name='acs-project-runtime'", (checksum,))


def test_fresh_default_never_creates_retired_tables_and_real_delivery_still_works(comm, tmp_path):
    with psycopg.connect(comm.dsn) as connection:
        tables = {row[0] for row in connection.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema()")}
        assert not tables.intersection(RETIRED)
        assert {"delivery_attempts", "delivery_receipts", "command_dedup", "inbox_messages", "enrolled_runtimes"} <= tables
        assert connection.execute("SELECT schema_version FROM runtime_schema_metadata WHERE schema_name=%s", (CORE_NAME,)).fetchone() == ("1",)
        assert connection.execute("SELECT schema_version FROM runtime_schema_metadata WHERE schema_name='acs-project-runtime'").fetchone() == ("2",)
        assert connection.execute("SELECT 1 FROM runtime_schema_metadata WHERE schema_name='acs-p1-runtime'").fetchone() is None
    request = send(comm)["data"]
    assert comm.dispatcher.dispatch({"tenant_id": comm.authority.tenant_id,
        "message_id": request["message_id"], "operation_id": request["operation_id"]})["status"] == "delivered"
    original = call(comm, "b", "read_message", handle=request["message_handle"])["data"]
    send(comm, "b", "a", "The fresh store can receive and reply", reply_to=[request["message_handle"]], activation="message_only")
    assert wait(comm, "a", request["message_handle"])["state"] == "satisfied"
    assert verify_project_schema(comm.authority)
    # Explicit repeated adoption must neither duplicate records nor resurrect
    # retired tables. Startup validation above performs no adoption.
    with psycopg.connect(comm.dsn) as connection:
        before = dataset(connection)
    comm.authority.initialize()
    comm.clients["a"].service.initialize()
    with psycopg.connect(comm.dsn) as connection:
        assert dataset(connection) == before
    (tmp_path / "fresh-storage-facts.json").write_text(json.dumps({"tables": sorted(tables), "table_count": len(tables),
        "retired_tables_present": [], "original_content": original["content"], "native_fixture_calls": len(comm.drivers["b"].calls),
        "model_requested": False}, indent=2), encoding="utf-8")


def test_explicit_known_legacy_adoption_preserves_every_stored_row_and_history(project):
    identity, packet = seed_legacy(project)
    with psycopg.connect(project.dsn) as connection:
        old_metadata(connection)
        before = dataset(connection)
        old_core = connection.execute("SELECT * FROM runtime_schema_metadata WHERE schema_name='acs-p1-runtime'").fetchone()
    with pytest.raises(ProjectSchemaAdoptionRequired):
        verify_project_schema(project.authority)
    # Current production class, not the historical fixture's initialize method.
    current = DomainAuthority(project.dsn, context=project.authority.context)
    current.initialize()
    project.projects.initialize()
    assert verify_project_schema(current)
    with psycopg.connect(project.dsn) as connection:
        after = dataset(connection)
        for table, rows in before.items():
            if table == "communication_archives":
                # Explicit adoption may append the packet's derived association;
                # it must preserve each original row in this index as well.
                assert set(rows) <= set(after[table]) and len(after[table]) == len(rows) + 1
            else:
                assert after[table] == rows, table
        assert connection.execute("SELECT * FROM runtime_schema_metadata WHERE schema_name='acs-p1-runtime'").fetchone() == old_core
        assert connection.execute("SELECT packet_json FROM delivery_messages WHERE message_id=%s", (identity["message_id"],)).fetchone()[0] == packet.model_dump(mode="json")


def test_unknown_legacy_checksum_is_rejected_before_ddl_or_identity_changes(project):
    with psycopg.connect(project.dsn) as connection:
        old_metadata(connection)
        connection.execute("UPDATE runtime_schema_metadata SET schema_checksum=%s WHERE schema_name='acs-p1-runtime'", ("f" * 64,))
        before = dataset(connection)
        metadata = connection.execute("SELECT * FROM runtime_schema_metadata ORDER BY schema_name").fetchall()
    with pytest.raises(SchemaAdoptionError):
        DomainAuthority(project.dsn, context=project.authority.context).initialize()
    with psycopg.connect(project.dsn) as connection:
        assert dataset(connection) == before
        assert connection.execute("SELECT * FROM runtime_schema_metadata ORDER BY schema_name").fetchall() == metadata


def test_missing_adoption_at_startup_is_read_only_and_unversioned_storage_is_not_guessed(comm):
    with psycopg.connect(comm.dsn) as connection:
        connection.execute("DELETE FROM runtime_schema_metadata WHERE schema_name=%s", (CORE_NAME,))
        before = dataset(connection)
    with pytest.raises(ProjectSchemaAdoptionRequired):
        verify_project_schema(comm.authority)
    with psycopg.connect(comm.dsn) as connection, pytest.raises(SchemaAdoptionError):
        adopt_core(connection)
    with psycopg.connect(comm.dsn) as connection:
        assert dataset(connection) == before
        assert connection.execute("SELECT 1 FROM runtime_schema_metadata WHERE schema_name=%s", (CORE_NAME,)).fetchone() is None


@pytest.mark.parametrize("relation", ["command_dedup", "collaboration_commands"])
def test_adoption_does_not_recreate_a_missing_authoritative_ledger(comm, relation):
    with psycopg.connect(comm.dsn) as connection:
        connection.execute(sql.SQL("ALTER TABLE {} RENAME TO {}").format(
            sql.Identifier(relation), sql.Identifier("retained_" + relation)))
    with pytest.raises((SchemaAdoptionError, ValueError)):
        comm.clients["a"].service.initialize()
    with psycopg.connect(comm.dsn) as connection:
        assert connection.execute("SELECT to_regclass(%s)", (relation,)).fetchone()[0] is None
        assert connection.execute("SELECT to_regclass(%s)", ("retained_" + relation,)).fetchone()[0] is not None


def test_adoption_cli_is_read_only_by_default_and_binds_apply_to_the_preview(project):
    identity, packet = seed_legacy(project)
    with psycopg.connect(project.dsn) as connection:
        old_metadata(connection)
        schema = connection.execute("SELECT current_schema()").fetchone()[0]
        before = dataset(connection)
        metadata = connection.execute("SELECT * FROM runtime_schema_metadata ORDER BY schema_name").fetchall()
    script = Path(__file__).resolve().parents[1] / "scripts/acs_communication_adopt.py"
    args = [sys.executable, str(script), "--dsn-env", "ACS_STORAGE_ADOPTION_DSN", "--schema", schema]
    env = dict(os.environ, ACS_STORAGE_ADOPTION_DSN=project.dsn)
    preview = json.loads(subprocess.run(args, env=env, capture_output=True, text=True, timeout=30, check=True).stdout)
    assert preview["mode"] == "dry_run" and preview["data_cleanup"] == "none" and not preview["native_started"]
    with psycopg.connect(project.dsn) as connection:
        assert dataset(connection) == before
        assert connection.execute("SELECT * FROM runtime_schema_metadata ORDER BY schema_name").fetchall() == metadata
    wrong = subprocess.run([*args, "--apply", "--expected-plan-sha256", "0" * 64], env=env, capture_output=True, timeout=30, check=False)
    assert wrong.returncode == 2
    applied = json.loads(subprocess.run([*args, "--apply", "--expected-plan-sha256", preview["plan_sha256"]],
                                       env=env, capture_output=True, text=True, timeout=30, check=True).stdout)
    assert applied["mode"] == "applied" and applied["identity_bootstrap"] == "unchanged"
    with psycopg.connect(project.dsn) as connection:
        assert dataset(connection) == before
        assert connection.execute("SELECT packet_json FROM delivery_messages WHERE message_id=%s", (identity["message_id"],)).fetchone()[0] == packet.model_dump(mode="json")
    assert verify_project_schema(project.authority)


def test_missing_native_fence_blocks_startup_and_is_not_silently_repaired(comm):
    with psycopg.connect(comm.dsn) as connection:
        connection.execute("DROP INDEX delivery_attempts_one_open")
        before = dataset(connection)
    with pytest.raises(ProjectSchemaAdoptionRequired):
        verify_project_schema(comm.authority)
    with pytest.raises(SchemaAdoptionError, match="missing_or_invalid_fence"):
        comm.authority.initialize()
    with psycopg.connect(comm.dsn) as connection:
        assert connection.execute("SELECT to_regclass('delivery_attempts_one_open')").fetchone()[0] is None
        assert dataset(connection) == before
