"""Current entry points without the retired task runtime or its tables."""
from __future__ import annotations

import json
import subprocess
import sys

import psycopg
import pytest
from psycopg import sql

from runtime.project_schema_state import ProjectSchemaAdoptionRequired, verify_project_schema
from runtime_tests.test_communication import call, send, wait
from runtime_tests.test_communication import comm as comm_fixture

comm = comm_fixture

LEGACY_TABLES = (
    "work_items", "accepted_state_revisions", "collaboration_work_links", "attempts", "evidence",
    "evidence_bundles", "reviews", "reviewer_assignments", "collaboration_handoffs", "collaboration_review_requests",
    "collaboration_watches", "collaboration_inbox_notifications", "collaboration_response_tracking",
    "collaboration_response_subscriptions", "collaboration_notification_preferences", "collaboration_inbox_consumptions",
    "collaboration_team_budgets", "collaboration_budget_reservations",
)


def retire_tables(f):
    with psycopg.connect(f.dsn) as connection:
        for table in LEGACY_TABLES:
            if connection.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0]:
                connection.execute(sql.SQL("ALTER TABLE {} RENAME TO {}").format(
                    sql.Identifier(table), sql.Identifier("retired_"+table)))


def test_current_service_has_no_task_mutators_or_eager_archive_runtime():
    probe = """
import json,sys
from runtime.project_service import ProjectService
from runtime.domain import DomainAuthority
from runtime.enrollment import EnrollmentAuthority
domain_retired=['create_work_item','transition_work_item','record_evidence','record_review','assign_reviewer',
                'get_work_item','register_attempt','record_execution_receipt','harness_sessions','leases',
                'register_effect','reconcile_effect']
assert not any(hasattr(DomainAuthority,name) for name in domain_retired)
assert not any(hasattr(EnrollmentAuthority,name) for name in ['register_attempt','current_attempt_binding',
                'authorize_execution_receipt','validate_new_execution_receipt','seal_execution_receipt',
                'verify_receipt_provenance'])
retired=['_create_work','_revise_work','_cancel_work','_handoff_work','_acknowledge_handoff',
         '_withdraw_handoff','_request_review','_submit_review','_accept_work','_stop_attempt_external',
         '_watch_changes','_set_notification']
assert not any(hasattr(ProjectService,name) for name in retired)
assert not any(name in sys.modules for name in ['runtime.project_work','runtime.project_inbox',
                'runtime.project_continuation','runtime.project_archive','runtime.recovery_service',
                'runtime.harness_sessions','runtime.lease_authority','runtime.effect_domain','runtime.team_policy'])
print(json.dumps({'retired_mutators':len(retired),'archive_loaded':False}))
"""
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True, timeout=20)
    assert json.loads(result.stdout)["retired_mutators"] == 12


def test_metadata_activity_resource_and_transport_notifications_do_not_need_tasks(comm):
    retire_tables(comm)
    assert comm.clients["a"].call("read_profile", {})["structuredContent"]["ok"]
    call(comm, "a", "list_connections")
    call(comm, "a", "list_routes")
    call(comm, "a", "load_project")
    root = call(comm, "a", "read_resource", handle="project:project-alpha:root")["data"]
    assert root["root_id"] == "root"
    call(comm, "a", "configure_team", prepare_native=False,
         members=[{"agent_slot_id": "slot-b", "principal_ref": "agent:b", "display_name": "Current receiver"}])
    sent = send(comm, activation="message_only")["data"]
    reply = send(comm, "b", "a", "The normal reply is independent of tasks", reply_to=[sent["message_handle"]],
                 activation="message_only")["data"]
    assert call(comm, "a", "read_resource", handle=sent["message_handle"])["data"]["reply"]["message_id"] == reply["message_id"]
    assert wait(comm, "a", sent["message_handle"])["state"] == "satisfied"
    activity = call(comm, "a", "list_activity")["data"]["items"]
    assert sent["message_id"] in {row["target_id"] for row in activity}
    assert reply["message_id"] in {row["target_id"] for row in activity}
    projects = comm.clients["a"].service
    credential = comm.clients["a"].credential_provider()
    projects.bind_notification_session("project-alpha", "transport-session", "transport-connection", credential)
    assert projects.pending_wake_keys("project-alpha", "transport-session", "transport-connection", credential)


def test_activity_never_exposes_another_peers_private_message_even_to_manager(comm):
    private = send(comm, "b", "c", "Private between B and C", activation="message_only")["data"]
    own = send(comm, "a", "b", "Visible to my own identity", activation="message_only")["data"]
    retire_tables(comm)
    rows = call(comm, "a", "list_activity")["data"]["items"]
    assert own["message_id"] in {row["target_id"] for row in rows}
    assert private["message_id"] not in {row["target_id"] for row in rows}
    filtered = call(comm, "a", "list_activity", target_handle=private["message_handle"])["data"]["items"]
    assert filtered == []


def test_unknown_message_and_retired_resource_kinds_do_not_query_task_tables(comm):
    retire_tables(comm)
    result = comm.clients["a"].call("read_message", {"project_id": "project-alpha", "handle": "message:project-alpha:absent"})["structuredContent"]
    assert not result["ok"] and result["data"]["code"] == "not_found"
    for kind in ("work", "handoff", "review", "evidence", "accepted", "attempt"):
        result = comm.clients["a"].call("read_resource", {"project_id": "project-alpha", "handle": kind+":project-alpha:absent"})["structuredContent"]
        assert not result["ok"] and result["data"]["field"] == "handle", result
    result = comm.clients["a"].call("load_project", {"project_id": "project-alpha", "include": ["active_work"]})["structuredContent"]
    assert not result["ok"] and result["data"]["field"] == "include"


def test_startup_checks_current_storage_without_migrating_or_requiring_task_tables(comm):
    retire_tables(comm)
    assert verify_project_schema(comm.authority)
    with psycopg.connect(comm.dsn) as connection:
        connection.execute("DROP TABLE communication_archives")
        connection.execute("DELETE FROM runtime_schema_metadata WHERE schema_name='acs-communication-archives'")
    with pytest.raises(ProjectSchemaAdoptionRequired):
        verify_project_schema(comm.authority)
    with psycopg.connect(comm.dsn) as connection:
        assert connection.execute("SELECT to_regclass('communication_archives')").fetchone()[0] is None


def test_contact_from_an_old_authority_generation_is_not_native_ready_but_can_retain_inbox(comm):
    with psycopg.connect(comm.dsn) as connection:
        connection.execute("INSERT INTO authority_instances(authority_id,authority_incarnation,status) VALUES (%s,'old-generation','revoked')",
                           (comm.authority.context.authority_id,))
        connection.execute("UPDATE grants SET authority_incarnation='old-generation' WHERE grant_ref='grant:b'")
    contact = next(row for row in call(comm, "a", "list_collaborators")["data"]["items"] if row["agent_slot_id"] == "slot-b")
    assert contact["state"] == "inactive"
    rejected = comm.clients["a"].call("send_message", {"project_id": "project-alpha", "to": contact["collaborator_handle"],
                                                       "content": "This must not activate an old identity"})["structuredContent"]
    assert not rejected["ok"] and rejected["data"]["code"] == "target_slot_unavailable"
    assert send(comm, activation="message_only")["data"]["native_status"] == "not_requested"
    assert comm.drivers["b"].calls == []
