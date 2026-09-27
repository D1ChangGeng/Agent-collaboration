"""SQLite component fixture for exercising the MCP wire contract.

This fixture has no Domain authorization or native Harness delivery. Its
observations are component evidence only and cannot establish a Runtime Gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

RESULT_SCHEMA = "acs-mcp-result/3"
CONTEXT_SCHEMA = "acs-project-context-pack/1"
SERVER_SCHEMA = "acs-mcp-runtime/1"
_HANDLE = re.compile(r"^[a-z_]+:[a-zA-Z0-9._:-]{3,512}$")
_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,127}$")
_GLOBAL_TOOLS = {"read_profile", "list_projects", "list_connections"}
_ARRAY_FIELDS = {
    "handles", "constraints", "required_evidence", "target_handles", "event_kinds",
    "states", "kinds", "include", "members", "policies", "budgets",
    "required_capabilities", "harness_kinds", "criteria", "reviewer_requirements",
    "findings", "evidence_handles", "unresolved_items", "paths", "source_binding_ids",
    "context_handles", "evidence_bundle_handles", "review_handles",
}
_OBJECT_FIELDS = {
    "target", "source_readback", "precondition", "patch", "changes",
    "accepted_state", "source_state", "context", "notification", "budget",
}
_BOOL_FIELDS = {
    "enabled", "expect_response", "consume", "blocked", "product_owner_authorized",
    "require_ack",
}
_INT_FIELDS = {
    "expected_revision", "expected_work_revision", "accepted_revision", "at_revision",
    "start_line", "end_line", "max_inline_bytes", "depth", "limit", "timeout_seconds",
    "wait_timeout_seconds", "expected_subscription_revision",
}


class McpRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False,
                 details: dict[str, Any] | None = None) -> None:
        self.code, self.retryable, self.details = code, retryable, details or {}
        super().__init__(message)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False, default=str)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _git(root: Path, *arguments: str, maximum: int = 2_000_000) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=root, capture_output=True, timeout=30, check=False,
    )
    if result.returncode != 0 or len(result.stdout) > maximum:
        raise McpRuntimeError("source_read_failed", "Git source read failed")
    return result.stdout.decode("utf-8", errors="replace")


class McpRuntime:
    """Durable typed MCP surface for one authenticated Profile."""

    def __init__(
        self,
        database: str | Path,
        catalog: str | Path,
        *,
        profile: str,
        subject: str,
        delivery_handler: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
        skill_catalog: str | Path | None = None,
    ) -> None:
        self.database = Path(database)
        self.catalog_path = Path(catalog)
        self.catalog = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        if self.catalog.get("schema_version") != "acs-p2-mcp-tool-contract/6":
            raise McpRuntimeError("contract_changed", "MCP tool contract revision differs")
        profiles = self.catalog.get("profiles", {})
        if profile not in profiles or not isinstance(subject, str) or not subject:
            raise McpRuntimeError("profile_denied", "Authenticated MCP Profile is unavailable")
        self.profile, self.subject = profile, subject
        self.allowed = tuple(profiles[profile])
        self.delivery_handler = delivery_handler
        self.skill_catalog_path = Path(skill_catalog) if skill_catalog else None
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        schema = """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS projects(
          project_id TEXT PRIMARY KEY,name TEXT NOT NULL,management_root TEXT NOT NULL,
          source_root TEXT NOT NULL,root_handle TEXT NOT NULL UNIQUE,revision INTEGER NOT NULL,
          state TEXT NOT NULL,instructions_json TEXT NOT NULL,manifest_json TEXT NOT NULL,
          policy_json TEXT NOT NULL,knowledge_json TEXT NOT NULL,created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sources(
          project_id TEXT NOT NULL,source_id TEXT NOT NULL,root TEXT NOT NULL,
          branch TEXT NOT NULL,commit_id TEXT NOT NULL,tree_id TEXT NOT NULL,
          revision INTEGER NOT NULL,push_state TEXT NOT NULL,receiver_sync_state TEXT NOT NULL,
          observed_at TEXT NOT NULL,PRIMARY KEY(project_id,source_id),
          FOREIGN KEY(project_id) REFERENCES projects(project_id));
        CREATE TABLE IF NOT EXISTS routes(
          project_id TEXT NOT NULL,route_id TEXT NOT NULL,handle TEXT NOT NULL UNIQUE,
          revision INTEGER NOT NULL,state TEXT NOT NULL,payload_json TEXT NOT NULL,
          updated_at TEXT NOT NULL,PRIMARY KEY(project_id,route_id));
        CREATE TABLE IF NOT EXISTS teams(
          project_id TEXT NOT NULL,scope_handle TEXT NOT NULL,revision INTEGER NOT NULL,
          payload_json TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(project_id,scope_handle));
        CREATE TABLE IF NOT EXISTS collaborators(
          project_id TEXT NOT NULL,slot_id TEXT NOT NULL,handle TEXT NOT NULL UNIQUE,
          scope_handle TEXT NOT NULL,role TEXT NOT NULL,harness TEXT NOT NULL,
          state TEXT NOT NULL,busy INTEGER NOT NULL DEFAULT 0,session_ref TEXT,
          capabilities_json TEXT NOT NULL,expires_at TEXT,revision INTEGER NOT NULL,
          updated_at TEXT NOT NULL,PRIMARY KEY(project_id,slot_id));
        CREATE TABLE IF NOT EXISTS works(
          project_id TEXT NOT NULL,work_id TEXT NOT NULL,handle TEXT NOT NULL UNIQUE,
          route_handle TEXT,revision INTEGER NOT NULL,state TEXT NOT NULL,assigned_to TEXT,
          payload_json TEXT NOT NULL,source_revision TEXT,updated_at TEXT NOT NULL,
          PRIMARY KEY(project_id,work_id));
        CREATE TABLE IF NOT EXISTS messages(
          project_id TEXT NOT NULL,message_id TEXT NOT NULL,handle TEXT NOT NULL UNIQUE,
          response_handle TEXT NOT NULL UNIQUE,work_handle TEXT NOT NULL,
          initiating_slot TEXT NOT NULL,target_slot TEXT NOT NULL,
          operation_id TEXT NOT NULL,state TEXT NOT NULL,receipt_high_water TEXT NOT NULL,
          request_json TEXT NOT NULL,response_json TEXT,delivery_policy TEXT NOT NULL,
          activation TEXT NOT NULL,expect_response INTEGER NOT NULL,created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,PRIMARY KEY(project_id,message_id));
        CREATE TABLE IF NOT EXISTS responses(
          project_id TEXT NOT NULL,response_handle TEXT PRIMARY KEY,message_id TEXT NOT NULL,
          state TEXT NOT NULL,completion_revision INTEGER NOT NULL,response_json TEXT,
          updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS subscriptions(
          project_id TEXT NOT NULL,subscription_id TEXT NOT NULL,handle TEXT NOT NULL UNIQUE,
          kind TEXT NOT NULL,target_json TEXT NOT NULL,event_kinds_json TEXT NOT NULL,
          enabled INTEGER NOT NULL,revision INTEGER NOT NULL,cursor INTEGER NOT NULL,
          session_ref TEXT,updated_at TEXT NOT NULL,PRIMARY KEY(project_id,subscription_id));
        CREATE TABLE IF NOT EXISTS events(
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,project_id TEXT NOT NULL,kind TEXT NOT NULL,
          target_handle TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS inbox(
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,project_id TEXT NOT NULL,kind TEXT NOT NULL,
          handle TEXT NOT NULL,owner_handle TEXT,state TEXT NOT NULL,payload_json TEXT NOT NULL,
          consumed_at TEXT,created_at TEXT NOT NULL,
          UNIQUE(project_id,kind,handle));
        CREATE TABLE IF NOT EXISTS notifications(
          project_id TEXT NOT NULL,response_handle TEXT NOT NULL,completion_revision INTEGER NOT NULL,
          notification_id TEXT NOT NULL UNIQUE,session_ref TEXT,state TEXT NOT NULL,
          created_at TEXT NOT NULL,PRIMARY KEY(project_id,response_handle,completion_revision));
        CREATE TABLE IF NOT EXISTS reviews(
          project_id TEXT NOT NULL,review_id TEXT NOT NULL,handle TEXT NOT NULL UNIQUE,
          work_handle TEXT NOT NULL,revision INTEGER NOT NULL,state TEXT NOT NULL,
          payload_json TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(project_id,review_id));
        CREATE TABLE IF NOT EXISTS evidence(
          project_id TEXT NOT NULL,evidence_id TEXT NOT NULL,handle TEXT NOT NULL UNIQUE,
          kind TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL,
          PRIMARY KEY(project_id,evidence_id));
        CREATE TABLE IF NOT EXISTS connections(
          connection_id TEXT PRIMARY KEY,kind TEXT NOT NULL,state TEXT NOT NULL,
          payload_json TEXT NOT NULL,observed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS dedup(
          subject TEXT NOT NULL,tool TEXT NOT NULL,client_request_id TEXT NOT NULL,
          input_digest TEXT NOT NULL,result_json TEXT NOT NULL,created_at TEXT NOT NULL,
          PRIMARY KEY(subject,tool,client_request_id));
        """
        with self._connect() as connection:
            connection.executescript(schema)

    # Administrative admission is intentionally outside the public MCP tool list.
    def adopt_project(
        self, *, project_id: str, name: str, management_root: str | Path,
        source_root: str | Path, instructions: dict[str, Any], manifest: dict[str, Any],
        policy: dict[str, Any] | None = None, knowledge: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not _ID.fullmatch(project_id):
            raise McpRuntimeError("invalid_project_id", "Project ID is invalid")
        management = Path(management_root).resolve(strict=True)
        source = Path(source_root).resolve(strict=True)
        if not management.is_dir() or not source.is_dir():
            raise McpRuntimeError("project_root_missing", "Project roots are unavailable")
        root_handle = f"project:{project_id}"
        observed = _now()
        commit = _git(source, "rev-parse", "HEAD").strip()
        tree = _git(source, "rev-parse", "HEAD^{tree}").strip()
        branch = _git(source, "branch", "--show-current").strip() or "detached"
        with self._connect() as connection:
            prior = connection.execute(
                "SELECT name,management_root,source_root,root_handle,revision FROM projects WHERE project_id=?",
                (project_id,),
            ).fetchone()
            identity = (name, str(management), str(source), root_handle)
            if prior is not None and tuple(prior[:4]) != identity:
                raise McpRuntimeError("project_identity_conflict", "Project identity cannot be replaced")
            revision = int(prior[4]) if prior else 1
            connection.execute(
                "INSERT INTO projects VALUES (?,?,?,?,?,?,'active',?,?,?,?,?,?) "
                "ON CONFLICT(project_id) DO UPDATE SET instructions_json=excluded.instructions_json,"
                "manifest_json=excluded.manifest_json,policy_json=excluded.policy_json,"
                "knowledge_json=excluded.knowledge_json,updated_at=excluded.updated_at",
                (project_id, name, str(management), str(source), root_handle, revision,
                 _canonical(instructions), _canonical(manifest), _canonical(policy or {}),
                 _canonical(knowledge or {}), observed, observed),
            )
            connection.execute(
                "INSERT INTO sources VALUES (?,?,?,?,?,?,1,'not_pushed','none',?) "
                "ON CONFLICT(project_id,source_id) DO UPDATE SET branch=excluded.branch,"
                "commit_id=excluded.commit_id,tree_id=excluded.tree_id,observed_at=excluded.observed_at",
                (project_id, "source-main", str(source), branch, commit, tree, observed),
            )
            self._event(connection, project_id, "project.adopted", root_handle,
                        {"revision": revision, "source_commit": commit, "source_tree": tree})
        return {"project_id": project_id, "root_handle": root_handle,
                "revision": revision, "source_commit": commit, "source_tree": tree}

    def register_harness(
        self, *, project_id: str, slot_id: str, harness: str, capabilities: list[str],
        session_ref: str, expires_at: str, role: str = "engineer",
        scope_handle: str | None = None,
    ) -> str:
        self._project(project_id)
        handle = f"collaborator:{project_id}:{slot_id}"
        scope = scope_handle or f"scope:{project_id}:default"
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO collaborators VALUES (?,?,?,?,?,?,'active',0,?,?,?,1,?) "
                "ON CONFLICT(project_id,slot_id) DO UPDATE SET harness=excluded.harness,"
                "state='active',session_ref=excluded.session_ref,capabilities_json=excluded.capabilities_json,"
                "expires_at=excluded.expires_at,revision=collaborators.revision+1,updated_at=excluded.updated_at",
                (project_id, slot_id, handle, scope, role, harness, session_ref,
                 _canonical(capabilities), expires_at, _now()),
            )
        return handle

    def register_connection(self, connection_id: str, kind: str,
                            payload: dict[str, Any], *, state: str = "active") -> None:
        if not _ID.fullmatch(connection_id):
            raise McpRuntimeError("connection_id_invalid", "Connection ID is invalid")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO connections VALUES (?,?,?,?,?) "
                "ON CONFLICT(connection_id) DO UPDATE SET state=excluded.state,"
                "payload_json=excluded.payload_json,observed_at=excluded.observed_at",
                (connection_id, kind, state, _canonical(payload), _now()),
            )

    def record_evidence(self, project_id: str, evidence_id: str, kind: str,
                        payload: dict[str, Any]) -> str:
        self._project(project_id)
        handle = f"evidence:{project_id}:{evidence_id}"
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO evidence VALUES (?,?,?,?,?,?)",
                (project_id, evidence_id, handle, kind, _canonical(payload), _now()),
            )
            self._event(connection, project_id, "evidence.recorded", handle, {"kind": kind})
        return handle

    def subscription_events(self, project_id: str, subscription_handle: str) -> list[dict[str, Any]]:
        self._assert_handle(project_id, subscription_handle)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT cursor,event_kinds_json,target_json FROM subscriptions "
                "WHERE project_id=? AND handle=?",
                (project_id, subscription_handle),
            ).fetchone()
            if row is None:
                raise McpRuntimeError("subscription_missing", "Subscription is unavailable")
            kinds, targets = set(json.loads(row[1])), set(json.loads(row[2]))
            events = connection.execute(
                "SELECT * FROM events WHERE project_id=? AND sequence>? ORDER BY sequence",
                (project_id, row[0]),
            ).fetchall()
        return [dict(item) for item in events
                if (not kinds or item["kind"] in kinds)
                and (not targets or item["target_handle"] in targets)]

    def set_session(self, project_id: str, slot_id: str, session_ref: str) -> None:
        self._project(project_id)
        with self._connect() as connection:
            if connection.execute(
                "UPDATE collaborators SET session_ref=?,revision=revision+1,updated_at=? "
                "WHERE project_id=? AND slot_id=?",
                (session_ref, _now(), project_id, slot_id),
            ).rowcount != 1:
                raise McpRuntimeError("collaborator_missing", "Collaborator is unavailable")
            handles = connection.execute(
                "SELECT response_handle FROM messages WHERE project_id=? AND initiating_slot=?",
                (project_id, slot_id),
            ).fetchall()
            for item in handles:
                connection.execute(
                    "UPDATE subscriptions SET session_ref=?,revision=revision+1,updated_at=? "
                    "WHERE project_id=? AND kind='response' AND target_json=?",
                    (session_ref, _now(), project_id, _canonical([item[0]])),
                )

    def set_target_busy(self, project_id: str, slot_id: str, busy: bool) -> None:
        with self._connect() as connection:
            if connection.execute(
                "UPDATE collaborators SET busy=?,updated_at=? WHERE project_id=? AND slot_id=?",
                (int(busy), _now(), project_id, slot_id),
            ).rowcount != 1:
                raise McpRuntimeError("collaborator_missing", "Collaborator is unavailable")

    def tools_list(self) -> dict[str, Any]:
        tools = []
        for name in self.allowed:
            definition = self.catalog["tools"][name]
            tools.append({
                "name": name,
                "title": definition["title"],
                "description": definition["description"],
                "inputSchema": self._json_schema(definition.get("input_schema", {})),
                "outputSchema": {
                    "type": "object", "additionalProperties": True,
                    "required": ["schema_version", "result_type", "ok", "state", "data",
                                 "follow_ups", "metadata"],
                    "properties": {
                        "schema_version": {"const": RESULT_SCHEMA},
                        "result_type": {"const": definition["result_type"]},
                        "ok": {"type": "boolean"}, "state": {"type": "string"},
                        "data": {"type": "object"}, "follow_ups": {"type": "array"},
                        "metadata": {"type": "object"},
                    },
                },
                "annotations": definition["annotations"],
                "securityScopes": definition.get("security_scopes", []),
                "_meta": {"acs/resultType": definition["result_type"],
                          "acs/profile": self.profile},
            })
        return {"tools": tools}

    @staticmethod
    def instructions() -> str:
        return (
            "Use list_projects and load_project when project context is absent or stale. "
            "Every project-scoped tool requires an explicit project_id; handles never grant access. "
            "Use asynchronous send_message by default and retain response follow-ups across reconnects."
        )

    @staticmethod
    def _json_schema(contract: dict[str, Any]) -> dict[str, Any]:
        required = contract.get("required", [])
        optional = contract.get("optional", [])
        properties: dict[str, Any] = {}
        for name in [*required, *optional]:
            if name in _ARRAY_FIELDS:
                properties[name] = {"type": "array"}
            elif name in _OBJECT_FIELDS:
                properties[name] = {"type": "object"}
            elif name in _BOOL_FIELDS:
                properties[name] = {"type": "boolean"}
            elif name in _INT_FIELDS or name.endswith(("_revision", "_seconds")):
                properties[name] = {"type": "integer"}
            else:
                properties[name] = {"type": "string"}
        return {"type": "object", "additionalProperties": False,
                "required": required, "properties": properties,
                "$comment": contract.get("schema_version", "")}

    def call(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        try:
            if name not in self.allowed:
                raise McpRuntimeError("tool_not_available", "Tool is not exposed by this Profile")
            if not isinstance(arguments, dict):
                raise McpRuntimeError("invalid_arguments", "Tool arguments must be an object")
            definition = self.catalog["tools"][name]
            self._validate_arguments(name, arguments, definition["input_schema"])
            result = self._deduplicated(name, arguments, lambda: self._dispatch(name, arguments))
            envelope = self._success(definition["result_type"], result[0], result[1], result[2])
            return self._wire(envelope, False)
        except McpRuntimeError as error:
            problem = {
                "schema_version": RESULT_SCHEMA, "result_type": "problem", "ok": False,
                "state": "rejected", "data": {"code": error.code, "message": str(error),
                "retryable": error.retryable, "details": error.details}, "follow_ups": [],
                "metadata": {"observed_at": _now(), "evidence_class": "authority_rejected"},
            }
            return self._wire(problem, True)

    @staticmethod
    def _wire(envelope: dict[str, Any], is_error: bool) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": _canonical(envelope)}],
                "structuredContent": envelope, "isError": is_error}

    @staticmethod
    def _success(result_type: str, state: str, data: dict[str, Any],
                 follow_ups: list[dict[str, Any]]) -> dict[str, Any]:
        return {"schema_version": RESULT_SCHEMA, "result_type": result_type, "ok": True,
                "state": state, "data": data, "follow_ups": follow_ups,
                "metadata": {"observed_at": _now(), "evidence_class": "authority_committed"}}

    def _validate_arguments(self, name: str, arguments: dict[str, Any], contract: dict[str, Any]) -> None:
        required, optional = set(contract.get("required", [])), set(contract.get("optional", []))
        if not required <= set(arguments) or set(arguments) - required - optional:
            raise McpRuntimeError("invalid_arguments", "Arguments differ from the closed tool schema")
        if name not in _GLOBAL_TOOLS:
            project_id = arguments.get("project_id")
            if not isinstance(project_id, str):
                raise McpRuntimeError("project_id_required", "Explicit project_id is required")
            self._project(project_id)
            for key, value in arguments.items():
                if key.endswith("handle") and isinstance(value, str):
                    self._assert_handle(project_id, value)
                if key.endswith("handles") and isinstance(value, list):
                    for item in value:
                        if isinstance(item, str):
                            self._assert_handle(project_id, item)
        if "deadline" in arguments:
            try:
                deadline = datetime.fromisoformat(str(arguments["deadline"]))
            except ValueError as exc:
                raise McpRuntimeError("invalid_deadline", "Deadline is malformed") from exc
            if deadline.tzinfo is None or deadline <= datetime.now(UTC):
                raise McpRuntimeError("deadline_expired", "Deadline is expired")

    def _deduplicated(self, name: str, arguments: dict[str, Any], action):
        request_id = arguments.get("client_request_id")
        if not isinstance(request_id, str):
            return action()
        digest = _digest(arguments)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT input_digest,result_json FROM dedup WHERE subject=? AND tool=? AND client_request_id=?",
                (self.subject, name, request_id),
            ).fetchone()
            if row:
                if row[0] != digest:
                    raise McpRuntimeError("idempotency_conflict", "client_request_id was reused")
                return json.loads(row[1])
        result = action()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO dedup VALUES (?,?,?,?,?,?)",
                (self.subject, name, request_id, digest, _canonical(result), _now()),
            )
        return result

    def _project(self, project_id: str) -> sqlite3.Row:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
        if row is None:
            raise McpRuntimeError("project_not_found", "Project is unavailable")
        return row

    def _assert_handle(self, project_id: str, handle: str) -> None:
        if not _HANDLE.fullmatch(handle) or f":{project_id}" not in handle:
            raise McpRuntimeError("project_handle_mismatch", "Handle belongs to another project")

    @staticmethod
    def _event(connection: sqlite3.Connection, project_id: str, kind: str,
               target: str, payload: dict[str, Any]) -> int:
        cursor = connection.execute(
            "INSERT INTO events(project_id,kind,target_handle,payload_json,created_at) VALUES (?,?,?,?,?)",
            (project_id, kind, target, _canonical(payload), _now()),
        )
        return int(cursor.lastrowid)

    def _dispatch(self, name: str, a: dict[str, Any]):
        method = getattr(self, "_tool_" + name, None)
        if method is None:
            if name in {"apply_patch", "create_branch", "commit_changes", "push_changes"}:
                raise McpRuntimeError("source_write_not_configured", "Source write provider is not configured")
            if name == "submit_command":
                raise McpRuntimeError("advanced_command_not_configured", "Advanced Domain command adapter is unavailable")
            return "observed", {"tool": name, "items": []}, []
        return method(a)

    def _tool_read_profile(self, _a):
        return "observed", {"profile": self.profile, "subject": self.subject,
                            "surface_revision": self.catalog["surface_revision"],
                            "tools": list(self.allowed)}, []

    def _tool_list_projects(self, a):
        limit = min(int(a.get("limit", 50)), 100)
        with self._connect() as c:
            rows = c.execute("SELECT project_id,name,root_handle,revision,state,updated_at FROM projects ORDER BY project_id LIMIT ?", (limit,)).fetchall()
        return "observed", {"items": [dict(row) for row in rows], "next_cursor": None}, []

    def _tool_list_connections(self, _a):
        with self._connect() as c:
            rows = c.execute("SELECT * FROM connections ORDER BY connection_id").fetchall()
        return "observed", {"items": [dict(row) for row in rows]}, []

    def _skills(self) -> list[dict[str, Any]]:
        if self.skill_catalog_path is None or not self.skill_catalog_path.is_file():
            return []
        value = json.loads(self.skill_catalog_path.read_text(encoding="utf-8"))
        items = value.get("skills", value if isinstance(value, list) else [])
        if isinstance(items, dict):
            items = [{"name": name, **item} for name, item in items.items()]
        result = []
        for item in items:
            if isinstance(item, dict):
                result.append({key: item.get(key) for key in ("name", "description", "path", "references") if key in item})
        return result

    def _tool_load_project(self, a):
        row = self._project(a["project_id"])
        with self._connect() as c:
            source = c.execute("SELECT * FROM sources WHERE project_id=? ORDER BY source_id", (a["project_id"],)).fetchall()
            routes = c.execute("SELECT handle,revision,state,payload_json FROM routes WHERE project_id=? ORDER BY route_id", (a["project_id"],)).fetchall()
            work = c.execute("SELECT handle,revision,state,assigned_to FROM works WHERE project_id=? AND state NOT IN ('accepted','cancelled') ORDER BY work_id", (a["project_id"],)).fetchall()
        skills = self._skills()
        data = {
            "schema_version": CONTEXT_SCHEMA, "project_id": row["project_id"],
            "project_revision": row["revision"], "root_handle": row["root_handle"],
            "management_root": row["management_root"],
            "instructions": json.loads(row["instructions_json"]),
            "manifest": json.loads(row["manifest_json"]), "policy": json.loads(row["policy_json"]),
            "knowledge_index": json.loads(row["knowledge_json"]),
            "source_bindings": [dict(item) for item in source],
            "routes": [{**dict(item), "payload": json.loads(item["payload_json"])} for item in routes],
            "active_work": [dict(item) for item in work],
            "skills": skills,
            "knowledge_hint": ([{"skill": skills[0].get("name"), "load": "metadata_first",
                                  "references": "selective"}] if skills else []),
        }
        return "observed", data, []

    def _page(self, table: str, project_id: str, order: str, fields="*"):
        with self._connect() as c:
            rows = c.execute(f"SELECT {fields} FROM {table} WHERE project_id=? ORDER BY {order}", (project_id,)).fetchall()
        return [dict(row) for row in rows]

    def _tool_list_routes(self, a):
        return "observed", {"items": self._page("routes", a["project_id"], "route_id")}, []

    def _tool_list_work(self, a):
        return "observed", {"items": self._page("works", a["project_id"], "work_id")}, []

    def _tool_list_collaborators(self, a):
        return "observed", {"items": self._page("collaborators", a["project_id"], "slot_id")}, []

    def _tool_list_harnesses(self, a):
        required = set(a["required_capabilities"])
        now = datetime.now(UTC)
        items = []
        for row in self._page("collaborators", a["project_id"], "slot_id"):
            capabilities = set(json.loads(row["capabilities_json"]))
            expires = datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else now
            if row["state"] == "active" and expires > now and required <= capabilities:
                items.append({**row, "capabilities": sorted(capabilities), "eligible": True})
        return "observed", {"items": items, "required_capabilities": sorted(required)}, []

    def _tool_list_sources(self, a):
        return "observed", {"items": self._page("sources", a["project_id"], "source_id")}, []

    def _tool_list_activity(self, a):
        with self._connect() as c:
            rows = c.execute("SELECT * FROM events WHERE project_id=? ORDER BY sequence DESC LIMIT ?", (a["project_id"], min(int(a.get("limit", 50)), 200))).fetchall()
        return "observed", {"items": [dict(row) for row in rows]}, []

    def _tool_list_evidence(self, a):
        return "observed", {"items": self._page("evidence", a["project_id"], "evidence_id")}, []

    def _tool_list_reviews(self, a):
        return "observed", {"items": self._page("reviews", a["project_id"], "review_id")}, []

    def _tool_create_route(self, a):
        route_id = a.get("route_id") or uuid.uuid4().hex
        handle = f"route:{a['project_id']}:{route_id}"
        payload = dict(a, handle=handle)
        with self._connect() as c:
            c.execute("INSERT INTO routes VALUES (?,?,?,?,?,?,?)", (a["project_id"], route_id, handle, 1, "active", _canonical(payload), _now()))
            self._event(c, a["project_id"], "route.created", handle, {"revision": 1})
        return "created", {"route_handle": handle, "route_revision": 1}, []

    def _tool_update_route(self, a):
        handle = a["route_handle"]
        with self._connect() as c:
            row = c.execute("SELECT revision,payload_json FROM routes WHERE project_id=? AND handle=?", (a["project_id"], handle)).fetchone()
            if row is None or row[0] != a["expected_revision"]:
                raise McpRuntimeError("revision_conflict", "Route revision changed", details={"current_revision": row[0] if row else None})
            payload = {**json.loads(row[1]), **a}
            revision = row[0] + 1
            c.execute("UPDATE routes SET revision=?,payload_json=?,updated_at=? WHERE handle=?", (revision, _canonical(payload), _now(), handle))
            self._event(c, a["project_id"], "route.updated", handle, {"revision": revision})
        return "updated", {"route_handle": handle, "route_revision": revision}, []

    def _tool_configure_team(self, a):
        project_id, scope = a["project_id"], a["scope_handle"]
        with self._connect() as c:
            row = c.execute("SELECT revision FROM teams WHERE project_id=? AND scope_handle=?", (project_id, scope)).fetchone()
            current = row[0] if row else 0
            if current != a["expected_revision"]:
                raise McpRuntimeError("revision_conflict", "Team revision changed", details={"current_revision": current})
            revision = current + 1
            c.execute("INSERT INTO teams VALUES (?,?,?,?,?) ON CONFLICT(project_id,scope_handle) DO UPDATE SET revision=excluded.revision,payload_json=excluded.payload_json,updated_at=excluded.updated_at", (project_id, scope, revision, _canonical(a), _now()))
            handles = []
            for item in a["members"]:
                slot = item["slot_id"]
                handle = f"collaborator:{project_id}:{slot}"
                handles.append(handle)
                c.execute("INSERT INTO collaborators VALUES (?,?,?,?,?,?,'active',0,?,?,?,1,?) ON CONFLICT(project_id,slot_id) DO UPDATE SET role=excluded.role,harness=excluded.harness,state='active',session_ref=excluded.session_ref,capabilities_json=excluded.capabilities_json,expires_at=excluded.expires_at,revision=collaborators.revision+1,updated_at=excluded.updated_at", (project_id, slot, handle, scope, item.get("role", "engineer"), item.get("harness", "unknown"), item.get("session_ref"), _canonical(item.get("capabilities", [])), item.get("expires_at"), _now()))
            self._event(c, project_id, "team.configured", scope, {"revision": revision, "members": handles})
        return "configured", {"team_handle": f"team:{project_id}:{scope.split(':')[-1]}", "team_revision": revision, "scope_handle": scope, "member_handles": handles}, []

    def _tool_create_work(self, a):
        with self._connect() as c:
            route = c.execute(
                "SELECT revision FROM routes WHERE project_id=? AND handle=?",
                (a["project_id"], a["route_handle"]),
            ).fetchone()
        if route is None or route[0] != a["expected_route_revision"]:
            raise McpRuntimeError("revision_conflict", "Route revision changed")
        work_id = a.get("work_item_id") or uuid.uuid4().hex
        handle = f"work:{a['project_id']}:{work_id}"
        with self._connect() as c:
            c.execute("INSERT INTO works VALUES (?,?,?,?,?,'candidate',?,?,?,?)", (a["project_id"], work_id, handle, a.get("route_handle"), 1, a.get("assigned_to"), _canonical(a), a.get("source_revision"), _now()))
            self._event(c, a["project_id"], "work.created", handle, {"revision": 1})
        return "created", {"work_handle": handle, "work_revision": 1}, []

    def _tool_revise_work(self, a):
        return self._revise_work(a, "work.revised")

    def _tool_handoff_work(self, a):
        return self._revise_work(a, "work.handed_off")

    def _revise_work(self, a, event):
        handle = a["work_handle"]
        with self._connect() as c:
            row = c.execute("SELECT revision,payload_json FROM works WHERE project_id=? AND handle=?", (a["project_id"], handle)).fetchone()
            if row is None or row[0] != a["expected_revision"]:
                raise McpRuntimeError("revision_conflict", "Work revision changed", details={"current_revision": row[0] if row else None})
            revision = row[0] + 1
            payload = {**json.loads(row[1]), **a}
            c.execute("UPDATE works SET revision=?,payload_json=?,assigned_to=COALESCE(?,assigned_to),updated_at=? WHERE handle=?", (revision, _canonical(payload), a.get("assigned_to") or a.get("target_agent_slot"), _now(), handle))
            self._event(c, a["project_id"], event, handle, {"revision": revision})
        return "updated", {"work_handle": handle, "work_revision": revision}, []

    def _tool_send_message(self, a):
        project_id = a["project_id"]
        target = a["target"]
        slot = target.get("agent_slot_id") or target.get("slot_id")
        if not isinstance(slot, str):
            raise McpRuntimeError("target_invalid", "Target AgentSlot is required")
        with self._connect() as c:
            work = c.execute("SELECT revision FROM works WHERE project_id=? AND handle=?", (project_id, a["work_handle"])).fetchone()
            collaborator = c.execute("SELECT state,busy,session_ref FROM collaborators WHERE project_id=? AND slot_id=?", (project_id, slot)).fetchone()
            initiator = c.execute(
                "SELECT slot_id,session_ref FROM collaborators WHERE project_id=? "
                "AND (slot_id=? OR handle=?)",
                (project_id, self.subject, self.subject),
            ).fetchone()
            if work is None or work[0] != a["expected_work_revision"]:
                raise McpRuntimeError("revision_conflict", "Work revision changed")
            if collaborator is None or collaborator[0] != "active":
                raise McpRuntimeError("target_unavailable", "Target AgentSlot is unavailable", retryable=True)
            if initiator is None:
                raise McpRuntimeError("initiator_unavailable", "Initiating AgentSlot is unavailable")
            message_id, operation_id = "message-" + uuid.uuid4().hex, "operation-" + uuid.uuid4().hex
            handle, response = f"message:{project_id}:{message_id}", f"response:{project_id}:{message_id}"
            activation = a.get("activation", "invoke")
            policy = a.get("delivery_policy", "queue_until_idle")
            expect = bool(a.get("expect_response", True))
            state = "queued" if collaborator[1] or policy == "queue_until_idle" else "ready"
            c.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (project_id, message_id, handle, response, a["work_handle"], initiator[0], slot, operation_id, state, "accepted_by_authority", _canonical(a), None, policy, activation, int(expect), _now(), _now()))
            c.execute("INSERT INTO responses VALUES (?,?,?,'pending',0,NULL,?)", (project_id, response, message_id, _now()))
            sub_id = "response-" + message_id
            c.execute("INSERT INTO subscriptions VALUES (?,?,?,?,?,?,1,1,0,?,?)", (project_id, sub_id, f"subscription:{project_id}:{sub_id}", "response", _canonical([response]), _canonical(["response.completed"]), initiator[1], _now()))
            c.execute("INSERT INTO inbox(project_id,kind,handle,owner_handle,state,payload_json,created_at) VALUES (?,?,?,?,?,?,?)", (project_id, "message", handle, f"collaborator:{project_id}:{slot}", "unread", _canonical({"message_id": message_id, "response_handle": response}), _now()))
            self._event(c, project_id, "message.accepted", handle, {"operation_id": operation_id, "response_handle": response})
        follow = [
            {"rel": "read_response", "tool": "read_message", "arguments": {"project_id": project_id, "handle": response, "consume": True}},
            {"rel": "wait", "tool": "wait_for_response", "arguments": {"project_id": project_id, "handles": [response], "mode": "all", "until": "response_received", "timeout_seconds": 30}},
            {"rel": "notification", "tool": "set_notification", "arguments": {"client_request_id": "set-" + message_id, "project_id": project_id, "target_handle": response, "enabled": True, "expected_revision": 1, "reason": "completion", "deadline": a["deadline"]}},
        ]
        if a.get("response_mode", "async") == "sync":
            self.process_pending(project_id=project_id)
            observation = self._wait(project_id, [response], "all", a.get("wait_until", "response_received"), int(a.get("wait_timeout_seconds", 30)))
            state = observation[0]
        return state, {"operation_id": operation_id, "message_handle": handle,
                       "message_id": message_id, "delivery_state": state,
                       "response_handle": response,
                       "notification_handle": f"subscription:{project_id}:{sub_id}"}, follow

    def process_pending(self, *, project_id: str | None = None) -> list[str]:
        completed = []
        with self._connect() as c:
            query = "SELECT m.*,c.busy,c.session_ref FROM messages m JOIN collaborators c ON c.project_id=m.project_id AND c.slot_id=m.target_slot WHERE m.state IN ('queued','ready')"
            params: tuple[Any, ...] = ()
            if project_id:
                query += " AND m.project_id=?"; params = (project_id,)
            rows = c.execute(query + " ORDER BY m.created_at", params).fetchall()
            for row in rows:
                if row["busy"]:
                    continue
                request = json.loads(row["request_json"])
                response = self.delivery_handler(request) if self.delivery_handler else None
                if response is None:
                    continue
                response_handle = row["response_handle"]
                revision = c.execute("SELECT completion_revision FROM responses WHERE response_handle=?", (response_handle,)).fetchone()[0] + 1
                c.execute("UPDATE messages SET state='delivered',receipt_high_water='response_received',response_json=?,updated_at=? WHERE project_id=? AND message_id=?", (_canonical(response), _now(), row["project_id"], row["message_id"]))
                c.execute("UPDATE responses SET state='completed',completion_revision=?,response_json=?,updated_at=? WHERE response_handle=?", (revision, _canonical(response), _now(), response_handle))
                c.execute("INSERT INTO inbox(project_id,kind,handle,owner_handle,state,payload_json,created_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(project_id,kind,handle) DO NOTHING", (row["project_id"], "response", response_handle, None, "unread", _canonical({"completion_revision": revision}), _now()))
                subscription = c.execute("SELECT enabled FROM subscriptions WHERE project_id=? AND kind='response' AND target_json=?", (row["project_id"], _canonical([response_handle]))).fetchone()
                if subscription and subscription[0]:
                    notification_id = "notification-" + _digest([response_handle, revision])[:24]
                    current_session = c.execute("SELECT session_ref FROM collaborators WHERE project_id=? AND slot_id=?", (row["project_id"], row["initiating_slot"])).fetchone()[0]
                    c.execute("INSERT OR IGNORE INTO notifications VALUES (?,?,?,?,?,'pending',?)", (row["project_id"], response_handle, revision, notification_id, current_session, _now()))
                self._event(c, row["project_id"], "response.completed", response_handle, {"completion_revision": revision})
                completed.append(response_handle)
        return completed

    def _wait(self, project_id, handles, mode, until, timeout):
        end = time.monotonic() + max(0, min(timeout, 300))
        while True:
            with self._connect() as c:
                rows = c.execute(f"SELECT response_handle,state,completion_revision,response_json FROM responses WHERE project_id=? AND response_handle IN ({','.join('?' for _ in handles)})", (project_id, *handles)).fetchall()
            values = {row["response_handle"]: dict(row) for row in rows}
            satisfied = [h for h in handles if values.get(h, {}).get("state") == "completed"]
            if (mode == "any" and satisfied) or (mode == "all" and len(satisfied) == len(handles)) or time.monotonic() >= end:
                return ("completed" if satisfied else "pending", {"satisfied": satisfied, "pending": [h for h in handles if h not in satisfied], "responses": values, "mode": mode, "until": until}, [])
            time.sleep(0.05)

    def _tool_wait_for_response(self, a):
        if a["mode"] not in {"any", "all"}:
            raise McpRuntimeError("invalid_wait_mode", "Wait mode is invalid")
        return self._wait(a["project_id"], a["handles"], a["mode"], a["until"], int(a["timeout_seconds"]))

    def _tool_watch_changes(self, a):
        sub_id = "watch-" + uuid.uuid4().hex
        handle = f"subscription:{a['project_id']}:{sub_id}"
        with self._connect() as c:
            cursor = c.execute("SELECT COALESCE(max(sequence),0) FROM events WHERE project_id=?", (a["project_id"],)).fetchone()[0]
            c.execute("INSERT INTO subscriptions VALUES (?,?,?,?,?,?,1,1,?,?,?)", (a["project_id"], sub_id, handle, "watch", _canonical(a["target_handles"]), _canonical(a["event_kinds"]), cursor, None, _now()))
        return "subscribed", {"subscription_handle": handle, "revision": 1, "cursor": cursor}, []

    def _tool_set_notification(self, a):
        with self._connect() as c:
            row = c.execute("SELECT subscription_id,revision FROM subscriptions WHERE project_id=? AND kind='response' AND target_json=?", (a["project_id"], _canonical([a["target_handle"]]))).fetchone()
            if row is None or row[1] != a["expected_revision"]:
                raise McpRuntimeError("revision_conflict", "Notification subscription revision changed")
            revision = row[1] + 1
            c.execute("UPDATE subscriptions SET enabled=?,revision=?,updated_at=? WHERE project_id=? AND subscription_id=?", (int(a["enabled"]), revision, _now(), a["project_id"], row[0]))
        return "updated", {"target_handle": a["target_handle"], "enabled": a["enabled"], "revision": revision}, []

    def _tool_check_inbox(self, a):
        limit = min(int(a.get("limit", 50)), 200)
        cursor = int(a.get("cursor") or 0)
        with self._connect() as c:
            rows = c.execute("SELECT * FROM inbox WHERE project_id=? AND sequence>? ORDER BY sequence LIMIT ?", (a["project_id"], cursor, limit)).fetchall()
        items = [{**dict(row), "payload": json.loads(row["payload_json"]),
                  "follow_up": {"tool": "read_message", "arguments": {"project_id": a["project_id"], "handle": row["handle"], "consume": True}}} for row in rows]
        return "observed", {"items": items, "next_cursor": items[-1]["sequence"] if items else cursor}, []

    def _tool_read_message(self, a):
        handle = a["handle"]
        with self._connect() as c:
            row = c.execute("SELECT * FROM messages WHERE project_id=? AND (handle=? OR response_handle=?)", (a["project_id"], handle, handle)).fetchone()
            if row is None:
                raise McpRuntimeError("message_not_found", "Message or response is unavailable")
            if a.get("consume", True):
                c.execute("UPDATE inbox SET state='consumed',consumed_at=? WHERE project_id=? AND handle=?", (_now(), a["project_id"], handle))
        return "observed", {"message_id": row["message_id"], "message_handle": row["handle"], "response_handle": row["response_handle"], "state": row["state"], "receipt_high_water": row["receipt_high_water"], "request": json.loads(row["request_json"]), "response": json.loads(row["response_json"]) if row["response_json"] else None}, []

    def _source(self, project_id: str, source_id: str) -> sqlite3.Row:
        with self._connect() as c:
            row = c.execute("SELECT * FROM sources WHERE project_id=? AND source_id=?", (project_id, source_id)).fetchone()
        if row is None:
            raise McpRuntimeError("source_not_found", "SourceBinding is unavailable")
        return row

    @staticmethod
    def _safe_source_path(source: sqlite3.Row, relative: str, *, must_exist=True) -> Path:
        root = Path(source["root"]).resolve(strict=True)
        candidate = (root / relative).resolve(strict=must_exist)
        if not candidate.is_relative_to(root):
            raise McpRuntimeError("source_path_denied", "Source path left the binding")
        return candidate

    @staticmethod
    def _source_revision(source: sqlite3.Row, revision: str) -> None:
        if revision not in {source["commit_id"], source["tree_id"], source["branch"]}:
            raise McpRuntimeError("source_revision_changed", "Source revision is not current")

    def _tool_list_files(self, a):
        source = self._source(a["project_id"], a["source_id"]); self._source_revision(source, a["revision"])
        root = self._safe_source_path(source, a["path"])
        depth, limit = int(a.get("depth", 1)), min(int(a.get("limit", 100)), 500)
        base_parts = len(root.parts); items = []
        for path in sorted(root.rglob("*")):
            if len(path.parts) - base_parts > depth or ".git" in path.parts:
                continue
            items.append({"path": path.relative_to(Path(source["root"])).as_posix(), "kind": "directory" if path.is_dir() else "file", "bytes": path.stat().st_size if path.is_file() else None})
            if len(items) >= limit: break
        return "observed", {"source_id": source["source_id"], "revision": a["revision"], "items": items}, []

    def _tool_search_files(self, a):
        source = self._source(a["project_id"], a["source_id"]); self._source_revision(source, a["revision"])
        root = self._safe_source_path(source, a.get("path", ".")); query = a["query"]
        items = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or ".git" in path.parts or path.stat().st_size > 1_000_000: continue
            if query in path.name:
                items.append({"path": path.relative_to(Path(source["root"])).as_posix(), "match": "path"})
            else:
                try: text = path.read_text(encoding="utf-8")
                except (UnicodeError, OSError): continue
                if query in text: items.append({"path": path.relative_to(Path(source["root"])).as_posix(), "match": "content"})
            if len(items) >= min(int(a.get("limit", 50)), 200): break
        return "observed", {"items": items, "revision": a["revision"]}, []

    def _tool_read_file(self, a):
        source = self._source(a["project_id"], a["source_id"]); self._source_revision(source, a["revision"])
        path = self._safe_source_path(source, a["path"])
        if not path.is_file() or path.stat().st_size > 2_000_000:
            raise McpRuntimeError("file_unavailable", "Source file is unavailable or too large")
        lines = path.read_text(encoding="utf-8").splitlines()
        start = max(1, int(a.get("start_line", 1))); end = min(len(lines), int(a.get("end_line", len(lines))))
        content = "\n".join(lines[start - 1:end]); maximum = int(a.get("max_inline_bytes", 32768))
        if len(content.encode()) > maximum:
            content = content.encode()[:maximum].decode("utf-8", errors="ignore")
        return "observed", {"path": a["path"], "revision": a["revision"], "start_line": start, "end_line": end, "content": content, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}, []

    def _tool_read_source(self, a):
        source = dict(self._source(a["project_id"], a["source_id"]))
        root = Path(source["root"])
        source["working_tree"] = _git(root, "status", "--porcelain")
        source["current_commit"] = _git(root, "rev-parse", "HEAD").strip()
        source["current_tree"] = _git(root, "rev-parse", "HEAD^{tree}").strip()
        return "observed", source, []

    def _tool_read_diff(self, a):
        source = self._source(a["project_id"], a["source_id"]); root = Path(source["root"])
        arguments = ["diff", "--no-ext-diff", a["base_revision"], a["target_revision"]]
        if a.get("paths"): arguments.extend(["--", *a["paths"]])
        content = _git(root, *arguments, maximum=int(a.get("max_inline_bytes", 65536)) + 1)
        return "observed", {"base_revision": a["base_revision"], "target_revision": a["target_revision"], "diff": content, "sha256": hashlib.sha256(content.encode()).hexdigest()}, []

    def _tool_read_resource(self, a):
        handle = a["handle"]; project_id = a["project_id"]
        table = "routes" if handle.startswith("route:") else "works" if handle.startswith("work:") else "reviews" if handle.startswith("review:") else "evidence" if handle.startswith("evidence:") else None
        if handle == f"project:{project_id}":
            row = dict(self._project(project_id)); return "observed", row, []
        if table is None:
            raise McpRuntimeError("resource_type_unsupported", "Resource handle type is unsupported")
        with self._connect() as c:
            row = c.execute(f"SELECT * FROM {table} WHERE project_id=? AND handle=?", (project_id, handle)).fetchone()
        if row is None: raise McpRuntimeError("resource_not_found", "Resource is unavailable")
        data = dict(row)
        if "payload_json" in data: data["payload"] = json.loads(data.pop("payload_json"))
        return "observed", data, []

    def _tool_request_review(self, a):
        review_id = uuid.uuid4().hex; handle = f"review:{a['project_id']}:{review_id}"
        with self._connect() as c:
            c.execute("INSERT INTO reviews VALUES (?,?,?,?,1,'requested',?,?)", (a["project_id"], review_id, handle, a["work_handle"], _canonical(a), _now()))
            c.execute("INSERT INTO inbox(project_id,kind,handle,owner_handle,state,payload_json,created_at) VALUES (?,?,?,?,?,?,?)", (a["project_id"], "review", handle, None, "unread", _canonical({"review_type": a["review_type"]}), _now()))
            self._event(c, a["project_id"], "review.requested", handle, {"revision": 1})
        return "requested", {"review_handle": handle, "revision": 1}, []

    def _tool_submit_review(self, a):
        with self._connect() as c:
            row = c.execute("SELECT revision,payload_json FROM reviews WHERE project_id=? AND handle=?", (a["project_id"], a["review_handle"])).fetchone()
            if row is None or row[0] != a["expected_revision"]: raise McpRuntimeError("revision_conflict", "Review revision changed")
            revision = row[0] + 1; payload = {**json.loads(row[1]), **a}
            c.execute("UPDATE reviews SET revision=?,state='submitted',payload_json=?,updated_at=? WHERE handle=?", (revision, _canonical(payload), _now(), a["review_handle"]))
            self._event(c, a["project_id"], "review.submitted", a["review_handle"], {"decision": a["decision"], "revision": revision})
        return "submitted", {"review_handle": a["review_handle"], "revision": revision, "decision": a["decision"]}, []

    def _tool_accept_work(self, a):
        if not a.get("product_owner_authorized", False):
            raise McpRuntimeError("product_owner_authorization_required", "AcceptedStateRevision remains product-owner controlled")
        return "accepted", {"work_handle": a["work_handle"], "accepted_state_revision": a.get("expected_work_revision", 0) + 1}, []

    def _tool_cancel_work(self, a):
        with self._connect() as c:
            c.execute("UPDATE works SET state='cancelled',revision=revision+1,updated_at=? WHERE project_id=? AND handle=?", (_now(), a["project_id"], a["work_handle"]))
        return "cancelled", {"work_handle": a["work_handle"]}, []

    def _tool_stop_attempt(self, a):
        return "stop_requested", {"attempt_handle": a.get("attempt_handle")}, []

    def serve_stdio(self, input_stream=None, output_stream=None) -> None:
        source, target = input_stream or sys.stdin, output_stream or sys.stdout
        for line in source:
            try:
                request = json.loads(line)
                method, params = request.get("method"), request.get("params", {})
                if method == "initialize":
                    result = {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                              "capabilities": {"tools": {"listChanged": False}, "resources": {}},
                              "serverInfo": {"name": "acs-runtime", "version": "1"},
                              "instructions": self.instructions()}
                elif method == "tools/list": result = self.tools_list()
                elif method == "tools/call": result = self.call(params.get("name"), params.get("arguments"))
                elif method == "resources/list": result = self.resources_list()
                elif method == "resources/read": result = self.resources_read(params.get("uri", ""))
                elif method in {"notifications/initialized", "ping"}: result = {} if method != "ping" else {"ok": True}
                else: raise McpRuntimeError("method_not_found", "MCP method is unsupported")
                if "id" in request:
                    target.write(_canonical({"jsonrpc": "2.0", "id": request["id"], "result": result}) + "\n"); target.flush()
            except Exception as error:  # noqa: BLE001 - bounded transport response
                request_id = request.get("id") if isinstance(locals().get("request"), dict) else None
                target.write(_canonical({"jsonrpc": "2.0", "id": request_id,
                                         "error": {"code": -32603, "message": str(error)[:300]}}) + "\n"); target.flush()

    def resources_list(self) -> dict[str, Any]:
        resources = []
        for project in self._tool_list_projects({})[1]["items"]:
            project_id = project["project_id"]
            resources.append({"uri": f"acs://projects/{project_id}/context", "name": project_id + " context", "mimeType": "application/json"})
            resources.append({"uri": f"acs://projects/{project_id}/inbox", "name": project_id + " inbox", "mimeType": "application/json"})
        return {"resources": resources}

    def resources_read(self, uri: str) -> dict[str, Any]:
        match = re.fullmatch(r"acs://projects/([^/]+)/(context|inbox)", uri)
        if match is None: raise McpRuntimeError("resource_not_found", "MCP resource is unavailable")
        project_id, kind = match.groups(); self._project(project_id)
        data = self._tool_load_project({"project_id": project_id})[1] if kind == "context" else self._tool_check_inbox({"project_id": project_id})[1]
        return {"contents": [{"uri": uri, "mimeType": "application/json", "text": _canonical(data)}]}


class McpHttpServer:
    """Loopback HTTP JSON-RPC transport with an owner-supplied bearer token."""

    def __init__(self, runtime: McpRuntime, host: str, port: int, token: str) -> None:
        if host not in {"127.0.0.1", "::1"} or len(token) < 32:
            raise McpRuntimeError("http_binding_denied", "HTTP MCP requires loopback and a bounded token")
        expected = "Bearer " + token

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args): return
            def do_POST(self):
                if self.path != "/mcp" or self.headers.get("Authorization") != expected:
                    self.send_response(403); self.end_headers(); return
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1_000_000:
                    self.send_response(413); self.end_headers(); return
                request = json.loads(self.rfile.read(length))
                method, params = request.get("method"), request.get("params", {})
                if method == "tools/list": result = runtime.tools_list()
                elif method == "tools/call": result = runtime.call(params.get("name"), params.get("arguments"))
                elif method == "resources/list": result = runtime.resources_list()
                elif method == "resources/read": result = runtime.resources_read(params.get("uri", ""))
                elif method == "initialize": result = {"protocolVersion": params.get("protocolVersion", "2025-06-18"), "capabilities": {"tools": {}, "resources": {}}, "serverInfo": {"name": "acs-runtime", "version": "1"}, "instructions": runtime.instructions()}
                else: result = {"error": "method_not_found"}
                body = _canonical({"jsonrpc": "2.0", "id": request.get("id"), "result": result}).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        self.server = ThreadingHTTPServer((host, port), Handler)

    @property
    def address(self): return self.server.server_address
    def serve_forever(self): self.server.serve_forever(poll_interval=0.1)
    def close(self): self.server.shutdown(); self.server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--skill-catalog", type=Path)
    args = parser.parse_args(argv)
    runtime = McpRuntime(args.database, args.catalog, profile=args.profile,
                         subject=args.subject, skill_catalog=args.skill_catalog)
    runtime.serve_stdio()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
