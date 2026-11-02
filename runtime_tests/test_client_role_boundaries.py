"""First-entry context and authorization follow the actual communication identity."""
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_identity_root_management import accepted, actor, result
from runtime_tests.test_identity_root_management import owner_client as owner_client_fixture

comm = comm_fixture
owner_client = owner_client_fixture


def test_client_directory_does_not_claim_a_legacy_root_slot_as_self(owner_client):
    directory = accepted(owner_client, "list_collaborators", project_id="project-alpha")
    assert directory["self"].startswith("client:")
    assert not any(item["is_self"] for item in directory["items"])


def test_legacy_organization_metadata_cannot_relabel_an_ordinary_binding(comm, owner_client):
    child = member_for_context(comm, owner_client)
    with comm.authority._connect() as connection:
        definition = connection.execute("SELECT definition FROM collaboration_teams WHERE project_id='project-alpha' AND scope_id='local-scope'").fetchone()[0]
        definition["members"][0]["organization_level"] = "root"
        connection.execute("UPDATE collaboration_teams SET definition=%s WHERE project_id='project-alpha' AND scope_id='local-scope'", (json.dumps(definition),))
    profile = accepted(child, "read_profile")
    assert profile["actor"]["organization"]["level"] == "agent"
    assert "configure_team" not in {item["name"] for item in child.tools_list()["tools"]}


def member_for_context(comm, parent):
    binding = accepted(parent, "configure_team", project_id="project-alpha", prepare_native=False,
        members=[{"agent_slot_id": "context-worker", "principal_ref": "agent:context-worker", "role": "engineer"}])["caller_bindings"][0]
    context = replace(comm.authority.context, principal_ref=binding["principal_ref"], grant_ref=binding["grant_ref"],
        agent_slot_id=binding["agent_slot_id"], trusted_client=False)
    return actor(comm, context, "engineer", comm.clients["a"].credential_provider())


def test_management_origin_routes_to_current_owner_files_and_keeps_native_local_files(comm, owner_client, tmp_path):
    from runtime.machine_filesystem import MachineFilesystem
    from runtime.surface_config import FilesystemSettings
    source = tmp_path / "owner"
    receiving = tmp_path / "receiving"
    source.mkdir()
    receiving.mkdir()
    (source / "AGENTS.md").write_bytes(b"Owner current management\n")
    (receiving / "AGENTS.md").write_bytes(b"Receiving native files\n")
    accepted(owner_client, "configure_root", project_id="project-alpha", changes={
        "management": {"mode": "current_files", "machine_id": "local", "path": str(source)},
        "instruction_paths": ["AGENTS.md"], "knowledge_index_paths": []})
    child = member_for_context(comm, owner_client)
    remote = MachineFilesystem("owner-source", cwd=source)
    authority = child.service.service.authority
    authority._delivery_endpoints = {"owner-source": SimpleNamespace(
        descriptor=lambda: {"machine_id": "owner-source"}, filesystem=lambda _context, op, args:
            remote.context(args.get("cwd")) if op == "filesystem_context" else remote.execute(op, args))}
    authority._filesystem_backend = MachineFilesystem("local", cwd=receiving)
    from runtime.filesystem_gateway import FilesystemGateway
    child.service.filesystems = FilesystemGateway(authority, FilesystemSettings(
        cwd=str(receiving), management_machine_id="owner-source"))
    pack = accepted(child, "load_project", project_id="project-alpha")
    assert pack["context_completeness"] == "current"
    assert pack["instructions"][0]["content"] == "Owner current management\n"
    assert pack["instructions"][0]["machine_id"] == "owner-source"
    assert accepted(child, "read_file", path="AGENTS.md")["content"] == "Receiving native files\n"
    explicit = accepted(child, "load_project", project_id="project-alpha", machine_id="local", management_path=str(receiving))
    assert explicit["instructions"][0]["content"] == "Receiving native files\n"


@pytest.mark.parametrize("access_mode", ["owner", "shared"])
@pytest.mark.parametrize("explicit_slot", [True, False])
def test_directory_self_is_the_resolved_slot_not_the_shared_principal(comm, owner_client, access_mode, explicit_slot):
    parent = owner_client if access_mode == "owner" else actor(comm,
        replace(comm.authority.context, trusted_client=True, agent_slot_id=None), "root_manager",
        comm.clients["a"].credential_provider(), access_mode="shared")
    members = [{"agent_slot_id": slot, "principal_ref": "agent:shared-directory", "role": "engineer"}
               for slot in ("directory-first", "directory-second")]
    if access_mode == "shared":
        for configured_member in members:
            configured_member["permissions"] = ["profile.engineer", "collaborators.read"]
    configured = accepted(parent, "configure_team", project_id="project-alpha", prepare_native=False, members=members)
    for binding in configured["caller_bindings"]:
        context = replace(comm.authority.context, principal_ref=binding["principal_ref"],
            grant_ref=binding["grant_ref"], trusted_client=False,
            agent_slot_id=binding["agent_slot_id"] if explicit_slot else None)
        child = actor(comm, context, binding["profile"], comm.clients["a"].credential_provider(), access_mode=access_mode)
        directory = accepted(child, "list_collaborators", project_id="project-alpha")
        assert [item["collaborator_handle"] for item in directory["items"] if item["is_self"]] == [directory["self"]]


def route_case(comm, owner_client, tmp_path, role="route", profile="route_manager"):
    configured = accepted(owner_client, "configure_root", project_id="context-root", changes={"name": "Context root"})
    routes = []
    for name in ("own", "sibling"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "AGENTS.md").write_text(name + " route instructions\n", newline="\n")
        route = accepted(owner_client, "create_route", project_id="context-root", root_handle=configured["root_handle"],
            client_request_id="create-" + name, expected_root_revision=1 + len(routes),
            route_id=name, display_name=name, goal="Communication context")
        manifest = {"management": {"mode": "current_files", "machine_id": "local", "path": str(directory)},
                    "instruction_paths": ["AGENTS.md"], "knowledge_index_paths": []}
        accepted(owner_client, "update_route", project_id="context-root", route_handle=route["route_handle"],
            client_request_id="context-" + name, expected_revision=1, reason="Set current Route context",
            changes={"context_manifest": manifest})
        routes.append(route)
    binding = accepted(owner_client, "configure_team", project_id="context-root", prepare_native=False,
        scope_handle=routes[0]["scope_handle"], members=[{
            "agent_slot_id": "context-member", "principal_ref": "agent:context-member", "role": role}])["caller_bindings"][0]
    context = replace(comm.authority.context, principal_ref=binding["principal_ref"],
        grant_ref=binding["grant_ref"], agent_slot_id=binding["agent_slot_id"], trusted_client=False)
    return actor(comm, context, profile, comm.clients["a"].credential_provider()), routes


@pytest.mark.parametrize("role,profile", [("route", "route_manager"), ("engineer", "engineer")])
def test_owner_route_bound_context_refuses_sibling_selection(comm, owner_client, tmp_path, role, profile):
    child, routes = route_case(comm, owner_client, tmp_path, role, profile)
    own = accepted(child, "load_project", project_id="context-root")
    assert own["instructions"][0]["content"] == "own route instructions\n"
    selected = result(child, "load_project", project_id="context-root", route_handle=routes[1]["route_handle"])
    assert not selected["ok"] and selected["data"]["code"] == "authorization_denied"


def test_owner_route_manager_cannot_modify_a_sibling_route(comm, owner_client, tmp_path):
    child, routes = route_case(comm, owner_client, tmp_path)
    own = accepted(child, "update_route", project_id="context-root", route_handle=routes[0]["route_handle"],
        client_request_id="own-update", expected_revision=2, reason="Own Route goal",
        changes={"goal": "Own route update"})
    assert own["revision"] == 3
    denied = result(child, "update_route", project_id="context-root", route_handle=routes[1]["route_handle"],
        client_request_id="sibling-update", expected_revision=2, reason="Forbidden sibling goal",
        changes={"goal": "Forbidden sibling update"})
    assert not denied["ok"] and denied["data"]["code"] == "authorization_denied"
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT definition->>'goal',revision FROM collaboration_routes "
            "WHERE project_id='context-root' AND route_id='sibling'").fetchone() == ("Communication context", 2)


@pytest.mark.parametrize("as_client", [True, False])
def test_root_can_select_own_project_route_context_in_owner_mode(comm, owner_client, tmp_path, as_client):
    _child, routes = route_case(comm, owner_client, tmp_path)
    manager = owner_client
    if not as_client:
        binding = accepted(owner_client, "configure_team", project_id="context-root", prepare_native=False,
            members=[{"agent_slot_id": "context-root-manager", "principal_ref": "agent:context-root-manager",
                      "role": "root"}])["caller_bindings"][0]
        context = replace(comm.authority.context, principal_ref=binding["principal_ref"],
            grant_ref=binding["grant_ref"], agent_slot_id=binding["agent_slot_id"], trusted_client=False)
        manager = actor(comm, context, "root_manager", comm.clients["a"].credential_provider())
        assert accepted(manager, "read_profile")["actor"]["organization"]["level"] == "root"
    pack = accepted(manager, "load_project", project_id="context-root", route_handle=routes[1]["route_handle"])
    assert pack["instructions"][0]["content"] == "sibling route instructions\n"

