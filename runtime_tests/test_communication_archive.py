"""Historical associations are adopted from stored facts, not rewritten as replies."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest

from runtime.communication_archive import adopt_legacy_index, archive_plan
from runtime_tests.test_communication_retirement import retire_tables
from runtime_tests.test_delivery import send as legacy_send
from runtime_tests.test_project_service import project as project_fixture

project = project_fixture
ROOT = Path(__file__).resolve().parents[1]


def seed_legacy(f):
    with psycopg.connect(f.dsn) as connection:
        connection.execute("INSERT INTO collaboration_work_links VALUES (%s,'project-alpha','work','existing-route','{}')",
                           (f.authority.tenant_id,))
    identity, _command, packet, _result = legacy_send(f)
    return identity, packet


def test_operator_dry_run_and_idempotent_adoption_preserve_exact_original_after_task_exit(project):
    f = project
    identity, packet = seed_legacy(f)
    with psycopg.connect(f.dsn) as connection:
        schema = connection.execute("SELECT current_schema()").fetchone()[0]
        before = connection.execute("SELECT packet_json,command_json,canonical_hash FROM delivery_messages WHERE message_id=%s", (identity["message_id"],)).fetchone()
        assert connection.execute("SELECT count(*) FROM communication_archives").fetchone()[0] == 0
    environment = dict(os.environ, ACS_ARCHIVE_INVENTORY_DSN=f.dsn)
    args = [sys.executable, str(ROOT/"scripts/acs_communication_inventory.py"), "--dsn-env", "ACS_ARCHIVE_INVENTORY_DSN",
            "--schema", schema, "--tenant-id", f.authority.tenant_id, "--project-id", "project-alpha"]
    preview = subprocess.run(args, env=environment, capture_output=True, text=True, check=True, timeout=30)
    plan = json.loads(preview.stdout)
    assert plan["mode"] == "dry_run" and plan["known_associations"] == 1
    assert plan["author_slot_unknown"] == 1 and plan["recipient_principal_unknown"] == 1
    with psycopg.connect(f.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM communication_archives").fetchone()[0] == 0
    applied = json.loads(subprocess.run(args+["--apply", "--expected-plan-sha256", plan["plan_sha256"]],
        env=environment, capture_output=True, text=True, check=True, timeout=30).stdout)
    assert applied["indexed_associations"] == 1
    with psycopg.connect(f.dsn) as connection:
        assert adopt_legacy_index(connection.cursor(), f.authority.tenant_id)["indexed_associations"] == 0
        assert connection.execute("SELECT packet_json,command_json,canonical_hash FROM delivery_messages WHERE message_id=%s", (identity["message_id"],)).fetchone() == before
    retire_tables(f)
    reference = "message:project-alpha:"+identity["message_id"]
    read = f.mcp.call("read_message", {"project_id": "project-alpha", "handle": reference})["structuredContent"]
    assert read["ok"] and read["data"]["historical"]
    assert read["data"]["content"] == packet.model_dump(mode="json")
    assert read["data"]["recorded_author"] == {"principal_ref": f.authority.context.principal_ref, "agent_slot_id": None}
    assert read["data"]["recorded_recipient"] == {"agent_slot_id": packet.target_agent_slot_id, "principal_ref": None}
    waited = f.mcp.call("wait_for_response", {"project_id": "project-alpha", "handles": [reference], "timeout_seconds": 0})["structuredContent"]
    assert not waited["ok"] and waited["data"]["field"] == "handles"
    with psycopg.connect(f.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone()[0] == 0


def test_unknown_association_is_not_guessed_and_changed_plan_cannot_apply(project):
    identity, _packet = seed_legacy(project)
    with psycopg.connect(project.dsn) as connection:
        cursor = connection.cursor()
        preview = archive_plan(cursor, project.authority.tenant_id)
        cursor.execute("DELETE FROM collaboration_work_links")
        with pytest.raises(ValueError, match="source changed"):
            adopt_legacy_index(cursor, project.authority.tenant_id, expected_plan_sha256=preview["plan_sha256"])
        current = archive_plan(cursor, project.authority.tenant_id)
        assert current["known_associations"] == 0 and current["tenant_legacy_without_project_association"] == 1
        assert adopt_legacy_index(cursor, project.authority.tenant_id)["indexed_associations"] == 0
        assert connection.execute("SELECT count(*) FROM delivery_messages WHERE message_id=%s", (identity["message_id"],)).fetchone()[0] == 1


def test_conflicting_index_is_reported_without_overwriting_source_or_prior_record(project):
    identity, _packet = seed_legacy(project)
    with psycopg.connect(project.dsn) as connection:
        cursor = connection.cursor()
        adopt_legacy_index(cursor, project.authority.tenant_id)
        cursor.execute("UPDATE communication_archives SET author_principal_ref='conflicting-stored-subject'")
        plan = archive_plan(cursor, project.authority.tenant_id)
        assert plan["conflicting_associations"] == 1
        with pytest.raises(ValueError, match="operator review"):
            adopt_legacy_index(cursor, project.authority.tenant_id)
        assert cursor.execute("SELECT author_principal_ref FROM communication_archives WHERE message_id=%s", (identity["message_id"],)).fetchone()[0] == "conflicting-stored-subject"
