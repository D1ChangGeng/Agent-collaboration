"""Installer-to-Domain registration with exact Git/Source readback, no Harness claim."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import psycopg
import pytest

from runtime.project_common import digest
from runtime.surface_config import load_settings
from runtime_tests.test_project_service import CATALOG
from runtime_tests.test_source import commit_all, git, make_repo
from runtime_tests.test_surfaces import profile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("registration_setup_tests", ROOT / "scripts/project_setup.py")
setup_api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup_api)

import runtime_project_adoption as adoption
import runtime_project_registration as registration

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="registration Source uses Linux backend")


@pytest.fixture
def registration_case(setup, tmp_path, monkeypatch):
    repo = tmp_path / "checkout"
    make_repo(repo)
    management = repo / "management"
    actions = setup_api.workspace_install(management, "bootstrap", False)
    assert not any(action.startswith(("error", "preserve-conflict")) for action in actions), actions
    args = Namespace(action="create", workspace=management, path="routes/main", route_id="route-main",
                     display_name="Existing main line", state=None, dry_run=False)
    assert setup_api.workspace_route_operation(args, ROOT / "assets/scaffold") == 0
    (management / ".agents/knowledge/index.yaml").write_text("documents: []\n")
    (management / "routes/main/.agents/knowledge").mkdir(exist_ok=True)
    (management / "routes/main/.agents/knowledge/index.yaml").write_text("documents: []\n")
    adoption.adopt(management, "project-registration", rollback_dir=tmp_path / "identity-backup")
    commit_all(repo, "preserved registered workspace")
    scope = "scope-" + digest([setup.authority.context.tenant_id, "project-registration", "route-main"])
    permissions = {"project.adopt", "profile.root_manager", "source.manage", "source.read", "artifact.read", "artifact.write"}
    for tool in CATALOG["tools"].values():
        permissions.update(tool["security_scopes"])
    setup.authority.bootstrap_local_grant(tuple(permissions))
    root_cas, route_cas = tmp_path / "root-cas", tmp_path / "route-cas"
    config, environment, _secret = profile(tmp_path, dsn=setup.dsn, context=setup.authority.context,
        extra={"artifacts": {"root": str(root_cas), "scope_id": "local-scope", "authorized_source_roots": [str(repo)]},
               "additional_artifacts": [{"root": str(route_cas), "scope_id": scope, "authorized_source_roots": [str(repo)]}]})
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    specification = {"schema_version": "acs-runtime-registration/1", "source_root": str(repo),
        "expected_commit": git(repo, "rev-parse", "HEAD").decode().strip(),
        "expected_tree": git(repo, "rev-parse", "HEAD^{tree}").decode().strip(),
        "scope_id": "local-scope", "agent_slot_id": "local-slot", "name": "Registration fixture",
        "source_id": "root-source", "repository_identity": {"kind": "git", "name": "registration-fixture"},
        "route_goals": {"route-main": "Continue the existing main development line"}}
    before = {str(path.relative_to(management)): path.read_bytes() for path in management.rglob("*") if path.is_file()}
    return Namespace(f=setup, repo=repo, root=management, config=config, specification=specification,
                     root_cas=root_cas, route_cas=route_cas, before=before, environment=environment)


def plan(case):
    return registration.preview(case.root, case.specification, load_settings(case.config), CATALOG)


def test_preview_never_opens_database_or_creates_cas(registration_case):
    case = registration_case
    result = plan(case)
    assert result["state"] == "planned" and result["domain_state"] == "not_read"
    assert not case.root_cas.exists() and not case.route_cas.exists()
    assert git(case.repo, "status", "--porcelain") == b""
    with psycopg.connect(case.f.dsn) as connection:
        assert connection.execute("SELECT to_regclass('collaboration_projects')").fetchone() == (None,)


def test_apply_preserves_metadata_and_reads_back_root_and_distinct_route(registration_case):
    case = registration_case
    prepared = plan(case)
    receipt = registration.apply(case.root, case.specification, case.config, CATALOG, prepared["plan_digest"], adopt_schema=True)
    assert receipt["state"] == "registered" and receipt["context_state"] == "current", receipt
    assert receipt["routes"][0]["context_state"] == "current", receipt
    assert receipt["routes"][0]["scope_id"] != "local-scope"
    assert receipt["routes"][0]["source_commit"] == case.specification["expected_commit"]
    assert receipt["execution_started"] is False
    with psycopg.connect(case.f.dsn) as connection:
        counts = {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                  for table in ("collaboration_projects", "collaboration_routes", "collaboration_sources", "operations")}
        root_source = connection.execute("SELECT snapshot_json->'route_id' FROM collaboration_source_snapshots WHERE source_id='root-source'").fetchone()[0]
        assert root_source is None
        adopted = connection.execute("SELECT definition->>'management_source_state',definition->'management_source_readback' "
                                     "FROM collaboration_routes").fetchone()
        assert adopted[0] == "adopted" and adopted[1]["source_commit"] == case.specification["expected_commit"]
    repeated = registration.apply(case.root, case.specification, case.config, CATALOG, prepared["plan_digest"])
    assert repeated == receipt
    with psycopg.connect(case.f.dsn) as connection:
        assert {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in counts} == counts
    assert {str(path.relative_to(case.root)): path.read_bytes() for path in case.root.rglob("*") if path.is_file()} == case.before
    assert git(case.repo, "status", "--porcelain") == b""


def test_changed_preview_or_dirty_source_refuses_before_cas_write(registration_case):
    case = registration_case
    prepared = plan(case)
    with pytest.raises(ValueError, match="preview changed"):
        registration.apply(case.root, case.specification, case.config, CATALOG, "0"*64, adopt_schema=True)
    assert not case.root_cas.exists()
    (case.root / "AGENTS.md").write_text((case.root / "AGENTS.md").read_text() + "New project-owned instruction\n")
    with pytest.raises(ValueError, match="exact clean"):
        registration.apply(case.root, case.specification, case.config, CATALOG, prepared["plan_digest"], adopt_schema=True)
    assert not case.root_cas.exists()


def test_registration_cli_requires_preview_and_works_outside_checkout(registration_case, tmp_path):
    case = registration_case
    specification = tmp_path / "registration.json"
    specification.write_text(json.dumps(case.specification))
    argv = [sys.executable, str(ROOT / "scripts/project_setup.py"), "workspace", "register-runtime-project",
        "--root", str(case.root), "--runtime-config", str(case.config), "--registration-spec", str(specification),
        "--tool-catalog", str(ROOT / "docs/runtime/p2-mcp-tool-contract.json")]
    def run(*extra):
        return subprocess.run([*argv, *extra], cwd=tmp_path, env=dict(os.environ, **case.environment),
                              capture_output=True, text=True, check=False, timeout=60)
    missing = run()
    assert missing.returncode == 1 and not case.root_cas.exists()
    preview = run("--dry-run")
    assert preview.returncode == 0, preview.stderr + preview.stdout
    approved = json.loads(preview.stdout)
    applied = run("--expected-plan-digest", approved["plan_digest"], "--adopt-project-schema")
    assert applied.returncode == 0, applied.stderr + applied.stdout
    assert json.loads(applied.stdout)["context_state"] == "current"
    assert "postgresql://" not in applied.stdout + applied.stderr


def test_failed_registration_rolls_back_domain_and_retains_private_cas(registration_case, monkeypatch):
    from runtime.project_service import ProjectService

    case = registration_case
    approved = plan(case)
    original = ProjectService.execute
    def fail_context(self, name, args, credential):
        if name == "update_route":
            raise ValueError("injected failure after Source export")
        return original(self, name, args, credential)
    monkeypatch.setattr(ProjectService, "execute", fail_context)
    with pytest.raises(ValueError, match="injected failure"):
        registration.apply(case.root, case.specification, case.config, CATALOG, approved["plan_digest"], adopt_schema=True)
    with psycopg.connect(case.f.dsn) as connection:
        assert connection.execute("SELECT to_regclass('collaboration_projects')").fetchone() == (None,)
        assert connection.execute("SELECT count(*) FROM scopes WHERE scope_id<>'local-scope'").fetchone() == (0,)
    assert case.root_cas.exists() and case.route_cas.exists()
    assert git(case.repo, "status", "--porcelain") == b""


def test_runtime_lifecycle_edit_requires_explicit_git_registry_reconciliation(registration_case):
    from runtime.project_service import ProjectService
    from runtime.project_source import ProjectSources
    from runtime.surface_config import configured_service

    case = registration_case
    approved = plan(case)
    registration.apply(case.root, case.specification, case.config, CATALOG, approved["plan_digest"], adopt_schema=True)
    with configured_service(case.config) as (shared, settings):
        sources = ProjectSources(shared.authority._artifact_store,
                                 {provider.scope_id: provider.authorized_source_roots for provider in settings.artifact_configs()})
        try:
            projects = ProjectService(shared, CATALOG, profile="root_manager", sources=sources)
            from runtime_tests.test_project_service import deadline
            projects.execute("update_route", {"project_id": "project-registration", "client_request_id": "pause-registered",
                "route_handle": "route:project-registration:route-main", "expected_revision": 2,
                "changes": {"state": "paused"}, "reason": "explicit runtime lifecycle edit", "deadline": deadline()}, settings.credential())
            state, pack, _ = projects.execute("load_project", {"project_id": "project-registration"}, settings.credential())
            assert state == "partial"
            assert pack["missing_context"] == ["route_metadata_sync:route:project-registration:route-main"]
            assert pack["routes"][0]["definition"]["management_source_readback"]["source_commit"] == case.specification["expected_commit"]
        finally:
            sources.close()
    with pytest.raises(ValueError, match="explicit reconciliation"):
        registration.apply(case.root, case.specification, case.config, CATALOG, approved["plan_digest"])
