"""Verify the diagnostic MCP UI uses the pinned SDK wire shapes and project guard."""
from __future__ import annotations

import asyncio

from mcp_types import CallToolRequestParams, ReadResourceRequestParams

from tools.runtime.p2_chat_receiver_widget_probe import PROJECT, TOOL, URI, create_probe_server


class _Service:
    def execute(self, name, args, _credential):
        if name == "list_projects":
            return "observed", {"items": [{"project_id": PROJECT}]}, []
        if name == "check_inbox" and args == {"project_id": PROJECT}:
            return "observed", {"project_id": PROJECT,
                "notifications": [{"notification_handle": "notification:project-portfolio-sandbox:old"}]}, []
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


def test_probe_exposes_authorized_component_and_exact_initial_inbox_baseline():
    server = create_probe_server(_Runtime())
    tools = _request(server, "tools/list")
    probe = next(tool for tool in tools.tools if tool.name == TOOL)
    assert probe.meta["ui"]["resourceUri"] == URI
    assert probe.annotations.read_only_hint is True
    resources = _request(server, "resources/list")
    assert [str(item.uri) for item in resources.resources] == [URI]
    resource = _request(server, "resources/read", ReadResourceRequestParams(uri=URI))
    assert resource.contents[0].mime_type == "text/html;profile=mcp-app"
    assert "sendFollowUpMessage" in resource.contents[0].text
    opened = _request(server, "tools/call", CallToolRequestParams(name=TOOL,
        arguments={"project_id": PROJECT}))
    assert opened.structured_content["baseline_handles"] == [
        "notification:project-portfolio-sandbox:old"]
    assert opened.is_error is False


def test_probe_rejects_a_different_project_before_reading_inbox():
    server = create_probe_server(_Runtime())
    rejected = _request(server, "tools/call", CallToolRequestParams(name=TOOL,
        arguments={"project_id": "project-other"}))
    assert rejected.is_error is True
