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

import psycopg
from pydantic import ValidationError

from runtime.communication_tools import NATIVE_COLLABORATION_TOOLS
from runtime.connection_clock import presentation_metadata
from runtime.delivery import DeliveryRejected
from runtime.errors import (
    AcceptanceGuardFailed,
    AuthorizationDenied,
    BusinessDeadlineExpired,
    IdempotencyConflict,
    IdentityRejected,
    InvalidToolArgument,
    InvalidTransition,
    NotFound,
    RevisionConflict,
)
from runtime.machine_filesystem import FilesystemError
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
        from runtime.communication_tools import DESCRIPTIONS, schema
        if name in DESCRIPTIONS or name == "configure_team":
            return schema(name)
        from runtime.filesystem_schema import ALL_TOOLS, input_schema
        owner = getattr(getattr(getattr(self.service, "service", None), "authority", None), "access_mode", "shared") == "owner"
        if owner and name in ALL_TOOLS:
            return input_schema(name)
        definition = self.service.catalog["tools"][name]["input_schema"]
        required = list(definition["required"])
        optional = list(definition["optional"])
        if owner:
            relaxed = {"deadline"}
            if name in {"list_files", "search_files", "read_source", "read_source_file", "list_source_files", "search_source_files"} and "revision" not in required:
                required.append("revision")
                optional = [field for field in optional if field != "revision"]
            if name == "load_project":
                optional.extend(["machine_id", "management_path"])
            if name == "create_route":
                relaxed.add("source_binding_ids")
            for field in list(required):
                if field in relaxed:
                    required.remove(field)
                    optional.append(field)
        if owner and name == "create_route":
            optional = [field for field in optional if field != "source_binding_ids"]
        properties = {}
        definitions = {}
        for field in [*required, *optional]:
            kind = ("array" if field in ARRAYS else "object" if field in OBJECTS
                    else "boolean" if field in BOOLEANS
                    else "integer" if field in INTEGERS or (
                        field.endswith(("_revision", "_seconds"))
                        and field not in {"base_revision", "target_revision"})
                    else "string")
            properties[field] = {"type": kind}
            if field in ARRAYS:
                if field in {"members", "policies", "budgets", "evidence_dispositions"}:
                    raise ValueError("legacy task input schemas are not supported")
                properties[field]["items"] = {"type": "string"}
            if field in {"at_revision", "cursor", "timeout_seconds", "wait_timeout_seconds"} or (owner and field == "deadline"):
                properties[field]["type"] = [kind, "null"]
            if field == "decision" and name in {"submit_review", "accept_work"}:
                properties[field]["enum"] = (["pass", "fail"] if name == "submit_review"
                                               else ["acceptance_ready", "accepted"])
            if field == "decision" and name == "acknowledge_handoff":
                properties[field]["enum"] = ["accepted", "rejected"]
            if field == "delivery_policy" and name == "watch_changes":
                properties[field]["enum"] = ["notify_current_session", "inbox_only"]
        return {"type": "object", "additionalProperties": False,
                "required": required, "properties": properties,
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
                "securityScopes": ([] if getattr(getattr(getattr(self.service, "service", None), "authority", None), "access_mode", "shared") == "owner"
                                   else definition["security_scopes"]),
                "_meta": {"acs/resultType": definition["result_type"],
                          "acs/profile": self.service.profile}})
        return {"tools": result}

    def _validate(self, name, arguments):
        schema = self.input_schema(name)
        if not isinstance(arguments, dict):
            raise InvalidToolArgument("$", "Pass the tool arguments as a JSON object.")
        if set(arguments) - set(schema["properties"]):
            raise InvalidToolArgument("$", "Remove arguments not listed in this tool's input schema.")
        for field in schema["required"]:
            if field not in arguments:
                raise InvalidToolArgument(field, f"Provide the required {field} argument.")
        types = {"string": str, "integer": int, "array": list, "object": dict,
                 "boolean": bool, "null": type(None)}
        for field, value in arguments.items():
            expected = schema["properties"][field]["type"]
            expected = expected if isinstance(expected, list) else [expected]
            if type(value) not in [types[item] for item in expected]:
                raise InvalidToolArgument(field, "Use the declared JSON type: " + " or ".join(expected) + ".")
            item_type = dict if field in {"members", "policies", "budgets", "evidence_dispositions"} else str
            if isinstance(value, list) and (len(value) > 100 or any(type(x) is not item_type for x in value)):
                raise InvalidToolArgument(field, "Use a bounded array of " + ("objects." if item_type is dict else "strings."))
            if "enum" in schema["properties"][field] and value not in schema["properties"][field]["enum"]:
                raise InvalidToolArgument(field, "Choose one of: " + json.dumps(schema["properties"][field]["enum"]) + ".")
            definition = schema["properties"][field]
            if type(value) is int:
                if "minimum" in definition and value < definition["minimum"]:
                    raise InvalidToolArgument(field, f"Use a value of at least {definition['minimum']}.")
                if "maximum" in definition and value > definition["maximum"]:
                    raise InvalidToolArgument(field, f"Use a value of at most {definition['maximum']}.")
            if isinstance(value, list):
                if "minItems" in definition and len(value) < definition["minItems"]:
                    raise InvalidToolArgument(field, f"Provide at least {definition['minItems']} entries.")
                if "maxItems" in definition and len(value) > definition["maxItems"]:
                    raise InvalidToolArgument(field, f"Provide at most {definition['maxItems']} entries.")
        if len(json.dumps(arguments, allow_nan=False, ensure_ascii=False).encode("utf-8")) > 65536:
            raise InvalidToolArgument("$", "Reduce the tool input to the 65536-byte UTF-8 JSON limit.")

    def call(self, name, arguments, *, request_id=None):
        recovery_request_id = None
        try:
            credential = self.credential_provider()
            self.service.service.authenticate(credential)
            from runtime.filesystem_schema import ALL_TOOLS
            machine_file = self.service.service.authority.access_mode == "owner" and name in ALL_TOOLS
            if not machine_file and credential and credential in json.dumps(arguments):
                raise ValueError("credentials cannot be tool arguments")
            if name not in self.service.IMPLEMENTED:
                raise ValueError("tool is not implemented")
            self._validate(name, arguments)
            if name in {"send_message", "configure_team"} and not arguments.get("client_request_id"):
                import uuid
                arguments = {**arguments, "client_request_id": request_id or uuid.uuid4().hex}
            if name in {"send_message", "configure_team"}:
                recovery_request_id = arguments["client_request_id"]
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
            if not machine_file and credential and credential in json.dumps(result, default=str):
                raise ValueError("credentials cannot be tool results")
        except psycopg.OperationalError:
            # A broken connection can hide a committed result. Never report an
            # authority rejection or replay SQL/Native effects at this boundary.
            retryable = recovery_request_id is not None or name in set(NATIVE_COLLABORATION_TOOLS) - {"send_message"}
            result = self._problem("service_unavailable", retryable=retryable)
            result["state"] = "unknown"
            result["metadata"]["evidence_class"] = "authority_unavailable"
            if recovery_request_id is not None:
                result["data"].update(client_request_id=recovery_request_id,
                                     recovery="retry_with_same_client_request_id")
        except FilesystemError as error:
            result = self._problem(error.code, retryable=error.code == "machine_offline")
            result["data"].update(error.details)
        except BusinessDeadlineExpired:
            result = self._problem("business_deadline_elapsed")
        except IdentityRejected as error:
            result = self._problem(error.code)
        except (PermissionError, AuthorizationDenied):
            result = self._problem("authorization_denied")
        except IdempotencyConflict:
            result = self._problem("idempotency_conflict")
        except RevisionConflict:
            result = self._problem("revision_conflict")
        except NotFound:
            result = self._problem("not_found")
        except DeliveryRejected as error:
            code = "message_expired" if error.state == "expired" else error.code
            result = self._problem(code, retryable=code in {"endpoint_unavailable", "invoke_endpoint_unavailable"})
        except (AcceptanceGuardFailed, InvalidTransition):
            result = self._problem("guard_rejected")
        except SourceError:
            result = self._problem("source_unavailable")
        except InvalidToolArgument as error:
            # Detail is public schema guidance, available only to a caller who
            # may discover this tool. Never echo supplied values or backend errors.
            try:
                visible = name in self.service.available_tools(credential)
            except (PermissionError, AuthorizationDenied, IdentityRejected):
                result = self._problem("authorization_denied")
            except Exception:  # noqa: BLE001 - unavailable discovery never discloses private errors.
                result = self._problem("service_unavailable", retryable=True)
            else:
                result = self._problem("invalid_arguments" if visible else "authorization_denied")
                if visible:
                    result["data"].update(field=error.field, guidance=error.guidance)
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
