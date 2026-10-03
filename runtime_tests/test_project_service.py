"""Real PostgreSQL integration; Driver callbacks remain fixture evidence."""
from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from runtime.auth import LocalCredentialAuthenticator
from runtime.mcp_runtime import McpRuntime
from runtime.models import CommandEnvelope
from runtime.project_service import ProjectService, parse_handle
from runtime.surfaces import SharedService

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "docs/runtime/p2-mcp-tool-contract.json").read_text())


def deadline():
    return (datetime.now(UTC) + timedelta(minutes=5)).isoformat()


@pytest.fixture
def project(setup):
    credential = "component-credential-" + uuid.uuid4().hex
    setup.authority.context = replace(setup.authority.context,
        credential_hash=hashlib.sha256(credential.encode()).hexdigest())
    permissions = {"project.adopt", "profile.root_manager", "work_item.create",
                   "delivery.manage", "message.send", "message.read", "runtime.invoke"}
    for tool in CATALOG["tools"].values():
        permissions.update(tool["security_scopes"])
    setup.authority.bootstrap_local_grant(tuple(permissions))
    service = SharedService(setup.authority, LocalCredentialAuthenticator(setup.authority.context))
    projects = ProjectService(service, CATALOG, profile="root_manager")
    projects.initialize()
    now = datetime.now(UTC)
    context = setup.authority.context
    command = CommandEnvelope(
        command_id="adopt-project", command_type="project.adopt", idempotency_key="adopt-project",
        correlation_id="adopt-project", tenant_id=context.tenant_id, authority_id=context.authority_id,
        authority_incarnation=context.authority_incarnation, principal_ref=context.principal_ref,
        grant_ref=context.grant_ref, target_kind="project", target_id="project-alpha",
        expected_revision=0, issued_at=now, deadline=now + timedelta(minutes=5),
    )
    projects.admit_project(command, project_id="project-alpha", root_id="existing-root",
        scope_id="local-scope", agent_slot_id="local-slot", name="Alpha",
        context_manifest={"routes": [{"route_id": "existing-route", "scope_id": "local-scope"}],
                          "evidence_class": "fixture_installer_metadata"}, credential=credential)
    setup.projects, setup.credential = projects, credential
    setup.mcp = McpRuntime(projects, lambda: credential)
    return setup


def work_args(identity="create-work"):
    return {"client_request_id": identity, "project_id": "project-alpha",
            "route_handle": "route:project-alpha:existing-route", "expected_route_revision": 1,
            "work_item_id": "mcp-work", "goal": "verify shared authority",
            "accepted_state": {"revision": 0}, "constraints": ["component test"],
            "source_baseline": "delivery-fixture-baseline", "required_evidence": ["readback"],
            "budget": {"turns": 1}, "deadline": deadline()}


def send_args():
    return {"client_request_id": "send-1", "project_id": "project-alpha",
            "work_handle": "work:project-alpha:mcp-work", "expected_work_revision": 0,
            "target": {"scope_id": "local-scope", "agent_slot_id": "local-slot"},
            "goal": "verify atomic tracking", "request": "fixture message only",
            "constraints": ["no native invocation"], "accepted_revision": 0,
            "required_evidence": ["PostgreSQL readback"], "activation": "message_only",
            "deadline": deadline()}


def ok(f, name, args):
    reply = f.mcp.call(name, args)
    assert not reply["isError"], reply
    return reply["structuredContent"]


def scalar(f, statement):
    with psycopg.connect(f.dsn) as connection:
        return connection.execute(statement).fetchone()[0]


def test_cli_probe_entrypoint_from_unrelated_directory(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "tools/runtime/mcp_component_probe.py"),
                             "--help"], cwd=tmp_path, capture_output=True, text=True,
                            timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    assert "--source-root" in result.stdout


def test_handles_compare_complete_project_identity():
    assert parse_handle("work:project-alpha:item", "work", "project-alpha") == "item"
    for value in ("work:project-alpha-extra:item", "work:other:project-alpha", "work:project-alpha:item:extra"):
        with pytest.raises(ValueError):
            parse_handle(value, "work", "project-alpha")


def test_work_and_message_use_existing_domain_tables(project):
    work = ok(project, "create_work", work_args())
    assert work["data"]["revision"] == 0
    assert scalar(project, "SELECT count(*) FROM work_items WHERE work_item_id='mcp-work'") == 1
    args = send_args()
    sent = ok(project, "send_message", args)
    assert sent["data"]["receipt_layer"] == "accepted_by_authority"
    assert scalar(project, "SELECT count(*) FROM delivery_messages") == 1
    assert scalar(project, "SELECT count(*) FROM outbox WHERE topic='message.delivery'") == 1
    assert scalar(project, "SELECT count(*) FROM collaboration_response_tracking") == 1
    assert scalar(project, "SELECT count(*) FROM collaboration_response_subscriptions") == 1
    assert project.driver.calls == []
    replay = ok(project, "send_message", args)
    assert replay["data"] == sent["data"]
    assert scalar(project, "SELECT count(*) FROM delivery_messages") == 1
    response = ok(project, "read_message", {"project_id": "project-alpha",
        "handle": sent["data"]["response_handle"], "consume": False})
    assert response["data"]["receipt_high_water"] == "accepted_by_authority"


def test_failed_tracking_insert_rolls_back_entire_domain_submission(project):
    ok(project, "create_work", work_args())
    with psycopg.connect(project.dsn) as connection:
        connection.execute("ALTER TABLE collaboration_response_subscriptions ADD CONSTRAINT "
                           "injected_failure CHECK (message_id='impossible-test-value')")
    sent = project.mcp.call("send_message", send_args())
    assert sent["isError"]
    assert scalar(project, "SELECT count(*) FROM delivery_messages") == 0
    assert scalar(project, "SELECT count(*) FROM outbox WHERE topic='message.delivery'") == 0
    assert scalar(project, "SELECT count(*) FROM collaboration_response_tracking") == 0
    assert scalar(project, "SELECT count(*) FROM collaboration_commands WHERE tool_name='send_message'") == 0
    assert scalar(project, "SELECT count(*) FROM command_dedup WHERE result_json->>'state'='message_queued'") == 0


def test_concurrent_replay_commits_one_work(project):
    args = work_args()
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(lambda _: project.mcp.call("create_work", args), range(4)))
    assert all(not reply["isError"] for reply in replies), replies
    assert len({reply["structuredContent"]["data"]["operation_id"] for reply in replies}) == 1
    assert scalar(project, "SELECT count(*) FROM work_items WHERE work_item_id='mcp-work'") == 1
    assert scalar(project, "SELECT count(*) FROM collaboration_work_links") == 1
    conflict = project.mcp.call("create_work", dict(args, goal="changed payload"))
    assert conflict["structuredContent"]["data"]["code"] == "idempotency_conflict"


def test_revocation_blocks_replay_discovery_and_context(project):
    args = work_args()
    ok(project, "create_work", args)
    with psycopg.connect(project.dsn) as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref='grant:p1'")
    assert project.mcp.call("create_work", args)["structuredContent"]["data"]["code"] == "authorization_denied"
    assert project.mcp.call("load_project", {"project_id": "project-alpha"})["isError"]
    assert ok(project, "list_projects", {})["data"]["items"] == []
    assert [x["name"] for x in project.mcp.tools_list()["tools"]] == ["read_profile"]


def test_membership_rebinding_cannot_upgrade_old_transport_credential(project):
    f = project
    with psycopg.connect(f.dsn) as connection:
        connection.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,"
                           "scope_id,permissions,expires_at) SELECT 'grant:replacement',tenant_id,principal_ref,"
                           "authority_id,authority_incarnation,scope_id,permissions,expires_at "
                           "FROM grants WHERE grant_ref='grant:p1'")
        connection.execute("UPDATE collaboration_memberships SET grant_ref='grant:replacement'")
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref='grant:p1'")
    assert f.mcp.call("create_work", work_args())["structuredContent"]["data"]["code"] == "authorization_denied"
    assert scalar(f, "SELECT count(*) FROM collaboration_work_links") == 0


def test_live_credential_cannot_select_unrelated_scoped_grant(project):
    f = project
    with psycopg.connect(f.dsn) as connection:
        connection.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,"
                           "scope_id,permissions,expires_at) SELECT 'grant:unrelated',tenant_id,principal_ref,"
                           "authority_id,authority_incarnation,scope_id,permissions,expires_at "
                           "FROM grants WHERE grant_ref='grant:p1'")
        connection.execute("UPDATE collaboration_memberships SET grant_ref='grant:unrelated'")
    assert f.mcp.call("load_project", {"project_id": "project-alpha"})["isError"]


def test_profile_reports_live_authorization_and_revocation(project):
    profile = ok(project, "read_profile", {})["data"]
    assert profile["granted_profiles"] == ["root_manager"]
    assert profile["domain_schema_version"] == "1.12"
    assert profile["grant"]["ref"] == "grant:p1"
    with psycopg.connect(project.dsn) as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref='grant:p1'")
    revoked = ok(project, "read_profile", {})["data"]
    assert revoked["granted_profiles"] == [] and revoked["grant"]["permissions"] == []
    assert revoked["connection_state"] == "authorization_unavailable"


def test_project_scope_and_transport_cannot_be_selected_by_caller(project):
    args = work_args()
    for attack in (dict(args, project_id="project-alpha-extra"),
                   dict(args, route_handle="route:project-alpha-extra:existing-route"),
                   dict(args, principal_ref="product-owner"),
                   dict(args, expected_route_revision=True)):
        assert project.mcp.call("create_work", attack)["isError"]
    wrong = McpRuntime(project.projects, lambda: "wrong-credential")
    assert wrong.call("list_projects", {})["isError"]
    with pytest.raises(PermissionError):
        wrong.tools_list()
    assert scalar(project, "SELECT count(*) FROM collaboration_work_links") == 0


def test_timeout_and_reconnect_preserve_tracking(project):
    ok(project, "create_work", work_args())
    sent = ok(project, "send_message", send_args())
    response = sent["data"]["response_handle"]
    observation = ok(project, "wait_for_response", {"project_id": "project-alpha",
        "handles": [response], "mode": "all", "until": "response_received", "timeout_seconds": 0})
    assert observation["state"] == "timeout" and observation["data"]["pending"] == [response]
    rebuilt = ProjectService(project.projects.service, CATALOG, profile="root_manager")
    state, inbox, _ = rebuilt.execute("check_inbox", {"project_id": "project-alpha"}, project.credential)
    assert state == "observed" and inbox["items"][0]["response_handle"] == response
    assert scalar(project, "SELECT count(*) FROM collaboration_response_subscriptions WHERE enabled") == 1


def test_grant_permission_changes_filter_available_tools(project):
    with psycopg.connect(project.dsn) as connection:
        connection.execute("UPDATE grants SET permissions=permissions - 'messages.send' "
                           "WHERE grant_ref='grant:p1'")
    names = [item["name"] for item in project.mcp.tools_list()["tools"]]
    assert "send_message" not in names and "create_work" in names
    assert project.mcp.call("send_message", send_args())["isError"]


def test_invalid_sync_bound_cannot_commit_a_message(project):
    ok(project, "create_work", work_args())
    rejected = project.mcp.call("send_message", dict(send_args(),
        response_mode="sync", wait_timeout_seconds=-1))
    assert rejected["structuredContent"]["data"]["code"] == "invalid_arguments"
    assert scalar(project, "SELECT count(*) FROM delivery_messages") == 0


def test_read_pending_response_does_not_consume_future_completion(project):
    ok(project, "create_work", work_args())
    sent = ok(project, "send_message", send_args())
    ok(project, "read_message", {"project_id": "project-alpha",
        "handle": sent["data"]["response_handle"], "consume": True})
    assert scalar(project, "SELECT count(*) FROM collaboration_response_subscriptions "
                           "WHERE consumed_at IS NULL") == 1


def test_wait_requires_requested_receipt_even_when_higher_marker_arrived(project):
    f = project
    ok(f, "create_work", work_args())
    sent = ok(f, "send_message", send_args())["data"]
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE delivery_messages SET receipt_high_water='runtime_dispatched'")
        connection.execute("INSERT INTO delivery_receipts(tenant_id,message_id,receipt_id,layer,evidence_json) "
                           "VALUES ('local-tenant',%s,'out-of-order-marker','runtime_dispatched','{}')",
                           (sent["message_id"],))
    result = ok(f, "wait_for_response", {"project_id": "project-alpha", "handles": [sent["response_handle"]],
        "mode": "all", "until": "target_inbox_committed", "timeout_seconds": 0})
    assert result["state"] == "timeout" and result["data"]["satisfied"] == []


def test_sync_replay_observes_current_receipts_without_resending(project):
    f = project
    ok(f, "create_work", work_args())
    args = dict(send_args(), response_mode="sync", wait_until="target_inbox_committed", wait_timeout_seconds=0)
    first = ok(f, "send_message", args)
    assert first["state"] == "timeout"
    with psycopg.connect(f.dsn) as connection:
        connection.execute("INSERT INTO delivery_receipts(tenant_id,message_id,receipt_id,layer,evidence_json) "
                           "VALUES ('local-tenant',%s,'later-inbox-marker','target_inbox_committed','{}')",
                           (first["data"]["message_id"],))
    replay = ok(f, "send_message", args)
    assert replay["state"] == "satisfied"
    assert replay["data"]["message_id"] == first["data"]["message_id"]
    assert scalar(f, "SELECT count(*) FROM delivery_messages") == 1


def test_wait_reports_terminal_failure_and_keeps_response_subscription(project):
    f = project
    ok(f, "create_work", work_args())
    sent = ok(f, "send_message", send_args())["data"]
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE delivery_messages SET state='blocked'")
    args = {"project_id": "project-alpha", "handles": [sent["response_handle"]],
            "mode": "all", "until": "response_received", "timeout_seconds": 30}
    result = ok(f, "wait_for_response", args)
    assert result["state"] == "terminal" and result["data"]["terminal"] == args["handles"]
    assert result["data"]["satisfied"] == []
    assert ok(f, "wait_for_response", dict(args, until="terminal"))["state"] == "satisfied"
    assert scalar(f, "SELECT count(*) FROM collaboration_response_subscriptions WHERE enabled") == 1


def test_domain_transaction_rolls_back_caught_nested_failure(project):
    authority = project.authority
    with authority.transaction() as (outer, connection):
        connection.execute("UPDATE collaboration_projects SET name='outer-change'")
        with pytest.raises(RuntimeError), outer.transaction() as (_, nested):
            nested.execute("UPDATE collaboration_projects SET name='inner-change'")
            raise RuntimeError("rollback nested savepoint")
        assert connection.execute("SELECT name FROM collaboration_projects").fetchone()[0] == "outer-change"
    assert authority._transaction_connection is None


def test_stale_revision_has_no_domain_or_tracking_effect(project):
    args = work_args()
    rejected = project.mcp.call("create_work", dict(args, expected_route_revision=2))
    assert rejected["structuredContent"]["data"]["code"] == "revision_conflict"
    assert scalar(project, "SELECT count(*) FROM collaboration_work_links") == 0
    ok(project, "create_work", args)
    rejected = project.mcp.call("send_message", dict(send_args(), expected_work_revision=1))
    assert rejected["isError"]
    assert scalar(project, "SELECT count(*) FROM delivery_messages") == 0


def test_real_sdk_process_discovers_and_commits_same_domain(project, tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from runtime_tests.test_surfaces import profile

    config, environment, secret = profile(tmp_path, dsn=project.dsn,
                                          context=project.authority.context)

    async def exercise():
        parameters = StdioServerParameters(command=sys.executable, args=[
            "-m", "runtime.project_entry", "--config", str(config), "--catalog",
            str(ROOT / "docs/runtime/p2-mcp-tool-contract.json"), "--profile", "root_manager",
        ], env=environment, cwd=str(ROOT))
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
            async with (stdio_client(parameters, errlog=errors) as streams,
                        ClientSession(*streams, read_timeout_seconds=15) as session):
                initialized = await session.initialize()
                discovered = await session.list_tools()
                reply = await session.call_tool("create_work", work_args())
                projects = await session.call_tool("list_projects", {})
            errors.seek(0)
            stderr = errors.read()
        assert secret not in stderr
        return initialized, discovered, reply, projects

    initialized, discovered, reply, projects = asyncio.run(exercise())
    assert initialized.server_info.name == "agent-collaboration-runtime"
    assert "send_message" in {tool.name for tool in discovered.tools}
    assert not reply.is_error, reply
    assert reply.structured_content["data"]["work_handle"] == "work:project-alpha:mcp-work"
    assert projects.structured_content["data"]["items"][0]["project_id"] == "project-alpha"
    assert scalar(project, "SELECT count(*) FROM work_items WHERE work_item_id='mcp-work'") == 1
