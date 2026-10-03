"""Profile-filtered MCP Runtime backed by the shared PostgreSQL Domain.

Tool availability is the intersection of implemented actions, the configured
Profile and current project Grants. Transport authentication is rechecked for
discovery and every call. ProjectService owns no alternate WorkItem or delivery
state; native execution is performed by the existing durable dispatcher.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from runtime.connection_clock import presentation_metadata
from runtime.errors import (
    AcceptanceGuardFailed,
    AuthorizationDenied,
    IdempotencyConflict,
    InvalidTransition,
    NotFound,
    RevisionConflict,
)
from runtime.project_service import ProjectService
from runtime.source import SourceError

ARRAYS = frozenset({
    "handles", "constraints", "required_evidence", "include", "states", "kinds",
    "source_binding_ids", "required_capabilities", "roles", "providers", "paths",
    "members", "policies", "budgets", "harness_kinds",
    "context_handles", "evidence_handles", "unresolved_items", "criteria",
    "reviewer_requirements", "findings", "evidence_classes", "review_types", "event_kinds",
    "review_handles", "evidence_bundle_handles",
    "target_handles",
    "evidence_dispositions",
})
OBJECTS = frozenset({"target", "accepted_state", "budget", "changes", "source_state", "source_readback", "effect_readback"})
BOOLEANS = frozenset({"consume", "expect_response", "require_ack", "enabled", "blocked"})
INTEGERS = frozenset({"limit", "max_inline_bytes", "accepted_revision", "at_revision",
                      "start_line", "end_line", "depth"})


class McpRuntime:
    def __init__(self, service: ProjectService, credential_provider, *, presentation_timezone="UTC"):
        self.service, self.credential_provider = service, credential_provider
        presentation_metadata({}, presentation_timezone)
        self.presentation_timezone = presentation_timezone

    def input_schema(self, name: str) -> dict[str, Any]:
        definition = self.service.catalog["tools"][name]["input_schema"]
        properties = {}
        definitions = {}
        for field in [*definition["required"], *definition["optional"]]:
            kind = ("array" if field in ARRAYS else "object" if field in OBJECTS
                    else "boolean" if field in BOOLEANS
                    else "integer" if field in INTEGERS or (
                        field.endswith(("_revision", "_seconds"))
                        and field not in {"base_revision", "target_revision"})
                    else "string")
            properties[field] = {"type": kind}
            if field in ARRAYS:
                if field in {"members", "policies", "budgets", "evidence_dispositions"}:
                    from runtime.project_management import TeamBudget, TeamMember, TeamPolicy
                    from runtime.project_work import EvidenceDisposition
                    item_schema = {"members": TeamMember, "policies": TeamPolicy,
                                   "budgets": TeamBudget, "evidence_dispositions": EvidenceDisposition}[field].model_json_schema()
                    definitions.update(item_schema.pop("$defs", {}))
                    properties[field]["items"] = item_schema
                else:
                    properties[field]["items"] = {"type": "string"}
            if field in {"at_revision", "cursor", "timeout_seconds", "wait_timeout_seconds"}:
                properties[field]["type"] = [kind, "null"]
            if field == "decision" and name in {"submit_review", "accept_work"}:
                properties[field]["enum"] = (["pass", "fail"] if name == "submit_review"
                                               else ["acceptance_ready", "accepted"])
            if field == "decision" and name == "acknowledge_handoff":
                properties[field]["enum"] = ["accepted", "rejected"]
            if field == "delivery_policy" and name == "watch_changes":
                properties[field]["enum"] = ["notify_current_session", "inbox_only"]
        return {"type": "object", "additionalProperties": False,
                "required": definition["required"], "properties": properties,
                **({"$defs": definitions} if definitions else {})}

    def tools_list(self):
        names = self.service.available_tools(self.credential_provider())
        result = []
        for name in names:
            definition = self.service.catalog["tools"][name]
            result.append({"name": name, "title": definition["title"],
                "description": definition["description"], "inputSchema": self.input_schema(name),
                "outputSchema": {"type": "object", "additionalProperties": False,
                    "required": ["schema_version", "result_type", "ok", "state", "data",
                                 "follow_ups", "metadata"],
                    "properties": {"schema_version": {"const": "acs-mcp-result/3"},
                        "result_type": {"type": "string"}, "ok": {"type": "boolean"},
                        "state": {"type": "string"}, "data": {"type": "object"},
                        "follow_ups": {"type": "array"}, "metadata": {"type": "object"}}},
                "annotations": definition["annotations"],
                "securityScopes": definition["security_scopes"],
                "_meta": {"acs/resultType": definition["result_type"],
                          "acs/profile": self.service.profile}})
        return {"tools": result}

    def _validate(self, name, arguments):
        schema = self.input_schema(name)
        if (not isinstance(arguments, dict) or set(arguments) - set(schema["properties"])
                or not set(schema["required"]) <= set(arguments)):
            raise ValueError("arguments differ from the closed tool schema")
        types = {"string": str, "integer": int, "array": list, "object": dict,
                 "boolean": bool, "null": type(None)}
        for field, value in arguments.items():
            expected = schema["properties"][field]["type"]
            expected = expected if isinstance(expected, list) else [expected]
            if type(value) not in [types[item] for item in expected]:
                raise ValueError("argument type differs from the tool schema")
            item_type = dict if field in {"members", "policies", "budgets", "evidence_dispositions"} else str
            if isinstance(value, list) and (len(value) > 100 or any(type(x) is not item_type for x in value)):
                raise ValueError("tool list arguments require bounded text entries")
        if len(json.dumps(arguments, allow_nan=False).encode()) > 65536:
            raise ValueError("tool input exceeds the configured bound")

    def call(self, name, arguments):
        try:
            credential = self.credential_provider()
            self.service.service.authenticate(credential)
            if credential and credential in json.dumps(arguments):
                raise ValueError("credentials cannot be tool arguments")
            if name not in self.service.IMPLEMENTED:
                raise ValueError("tool is not implemented")
            self._validate(name, arguments)
            state, data, follow_ups = self.service.execute(name, arguments, credential)
            result = {"schema_version": "acs-mcp-result/3",
                      "result_type": self.service.catalog["tools"][name]["result_type"],
                      "ok": True, "state": state, "data": data, "follow_ups": follow_ups,
                      "metadata": {"evidence_class": "authority_observation",
                                   "observed_at": datetime.now(UTC).isoformat(),
                                   "timestamp_source": "node_local_utc",
                                   "timestamp_authority": "unverified"}}
            result["metadata"]["presentation"] = presentation_metadata(
                {"data": data, "metadata": {"observed_at": result["metadata"]["observed_at"]}},
                self.presentation_timezone,
            )
            if credential and credential in json.dumps(result, default=str):
                raise ValueError("credentials cannot be tool results")
        except (PermissionError, AuthorizationDenied):
            result = self._problem("authorization_denied")
        except IdempotencyConflict:
            result = self._problem("idempotency_conflict")
        except RevisionConflict:
            result = self._problem("revision_conflict")
        except NotFound:
            result = self._problem("not_found")
        except (AcceptanceGuardFailed, InvalidTransition):
            result = self._problem("guard_rejected")
        except SourceError:
            result = self._problem("source_unavailable")
        except (ValueError, TypeError, KeyError, ValidationError):
            result = self._problem("invalid_arguments")
        except Exception:  # noqa: BLE001 - transport never exposes private backend errors
            result = self._problem("service_unavailable", retryable=True)
        return {"content": [{"type": "text", "text": json.dumps(result, default=str)}],
                "structuredContent": result, "isError": not result["ok"]}

    @staticmethod
    def _problem(code, retryable=False):
        return {"schema_version": "acs-mcp-result/3", "result_type": "problem", "ok": False,
                "state": "rejected", "data": {"code": code, "retryable": retryable},
                "follow_ups": [], "metadata": {"evidence_class": "authority_rejected"}}

    def create_server(self):
        """Use the installed MCP SDK for handshake, schema and transport framing."""
        from runtime.project_mcp_server import create_project_server

        return create_project_server(self)
