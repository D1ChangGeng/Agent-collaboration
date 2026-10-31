"""Caller waiting, business expiry and discovery transaction regressions."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import anyio
import psycopg

from runtime import project_service as module
from runtime.mcp_runtime import McpRuntime
from runtime.project_service import ProjectService
from runtime_tests.test_project_service import (
    CATALOG,
    ok,
    scalar,
    send_args,
    work_args,
)
from runtime_tests.test_project_service import (
    project as project_fixture,
)

project = project_fixture

def observation(*, complete=False, state="queued"):
    return {"response_handle": "response:project-alpha:message-one", "state": state,
            "receipts": [("response_received", {})] if complete else []}


def wait_service(monkeypatch, *, complete_after=90, state="queued"):
    elapsed = [0.0]
    service = ProjectService.__new__(ProjectService)
    service.execute = lambda *_args: ("observed", observation(
        complete=elapsed[0] >= complete_after, state=state), [])
    clock = SimpleNamespace(monotonic=lambda: elapsed[0],
                            sleep=lambda _seconds: elapsed.__setitem__(0, elapsed[0] + 31))
    monkeypatch.setattr(module, "time", clock)
    return service, elapsed


def options(**extra):
    return {"project_id": "project-alpha", "handles": ["response:project-alpha:message-one"],
            "mode": "all", "until": "response_received", **extra}


def test_default_wait_reaches_completion_after_the_previous_thirty_second_window(monkeypatch):
    service, elapsed = wait_service(monkeypatch)
    state, data, _ = service._wait(options(), "credential")
    assert state == "satisfied" and elapsed[0] >= 90
    assert data["satisfied"] == options()["handles"]


def test_explicit_wait_budget_returns_pending_without_cancelling_tracking(monkeypatch):
    service, _ = wait_service(monkeypatch)
    state, data, _ = service._wait(options(timeout_seconds=31), "credential")
    assert state == "timeout" and data["pending"] == options()["handles"]


def test_uncertain_delivery_can_still_complete_during_default_wait(monkeypatch):
    service, elapsed = wait_service(monkeypatch, state="uncertain")
    assert service._wait(options(), "credential")[0] == "satisfied"
    assert elapsed[0] >= 90


def test_mcp_contract_exposes_optional_wait_and_business_expiry():
    runtime = McpRuntime(SimpleNamespace(catalog=CATALOG), lambda: "credential")
    assert "deadline" not in runtime.input_schema("send_message")["required"]
    assert "timeout_seconds" not in runtime.input_schema("wait_for_response")["required"]
    for value in (None, 0, 31, 3600):
        runtime._validate("wait_for_response", options(timeout_seconds=value))


def test_cancelled_mcp_wait_releases_its_worker_without_a_fixed_wait_deadline():
    done = threading.Event()
    entered = threading.Event()
    service = ProjectService.__new__(ProjectService)
    service.execute = lambda *_args: (entered.set() or "observed", observation(), [])

    def wait():
        try:
            service._wait(options(), "credential")
        finally:
            done.set()

    async def exercise():
        with anyio.move_on_after(0.05):
            await anyio.to_thread.run_sync(wait, abandon_on_cancel=True)
        assert entered.is_set()
        assert await anyio.to_thread.run_sync(done.wait, 2)

    anyio.run(exercise)


def test_auto_expiry_outlives_internal_command_budget_and_respects_grant(project):
    ok(project, "create_work", work_args())
    args = send_args()
    args.pop("deadline")
    sent = ok(project, "send_message", args)["data"]
    with psycopg.connect(project.dsn) as connection:
        row = connection.execute("SELECT deadline,command_json->>'issued_at' FROM delivery_messages").fetchone()
        expiry = connection.execute("SELECT expires_at FROM grants WHERE grant_ref='grant:p1'").fetchone()[0]
    assert row[0] > datetime.fromisoformat(row[1]) + timedelta(seconds=30)
    assert row[0] <= expiry and datetime.fromisoformat(sent["deadline"]) == row[0]


def test_auto_expiry_respects_work_budget_and_scope_policy(project):
    args = work_args()
    args["budget"]["message_ttl_seconds"] = 60
    ok(project, "create_work", args)
    with psycopg.connect(project.dsn) as connection:
        connection.execute("UPDATE scopes SET policy=policy || '{\"message_ttl_seconds\":120}'::jsonb")
    args = send_args()
    args.pop("deadline")
    ok(project, "send_message", args)
    with psycopg.connect(project.dsn) as connection:
        expiry, issued = connection.execute("SELECT deadline,command_json->>'issued_at' FROM delivery_messages").fetchone()
    assert (expiry - datetime.fromisoformat(issued)).total_seconds() == 60


def test_observation_changes_replay_the_same_committed_message(project):
    ok(project, "create_work", work_args())
    args = send_args()
    args.pop("deadline")
    first = ok(project, "send_message", args)["data"]
    second = ok(project, "send_message", dict(args, response_mode="sync", wait_timeout_seconds=0))
    assert second["state"] == "timeout" and second["data"]["message_id"] == first["message_id"]
    assert scalar(project, "SELECT count(*) FROM delivery_messages") == 1
    assert scalar(project, "SELECT count(*) FROM collaboration_response_subscriptions") == 1


def test_default_sync_waits_for_a_durable_final_response(project, monkeypatch):
    ok(project, "create_work", work_args())
    elapsed = [0.0]
    def complete(_seconds):
        elapsed[0] += 31
        evidence = {"response_digest": "a" * 64, "response_artifact_ref": "artifact:" + "a" * 64}
        with psycopg.connect(project.dsn) as connection:
            connection.execute("INSERT INTO delivery_receipts(tenant_id,message_id,receipt_id,layer,evidence_json) "
                               "SELECT tenant_id,message_id,'final-response','response_received',%s::jsonb "
                               "FROM delivery_messages", (json.dumps(evidence),))
            connection.execute("UPDATE delivery_messages SET receipt_high_water='response_received'")
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: elapsed[0], sleep=complete))
    args = send_args()
    args.pop("deadline")
    result = ok(project, "send_message", dict(args, response_mode="sync"))
    assert result["state"] == "satisfied" and elapsed[0] == 31
    assert result["data"]["observation"]["observations"][0]["receipt_high_water"] == "response_received"


def test_discovery_uses_one_transaction_and_rechecks_revocation(project, monkeypatch):
    original = project.authority.transaction
    counted = Mock(wraps=original)
    monkeypatch.setattr(project.authority, "transaction", counted)
    names = project.projects.available_tools(project.credential)
    assert "send_message" in names and counted.call_count == 1
    with psycopg.connect(project.dsn) as connection:
        connection.execute("UPDATE grants SET permissions=permissions - 'messages.send' WHERE grant_ref='grant:p1'")
    assert "send_message" not in project.projects.available_tools(project.credential)
    assert counted.call_count == 2


def test_machine_without_projects_discovers_the_two_entry_tools(project):
    with psycopg.connect(project.dsn) as connection:
        connection.execute("DELETE FROM collaboration_memberships")
    assert set(project.projects.available_tools(project.credential)) == {"read_profile", "list_projects"}
    assert project.projects.execute("list_projects", {}, project.credential)[1]["items"] == []
