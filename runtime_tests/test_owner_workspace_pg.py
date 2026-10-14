"""Current owner workspace reads retain exact committed snapshots."""
from runtime_tests.test_project_service import ok

pytest_plugins = ("runtime_tests.test_project_source",)


def select_owner(f):
    from runtime_tests.test_current_project_files_pg import owner
    return owner(f)


def test_owner_reads_current_workspace_and_retains_commit_snapshot(source_project):
    f=source_project
    select_owner(f)
    (f.repo/"README.md").write_text("current workspace content\n")
    (f.repo/"new-module.py").write_text("NEW_MODULE = True\n")
    current=ok(f,"read_file",{"path":str(f.repo/"README.md")})["data"]
    assert current["content"]=="current workspace content\n"
    retained=ok(f,"read_source_file",{"project_id":"project-alpha","source_id":"source-main","revision":f.commit,"path":"README.md"})["data"]
    assert retained["content"]=="first line\nsecond line\n"
    listing=ok(f,"list_directory",{"path":str(f.repo)})["data"]
    assert "new-module.py" in str(listing)
    assert retained["revision"]==f.commit



def test_owner_session_directory_selects_current_machine_files(source_project):
    f=source_project
    select_owner(f)
    ok(f,"select_filesystem",{"cwd":str(f.repo)})
    assert ok(f,"read_file",{"path":"README.md"})["data"]["content"]=="first line\nsecond line\n"
    for name in ("read_source_file","read_source","list_source_files","search_source_files"):
        assert {"source_id","revision"} <= set(f.mcp.input_schema(name)["required"])
    assert f.mcp.call("read_source",{"project_id":"project-alpha"})["isError"]


def test_owner_current_files_follow_new_commit_and_retain_archive(source_project):
    from runtime_tests.test_source import commit_all, git
    f=source_project
    select_owner(f)
    baseline=f.commit
    (f.repo/"README.md").write_text("latest selected checkout\n")
    commit_all(f.repo,"advance selected checkout")
    assert git(f.repo,"rev-parse","HEAD").decode().strip()!=baseline
    assert ok(f,"read_file",{"path":str(f.repo/"README.md")})["data"]["content"]=="latest selected checkout\n"
    retained=ok(f,"read_source_file",{"project_id":"project-alpha","source_id":"source-main","revision":baseline,"path":"README.md"})["data"]
    assert retained["content"]=="first line\nsecond line\n"
    state=ok(f,"read_source",{"project_id":"project-alpha","source_id":"source-main","revision":baseline})["data"]
    assert state["commit"]==baseline and state["record_kind"]=="source_archive"


def test_owner_location_choice_reads_another_checkout(source_project,tmp_path):
    from runtime_tests.test_source import git
    f=source_project
    select_owner(f)
    other=tmp_path/"other-checkout"
    git(f.repo,"clone","-q",str(f.repo),str(other))
    (other/"README.md").write_text("selected other checkout\n")
    chosen=ok(f,"read_file",{"cwd":str(other),"path":"README.md"})["data"]
    assert chosen["content"]=="selected other checkout\n" and chosen["resolved_path"]==str(other/"README.md")
    assert ok(f,"read_file",{"path":str(f.repo/"README.md")})["data"]["content"]=="first line\nsecond line\n"


def test_owner_selects_primary_or_linked_worktree_explicitly(source_project,tmp_path):
    from runtime_tests.test_source import git
    f=source_project
    select_owner(f)
    primary=f.repo
    linked=tmp_path/"linked-worktree"
    git(primary,"worktree","add","-q","-b","reader-worktree",str(linked))
    (primary/"README.md").write_text("current primary worktree\n")
    assert ok(f,"read_file",{"cwd":str(primary),"path":"README.md"})["data"]["content"]=="current primary worktree\n"
    assert ok(f,"read_file",{"cwd":str(linked),"path":"README.md"})["data"]["content"]=="first line\nsecond line\n"


def test_owner_context_uses_current_management_and_skill_files(source_project):
    f=source_project
    select_owner(f)
    context=ok(f,"load_project",{"project_id":"project-alpha"})
    assert context["data"]["source_guidance"]=={"reader":"machine_filesystem","version_selection":"agent_explicit"}
    assert "source_bindings" not in context["data"]
    followup=next(item for item in context["follow_ups"] if item["rel"]=="read_skill")
    assert followup["tool"]=="read_file" and "revision" not in followup["arguments"]
    assert "SKILL_BODY_MARKER" in ok(f,followup["tool"],followup["arguments"])["data"]["content"]


def test_owner_source_paging_keeps_explicitly_selected_archive_bytes(source_project):
    f=source_project
    select_owner(f)
    first=ok(f,"read_source_file",{"project_id":"project-alpha","source_id":"source-main","revision":f.commit,"path":"README.md","max_inline_bytes":12})
    follow=first["follow_ups"][0]
    assert follow["arguments"]["revision"]==f.commit
    (f.repo/"README.md").write_text("new contents after first page\n")
    assert ok(f,follow["tool"],follow["arguments"])["data"]["content"]=="second line\n"


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
                     (json.dumps({"purpose": "management-only-snapshot", "original_management_root": str(f.repo / "management")}),))
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


def test_owner_product_archive_and_current_management_are_separate(source_project,tmp_path):
    f=source_project
    select_owner(f)
    product,commit=split_product_source(f,tmp_path)
    context=ok(f,"load_project",{"project_id":"project-alpha"})["data"]
    assert "source_observation" not in context and "primary_source_id" not in context["source_guidance"]
    assert context["management_root"]["path"]==str(f.repo/"management")
    assert ok(f,"read_file",{"path":str(product/"README.md")})["data"]["content"]=="source-product latest product\n"
    archived=ok(f,"read_source",{"project_id":"project-alpha","source_id":"source-product","revision":commit})["data"]
    assert archived["commit"]==commit and archived["repository"]["name"]=="product-fixture"
    sources=ok(f,"list_sources",{"project_id":"project-alpha"})["data"]["items"]
    record=next(item for item in sources if item["source_id"]=="source-product")
    assert record["record_kind"]=="source_archive" and "default_read" not in record
    assert record["origin_hint"]=={"host":"another-host","path":"/origin/product"}


def test_owner_explicit_reader_override_preserves_session_directory(source_project,tmp_path):
    from runtime_tests.test_source import git
    f=source_project
    select_owner(f)
    primary=f.repo
    other=tmp_path/"alternate-reader"
    git(primary,"clone","-q",str(primary),str(other))
    (other/"README.md").write_text("alternate reader contents\n")
    set_source_preferences(f,primary_source_id="source-main",primary_source_root=str(primary))
    ok(f,"select_filesystem",{"cwd":str(primary)})
    assert ok(f,"read_file",{"cwd":str(other),"path":"README.md"})["data"]["content"]=="alternate reader contents\n"
    assert ok(f,"read_file",{"path":"README.md"})["data"]["content"]=="first line\nsecond line\n"
    assert ok(f,"filesystem_context",{})["data"]["cwd"]==str(primary)


def test_owner_multiple_recorded_sources_do_not_select_a_file_reader(source_project,tmp_path):
    f=source_project
    select_owner(f)
    primary,_=split_product_source(f,tmp_path)
    secondary,_=split_product_source(f,tmp_path,source_id="source-secondary")
    set_source_preferences(f,primary_source_id="source-product",primary_source_root=str(primary))
    ok(f,"select_filesystem",{"cwd":str(secondary)})
    assert ok(f,"read_file",{"path":"README.md"})["data"]["content"]=="source-secondary latest product\n"
    assert ok(f,"read_file",{"cwd":str(primary),"path":"README.md"})["data"]["content"]=="source-product latest product\n"
    assert f.mcp.call("read_source_file",{"project_id":"project-alpha","path":"README.md"})["isError"]


def test_owner_management_archive_has_no_default_file_selection(source_project):
    import json

    import psycopg
    f=source_project
    select_owner(f)
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE collaboration_sources SET repository_identity=repository_identity || %s::jsonb",(json.dumps({"purpose":"management-only-snapshot"}),))
    assert ok(f,"read_file",{"path":str(f.repo/"README.md")})["data"]["content"]=="first line\nsecond line\n"
    context=ok(f,"load_project",{"project_id":"project-alpha"})["data"]
    assert "primary_source_id" not in context["manifest"] and "source_observation" not in context
    assert f.mcp.call("read_source_file",{"project_id":"project-alpha","path":"README.md"})["isError"]
