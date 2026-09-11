"""Concrete Codex App Server stdio driver, reference profiles 0.152.1/0.153.2.

Protocol inputs: binary-generated experimental schemas; fixed upstream sources
5adb68a49933ae446bf11935662c83dba55a0804 and
657a993cbee87acf52d14b758ce49dbd46d1b8eb. Public documentation:
https://learn.chatgpt.com/docs/app-server

Node authenticates AuthorizedOperation, supplies an isolated immutable launch
profile and enforces Scope/Attempt ownership. This module performs no planning.
Attach is read-only. A surviving stdio process cannot be reconnected by guessing
a PID: Node must supply a live authorized transport. Lost ACKs never auto-retry.
Native settings checks are not OS containment or cross-machine Gate evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
import tomllib
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

if __package__:
    from .codex_jsonrpc import JsonRpcClient
else:
    from codex_jsonrpc import JsonRpcClient


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_digest(path):
    result = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


class DriverRejected(ValueError):
    pass


class OutcomeUncertain(RuntimeError):
    pass


@dataclass(frozen=True)
class AuthorizedOperation:
    operation_id: str
    command_id: str
    message_id: str
    grant_ref: str
    deadline: datetime

    def validate(self):
        if any(
            not isinstance(value, str) or not 1 <= len(value) <= 256
            for value in (self.operation_id, self.command_id, self.message_id, self.grant_ref)
        ):
            raise DriverRejected(
                "complete bounded operation/command/message/Grant identity required"
            )
        if self.deadline.tzinfo is None or self.deadline <= datetime.now(UTC):
            raise DriverRejected("operation authorization deadline expired or lacks timezone")


@dataclass(frozen=True)
class BindingIdentity:
    node_id: str
    node_boot_id: str
    runtime_id: str
    attempt_id: str
    agent_slot_id: str
    revision: int

    def validate(self):
        if (
            type(self.revision) is not int
            or self.revision < 1
            or any(
                not isinstance(v, str) or not v for k, v in asdict(self).items() if k != "revision"
            )
        ):
            raise DriverRejected("complete immutable Node boot/Runtime/Attempt binding required")


@dataclass(frozen=True)
class LaunchProfile:
    executable: str
    executable_sha256: str
    version: str
    schema_path: str
    schema_sha256: str
    cwd: str
    codex_home: str
    config_sha256: str
    permission_profile: str
    environment: dict[str, str]
    model: str | None = None

    def validate(self):
        if self.version not in {"0.152.1", "0.153.2"}:
            raise DriverRejected("version has no reviewed reference profile")
        for path in (self.executable, self.cwd, self.codex_home, self.schema_path):
            if not Path(path).is_absolute():
                raise DriverRejected("profile paths must be absolute")
        if file_digest(self.executable) != self.executable_sha256:
            raise DriverRejected("executable differs from pinned profile")
        if file_digest(self.schema_path) != self.schema_sha256:
            raise DriverRejected("schema differs from pinned profile")
        config_path = Path(self.codex_home) / "config.toml"
        if file_digest(config_path) != self.config_sha256:
            raise DriverRejected("configuration differs from pinned profile")
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        if (
            config.get("default_permissions") != self.permission_profile
            or self.permission_profile.startswith(":")
            or config.get("approval_policy") != "never"
        ):
            raise DriverRejected(
                "named permission profile and noninteractive approval policy required"
            )
        if "CODEX_HOME" in self.environment and self.environment["CODEX_HOME"] != self.codex_home:
            raise DriverRejected("environment CODEX_HOME conflicts with profile")
        return self

    def binding(self):
        # Do not serialize environment values or configuration contents.
        return {k: v for k, v in asdict(self).items() if k != "environment"}


@dataclass
class OwnedProcess:
    process: subprocess.Popen
    birth_ref: str
    containment_id: str | None = None


class NodeSupervisor(Protocol):
    def launch(self, argv, *, cwd, env, label) -> OwnedProcess: ...
    def inspect(self, owned: OwnedProcess) -> dict: ...
    def terminate_tree(self, owned: OwnedProcess) -> dict: ...


class DriverJournal:
    """Local durable evidence adapter; Domain dedup remains authoritative.

    Parent directory must be Node-owned private storage. A kernel lock prevents
    two local Driver instances from mutating one binding. No lock stealing or
    timeout-based takeover is performed. Node still owns cross-host fencing.
    """

    def __init__(self, path):
        self.path = str(path)
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS driver_operations(
                  operation_id TEXT PRIMARY KEY, binding_id TEXT NOT NULL,
                  command_id TEXT NOT NULL UNIQUE, message_id TEXT NOT NULL UNIQUE,
                  action TEXT NOT NULL, input_hash TEXT NOT NULL, input_json TEXT NOT NULL,
                  state TEXT NOT NULL, result_json TEXT);
                CREATE TABLE IF NOT EXISTS driver_events(
                  sequence INTEGER PRIMARY KEY AUTOINCREMENT, operation_id TEXT NOT NULL,
                  kind TEXT NOT NULL, body TEXT NOT NULL, observed_at TEXT NOT NULL);
            """)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.execute("PRAGMA synchronous=FULL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def claim(self, binding_id):
        path = self.path + "." + digest(binding_id) + ".lock"
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if os.name == "nt":
                import msvcrt

                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"0")
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            os.close(fd)
            raise DriverRejected("binding already owned by a local Driver") from None

    def read(self, operation_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT binding_id,action,input_hash,input_json,state,result_json "
                "FROM driver_operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "binding_id": row[0],
            "action": row[1],
            "input_hash": row[2],
            "input": json.loads(row[3]),
            "state": row[4],
            "result": json.loads(row[5]) if row[5] else None,
        }

    def begin(self, operation, binding, action, payload):
        body = {
            "command_id": operation.command_id,
            "message_id": operation.message_id,
            "grant_ref": operation.grant_ref,
            "deadline": operation.deadline.isoformat(),
            "binding_id": binding,
            "action": action,
            "payload": payload,
        }
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT input_hash FROM driver_operations WHERE operation_id=?",
                (operation.operation_id,),
            ).fetchone()
            if row is not None:
                if row[0] != digest(body):
                    raise DriverRejected("operation identity reused with different input")
            else:
                pending = conn.execute(
                    "SELECT operation_id FROM driver_operations WHERE binding_id=? "
                    "AND state IN ('intent','uncertain') LIMIT 1",
                    (binding,),
                ).fetchone()
                if pending and action not in {"terminate", "cancel"}:
                    raise OutcomeUncertain("binding has unresolved operation: " + pending[0])
                conn.execute(
                    "INSERT INTO driver_operations VALUES(?,?,?,?,?,?,?,'intent',NULL)",
                    (
                        operation.operation_id,
                        binding,
                        operation.command_id,
                        operation.message_id,
                        action,
                        digest(body),
                        canonical(body),
                    ),
                )
        return {**self.read(operation.operation_id), "created": row is None}

    def event(self, operation_id, kind, body):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO driver_events(operation_id,kind,body,observed_at) VALUES(?,?,?,?)",
                (operation_id, kind, canonical(body), datetime.now(UTC).isoformat()),
            )

    def finish(self, operation_id, state, result):
        with self._connect() as conn:
            conn.execute(
                "UPDATE driver_operations SET state=?,result_json=? WHERE operation_id=?",
                (state, canonical(result), operation_id),
            )


class CodexAppServerDriver:
    harness = "codex"

    def __init__(
        self,
        binding_id,
        profile,
        journal,
        *,
        identity,
        check_current,
        supervisor=None,
        rpc_timeout=30,
    ):
        if not isinstance(binding_id, str) or not binding_id:
            raise DriverRejected("immutable Node binding id/revision identity required")
        self.binding_id, self.profile, self.journal = binding_id, profile, journal
        identity.validate()
        if not callable(check_current):
            raise DriverRejected("Node current-authorization callback is required")
        self.identity, self.check_current = identity, check_current
        self.supervisor, self.rpc_timeout = supervisor, rpc_timeout
        self._claim_fd = journal.claim(binding_id)
        self._lock = threading.RLock()
        self.client = None
        self.owned = None
        self.thread_id = None
        self.session_id = None
        self.ownership = "unbound"
        self._initialized = False

    def _rpc(self, operation, method, params):
        operation.validate()
        self.check_current(operation, self.identity)
        request_id = uuid.uuid4().hex
        self.journal.event(
            operation.operation_id,
            "rpc_intent",
            {
                "request_id": request_id,
                "method": method,
                "params": params,
                "binding": asdict(self.identity),
                "command_id": operation.command_id,
                "message_id": operation.message_id,
                "grant_ref": operation.grant_ref,
            },
        )
        self.check_current(operation, self.identity)
        operation.validate()
        remaining = (operation.deadline - datetime.now(UTC)).total_seconds()
        result = self.client.request(
            method, params, timeout=min(self.rpc_timeout, remaining), request_id=request_id
        )
        self.journal.event(
            operation.operation_id, "rpc_response", {"request_id": request_id, "result": result}
        )
        self._drain(operation.operation_id)
        return result

    def _drain(self, operation_id):
        for event in self.client.drain_events():
            self.journal.event(operation_id, "native_event", event)

    def _run(self, operation, action, payload, function):
        with self._lock:
            operation.validate()
            self.check_current(operation, self.identity)
            operation.validate()
            record = self.journal.begin(
                operation, self.binding_id, action, {**payload, "binding": asdict(self.identity)}
            )
            if record["state"] == "acknowledged":
                return record["result"]
            if record["state"] == "rejected":
                raise DriverRejected(
                    "this operation was previously rejected before mutation dispatch"
                )
            # A previous attempt may have dispatched before its process crashed.
            if not record["created"]:
                raise OutcomeUncertain("inspect/reconcile the original operation before any retry")
            with self.journal._connect() as conn:
                dispatched = conn.execute(
                    "SELECT 1 FROM driver_events WHERE operation_id=? LIMIT 1",
                    (operation.operation_id,),
                ).fetchone()
            if dispatched:
                raise OutcomeUncertain(
                    "durable intent already has execution evidence; no blind retry"
                )
            try:
                result = function()
                result.update(
                    operation_id=operation.operation_id,
                    command_id=operation.command_id,
                    message_id=operation.message_id,
                )
                self.journal.finish(operation.operation_id, "acknowledged", result)
                return result
            except BaseException as exc:
                state = "uncertain"
                if isinstance(exc, DriverRejected):
                    with self.journal._connect() as conn:
                        events = conn.execute(
                            "SELECT kind,body FROM driver_events WHERE operation_id=?",
                            (operation.operation_id,),
                        ).fetchall()
                    if not any(
                        kind == "process_intent"
                        or kind == "rpc_intent"
                        and json.loads(body).get("method")
                        in {"thread/start", "thread/resume", "turn/start", "turn/interrupt"}
                        for kind, body in events
                    ):
                        state = "rejected"
                self.journal.finish(
                    operation.operation_id, state, {"error_type": type(exc).__name__}
                )
                raise

    def _initialize(self, operation):
        if self._initialized:
            return
        result = self._rpc(
            operation,
            "initialize",
            {
                "clientInfo": {"name": "acs_runtime", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        if (
            not isinstance(result, dict)
            or not re.search(
                r"(?<![\d.])" + re.escape(self.profile.version) + r"(?![\d.])",
                result.get("userAgent", ""),
            )
            or Path(result.get("codexHome", "")) != Path(self.profile.codex_home)
        ):
            raise DriverRejected("initialize response does not bind expected version/CODEX_HOME")
        self.journal.event(operation.operation_id, "notification_intent", {"method": "initialized"})
        self.client.notify("initialized", {})
        self._initialized = True

    def _native_thread(self, response):
        thread = response.get("thread") if isinstance(response, dict) else None
        if not isinstance(thread, dict) or any(
            not isinstance(thread.get(k), str) or not thread[k] for k in ("id", "sessionId")
        ):
            raise DriverRejected("native response lacks complete thread/session identity")
        if self.thread_id is not None and thread["id"] != self.thread_id:
            raise DriverRejected("response belongs to another native thread")
        if self.session_id is not None and thread["sessionId"] != self.session_id:
            raise DriverRejected("native session-tree identity changed")
        return thread

    def _settings(self, operation, response):
        if (
            response.get("activePermissionProfile", {}).get("id") != self.profile.permission_profile
            or response.get("approvalPolicy") != "never"
            or Path(response.get("cwd", "")) != Path(self.profile.cwd)
        ):
            raise DriverRejected("native active settings differ from immutable launch profile")
        states = {}
        cursor = None
        for _ in range(20):
            params = {"threadId": self.thread_id, "limit": 100}
            if cursor is not None:
                params["cursor"] = cursor
            page = self._rpc(operation, "experimentalFeature/list", params)
            states.update({row["name"]: row["enabled"] for row in page["data"]})
            cursor = page.get("nextCursor")
            if not cursor:
                break
        else:
            raise DriverRejected("feature pagination bound exceeded")
        if any(states.get(name) is not False for name in ("multi_agent", "multi_agent_v2")):
            raise DriverRejected("native delegation disablement was not positively observed")

    def spawn(self, operation):
        def perform():
            if self.client is not None:
                raise DriverRejected("Driver already has an endpoint")
            self.profile.validate()
            self.check_current(operation, self.identity)
            argv = [
                self.profile.executable,
                "--disable",
                "multi_agent",
                "--disable",
                "multi_agent_v2",
                "app-server",
            ]
            env = dict(self.profile.environment, CODEX_HOME=self.profile.codex_home)
            self.journal.event(
                operation.operation_id,
                "process_intent",
                {"argv": argv, "profile": self.profile.binding()},
            )
            self.check_current(operation, self.identity)
            operation.validate()
            if self.supervisor is not None:
                self.owned = self.supervisor.launch(
                    argv, cwd=self.profile.cwd, env=env, label=operation.operation_id
                )
            else:
                process = subprocess.Popen(
                    argv,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=self.profile.cwd,
                    env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                self.owned = OwnedProcess(process, "local-handle:" + uuid.uuid4().hex)
            self.ownership = "exclusive_owned"
            self.journal.event(
                operation.operation_id,
                "process_started",
                {
                    "pid": self.owned.process.pid,
                    "birth_ref": self.owned.birth_ref,
                    "containment_id": self.owned.containment_id,
                },
            )
            self.client = JsonRpcClient(
                self.owned.process.stdout,
                self.owned.process.stdin,
                stderr=self.owned.process.stderr,
            )
            self._initialize(operation)
            params = {"cwd": self.profile.cwd, "approvalPolicy": "never", "ephemeral": False}
            if self.profile.model:
                params["model"] = self.profile.model
            response = self._rpc(operation, "thread/start", params)
            thread = self._native_thread(response)
            self.thread_id, self.session_id = thread["id"], thread["sessionId"]
            self._settings(operation, response)
            return self._binding_receipt("runtime_acknowledged")

        return self._run(operation, "spawn", {"profile": self.profile.binding()}, perform)

    def attach(self, operation, client, thread_id):
        def perform():
            if self.client is not None:
                raise DriverRejected("endpoint already bound")
            self.client, self.thread_id, self.ownership = client, thread_id, "shared_attached"
            self._initialize(operation)
            response = self._rpc(
                operation, "thread/read", {"threadId": thread_id, "includeTurns": False}
            )
            thread = self._native_thread(response)
            self.session_id = thread["sessionId"]
            return self._binding_receipt("context_observed")

        return self._run(operation, "attach", {"thread_id": thread_id}, perform)

    def _owned_mutation(self):
        if self.ownership != "exclusive_owned" or self.client is None or self.thread_id is None:
            raise DriverRejected("mutation requires this Driver's exclusive owned native binding")

    def _binding_receipt(self, layer, **values):
        return {
            "binding_id": self.binding_id,
            "thread_id": self.thread_id,
            "session_id": self.session_id,
            "binding": asdict(self.identity),
            "ownership": self.ownership,
            "receipt_layer": layer,
            "observed_at": datetime.now(UTC).isoformat(),
            **values,
        }

    def _inspect(self, operation):
        response = self._rpc(
            operation, "thread/read", {"threadId": self.thread_id, "includeTurns": False}
        )
        thread = self._native_thread(response)
        turns, cursor = [], None
        for _ in range(20):
            params = {
                "threadId": self.thread_id,
                "itemsView": "full",
                "limit": 100,
                "sortDirection": "desc",
            }
            if cursor:
                params["cursor"] = cursor
            page = self._rpc(operation, "thread/turns/list", params)
            turns.extend(page["data"])
            cursor = page.get("nextCursor")
            if not cursor:
                break
        else:
            raise DriverRejected("native history exceeds reconciliation bound")
        return {
            "thread": thread,
            "turns": turns,
            "transport": self.client.diagnostics(),
            "root_exit_code": self.owned.process.poll() if self.owned else None,
            "descendant_state": "unknown",
        }

    def inspect(self, operation):
        # Read-only observation is permitted while a mutation is uncertain.
        with self._lock:
            operation.validate()
            if self.client is None or self.thread_id is None:
                raise OutcomeUncertain(
                    "no positively bound native thread; Node must inspect owned process"
                )
            return self._inspect(operation)

    @staticmethod
    def _matching_turns(view, message_id, text):
        matched = []
        for turn in view["turns"]:
            for item in turn.get("items", []):
                if (
                    item.get("type") == "userMessage"
                    and item.get("clientId") == message_id
                    and item.get("content") == [{"type": "text", "text": text, "text_elements": []}]
                ):
                    matched.append(turn)
        return matched

    def invoke(self, operation, text):
        if not isinstance(text, str) or not text or len(text.encode()) > 1024 * 1024:
            raise DriverRejected("only bounded authorized text input is supported")

        def perform():
            self._owned_mutation()
            view = self._inspect(operation)
            if view["thread"].get("status", {}).get("type") != "idle" or any(
                t.get("status") == "inProgress" for t in view["turns"]
            ):
                raise DriverRejected("active/unknown native turn; implicit steering is prohibited")
            response = self._rpc(
                operation,
                "turn/start",
                {
                    "threadId": self.thread_id,
                    "clientUserMessageId": operation.message_id,
                    "input": [{"type": "text", "text": text, "text_elements": []}],
                },
            )
            turn = response.get("turn", {})
            if not isinstance(turn.get("id"), str) or not turn["id"]:
                raise OutcomeUncertain("native invoke ACK omitted turn identity")
            return self._binding_receipt(
                "runtime_acknowledged", turn_id=turn["id"], native_status=turn.get("status")
            )

        return self._run(operation, "invoke", {"thread_id": self.thread_id, "text": text}, perform)

    def resume(self, operation):
        def perform():
            self._owned_mutation()
            response = self._rpc(
                operation, "thread/resume", {"threadId": self.thread_id, "excludeTurns": True}
            )
            self._native_thread(response)
            self._settings(operation, response)
            return self._binding_receipt("context_resumed")

        return self._run(operation, "resume", {"thread_id": self.thread_id}, perform)

    def cancel(self, operation, turn_id):
        if not isinstance(turn_id, str) or not turn_id:
            raise DriverRejected("exact nonempty native turn id is required")

        def perform():
            self._owned_mutation()
            view = self._inspect(operation)
            matching = [turn for turn in view["turns"] if turn.get("id") == turn_id]
            if len(matching) != 1:
                raise DriverRejected("target turn was not independently observed")
            if matching[0]["status"] == "inProgress":
                self._rpc(
                    operation, "turn/interrupt", {"threadId": self.thread_id, "turnId": turn_id}
                )
            for _ in range(30):
                latest = self._inspect(operation)
                terminal = [
                    t
                    for t in latest["turns"]
                    if t.get("id") == turn_id
                    and t.get("status") in {"completed", "interrupted", "failed"}
                ]
                if terminal:
                    return self._binding_receipt(
                        "response_received", turn_id=turn_id, native_status=terminal[0]["status"]
                    )
                time.sleep(0.1)
            raise OutcomeUncertain("interrupt ACK lacks observed terminal turn")

        return self._run(
            operation, "cancel", {"thread_id": self.thread_id, "turn_id": turn_id}, perform
        )

    def reconcile(self, operation, uncertain_operation_id):
        with self._lock:
            operation.validate()
            self.check_current(operation, self.identity)
            record = self.journal.read(uncertain_operation_id)
            if (
                record is None
                or record["binding_id"] != self.binding_id
                or record["action"] != "invoke"
                or record["state"] not in {"intent", "uncertain", "acknowledged"}
            ):
                raise OutcomeUncertain(
                    "only uniquely correlated invoke recovery is supported; preserve other uncertainty"
                )
            view = self.inspect(operation)
            body = record["input"]
            if body["payload"].get("binding") != asdict(self.identity):
                raise DriverRejected("late receipt belongs to a retired binding identity")
            matches = self._matching_turns(view, body["message_id"], body["payload"]["text"])
            if len(matches) != 1:
                raise OutcomeUncertain("no unique native message/content match; never resubmit")
            turn = matches[0]
            known = record["result"] or {}
            if known.get("turn_id") not in (None, turn["id"]):
                raise DriverRejected("reconciliation cannot replace the acknowledged native turn")
            if record["state"] == "acknowledged":
                return record["result"]
            result = self._binding_receipt(
                "runtime_acknowledged",
                turn_id=turn["id"],
                native_status=turn["status"],
                reconciliation="native_message_readback",
                operation_id=uncertain_operation_id,
                command_id=body["command_id"],
                message_id=body["message_id"],
            )
            self.journal.event(uncertain_operation_id, "reconciled", result)
            self.journal.finish(uncertain_operation_id, "acknowledged", result)
            return result

    def terminate(self, operation):
        def perform():
            if self.ownership != "exclusive_owned" or self.owned is None:
                raise DriverRejected("termination requires an exclusively owned process")
            if self.supervisor is None or self.owned is None or not self.owned.containment_id:
                raise DriverRejected(
                    "process-tree containment is unavailable; termination unverified"
                )
            self.check_current(operation, self.identity)
            operation.validate()
            proof = self.supervisor.terminate_tree(self.owned)
            if (
                proof.get("verified") is not True
                or proof.get("birth_ref") != self.owned.birth_ref
                or proof.get("containment_id") != self.owned.containment_id
                or proof.get("root_exited") is not True
                or proof.get("remaining_pids") != []
                or self.owned.process.poll() is None
            ):
                raise OutcomeUncertain("supervisor did not prove complete owned-tree termination")
            if self.client is not None:
                self.client.close()
            return self._binding_receipt("process_tree_terminated", supervisor_proof=proof)

        return self._run(operation, "terminate", {"thread_id": self.thread_id}, perform)

    def collect_result(self, operation, invocation_operation_id):
        """Read correlated terminal output; never starts/resumes reasoning."""
        with self._lock:
            operation.validate()
            self.check_current(operation, self.identity)
            record = self.journal.read(invocation_operation_id)
            if (
                record is None
                or record["binding_id"] != self.binding_id
                or record["action"] != "invoke"
                or record["input"]["payload"].get("binding") != asdict(self.identity)
            ):
                raise DriverRejected("invocation is not bound to this Node boot/Runtime/Attempt")
            view = self.inspect(operation)
            body = record["input"]
            matches = self._matching_turns(view, body["message_id"], body["payload"]["text"])
            if len(matches) != 1:
                raise OutcomeUncertain("terminal output lacks unique native message correlation")
            turn = matches[0]
            if record["result"] and record["result"].get("turn_id") not in (None, turn["id"]):
                raise DriverRejected("terminal result belongs to a different turn")
            terminal = turn.get("status") in {"completed", "interrupted", "failed"}
            messages = [
                item for item in turn.get("items", []) if item.get("type") == "agentMessage"
            ]
            result = self._binding_receipt(
                "response_received" if terminal else "runtime_acknowledged",
                operation_id=invocation_operation_id,
                command_id=body["command_id"],
                message_id=body["message_id"],
                turn_id=turn["id"],
                native_status=turn.get("status"),
                native_error=turn.get("error"),
                assistant_messages=messages,
            )
            self.journal.event(
                invocation_operation_id,
                "terminal_observation" if terminal else "turn_observation",
                result,
            )
            return result

    def detach_transport(self):
        """Release local transport/lock only; makes no process termination claim."""
        with self._lock:
            if self.client:
                self.client.close()
            if self._claim_fd is not None:
                os.close(self._claim_fd)
                self._claim_fd = None
