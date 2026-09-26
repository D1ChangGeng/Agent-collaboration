"""Isolated ChatGPT component wake probe over the existing project MCP authority.

This probe establishes only whether a mounted Chat component can observe a new
ACS Inbox notification and cause an unsolicited native Chat Turn. It does not
register a receiving Endpoint or pass the P2 Chat receiver Gate.
"""
from __future__ import annotations

import argparse
import json
import sys
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import anyio
from mcp.server.lowlevel import Server
from mcp_types import CallToolResult, ListResourcesResult, ListToolsResult, ReadResourceResult

from runtime.mcp_runtime import McpRuntime
from runtime.project_entry import serve_stdio
from runtime.project_service import ProjectService
from runtime.project_source import ProjectSources
from runtime.surface_config import configured_service


PROJECT = "project-portfolio-sandbox"
TOOL = "open_chat_receiver_probe"
URI = "ui://acs/chat-receiver-probe/v1.html"

HTML = r"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { font: 14px system-ui, sans-serif; margin: 16px; color: #17212b; }
  strong { display: block; margin-bottom: 8px; }
  #status { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
<strong>ACS Chat receiver capability probe</strong>
<div id="status">Waiting for the ChatGPT component bridge.</div>
<script type="module">
const status = document.getElementById('status');
let projectId = null;
let seen = new Set();
let busy = false;
let fired = false;
function show(message) { status.textContent = message; }
function initialize() {
  const bridge = window.openai;
  const output = bridge?.toolOutput;
  if (!bridge || typeof bridge.callTool !== 'function' ||
      typeof bridge.sendFollowUpMessage !== 'function' || !output?.project_id) {
    show('Waiting for component tool output and Chat follow-up capability.');
    return false;
  }
  if (projectId === output.project_id) return true;
  projectId = output.project_id;
  seen = new Set(output.baseline_handles || []);
  show('Connected to ' + projectId + '. Waiting for a new ACS notification.');
  return true;
}
function body(result) {
  if (result?.structuredContent) return result.structuredContent;
  if (result?.structured_content) return result.structured_content;
  if (result?.result?.structuredContent) return result.result.structuredContent;
  return result;
}
async function poll() {
  if (busy || fired || !initialize()) return;
  busy = true;
  try {
    const result = body(await window.openai.callTool('check_inbox', {project_id: projectId}));
    if (result?.ok !== true || result?.data?.project_id !== projectId) {
      show('Inbox observation unavailable; waiting for the next poll.');
      return;
    }
    const notices = result.data.notifications || [];
    for (const notice of notices) {
      const handle = notice.notification_handle;
      if (!handle || seen.has(handle)) continue;
      seen.add(handle);
      if (notice.payload?.kind !== 'team.configured') continue;
      fired = true;
      show('New ACS notification ' + handle + '. Requesting a native Chat follow-up.');
      const prompt = 'ACS Chat receiver probe notification ' + handle +
        '. Please call ACS read_message with project_id=' + projectId +
        ', handle=' + handle + ', consume=false; report the event_id and command_id.';
      await window.openai.sendFollowUpMessage({prompt, scrollToBottom: false});
      show('Chat follow-up submitted for ' + handle + '. Verify the native Turn and ACS readback.');
      break;
    }
  } catch (error) {
    show('Component bridge error: ' + String(error?.name || error));
  } finally {
    busy = false;
  }
}
window.addEventListener('openai:set_globals', initialize);
initialize();
setInterval(poll, 2500);
</script></html>"""


def create_probe_server(runtime: McpRuntime) -> Server:
    async def list_tools(_ctx, _params):
        base = runtime.tools_list()["tools"]
        if "check_inbox" not in {item["name"] for item in base}:
            return ListToolsResult.model_validate({"tools": base})
        base.append({
            "name": TOOL,
            "title": "Open ACS Chat receiver probe",
            "description": "Show a short-lived component that observes new project Inbox notifications and probes native Chat follow-up capability.",
            "inputSchema": {"type": "object", "additionalProperties": False,
                            "required": ["project_id"],
                            "properties": {"project_id": {"type": "string"}}},
            "outputSchema": {"type": "object", "additionalProperties": False,
                             "required": ["project_id", "baseline_handles", "observed_at"],
                             "properties": {"project_id": {"type": "string"},
                                            "baseline_handles": {"type": "array", "items": {"type": "string"}},
                                            "observed_at": {"type": "string"}}},
            "annotations": {"readOnlyHint": True, "destructiveHint": False,
                            "idempotentHint": True, "openWorldHint": False},
            "_meta": {"ui": {"resourceUri": URI, "visibility": ["model", "app"]},
                      "openai/outputTemplate": URI},
        })
        return ListToolsResult.model_validate({"tools": base})

    async def call_tool(_ctx, params):
        if params.name != TOOL:
            return CallToolResult.model_validate(runtime.call(params.name, params.arguments or {}))
        args = params.arguments or {}
        if set(args) != {"project_id"} or args["project_id"] != PROJECT:
            return CallToolResult(content=[{"type": "text", "text": "Probe project unavailable"}],
                                  is_error=True)
        try:
            _, inbox, _ = runtime.service.execute("check_inbox", args,
                                                  runtime.credential_provider())
        except Exception:
            return CallToolResult(content=[{"type": "text", "text": "Probe Inbox unavailable"}],
                                  is_error=True)
        output = {"project_id": PROJECT,
                  "baseline_handles": [item["notification_handle"]
                                       for item in inbox.get("notifications", [])],
                  "observed_at": datetime.now(UTC).isoformat()}
        return CallToolResult.model_validate({
            "content": [{"type": "text", "text": "ACS Chat receiver probe is ready."}],
            "structuredContent": output,
            "isError": False,
        })

    async def list_resources(_ctx, _params):
        projects = runtime.service.execute("list_projects", {}, runtime.credential_provider())[1]
        if PROJECT not in {item["project_id"] for item in projects["items"]}:
            return ListResourcesResult(resources=[])
        return ListResourcesResult.model_validate({"resources": [{"uri": URI,
            "name": "ACS Chat receiver probe UI", "mimeType": "text/html;profile=mcp-app"}]})

    async def read_resource(_ctx, params):
        if str(params.uri) != URI:
            raise ValueError("Unknown probe resource")
        projects = runtime.service.execute("list_projects", {}, runtime.credential_provider())[1]
        if PROJECT not in {item["project_id"] for item in projects["items"]}:
            raise ValueError("Probe project unavailable")
        return ReadResourceResult.model_validate({"contents": [{
            "uri": URI, "mimeType": "text/html;profile=mcp-app", "text": HTML,
            "_meta": {"ui": {"csp": {"connectDomains": [], "resourceDomains": []},
                             "prefersBorder": True}},
        }]})

    return Server("acs-chat-receiver-probe", version="0.1.0",
                  on_list_tools=list_tools, on_call_tool=call_tool,
                  on_list_resources=list_resources, on_read_resource=read_resource)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    args = parser.parse_args(argv)
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    with configured_service(args.config) as (service, settings), ExitStack() as resources:
        configs = settings.artifact_configs()
        roots = (configs[0].authorized_source_roots if len(configs) == 1 else
                 {item.scope_id: item.authorized_source_roots for item in configs
                  if item.authorized_source_roots})
        sources = ProjectSources(service.authority._artifact_store, roots)
        resources.callback(sources.close)
        projects = ProjectService(service, catalog, profile="reviewer", sources=sources)
        runtime = McpRuntime(projects, settings.credential)
        service.authenticate(settings.credential())
        anyio.run(serve_stdio, create_probe_server(runtime))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print('{"error":"probe_unavailable"}', file=sys.stderr)
        raise SystemExit(2)
