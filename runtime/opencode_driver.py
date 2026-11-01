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
    DriverDeferred,
    DriverJournal,
    DriverRejected,
    OutcomeUncertain,
    digest,
    file_digest,
)
from runtime.receiver_paths import PathSecurityRejected, private_parent

if __package__:
    from .opencode_http import (
        HttpFailure,
        HttpPreCallTimeout,
        HttpRejected,
        LoopbackHttp,
        listener_owner_pids,
    )
else:
    from opencode_http import (
        HttpFailure,
        HttpPreCallTimeout,
        HttpRejected,
        LoopbackHttp,
        listener_owner_pids,
    )

SESSION_RULES = [
    {"permission": "*", "pattern": "*", "action": "deny"},
    {"permission": "task", "pattern": "*", "action": "deny"},
]
COLLABORATION_TOOLS = (
    "read_profile", "list_projects", "load_project", "list_collaborators",
    "check_inbox", "list_messages", "read_message", "send_message", "wait_for_response",
)
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


def reviewed_private_external_allow(profile, pattern):
    """Admit only OpenCode's exact private tool-output/cache path rules."""
    if os.name != "posix" or not isinstance(pattern, str):
        return False
    for root, suffix in (
        (Path(profile.data_root), ("opencode", "tool-output")),
        (Path(profile.temp_root), ("opencode",)),
    ):
        target = root.joinpath(*suffix)
        if pattern != str(target) + "/*":
            continue
        try:
            descriptor, _ = private_parent(root)
            os.close(descriptor)
            if root.resolve(strict=True) != root:
                return False
            cursor = root
            for part in suffix:
                cursor = cursor / part
                try:
                    info = cursor.lstat()
                except FileNotFoundError:
                    break
                if (
                    not stat.S_ISDIR(info.st_mode)
                    or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) & 0o022
                    or cursor.resolve(strict=True) != cursor
                ):
                    return False
            return True
        except (OSError, PathSecurityRejected, ValueError):
            return False
    return False


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
    agent: str | None
    provider_id: str | None
    model_id: str | None
    environment: dict[str, str]
    execution_mode: str = "restricted"
    collaboration_server: str | None = None

    def collaboration_permissions(self):
        server = self.collaboration_server
        if server is None:
            return {}
        if not isinstance(server, str) or re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", server) is None:
            raise DriverRejected("collaboration MCP server name is invalid")
        return {server + "_" + tool: "allow" for tool in COLLABORATION_TOOLS}

    def restricted_permissions(self):
        return {"*": "deny", "task": "deny", **self.collaboration_permissions()}

    def session_permissions(self):
        return [*SESSION_RULES, *({"permission": name, "pattern": "*", "action": "allow"}
            for name in self.collaboration_permissions())]

    @property
    def config_path(self):
        return Path(self.config_root) / "opencode" / "opencode.json"

    def binding(self):
        return {key: value for key, value in asdict(self).items() if key != "environment"}

    def validate(self, *, executable=True, fresh=False, config_digest=True):
        if self.execution_mode not in {"native", "restricted"}:
            raise DriverRejected("unsupported execution environment")
        if self.execution_mode == "restricted" and self.version not in {"1.18.27", "1.18.30", "1.18.31", "1.18.34"}:
            raise DriverRejected("OpenCode version requires a separate reference profile")
        roots = [self.home, self.config_root, self.data_root, self.state_root,
                 self.cache_root, self.temp_root, self.cwd]
        if any(not Path(path).is_absolute() or not Path(path).is_dir() for path in roots):
            raise DriverRejected("private runtime roots and authorized cwd must be absolute directories")
        if self.execution_mode == "restricted" and len({str(Path(path).resolve()) for path in roots}) != len(roots):
            raise DriverRejected("runtime roots must be independently scoped")
        if self.execution_mode == "restricted" and fresh and any(any(Path(path).iterdir()) for path in
                         (self.home, self.data_root, self.state_root, self.cache_root, self.temp_root)):
            raise DriverRejected("spawn requires fresh private runtime roots")
        if not Path(self.executable).is_absolute() or not Path(self.schema_path).is_absolute():
            raise DriverRejected("executable/schema paths must be absolute")
        if self.execution_mode == "restricted" and executable and file_digest(self.executable) != self.executable_sha256:
            raise DriverRejected("OpenCode executable differs from the pinned profile")
        if self.execution_mode == "restricted" and file_digest(self.schema_path) != self.schema_sha256:
            raise DriverRejected("OpenCode schema/configuration changed")
        if self.execution_mode == "restricted" and config_digest and file_digest(self.config_path) != self.config_sha256:
            raise DriverRejected("OpenCode configuration changed before native startup")
        selections = (self.agent, self.provider_id, self.model_id)
        if self.execution_mode == "restricted" and not all(isinstance(value, str) and value for value in selections):
            raise DriverRejected("trusted agent/provider/model selection is required")
        if self.execution_mode == "native":
            if any(value is not None and (not isinstance(value, str) or not value) for value in selections):
                raise DriverRejected("native selection must be explicit or inherited")
            if (self.provider_id is None) != (self.model_id is None):
                raise DriverRejected("native provider/model selection must be paired")
            if any(not isinstance(key, str) or not isinstance(value, str) or "\0" in key+value
                   for key, value in self.environment.items()):
                raise DriverRejected("invalid process environment")
            return self
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
        expected_permissions = self.restricted_permissions()
        if (config.get("permission") != expected_permissions
                or selected.get("permission") != expected_permissions
                or config.get("default_agent") != self.agent
                or config.get("model") != self.provider_id + "/" + self.model_id
                or selected.get("model") != self.provider_id + "/" + self.model_id
                or config.get("plugin", []) != []):
            raise DriverRejected("deny-all global/agent permissions and pinned selection are required")
        mcp = config.get("mcp", {})
        if self.collaboration_server is None:
            if mcp != {}:
                raise DriverRejected("unapproved MCP configuration in restricted profile")
        else:
            entry = mcp.get(self.collaboration_server) if isinstance(mcp, dict) else None
            command = entry.get("command") if isinstance(entry, dict) else None
            if (not isinstance(mcp, dict) or set(mcp) != {self.collaboration_server} or not isinstance(entry, dict)
                    or entry.get("type") != "local" or entry.get("enabled") is not True
                    or not isinstance(command, list) or not command
                    or any(not isinstance(arg, str) or not arg or "\0" in arg for arg in command)
                    or not Path(command[0]).is_absolute()):
                raise DriverRejected("restricted collaboration requires one pinned local MCP entry")
        for key, value in self.environment.items():
            if (not isinstance(key, str) or not isinstance(value, str) or "\0" in key + value
                    or "proxy" in key.lower() or key.startswith("OPENCODE_")
                    or key in {"NODE_OPTIONS", "BUN_OPTIONS", "LD_PRELOAD", "LD_LIBRARY_PATH"}):
                raise DriverRejected("environment contains an unapproved runtime/proxy override")
        return self

    def process_environment(self, password):
        values = dict(self.environment)
        if self.execution_mode == "native":
            values.update({"HOME": self.home, "USERPROFILE": self.home,
                "XDG_CONFIG_HOME": self.config_root, "XDG_DATA_HOME": self.data_root,
                "XDG_STATE_HOME": self.state_root, "XDG_CACHE_HOME": self.cache_root,
                "OPENCODE_SERVER_USERNAME": "opencode", "OPENCODE_SERVER_PASSWORD": password})
            return values
        values.update({
            "HOME": self.home, "USERPROFILE": self.home, "APPDATA": self.config_root,
            "LOCALAPPDATA": self.data_root, "XDG_CONFIG_HOME": self.config_root,
            "XDG_DATA_HOME": self.data_root, "XDG_STATE_HOME": self.state_root,
            "XDG_CACHE_HOME": self.cache_root, "TEMP": self.temp_root, "TMP": self.temp_root,
            "TMPDIR": self.temp_root, "OPENCODE_CONFIG_DIR": str(self.config_path.parent),
            "OPENCODE_DISABLE_PROJECT_CONFIG": "1", "OPENCODE_DISABLE_AUTOUPDATE": "1",
            "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
            "OPENCODE_DISABLE_MODELS_FETCH": "1", "OPENCODE_SERVER_USERNAME": "opencode",
            "OPENCODE_SERVER_PASSWORD": password,
        })
        if self.collaboration_server is not None:
            # OpenCode installs its SDK metadata in its native config directory.
            # Keep those mutable, owned files in state, away from the operator's
            # pinned configuration and its closed directory admission rules.
            values.pop("OPENCODE_CONFIG_DIR", None)
            values["OPENCODE_CONFIG"] = str(self.config_path)
            values["XDG_CONFIG_HOME"] = str(Path(self.state_root) / "native-config")
        return values


class OpenCodeNativeDriver:
    harness = "opencode"

    def __init__(self, binding_id, profile, journal: DriverJournal, *, identity: BindingIdentity, check_current, supervisor=None,
                 http_timeout=10, readback_attempts=10, auth_stager=None,
                 required_provider_url=None, clock=None, observe_events=True):
        if not isinstance(binding_id, str) or not binding_id or not callable(check_current):
            raise DriverRejected("immutable binding and current Node authorization are required")
        identity.validate()
        if (auth_stager is None) != (required_provider_url is None):
            raise DriverRejected("private auth stage and reviewed provider route must be paired")
        if auth_stager is not None and (
            not callable(getattr(auth_stager, "stage", None))
            or not callable(getattr(auth_stager, "assert_current", None))
            or not isinstance(required_provider_url, str)
            or not required_provider_url.startswith("https://")
        ):
            raise DriverRejected("private auth stage is not a bounded host capability")
        self.binding_id, self.profile, self.journal = binding_id, profile, journal
        self.clock = clock if clock is not None else getattr(journal, "clock", None)
        if self.clock is not None:
            self.journal.clock = self.clock
        self.identity, self._identity = identity, asdict(identity)
        self.check_current, self.supervisor = check_current, supervisor
        self.http_timeout, self.readback_attempts = http_timeout, readback_attempts
        self.auth_stager = auth_stager
        self.required_provider_url = required_provider_url
        self.auth_observation = None
        if type(observe_events) is not bool:
            raise DriverRejected("event observation must be a trusted boolean setting")
        self.observe_events = observe_events
        self._lock = threading.RLock()
        self._claim_journal = journal
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
        self._claim_fd, self._claim_token = journal.claim_ownership(binding_id)

    def _auth(self, operation: AuthorizedOperation):
        operation.validate(self.clock)
        if asdict(self.identity) != self._identity or self._claim_fd is None:
            raise DriverRejected("Driver binding is retired or detached")
        self.check_current(operation, self.identity)
        operation.validate(self.clock)
        if asdict(self.identity) != self._identity:
            raise DriverRejected("binding changed during authorization")

    def _receipt(self, layer, **values):
        return {"binding_id": self.binding_id, "binding": dict(self._identity),
                "native_session_id": self.session_id, "ownership": self.ownership,
                "receipt_layer": layer, "observed_at": (self.clock.observation_time() if self.clock is not None else datetime.now(UTC)).isoformat(), **values}

    def _run(self, operation, action, payload, function):
        with self._lock:
            self._auth(operation)
            record = self.journal.begin(operation, self.binding_id, action,
                                        {**payload, "binding": self._identity}, clock=self.clock)
            self._auth(operation)
            if record["state"] == "acknowledged":
                return record["result"]
            if not record["created"] and record["state"] != "deferred":
                raise OutcomeUncertain("original operation must be reconciled; no blind redispatch")
            if record["state"] == "deferred" and self.journal.has_mutating_io(operation.operation_id):
                raise OutcomeUncertain("deferred invocation has mutating I/O evidence")
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
                        if isinstance(error, DriverDeferred) and not self.journal.has_mutating_io(operation.operation_id):
                            state = "deferred"
                if state in {"rejected", "deferred"}:
                    self._active_message, self._active_operation_id = previous_active
                self.journal.finish(operation.operation_id, state, {"error_type": type(error).__name__})
                raise

    def _http(self, operation, method, path, payload=None, *, max_bytes=4 * 1024 * 1024, on_dispatch=None):
        self._auth(operation)
        if self.client is None:
            raise OutcomeUncertain("native endpoint is not bound")
        self.journal.event(operation.operation_id, "http_intent",
                           {"method": method, "path": path, "body_digest": digest(payload),
                            "binding": self._identity, "endpoint": self.client.endpoint})
        self._auth(operation)
        remaining = operation.remaining(self.clock)
        dispatch_evidence = {
            "method": method,
            "path": path,
            "body_digest": digest(payload),
            "binding": self._identity,
            "endpoint": self.client.endpoint,
        }
        def dispatch():
            if on_dispatch is not None:
                on_dispatch()
            self.journal.event(operation.operation_id, "http_dispatch", dispatch_evidence)

        try:
            status, value = self.client.request(
                method,
                path,
                payload,
                timeout=min(self.http_timeout, remaining),
                max_bytes=max_bytes,
                before_send=lambda: self._auth(operation),
                on_dispatch=dispatch,
            )
        except HttpPreCallTimeout as error:
            raise DriverRejected("native HTTP duration elapsed before dispatch") from error
        self.journal.event(operation.operation_id, "http_response",
                           {"method": method, "path": path, "status": status, "body_digest": digest(value)})
        return status, value

    def _observe_native_profile(self, operation):
        health = None
        for attempt in range(3):
            try:
                _, health = self._http(operation, "GET", "/global/health")
                break
            except (OSError, TimeoutError) as error:
                if attempt == 2:
                    raise OutcomeUncertain(
                        "owned native listener has no bounded health readback"
                    ) from error
                self._auth(operation)
                time.sleep(0.05)
        if (health.get("healthy") is not True or (self.profile.execution_mode == "restricted"
                and health.get("version") != self.profile.version)):
            raise DriverRejected("health/version does not match the pinned native profile")
        _, schema = self._http(operation, "GET", "/doc", max_bytes=16 * 1024 * 1024)
        if self.profile.execution_mode == "restricted" and digest(schema) != digest(json.loads(Path(self.profile.schema_path).read_text())):
            raise DriverRejected("served OpenAPI differs from the reviewed schema")
        _, config = self._http(operation, "GET", "/config")
        if self.auth_stager is not None:
            self.auth_stager.assert_current(self.profile)
            selected = config.get("provider", {}).get(self.profile.provider_id, {})
            if (
                not isinstance(selected, dict)
                or selected.get("options") != {"baseURL": self.required_provider_url}
                or selected.get("npm") != "@ai-sdk/openai"
            ):
                raise DriverRejected("effective native Responses route differs from owner scene")
            self._auth(operation)
            if self.client is None:
                raise DriverRejected("owned native provider readback has no transport")
            _, provider_state = self.client.request(
                "GET", "/provider", timeout=self.http_timeout, max_bytes=8 * 1024 * 1024,
                before_send=lambda: self._auth(operation),
            )
            all_providers = provider_state.get("all") if isinstance(provider_state, dict) else None
            connected = provider_state.get("connected") if isinstance(provider_state, dict) else None
            selected_providers = [
                item for item in all_providers if isinstance(item, dict)
                and item.get("id") == self.profile.provider_id
            ] if isinstance(all_providers, list) else []
            if (
                not isinstance(connected, list)
                or connected.count(self.profile.provider_id) != 1
                or len(selected_providers) != 1
                or selected_providers[0].get("source") not in {"api", "config"}
            ):
                raise DriverRejected("native provider did not consume the owner auth file")
            stage = self.auth_stager.assert_current(self.profile)
            self.auth_observation = {
                **stage, "provider_connected": True,
                "native_route_equal": True,
                "native_source": selected_providers[0].get("source"),
            }
            self.journal.event(
                operation.operation_id, "provider_auth_readback", self.auth_observation,
            )
        if self.profile.execution_mode == "native":
            self.journal.event(operation.operation_id, "native_environment_observed",
                {"version": health.get("version"), "agent": self.profile.agent})
            return
        agent = config.get("agent", {}).get(self.profile.agent, {})
        if (config.get("permission") != self.profile.restricted_permissions()
                or agent.get("permission") != self.profile.restricted_permissions()
                or config.get("default_agent") != self.profile.agent
                or config.get("model") != self.profile.provider_id + "/" + self.profile.model_id):
            raise DriverRejected("effective native configuration is not the deny-all profile")
        if self.profile.collaboration_server is not None:
            if set(config.get("mcp", {})) != {self.profile.collaboration_server}:
                raise DriverRejected("effective MCP inventory differs from restricted profile")
            _, servers = self._http(operation, "GET", "/mcp")
            if servers.get(self.profile.collaboration_server, {}).get("status") != "connected":
                raise DriverRejected("restricted collaboration MCP did not connect")
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
        observed_collaboration = set()
        for rule in rules[global_denies[-1] + 1:]:
            private_allow = (
                rule == {
                    "permission": "external_directory",
                    "pattern": rule["pattern"],
                    "action": "allow",
                }
                and reviewed_private_external_allow(self.profile, rule["pattern"])
            )
            collaboration_allow = (rule["permission"] in self.profile.collaboration_permissions()
                and rule["pattern"] == "*" and rule["action"] == "allow")
            if collaboration_allow:
                observed_collaboration.add(rule["permission"])
            if rule["action"] != "deny" and not private_allow and not collaboration_allow:
                raise DriverRejected(
                    "native agent has an unreviewed permission after the deny-all boundary"
                )
        if observed_collaboration != set(self.profile.collaboration_permissions()):
            raise DriverRejected("native collaboration permissions were not positively observed")

    def _metadata(self, operation_id):
        return {"acs_binding_id": self.binding_id, "acs_binding": self._identity,
                "acs_operation_id": operation_id}

    def _session_payload(self, operation_id):
        return {
            "title": "ACS " + operation_id,
            **({"agent": self.profile.agent} if self.profile.agent is not None else {}),
            **({"model": {"providerID": self.profile.provider_id, "id": self.profile.model_id}}
               if self.profile.provider_id is not None else {}),
            "metadata": self._metadata(operation_id),
            **({"permission": self.profile.session_permissions()} if self.profile.execution_mode == "restricted" else {}),
        }

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
                or self.profile.execution_mode == "restricted" and value.get("permission") != self.profile.session_permissions()
                or self.profile.agent is not None and value.get("agent") != self.profile.agent
                or self.profile.model_id is not None and value.get("model", {}).get("id") != self.profile.model_id
                or self.profile.provider_id is not None and value.get("model", {}).get("providerID") != self.profile.provider_id):
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
        if self.profile.execution_mode == "native" or not self.observe_events:
            # Owner communication uses bounded session/message readback at the
            # dispatch boundary. It does not subscribe to execution events.
            self._event_state = "not_required"
            return
        self._event_stop = threading.Event()
        stop = self._event_stop
        settled = threading.Event()
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
        self._event_state = "connecting"

        def read():
            def opened():
                self._auth(operation)
                self._event_state = "subscribed"
                self.journal.event(operation.operation_id, "event_subscription_opened",
                                   {"native_session_id": session_id, "binding": identity})
                settled.set()
            try:
                self.client.events(stop, observe, before_send=lambda: self._auth(operation), opened=opened)
                self._event_state = "closed"
            except DriverRejected:
                # Claim loss is already authoritative. Do not open the journal
                # from this background thread after its ownership was released.
                self._event_state = "unavailable"
            except Exception as error:  # noqa: BLE001 - background observation failure is journaled without response bodies.
                self._event_state = "unavailable"
                try:
                    self.journal.event(operation.operation_id, "event_subscription_unavailable",
                                       {"error_type": type(error).__name__, "binding": identity,
                                        "native_session_id": session_id})
                except Exception as journal_error:  # noqa: BLE001 - bounded background state
                    self._event_state = (
                        "unavailable_unjournaled:" + type(journal_error).__name__
                    )
            finally:
                settled.set()
        self._event_thread = threading.Thread(target=read, daemon=True)
        self._event_thread.start()
        if not settled.wait(timeout=min(2.0, float(self.http_timeout))):
            self._stop_events()
            self._event_state = "unavailable"

    def _stop_events(self):
        self._event_stop.set()
        thread = self._event_thread
        if thread is not None:
            for _ in range(3):
                if self.client is not None:
                    self.client.stop_events()
                thread.join(timeout=0.75)
                if not thread.is_alive():
                    break
            if thread.is_alive():
                raise DriverRejected("native event observation thread did not stop")
        self._event_thread = None

    def spawn(self, operation):
        def perform():
            if self.client is not None or self.owned is not None:
                raise DriverRejected("Driver already owns or attaches to an endpoint")
            self.profile.validate(fresh=True)
            if self.supervisor is None:
                raise DriverRejected("native spawn requires an actual Node containment supervisor")
            if self.auth_stager is not None:
                try:
                    stage = self.auth_stager.stage(self.profile)
                except ValueError as error:
                    raise DriverRejected("private OpenCode auth staging rejected") from error
                self.journal.event(operation.operation_id, "private_auth_staged", stage)
            password = secrets.token_urlsafe(36)
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            argv = [self.profile.executable]
            if self.profile.execution_mode == "restricted":
                argv.append("--pure")
            argv.extend(["serve", "--hostname", "127.0.0.1", "--port", str(port)])
            self.journal.event(operation.operation_id, "process_intent",
                               {"argv": argv, "profile": self.profile.binding(), "binding": self._identity})
            self._auth(operation)
            self.journal.event(
                operation.operation_id,
                "process_dispatch",
                {"argv": argv, "profile": self.profile.binding(), "binding": self._identity},
            )
            process_label = "opencode-" + hashlib.sha256(operation.operation_id.encode()).hexdigest()[:32]
            self.owned = self.supervisor.launch(argv, cwd=self.profile.cwd,
                                                env=self.profile.process_environment(password), label=process_label)
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
            until = time.monotonic() + min(15, operation.remaining(self.clock))
            while not owner():
                self._auth(operation)
                if self.owned.process.poll() is not None or time.monotonic() >= until:
                    raise OutcomeUncertain("owned server did not expose a verified loopback listener")
                time.sleep(0.05)
            self._observe_native_profile(operation)
            _, session = self._http(
                operation, "POST", "/session", self._session_payload(operation.operation_id)
            )
            self._session(session, expected_operation=operation.operation_id)
            self.session_id = session["id"]
            self._start_events(operation)
            return self._receipt("runtime_acknowledged", native_ack_type="session_create_response")
        return self._run(operation, "spawn", {"profile": self.profile.binding()}, perform)

    def replace_session(self, operation):
        """Replace one owned idle Session without starting a second native process."""
        recorded = self.journal.read(operation.operation_id)
        previous = (
            recorded.get("input", {}).get("payload", {}).get("previous_native_session_id")
            if isinstance(recorded, dict)
            else self.session_id
        )

        def perform():
            self._owned_mutation()
            if self.session_id != previous:
                raise DriverRejected("native session changed before replacement")
            before = self._inspect(operation)
            if before["status"]["type"] != "idle" or before["messages"]:
                raise DriverRejected("native session replacement requires one empty idle Session")
            self._stop_events()
            _, created = self._http(
                operation, "POST", "/session", self._session_payload(operation.operation_id)
            )
            self.session_id = None
            self._session(created, expected_operation=operation.operation_id)
            replacement = created["id"]
            if replacement == previous:
                raise DriverRejected("native session replacement reused the old identity")
            self.session_id = replacement
            _, old_value = self._http(operation, "GET", "/session/" + previous)
            old_metadata = old_value.get("metadata", {}) if isinstance(old_value, dict) else {}
            if (
                not isinstance(old_value, dict)
                or old_value.get("id") != previous
                or old_metadata.get("acs_binding_id") != self.binding_id
                or old_metadata.get("acs_binding") != self._identity
                or Path(old_value.get("directory", "")).resolve() != Path(self.profile.cwd).resolve()
            ):
                raise DriverRejected("retired native Session readback left the binding")
            _, values = self._http(operation, "GET", "/session")
            if (
                not isinstance(values, list)
                or len(values) > 4096
                or [item.get("id") for item in values].count(previous) != 1
                or [item.get("id") for item in values].count(replacement) != 1
            ):
                raise DriverRejected("native Session replacement list readback differs")
            after = self._inspect(operation)
            if after["status"]["type"] != "idle" or after["messages"]:
                raise DriverRejected("replacement native Session is not empty and idle")
            self._start_events(operation)
            result = self._receipt(
                "runtime_acknowledged",
                native_ack_type="session_replace_readback",
                previous_native_session_id=previous,
                native_session_id=replacement,
                previous_status="idle",
                replacement_status="idle",
                replacement_count=1,
                observed_session_count=len(values),
            )
            self.journal.event(operation.operation_id, "session_replacement_readback", result)
            return result

        return self._run(
            operation,
            "replace_session",
            {"previous_native_session_id": previous},
            perform,
        )

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
        controlled = (self.ownership == "exclusive_owned" and self.owned is not None
                      or self.profile.execution_mode == "native" and self.ownership == "shared_attached" and self.client is not None)
        if not controlled or self.session_id is None:
            raise DriverRejected("mutation requires exclusive owned native capacity")
        self.profile.validate(executable=False, config_digest=False)

    def _inspect_status(self, operation, *, on_dispatch=None):
        _, statuses = self._http(operation, "GET", "/session/status", on_dispatch=on_dispatch)
        if not isinstance(statuses, dict):
            raise OutcomeUncertain("native status inventory is malformed")
        status = statuses.get(self.session_id, {"type": "idle"})
        if not isinstance(status, dict) or status.get("type") not in ("idle", "busy", "retry"):
            raise OutcomeUncertain("unknown native session status")
        return status

    def inspect_readiness(self, operation, *, before_status):
        """Read current activity after binding validation, without message history.

        The trusted caller timestamps the final status request after expensive
        authorization checks. A slow response still consumes the same lease.
        """
        with self._lock:
            self._auth(operation)
            if self.client is None or self.session_id is None:
                raise OutcomeUncertain("no positively bound native session")
            _, session = self._http(operation, "GET", "/session/" + self.session_id)
            self._session(session)
            status = self._inspect_status(operation, on_dispatch=before_status)
            return self._receipt("context_observed", session=session, status=status)

    def _inspect(self, operation):
        if self.client is None or self.session_id is None:
            raise OutcomeUncertain("no positively bound native session")
        _, session = self._http(operation, "GET", "/session/" + self.session_id)
        self._session(session)
        status = self._inspect_status(operation)
        _, messages = self._http(operation, "GET", "/session/" + self.session_id + "/message")
        if not isinstance(messages, list) or len(messages) > 4096:
            raise OutcomeUncertain("native message history exceeds the bounded readback profile")
        if any(value.get("info", {}).get("sessionID") != self.session_id for value in messages):
            raise DriverRejected("message readback contains a different native session")
        for message in messages:
            message_id = native_id(message.get("info", {}).get("id"), "msg")
            parts = message.get("parts")
            if not isinstance(parts, list) or any(not isinstance(part, dict) for part in parts):
                raise DriverRejected("native message parts are malformed")
            if any(
                part.get("sessionID") != self.session_id or part.get("messageID") != message_id
                for part in parts
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
        now = int((self.clock.observation_time().timestamp() if self.clock is not None else time.time()) * 1000)
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
                or self.profile.agent is not None and info.get("agent") != self.profile.agent
                or self.profile.provider_id is not None and info.get("model", {}).get("providerID") != self.profile.provider_id
                or self.profile.model_id is not None and info.get("model", {}).get("modelID") != self.profile.model_id
                or info.get("tools") is not None or info.get("system") is not None):
            raise DriverRejected("native message readback differs from the exact authorized input")
        # OpenCode persists the exact user-message header before its text part.
        # Only this narrow state is pending; callers retain their bounded readback
        # window and never submit another prompt when that window is exhausted.
        if not isinstance(parts, list) or any(not isinstance(part, dict) for part in parts):
            raise DriverRejected("native message parts are malformed")
        if parts == []:
            self.journal.event(operation.operation_id, "message_readback_incomplete", {
                "native_session_id": self.session_id, "native_message_id": message_id,
                "reason": "parts_not_committed",
            })
            return None
        if (not isinstance(parts, list) or len(parts) != 1
                or parts[0].get("type") != "text" or parts[0].get("text") != payload["text"]
                or parts[0].get("sessionID") != self.session_id or parts[0].get("messageID") != message_id
                or parts[0].get("synthetic", False) or parts[0].get("ignored", False)):
            raise DriverRejected("native message readback differs from the exact authorized input")
        return value

    def invoke(self, operation, text, *, on_dispatch=None):
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
                    raise DriverDeferred("busy")
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
                    "messageID": message_id,
                    **({"agent": self.profile.agent} if self.profile.agent is not None else {}),
                    **({"model": {"providerID": self.profile.provider_id, "modelID": self.profile.model_id}}
                       if self.profile.provider_id is not None else {}),
                    "parts": [{"type": "text", "text": text}],
                }, on_dispatch=on_dispatch)
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
            try:
                self._auth(operation)
                record = self._invocation(invocation_operation_id)
                if record["state"] not in ("intent", "uncertain", "acknowledged"):
                    raise DriverRejected("rejected invocation has no accepted response")
                payload = record["input"]["payload"]
                if self._message_readback(operation, payload) is None:
                    raise OutcomeUncertain("response lacks its exact user-message readback")
                view = self._inspect(operation)
            except (HttpRejected, HttpFailure, OSError, TimeoutError) as error:
                raise OutcomeUncertain("native terminal readback transport is temporarily unavailable") from error
            answers = [value for value in view["messages"] if value["info"].get("role") == "assistant"
                       and value["info"].get("parentID") == payload["native_message_id"]]
            terminal = [value for value in answers if value["info"].get("time", {}).get("completed") is not None
                        or value["info"].get("error")]
            if view["status"]["type"] != "idle" or not terminal:
                raise OutcomeUncertain("correlated assistant output is not terminal")
            body = record["input"]
            errors = [value["info"]["error"] for value in terminal if value["info"].get("error")]
            terminal_observed_at = self.journal.first_event_observed_at(
                invocation_operation_id, "terminal_readback",
            ) or (self.clock.observation_time() if self.clock is not None else datetime.now(UTC)).isoformat()
            result = self._receipt("response_received", native_message_id=payload["native_message_id"],
                                   native_assistant_ids=[value["info"]["id"] for value in terminal],
                                   assistant_text=[part["text"] for value in answers for part in value.get("parts", [])
                                                   if part.get("type") == "text"],
                                   assistant_part_types=[part.get("type") for value in answers
                                                         for part in value.get("parts", [])],
                                   delegation_part_count=sum(
                                       part.get("type") in {"tool", "task", "subtask", "agent"}
                                       for value in answers for part in value.get("parts", [])
                                   ),
                                   native_error_digests=[digest(error) for error in errors],
                                   native_terminal_outcome=("interrupted" if any(error.get("name") == "MessageAbortedError" for error in errors)
                                                            else "failed" if errors else "completed"),
                                   native_terminal_observed_at=terminal_observed_at,
                                   operation_id=invocation_operation_id, command_id=body["command_id"],
                                   message_id=body["message_id"])
            self.journal.event(
                invocation_operation_id, "terminal_readback", result,
                observed_at=terminal_observed_at,
            )
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
            owned_group = self.profile.execution_mode == "native" and proof.get("scope") == "owned_process_group"
            if owned_group:
                if (proof.get("verified") is not True or proof.get("birth_ref") != self.owned.birth_ref
                        or proof.get("containment_id") != self.owned.containment_id
                        or proof.get("root_exit_code") is None or proof.get("remaining_group_members") != []
                        or self.owned.process.poll() is None):
                    raise OutcomeUncertain("owned process group stop readback is incomplete")
            elif (proof.get("verified") is not True or proof.get("birth_ref") != self.owned.birth_ref
                    or proof.get("containment_id") != self.owned.containment_id
                    or proof.get("root_exited") is not True or proof.get("remaining_pids") != []
                    or self.owned.process.poll() is None):
                raise OutcomeUncertain("complete owned process termination is unverified")
            self._stop_events()
            for thread in self._diag_threads:
                thread.join(timeout=2)
                if thread.is_alive():
                    raise OutcomeUncertain("native diagnostic drain thread did not stop")
            self._diag_threads = []
            return self._receipt("process_group_terminated" if owned_group else "process_tree_terminated", supervisor_proof=proof)
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
                    or ((proof.get("root_exit_code") is None or proof.get("remaining_group_members") != [])
                        if self.profile.execution_mode == "native" and proof.get("scope") == "owned_process_group" else
                        (proof.get("root_exited") is not True or proof.get("remaining_pids") != []))
                    or self.owned.process.poll() is None
                ):
                    raise DriverRejected(
                        "live exclusive capacity must be terminated before detach"
                    )
            self._stop_events()
            for thread in self._diag_threads:
                thread.join(timeout=2)
                if thread.is_alive():
                    raise DriverRejected("native diagnostic drain thread did not stop")
            self._diag_threads = []
            self.client = None
            self.session_id = None
            self.owned = None
            self.ownership = "unbound"
            if self._claim_token is not None:
                self._claim_journal.release_claim(self._claim_token)
                self._claim_token = None
                self._claim_fd = None
