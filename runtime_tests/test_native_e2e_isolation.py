"""Keep real Native test discovery distinct from inherited MCP/App contact."""
import json

import pytest

from runtime_tests.native_e2e_isolation import configured_mcp_servers, validate_tool_destinations


def event(**changes):
    item = {"type": "mcp_tool_call", "server": "codex", "tool": "list_mcp_resources", "arguments": {},
            "error": None, "result": {"content": [{"type": "text", "text": json.dumps({"resources": []})}],
                                       "structured_content": None}}
    item.update(changes)
    return {"type": "item.completed", "item": item}


def test_acs_only_inventory_allows_builtin_empty_discovery_and_actual_acs_calls():
    servers = configured_mcp_servers({}, ['mcp_servers={acs={command="private-python"}}'])
    result = validate_tool_destinations([event(), event(server="acs", tool="send_message")], servers)
    assert result == {"configured_servers": ["acs"], "builtin_discovery_count": 1}


def test_discovery_accepts_only_the_actual_isolated_project_inbox_resource():
    listing = {"resources": [{"server": "acs", "uri": "acs://projects/project-alpha/inbox",
                              "name": "project-alpha Inbox", "mimeType": "application/json"}]}
    row = event(result={"content": [{"type": "text", "text": json.dumps(listing)}], "structured_content": None})
    assert validate_tool_destinations([row], {"acs"})["builtin_discovery_count"] == 1


@pytest.mark.parametrize("resource", [{"server": "personal", "uri": "acs://projects/project-alpha/inbox", "mimeType": "application/json"},
    {"server": "acs", "uri": "acs://projects/private-project/inbox", "mimeType": "application/json"},
    {"server": "acs", "uri": "file:///private", "mimeType": "application/json"}])
def test_discovery_cannot_return_another_server_project_or_file(resource):
    row = event(result={"content": [{"type": "text", "text": json.dumps({"resources": [resource]})}]})
    with pytest.raises(AssertionError):
        validate_tool_destinations([row], {"acs"})


@pytest.mark.parametrize("changes", [{"server": "stripe"}, {"server": None}, {"tool": "read_mcp_resource"},
    {"arguments": {"server": "github"}}, {"arguments": {"cursor": "external"}}, {"error": {"message": "failed"}},
    {"result": {"content": [{"type": "text", "text": '{"resources":[{"server":"other"}]}'}]}},
    {"result": {"content": [{"type": "text", "text": '{"resources":[],"nextCursor":"foreign"}'}]}}])
def test_discovery_exception_cannot_hide_another_server_or_resource(changes):
    with pytest.raises(AssertionError):
        validate_tool_destinations([event(**changes)], {"acs"})


def test_aggregate_discovery_cannot_hide_extra_configured_servers():
    with pytest.raises(AssertionError):
        configured_mcp_servers({"mcp_servers": {"personal": {}}}, ['mcp_servers={acs={command="private-python"}}'])
    with pytest.raises(AssertionError):
        validate_tool_destinations([event()], {"acs", "personal"})
