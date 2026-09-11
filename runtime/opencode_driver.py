"""OpenCode 1.18.27/1.18.30 native HTTP Driver.

Shares the established local DriverJournal and authorization/binding types;
Domain remains authoritative. HTTP 204 is scheduling, never native acceptance.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import socket
import stat
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from runtime.codex_driver import (
    AuthorizedOperation,
    BindingIdentity,
    DriverJournal,
    DriverRejected,
    OutcomeUncertain,
    digest,
    file_digest,
)

if __package__:
    from .opencode_http import HttpFailure, LoopbackHttp, listener_owner_pids
else:
    from opencode_http import HttpFailure, LoopbackHttp, listener_owner_pids

SESSION_RULES = [
    {"permission": "*", "pattern": "*", "action": "deny"},
    {"permission": "task", "pattern": "*", "action": "deny"},
]
NATIVE_GITIGNORE = b"node_modules\npackage.json\npackage-lock.json\nbun.lock\n.gitignore"


def generated_data_matches(path):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return False
        return os.read(descriptor, len(NATIVE_GITIGNORE) + 1) == NATIVE_GITIGNORE
    finally:
        os.close(descriptor)


def native_id(value, prefix):
    if not isinstance(value, str) or not re.fullmatch(prefix + r"_[A-Za-z0-9_-]{1,250}", value):
        raise DriverRejected("native identifier is missing or malformed")
    return value


@dataclass(frozen=True)
class OpenCodeLaunchProfile:
    executable: str
    executable_sha256: str
    version: str
    schema_path: str
    schema_sha256: str
    cwd: str
    home: str
    config_root: str
    data_root: str
    state_root: str
    cache_root: str
    temp_root: str
    config_sha256: str
    agent: str
    provider_id: str
    model_id: str
    environment: dict[str, str]

    @property
    def config_path(self):
        return Path(self.config_root) / "opencode" / "opencode.json"

    def binding(self):
        return {key: value for key, value in asdict(self).items() if key != "environment"}

    def validate(self, *, executable=True, fresh=False):
        if self.version not in {"1.18.27", "1.18.30"}:
            raise DriverRejected("OpenCode version requires a separate reference profile")
        roots = [self.home, self.config_root, self.data_root, self.state_root,
                 self.cache_root, self.temp_root, self.cwd]
        if any(not Path(path).is_absolute() or not Path(path).is_dir() for path in roots):
            raise DriverRejected("private runtime roots and authorized cwd must be absolute directories")
        if len({str(Path(path).resolve()) for path in roots}) != len(roots):
            raise DriverRejected("runtime roots must be independently scoped")
        if fresh and any(any(Path(path).iterdir()) for path in
                         (self.home, self.data_root, self.state_root, self.cache_root, self.temp_root)):
            raise DriverRejected("spawn requires fresh private runtime roots")
        if not Path(self.executable).is_absolute() or not Path(self.schema_path).is_absolute():
            raise DriverRejected("executable/schema paths must be absolute")
        if executable and file_digest(self.executable) != self.executable_sha256:
            raise DriverRejected("OpenCode executable differs from the pinned profile")
        if file_digest(self.schema_path) != self.schema_sha256 or file_digest(self.config_path) != self.config_sha256:
            raise DriverRejected("OpenCode schema/configuration changed")
        if not all(isinstance(value, str) and value for value in (self.agent, self.provider_id, self.model_id)):
            raise DriverRejected("trusted agent/provider/model selection is required")
        for path in Path(self.config_root).rglob("*"):
            if path.is_symlink():
                raise DriverRejected("configuration roots cannot contain symlinks")
            if path.is_dir():
                continue
            approved_data = (path == self.config_path or path == self.config_path.parent / ".gitignore"
                             and generated_data_matches(path))
            if not approved_data:
                raise DriverRejected("configuration roots may contain only approved configuration data")
        for path in (Path(self.home) / ".opencode", Path(self.cwd) / ".opencode"):
            if path.exists() or path.is_symlink():
                raise DriverRejected("project/custom-tool configuration must not be materialized")
        config = json.loads(self.config_path.read_text())
        selected = config.get("agent", {}).get(self.agent, {})
        if (config.get("permission") != {"*": "deny", "task": "deny"}
                or selected.get("permission") != {"*": "deny", "task": "deny"}
                or config.get("default_agent") != self.agent
                or config.get("model") != self.provider_id + "/" + self.model_id
                or selected.get("model") != self.provider_id + "/" + self.model_id
                or config.get("plugin", []) != [] or config.get("mcp", {}) != {}):
            raise DriverRejected("deny-all global/agent permissions and pinned selection are required")
        for key, value in self.environment.items():
            if (not isinstance(key, str) or not isinstance(value, str) or "\0" in key + value
                    or "proxy" in key.lower() or key.startswith("OPENCODE_")
                    or key in {"NODE_OPTIONS", "BUN_OPTIONS", "LD_PRELOAD", "LD_LIBRARY_PATH"}):
                raise DriverRejected("environment contains an unapproved runtime/proxy override")
        return self

    def process_environment(self, password):
        values = dict(self.environment)
        values.update({
            "HOME": self.home, "USERPROFILE": self.home, "APPDATA": self.config_root,
            "LOCALAPPDATA": self.data_root, "XDG_CONFIG_HOME": self.config_root,
            "XDG_DATA_HOME": self.data_root, "XDG_STATE_HOME": self.state_root,
            "XDG_CACHE_HOME": self.cache_root, "TEMP": self.temp_root, "TMP": self.temp_root,
            "TMPDIR": self.temp_root, "OPENCODE_CONFIG_DIR": str(self.config_path.parent),
            "OPENCODE_DISABLE_PROJECT_CONFIG": "1", "OPENCODE_DISABLE_AUTOUPDATE": "1",
            "OPENCODE_DISABLE_MODELS_FETCH": "1", "OPENCODE_SERVER_USERNAME": "opencode",
            "OPENCODE_SERVER_PASSWORD": password,
        })
        return values


class OpenCodeNativeDriver:
    harness = "opencode"

    def __init__(self, binding_id, profile, journal: DriverJournal, *, identity: BindingIdentity, check_current, supervisor=None,
                 http_timeout=10, readback_attempts=10):
        if not isinstance(binding_id, str) or not binding_id or not callable(check_current):
            raise DriverRejected("immutable binding and current Node authorization are required")
        identity.validate()
        self.binding_id, self.profile, self.journal = binding_id, profile, journal
        self.identity, self._identity = identity, asdict(identity)
        self.check_current, self.supervisor = check_current, supervisor
        self.http_timeout, self.readback_attempts = http_timeout, readback_attempts
        self._lock = threading.RLock()
        self._claim_fd = journal.claim(binding_id)
        self.client = self.owned = self.session_id = None
        self.ownership = "unbound"
        self._active_message = None
        self._active_operation_id = None
        self._event_stop = threading.Event()
        self._event_thread = None
        self._event_state = "not_started"
        self._native_counter = 0
        self._last_ms = 0
        self._diag_threads = []
        self._diag_bytes = 0
        self._diag_hash = hashlib.sha256()
        self._diag_lock = threading.Lock()

    def _auth(self, operation: AuthorizedOperation):
        operation.validate()
        if asdict(self.identity) != self._identity or self._claim_fd is None:
            raise DriverRejected("Driver binding is retired or detached")
        self.check_current(operation, self.identity)
        operation.validate()
        if asdict(self.identity) != self._identity:
            raise DriverRejected("binding changed during authorization")

    def _receipt(self, layer, **values):
        return {"binding_id": self.binding_id, "binding": dict(self._identity),
                "native_session_id": self.session_id, "ownership": self.ownership,
                "receipt_layer": layer, "observed_at": datetime.now(UTC).isoformat(), **values}

    def _run(self, operation, action, payload, function):
        with self._lock:
            self._auth(operation)
            record = self.journal.begin(operation, self.binding_id, action,
                                        {**payload, "binding": self._identity})
            self._auth(operation)
            if record["state"] == "acknowledged":
                return record["result"]
            if not record["created"]:
                raise OutcomeUncertain("original operation must be reconciled; no blind redispatch")
            previous_active = self._active_message, self._active_operation_id
            try:
                result = function()
                result.update(operation_id=operation.operation_id, command_id=operation.command_id,
                              message_id=operation.message_id)
                state = "uncertain" if result["receipt_layer"] == "runtime_dispatched" else "acknowledged"
                self.journal.finish(operation.operation_id, state, result)
                return result
            except BaseException as error:
                state = "uncertain"
                if isinstance(error, DriverRejected):
                    with self.journal._connect() as connection:
                        events = connection.execute("SELECT kind,body FROM driver_events WHERE operation_id=?",
                                                    (operation.operation_id,)).fetchall()
                    if not any(kind == "process_dispatch" or kind == "http_dispatch" and json.loads(body)["method"] == "POST"
                               for kind, body in events):
                        state = "rejected"
                if state == "rejected":
                    self._active_message, self._active_operation_id = previous_active
                self.journal.finish(operation.operation_id, state, {"error_type": type(error).__name__})
                raise

    def _http(self, operation, method, path, payload=None, *, max_bytes=4 * 1024 * 1024):
        self._auth(operation)
        if self.client is None:
            raise OutcomeUncertain("native endpoint is not bound")
        self.journal.event(operation.operation_id, "http_intent",
                           {"method": method, "path": path, "body_digest": digest(payload),
                            "binding": self._identity, "endpoint": self.client.endpoint})
        self._auth(operation)
        remaining = (operation.deadline - datetime.now(UTC)).total_seconds()
        dispatch_evidence = {
            "method": method,
            "path": path,
            "body_digest": digest(payload),
            "binding": self._identity,
            "endpoint": self.client.endpoint,
        }
        status, value = self.client.request(
            method,
            path,
            payload,
            timeout=min(self.http_timeout, remaining),
            max_bytes=max_bytes,
            before_send=lambda: self._auth(operation),
            on_dispatch=lambda: self.journal.event(
                operation.operation_id,
                "http_dispatch",
                dispatch_evidence,
            ),
        )
        self.journal.event(operation.operation_id, "http_response",
                           {"method": method, "path": path, "status": status, "body_digest": digest(value)})
        return status, value

    def _observe_native_profile(self, operation):
        _, health = self._http(operation, "GET", "/global/health")
        if health != {"healthy": True, "version": self.profile.version}:
            raise DriverRejected("health/version does not match the pinned native profile")
        _, schema = self._http(operation, "GET", "/doc", max_bytes=16 * 1024 * 1024)
        if digest(schema) != digest(json.loads(Path(self.profile.schema_path).read_text())):
            raise DriverRejected("served OpenAPI differs from the reviewed schema")
        _, config = self._http(operation, "GET", "/config")
        agent = config.get("agent", {}).get(self.profile.agent, {})
        if (config.get("permission") != {"*": "deny", "task": "deny"}
                or agent.get("permission") != {"*": "deny", "task": "deny"}
                or config.get("default_agent") != self.profile.agent
                or config.get("model") != self.profile.provider_id + "/" + self.profile.model_id):
            raise DriverRejected("effective native configuration is not the deny-all profile")
        _, agents = self._http(operation, "GET", "/agent")
        matches = [value for value in agents if value.get("name") == self.profile.agent]
        if len(matches) != 1:
            raise DriverRejected("selected native agent is not unique")
        rules = matches[0].get("permission", [])
        _, tool_ids = self._http(operation, "GET", "/experimental/tool/ids")
        if (
            not isinstance(tool_ids, list)
            or not tool_ids
            or len(tool_ids) > 4096
            or len(set(tool_ids)) != len(tool_ids)
            or any(
                not isinstance(tool, str)
                or not tool
                or len(tool) > 256
                or any(ord(char) < 32 or ord(char) == 127 for char in tool)
                for tool in tool_ids
            )
        ):
            raise DriverRejected("native tool inventory is malformed or unbounded")
        if not isinstance(rules, list) or any(
            not isinstance(rule, dict)
            or not isinstance(rule.get("permission"), str)
            or not isinstance(rule.get("pattern"), str)
            or rule.get("action") not in {"allow", "ask", "deny"}
            for rule in rules
        ):
            raise DriverRejected("native permission rules are malformed")
        global_denies = [
            index
            for index, rule in enumerate(rules)
            if rule == {"permission": "*", "pattern": "*", "action": "deny"}
        ]
        if not global_denies:
            raise DriverRejected("native agent lacks a final deny-all boundary")
        protected_permissions = set(tool_ids) | {"task"}
        for rule in rules[global_denies[-1] + 1:]:
            if (
                rule["action"] != "deny"
                and rule["permission"] in protected_permissions | {"*"}
            ):
                raise DriverRejected(
                    "native agent has an effective allow after the deny-all boundary"
                )

    def _metadata(self, operation_id):
        return {"acs_binding_id": self.binding_id, "acs_binding": self._identity,
                "acs_operation_id": operation_id}

    def _session(self, value, *, expected_operation=None):
        if not isinstance(value, dict):
            raise DriverRejected("native session response is malformed")
        session_id = native_id(value.get("id"), "ses")
        if self.session_id is not None and session_id != self.session_id:
            raise DriverRejected("native session identity changed")
        metadata = value.get("metadata", {})
        if (metadata.get("acs_binding_id") != self.binding_id
                or metadata.get("acs_binding") != self._identity
                or not isinstance(metadata.get("acs_operation_id"), str)
                or expected_operation is not None and metadata.get("acs_operation_id") != expected_operation
                or Path(value.get("directory", "")).resolve() != Path(self.profile.cwd).resolve()
                or value.get("permission") != SESSION_RULES
                or value.get("agent") != self.profile.agent
                or value.get("model", {}).get("id") != self.profile.model_id
                or value.get("model", {}).get("providerID") != self.profile.provider_id):
            raise DriverRejected("native session is not bound to the original Node/Attempt/profile")
        return value

    def _drain_output(self, stream):
        try:
            while chunk := stream.read(4096):
                with self._diag_lock:
                    self._diag_bytes += len(chunk)
                    self._diag_hash.update(chunk)
        except (OSError, ValueError):
            pass

    def _start_events(self, operation):
        self._stop_events()
        self._event_stop = threading.Event()
        stop = self._event_stop
        session_id, identity = self.session_id, dict(self._identity)
        self._auth(operation)
        self.journal.event(operation.operation_id, "http_intent",
                           {"method": "GET", "path": "/event", "binding": identity,
                            "native_session_id": session_id, "stream": "SSE"})
        def observe(value):
            self._auth(operation)
            props = value.get("properties", {})
            observed_session = props.get("sessionID") or props.get("info", {}).get("sessionID") or props.get("part", {}).get("sessionID")
            if observed_session == session_id:
                self.journal.event(operation.operation_id, "native_event",
                                   {"type": value.get("type"), "native_session_id": session_id,
                                    "binding": identity, "event_digest": digest(value)})
        def read():
            self._event_state = "connecting"
            def opened():
                self._auth(operation)
                self._event_state = "subscribed"
                self.journal.event(operation.operation_id, "event_subscription_opened",
                                   {"native_session_id": session_id, "binding": identity})
            try:
                self.client.events(stop, observe, before_send=lambda: self._auth(operation), opened=opened)
                self._event_state = "closed"
            except Exception as error:  # noqa: BLE001 - background observation failure is journaled without response bodies.
                self._event_state = "unavailable"
                self.journal.event(operation.operation_id, "event_subscription_unavailable",
                                   {"error_type": type(error).__name__, "binding": identity,
                                    "native_session_id": session_id})
        self._event_thread = threading.Thread(target=read, daemon=True)
        self._event_thread.start()

    def _stop_events(self):
        self._event_stop.set()
        if self.client is not None:
            self.client.stop_events()
        if self._event_thread is not None:
            self._event_thread.join(timeout=1.5)

    def spawn(self, operation):
        def perform():
            if self.client is not None or self.owned is not None:
                raise DriverRejected("Driver already owns or attaches to an endpoint")
            self.profile.validate(fresh=True)
            if self.supervisor is None:
                raise DriverRejected("native spawn requires an actual Node containment supervisor")
            password = secrets.token_urlsafe(36)
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            argv = [self.profile.executable, "--pure", "serve", "--hostname", "127.0.0.1", "--port", str(port)]
            self.journal.event(operation.operation_id, "process_intent",
                               {"argv": argv, "profile": self.profile.binding(), "binding": self._identity})
            self._auth(operation)
            self.journal.event(
                operation.operation_id,
                "process_dispatch",
                {"argv": argv, "profile": self.profile.binding(), "binding": self._identity},
            )
            self.owned = self.supervisor.launch(argv, cwd=self.profile.cwd,
                                                env=self.profile.process_environment(password), label=operation.operation_id)
            self.ownership = "exclusive_owned"
            self.journal.event(operation.operation_id, "process_started",
                               {"pid": self.owned.process.pid, "birth_ref": self.owned.birth_ref,
                                "containment_id": self.owned.containment_id})
            for stream in (self.owned.process.stdout, self.owned.process.stderr):
                thread = threading.Thread(target=self._drain_output, args=(stream,), daemon=True)
                thread.start()
                self._diag_threads.append(thread)
            def owner():
                proof = self.supervisor.inspect(self.owned)
                owners = listener_owner_pids(port)
                return (proof.get("verified") is True and proof.get("birth_ref") == self.owned.birth_ref
                        and proof.get("containment_id") == self.owned.containment_id
                        and not proof.get("root_exited") and bool(owners)
                        and owners <= set(proof.get("remaining_pids", [])))
            self.client = LoopbackHttp(port, password, self.profile.cwd, owner, timeout=self.http_timeout)
            until = time.monotonic() + min(15, (operation.deadline - datetime.now(UTC)).total_seconds())
            while not owner():
                self._auth(operation)
                if self.owned.process.poll() is not None or time.monotonic() >= until:
                    raise OutcomeUncertain("owned server did not expose a verified loopback listener")
                time.sleep(0.05)
            self._observe_native_profile(operation)
            _, session = self._http(operation, "POST", "/session", {
                "title": "ACS " + operation.operation_id, "agent": self.profile.agent,
                "model": {"providerID": self.profile.provider_id, "id": self.profile.model_id},
                "metadata": self._metadata(operation.operation_id), "permission": SESSION_RULES,
            })
            self._session(session, expected_operation=operation.operation_id)
            self.session_id = session["id"]
            self._start_events(operation)
            return self._receipt("runtime_acknowledged", native_ack_type="session_create_response")
        return self._run(operation, "spawn", {"profile": self.profile.binding()}, perform)

    def attach(self, operation, client, session_id):
        native_id(session_id, "ses")
        def perform():
            if self.client is not None or not isinstance(client, LoopbackHttp):
                raise DriverRejected("attach requires a fresh authorized local HTTP transport")
            if client.directory != self.profile.cwd:
                raise DriverRejected("attached endpoint directory differs from the binding")
            self.client, self.ownership = client, "shared_attached"
            self.profile.validate()
            self._observe_native_profile(operation)
            _, value = self._http(operation, "GET", "/session/" + session_id)
            self._session(value)
            self.session_id = session_id
            self._start_events(operation)
            return self._receipt("context_observed")
        return self._run(operation, "attach", {"native_session_id": session_id}, perform)

    def _owned_mutation(self):
        if self.ownership != "exclusive_owned" or self.owned is None or self.session_id is None:
            raise DriverRejected("mutation requires exclusive owned native capacity")
        self.profile.validate(executable=False)

    def _inspect(self, operation):
        if self.client is None or self.session_id is None:
            raise OutcomeUncertain("no positively bound native session")
        _, session = self._http(operation, "GET", "/session/" + self.session_id)
        self._session(session)
        _, statuses = self._http(operation, "GET", "/session/status")
        status = statuses.get(self.session_id, {"type": "idle"})
        if status.get("type") not in ("idle", "busy", "retry"):
            raise OutcomeUncertain("unknown native session status")
        _, messages = self._http(operation, "GET", "/session/" + self.session_id + "/message")
        if not isinstance(messages, list) or len(messages) > 4096:
            raise OutcomeUncertain("native message history exceeds the bounded readback profile")
        if any(value.get("info", {}).get("sessionID") != self.session_id for value in messages):
            raise DriverRejected("message readback contains a different native session")
        for message in messages:
            message_id = native_id(message.get("info", {}).get("id"), "msg")
            if not isinstance(message.get("parts"), list) or any(
                part.get("sessionID") != self.session_id or part.get("messageID") != message_id
                for part in message["parts"]
            ):
                raise DriverRejected("native message parts are cross-bound")
        return {"session": session, "status": status, "messages": messages}

    def inspect(self, operation):
        with self._lock:
            self._auth(operation)
            view = self._inspect(operation)
            return self._receipt("context_observed", **view,
                                 process=self.supervisor.inspect(self.owned) if self.owned else None,
                                 event_stream=self._event_state)

    def resume(self, operation):
        def perform():
            self._owned_mutation()
            view = self._inspect(operation)
            self._start_events(operation)
            return self._receipt("context_resumed", status=view["status"])
        return self._run(operation, "resume", {"native_session_id": self.session_id}, perform)

    def _new_message_id(self):
        now = int(time.time() * 1000)
        self._native_counter = self._native_counter + 1 if now == self._last_ms else 1
        self._last_ms = now
        encoded = (now * 0x1000 + self._native_counter) & ((1 << 48) - 1)
        alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        return "msg_" + f"{encoded:012x}" + "".join(secrets.choice(alphabet) for _ in range(14))

    def _invocation(self, operation_id):
        record = self.journal.read(operation_id)
        if (record is None or record["binding_id"] != self.binding_id or record["action"] != "invoke"
                or record["input"]["payload"].get("binding") != self._identity
                or record["input"]["payload"].get("native_session_id") != self.session_id):
            raise DriverRejected("invocation belongs to another binding or native session")
        if (record["result"] or {}).get("native_message_id") not in (None, record["input"]["payload"]["native_message_id"]):
            raise DriverRejected("known native message identity cannot be changed")
        return record

    def _message_readback(self, operation, payload):
        message_id = native_id(payload["native_message_id"], "msg")
        try:
            _, value = self._http(operation, "GET", "/session/" + self.session_id + "/message/" + message_id)
        except HttpFailure as error:
            if error.status == 404:
                return None
            raise
        info = value.get("info", {})
        parts = value.get("parts")
        if (info.get("id") != message_id or info.get("sessionID") != self.session_id or info.get("role") != "user"
                or info.get("agent") != self.profile.agent
                or info.get("model", {}).get("providerID") != self.profile.provider_id
                or info.get("model", {}).get("modelID") != self.profile.model_id
                or info.get("tools") is not None or info.get("system") is not None
                or not isinstance(parts, list) or len(parts) != 1
                or parts[0].get("type") != "text" or parts[0].get("text") != payload["text"]
                or parts[0].get("sessionID") != self.session_id or parts[0].get("messageID") != message_id
                or parts[0].get("synthetic", False) or parts[0].get("ignored", False)):
            raise DriverRejected("native message readback differs from the exact authorized input")
        return value

    def invoke(self, operation, text):
        if not isinstance(text, str) or not text or len(text.encode()) > 1024 * 1024:
            raise DriverRejected("only bounded plain text is admitted")
        with self._lock:
            self._auth(operation)
            prior = self.journal.read(operation.operation_id)
            message_id = (prior["input"]["payload"].get("native_message_id") if prior and prior["action"] == "invoke"
                          else self._new_message_id())
            payload = {"native_session_id": self.session_id, "native_message_id": message_id, "text": text}
            def perform():
                self._owned_mutation()
                view = self._inspect(operation)
                if view["status"]["type"] != "idle":
                    raise DriverRejected("native session is active; implicit steering is prohibited")
                if self._active_message is None and view["messages"]:
                    raise OutcomeUncertain("unregistered native history cannot start a new authorized turn")
                if self._active_message is not None:
                    previous = [value for value in view["messages"] if value["info"].get("role") == "assistant"
                                and value["info"].get("parentID") == self._active_message
                                and (value["info"].get("time", {}).get("completed") is not None or value["info"].get("error"))]
                    if not previous:
                        raise OutcomeUncertain("prior invocation lacks terminal readback")
                self._active_message = message_id
                self._active_operation_id = operation.operation_id
                self._start_events(operation)
                code, _ = self._http(operation, "POST", "/session/" + self.session_id + "/prompt_async", {
                    "messageID": message_id, "agent": self.profile.agent,
                    "model": {"providerID": self.profile.provider_id, "modelID": self.profile.model_id},
                    "parts": [{"type": "text", "text": text}],
                })
                if code != 204:
                    raise OutcomeUncertain("native asynchronous scheduling ACK was not observed")
                for _ in range(self.readback_attempts):
                    if self._message_readback(operation, payload) is not None:
                        return self._receipt("runtime_acknowledged", native_message_id=message_id,
                                             native_ack_type="exact_message_readback", http_ack=204)
                    time.sleep(0.05)
                return self._receipt("runtime_dispatched", native_message_id=message_id,
                                     native_ack_type="http_204_scheduling_only", http_ack=204)
            return self._run(operation, "invoke", payload, perform)

    def reconcile(self, operation, invocation_operation_id):
        with self._lock:
            self._auth(operation)
            candidate = self.journal.read(invocation_operation_id)
            if candidate is not None and candidate["action"] == "spawn":
                return self._reconcile_spawn(operation, invocation_operation_id, candidate)
            record = self._invocation(invocation_operation_id)
            if record["state"] not in ("intent", "uncertain", "acknowledged"):
                raise DriverRejected("rejected operation cannot be promoted by reconciliation")
            payload = record["input"]["payload"]
            self._inspect(operation)
            if self._message_readback(operation, payload) is None:
                raise OutcomeUncertain("no exact native message readback; never resubmit")
            known = record["result"] or {}
            if known.get("native_message_id") not in (None, payload["native_message_id"]):
                raise DriverRejected("known native message identity cannot be changed")
            if record["state"] == "acknowledged":
                return record["result"]
            body = record["input"]
            result = self._receipt("runtime_acknowledged", native_message_id=payload["native_message_id"],
                                   native_ack_type="exact_message_readback",
                                   operation_id=invocation_operation_id, command_id=body["command_id"],
                                   message_id=body["message_id"])
            self.journal.event(invocation_operation_id, "reconciled", result)
            self.journal.finish(invocation_operation_id, "acknowledged", result)
            self._active_message = payload["native_message_id"]
            self._active_operation_id = invocation_operation_id
            return result

    def _reconcile_spawn(self, operation, original_id, record):
        if (record["binding_id"] != self.binding_id
                or record["input"]["payload"].get("binding") != self._identity
                or record["input"]["payload"].get("profile") != self.profile.binding()
                or record["state"] not in ("intent", "uncertain", "acknowledged")
                or self.ownership != "exclusive_owned" or self.client is None or self.owned is None):
            raise DriverRejected("session recovery requires the original owned process and immutable binding")
        with self.journal._connect() as connection:
            events = connection.execute("SELECT body FROM driver_events WHERE operation_id=? AND kind='http_intent'",
                                        (original_id,)).fetchall()
        if not any(json.loads(row[0])["method"] == "POST" and json.loads(row[0])["path"] == "/session" for row in events):
            raise OutcomeUncertain("no recorded native session-create dispatch intent")
        self._observe_native_profile(operation)
        _, sessions = self._http(operation, "GET", "/session")
        if not isinstance(sessions, list) or len(sessions) > 4096:
            raise OutcomeUncertain("native session recovery exceeds the bounded profile")
        matches = [value for value in sessions if value.get("metadata", {}).get("acs_operation_id") == original_id
                   and value.get("metadata", {}).get("acs_binding_id") == self.binding_id
                   and value.get("metadata", {}).get("acs_binding") == self._identity]
        if len(matches) != 1:
            raise OutcomeUncertain("session-create readback is not a unique metadata match")
        session = self._session(matches[0], expected_operation=original_id)
        if (record["result"] or {}).get("native_session_id") not in (None, session["id"]):
            raise DriverRejected("known native session identity cannot be replaced")
        if record["state"] == "acknowledged":
            return record["result"]
        self.session_id = session["id"]
        self._start_events(operation)
        body = record["input"]
        result = self._receipt("runtime_acknowledged", native_ack_type="unique_session_metadata_readback",
                               operation_id=original_id, command_id=body["command_id"], message_id=body["message_id"])
        self.journal.event(original_id, "session_reconciled", result)
        self.journal.finish(original_id, "acknowledged", result)
        return result

    def collect_result(self, operation, invocation_operation_id):
        with self._lock:
            self._auth(operation)
            record = self._invocation(invocation_operation_id)
            if record["state"] not in ("intent", "uncertain", "acknowledged"):
                raise DriverRejected("rejected invocation has no accepted response")
            payload = record["input"]["payload"]
            if self._message_readback(operation, payload) is None:
                raise OutcomeUncertain("response lacks its exact user-message readback")
            view = self._inspect(operation)
            answers = [value for value in view["messages"] if value["info"].get("role") == "assistant"
                       and value["info"].get("parentID") == payload["native_message_id"]]
            terminal = [value for value in answers if value["info"].get("time", {}).get("completed") is not None
                        or value["info"].get("error")]
            if view["status"]["type"] != "idle" or not terminal:
                raise OutcomeUncertain("correlated assistant output is not terminal")
            body = record["input"]
            errors = [value["info"]["error"] for value in terminal if value["info"].get("error")]
            result = self._receipt("response_received", native_message_id=payload["native_message_id"],
                                   native_assistant_ids=[value["info"]["id"] for value in terminal],
                                   assistant_text=[part["text"] for value in answers for part in value.get("parts", [])
                                                   if part.get("type") == "text"],
                                   native_error_digests=[digest(error) for error in errors],
                                   native_terminal_outcome=("interrupted" if any(error.get("name") == "MessageAbortedError" for error in errors)
                                                            else "failed" if errors else "completed"),
                                   operation_id=invocation_operation_id, command_id=body["command_id"],
                                   message_id=body["message_id"])
            self.journal.event(invocation_operation_id, "terminal_readback", result)
            return result

    def cancel(self, operation, native_message_id):
        native_id(native_message_id, "msg")
        def perform():
            self._owned_mutation()
            if native_message_id != self._active_message:
                raise DriverRejected("cancel target is not this binding's active message")
            invocation = self._invocation(self._active_operation_id)
            if self._message_readback(operation, invocation["input"]["payload"]) is None:
                raise OutcomeUncertain("cancel target lacks exact native message readback")
            sent_abort = False
            for _ in range(self.readback_attempts):
                latest = self._inspect(operation)
                users = [value["info"] for value in latest["messages"] if value["info"].get("role") == "user"]
                if not users or max(users, key=lambda value: (value["time"]["created"], value["id"]))["id"] != native_message_id:
                    raise DriverRejected("session-only abort cannot target a replaced message")
                if latest["status"]["type"] in ("busy", "retry") and not sent_abort:
                    _, value = self._http(operation, "POST", "/session/" + self.session_id + "/abort")
                    if value is not True:
                        raise OutcomeUncertain("native abort did not acknowledge scheduling")
                    sent_abort = True
                    latest = self._inspect(operation)
                terminal = [value for value in latest["messages"] if value["info"].get("role") == "assistant"
                            and value["info"].get("parentID") == native_message_id
                            and (value["info"].get("time", {}).get("completed") is not None or value["info"].get("error"))]
                if latest["status"]["type"] == "idle" and terminal:
                    errors = [value["info"]["error"] for value in terminal if value["info"].get("error")]
                    return self._receipt("response_received", native_message_id=native_message_id,
                                         abort_requested=sent_abort, native_status="idle",
                                         native_terminal_outcome=("interrupted" if any(error.get("name") == "MessageAbortedError" for error in errors)
                                                                  else "failed" if errors else "completed"),
                                         native_assistant_ids=[value["info"]["id"] for value in terminal])
                time.sleep(0.05)
            raise OutcomeUncertain("abort ACK lacks correlated terminal readback")
        return self._run(operation, "cancel", {"native_session_id": self.session_id,
                                              "native_message_id": native_message_id}, perform)

    def terminate(self, operation):
        def perform():
            if self.ownership != "exclusive_owned" or self.owned is None or self.supervisor is None:
                raise DriverRejected("termination requires this Driver's owned containment")
            self._auth(operation)
            proof = self.supervisor.terminate_tree(self.owned)
            if (proof.get("verified") is not True or proof.get("birth_ref") != self.owned.birth_ref
                    or proof.get("containment_id") != self.owned.containment_id
                    or proof.get("root_exited") is not True or proof.get("remaining_pids") != []
                    or self.owned.process.poll() is None):
                raise OutcomeUncertain("complete owned process termination is unverified")
            self._stop_events()
            for thread in self._diag_threads:
                thread.join(timeout=1)
            return self._receipt("process_tree_terminated", supervisor_proof=proof)
        return self._run(operation, "terminate", {"native_session_id": self.session_id}, perform)

    def detach_transport(self):
        with self._lock:
            if self.ownership == "exclusive_owned" and self.owned is not None:
                if self.supervisor is None:
                    raise DriverRejected(
                        "exclusive capacity cannot detach without termination proof"
                    )
                proof = self.supervisor.inspect(self.owned)
                if (
                    proof.get("verified") is not True
                    or proof.get("birth_ref") != self.owned.birth_ref
                    or proof.get("containment_id") != self.owned.containment_id
                    or proof.get("root_exited") is not True
                    or proof.get("remaining_pids") != []
                    or self.owned.process.poll() is None
                ):
                    raise DriverRejected(
                        "live exclusive capacity must be terminated before detach"
                    )
            self._stop_events()
            self.client = None
            self.session_id = None
            self.owned = None
            self.ownership = "unbound"
            if self._claim_fd is not None:
                os.close(self._claim_fd)
                self._claim_fd = None
