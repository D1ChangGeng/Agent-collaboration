"""Validate exact Native tool destinations in an ACS-only test environment."""
from __future__ import annotations

import json
import tomllib


def configured_mcp_servers(config, overrides):
    servers = set(config.get("mcp_servers", {}))
    for value in overrides:
        servers.update(tomllib.loads(value).get("mcp_servers", {}))
    assert servers == {"acs"}, "Isolated acceptance must configure only its ACS MCP server"
    return servers


def validate_tool_destinations(events, servers):
    assert servers == {"acs"}, "Unknown Native MCP inventory"
    discovery = 0
    for row in events:
        item = row.get("item", {})
        if item.get("type") != "mcp_tool_call":
            continue
        if item.get("server") == "acs":
            continue
        # Codex 0.166 emits the built-in aggregate resource operation under
        # server=codex, although no external MCP named codex is configured.
        # Admit only this discovery over the independently checked ACS-only
        # inventory, never a generic built-in/unknown-server exemption.
        assert item.get("server") == "codex" and item.get("tool") == "list_mcp_resources", "Unexpected Native tool server"
        arguments = item.get("arguments")
        assert arguments in ({}, {"server": "acs"}), "Discovery must be scoped to the configured ACS inventory"
        if row.get("type") == "item.started":
            assert item.get("result") is None and item.get("error") is None
            continue
        assert row.get("type") == "item.completed" and item.get("error") is None
        result = item.get("result")
        assert isinstance(result, dict) and result.get("structured_content") is None
        content = result.get("content")
        assert isinstance(content, list) and len(content) == 1 and content[0].get("type") == "text"
        listing = json.loads(content[0]["text"])
        allowed_keys = {"resources"} if arguments == {} else {"server", "resources"}
        assert isinstance(listing, dict) and set(listing) == allowed_keys
        if arguments:
            assert listing["server"] == "acs"
        resources = listing.get("resources")
        assert isinstance(resources, list) and len(resources) <= 1
        for resource in resources:
            assert (isinstance(resource, dict) and resource.get("server") == "acs"
                    and resource.get("uri") == "acs://projects/project-alpha/inbox"
                    and resource.get("mimeType") == "application/json"), "Discovery escaped the isolated ACS Project"
        discovery += 1
    return {"configured_servers": sorted(servers), "builtin_discovery_count": discovery}
