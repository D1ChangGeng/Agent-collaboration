"""Owner filesystem tools use real PostgreSQL authentication independently of projects."""
import base64

from runtime_tests.test_project_service import ok


def test_owner_file_tools_work_without_project_or_source_registration(project, tmp_path):
    f = project
    f.authority.access_mode = "owner"
    from runtime.project_service import ProjectService
    from runtime.mcp_runtime import McpRuntime
    f.projects = ProjectService(f.projects.service, f.projects.catalog, profile="root_manager")
    f.mcp = McpRuntime(f.projects, lambda: f.credential)
    with f.authority._connect() as conn:
        conn.execute("DELETE FROM collaboration_memberships")
        conn.execute("DELETE FROM collaboration_routes")
        conn.execute("DELETE FROM collaboration_projects")
    path = tmp_path / ".env"
    content = "SYNTHETIC_ONLY=outside_project\n"
    path.write_bytes(content.encode())
    schema = f.mcp.input_schema("read_file")
    assert schema["required"] == ["path"]
    assert "project_id" not in schema["properties"]
    read = ok(f, "read_file", {"path": str(path)})["data"]
    assert read["content"] == content
    assert read["machine_id"] == "local"
    assert read["path"] == str(path)
    assert "read_file" in f.projects.available_tools(f.credential)
    assert "write_file" in f.projects.available_tools(f.credential)
    ok(f, "write_file", {"path": str(tmp_path/"new/created.txt"), "content": "created\n"})
    ok(f, "edit_file", {"path": str(tmp_path/"new/created.txt"), "old_text": "created", "new_text": "edited"})
    assert (tmp_path/"new/created.txt").read_bytes() == b"edited\n"


def test_owner_mcp_context_and_followups_keep_native_bytes(project, tmp_path):
    f = project
    f.authority.access_mode = "owner"
    from runtime.project_service import ProjectService
    from runtime.mcp_runtime import McpRuntime
    f.projects = ProjectService(f.projects.service, f.projects.catalog, profile="root_manager")
    f.mcp = McpRuntime(f.projects, lambda: f.credential)
    ok(f, "select_filesystem", {"cwd": str(tmp_path)})
    binary = bytes(range(256))*3
    (tmp_path/"file.dat").write_bytes(binary)
    result = ok(f, "read_file", {"path": "file.dat", "encoding": "base64", "max_output_bytes": 40})
    received = base64.b64decode(result["data"]["content"])
    while result["follow_ups"]:
        follow = result["follow_ups"][0]
        result = ok(f, follow["tool"], follow["arguments"])
        received += base64.b64decode(result["data"]["content"])
    assert received == binary
    assert ok(f, "filesystem_context", {})["data"]["cwd"] == str(tmp_path)


def test_shared_keeps_source_file_contract_and_machine_tools_unavailable(project):
    f = project
    assert "project_id" in f.mcp.input_schema("read_file")["required"]
    assert "revision" in f.mcp.input_schema("read_file")["required"]
    assert "write_file" not in f.projects.available_tools(f.credential)
    result = f.mcp.call("write_file", {"path": "ignored", "content": "ignored"})
    assert result["isError"]
