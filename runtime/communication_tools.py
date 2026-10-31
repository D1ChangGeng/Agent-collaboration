"""Public communication schemas, shared by discovery and calls."""
from __future__ import annotations

TASK_TOOLS = frozenset({
    "list_work", "create_work", "revise_work", "handoff_work", "acknowledge_handoff", "withdraw_handoff",
    "request_review", "submit_review", "accept_work", "cancel_work", "stop_attempt", "list_evidence", "list_reviews",
})
LEGACY_CONTINUATION_TOOLS = frozenset({"watch_changes", "set_notification"})
DEFERRED_TOOLS = frozenset({"create_branch", "commit_changes", "push_changes", "submit_command"})


def schema(name):
    properties = {"project_id": {"type": "string"}}
    required = ["project_id"]
    if name == "send_message":
        required += ["to", "content"]
        properties.update({"to": {"type": "string"}, "content": {"type": "string"},
            "client_request_id": {"type": "string"},
            "reply_to": {"type": "array", "items": {"type": "string"}, "maxItems": 32},
            "activation": {"type": "string", "enum": ["invoke", "message_only"], "default": "invoke"},
            "response_mode": {"type": "string", "enum": ["async", "sync"], "default": "async"},
            "wait_timeout_seconds": {"type": ["integer", "null"], "minimum": 0},
            "deadline": {"type": ["string", "null"]}})
    elif name == "read_message":
        required += ["handle"]
        properties.update({"handle": {"type": "string", "description": "A message_handle, response_handle or notification_handle returned by ACS."},
            "max_inline_bytes": {"type": "integer"},
                           "offset": {"type": "integer", "minimum": 0}})
    elif name == "wait_for_response":
        required += ["handles"]
        properties.update({"handles": {"type": "array", "items": {"type": "string"}, "maxItems": 32},
            "mode": {"type": "string", "enum": ["any", "all"], "default": "all"},
            "until": {"type": "string", "enum": ["response_received", "accepted_by_authority",
                "target_inbox_committed", "runtime_dispatched", "runtime_acknowledged"], "default": "response_received"},
            "timeout_seconds": {"type": ["integer", "null"], "minimum": 0}})
    elif name == "list_harnesses":
        properties.update({"scope_handle": {"type": "string"},
            "required_capabilities": {"type": "array", "items": {"type": "string"}},
            "harness_kinds": {"type": "array", "items": {"type": "string"}},
            "cursor": {"type": ["string", "null"]}, "limit": {"type": "integer"}})
    elif name == "configure_team":
        required += ["members"]
        properties.update({"client_request_id": {"type": "string"}, "scope_handle": {"type": "string"},
            "expected_revision": {"type": "integer"}, "members": {"type": "array", "minItems": 1, "maxItems": 32,
                "items": {"type": "object", "additionalProperties": False, "required": ["agent_slot_id"],
                    "properties": {"agent_slot_id": {"type": "string"}, "principal_ref": {"type": "string"},
                        "display_name": {"type": "string"}, "role": {"type": "string", "enum": ["root", "route", "engineer", "reviewer", "specialist", "finalizer"]},
                        "profile": {"type": "string", "enum": ["root_manager", "route_manager", "engineer", "reviewer", "operator"]},
                        "harness_requirements": {"type": "array", "items": {"type": "string", "enum": ["codex", "opencode"]}},
                        "permissions": {"type": "array", "items": {"type": "string"}}, "expires_at": {"type": "string"},
                        "endpoint_id": {"type": ["string", "null"]},
                        "if_unchanged": {"type": "object"}}}},
            "prepare_native": {"type": "boolean", "default": True}})
    elif name == "list_collaborators":
        properties.update({"scope_handle": {"type": "string"}, "name": {"type": "string"},
                           "roles": {"type": "array", "items": {"type": "string"}},
                           "states": {"type": "array", "items": {"type": "string"}},
                           "cursor": {"type": ["string", "null"]}, "limit": {"type": "integer"}})
    else:
        properties.update({"cursor": {"type": ["string", "null"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                           "with": {"type": "string", "description": "Filter by a peer's collaborator_handle or Client address; use read_message for notification handles."}})
        if name == "list_messages":
            properties["direction"] = {"type": "string", "enum": ["both", "incoming", "outgoing"], "default": "both"}
        if name == "check_inbox":
            properties["notification_cursor"] = {"type": ["string", "null"]}
    return {"type": "object", "additionalProperties": False, "required": required, "properties": properties}


DESCRIPTIONS = {
    "list_harnesses": "Read current registered receiving locations and observed Native Session state. "
        "Defaults to authorized project locations. unknown is not idle. This query never prepares, starts, "
        "resumes or invokes a Harness. Configuration is a separate authorized action.",
    "configure_team": "Add or partially update stable collaborators in the current authorized scope. "
        "Only specified members and fields change. Existing members remain. For a new member provide "
        "agent_slot_id and principal_ref; role/profile and Harness preferences are optional. Names never change "
        "historical authors. if_unchanged detects conflicting property edits. Native session state is reported "
        "separately from committed configuration; credentials and Native IDs are not inferred from message text.",
    "list_collaborators": "Find authorized contacts and your own stable address. Names and roles help select a "
        "recipient; use collaborator_handle directly as send_message.to. Optional filters narrow visibility.",
    "send_message": "Send natural content from your authenticated identity to a collaborator. Use this tool for "
        "replies, corrections and handoffs; reply_to names original message handles. Defaults to invoke + async. "
        "sync waits for the recipient's first explicit reply, including clarification. message_only does not wake "
        "the recipient. Timeout leaves communication intact. Reuse client_request_id for the same send's retry; "
        "intentional identical sends use different IDs.",
    "read_message": "Read permitted original content, relationships and the first explicit Agent reply. "
        "Also accepts notification_handle to read an ACS system notification and its own Native delivery state. "
        "Reading preserves Inbox and history. Continue content with next_offset. Native output is not a reply.",
    "check_inbox": "List messages addressed to your authenticated identity without consuming them. Read content "
        "with read_message; reply using send_message with from as to and message_handle in reply_to. "
        "notifications lists ACS system notices: pass notification_handle to read_message. "
        "with filters peer addresses, not notification handles. next_cursor continues the page; resume_cursor discovers later messages.",
    "list_messages": "Find your incoming and outgoing history. Optional with and direction narrow results. "
        "Stable cursors follow authority commit order, not UUID or sender clocks.",
    "wait_for_response": "Observe original sent message or response handles without sending or invoking again. "
        "Defaults to all and the actual recipient's first explicit reply. any returns when one has replied. "
        "timeout_seconds bounds this observation only; repeat after reconnecting to obtain the same first reply.",
}


def adopt_catalog(catalog):
    tools = {name: value for name, value in catalog["tools"].items()
             if name not in TASK_TOOLS | LEGACY_CONTINUATION_TOOLS | DEFERRED_TOOLS}
    for name, description in DESCRIPTIONS.items():
        value = dict(tools.get(name, tools["check_inbox"]))
        contract = schema(name)
        value.update(title=name.replace("_", " ").title(), description=description,
                     selection_guidance=description,
                     result_type="message_list" if name == "list_messages" else value["result_type"],
                     security_scopes=["runtime.read"] if name == "list_harnesses" else
                         ["collaborators.manage", "grants.manage"] if name == "configure_team" else
                         ["collaborators.read"] if name == "list_collaborators" else
                         ["message.send"] if name == "send_message" else ["message.read"],
                     input_schema={"schema_version": "acs-mcp-" + name.replace("_", "-") + "/2",
                                   "required": contract["required"],
                                   "optional": [key for key in contract["properties"] if key not in contract["required"]],
                                   "json_schema": contract})
        value["annotations"] = {**value["annotations"], "readOnlyHint": name not in {"send_message", "configure_team"},
                                "destructiveHint": False}
        tools[name] = value
    profiles = {name: list(dict.fromkeys([*(tool for tool in items if tool in tools),
                                        *(tool for tool in DESCRIPTIONS if tool != "configure_team")]))
                for name, items in catalog["profiles"].items()}
    defaults = {key: value for key, value in catalog.get("defaults", {}).items()
                if key not in {"expect_response", "wait_until"}}
    defaults.update(read_consumes=False, wait_condition="explicit_recipient_reply")
    groups = {name: [tool for tool in items if tool in tools] for name, items in catalog.get("tool_groups", {}).items()}
    groups = {name: items for name, items in groups.items() if items}
    grouped = {tool for items in groups.values() for tool in items}
    groups.setdefault("communication", []).extend(tool for tool in tools if tool not in grouped)
    groups = {name: items for name, items in groups.items() if items}
    result_types = dict(catalog.get("result_types", {}))
    result_types.update({"message_list": ["project_id", "items", "next_cursor", "resume_cursor"],
        "message_snapshot": ["project_id", "message_handle", "content", "reply_to", "reply", "next_offset"],
        "response_observation": ["project_id", "satisfied", "pending", "observations"],
        "message_submission": ["project_id", "message_handle", "response_handle", "from", "to", "native_status"],
        "team_configuration": ["project_id", "configuration_state", "team_revision", "native_sessions"]})
    result_types = {kind: result_types[kind] for kind in {tool["result_type"] for tool in tools.values()}}
    return {**catalog, "schema_version": "acs-p2-mcp-tool-contract/7", "surface_revision": "acs-communication/1",
            "defaults": defaults, "receipt_order": ["accepted_by_authority", "target_inbox_committed",
                "runtime_dispatched", "runtime_acknowledged"], "tools": tools, "profiles": profiles,
            "advanced_tools": [], "compatibility_aliases": {}, "tool_groups": groups, "result_types": result_types,
            "result_revision": "acs-communication-results/1",
            "agent_organization_model": {"schema_version": "acs-agent-organization/2",
                "management_levels": ["client", "root", "route"], "ordinary_slot_is_management_level": False},
            "access_modes": {"owner": {"authorization": "trusted Client or bound Slot; live identity and project checks"},
                             "shared": {"authorization": "trusted caller binding and scoped, live Grants"}}}
