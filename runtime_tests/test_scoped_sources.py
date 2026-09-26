"""Explicit multi-Scope Source/CAS routing with real Git, bytes and PostgreSQL."""
from __future__ import annotations

import sys
from contextlib import ExitStack
from copy import copy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from runtime.auth import LocalCredentialAuthenticator
from runtime.mcp_runtime import McpRuntime
from runtime.models import CommandEnvelope
from runtime.project_common import digest
from runtime.project_service import ProjectService
from runtime.project_source import ProjectSources
from runtime.scoped_artifacts import ScopedArtifactStores
from runtime.source_models import SourceRequest
from runtime.surfaces import SharedService
from runtime_tests.test_project_management import team_args, worker_client
from runtime_tests.test_project_routes import route_args, work_for
from runtime_tests.test_project_service import CATALOG, ok
from runtime_tests.test_project_source import read_args
from runtime_tests.test_project_source import source_project as source_fixture
from runtime_tests.test_source import commit_all, git, make_repo

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Source uses Linux dirfd backend")


@pytest.fixture
def source_project(setup, tmp_path):
    yield from source_fixture.__wrapped__(setup, tmp_path)


def command(context, project="project-beta", kind="source.bind", identity="bind-beta"):
    now = datetime.now(UTC)
    return CommandEnvelope(command_id=identity, command_type=kind, idempotency_key=identity,
        correlation_id=identity, tenant_id=context.tenant_id, authority_id=context.authority_id,
        authority_incarnation=context.authority_incarnation, principal_ref=context.principal_ref,
        grant_ref=context.grant_ref, target_kind="project", target_id=project, expected_revision=0,
        issued_at=now, deadline=now+timedelta(minutes=5))


def test_two_projects_route_same_source_name_to_distinct_scope_cas(source_project, tmp_path):
    from runtime.artifacts import ArtifactError, LocalArtifactStore

    f = source_project
    original_sources = f.projects.sources
    beta_repo = tmp_path / "beta-repo"
    make_repo(beta_repo)
    (beta_repo / "README.md").write_text("BETA_ONLY_BYTES\n")
    commit_all(beta_repo, "beta source fixture")
    beta_commit = git(beta_repo, "rev-parse", "HEAD").decode().strip()
    beta_tree = git(beta_repo, "rev-parse", "HEAD^{tree}").decode().strip()
    with ExitStack() as resources:
        beta_store = resources.enter_context(LocalArtifactStore(tmp_path / "beta-cas", scope_id="beta-scope"))
        stores = ScopedArtifactStores([original_sources.store, beta_store])
        sources = ProjectSources(stores, {"local-scope": [f.repo], "beta-scope": [beta_repo]})
        resources.callback(sources.close)
        f.projects.sources = sources
        resources.callback(setattr, f.projects, "sources", original_sources)
        with psycopg.connect(f.dsn) as connection:
            parent_policy = connection.execute("SELECT policy FROM scopes WHERE scope_id='local-scope'").fetchone()[0]
            connection.execute("INSERT INTO scopes VALUES ('beta-scope','local-tenant','{}','active')")
            connection.execute("INSERT INTO agent_slots VALUES ('beta-slot','local-tenant','beta-scope','active')")
            connection.execute("INSERT INTO grants SELECT 'grant:beta',tenant_id,principal_ref,authority_id,"
                               "authority_incarnation,'beta-scope',permissions,expires_at,NULL FROM grants WHERE grant_ref='grant:p1'")
            connection.execute("INSERT INTO grant_delegations(grant_ref,parent_grant_ref,tenant_id,command_id,parent_policy_digest) "
                               "VALUES ('grant:beta','grant:p1','local-tenant','operator-fixture',%s)", (digest(parent_policy),))
        beta_authority = copy(f.authority)
        beta_authority.context = replace(f.authority.context, grant_ref="grant:beta")
        beta_service = ProjectService(SharedService(beta_authority, LocalCredentialAuthenticator(beta_authority.context)),
                                     CATALOG, profile="root_manager", sources=sources)
        beta_service.admit_project(command(beta_authority.context, kind="project.adopt", identity="adopt-beta"),
            project_id="project-beta", root_id="beta-root", scope_id="beta-scope", agent_slot_id="beta-slot", name="Beta",
            context_manifest={"routes": [{"route_id": "beta-route", "scope_id": "beta-scope"}]}, credential=f.credential)
        request = SourceRequest(root=beta_repo, tenant_id=f.authority.context.tenant_id, scope_id="beta-scope",
            root_id="beta-root", route_id="beta-route", expected_commit=beta_commit, expected_tree=beta_tree,
            include_untracked=False)
        # The original manager credential resolves the independently admitted
        # beta membership and its descendant Grant. No credential replacement.
        f.projects.admit_source(command(f.authority.context), project_id="project-beta", source_id="source-main",
            request=request, repository_identity={"kind": "git", "name": "beta-source-fixture"}, credential=f.credential)
        projects = ok(f, "list_projects", {})["data"]["items"]
        assert {p["project_id"] for p in projects} == {"project-alpha", "project-beta"}
        assert ok(f, "read_file", read_args(f))["data"]["content"] == "first line\nsecond line\n"
        beta_args = {"project_id": "project-beta", "source_id": "source-main", "path": "README.md", "revision": beta_commit}
        assert ok(f, "read_file", beta_args)["data"]["content"] == "BETA_ONLY_BYTES\n"
        wrong_project = f.mcp.call("read_file", dict(beta_args, project_id="project-alpha"))
        assert wrong_project["isError"]
        # A digest existing in another store does not permit a provider fallback.
        beta_ref = beta_store.put_bytes(b"PRIVATE_BETA_ARTIFACT")
        with pytest.raises((ArtifactError, FileNotFoundError)):
            stores.read(beta_ref.model_copy(update={"scope_id": "local-scope"}))
        with psycopg.connect(f.dsn) as connection:
            connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref='grant:beta'")
        assert f.mcp.call("read_file", beta_args)["structuredContent"]["data"]["code"] == "authorization_denied"
        assert not f.mcp.call("read_file", read_args(f))["isError"]


def test_unknown_scope_and_same_cas_root_are_rejected(source_project, tmp_path):
    from runtime.artifacts import ArtifactError, LocalArtifactStore

    original = source_project.projects.sources.store
    with pytest.raises(ArtifactError, match="scope binding"):
        LocalArtifactStore(original.root, scope_id="wrong-alias")
    with (LocalArtifactStore(original.root / "nested", scope_id="wrong-alias") as alias,
          pytest.raises(ArtifactError, match="disjoint")):
        ScopedArtifactStores([original, alias])
    registry = ScopedArtifactStores([original])
    with pytest.raises(ArtifactError, match="no admitted provider"):
        registry.for_scope("unregistered")
    with pytest.raises(ArtifactError, match="complete typed"):
        registry.read({"scope_id": "local-scope"})


def test_source_binding_cannot_change_route_identity_on_replay(source_project):
    f = source_project
    with psycopg.connect(f.dsn) as connection:
        connection.execute("INSERT INTO collaboration_routes(tenant_id,project_id,route_id,scope_id,definition) "
                           "VALUES ('local-tenant','project-alpha','other-route','local-scope','{}')")
    changed = SourceRequest(root=f.repo, tenant_id=f.authority.context.tenant_id, scope_id="local-scope",
        root_id="existing-root", route_id="other-route", expected_commit=f.commit, expected_tree=f.tree,
        include_untracked=False)
    with pytest.raises(ValueError, match="identity cannot be replaced"):
        f.projects.admit_source(command(f.authority.context, project="project-alpha").model_copy(update={"expected_revision": 1}),
            project_id="project-alpha", source_id="source-main", request=changed,
            repository_identity={"kind": "git", "name": "source-fixture"}, credential=f.credential)


def test_route_scoped_context_hydrates_own_source_and_allows_its_manager(source_project, tmp_path):
    from runtime.artifacts import LocalArtifactStore

    f = source_project
    (f.repo / "route-AGENTS.md").write_text("ROUTE_INSTRUCTION_MARKER\nKeep this Route independent.\n")
    commit_all(f.repo, "route instructions fixture")
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE grants SET permissions=permissions || '[\"profile.route_manager\"]'::jsonb "
                           "WHERE grant_ref='grant:p1'")
    route = ok(f, "create_route", route_args())["data"]
    scope = route["scope_handle"].split(":")[-1]
    original_sources = f.projects.sources
    commit = git(f.repo, "rev-parse", "HEAD").decode().strip()
    tree = git(f.repo, "rev-parse", "HEAD^{tree}").decode().strip()
    with ExitStack() as resources:
        route_store = resources.enter_context(LocalArtifactStore(tmp_path / "route-cas", scope_id=scope))
        stores = ScopedArtifactStores([original_sources.store, route_store])
        sources = ProjectSources(stores, {"local-scope": [f.repo], scope: [f.repo]})
        resources.callback(sources.close)
        f.projects.sources = sources
        resources.callback(setattr, f.projects, "sources", original_sources)
        request = SourceRequest(root=f.repo, tenant_id=f.authority.context.tenant_id, scope_id=scope,
            root_id="existing-root", route_id="next-route", expected_commit=commit,
            expected_tree=tree, include_untracked=False)
        f.projects.admit_source(command(f.authority.context, project="project-alpha", identity="bind-route-source"),
            project_id="project-alpha", source_id="route-source", request=request,
            repository_identity={"kind": "git", "name": "route-source-fixture"}, credential=f.credential)
        context = {"management": {"source_id": "route-source", "path": "management"},
            "instruction_paths": ["management/AGENTS.md", "route-AGENTS.md"],
            "knowledge_index_paths": ["management/.agents/knowledge/index.yaml"],
            "skill_catalog": {"source_id": "route-source", "path": "skills/catalog.json"}}
        ok(f, "update_route", {"project_id": "project-alpha", "client_request_id": "route-context",
            "route_handle": route["route_handle"], "expected_revision": 1,
            "changes": {"context_manifest": context}, "reason": "explicit scoped Source adoption",
            "deadline": command(f.authority.context).deadline.isoformat()})
        team = team_args()
        team["scope_handle"] = route["scope_handle"]
        team["members"][0].update(profile="route_manager", role="route", permissions=[
            "profile.route_manager", "projects.read", "context.read", "source.read", "artifact.read", "work.read",
            "work.manage", "work_item.create", "message.read", "messages.read"])
        ok(f, "configure_team", team)
        worker, _ = worker_client(f)
        projects = ProjectService(worker.service.service, CATALOG, profile="route_manager", sources=sources)
        client = McpRuntime(projects, worker.credential_provider)
        pack = client.call("load_project", {"project_id": "project-alpha", "context_view": "route_management"})
        assert not pack["isError"], pack
        assert pack["structuredContent"]["state"] == "current", pack
        data = pack["structuredContent"]["data"]
        assert data["context_scope_id"] == scope
        assert "ROUTE_INSTRUCTION_MARKER" in data["instructions"][1]["content"]
        assert data["skills"] == [{"name": "acs-project-context", "description": "Project and Root identity knowledge."}]
        assert [s["source_id"] for s in data["source_bindings"]] == ["route-source"]
        denied = client.call("read_file", read_args(f))
        assert denied["structuredContent"]["data"]["code"] == "authorization_denied"
        created = client.call("create_work", dict(work_for(), expected_route_revision=2, source_baseline=commit))
        assert not created["isError"], created
