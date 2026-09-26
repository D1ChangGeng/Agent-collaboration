"""Isolated ChatGPT component wake probe over the existing project MCP authority.

This probe establishes only whether a mounted Chat component can observe a new
ACS Inbox notification and cause an unsolicited native Chat Turn. It does not
register a receiving Endpoint or pass the P2 Chat receiver Gate.
"""
from __future__ import annotations

import argparse
import json
import secrets
import sqlite3
import sys
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
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
CLAIM_TOOL = "claim_chat_receiver_probe_wake"
URI = "ui://acs/chat-receiver-probe/v1.html"
LEASE_SECONDS = 300


class ProbeJournal:
    """Private, bounded UI probe claims; never an ACS Domain authority."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS probes (probe_id TEXT PRIMARY KEY, "
                       "project_id TEXT NOT NULL, expires_at TEXT NOT NULL, "
                       "baseline_handles TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS claims (project_id TEXT NOT NULL, "
                       "notification_handle TEXT NOT NULL, probe_id TEXT NOT NULL, "
                       "claimed_at TEXT NOT NULL, PRIMARY KEY(project_id,notification_handle))")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA busy_timeout=5000")
        return db

    def open(self, project_id: str, baseline_handles: list[str]):
        now = datetime.now(UTC)
        probe_id = secrets.token_urlsafe(24)
        expires_at = (now + timedelta(seconds=LEASE_SECONDS)).isoformat()
        with self._connect() as db:
            db.execute("INSERT INTO probes VALUES (?,?,?,?)",
                       (probe_id, project_id, expires_at, json.dumps(baseline_handles)))
        return {"project_id": project_id, "probe_id": probe_id,
                "baseline_handles": baseline_handles, "observed_at": now.isoformat(),
                "expires_at": expires_at}

    def claim(self, project_id: str, probe_id: str, notification_handle: str,
              notifications: list[dict]):
        now = datetime.now(UTC)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT project_id,expires_at,baseline_handles FROM probes "
                             "WHERE probe_id=?", (probe_id,)).fetchone()
            if (row is None or row[0] != project_id or
                    datetime.fromisoformat(row[1]) <= now or
                    notification_handle in json.loads(row[2])):
                return False
            if not any(item.get("notification_handle") == notification_handle and
                       item.get("notification_enabled") is True and
                       item.get("payload", {}).get("kind") == "team.configured"
                       for item in notifications):
                return False
            result = db.execute("INSERT OR IGNORE INTO claims VALUES (?,?,?,?)",
                                (project_id, notification_handle, probe_id, now.isoformat()))
            return result.rowcount == 1

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
let probeId = null;
let expiresAt = 0;
let seen = new Set();
let busy = false;
let fired = false;
let timer = null;
function show(message) { status.textContent = message; }
function expired() {
  if (Date.now() < expiresAt) return false;
  if (timer !== null) clearInterval(timer);
  show('Probe expired. Open a new probe to observe further notifications.');
  return true;
}
function initialize() {
  const bridge = window.openai;
  const output = bridge?.toolOutput;
  if (!bridge || typeof bridge.callTool !== 'function' ||
      typeof bridge.sendFollowUpMessage !== 'function' || !output?.project_id ||
      !output?.probe_id || !output?.expires_at) {
    show('Waiting for component tool output and Chat follow-up capability.');
    return false;
  }
  if (probeId === output.probe_id) return !expired();
  projectId = output.project_id;
  probeId = output.probe_id;
  expiresAt = Date.parse(output.expires_at);
  if (!Number.isFinite(expiresAt)) return false;
  seen = new Set(output.baseline_handles || []);
  fired = false;
  if (expired()) return false;
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
  if (busy || fired || !initialize() || expired()) return;
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
      if (notice.payload?.kind !== 'team.configured' ||
          notice.notification_enabled !== true) {
        seen.add(handle);
        continue;
      }
      const claimed = body(await window.openai.callTool('claim_chat_receiver_probe_wake',
        {project_id: projectId, probe_id: probeId, notification_handle: handle}));
      seen.add(handle);
      if (claimed?.claimed !== true) continue;
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
timer = setInterval(poll, 2500);
if (expiresAt && Date.now() >= expiresAt) clearInterval(timer);
</script></html>"""


def create_probe_server(runtime: McpRuntime, journal_path: Path) -> Server:
    journal = ProbeJournal(journal_path)

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
                             "required": ["project_id", "probe_id", "baseline_handles",
                                          "observed_at", "expires_at"],
                             "properties": {"project_id": {"type": "string"},
                                            "probe_id": {"type": "string"},
                                            "baseline_handles": {"type": "array", "items": {"type": "string"}},
                                            "observed_at": {"type": "string"},
                                            "expires_at": {"type": "string"}}},
            "annotations": {"readOnlyHint": False, "destructiveHint": False,
                            "idempotentHint": False, "openWorldHint": False},
            "_meta": {"ui": {"resourceUri": URI, "visibility": ["model", "app"]},
                      "openai/outputTemplate": URI},
        })
        base.append({
            "name": CLAIM_TOOL,
            "title": "Claim ACS Chat receiver probe wake",
            "description": "Claim one enabled notification for the active diagnostic Chat component.",
            "inputSchema": {"type": "object", "additionalProperties": False,
                            "required": ["project_id", "probe_id", "notification_handle"],
                            "properties": {"project_id": {"type": "string"},
                                           "probe_id": {"type": "string"},
                                           "notification_handle": {"type": "string"}}},
            "outputSchema": {"type": "object", "additionalProperties": False,
                             "required": ["claimed"], "properties": {"claimed": {"type": "boolean"}}},
            "annotations": {"readOnlyHint": False, "destructiveHint": False,
                            "idempotentHint": False, "openWorldHint": False},
            "_meta": {"ui": {"visibility": ["app"]}},
        })
        return ListToolsResult.model_validate({"tools": base})

    async def call_tool(_ctx, params):
        if params.name not in {TOOL, CLAIM_TOOL}:
            return CallToolResult.model_validate(runtime.call(params.name, params.arguments or {}))
        args = params.arguments or {}
        required = ({"project_id"} if params.name == TOOL else
                    {"project_id", "probe_id", "notification_handle"})
        if (set(args) != required or args.get("project_id") != PROJECT or
                any(not isinstance(value, str) or not value for value in args.values())):
            return CallToolResult(content=[{"type": "text", "text": "Probe project unavailable"}],
                                  is_error=True)
        try:
            _, inbox, _ = runtime.service.execute("check_inbox", {"project_id": PROJECT},
                                                  runtime.credential_provider())
        except Exception:  # noqa: BLE001 - do not expose private Inbox/auth details to the widget
            return CallToolResult(content=[{"type": "text", "text": "Probe Inbox unavailable"}],
                                  is_error=True)
        if params.name == CLAIM_TOOL:
            claimed = journal.claim(PROJECT, args["probe_id"], args["notification_handle"],
                                    inbox.get("notifications", []))
            return CallToolResult.model_validate({
                "content": [{"type": "text", "text": "Probe wake claim recorded." if claimed
                             else "Probe wake claim unavailable."}],
                "structuredContent": {"claimed": claimed}, "isError": False})
        output = journal.open(PROJECT, [item["notification_handle"]
                                        for item in inbox.get("notifications", [])])
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
        anyio.run(serve_stdio, create_probe_server(
            runtime, args.config.parent / "chat-receiver-probe-journal.sqlite3"))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 - keep private startup errors out of the MCP wire
        print('{"error":"probe_unavailable"}', file=sys.stderr)
        raise SystemExit(2) from None
