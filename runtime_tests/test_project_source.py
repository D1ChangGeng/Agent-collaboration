"""Project Source integration with real PostgreSQL, Git and CAS boundaries."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from runtime.artifacts import LocalArtifactStore
from runtime.models import CommandEnvelope
from runtime.project_service import ProjectService
from runtime.project_source import ProjectSources
from runtime.source_models import SourceRequest
from runtime_tests.test_project_service import CATALOG, deadline, ok, work_args
from runtime_tests.test_project_service import project as project_fixture
from runtime_tests.test_source import commit_all, git, make_repo

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Source uses Linux dirfd backend")


def bind(f, revision=0):
    now = datetime.now(UTC)
    identity = "bind-" + uuid.uuid4().hex
    context = f.authority.context
    command = CommandEnvelope(command_id=identity, command_type="source.bind", idempotency_key=identity,
        correlation_id=identity, tenant_id=context.tenant_id, authority_id=context.authority_id,
        authority_incarnation=context.authority_incarnation, principal_ref=context.principal_ref,
        grant_ref=context.grant_ref, target_kind="project", target_id="project-alpha",
        expected_revision=revision, issued_at=now, deadline=now + timedelta(minutes=5))
    f.commit = git(f.repo, "rev-parse", "HEAD").decode().strip()
    f.tree = git(f.repo, "rev-parse", "HEAD^{tree}").decode().strip()
    request = SourceRequest(root=f.repo, tenant_id=context.tenant_id, scope_id="local-scope",
        root_id="existing-root", route_id="existing-route", expected_commit=f.commit,
        expected_tree=f.tree, include_untracked=False)
    return f.projects.admit_source(command, project_id="project-alpha", source_id="source-main",
        request=request, repository_identity={"kind": "git", "name": "source-fixture"},
        credential=f.credential)


@pytest.fixture
def source_project(setup, tmp_path):
    f = project_fixture.__wrapped__(setup)
    f.repo = make_repo(tmp_path / "source")
    management = f.repo / "management"
    (management / ".agents/knowledge").mkdir(parents=True)
    (management / "AGENTS.md").write_text(
        "# Fixture instructions\n<!-- ACS-PROJECT:BEGIN -->\nproject_id: project-alpha\n"
        "<!-- ACS-PROJECT:END -->\nPreserve the existing Root.\n")
    (management / ".agents/manifest.json").write_text(json.dumps({
        "root_id": "existing-root", "project_id": "project-alpha"}))
    (management / ".agents/knowledge/index.yaml").write_text("documents: []\n")
    skills = f.repo / "skills/acs-project-context"
    (skills / "references").mkdir(parents=True)
    (skills / "SKILL.md").write_text("# SKILL_BODY_MARKER\nRead references/model.md for identities.\n")
    (skills / "references/model.md").write_text("MODEL_REFERENCE_MARKER\nRoot is a durable identity.\n")
    (skills / "references/decisions.md").write_text("UNSELECTED_REFERENCE_MARKER\n")
    (f.repo / "skills/catalog.json").write_text(json.dumps({"skills": {
        "acs-project-context": {"description": "Project and Root identity knowledge.",
                                "spec": "acs-project-context/SKILL.md"}}}))
    (f.repo / "README.md").write_text("first line\nsecond line\n")
    (f.repo / ".env").write_text("DO_NOT_EXPORT=fixture-secret\n")
    commit_all(f.repo, "source fixture")
    context = {"routes": [{"route_id": "existing-route", "scope_id": "local-scope"}],
        "management": {"source_id": "source-main", "path": "management"},
        "instruction_paths": ["management/AGENTS.md"],
        "knowledge_index_paths": ["management/.agents/knowledge/index.yaml"],
        "skill_catalog": {"source_id": "source-main", "path": "skills/catalog.json"}}
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE collaboration_projects SET context_manifest=%s", (json.dumps(context),))
        connection.execute("UPDATE grants SET permissions=permissions || %s::jsonb "
                           "WHERE grant_ref='grant:p1'", (json.dumps([
                               "source.manage", "artifact.read", "artifact.write"]),))
    store = LocalArtifactStore(tmp_path / "source-cas", scope_id="local-scope")
    f.projects.sources = ProjectSources(store, [f.repo])
    try:
        bind(f)
        yield f
    finally:
        f.projects.sources.close()
        store.close()


def read_args(f, path="README.md", **extra):
    return {"project_id": "project-alpha", "source_id": "source-main", "path": path,
            "revision": f.commit, **extra}


def test_source_reads_return_exact_cas_bytes_and_current_git_observation(source_project):
    f = source_project
    read = ok(f, "read_file", read_args(f, start_line=2, end_line=2))
    assert read["data"]["content"] == "second line\n"
    state = ok(f, "read_source", {"project_id": "project-alpha", "source_id": "source-main"})
    assert state["state"] == "current"
    assert state["data"]["commit"] == f.commit and state["data"]["tree"] == f.tree
    assert state["data"]["branch"] == git(f.repo, "branch", "--show-current").decode().strip()
    assert state["data"]["push"] == "not-measured"
    assert str(f.repo) not in json.dumps(state)
    connections = ok(f, "list_connections", {"project_id": "project-alpha", "kinds": ["source"]})
    assert connections["data"]["items"][0]["source_id"] == "source-main"
    assert str(f.repo) not in json.dumps(connections)


def test_completed_response_reads_digest_verified_native_artifact(source_project):
    f = source_project
    ok(f, "create_work", work_args())
    sent = ok(f, "send_message", {
        "client_request_id": "response-readback-send", "project_id": "project-alpha",
        "work_handle": "work:project-alpha:mcp-work", "expected_work_revision": 0,
        "target": {"scope_id": "local-scope", "agent_slot_id": "local-slot"},
        "goal": "read native result", "request": "return exact response artifact",
        "constraints": ["digest verified"], "accepted_revision": 0,
        "required_evidence": ["native response artifact"], "activation": "message_only",
        "deadline": deadline(),
    })["data"]
    native = {"assistant_text": ["NATIVE_RESPONSE_MARKER"], "outcome": "completed"}
    encoded = json.dumps(native, sort_keys=True, separators=(",", ":")).encode()
    reference = f.projects.sources.store.put_bytes(
        encoded, kind="readback", media_type="application/json",
    )
    evidence = {"receipt_id": "response-readback-receipt",
        "response_artifact_ref": "artifact:" + reference.sha256,
        "response_digest": reference.sha256}
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE delivery_messages SET state='delivered',"
                           "receipt_high_water='response_received' WHERE message_id=%s",
                           (sent["message_id"],))
        connection.execute("INSERT INTO delivery_receipts(tenant_id,message_id,receipt_id,layer,evidence_json) "
                           "VALUES ('local-tenant',%s,%s,'response_received',%s)",
                           (sent["message_id"], evidence["receipt_id"], json.dumps(evidence)))
    args = {"project_id": "project-alpha", "handle": sent["response_handle"], "consume": False}
    read = ok(f, "read_message", args)["data"]
    assert read["response"] == native
    assert read["response_artifact"] == {
        **reference.model_dump(mode="json"), "opaque_ref": "artifact:" + reference.sha256,
        "content_state": "inline",
    }
    bounded = ok(f, "read_message", dict(args, max_inline_bytes=1))["data"]
    assert "response" not in bounded
    assert bounded["response_artifact"]["content_state"] == "verified_reference"
    f.authority._artifact_store = f.projects.sources.store
    artifact_only = ProjectService(f.projects.service, CATALOG, profile="root_manager")
    artifact_read = artifact_only.execute("read_message", args, f.credential)[1]
    assert artifact_read["response"] == native
    assert artifact_read["response_artifact"]["content_state"] == "inline"
    artifact_handle = "artifact:project-alpha:local-scope." + reference.sha256
    resource = ok(f, "read_resource", {"project_id": "project-alpha",
        "handle": artifact_handle, "view": "content", "content_mode": "inline"})["data"]
    assert json.loads(resource["content"]) == native
    assert resource["content_state"] == "inline"
    assert f.mcp.call("read_resource", {"project_id": "another-project",
        "handle": artifact_handle})["isError"]
    (f.projects.sources.store.root / reference.path).unlink()
    missing = f.mcp.call("read_message", args)
    assert missing["structuredContent"]["data"]["code"] == "source_unavailable"


def test_context_hydrates_instructions_and_metadata_then_loads_one_reference(source_project, monkeypatch):
    f = source_project
    loaded = []
    original = f.projects.sources.store.read
    def record(ref):
        data = original(ref)
        loaded.append(data)
        return data
    monkeypatch.setattr(f.projects.sources.store, "read", record)
    context = ok(f, "load_project", {"project_id": "project-alpha"})
    assert context["state"] == "current", context
    assert "Preserve the existing Root" in context["data"]["instructions"][0]["content"]
    assert context["data"]["skills"] == [{"name": "acs-project-context",
        "description": "Project and Root identity knowledge."}]
    assert not any(b"SKILL_BODY_MARKER" in value or b"MODEL_REFERENCE_MARKER" in value
                   or b"UNSELECTED_REFERENCE_MARKER" in value for value in loaded)
    follow = next(item for item in context["follow_ups"] if item["rel"] == "read_skill")
    skill = ok(f, follow["tool"], follow["arguments"])
    assert "SKILL_BODY_MARKER" in skill["data"]["content"]
    assert not any(b"UNSELECTED_REFERENCE_MARKER" in value for value in loaded)
    ref = ok(f, "read_file", read_args(f, "skills/acs-project-context/references/model.md"))
    assert "MODEL_REFERENCE_MARKER" in ref["data"]["content"]
    assert not any(b"UNSELECTED_REFERENCE_MARKER" in value for value in loaded)
    assert str(f.repo) not in json.dumps(context)


@pytest.mark.parametrize("path", ["../README.md", "/etc/passwd", "management/../README.md",
                                  ".env", "management\\AGENTS.md"])
def test_source_path_and_secret_boundaries(source_project, path):
    reply = source_project.mcp.call("read_file", read_args(source_project, path))
    assert reply["isError"]
    assert "fixture-secret" not in json.dumps(reply)


def test_source_revision_is_exact_and_project_isolation_is_enforced(source_project):
    f = source_project
    assert f.mcp.call("read_file", dict(read_args(f), revision="HEAD"))["isError"]
    assert f.mcp.call("read_file", dict(read_args(f), project_id="project-alpha-extra"))["isError"]


def test_dirty_current_state_does_not_change_immutable_revision(source_project):
    f = source_project
    (f.repo / "README.md").write_text("changed after admission\n")
    state = ok(f, "read_source", {"project_id": "project-alpha", "source_id": "source-main"})
    assert state["state"] == "stale" and state["data"]["working_tree"] == "dirty"
    assert ok(f, "load_project", {"project_id": "project-alpha"})["state"] == "stale"
    assert ok(f, "read_file", read_args(f))["data"]["content"] == "first line\nsecond line\n"


def test_diff_between_two_admitted_revisions(source_project):
    f = source_project
    before = f.commit
    (f.repo / "README.md").write_text("replacement line\n")
    commit_all(f.repo, "replace source")
    bind(f, revision=1)
    diff = ok(f, "read_diff", {"project_id": "project-alpha", "source_id": "source-main",
        "base_revision": before, "target_revision": f.commit, "paths": ["README.md"]})
    assert "-first line" in diff["data"]["content"] and "+replacement line" in diff["data"]["content"]
    assert diff["data"]["changes"][0]["path"] == "README.md"
    assert ok(f, "read_file", dict(read_args(f), revision=before))["data"]["content"].startswith("first line")


def test_source_revocation_rechecked_at_each_byte_read(source_project):
    f = source_project
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE grants SET permissions=permissions - 'artifact.read' "
                           "WHERE grant_ref='grant:p1'")
    assert f.mcp.call("read_file", read_args(f))["isError"]
    context = ok(f, "load_project", {"project_id": "project-alpha"})
    assert context["state"] == "partial"
    assert context["data"]["missing_context"] == ["source_read_authorization"]
    assert "instructions" not in context["data"]


def test_list_and_search_provide_bounded_cursors(source_project):
    f = source_project
    listed = ok(f, "list_files", read_args(f, ".", limit=2))
    assert len(listed["data"]["items"]) == 2 and listed["data"]["next_cursor"]
    assert all(item["path"] != ".env" for item in listed["data"]["items"])
    searched = ok(f, "search_files", {"project_id": "project-alpha", "source_id": "source-main",
        "revision": f.commit, "query": "durable identity", "path": "skills"})
    assert [item["path"] for item in searched["data"]["items"]] == ["skills/acs-project-context/references/model.md"]


def test_manifest_identity_mismatch_blocks_context(source_project):
    f = source_project
    (f.repo / "management/.agents/manifest.json").write_text(json.dumps({
        "project_id": "project-other", "root_id": "existing-root"}))
    commit_all(f.repo, "identity mismatch")
    bind(f, revision=1)
    assert f.mcp.call("load_project", {"project_id": "project-alpha"})["isError"]
    assert f.mcp.call("create_work", work_args())["isError"]


def test_current_identity_edit_blocks_mutations_before_new_snapshot(source_project):
    f = source_project
    (f.repo / "management/AGENTS.md").write_text("project_id: project-other\n")
    assert f.mcp.call("create_work", work_args())["isError"]
    with psycopg.connect(f.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM collaboration_work_links").fetchone()[0] == 0


def test_ordinary_source_edits_preserve_project_management_authority(source_project):
    f = source_project
    (f.repo / "README.md").write_text("engineering is in progress\n")
    assert ok(f, "create_work", dict(work_args(), source_baseline=f.commit))["state"] == "created"
    assert ok(f, "load_project", {"project_id": "project-alpha"})["state"] == "stale"


def test_large_instruction_returns_explicit_followup_in_bounded_context(source_project):
    f = source_project
    with (f.repo / "management/AGENTS.md").open("a") as stream:
        stream.write("Detailed instruction content.\n" * 400)
    commit_all(f.repo, "long instruction")
    bind(f, revision=1)
    context = ok(f, "load_project", {"project_id": "project-alpha", "max_inline_bytes": 4096})
    assert context["state"] == "partial"
    assert "content" not in context["data"]["instructions"][0]
    assert len(json.dumps(context["data"], separators=(",", ":"), sort_keys=True).encode()) <= 4096
    follow = next(item for item in context["follow_ups"] if item["rel"] == "read_instructions")
    assert follow["arguments"]["project_id"] == "project-alpha"
    assert follow["arguments"]["revision"] == f.commit


def test_sdk_process_hydrates_context_and_reads_selected_skill(source_project, tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from runtime_tests.test_project_service import ROOT
    from runtime_tests.test_surfaces import profile

    f = source_project
    config, environment, secret = profile(tmp_path, dsn=f.dsn, context=f.authority.context,
        extra={"artifacts": {"root": str(f.projects.sources.store.root), "scope_id": "local-scope",
                              "authorized_source_roots": [str(f.repo)]}})

    async def exercise():
        parameters = StdioServerParameters(command=sys.executable, args=["-m", "runtime.project_entry",
            "--config", str(config), "--catalog", str(ROOT / "docs/runtime/p2-mcp-tool-contract.json"),
            "--profile", "root_manager"], env=environment, cwd=str(ROOT))
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
            async with (stdio_client(parameters, errlog=errors) as streams,
                        ClientSession(*streams, read_timeout_seconds=20) as session):
                await session.initialize()
                tools = await session.list_tools()
                pack = await session.call_tool("load_project", {"project_id": "project-alpha"})
                assert not pack.is_error, pack
                follow = next(item for item in pack.structured_content["follow_ups"] if item["rel"] == "read_skill")
                body = await session.call_tool(follow["tool"], follow["arguments"])
            errors.seek(0)
            assert secret not in errors.read()
        return tools, pack, body

    tools, pack, body = asyncio.run(exercise())
    assert {"read_file", "read_source", "read_diff"} <= {item.name for item in tools.tools}
    assert pack.structured_content["state"] == "current"
    assert not body.is_error and "SKILL_BODY_MARKER" in body.structured_content["data"]["content"]
