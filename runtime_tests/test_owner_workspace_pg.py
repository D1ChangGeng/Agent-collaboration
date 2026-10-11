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
