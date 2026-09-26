from __future__ import annotations

import io
import json
import threading
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from runtime.mcp_runtime import McpHttpServer, McpRuntime

ROOT = Path(__file__).parents[1]
CATALOG = ROOT / "docs/runtime/p2-mcp-tool-contract.json"
SKILLS = ROOT / "docs/runtime/p2-skill-contract.json"


def deadline() -> str:
    return (datetime.now(UTC) + timedelta(minutes=5)).isoformat()


def runtime(tmp_path, *, profile="root_manager", subject="root", handler=None):
    value = McpRuntime(
        tmp_path / "runtime.sqlite", CATALOG, profile=profile, subject=subject,
        delivery_handler=handler, skill_catalog=SKILLS,
    )
    value.adopt_project(
        project_id="project-alpha", name="Alpha",
        management_root=ROOT / "agent-collabration", source_root=ROOT,
        instructions={"agents": "AGENTS.md"}, manifest={"routes": "routes.yaml"},
        knowledge={"index": ".agents/knowledge/README.md"},
    )
    return value


def ok(value, name, arguments):
    result = value.call(name, arguments)
    assert result["isError"] is False, result
    assert result["structuredContent"]["ok"] is True
    return result["structuredContent"]


def configure(value):
    result = ok(value, "configure_team", {
        "client_request_id": "team-1", "project_id": "project-alpha",
        "scope_handle": "scope:project-alpha:default", "expected_revision": 0,
        "members": [
            {"slot_id": "root", "role": "root", "harness": "codex",
             "session_ref": "session-root-old", "capabilities": ["manage", "review"],
             "expires_at": deadline()},
            {"slot_id": "worker", "role": "engineer", "harness": "opencode",
             "session_ref": "session-worker", "capabilities": ["execute", "source.read"],
             "expires_at": deadline()},
        ],
        "policies": [{"name": "owner-only"}], "budgets": [{"kind": "turns", "limit": 8}],
        "deadline": deadline(),
    })
    assert result["data"]["team_revision"] == 1
    return result


def route_and_work(value):
    route = ok(value, "create_route", {
        "client_request_id": "route-1", "project_id": "project-alpha",
        "root_handle": "project:project-alpha", "expected_root_revision": 1,
        "route_id": "runtime", "display_name": "Runtime", "goal": "P2",
        "source_binding_ids": ["source-main"], "deadline": deadline(),
    })
    work = ok(value, "create_work", {
        "client_request_id": "work-1", "project_id": "project-alpha",
        "route_handle": route["data"]["route_handle"], "expected_route_revision": 1,
        "work_item_id": "mcp-flow", "goal": "exercise MCP",
        "accepted_state": {"revision": 0}, "constraints": ["exact project"],
        "source_baseline": value._project("project-alpha")["revision"],
        "required_evidence": ["wire"], "budget": {"turns": 8}, "deadline": deadline(),
    })
    return route["data"]["route_handle"], work["data"]["work_handle"]


def test_profile_filtered_discovery_and_closed_schemas(tmp_path):
    root = runtime(tmp_path / "root")
    reviewer = runtime(tmp_path / "reviewer", profile="reviewer", subject="reviewer")
    operator = runtime(tmp_path / "operator", profile="operator", subject="operator")
    root_names = [item["name"] for item in root.tools_list()["tools"]]
    reviewer_names = [item["name"] for item in reviewer.tools_list()["tools"]]
    operator_names = [item["name"] for item in operator.tools_list()["tools"]]
    assert "configure_team" in root_names and "submit_review" not in root_names
    assert "submit_review" in reviewer_names and "configure_team" not in reviewer_names
    assert operator_names == ["read_profile", "list_projects", "list_connections", "submit_command"]
    assert all(item["inputSchema"]["additionalProperties"] is False for item in root.tools_list()["tools"])
    denied = reviewer.call("configure_team", {})
    assert denied["isError"] and denied["structuredContent"]["data"]["code"] == "tool_not_available"


def test_async_wait_notification_inbox_and_session_replacement(tmp_path):
    calls = []

    def handler(request):
        calls.append(request["request"])
        return {"text": "OPEN_CODE_DONE", "evidence": ["native-terminal"]}

    value = runtime(tmp_path, handler=handler)
    configure(value)
    _route, work = route_and_work(value)
    value.set_target_busy("project-alpha", "worker", True)
    sent = ok(value, "send_message", {
        "client_request_id": "message-1", "project_id": "project-alpha",
        "work_handle": work, "expected_work_revision": 1,
        "target": {"scope_id": "default", "agent_slot_id": "worker"},
        "goal": "delegate", "request": "perform real task", "constraints": ["one result"],
        "accepted_revision": 0, "required_evidence": ["native"], "deadline": deadline(),
    })
    response = sent["data"]["response_handle"]
    assert sent["state"] == "queued" and calls == []
    assert value.process_pending(project_id="project-alpha") == []

    # A fresh MCP process can recover the same durable response handle.
    resumed = McpRuntime(
        tmp_path / "runtime.sqlite", CATALOG, profile="root_manager", subject="root",
        delivery_handler=handler, skill_catalog=SKILLS,
    )
    pending = ok(resumed, "wait_for_response", {
        "project_id": "project-alpha", "handles": [response], "mode": "all",
        "until": "response_received", "timeout_seconds": 0,
    })
    assert pending["state"] == "pending"
    resumed.set_session("project-alpha", "root", "session-root-new")
    resumed.set_target_busy("project-alpha", "worker", False)
    assert resumed.process_pending(project_id="project-alpha") == [response]
    completed = ok(resumed, "wait_for_response", {
        "project_id": "project-alpha", "handles": [response], "mode": "all",
        "until": "response_received", "timeout_seconds": 1,
    })
    assert completed["state"] == "completed" and calls == ["perform real task"]
    with resumed._connect() as connection:
        notification = connection.execute(
            "SELECT session_ref,state,count(*) FROM notifications WHERE response_handle=?",
            (response,),
        ).fetchone()
    assert tuple(notification) == ("session-root-new", "pending", 1)
    assert resumed.process_pending(project_id="project-alpha") == []
    inbox = ok(resumed, "check_inbox", {"project_id": "project-alpha"})
    assert {item["kind"] for item in inbox["data"]["items"]} == {"message", "response"}
    snapshot = ok(resumed, "read_message", {
        "project_id": "project-alpha", "handle": response, "consume": True,
    })
    assert snapshot["data"]["response"]["text"] == "OPEN_CODE_DONE"


def test_project_context_cross_project_isolation_source_and_skills(tmp_path):
    value = runtime(tmp_path)
    value.adopt_project(
        project_id="project-beta", name="Beta",
        management_root=ROOT / "agent-collabration", source_root=ROOT,
        instructions={"agents": "AGENTS.md"}, manifest={"project": "beta"},
    )
    projects = ok(value, "list_projects", {})
    assert [item["project_id"] for item in projects["data"]["items"]] == ["project-alpha", "project-beta"]
    context = ok(value, "load_project", {"project_id": "project-alpha"})
    assert context["data"]["schema_version"] == "acs-project-context-pack/1"
    assert context["data"]["source_bindings"][0]["project_id"] == "project-alpha"
    assert context["data"]["skills"] and context["data"]["knowledge_hint"][0]["load"] == "metadata_first"
    mismatch = value.call("read_resource", {
        "project_id": "project-beta", "handle": "project:project-alpha",
    })
    assert mismatch["isError"] and mismatch["structuredContent"]["data"]["code"] == "project_handle_mismatch"
    source = context["data"]["source_bindings"][0]
    state = ok(value, "read_source", {"project_id": "project-alpha", "source_id": "source-main"})
    assert state["data"]["current_commit"] == source["commit_id"]
    listing = ok(value, "list_files", {
        "project_id": "project-alpha", "source_id": "source-main", "path": "runtime",
        "revision": source["commit_id"], "depth": 1,
    })
    assert any(item["path"].endswith("mcp_runtime.py") for item in listing["data"]["items"])
    read = ok(value, "read_file", {
        "project_id": "project-alpha", "source_id": "source-main",
        "path": "runtime/mcp_runtime.py", "revision": source["commit_id"],
        "start_line": 1, "end_line": 8,
    })
    assert "Profile-filtered MCP Runtime" in read["data"]["content"]


def test_stdio_and_http_transports_return_native_mcp_bytes(tmp_path):
    value = runtime(tmp_path)
    source = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n"
    )
    target = io.StringIO()
    value.serve_stdio(source, target)
    messages = [json.loads(line) for line in target.getvalue().splitlines()]
    assert messages[0]["result"]["serverInfo"]["name"] == "acs-runtime"
    assert any(item["name"] == "load_project" for item in messages[1]["result"]["tools"])

    server = McpHttpServer(value, "127.0.0.1", 0, "x" * 48)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.address[1]}/mcp",
            data=json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                             "params": {"name": "load_project", "arguments": {"project_id": "project-alpha"}}}).encode(),
            headers={"Authorization": "Bearer " + "x" * 48, "Content-Type": "application/json"},
        )
        response = json.loads(urllib.request.urlopen(request, timeout=5).read())
        assert response["result"]["structuredContent"]["data"]["project_id"] == "project-alpha"
    finally:
        server.close(); thread.join(timeout=5)


def test_product_owner_acceptance_boundary_is_fail_closed(tmp_path):
    value = runtime(tmp_path)
    # accept_work does not admit an extra ad-hoc authorization field outside the
    # closed contract and therefore cannot self-authorize AcceptedStateRevision.
    definition = value.catalog["tools"]["accept_work"]["input_schema"]
    arguments = {name: ([] if name.endswith("handles") else 1 if name.endswith("revision")
                        else "x") for name in definition["required"]}
    arguments.update(project_id="project-alpha", work_handle="work:project-alpha:x", deadline=deadline())
    result = value.call("accept_work", arguments)
    assert result["isError"]
