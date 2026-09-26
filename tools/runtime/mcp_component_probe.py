"""Exercise the MCP component fixture; never emits passing Runtime Gate records."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import threading
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SOURCE_ROOT = Path(__file__).resolve().parents[2]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from runtime_tests.mcp_component_fixture import McpHttpServer, McpRuntime

MCP_SCENARIOS = (
    "P2-MCP-TEAM-CONFIGURE", "P2-MCP-HARNESS-LIST", "P2-MCP-SEND-ASYNC",
    "P2-MCP-SEND-SYNC", "P2-MCP-BOUNDED-WAIT-CONTINUITY",
    "P2-MCP-TARGET-IDLE-DELIVERY", "P2-MCP-COMPLETION-NOTIFICATION",
    "P2-MCP-SESSION-CONTINUITY", "P2-MCP-RESOURCE-MESSAGE-INBOX",
    "P2-MCP-TYPED-CONTROL", "P2-MCP-WAIT-AGGREGATION",
    "P2-MCP-SKILL-KNOWLEDGE-ROUTING",
)
MANAGEMENT_SCENARIOS = (
    "P2-MGMT-PROJECT-ADOPTION-IDENTITY", "P2-MGMT-PROJECT-ID-ISOLATION",
    "P2-MGMT-LOCAL-CONTEXT-HYDRATION", "P2-MGMT-WEB-CONTEXT-HYDRATION",
    "P2-MGMT-CROSS-PROJECT-LIST", "P2-MGMT-ROUTE-WORK-COLLABORATOR-LISTS",
    "P2-MGMT-EVIDENCE-REVIEW-LISTS", "P2-MGMT-FILESYSTEM-SOURCE-READ",
    "P2-MGMT-EXTERNAL-SOURCE-COORDINATION", "P2-MGMT-WEB-REVIEWER-FLOW",
    "P2-MGMT-WATCH-INBOX-RECOVERY", "P2-MGMT-SKILL-CONTEXT-PRESENTATION",
)


def deadline() -> str:
    return (datetime.now(UTC) + timedelta(minutes=10)).isoformat()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, default=str)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def call(runtime: McpRuntime, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    wire = runtime.call(name, arguments)
    if wire["isError"]:
        raise RuntimeError(name + " failed: " + wire["content"][0]["text"])
    return wire


def http_call(address, token: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{address[1]}/mcp",
        data=canonical({"jsonrpc": "2.0", "id": name, "method": "tools/call",
                        "params": {"name": name, "arguments": arguments}}),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(request, timeout=10).read())["result"]


def result(wire):
    return wire["structuredContent"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--management-root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--skill-catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tree", required=True)
    args = parser.parse_args()
    source = args.source_root.resolve(strict=True)
    management = args.management_root.resolve(strict=True)
    if subprocess_output(source, "HEAD") != args.commit or subprocess_output(source, "HEAD^{tree}") != args.tree:
        raise RuntimeError("source identity changed")
    if subprocess_status(source):
        raise RuntimeError("source checkout is not clean")
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    database = output / "mcp-runtime.sqlite"
    transcript: list[dict[str, Any]] = []
    deliveries: list[str] = []

    def handler(request):
        deliveries.append(request["client_request_id"])
        return {"text": "response:" + request["request"],
                "request_id": request["client_request_id"],
                "evidence": ["mcp-live-handler"]}

    root = McpRuntime(database, args.catalog, profile="root_manager", subject="root",
                      delivery_handler=handler, skill_catalog=args.skill_catalog)
    alpha = root.adopt_project(
        project_id="project-agent-collaboration", name="Agent Collaboration",
        management_root=management, source_root=source,
        instructions={"path": "AGENTS.md", "sha256": hashlib.sha256((management / "AGENTS.md").read_bytes()).hexdigest()},
        manifest={"routes": ".agents/coordination/routes.yaml"},
        policy={"accepted_state_owner": "product-owner"},
        knowledge={"root": ".agents/knowledge", "routing": "metadata-first"},
    )
    alpha_repeat = root.adopt_project(
        project_id="project-agent-collaboration", name="Agent Collaboration",
        management_root=management, source_root=source,
        instructions={"path": "AGENTS.md", "sha256": hashlib.sha256((management / "AGENTS.md").read_bytes()).hexdigest()},
        manifest={"routes": ".agents/coordination/routes.yaml"},
        policy={"accepted_state_owner": "product-owner"}, knowledge={"root": ".agents/knowledge", "routing": "metadata-first"},
    )
    beta = root.adopt_project(
        project_id="project-agent-collaboration-beta", name="Agent Collaboration Beta",
        management_root=management, source_root=source,
        instructions={"path": "AGENTS.md"}, manifest={"routes": "beta"},
    )
    root.register_connection("local-stdio", "stdio", {"profile": "root_manager"})
    root.register_connection("web-loopback", "http", {"profile": "root_manager", "auth": "bearer-reference"})
    root.register_connection("github-source", "external-source", {
        "project_id": "project-agent-collaboration", "source_id": "source-main",
        "commit": args.commit, "tree": args.tree, "credentials": "external-provider-owned",
    })

    team_args = {
        "client_request_id": "team-live-1", "project_id": "project-agent-collaboration",
        "scope_handle": "scope:project-agent-collaboration:runtime", "expected_revision": 0,
        "members": [
            {"slot_id": "root", "role": "root", "harness": "codex", "session_ref": "session-root-1", "capabilities": ["manage", "review", "notify"], "expires_at": deadline()},
            {"slot_id": "worker", "role": "engineer", "harness": "opencode", "session_ref": "session-worker-1", "capabilities": ["execute", "source.read"], "expires_at": deadline()},
            {"slot_id": "reviewer", "role": "reviewer", "harness": "codex-web", "session_ref": "session-reviewer-1", "capabilities": ["review", "source.read"], "expires_at": deadline()},
        ],
        "policies": [{"name": "owner-only"}], "budgets": [{"kind": "messages", "limit": 20}],
        "deadline": deadline(),
    }
    team = call(root, "configure_team", team_args); transcript.append(team)
    team_replay = call(root, "configure_team", team_args); transcript.append(team_replay)
    harnesses = call(root, "list_harnesses", {
        "project_id": "project-agent-collaboration",
        "scope_handle": "scope:project-agent-collaboration:runtime",
        "required_capabilities": ["execute"],
    }); transcript.append(harnesses)
    route = call(root, "create_route", {
        "client_request_id": "route-live-1", "project_id": "project-agent-collaboration",
        "root_handle": alpha["root_handle"], "expected_root_revision": 1,
        "route_id": "runtime", "display_name": "Runtime", "goal": "P2 workflow",
        "source_binding_ids": ["source-main"], "deadline": deadline(),
    }); transcript.append(route)
    route_handle = result(route)["data"]["route_handle"]
    work = call(root, "create_work", {
        "client_request_id": "work-live-1", "project_id": "project-agent-collaboration",
        "route_handle": route_handle, "expected_route_revision": 1,
        "work_item_id": "workflow", "goal": "exercise P2 MCP",
        "accepted_state": {"revision": 0}, "constraints": ["exact project"],
        "source_baseline": args.commit, "required_evidence": ["MCP bytes"],
        "budget": {"messages": 20}, "deadline": deadline(),
    }); transcript.append(work)
    work_handle = result(work)["data"]["work_handle"]

    # Async returns before provider execution.
    async_args = message_args("async-live", work_handle, "worker", "async", args.commit)
    async_wire = call(root, "send_message", async_args); transcript.append(async_wire)
    async_handle = result(async_wire)["data"]["response_handle"]
    async_pre = list(deliveries)
    root.process_pending(project_id="project-agent-collaboration")
    async_wait = call(root, "wait_for_response", wait_args(async_handle)); transcript.append(async_wait)

    sync_args = message_args("sync-live", work_handle, "worker", "sync", args.commit)
    sync_args.update(response_mode="sync", wait_until="response_received", wait_timeout_seconds=5)
    sync_wire = call(root, "send_message", sync_args); transcript.append(sync_wire)

    # Queue-until-idle, reconnect, Session replacement and notification routing.
    root.set_target_busy("project-agent-collaboration", "worker", True)
    idle_wire = call(root, "send_message", message_args("idle-live", work_handle, "worker", "idle", args.commit)); transcript.append(idle_wire)
    idle_handle = result(idle_wire)["data"]["response_handle"]
    idle_before = root.process_pending(project_id="project-agent-collaboration")
    resumed = McpRuntime(database, args.catalog, profile="root_manager", subject="root",
                         delivery_handler=handler, skill_catalog=args.skill_catalog)
    timeout_wire = call(resumed, "wait_for_response", wait_args(idle_handle, timeout=0)); transcript.append(timeout_wire)
    resumed.set_session("project-agent-collaboration", "root", "session-root-2")
    resumed.set_target_busy("project-agent-collaboration", "worker", False)
    idle_completed = resumed.process_pending(project_id="project-agent-collaboration")
    idle_wait = call(resumed, "wait_for_response", wait_args(idle_handle)); transcript.append(idle_wait)
    with resumed._connect() as connection:
        notification = dict(connection.execute(
            "SELECT * FROM notifications WHERE response_handle=?", (idle_handle,),
        ).fetchone())
        notification_count = connection.execute(
            "SELECT count(*) FROM notifications WHERE response_handle=?", (idle_handle,),
        ).fetchone()[0]
    resumed.process_pending(project_id="project-agent-collaboration")
    with resumed._connect() as connection:
        notification_count_after = connection.execute(
            "SELECT count(*) FROM notifications WHERE response_handle=?", (idle_handle,),
        ).fetchone()[0]

    inbox = call(resumed, "check_inbox", {"project_id": "project-agent-collaboration"}); transcript.append(inbox)
    resource_message = call(resumed, "read_message", {
        "project_id": "project-agent-collaboration", "handle": idle_handle, "consume": True,
    }); transcript.append(resource_message)
    notification_handle = result(idle_wire)["data"]["notification_handle"]
    notification_off = call(resumed, "set_notification", {
        "client_request_id": "notification-off", "project_id": "project-agent-collaboration",
        "target_handle": idle_handle, "enabled": False, "expected_revision": 2,
        "reason": "typed-control", "deadline": deadline(),
    }); transcript.append(notification_off)
    stop = call(resumed, "stop_attempt", {
        "client_request_id": "stop-attempt", "project_id": "project-agent-collaboration",
        "attempt_handle": "attempt:project-agent-collaboration:idle", "expected_revision": 1,
        "reason": "typed-control", "deadline": deadline(),
    }); transcript.append(stop)

    # any/all aggregation uses two distinct durable handles.
    resumed.set_target_busy("project-agent-collaboration", "reviewer", True)
    any_one = call(resumed, "send_message", message_args("any-worker", work_handle, "worker", "one", args.commit)); transcript.append(any_one)
    any_two = call(resumed, "send_message", message_args("any-reviewer", work_handle, "reviewer", "two", args.commit)); transcript.append(any_two)
    handles = [result(any_one)["data"]["response_handle"], result(any_two)["data"]["response_handle"]]
    resumed.process_pending(project_id="project-agent-collaboration")
    any_wait = call(resumed, "wait_for_response", {
        "project_id": "project-agent-collaboration", "handles": handles,
        "mode": "any", "until": "response_received", "timeout_seconds": 1,
    }); transcript.append(any_wait)
    resumed.set_target_busy("project-agent-collaboration", "reviewer", False)
    resumed.process_pending(project_id="project-agent-collaboration")
    all_wait = call(resumed, "wait_for_response", {
        "project_id": "project-agent-collaboration", "handles": handles,
        "mode": "all", "until": "response_received", "timeout_seconds": 1,
    }); transcript.append(all_wait)

    context = call(resumed, "load_project", {"project_id": "project-agent-collaboration"}); transcript.append(context)

    # Management and web flows.
    projects = call(resumed, "list_projects", {}); transcript.append(projects)
    mismatch = resumed.call("read_resource", {
        "project_id": "project-agent-collaboration-beta", "handle": alpha["root_handle"],
    }); transcript.append(mismatch)
    routes = call(resumed, "list_routes", {"project_id": "project-agent-collaboration"}); transcript.append(routes)
    works = call(resumed, "list_work", {"project_id": "project-agent-collaboration"}); transcript.append(works)
    collaborators = call(resumed, "list_collaborators", {"project_id": "project-agent-collaboration"}); transcript.append(collaborators)
    evidence_handle = resumed.record_evidence("project-agent-collaboration", "mcp-live", "wire", {"sha256": hashlib.sha256(canonical(transcript)).hexdigest()})
    review_request = call(resumed, "request_review", {
        "client_request_id": "review-live", "project_id": "project-agent-collaboration",
        "work_handle": work_handle, "expected_work_revision": 1, "review_type": "engineering",
        "candidate_ref": args.commit, "source_baseline": args.commit,
        "criteria": ["exact source"], "required_evidence": ["wire"],
        "reviewer_requirements": ["independent"], "deadline": deadline(),
    }); transcript.append(review_request)
    evidence_list = call(resumed, "list_evidence", {"project_id": "project-agent-collaboration"}); transcript.append(evidence_list)
    review_list = call(resumed, "list_reviews", {"project_id": "project-agent-collaboration"}); transcript.append(review_list)
    source_state = call(resumed, "read_source", {"project_id": "project-agent-collaboration", "source_id": "source-main"}); transcript.append(source_state)
    file_list = call(resumed, "list_files", {"project_id": "project-agent-collaboration", "source_id": "source-main", "path": "runtime", "revision": args.commit, "depth": 1}); transcript.append(file_list)
    search = call(resumed, "search_files", {"project_id": "project-agent-collaboration", "source_id": "source-main", "query": "class McpRuntime", "revision": args.commit, "path": "runtime"}); transcript.append(search)
    file_read = call(resumed, "read_file", {"project_id": "project-agent-collaboration", "source_id": "source-main", "path": "runtime/mcp_runtime.py", "revision": args.commit, "start_line": 1, "end_line": 40}); transcript.append(file_read)
    diff = call(resumed, "read_diff", {"project_id": "project-agent-collaboration", "source_id": "source-main", "base_revision": args.commit, "target_revision": args.commit}); transcript.append(diff)
    connections = call(resumed, "list_connections", {}); transcript.append(connections)
    watch = call(resumed, "watch_changes", {
        "client_request_id": "watch-live", "project_id": "project-agent-collaboration",
        "target_handles": [work_handle], "event_kinds": ["review.submitted"],
        "delivery_policy": "inbox", "expected_revision": 0, "deadline": deadline(),
    }); transcript.append(watch)

    reviewer = McpRuntime(database, args.catalog, profile="reviewer", subject="reviewer",
                          skill_catalog=args.skill_catalog)
    web_token = "p2-web-" + "x" * 48
    web = McpHttpServer(reviewer, "127.0.0.1", 0, web_token)
    web_thread = threading.Thread(target=web.serve_forever, daemon=True); web_thread.start()
    try:
        web_context = http_call(web.address, web_token, "load_project", {"project_id": "project-agent-collaboration"})
        web_read = http_call(web.address, web_token, "read_file", {"project_id": "project-agent-collaboration", "source_id": "source-main", "path": "runtime/mcp_runtime.py", "revision": args.commit, "start_line": 1, "end_line": 12})
        review_handle = result(review_request)["data"]["review_handle"]
        web_review = http_call(web.address, web_token, "submit_review", {
            "client_request_id": "submit-review-live", "project_id": "project-agent-collaboration",
            "review_handle": review_handle, "expected_revision": 1, "decision": "pass",
            "findings": [], "evidence_handles": [evidence_handle],
            "source_readback": {"commit": args.commit, "tree": args.tree},
            "unresolved_items": [], "deadline": deadline(),
        })
    finally:
        web.close(); web_thread.join(timeout=5)
    watch_events = resumed.subscription_events(
        "project-agent-collaboration", result(watch)["data"]["subscription_handle"],
    )
    recovered_inbox = call(McpRuntime(database, args.catalog, profile="root_manager", subject="root", skill_catalog=args.skill_catalog),
                           "check_inbox", {"project_id": "project-agent-collaboration"})
    transcript.append(recovered_inbox)

    # Native stdio MCP bytes and profile-filtered discovery.
    stdio_in = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n" +
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n" +
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}}) + "\n"
    )
    stdio_out = io.StringIO(); resumed.serve_stdio(stdio_in, stdio_out)
    stdio_messages = [json.loads(line) for line in stdio_out.getvalue().splitlines()]
    profile_lists = {
        profile: [item["name"] for item in McpRuntime(database, args.catalog, profile=profile,
                   subject=("reviewer" if profile == "reviewer" else "root"), skill_catalog=args.skill_catalog).tools_list()["tools"]]
        for profile in ("root_manager", "reviewer", "engineer", "operator")
    }

    mcp_evidence = {
        "P2-MCP-TEAM-CONFIGURE": {"team": result(team), "replay": result(team_replay)},
        "P2-MCP-HARNESS-LIST": {"harnesses": result(harnesses)},
        "P2-MCP-SEND-ASYNC": {"submission": result(async_wire), "deliveries_before_return": async_pre, "wait": result(async_wait)},
        "P2-MCP-SEND-SYNC": {"submission": result(sync_wire)},
        "P2-MCP-BOUNDED-WAIT-CONTINUITY": {"submission": result(idle_wire), "timeout": result(timeout_wire), "resumed": result(idle_wait)},
        "P2-MCP-TARGET-IDLE-DELIVERY": {"before_idle": idle_before, "after_idle": idle_completed},
        "P2-MCP-COMPLETION-NOTIFICATION": {"notification": notification, "count": notification_count, "count_after_reprocess": notification_count_after},
        "P2-MCP-SESSION-CONTINUITY": {"old_session": "session-root-1", "new_session": notification["session_ref"], "response_handle": idle_handle},
        "P2-MCP-RESOURCE-MESSAGE-INBOX": {"resources": stdio_messages[2]["result"], "inbox": result(inbox), "message": result(resource_message)},
        "P2-MCP-TYPED-CONTROL": {"notification": result(notification_off), "stop": result(stop), "notification_handle": notification_handle},
        "P2-MCP-WAIT-AGGREGATION": {"handles": handles, "any": result(any_wait), "all": result(all_wait)},
        "P2-MCP-SKILL-KNOWLEDGE-ROUTING": {"skills": result(context)["data"]["skills"], "knowledge_hint": result(context)["data"]["knowledge_hint"]},
    }
    management_evidence = {
        "P2-MGMT-PROJECT-ADOPTION-IDENTITY": {"first": alpha, "repeat": alpha_repeat},
        "P2-MGMT-PROJECT-ID-ISOLATION": {"rejection": mismatch["structuredContent"]},
        "P2-MGMT-LOCAL-CONTEXT-HYDRATION": {"context": result(context)},
        "P2-MGMT-WEB-CONTEXT-HYDRATION": {"context": web_context},
        "P2-MGMT-CROSS-PROJECT-LIST": {"projects": result(projects), "beta": beta},
        "P2-MGMT-ROUTE-WORK-COLLABORATOR-LISTS": {"routes": result(routes), "work": result(works), "collaborators": result(collaborators)},
        "P2-MGMT-EVIDENCE-REVIEW-LISTS": {"evidence": result(evidence_list), "reviews": result(review_list)},
        "P2-MGMT-FILESYSTEM-SOURCE-READ": {"source": result(source_state), "files": result(file_list), "search": result(search), "file": result(file_read), "diff": result(diff)},
        "P2-MGMT-EXTERNAL-SOURCE-COORDINATION": {"connections": result(connections), "source_commit": result(source_state)["data"]["current_commit"], "source_tree": result(source_state)["data"]["current_tree"]},
        "P2-MGMT-WEB-REVIEWER-FLOW": {"source": web_read, "review": web_review},
        "P2-MGMT-WATCH-INBOX-RECOVERY": {"subscription": result(watch), "events": watch_events, "inbox": result(recovered_inbox)},
        "P2-MGMT-SKILL-CONTEXT-PRESENTATION": {"skills": result(context)["data"]["skills"], "knowledge_hint": result(context)["data"]["knowledge_hint"], "context_schema": result(context)["data"]["schema_version"]},
    }
    for gate, values in (("P2-MCP-WORKFLOW", mcp_evidence),
                         ("P2-MANAGEMENT-WORKFLOW", management_evidence)):
        gate_root = output / gate; gate_root.mkdir(mode=0o700)
        for scenario, data in values.items():
            evidence = {
                "schema_version": "acs-mcp-component-scenario/1", "gate": gate,
                "scenario_id": scenario, "status": "observed", "source_commit": args.commit,
                "evidence_class": "component_fixture", "gate_eligible": False,
                "source_tree": args.tree, "profile": "root_manager",
                "surface_revision": root.catalog["surface_revision"],
                "observed_at": datetime.now(UTC).isoformat(), "data": data,
                "unresolved_items": [],
            }
            write(gate_root / (scenario + "-evidence.json"), evidence)
    with resumed._connect() as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    transcript_path = output / "mcp-wire-transcript.json"
    write(transcript_path, {"stdio": stdio_messages, "profile_tools": profile_lists,
                            "calls": transcript, "web": {"context": web_context, "review": web_review}})
    inventory = {
        "schema_version": "acs-mcp-component-run/1", "status": "observed",
        "evidence_class": "component_fixture", "gate_eligible": False,
        "source_commit": args.commit, "source_tree": args.tree,
        "database": {"path": str(database), "sha256": sha(database), "bytes": database.stat().st_size},
        "wire": {"path": str(transcript_path), "sha256": sha(transcript_path), "bytes": transcript_path.stat().st_size},
        "gates": {"P2-MCP-WORKFLOW": list(mcp_evidence), "P2-MANAGEMENT-WORKFLOW": list(management_evidence)},
        "profile_tool_counts": {name: len(tools) for name, tools in profile_lists.items()},
        "observed_at": datetime.now(UTC).isoformat(), "unresolved_items": [],
    }
    write(output / "run.json", inventory)
    print(json.dumps({"status": "observed", "evidence_class": "component_fixture",
                      "gate_eligible": False, "mcp_scenarios": len(mcp_evidence),
                      "management_scenarios": len(management_evidence),
                      "database_sha256": inventory["database"]["sha256"],
                      "wire_sha256": inventory["wire"]["sha256"]}, sort_keys=True))


def message_args(identity, work, slot, text, commit):
    return {"client_request_id": identity, "project_id": "project-agent-collaboration",
            "work_handle": work, "expected_work_revision": 1,
            "target": {"scope_id": "runtime", "agent_slot_id": slot},
            "goal": identity, "request": text, "constraints": ["one response"],
            "accepted_revision": 0, "required_evidence": ["native"],
            "deadline": deadline()}


def wait_args(handle, timeout=5):
    return {"project_id": "project-agent-collaboration", "handles": [handle],
            "mode": "all", "until": "response_received", "timeout_seconds": timeout}


def subprocess_output(root: Path, ref: str) -> str:
    import subprocess
    return subprocess.check_output(["git", "rev-parse", ref], cwd=root, text=True).strip()


def subprocess_status(root: Path) -> str:
    import subprocess
    return subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True)


if __name__ == "__main__":
    main()
