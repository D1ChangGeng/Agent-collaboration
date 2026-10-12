"""Current owner workspace reads retain exact committed snapshots."""
from runtime_tests.test_project_service import ok

pytest_plugins = ("runtime_tests.test_project_source",)


def test_owner_reads_current_workspace_and_retains_commit_snapshot(source_project):
    f = source_project
    f.authority.access_mode = "owner"
    (f.repo/"README.md").write_text("current workspace content\n")
    (f.repo/"new-module.py").write_text("NEW_MODULE = True\n")
    args = {"project_id": "project-alpha", "source_id": "source-main", "path": "README.md"}
    current = ok(f, "read_file", args)["data"]
    assert current["content"] == "current workspace content\n"
    assert current["revision"].startswith("workspace:")
    sources = ok(f,"list_sources",{"project_id":"project-alpha"})["data"]["items"]
    source = next(item for item in sources if item["source_id"] == "source-main")
    assert source["commit"] == f.commit and source["view_revision"] == current["revision"]
    connections = ok(f,"list_connections",{"project_id":"project-alpha","kinds":["source"]})["data"]["items"]
    source_connection = next(item for item in connections if item["source_id"] == "source-main")
    assert source_connection["commit"] == f.commit and source_connection["view_revision"] == current["revision"]
    retained = ok(f, "read_file", dict(args, revision=f.commit))["data"]
    assert retained["content"] == "first line\nsecond line\n"
    assert retained["revision"] == f.commit
    exact_workspace = ok(f, "read_file", dict(args, revision=current["revision"]))["data"]
    assert exact_workspace["content"] == current["content"]
    listing = ok(f, "list_files", dict(args, path="", depth=1))["data"]["items"]
    assert any(item["path"] == "new-module.py" for item in listing)
    assert not any(item["path"] == ".env" for item in listing)
    assert ok(f, "read_source", {"project_id": "project-alpha", "source_id": "source-main"})["state"] == "current"



def test_owner_source_defaults_choose_current_primary_hint(source_project):
    f = source_project
    f.authority.access_mode = "owner"
    args = {"project_id": "project-alpha", "path": "README.md"}
    read = ok(f, "read_file", args)["data"]
    assert read["source_id"] == "source-main"
    assert read["content"] == "first line\nsecond line\n"
    assert read["source_selection"]["location_choice"] == "main_worktree"
    assert "source_id" not in args
    state = ok(f, "read_source", {"project_id": "project-alpha"})["data"]
    assert state["version_guidance"]["kind"] == "advisory"
    assert state["version_guidance"]["commit"] == f.commit
    for name in ("read_file", "read_source", "list_files", "search_files"):
        schema = f.mcp.input_schema(name)
        assert "source_id" not in schema["required"]
        assert "revision" not in schema["required"]
        assert "source_root" in schema["properties"]


def test_owner_source_defaults_follow_new_commit_and_retain_baseline(source_project):
    from runtime_tests.test_source import commit_all, git
    f = source_project
    f.authority.access_mode = "owner"
    baseline = f.commit
    (f.repo / "README.md").write_text("latest main checkout\n")
    commit_all(f.repo, "advance primary checkout")
    current = git(f.repo, "rev-parse", "HEAD").decode().strip()
    args = {"project_id": "project-alpha", "path": "README.md"}
    assert ok(f, "read_file", args)["data"]["content"] == "latest main checkout\n"
    assert ok(f, "read_source", {"project_id": "project-alpha"})["data"]["commit"] == current
    retained = ok(f, "read_file", dict(args, revision=baseline))["data"]
    assert retained["content"] == "first line\nsecond line\n"
    selected = ok(f, "read_source", {"project_id": "project-alpha", "revision": baseline})["data"]
    assert selected["commit"] == current
    assert selected["actual_source"] == retained["actual_source"]
    assert selected["actual_source"]["commit"] == baseline


def test_owner_location_choice_reads_another_checkout(source_project, tmp_path):
    from runtime.project_source import ProjectSources
    from runtime_tests.test_source import git
    f = source_project
    f.authority.access_mode = "owner"
    other = tmp_path / "other-checkout"
    git(f.repo, "clone", "-q", str(f.repo), str(other))
    (other / "README.md").write_text("selected other checkout\n")
    store = f.projects.sources.store
    f.projects.sources.close()
    f.projects.sources = ProjectSources(store, [f.repo.parent])
    read = ok(f, "read_file", {"project_id": "project-alpha", "path": "README.md",
                             "source_root": str(other)})["data"]
    assert read["content"] == "selected other checkout\n"
    assert read["source_selection"]["location_choice"] == "caller"
    assert read["source_selection"]["provider_choice"] == "agent"
    assert ok(f, "read_file", {"project_id": "project-alpha", "path": "README.md",
                             "revision": f.commit})["data"]["content"] == "first line\nsecond line\n"


def test_owner_relocated_hint_defaults_to_primary_worktree(source_project, tmp_path):
    from runtime.project_source import ProjectSources
    from runtime_tests.test_project_source import bind
    from runtime_tests.test_source import git
    f = source_project
    f.authority.access_mode = "owner"
    primary = f.repo
    linked = tmp_path / "route-worktree"
    git(primary, "worktree", "add", "-q", "--detach", str(linked), "HEAD")
    store = f.projects.sources.store
    f.projects.sources.close()
    f.projects.sources = ProjectSources(store, [f.repo.parent])
    f.repo = linked
    bind(f, revision=1)
    (primary / "README.md").write_text("latest primary worktree\n")
    read = ok(f, "read_file", {"project_id": "project-alpha", "path": "README.md"})["data"]
    assert read["content"] == "latest primary worktree\n"
    assert read["source_selection"]["location_choice"] == "main_worktree"
    chosen = ok(f, "read_file", {"project_id": "project-alpha", "path": "README.md",
                               "source_root": str(linked)})["data"]
    assert chosen["content"] == "first line\nsecond line\n"


def test_owner_context_source_guidance_and_current_skill_followup(source_project):
    f = source_project
    f.authority.access_mode = "owner"
    context = ok(f, "load_project", {"project_id": "project-alpha"})
    guidance = context["data"]["source_guidance"]
    assert guidance["default_read"] == "current_main_worktree"
    assert guidance["version_guidance"] == "advisory"
    assert guidance["provider_choice"] == "agent"
    followup = next(item for item in context["follow_ups"] if item["rel"] == "read_skill")
    assert "revision" not in followup["arguments"]
    assert followup["source_version_hint"] == f.commit
    assert "SKILL_BODY_MARKER" in ok(f, followup["tool"], followup["arguments"])["data"]["content"]


def test_owner_source_paging_keeps_selected_bytes(source_project):
    f = source_project
    f.authority.access_mode = "owner"
    first = ok(f, "read_file", {"project_id": "project-alpha", "path": "README.md",
                              "max_inline_bytes": 12})
    follow = first["follow_ups"][0]
    assert follow["arguments"]["revision"] == first["data"]["revision"]
    (f.repo / "README.md").write_text("new contents after first page\n")
    next_page = ok(f, follow["tool"], follow["arguments"])["data"]
    assert next_page["content"] == "second line\n"


def set_source_preferences(f, **values):
    import json
    import psycopg
    with psycopg.connect(f.dsn) as conn:
        manifest = conn.execute("SELECT context_manifest FROM collaboration_projects "
                                "WHERE project_id='project-alpha'").fetchone()[0]
        manifest.update(values)
        conn.execute("UPDATE collaboration_projects SET context_manifest=%s "
                     "WHERE project_id='project-alpha'", (json.dumps(manifest),))


def split_product_source(f, tmp_path, source_id="source-product"):
    import json
    import uuid
    from datetime import UTC, datetime
    import psycopg
    from runtime.models import CommandEnvelope
    from runtime.project_source import ProjectSources
    from runtime.source_models import SourceRequest
    from runtime_tests.test_source import commit_all, git
    repo = tmp_path / source_id
    git(f.repo, "clone", "-q", str(f.repo), str(repo))
    git(repo, "config", "user.email", "source-test@example.invalid")
    git(repo, "config", "user.name", "Source Test")
    (repo / "README.md").write_text(source_id + " latest product\n")
    commit_all(repo, "product source")
    commit = git(repo, "rev-parse", "HEAD").decode().strip()
    tree = git(repo, "rev-parse", "HEAD^{tree}").decode().strip()
    store = f.projects.sources.store
    f.projects.sources.close()
    f.projects.sources = ProjectSources(store, [f.repo.parent])
    with psycopg.connect(f.dsn) as conn:
        conn.execute("UPDATE collaboration_sources SET repository_identity=repository_identity || %s::jsonb "
                     "WHERE project_id='project-alpha' AND source_id='source-main'",
                     (json.dumps({"purpose": "management-only-snapshot"}),))
    context = f.authority.context
    identity = "source-product-" + uuid.uuid4().hex
    command = CommandEnvelope(command_id=identity, command_type="source.bind", idempotency_key=identity,
        correlation_id=identity, tenant_id=context.tenant_id, authority_id=context.authority_id,
        authority_incarnation=context.authority_incarnation, principal_ref=context.principal_ref,
        grant_ref=context.grant_ref, target_kind="project", target_id="project-alpha",
        expected_revision=0, issued_at=datetime.now(UTC), deadline=None)
    request = SourceRequest(root=repo, tenant_id=context.tenant_id, scope_id="local-scope",
        root_id="existing-root", route_id="existing-route", expected_commit=commit,
        expected_tree=tree, include_untracked=False)
    f.projects.admit_source(command, project_id="project-alpha", source_id=source_id, request=request,
        repository_identity={"kind": "git", "name": "product-fixture", "origin_host": "another-host",
                             "origin_path": "/origin/product"}, credential=f.credential)
    return repo, commit


def test_owner_product_guidance_is_separate_from_management(source_project, tmp_path):
    f = source_project
    f.authority.access_mode = "owner"
    product, commit = split_product_source(f, tmp_path)
    context = ok(f, "load_project", {"project_id": "project-alpha"})["data"]
    assert context["source_guidance"]["primary_source_id"] == "source-product"
    assert context["source_observation"]["commit"] == commit
    assert context["management_source_observation"]["commit"] == f.commit
    assert context["management_root"]["source_id"] == "source-main"
    assert context["source_guidance"]["repository"]["name"] == "product-fixture"
    assert context["instructions"][0]["source_id"] == "source-main"
    read = ok(f, "read_file", {"project_id": "project-alpha", "path": "README.md"})["data"]
    assert read["content"] == "source-product latest product\n"
    assert read["actual_source"]["root"] == str(product)
    assert read["actual_source"]["commit"] == commit
    assert read["actual_source"]["provider"] == "filesystem"
    sources = ok(f, "list_sources", {"project_id": "project-alpha"})["data"]["items"]
    hint = next(item for item in sources if item["source_id"] == "source-product")
    assert hint["origin_hint"] == {"host": "another-host", "path": "/origin/product"}
    assert hint["current_readable_root"] == str(product)


def test_owner_preferred_primary_root_survives_other_reader_choice(source_project, tmp_path):
    from runtime.project_source import ProjectSources
    from runtime_tests.test_source import git
    f = source_project
    f.authority.access_mode = "owner"
    primary = f.repo
    other = tmp_path / "alternate-reader"
    git(primary, "clone", "-q", str(primary), str(other))
    (other / "README.md").write_text("alternate reader contents\n")
    store = f.projects.sources.store
    f.projects.sources.close()
    f.projects.sources = ProjectSources(store, [primary.parent])
    set_source_preferences(f, primary_source_id="source-main", primary_source_root=str(primary))
    args = {"project_id": "project-alpha", "path": "README.md"}
    chosen = ok(f, "read_file", dict(args, source_root=str(other)))["data"]
    assert chosen["content"] == "alternate reader contents\n"
    assert chosen["actual_source"]["root"] == str(other)
    current = ok(f, "read_file", args)["data"]
    assert current["content"] == "first line\nsecond line\n"
    assert current["actual_source"]["root"] == str(primary)
    state = ok(f, "read_source", {"project_id": "project-alpha"})["data"]
    assert state["actual_source"]["root"] == str(primary)


def test_owner_multiple_product_sources_use_declared_primary(source_project, tmp_path):
    f = source_project
    f.authority.access_mode = "owner"
    primary, _ = split_product_source(f, tmp_path)
    secondary, _ = split_product_source(f, tmp_path, source_id="source-secondary")
    set_source_preferences(f, primary_source_id="source-product", primary_source_root=str(primary))
    args = {"project_id": "project-alpha", "path": "README.md"}
    assert ok(f, "read_file", args)["data"]["actual_source"]["root"] == str(primary)
    selected = ok(f, "read_file", dict(args, source_id="source-secondary"))["data"]
    assert selected["actual_source"]["root"] == str(secondary)
    assert selected["content"] == "source-secondary latest product\n"


def test_owner_management_only_snapshot_is_not_product_default(source_project):
    import json
    import psycopg
    f = source_project
    f.authority.access_mode = "owner"
    with psycopg.connect(f.dsn) as conn:
        conn.execute("UPDATE collaboration_sources SET repository_identity=repository_identity || %s::jsonb",
                     (json.dumps({"purpose": "management-only-snapshot"}),))
    result = f.mcp.call("read_file", {"project_id": "project-alpha", "path": "README.md"})
    assert result["isError"]
    assert result["structuredContent"]["data"]["code"] == "invalid_arguments"
    explicit = ok(f, "read_file", {"project_id": "project-alpha", "source_id": "source-main",
                                  "path": "management/AGENTS.md"})["data"]
    assert "Fixture instructions" in explicit["content"]
    context = ok(f, "load_project", {"project_id": "project-alpha"})["data"]
    assert context["source_guidance"]["primary_source_id"] is None
    assert context["source_guidance"]["version_hint_ref"] is None
    assert context["source_observation"] is None
    assert context["management_source_observation"]["commit"] == f.commit
