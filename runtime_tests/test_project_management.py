"""Management authorization and policy integration against real PostgreSQL."""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from runtime.auth import LocalCredentialAuthenticator
from runtime.delivery import DeliveryService
from runtime.delivery_models import DeliveryPacket, EndpointBindingRequest
from runtime.delivery_node import LocalNodeEndpoint
from runtime.domain import DomainAuthority
from runtime.errors import AuthorizationDenied
from runtime.mcp_runtime import McpRuntime
from runtime.node import NodeJournal
from runtime.project_common import digest
from runtime.project_service import ProjectService
from runtime.surfaces import SharedService
from runtime_tests.test_delivery import command
from runtime_tests.test_project_service import CATALOG, ok, scalar, send_args, work_args
from runtime_tests.test_project_service import project as project_fixture


@pytest.fixture
def managed(setup, tmp_path):
    f = project_fixture.__wrapped__(setup)
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE grants SET permissions=permissions || %s::jsonb WHERE grant_ref='grant:p1'",
                           (json.dumps(["profile.reviewer", "profile.engineer", "review.record", "work_item.read"]),))
    f.team_journal = NodeJournal(tmp_path / "team-node.sqlite")
    return f


def team_args(*, maximum=4, revision=0, identity="team-1"):
    now = datetime.now(UTC)
    return {"client_request_id": identity, "project_id": "project-alpha",
        "scope_handle": "scope:project-alpha:local-scope", "expected_revision": revision,
        "members": [{"agent_slot_id": "team-worker", "principal_ref": "agent:team-worker",
            "role": "engineer", "profile": "engineer", "grant_ref": "grant:team-worker",
            "permissions": ["profile.engineer", "projects.read", "context.read", "work_item.read",
            "work.read", "messages.read", "message.read", "source.read",
            "resources.read", "handoff.ack"],
            "expires_at": (now + timedelta(minutes=4)).isoformat(), "budget_ref": "budget:team",
            "harness_requirements": ["codex"]}],
        "policies": [{"policy_ref": "policy:team", "rules": {"allowed_activations": ["message_only"],
            "allowed_delivery_policies": ["queue_until_idle"], "max_deadline_seconds": 300}}],
        "budgets": [{"budget_ref": "budget:team", "max_messages": maximum,
            "max_pending_messages": 4, "expires_at": (now + timedelta(minutes=5)).isoformat()}],
        "deadline": (now + timedelta(minutes=1)).isoformat()}


def worker_client(f):
    secret = "worker-private-" + uuid.uuid4().hex
    context = replace(f.authority.context, principal_ref="agent:team-worker", grant_ref="grant:team-worker",
                      credential_hash=hashlib.sha256(secret.encode()).hexdigest())
    authority = DomainAuthority(f.dsn, context=context)
    service = SharedService(authority, LocalCredentialAuthenticator(context))
    return McpRuntime(ProjectService(service, CATALOG, profile="engineer"), lambda: secret), authority


def bind_worker(f):
    endpoint = LocalNodeEndpoint(f.team_journal, "local-scope", "team-worker", f.driver)
    delivery = DeliveryService(f.authority, {"team-endpoint": endpoint})
    delivery.bind_endpoint(command(f.authority, "message.bind", "team-endpoint"), EndpointBindingRequest(
        scope_id="local-scope", agent_slot_id="team-worker", expires_at=datetime.now(UTC) + timedelta(minutes=5)))
    return delivery


def team_send():
    return dict(send_args(), target={"scope_id": "local-scope", "agent_slot_id": "team-worker"},
                deadline=(datetime.now(UTC)+timedelta(minutes=2)).isoformat())


def test_team_configures_real_grants_membership_policy_budget_and_dedup(managed):
    f = managed
    args = team_args()
    receipt = ok(f, "configure_team", args)
    assert receipt["data"]["team_revision"] == 1
    assert scalar(f, "SELECT count(*) FROM grant_delegations") == 1
    assert scalar(f, "SELECT count(*) FROM collaboration_team_budgets") == 1
    assert ok(f, "configure_team", args)["data"] == receipt["data"]
    assert scalar(f, "SELECT count(*) FROM outbox WHERE topic='team.configured'") == 1
    members = ok(f, "list_collaborators", {"project_id": "project-alpha"})
    assert members["data"]["items"][0]["agent_slot_id"] == "team-worker"
    child, _ = worker_client(f)
    context = child.call("load_project", {"project_id": "project-alpha"})
    assert not context["isError"], context
    assert "configure_team" not in {item["name"] for item in child.tools_list()["tools"]}


@pytest.mark.parametrize("mutation", ["revoke", "permission", "policy", "expiry"])
def test_child_grant_cannot_outlive_parent_authority(managed, mutation):
    f = managed
    ok(f, "configure_team", team_args())
    child, authority = worker_client(f)
    assert authority.get_work_item("work")["state"] == "candidate"
    with psycopg.connect(f.dsn) as connection:
        if mutation == "revoke":
            connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref='grant:p1'")
        elif mutation == "permission":
            connection.execute("UPDATE grants SET permissions=permissions - 'work_item.read' WHERE grant_ref='grant:p1'")
        elif mutation == "policy":
            connection.execute("UPDATE scopes SET policy=policy || '{\"new_policy\":true}' WHERE scope_id='local-scope'")
        else:
            connection.execute("UPDATE grants SET expires_at=clock_timestamp() WHERE grant_ref='grant:p1'")
    with pytest.raises(AuthorizationDenied):
        authority.get_work_item("work")
    assert child.call("load_project", {"project_id": "project-alpha"})["isError"]
    if mutation == "policy":
        collaborators = ok(f, "list_collaborators", {"project_id": "project-alpha"})
        assert collaborators["data"]["items"][0]["state"] == "inactive"


def test_team_cannot_escalate_permissions_or_claim_existing_identity(managed):
    f = managed
    args = team_args()
    args["members"][0]["permissions"].append("acceptance.finalize")
    assert f.mcp.call("configure_team", args)["isError"]
    assert scalar(f, "SELECT count(*) FROM collaboration_teams") == 0
    assert scalar(f, "SELECT count(*) FROM grants WHERE grant_ref='grant:team-worker'") == 0
    args = team_args()
    args["members"][0]["agent_slot_id"] = "local-slot"
    assert f.mcp.call("configure_team", args)["isError"]


def test_budget_is_atomic_and_applies_to_raw_domain_send(managed):
    f = managed
    ok(f, "create_work", work_args())
    ok(f, "configure_team", team_args(maximum=1))
    delivery = bind_worker(f)
    args = team_send()
    sent = ok(f, "send_message", args)
    assert ok(f, "send_message", args)["data"] == sent["data"]
    assert scalar(f, "SELECT messages_used FROM collaboration_team_budgets") == 1
    assert f.mcp.call("send_message", dict(args, client_request_id="second-message"))["isError"]
    with psycopg.connect(f.dsn) as connection:
        packet = DeliveryPacket.model_validate(connection.execute("SELECT packet_json FROM delivery_messages").fetchone()[0])
    with pytest.raises(AuthorizationDenied):
        delivery.send_message(command(f.authority, "message.send", "raw-bypass"), packet,
                              endpoint_id="team-endpoint", binding_revision=1)
    assert scalar(f, "SELECT count(*) FROM delivery_messages") == 1
    assert scalar(f, "SELECT count(*) FROM collaboration_budget_reservations") == 1


def test_team_policy_blocks_invoke_and_reconfiguration_preserves_usage(managed):
    f = managed
    ok(f, "create_work", work_args())
    ok(f, "configure_team", team_args(maximum=1))
    bind_worker(f)
    assert f.mcp.call("send_message", dict(team_send(), activation="invoke"))["isError"]
    ok(f, "send_message", team_send())
    ok(f, "configure_team", team_args(maximum=2, revision=1, identity="team-2"))
    assert scalar(f, "SELECT messages_used FROM collaboration_team_budgets") == 1
    child, _ = worker_client(f)
    assert not child.call("load_project", {"project_id": "project-alpha"})["isError"]


def test_stale_team_revision_and_removed_member_are_fenced(managed):
    f = managed
    ok(f, "configure_team", team_args())
    assert f.mcp.call("configure_team", team_args(identity="stale"))["structuredContent"]["data"]["code"] == "revision_conflict"
    args = team_args(revision=1, identity="replace-member")
    args["members"][0].update(agent_slot_id="replacement-worker", principal_ref="agent:replacement",
                               grant_ref="grant:replacement")
    ok(f, "configure_team", args)
    child, _ = worker_client(f)
    assert child.call("load_project", {"project_id": "project-alpha"})["isError"]
    assert scalar(f, "SELECT status FROM agent_slots WHERE agent_slot_id='team-worker'") == "revoked"


def test_harness_discovery_does_not_invent_native_observations(managed):
    f = managed
    ok(f, "configure_team", team_args())
    bind_worker(f)
    result = ok(f, "list_harnesses", {"project_id": "project-alpha",
        "scope_handle": "scope:project-alpha:local-scope", "required_capabilities": ["message"]})
    item = next(item for item in result["data"]["items"] if item["endpoint_id"] == "team-endpoint")
    assert item["harness"] == "unknown" and item["eligible"] is False


def test_1_11_migration_preserves_existing_domain_rows(setup):
    f = setup
    with psycopg.connect(f.dsn) as connection:
        before = connection.execute("SELECT row_to_json(g) FROM grants g ORDER BY grant_ref").fetchall()
        connection.execute("DROP TABLE grant_delegations")
        connection.execute("DROP TABLE work_item_revisions")
        connection.execute("ALTER TABLE reviews DROP COLUMN evidence_refs")
        connection.execute("ALTER TABLE domain_events DROP COLUMN writer_xid")
        connection.execute("UPDATE runtime_schema_metadata SET schema_version='1.11',schema_checksum=%s",
                           ("e840b74d16389bd9b07df1aee061e696955e78a0397dd8649571b04193c49b9d",))
    f.authority.initialize()
    f.authority.initialize()
    with psycopg.connect(f.dsn) as connection:
        assert connection.execute("SELECT row_to_json(g) FROM grants g ORDER BY grant_ref").fetchall() == before
        assert connection.execute("SELECT schema_version FROM runtime_schema_metadata").fetchone() == ("1.12",)
        assert connection.execute("SELECT count(*) FROM grant_delegations").fetchone() == (0,)


def test_existing_root_can_join_team_without_rewriting_its_grant(managed):
    f = managed
    args = team_args()
    with psycopg.connect(f.dsn) as connection:
        original = connection.execute("SELECT row_to_json(g) FROM grants g WHERE grant_ref='grant:p1'").fetchone()[0]
    args["members"].append({"agent_slot_id": "local-slot", "principal_ref": f.authority.context.principal_ref,
        "role": "root", "profile": "root_manager", "grant_ref": "grant:p1",
        "permissions": original["permissions"], "expires_at": original["expires_at"],
        "budget_ref": "budget:team", "harness_requirements": ["codex"]})
    ok(f, "configure_team", args)
    with psycopg.connect(f.dsn) as connection:
        assert connection.execute("SELECT row_to_json(g) FROM grants g WHERE grant_ref='grant:p1'").fetchone()[0] == original
        assert connection.execute("SELECT count(*) FROM grant_delegations WHERE grant_ref='grant:p1'").fetchone()[0] == 0
    ok(f, "create_work", work_args())
    root_send = dict(send_args(), deadline=(datetime.now(UTC) + timedelta(minutes=2)).isoformat())
    assert ok(f, "send_message", root_send)["state"] == "accepted"


def test_cyclic_delegation_is_rejected_without_recursing_forever(managed):
    f = managed
    ok(f, "configure_team", team_args())
    _, authority = worker_client(f)
    with psycopg.connect(f.dsn) as connection:
        policy = connection.execute("SELECT policy FROM scopes WHERE scope_id='local-scope'").fetchone()[0]
        connection.execute("INSERT INTO grant_delegations(grant_ref,parent_grant_ref,tenant_id,command_id,"
                           "parent_policy_digest) VALUES ('grant:p1','grant:team-worker','local-tenant',"
                           "'corruption-fault',%s)", (digest(policy),))
    with pytest.raises(AuthorizationDenied):
        authority.get_work_item("work")
