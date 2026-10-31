"""Current management files and explicit Source archives on the communication core."""

import json
from argparse import Namespace

import psycopg

from runtime_tests.test_project_registration import registration_case as registration_fixture
from runtime_tests.test_project_service import ok, scalar

registration_case = registration_fixture


def owner(f):
    from runtime.mcp_runtime import McpRuntime
    from runtime.project_service import ProjectService
    from runtime_tests.test_project_service import CATALOG

    f.authority.access_mode = "owner"
    f.projects = ProjectService(
        f.projects.service, CATALOG, profile="root_manager", sources=f.projects.sources
    )
    f.mcp = McpRuntime(f.projects, lambda: f.credential)
    return f


def configure(f, directory, revision=1, request="current-management", paths=None):
    return ok(
        f,
        "configure_project",
        {
            "project_id": "project-alpha",
            "client_request_id": request,
            "expected_revision": revision,
            "changes": {
                "management": {
                    "mode": "current_files",
                    "machine_id": "local",
                    "path": str(directory),
                },
                "instruction_paths": paths or ["AGENTS.md"],
                "knowledge_index_paths": [],
            },
        },
    )


def test_project_context_reads_current_files_with_zero_source_records(project, tmp_path):
    f = owner(project)
    document = tmp_path / "AGENTS.md"
    document.write_text("Current project instructions\n")
    configured = configure(f, tmp_path)
    assert configured["data"]["revision"] == 2
    assert scalar(f, "SELECT count(*) FROM collaboration_sources") == 0
    first = ok(f, "load_project", {"project_id": "project-alpha"})
    assert first["state"] == "current"
    assert first["data"]["instructions"][0]["content"] == document.read_bytes().decode("utf-8")
    document.write_text("Updated current instructions\n")
    second = ok(f, "load_project", {"project_id": "project-alpha"})
    assert second["data"]["instructions"][0]["content"] == document.read_bytes().decode("utf-8")
    assert "source_bindings" not in second["data"]
    assert "primary_source_id" not in second["data"]["manifest"]


def test_machine_read_uses_current_arbitrary_path_outside_management(project, tmp_path):
    f = owner(project)
    directory = tmp_path / "management"
    directory.mkdir()
    (directory / "AGENTS.md").write_text("Instructions\n")
    configure(f, directory)
    outside = tmp_path / "outside.txt"
    outside.write_text("Current native account file\n")
    assert ok(f, "read_file", {"path": str(outside)})["data"]["content"] == outside.read_text()
    assert scalar(f, "SELECT count(*) FROM collaboration_sources") == 0


def test_source_archive_requires_an_explicit_id_and_revision(source_project):
    f = owner(source_project)
    for args in (
        {"project_id": "project-alpha", "path": "README.md"},
        {"project_id": "project-alpha", "source_id": "source-main", "path": "README.md"},
    ):
        assert f.mcp.call("read_source_file", args)["isError"]
    fixed = ok(
        f,
        "read_source_file",
        {
            "project_id": "project-alpha",
            "source_id": "source-main",
            "revision": f.commit,
            "path": "README.md",
        },
    )
    assert fixed["data"]["content"] == "first line\nsecond line\n"
    (f.repo / "README.md").write_text("Current edited content\n")
    assert (
        ok(f, "read_file", {"path": str(f.repo / "README.md")})["data"]["content"]
        == "Current edited content\n"
    )
    assert (
        ok(
            f,
            "read_source_file",
            {
                "project_id": "project-alpha",
                "source_id": "source-main",
                "revision": f.commit,
                "path": "README.md",
            },
        )["data"]["content"]
        == fixed["data"]["content"]
    )


def test_owner_registration_works_outside_git_and_creates_no_sources(registration_case, tmp_path):
    import runtime_project_registration as registration

    from runtime.surface_config import load_settings
    from runtime_tests.test_project_service import CATALOG

    case = registration_case
    directory = tmp_path / "standalone-management"
    import runtime_project_adoption as adoption

    from runtime_tests.test_project_registration import ROOT, setup_api

    actions = setup_api.workspace_install(directory, "bootstrap", False)
    assert not any(action.startswith(("error", "preserve-conflict")) for action in actions)
    assert (
        setup_api.workspace_route_operation(
            Namespace(
                action="create",
                workspace=directory,
                path="routes/main",
                route_id="route-main",
                display_name="Current development line",
                state=None,
                dry_run=False,
            ),
            ROOT / "assets/scaffold",
        )
        == 0
    )
    adoption.adopt(
        directory, "project-registration", rollback_dir=tmp_path / "standalone-identity-backup"
    )
    data = json.loads(case.config.read_text())
    data["access_mode"] = "owner"
    case.config.write_text(json.dumps(data))
    specification = {
        key: value
        for key, value in case.specification.items()
        if key
        not in {
            "source_root",
            "expected_commit",
            "expected_tree",
            "source_id",
            "repository_identity",
        }
    }
    planned = registration.preview(directory, specification, load_settings(case.config), CATALOG)
    assert planned["mode"] == "current_files" and not (directory / ".git").exists()
    result = registration.apply(
        directory, specification, case.config, CATALOG, planned["plan_digest"], adopt_schema=True
    )
    assert result["context_state"] == "current"
    with psycopg.connect(case.f.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM collaboration_sources").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM collaboration_routes").fetchone()[0] == 1


def test_legacy_management_origin_reads_current_repository_relative_paths(project, tmp_path):
    import json

    f = owner(project)
    management = tmp_path / "agent-collabration"
    management.mkdir()
    (management / "AGENTS.md").write_text("Current management instructions\n")
    (tmp_path / "AGENTS.md").write_text("Current containing checkout instructions\n")
    manifest = {
        "management": {"source_id": "old-static-snapshot", "path": "agent-collabration"},
        "local_management_root": str(management),
        "primary_source_root": str(tmp_path / "unrelated-product"),
        "instruction_paths": ["agent-collabration/AGENTS.md", "AGENTS.md"],
        "knowledge_index_paths": [],
    }
    with psycopg.connect(f.dsn) as connection:
        connection.execute(
            "UPDATE collaboration_projects SET context_manifest=%s WHERE project_id='project-alpha'",
            (json.dumps(manifest),),
        )
    result = ok(f, "load_project", {"project_id": "project-alpha"})
    assert result["state"] == "current"
    assert [item["content"] for item in result["data"]["instructions"]] == [
        "Current management instructions\n",
        "Current containing checkout instructions\n",
    ]
    assert scalar(f, "SELECT count(*) FROM collaboration_sources") == 0


def test_current_context_respects_canonical_json_budget(project, tmp_path):
    from runtime.project_common import canonical

    f = owner(project)
    (tmp_path / "AGENTS.md").write_text("中" * 15000)
    configure(f, tmp_path)
    result = ok(f, "load_project", {"project_id": "project-alpha", "max_inline_bytes": 65536})
    assert len(canonical(result["data"]).encode()) <= 65536
    assert result["state"] == "partial"
    follow = next(item for item in result["follow_ups"] if item["tool"] == "read_file")
    assert ok(f, "read_file", follow["arguments"])["data"]["content"] == "中" * 15000


def test_explicit_route_context_reads_route_documents(project, tmp_path):
    f = owner(project)
    (tmp_path / "AGENTS.md").write_text("ROOT_CONTEXT")
    configure(f, tmp_path)
    route = tmp_path / "route"
    route.mkdir()
    (route / "AGENTS.md").write_text("ROUTE_CONTEXT")
    ok(
        f,
        "update_route",
        {
            "project_id": "project-alpha",
            "client_request_id": "current-route-context",
            "route_handle": "route:project-alpha:existing-route",
            "expected_revision": 1,
            "changes": {
                "context_manifest": {
                    "management": {
                        "mode": "current_files",
                        "machine_id": "local",
                        "path": str(route),
                    },
                    "instruction_paths": ["AGENTS.md"],
                    "knowledge_index_paths": [],
                }
            },
            "reason": "Agent selected Route management documents",
        },
    )
    for view in ("route_management", "reviewer", "finalizer"):
        result = ok(
            f,
            "load_project",
            {
                "project_id": "project-alpha",
                "context_view": view,
                "route_handle": "route:project-alpha:existing-route",
            },
        )
        assert result["state"] == "current"
        assert result["data"]["instructions"][0]["content"] == "ROUTE_CONTEXT"


def test_legacy_management_call_override_reads_selected_current_location(project, tmp_path):
    import json

    f = owner(project)
    before = tmp_path / "before" / "agent-collabration"
    after = tmp_path / "after" / "agent-collabration"
    before.mkdir(parents=True)
    after.mkdir(parents=True)
    (before / "AGENTS.md").write_text("OLD_LOCATION")
    (after / "AGENTS.md").write_text("SELECTED_CURRENT_LOCATION")
    manifest = {
        "management": {"source_id": "old-observation", "path": "agent-collabration"},
        "local_management_root": str(before),
        "instruction_paths": ["agent-collabration/AGENTS.md"],
    }
    with psycopg.connect(f.dsn) as connection:
        connection.execute(
            "UPDATE collaboration_projects SET context_manifest=%s WHERE project_id='project-alpha'",
            (json.dumps(manifest),),
        )
    selected = ok(f, "load_project", {"project_id": "project-alpha", "management_path": str(after)})
    assert selected["state"] == "current"
    assert selected["data"]["instructions"][0]["content"] == "SELECTED_CURRENT_LOCATION"
    assert selected["data"]["instructions"][0]["resolved_path"] == str(after / "AGENTS.md")
    assert (
        ok(f, "load_project", {"project_id": "project-alpha"})["data"]["instructions"][0]["content"]
        == "OLD_LOCATION"
    )


def test_legacy_machine_override_uses_target_current_directory(project, tmp_path):
    import json

    from runtime.machine_filesystem import MachineFilesystem

    f = owner(project)
    old = tmp_path / "old" / "agent-collabration"
    target = tmp_path / "target" / "agent-collabration"
    old.mkdir(parents=True)
    target.mkdir(parents=True)
    (old / "AGENTS.md").write_text("ORIGINAL_MACHINE")
    (target / "AGENTS.md").write_text("SELECTED_MACHINE")
    backend = MachineFilesystem("fixture-target", cwd=target)

    class Endpoint:
        def descriptor(self):
            return {"machine_id": "fixture-target"}

        def filesystem(self, context, operation, args):
            return (
                backend.context(args.get("cwd"), args.get("base_cwd"))
                if operation == "filesystem_context"
                else backend.execute(operation, args)
            )

    f.authority._delivery_endpoints["fixture-target"] = Endpoint()
    manifest = {
        "management": {"source_id": "previous-observation", "path": "agent-collabration"},
        "local_management_root": str(old),
        "instruction_paths": ["agent-collabration/AGENTS.md"],
    }
    with psycopg.connect(f.dsn) as connection:
        connection.execute(
            "UPDATE collaboration_projects SET context_manifest=%s WHERE project_id='project-alpha'",
            (json.dumps(manifest),),
        )
    result = ok(f, "load_project", {"project_id": "project-alpha", "machine_id": "fixture-target"})
    assert result["state"] == "current"
    assert result["data"]["management_root"]["machine_id"] == "fixture-target"
    assert result["data"]["instructions"][0]["content"] == "SELECTED_MACHINE"
    assert result["data"]["instructions"][0]["resolved_path"] == str(target / "AGENTS.md")


def test_owner_only_project_configuration_keeps_shared_profiles_unchanged(project):
    from runtime.project_service import ProjectService
    from runtime_tests.test_project_service import CATALOG

    root_before = list(CATALOG["profiles"]["root_manager"])
    operator_before = list(CATALOG["profiles"]["operator"])
    assert "configure_project" not in project.projects.available_tools(project.credential)
    f = owner(project)
    assert "configure_project" in f.projects.available_tools(f.credential)
    assert CATALOG["profiles"]["root_manager"] == root_before
    assert CATALOG["profiles"]["operator"] == operator_before
    f.authority.access_mode = "shared"
    shared = ProjectService(f.projects.service, CATALOG, profile="root_manager")
    assert "configure_project" not in shared.available_tools(f.credential)
