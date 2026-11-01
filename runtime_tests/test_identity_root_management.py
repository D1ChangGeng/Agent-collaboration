"""Real PG identity/Root API regressions; Native qualification is separate."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from runtime.auth import LocalCredentialAuthenticator
from runtime.domain import DomainAuthority
from runtime.mcp_runtime import McpRuntime
from runtime.project_service import ProjectService
from runtime.surfaces import SharedService
from runtime_tests.test_communication import CATALOG
from runtime_tests.test_communication import comm as comm_fixture

comm = comm_fixture


def actor(comm, context, profile, token):
    authority = DomainAuthority(comm.dsn, context=context, access_mode="owner")
    service = ProjectService(SharedService(authority, LocalCredentialAuthenticator(context)), CATALOG, profile=profile)
    return McpRuntime(service, lambda: token)


def result(client, tool, **args):
    return client.call(tool, args)["structuredContent"]


def accepted(client, tool, **args):
    value = result(client, tool, **args)
    assert value["ok"], value
    return value["data"]


@pytest.fixture
def owner_client(comm):
    return actor(comm, replace(comm.authority.context, trusted_client=True, agent_slot_id=None),
                 "root_manager", comm.clients["a"].credential_provider())


def member(comm, manager, slot, role, profile, scope=None):
    args = {"project_id": "project-alpha", "client_request_id": "configure-" + slot,
            "members": [{"agent_slot_id": slot, "principal_ref": "agent:" + slot, "role": role,
                         "profile": profile, "display_name": slot}]}
    if scope:
        args["scope_handle"] = scope
    value = accepted(manager, "configure_team", **args)
    binding = value["caller_bindings"][0]
    context = replace(comm.authority.context, principal_ref=binding["principal_ref"],
                      grant_ref=binding["grant_ref"], agent_slot_id=slot, trusted_client=False)
    return actor(comm, context, profile, comm.clients["a"].credential_provider())


def test_first_client_context_is_explicit_before_selecting_a_project(owner_client):
    profile = accepted(owner_client, "read_profile")
    assert profile["actor"]["organization"]["level"] == "client"
    assert profile["actor"]["agent_slot_id"] is None
    assert profile["actor"]["native_session_requirement"] == "none"
    assert "configure_root" in {tool["name"] for tool in owner_client.tools_list()["tools"]}
    assert set(owner_client.service.catalog["result_types"]["profile_snapshot"]) <= set(profile)
    assert "actor" in owner_client.service.catalog["tools"]["read_profile"]["description"]


@pytest.mark.parametrize("role,profile", [("root", "root_manager"), ("route", "route_manager"), ("engineer", "engineer")])
def test_role_context_has_live_communication_guidance_only(comm, owner_client, role, profile):
    child = member(comm, owner_client, "context-" + role, role, profile)
    pack = accepted(child, "load_project", project_id="project-alpha")
    binding = pack["actor_binding"]
    assert "work_query" not in binding and "review_query" not in binding
    assert binding["communication_address"].endswith(":context-" + role)
    assert binding["manager_handle"].startswith("client:")
    for key in ("inbox_query", "history_query", "contacts_query"):
        assert binding[key]["tool"] in child.service.available_tools(child.credential_provider())


def test_route_manager_discovery_matches_route_creation_refusal(comm, owner_client):
    manager = member(comm, owner_client, "route-manager", "route", "route_manager")
    assert "create_route" not in manager.service.available_tools(manager.credential_provider())
    denied = result(manager, "create_route", project_id="project-alpha", client_request_id="forbidden-route",
                    root_handle="project:project-alpha:root", expected_root_revision=1,
                    route_id="forbidden", display_name="Forbidden", goal="Must reject")
    assert not denied["ok"] and denied["data"]["code"] == "authorization_denied"


def test_root_configuration_establishes_one_namespace_without_a_client_slot(comm, owner_client):
    args = {"project_id": "root-new", "client_request_id": "root-new-setup",
            "changes": {"name": "New communication root"}}
    root = accepted(owner_client, "configure_root", **args)
    duplicate = accepted(owner_client, "configure_root", **args)
    assert root == duplicate
    pack = accepted(owner_client, "load_project", project_id="root-new")
    assert pack["actor_binding"]["organization"]["level"] == "client"
    assert pack["actor_binding"]["agent_slot_id"] is None
    assert pack["root_handle"] == root["root_handle"]
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM collaboration_projects WHERE project_id='root-new'").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM collaboration_memberships WHERE project_id='root-new'").fetchone() == (0,)
        assert connection.execute("SELECT to_regclass('work_items')").fetchone() == (None,)


def test_concurrent_first_root_configuration_keeps_one_manager_and_operation(comm, owner_client):
    args = {"project_id": "concurrent-root", "client_request_id": "concurrent-root-setup",
            "changes": {"name": "Concurrent Root"}, "prepare_native": False,
            "manager": {"agent_slot_id": "concurrent-root-manager", "principal_ref": "agent:concurrent-root"}}
    with ThreadPoolExecutor(max_workers=4) as executor:
        values = list(executor.map(lambda _: accepted(owner_client, "configure_root", **args), range(4)))
    assert all(value == values[0] for value in values)
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM collaboration_team_members WHERE project_id='concurrent-root'").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM collaboration_commands WHERE project_id='concurrent-root' AND tool_name='configure_root'").fetchone() == (1,)


def test_two_namespaces_cannot_concurrently_claim_the_same_root_identity(comm, owner_client):
    with ThreadPoolExecutor(max_workers=2) as executor:
        values = list(executor.map(lambda project: result(owner_client, "configure_root", project_id=project,
            changes={"name": project, "root_id": "unique-root"}), ["root-namespace-one", "root-namespace-two"]))
    assert sum(value["ok"] for value in values) == 1
    rejected = next(value for value in values if not value["ok"])
    assert rejected["data"]["code"] == "invalid_arguments" and rejected["data"]["field"] == "changes.root_id"
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM collaboration_projects WHERE root_id='unique-root'").fetchone() == (1,)


def test_root_configuration_attaches_existing_files_without_separate_project_admission(comm, owner_client, tmp_path):
    instructions = tmp_path / "AGENTS.md"
    instructions.write_text("Existing Root communication guidance\n", newline="\n")
    configured = accepted(owner_client, "configure_root", project_id="existing-files-root", client_request_id="existing-files-root",
        changes={"name": "Existing files", "management": {"mode": "current_files", "machine_id": "local", "path": str(tmp_path)},
                 "instruction_paths": ["AGENTS.md"], "knowledge_index_paths": []})
    pack = accepted(owner_client, "load_project", project_id="existing-files-root")
    assert pack["root_handle"] == configured["root_handle"]
    assert pack["instructions"][0]["content"] == instructions.read_text()
    assert pack["actor_binding"]["organization"]["level"] == "client"
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM collaboration_sources WHERE project_id='existing-files-root'").fetchone() == (0,)


def test_bound_root_cannot_establish_a_peer_root(comm, owner_client):
    manager = member(comm, owner_client, "project-root", "root", "root_manager")
    denied = result(manager, "configure_root", project_id="root-other", client_request_id="forbidden-root",
                    changes={"name": "Forbidden root"})
    assert not denied["ok"] and denied["data"]["code"] == "authorization_denied"
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM collaboration_projects WHERE project_id='root-other'").fetchone() == (0,)


def test_root_manager_configuration_is_atomic_and_native_state_is_truthful(comm, owner_client):
    configured = accepted(owner_client, "configure_root", project_id="root-with-manager", client_request_id="root-manager-setup",
                          changes={"name": "Managed root"},
                          manager={"agent_slot_id": "new-root-manager", "principal_ref": "agent:new-root-manager"})
    manager = configured["manager_configuration"]
    assert manager["caller_bindings"][0]["profile"] == "root_manager"
    assert manager["caller_bindings"][0]["trusted_client"] is False
    assert manager["native_sessions"][0]["session_ref"] is None
    assert manager["native_sessions"][0]["state"] == "provider_unavailable"
    binding = manager["caller_bindings"][0]
    context = replace(comm.authority.context, agent_slot_id=binding["agent_slot_id"], principal_ref=binding["principal_ref"],
                      grant_ref=binding["grant_ref"], trusted_client=False)
    child = actor(comm, context, "root_manager", comm.clients["a"].credential_provider())
    pack = accepted(child, "load_project", project_id="root-with-manager")
    assert pack["actor_binding"]["organization"]["level"] == "root"
    accepted(child, "configure_root", project_id="root-with-manager", client_request_id="own-root-update",
             changes={"name": "Updated by its Root Manager"})
    updated = accepted(child, "configure_root", project_id="root-with-manager", client_request_id="own-display-update",
                       changes={}, prepare_native=False,
                       manager={"agent_slot_id": "new-root-manager", "display_name": "Updated manager"})
    assert updated["manager_configuration"]["caller_bindings"][0]["principal_ref"] == "agent:new-root-manager"


def test_invalid_manager_does_not_leave_a_half_created_root(comm, owner_client):
    denied = result(owner_client, "configure_root", project_id="root-rollback", client_request_id="invalid-root-manager",
                    changes={"name": "Rollback"}, manager={"agent_slot_id": "slot-b", "principal_ref": "agent:other-owner"})
    assert not denied["ok"]
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM collaboration_projects WHERE project_id='root-rollback'").fetchone() == (0,)


def test_root_retry_and_partial_update_do_not_overwrite_stale_expectations(owner_client):
    accepted(owner_client, "configure_root", project_id="root-retries", client_request_id="setup", changes={"name": "Initial"})
    accepted(owner_client, "configure_root", project_id="root-retries", client_request_id="rename", changes={"name": "Current"},
             if_unchanged={"name": "Initial"})
    stale = result(owner_client, "configure_root", project_id="root-retries", client_request_id="stale",
                   changes={"name": "Stale"}, if_unchanged={"name": "Initial"})
    assert not stale["ok"] and stale["data"]["code"] == "revision_conflict"
    conflicting = result(owner_client, "configure_root", project_id="root-retries", client_request_id="setup", changes={"name": "Changed"})
    assert not conflicting["ok"] and conflicting["data"]["code"] == "idempotency_conflict"


def test_team_revision_feedback_distinguishes_team_from_root_and_route_versions(owner_client):
    conflict = result(owner_client, "configure_team", project_id="project-alpha", expected_revision=1,
                      client_request_id="wrong-team-revision", members=[{"agent_slot_id": "new-member",
                          "principal_ref": "agent:new-member", "role": "engineer"}])
    assert not conflict["ok"] and conflict["data"]["code"] == "revision_conflict"
    assert conflict["data"]["field"] == "expected_revision"
    assert conflict["data"]["current_revision"] == 0
    assert "team_revision" in conflict["data"]["guidance"] and "if_unchanged" in conflict["data"]["guidance"]
    merged = accepted(owner_client, "configure_team", project_id="project-alpha",
                      client_request_id="partial-member-update", members=[{"agent_slot_id": "new-member",
                          "principal_ref": "agent:new-member", "role": "engineer"}])
    assert merged["team_revision"] == 1


@pytest.mark.parametrize("changes,manager,field", [
    ({"name": "Invalid root", "unexpected": True}, None, "changes"),
    ({"name": "Invalid root"}, {"agent_slot_id": "new-member"}, "manager.principal_ref"),
    ({"name": "Invalid root"}, {"agent_slot_id": "new-member", "principal_ref": "agent:new", "trusted_client": True}, "manager"),
])
def test_root_nested_schema_rejects_unadvertised_or_incomplete_configuration(comm, owner_client, changes, manager, field):
    args = {"project_id": "invalid-nested-root", "changes": changes}
    if manager is not None:
        args["manager"] = manager
    invalid = result(owner_client, "configure_root", **args)
    assert not invalid["ok"] and invalid["data"]["code"] == "invalid_arguments"
    assert invalid["data"]["field"] == field
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM collaboration_projects WHERE project_id='invalid-nested-root'").fetchone() == (0,)


def test_stale_role_session_cannot_keep_discovering_or_using_old_privileges(comm, owner_client):
    manager = member(comm, owner_client, "changed-manager", "root", "root_manager")
    accepted(owner_client, "configure_team", project_id="project-alpha", client_request_id="demote-manager",
             members=[{"agent_slot_id": "changed-manager", "profile": "engineer", "role": "engineer"}])
    denied = result(manager, "read_profile")
    assert not denied["ok"] and denied["data"]["code"] == "authorization_denied"
    from runtime.errors import AuthorizationDenied
    with pytest.raises(AuthorizationDenied):
        manager.service.available_tools(manager.credential_provider())
    assert not result(manager, "configure_root", project_id="project-alpha", client_request_id="stale-manager-write",
                      changes={"name": "Must not write"})["ok"]


@pytest.mark.parametrize("boundary", ["grant", "slot", "scope"])
def test_inactive_binding_is_not_advertised_as_usable(comm, owner_client, boundary):
    manager = member(comm, owner_client, "inactive-manager", "root", "root_manager")
    with comm.authority._connect() as connection:
        if boundary == "grant":
            connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (manager.service.context.grant_ref,))
        elif boundary == "slot":
            connection.execute("UPDATE agent_slots SET status='revoked' WHERE agent_slot_id='inactive-manager'")
        else:
            connection.execute("UPDATE scopes SET status='revoked' WHERE scope_id='local-scope'")
    from runtime.errors import AuthorizationDenied, IdentityRejected
    with pytest.raises((AuthorizationDenied, IdentityRejected)):
        manager.service.available_tools(manager.credential_provider())
    assert not result(manager, "read_profile")["ok"]


def test_shared_context_actions_follow_current_grant_permissions(comm):
    configured = accepted(comm.clients["a"], "configure_team", project_id="project-alpha",
                          client_request_id="shared-context-member", prepare_native=False,
                          members=[{"agent_slot_id": "shared-context-member", "principal_ref": "agent:shared-context",
                                    "role": "engineer"}])
    binding = configured["caller_bindings"][0]
    context = replace(comm.authority.context, principal_ref=binding["principal_ref"], grant_ref=binding["grant_ref"],
                      agent_slot_id=binding["agent_slot_id"], trusted_client=False)
    authority = DomainAuthority(comm.dsn, context=context, access_mode="shared")
    child = McpRuntime(ProjectService(SharedService(authority, LocalCredentialAuthenticator(context)), CATALOG, profile="engineer"),
                       comm.clients["a"].credential_provider)
    with comm.authority._connect() as connection:
        connection.execute("UPDATE grants SET permissions=permissions-'message.read' WHERE grant_ref=%s", (binding["grant_ref"],))
    profile = accepted(child, "read_profile")
    tools = {tool["name"] for tool in child.tools_list()["tools"]}
    assert "check_inbox" not in tools and "configure_root" not in tools
    for scoped in profile["actor"]["bindings"]:
        assert "inbox_query" not in scoped and "history_query" not in scoped
        assert all(query["tool"] in tools for key, query in scoped.items() if key.endswith("_query"))
