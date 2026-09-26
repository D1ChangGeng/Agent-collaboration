"""Verify the diagnostic MCP UI uses the pinned SDK wire shapes and project guard."""
from __future__ import annotations

import asyncio
import shutil
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from mcp_types import CallToolRequestParams, ReadResourceRequestParams

from tools.runtime.p2_chat_receiver_widget_probe import (
    CLAIM_TOOL,
    HTML,
    PROJECT,
    TOOL,
    URI,
    create_probe_server,
)


class _Service:
    def __init__(self):
        self.notifications = [{"notification_handle": "notification:project-portfolio-sandbox:old"}]

    def execute(self, name, args, _credential):
        if name == "list_projects":
            return "observed", {"items": [{"project_id": PROJECT}]}, []
        if name == "check_inbox" and args == {"project_id": PROJECT}:
            return "observed", {"project_id": PROJECT,
                "notifications": self.notifications}, []
        raise AssertionError((name, args))


class _Runtime:
    service = _Service()

    @staticmethod
    def credential_provider():
        return "fixture-credential"

    @staticmethod
    def tools_list():
        return {"tools": [{"name": "check_inbox", "description": "Read Inbox",
            "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}},
                            "required": ["project_id"]}}]}

    @staticmethod
    def call(name, arguments):
        assert name == "check_inbox" and arguments == {"project_id": PROJECT}
        return {"content": [{"type": "text", "text": "Inbox"}],
                "structuredContent": {"ok": True, "data": {"project_id": PROJECT,
                    "notifications": []}}, "isError": False}


def _request(server, method, params=None):
    return asyncio.run(server._request_handlers[method].handler(None, params))


def test_probe_exposes_authorized_component_and_exact_initial_inbox_baseline(tmp_path):
    server = create_probe_server(_Runtime(), tmp_path / "claims.sqlite3")
    tools = _request(server, "tools/list")
    probe = next(tool for tool in tools.tools if tool.name == TOOL)
    assert probe.meta["ui"]["resourceUri"] == URI
    assert probe.annotations.read_only_hint is False
    claim = next(tool for tool in tools.tools if tool.name == CLAIM_TOOL)
    assert claim.meta["ui"]["visibility"] == ["app"]
    resources = _request(server, "resources/list")
    assert [str(item.uri) for item in resources.resources] == [URI]
    resource = _request(server, "resources/read", ReadResourceRequestParams(uri=URI))
    assert resource.contents[0].mime_type == "text/html;profile=mcp-app"
    assert "sendFollowUpMessage" in resource.contents[0].text
    opened = _request(server, "tools/call", CallToolRequestParams(name=TOOL,
        arguments={"project_id": PROJECT}))
    assert opened.structured_content["baseline_handles"] == [
        "notification:project-portfolio-sandbox:old"]
    assert datetime.fromisoformat(opened.structured_content["expires_at"]) > datetime.now(UTC)
    assert opened.structured_content["probe_id"]
    assert opened.is_error is False


def test_probe_rejects_a_different_project_before_reading_inbox(tmp_path):
    server = create_probe_server(_Runtime(), tmp_path / "claims.sqlite3")
    rejected = _request(server, "tools/call", CallToolRequestParams(name=TOOL,
        arguments={"project_id": "project-other"}))
    assert rejected.is_error is True


def test_claim_requires_enabled_new_notice_and_deduplicates_across_mounts(tmp_path):
    service = _Service()
    runtime = _Runtime()
    runtime.service = service
    journal_path = tmp_path / "claims.sqlite3"
    first = create_probe_server(runtime, journal_path)
    open_first = _request(first, "tools/call", CallToolRequestParams(
        name=TOOL, arguments={"project_id": PROJECT})).structured_content
    second = create_probe_server(runtime, journal_path)
    open_second = _request(second, "tools/call", CallToolRequestParams(
        name=TOOL, arguments={"project_id": PROJECT})).structured_content
    handle = "notification:project-portfolio-sandbox:new"
    args = lambda probe_id: {"project_id": PROJECT, "probe_id": probe_id,
                             "notification_handle": handle}
    service.notifications = [*service.notifications, {"notification_handle": handle,
        "notification_enabled": False, "payload": {"kind": "team.configured"}}]
    denied = _request(first, "tools/call", CallToolRequestParams(
        name=CLAIM_TOOL, arguments=args(open_first["probe_id"])))
    assert denied.structured_content == {"claimed": False}
    service.notifications[-1]["notification_enabled"] = True
    accepted = _request(first, "tools/call", CallToolRequestParams(
        name=CLAIM_TOOL, arguments=args(open_first["probe_id"])))
    assert accepted.structured_content == {"claimed": True}
    duplicate = _request(second, "tools/call", CallToolRequestParams(
        name=CLAIM_TOOL, arguments=args(open_second["probe_id"])))
    assert duplicate.structured_content == {"claimed": False}
    baseline = _request(first, "tools/call", CallToolRequestParams(
        name=CLAIM_TOOL, arguments={"project_id": PROJECT,
            "probe_id": open_first["probe_id"], "notification_handle":
            "notification:project-portfolio-sandbox:old"}))
    assert baseline.structured_content == {"claimed": False}


def test_expired_probe_cannot_claim(tmp_path):
    service = _Service()
    runtime = _Runtime()
    runtime.service = service
    journal_path = tmp_path / "claims.sqlite3"
    server = create_probe_server(runtime, journal_path)
    opened = _request(server, "tools/call", CallToolRequestParams(
        name=TOOL, arguments={"project_id": PROJECT})).structured_content
    handle = "notification:project-portfolio-sandbox:new"
    service.notifications = [{"notification_handle": handle,
        "notification_enabled": True, "payload": {"kind": "team.configured"}}]
    with sqlite3.connect(journal_path) as db:
        db.execute("UPDATE probes SET expires_at=? WHERE probe_id=?",
                   ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), opened["probe_id"]))
    result = _request(server, "tools/call", CallToolRequestParams(name=CLAIM_TOOL,
        arguments={"project_id": PROJECT, "probe_id": opened["probe_id"],
                   "notification_handle": handle}))
    assert result.structured_content == {"claimed": False}


def test_component_bridge_obeys_notification_policy_and_claim_result():
    if shutil.which("node") is None:
        pytest.skip("Node is needed to execute the embedded Chat component")
    runner = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const html = require('node:fs').readFileSync(0, 'utf8');
const script = html.match(/<script type="module">([\s\S]*?)<\/script>/)[1];
const notifications = [];
const claims = [];
const followUps = [];
const probeElements = {status: {textContent: ''}, phase: {textContent: ''}};
const probeDocument = {documentElement: {dataset: {}},
  getElementById: id => probeElements[id]};
let tick;
let cleared = false;
let allowClaim = false;
const bridge = {
  theme: 'dark',
  toolOutput: {project_id: 'project-portfolio-sandbox', probe_id: 'probe-1',
    baseline_handles: [], expires_at: new Date(Date.now() + 300000).toISOString()},
  setWidgetState(state) { this.widgetState = state; },
  async callTool(name, args) {
    if (name === 'check_inbox') return {structuredContent: {ok: true,
      data: {project_id: bridge.toolOutput.project_id, notifications}}};
    if (name === 'claim_chat_receiver_probe_wake') {
      claims.push(args);
      return {structuredContent: {claimed: allowClaim}};
    }
    throw new Error(name);
  },
  async sendFollowUpMessage(args) { followUps.push(args); }
};
vm.runInNewContext(script, {document: probeDocument,
  window: {openai: bridge, addEventListener: () => {}},
  setInterval: fn => {tick = fn; return 1}, clearInterval: () => {cleared = true},
  Date, Set, String, Number});
(async () => {
  notifications.push({notification_handle: 'disabled', notification_enabled: false,
    payload: {kind: 'team.configured'}});
  await tick();
  assert.equal(claims.length, 0);
  assert.equal(followUps.length, 0);
  notifications.push({notification_handle: 'claim-rejected', notification_enabled: true,
    payload: {kind: 'team.configured'}});
  await tick();
  assert.equal(claims.length, 1);
  assert.equal(followUps.length, 0);
  allowClaim = true;
  notifications.push({notification_handle: 'claimed', notification_enabled: true,
    payload: {kind: 'team.configured'}});
  await tick();
  assert.equal(claims.length, 2);
  assert.equal(followUps.length, 1);
  assert.match(followUps[0].prompt, /claimed/);
  await tick();
  assert.equal(followUps.length, 1);
  assert.equal(cleared, true);
  assert.equal(probeDocument.documentElement.dataset.theme, 'dark');
  assert.equal(probeElements.phase.textContent, 'SUBMITTED');
  assert.equal(bridge.widgetState.privateContent.phase, 'SUBMITTED');
  const uncertainElements = {status: {textContent: ''}, phase: {textContent: ''}};
  const uncertainDocument = {documentElement: {dataset: {}},
    getElementById: id => uncertainElements[id]};
  let uncertainTick;
  let uncertainSends = 0;
  const uncertainBridge = {
    toolOutput: {project_id: 'project-portfolio-sandbox', probe_id: 'probe-2',
      baseline_handles: [], expires_at: new Date(Date.now() + 300000).toISOString()},
    setWidgetState(state) { this.widgetState = state; },
    async callTool(name) {
      if (name === 'check_inbox') return {structuredContent: {ok: true,
        data: {project_id: 'project-portfolio-sandbox', notifications: [
          {notification_handle: 'uncertain', notification_enabled: true,
           payload: {kind: 'team.configured'}}]}}};
      return {structuredContent: {claimed: true}};
    },
    async sendFollowUpMessage() { uncertainSends++; throw new Error('host rejected'); }
  };
  vm.runInNewContext(script, {document: uncertainDocument,
    window: {openai: uncertainBridge, addEventListener: () => {}},
    setInterval: fn => {uncertainTick = fn; return 2}, clearInterval: () => {},
    Date, Set, String, Number});
  await uncertainTick();
  await uncertainTick();
  assert.match(uncertainElements.status.textContent, /outcome_uncertain for uncertain/);
  assert.equal(uncertainBridge.widgetState.privateContent.phase, 'UNCERTAIN');
  assert.equal(uncertainSends, 1);
  const restoredElements = {status: {textContent: ''}, phase: {textContent: ''}};
  let restoredTick;
  let restoredCleared = false;
  let restoredCalls = 0;
  const restoredBridge = {
    toolOutput: {project_id: 'project-portfolio-sandbox', probe_id: 'probe-3',
      baseline_handles: [], expires_at: new Date(Date.now() + 300000).toISOString()},
    widgetState: {privateContent: {probe_id: 'probe-3', phase: 'CLAIMING',
      message: 'Claim outcome unknown after remount.'}},
    async callTool() { restoredCalls++; },
    async sendFollowUpMessage() { restoredCalls++; }
  };
  vm.runInNewContext(script, {document: {documentElement: {dataset: {}},
    getElementById: id => restoredElements[id]},
    window: {openai: restoredBridge, addEventListener: () => {}},
    setInterval: fn => {restoredTick = fn; return 3},
    clearInterval: () => {restoredCleared = true}, Date, Set, String, Number});
  await restoredTick();
  assert.equal(restoredCleared, true);
  assert.equal(restoredCalls, 0);
  assert.equal(restoredElements.phase.textContent, 'CLAIMING');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(["node", "-e", runner], input=HTML,
                            text=True, capture_output=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
