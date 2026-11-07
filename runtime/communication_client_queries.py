"""Read-only client projections over the existing authenticated ProjectService.

This bridge does not implement HTTP, conversations, personal state, or a second
message store. ``ClientProjection`` explicitly separates an incomplete target
DTO from the authorized legacy observation used to build it. An HTTP integrator
must fill owning read-model metadata and call ``require_complete``; serializing
``core`` as a client DTO would expose a different contract.

All content, including digest inputs, is obtained through ``execute``. Historical
structured task packets are not converted into natural Agent messages. Waiting
delegates the existing observation-lease/ToolResult selection semantics and never
sends a message or manufactures a peer response.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from runtime.errors import InvalidToolArgument
from runtime.project_common import parse_handle


class ClientQueryUnavailable(ValueError):
    code = "unsupported_projection"

    def __init__(self, target: str, missing_fields: tuple[str, ...]):
        self.target, self.missing_fields = target, tuple(missing_fields)
        super().__init__(f"{target} requires owning read-model metadata: {', '.join(missing_fields)}")


@dataclass(frozen=True)
class ClientProjection:
    target: str
    data: dict[str, Any]
    missing_fields: tuple[str, ...] = ()
    core: dict[str, Any] = field(default_factory=dict, repr=False)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return not self.missing_fields

    def require_complete(self) -> dict[str, Any]:
        if self.missing_fields:
            raise ClientQueryUnavailable(self.target, self.missing_fields)
        return deepcopy(self.data)


def conversation_view_id(tenant_id: str, project_id: str, first: str, second: str) -> str:
    """Stable query-view identity; never a send prerequisite or native Session ID."""
    if not isinstance(tenant_id, str) or not tenant_id:
        raise ValueError("a trusted tenant identity is required")
    for address in (first, second):
        kind = "client" if isinstance(address, str) and address.startswith("client:") else "collaborator"
        parse_handle(address, kind, project_id)
    identity = [tenant_id, project_id, sorted((first, second))]
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return "conversation-" + hashlib.sha256(encoded).hexdigest()


def _page(data):
    # The legacy query is keyset-paged, but does not create a consistent snapshot.
    return {"next_cursor": data.get("next_cursor"), "snapshot_id": None}


def _continuations(actions):
    result = []
    for action in actions:
        if action.get("tool") != "read_message":
            continue
        arguments = action["arguments"]
        item = {"message_handle": arguments["handle"], "offset": arguments["offset"],
                "max_inline_bytes": arguments["max_inline_bytes"]}
        if item not in result:
            result.append(item)
    return result


def _natural(data):
    if data.get("historical") or not isinstance(data.get("content"), str):
        raise ClientQueryUnavailable("Message", ("natural_message_body",))
    if not all(isinstance(data.get(key), str) and data[key] for key in
               ("message_handle", "project_id", "from", "to")):
        raise ClientQueryUnavailable("Message", ("stable_message_identity",))


def _same_message(expected, observed):
    keys = ("message_handle", "project_id", "from", "to", "reply_to", "activation", "operation_id")
    if any(expected.get(key) != observed.get(key) for key in keys):
        raise ClientQueryUnavailable("Message", ("immutable_message_identity_changed",))


def _body_slice(data, full, offset):
    _natural(data)
    _natural(full)
    _same_message(data, full)
    if "next_offset" not in data or "next_offset" not in full:
        raise ClientQueryUnavailable("BodySlice", ("body_continuation_metadata",))
    if full["next_offset"] is not None:
        raise ClientQueryUnavailable("BodySlice", ("complete_body_digest_and_length",))
    raw = full["content"].encode("utf-8")
    end = data.get("next_offset")
    if (type(offset) is not int or offset < 0 or offset > len(raw)
            or end is not None and (type(end) is not int or not offset <= end <= len(raw))):
        raise ValueError("invalid UTF-8 body slice offset")
    try:
        raw[:offset].decode("utf-8")
        text = raw[offset:end].decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("body slice is not on a UTF-8 boundary") from error
    if text != data["content"]:
        raise ClientQueryUnavailable("BodySlice", ("immutable_message_body_changed",))
    return {"text": text, "offset": offset, "next_offset": end,
            "total_bytes": len(raw), "digest": hashlib.sha256(raw).hexdigest()}


def _delivery_facts(data):
    _natural(data)
    high_water = data.get("receipt_high_water")
    layers = ("accepted_by_authority", "target_inbox_committed", "runtime_dispatched", "runtime_acknowledged")
    if high_water not in layers:
        raise ClientQueryUnavailable("DeliveryFacts", ("current_receipt_high_water",))
    native = {"state": "unknown", "operation_ref": None, "binding_epoch": None,
              "provider_generation": None, "evidence_ref": None, "native_input_ref": None,
              "reason_code": "native_receipt_not_exposed_by_core_read"}
    missing = ["revision"]
    if data.get("activation") == "message_only" or data["to"].startswith("client:"):
        native.update(state="not_requested", reason_code=None)
    elif high_water == "runtime_acknowledged":
        # The high water is positive evidence of an ACK, but this legacy result
        # exposes neither the Native operation nor its actual receipt reference.
        native.update(state="accepted", reason_code="native_receipt_reference_not_exposed")
        missing.extend(("native.operation_ref", "native.evidence_ref"))
    reply = data.get("reply")
    facts = {"message_handle": data["message_handle"], "accepted_by_authority": True,
             "target_inbox_committed": layers.index(high_water) >= 1, "native": native,
             "consumption": {"state": "not_observed", "semantics": "provider_input_consumed", "evidence_ref": None},
             "response": {"present": reply is not None,
                          "message_handle": reply["message_handle"] if reply is not None else None}}
    return facts, tuple(missing)


class CommunicationClientQueries:
    """Every query uses the supplied current credential and live Domain checks."""

    def __init__(self, projects, credential_provider):
        if not callable(getattr(projects, "execute", None)) or not callable(credential_provider):
            raise TypeError("a ProjectService and current credential provider are required")
        self.projects, self.credential_provider = projects, credential_provider

    def _query(self, name, arguments):
        state, data, actions = self.projects.execute(name, arguments, self.credential_provider())
        return state, deepcopy(data), deepcopy(actions)

    def profile(self, project_id):
        state, data, _actions = self._query("read_profile", {})
        actor = data.get("actor")
        if data.get("connection_state") != "authorized" or not isinstance(actor, dict):
            raise ClientQueryUnavailable("Actor", ("current_authorized_binding",))
        _directory_state, directory, _follow = self._query("list_collaborators", {"project_id": project_id, "limit": 1})
        # Never infer trusted Client capability from an omitted/native-less Slot.
        binding = next((entry for entry in actor.get("bindings", []) if entry.get("project_id") == project_id), actor)
        level = binding.get("organization", {}).get("level")
        target = {"address": directory["self"], "principal_ref": data["subject"],
                  "agent_slot_id": binding.get("agent_slot_id")}
        missing = ["auth_revision", "allowed_actions"]
        if level in {"client", "root", "route", "agent"}:
            target["level"] = level
        else:
            missing.append("level")
        return ClientProjection("Actor", target, tuple(missing), data,
            {"core_state": state, "project_id": project_id, "binding_source": actor.get("binding_source")})

    def projects_page(self, *, cursor=None, limit=50):
        state, data, _actions = self._query("list_projects", {"cursor": cursor, "limit": limit})
        items = [{"project_id": row["project_id"], "root_handle": row["root_handle"],
                  "revision": row["project_revision"]} for row in data["items"]]
        missing = tuple(field_name for index in range(len(items))
                        for field_name in (f"items[{index}].name", f"items[{index}].allowed_actions"))
        return ClientProjection("ProjectPage", {"items": items, "page": _page(data)}, missing, data,
                                {"core_state": state})

    def routes_page(self, project_id, *, cursor=None, limit=50):
        state, data, _actions = self._query("list_routes", {"project_id": project_id, "cursor": cursor, "limit": limit})
        items, missing = [], []
        for index, row in enumerate(data["items"]):
            item = {"route_handle": row["route_handle"], "project_id": project_id,
                    "scope_handle": "scope:" + project_id + ":" + row["scope_id"],
                    "state": row["state"], "revision": row["revision"]}
            for key in ("display_name", "goal"):
                if isinstance(row.get("definition", {}).get(key), str):
                    item[key] = row["definition"][key]
                else:
                    missing.append(f"items[{index}].{key}")
            items.append(item)
        return ClientProjection("RoutePage", {"items": items, "page": _page(data)}, tuple(missing), data,
                                {"core_state": state})

    def contacts_page(self, project_id, *, cursor=None, limit=50):
        state, data, _actions = self._query("list_collaborators", {"project_id": project_id, "cursor": cursor, "limit": limit})
        items, missing = [], []
        for index, row in enumerate(data["items"]):
            item = {"address": row["collaborator_handle"], "display_name": row["display_name"],
                    "agent_slot_id": row["agent_slot_id"], "manager_handle": row.get("manager_handle"),
                    "role": row.get("role"), "scope_handles": [row["scope_handle"]], "is_self": row["is_self"]}
            selected = row.get("receiver", {})
            if selected.get("selection") == "configured" and selected.get("endpoint_id"):
                item["receiver_refs"] = [selected["endpoint_id"]]
            else:
                missing.append(f"items[{index}].receiver_refs")
            missing.append(f"items[{index}].revision")
            items.append(item)
        return ClientProjection("ContactPage", {"items": items, "page": _page(data)}, tuple(missing), data,
                                {"core_state": state, "self_address": data["self"]})

    def _message(self, data, full, offset):
        _natural(data)
        target = {"message_handle": data["message_handle"], "project_id": data["project_id"],
            "conversation_id": conversation_view_id(self.projects.context.tenant_id, data["project_id"], data["from"], data["to"]),
            "sender": data["from"], "to": data["to"], "content": _body_slice(data, full, offset),
            "reply_to": list(data["reply_to"]), "source": "acs_client" if data["from"].startswith("client:") else "acs_agent",
            "first_reply_handle": data["reply"]["message_handle"] if data.get("reply") is not None else None}
        return target

    def read_message(self, project_id, message_handle, *, offset=0, max_inline_bytes=16384):
        state, data, actions = self._query("read_message", {"project_id": project_id, "handle": message_handle,
            "offset": offset, "max_inline_bytes": max_inline_bytes})
        _natural(data)
        # The current ordinary Core limit is 32 KiB. A separate authorized 64 KiB
        # read gives exact immutable length/digest without changing this result's
        # requested slice or its independently budgeted first reply.
        if offset == 0 and data.get("next_offset") is None and (
                data.get("reply") is None or data["reply"].get("next_offset") is None):
            full = data
        else:
            _full_state, full, _full_actions = self._query("read_message", {"project_id": project_id,
                "handle": data["message_handle"], "offset": 0, "max_inline_bytes": 65536})
        first_reply = None
        if data.get("reply") is not None:
            reply = data["reply"]
            full_reply = full.get("reply")
            if full_reply is None or full_reply.get("message_handle") != reply["message_handle"]:
                _reply_state, full_reply, _reply_actions = self._query("read_message", {"project_id": project_id,
                    "handle": reply["message_handle"], "offset": 0, "max_inline_bytes": 65536})
            first_reply = self._message(reply, full_reply, 0)
        missing = ["message." + key for key in ("attachment_refs", "conversation_sequence", "committed_at", "revision")]
        if first_reply is not None:
            missing.extend("first_reply." + key for key in ("attachment_refs", "conversation_sequence", "committed_at", "revision", "first_reply_handle"))
            # Embedded reply views do not expose whether that reply has its own
            # reply. Omit the unknown relationship rather than assert null.
            first_reply.pop("first_reply_handle")
        target = {"message": self._message(data, full, offset), "first_reply": first_reply,
                  "continuations": _continuations(actions)}
        return ClientProjection("ReadMessageResponse", target, tuple(missing), data, {"core_state": state})

    def messages_page(self, project_id, *, peer=None, direction="both", cursor=None, limit=50,
                      max_inline_bytes=16384):
        arguments = {"project_id": project_id, "cursor": cursor, "limit": limit, "direction": direction}
        if peer:
            arguments["with"] = peer
        state, data, _actions = self._query("list_messages", arguments)
        items, missing, continuations = [], [], []
        for index, row in enumerate(data["items"]):
            read = self.read_message(project_id, row["message_handle"], max_inline_bytes=max_inline_bytes)
            items.append(read.data["message"])
            missing.extend(f"items[{index}]." + field_name.removeprefix("message.")
                           for field_name in read.missing_fields if field_name.startswith("message."))
            continuations.extend(read.data["continuations"])
        return ClientProjection("MessagePage", {"items": items, "page": _page(data)}, tuple(missing), data,
            {"core_state": state, "resume_cursor": data.get("resume_cursor"), "cursor_reset": data.get("cursor_reset", False),
             "continuations": continuations, "snapshot_consistency": "not_provided_by_legacy_query"})

    def delivery(self, project_id, message_handle):
        state, data, _actions = self._query("read_message", {"project_id": project_id, "handle": message_handle,
                                                             "max_inline_bytes": 65536})
        target, missing = _delivery_facts(data)
        return ClientProjection("DeliveryFacts", target, missing, data, {"core_state": state})

    def wait_for_response(self, project_id, handles, *, mode="all", until="response_received", timeout_seconds=None):
        arguments = {"project_id": project_id, "handles": handles, "mode": mode, "until": until}
        if timeout_seconds is not None:
            arguments["timeout_seconds"] = timeout_seconds
        state, data, actions = self._query("wait_for_response", arguments)
        if state not in {"satisfied", "timeout"}:
            raise ClientQueryUnavailable("WaitResponse", ("known_wait_observation_state",))
        items, missing = [], []
        for index, observation in enumerate(data["observations"]):
            item, fields = _delivery_facts(observation)
            items.append(item)
            missing.extend(f"items[{index}]." + name for name in fields)
        target = {"wait": {"state": "satisfied" if state == "satisfied" else "timed_out",
            "satisfied_handles": list(data["satisfied"]), "pending_handles": list(data["pending"])},
            "items": items, "continuations": _continuations(actions)}
        return ClientProjection("WaitResponse", target, tuple(missing), data, {"core_state": state})

    def operation(self, project_id, operation_ref, *, message_handle=None):
        if message_handle is None:
            raise ClientQueryUnavailable("Operation", ("authorized_message_context",))
        state, data, _actions = self._query("read_message", {"project_id": project_id, "handle": message_handle,
                                                             "max_inline_bytes": 65536})
        _natural(data)
        if data.get("operation_id") != operation_ref:
            raise InvalidToolArgument("operation_ref", "Use this message's original Core delivery operation.")
        phase = data["state"]
        native_possible = data.get("receipt_high_water") in {"runtime_dispatched", "runtime_acknowledged"}
        normalized = {"queued": "queued", "retry_wait": "deferred", "delivering": "submitting",
                      "delivered": "completed", "uncertain": "unknown", "blocked": "definitively_rejected",
                      "expired": "definitively_rejected", "budget_exhausted": "definitively_rejected"}
        if phase not in normalized:
            raise ClientQueryUnavailable("Operation", ("known_delivery_operation_state",))
        target = {"operation_id": operation_ref, "kind": "delivery", "state": normalized[phase],
            "message_handle": data["message_handle"], "receiver_ref": None, "binding_epoch": None,
            "effect_state": "native_possible" if native_possible else "unknown" if phase == "uncertain" else "committed",
            "reason_code": data.get("delivery", {}).get("error_code")}
        if native_possible and phase in {"blocked", "expired", "budget_exhausted"}:
            target["state"] = "unknown"
        return ClientProjection("Operation", target, ("evidence_refs", "revision", "created_at", "updated_at"),
                                data, {"core_state": state, "delivery_state": phase})
