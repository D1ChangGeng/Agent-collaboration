"""Prepare a separately approved empty-Session settings/cold-resume probe.

No model turn or ACS message is issued. A failed start/resume is never retried
and never replaced with another Session. This tool does not qualify a Driver.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import time
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from runtime.codex_jsonrpc import JsonRpcClient, RpcError
from runtime.receiver_paths import private_parent
from runtime.supervisor import WindowsJobSupervisor
from tools.runtime.probe_codex_metadata import digest, private_directory

PROFILE = "acs-empty-session-probe"
PROVIDER = "acs_empty_session_probe"
MODEL = "acs-no-model"
DISABLED = (
    "multi_agent", "multi_agent_v2", "shell_tool", "request_permissions_tool",
    "apps", "plugins", "daemon_auto_start",
)
METHODS = (
    "initialize", "experimentalFeature/list", "permissionProfile/list",
    "thread/start", "thread/read", "thread/resume", "thread/turns/list",
)
PINNED_EXE = "9d563ee4e0441ff9d59d612013e0460ddf8e5709735c2d9f6b98b7ef8ca4eb42"
PINNED_SCHEMA = "8aabf260bb66e9ca9ae5d20253f443971834644fe4659c85f8b1cc9e1d22dd5c"
DIRECTORIES = ("home", "workspace", "temp", "appdata", "localappdata")
DEPENDENCIES = (
    "tools/runtime/probe_codex_session_settings.py", "tools/runtime/probe_codex_metadata.py",
    "runtime/codex_jsonrpc.py", "runtime/supervisor.py", "runtime/receiver_paths.py",
)


def configuration(root, executable):
    # JSON quoted forward-slash paths are valid TOML basic strings.
    paths = (":minimal", (root/"workspace").as_posix(), executable.as_posix())
    lines = [
        f'default_permissions = "{PROFILE}"', 'approval_policy = "never"',
        f'model_provider = "{PROVIDER}"', f'model = "{MODEL}"',
        'web_search = "disabled"', 'cli_auth_credentials_store = "file"',
        'project_root_markers = []',
        f"[permissions.{PROFILE}.filesystem]",
        *(f'{json.dumps(path)} = "read"' for path in paths),
        f"[permissions.{PROFILE}.network]", "enabled = false",
        f"[model_providers.{PROVIDER}]", 'name = "ACS empty-Session loopback"',
        'base_url = "http://127.0.0.1:9/v1"', 'env_key = "ACS_EMPTY_SESSION_PROBE_TOKEN"',
        'wire_api = "responses"', "[windows]", 'sandbox = "mxc"', "[features]",
        *(f"{name} = false" for name in DISABLED),
        "[otel]", 'exporter = "none"', "log_user_prompt = false",
    ]
    return "\n".join(lines)+"\n"


def prepare(executable, schema, directory, history_mode="legacy"):
    if history_mode not in {"legacy", "paginated"}:
        raise ValueError("only actual schema history modes are supported")
    executable, schema, root = (Path(p).resolve() for p in (executable, schema, directory))
    if root.exists() or digest(executable) != PINNED_EXE or digest(schema) != PINNED_SCHEMA:
        raise ValueError("new private directory and reviewed 0.166.0 binary/schema required")
    private_directory(root)
    for name in DIRECTORIES:
        (root/name).mkdir()
    (root/"home/config.toml").write_text(configuration(root, executable), encoding="utf-8")
    plan = {
        "schema_version": "acs-codex-empty-session-probe/1",
        "created_at": datetime.now(UTC).isoformat(), "root": str(root),
        "executable": str(executable), "executable_sha256": PINNED_EXE,
        "schema": str(schema), "schema_sha256": PINNED_SCHEMA,
        "config_sha256": digest(root/"home/config.toml"),
        "dependencies": {name: digest(ROOT/name) for name in DEPENDENCIES},
        "methods": list(METHODS), "notify": ["initialized"],
        "history_mode": history_mode,
        "new_Sessions_max": 1, "owned_processes_max": 2, "model_prompts": 0,
        "pagination_max_pages": 20, "phase_deadline_seconds": 45,
        "environment_policy": "private home/workspace, explicit OS paths, dummy loopback token; no inherited account/API/proxy/MCP",
        "sequence": ["preflight", "start one empty Session", "settings and empty history readback",
                     "stop own Job and verify empty", "new own Job", "resume exact original thread/session",
                     "settings and empty history readback", "stop own Job and verify empty"],
        "failure_policy": "stop; never retry start/resume or substitute another Session",
        "evidence_limit": "Native settings and empty cold-resume only; no model, ACS delivery or independent Agent proof",
    }
    (root/"plan.json").write_text(json.dumps(plan, indent=2)+"\n", encoding="utf-8")
    return plan


def checked(path, *, executing=False):
    path = Path(path).absolute()
    if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("actual regular plan required")
    plan = json.loads(path.read_text(encoding="utf-8"))
    root, executable = Path(plan["root"]).resolve(), Path(plan["executable"])
    private_parent(root)
    for name in DIRECTORIES:
        selected = root/name
        private_parent(selected)
        if selected.is_symlink() or not stat.S_ISDIR(selected.lstat().st_mode):
            raise ValueError("private regular directories required")
    expected = {
        "schema_version": "acs-codex-empty-session-probe/1", "executable_sha256": PINNED_EXE,
        "schema_sha256": PINNED_SCHEMA, "methods": list(METHODS), "notify": ["initialized"],
        "new_Sessions_max": 1, "owned_processes_max": 2, "model_prompts": 0,
        "pagination_max_pages": 20, "phase_deadline_seconds": 45,
        "dependencies": {name: digest(ROOT/name) for name in DEPENDENCIES},
    }
    if (path != root/"plan.json" or any(plan.get(k) != v for k, v in expected.items())
            or plan.get("history_mode") not in {"legacy", "paginated"}
            or digest(executable) != PINNED_EXE or digest(plan["schema"]) != PINNED_SCHEMA
            or digest(root/"home/config.toml") != plan["config_sha256"]
            or (root/"home/config.toml").read_text(encoding="utf-8") != configuration(root, executable)):
        raise ValueError("probe plan or reviewed pins changed")
    if (root/"result.json").exists() or (not executing and (root/"execution-started.json").exists()):
        raise ValueError("probe cannot be replayed, including after an uncertain interruption")
    for name in ("auth.json", "credentials.json", "config.local.toml"):
        if (root/"home"/name).exists():
            raise ValueError("unexpected private account/config state")
    return plan


def environment(root):
    env = {name: os.environ[name] for name in ("SystemRoot", "WINDIR", "COMSPEC") if name in os.environ}
    system_root = PureWindowsPath(os.environ["SystemRoot"])
    if not system_root.is_absolute() or len(system_root.drive) != 2 or system_root.drive[1] != ":":
        raise ValueError("a local absolute Windows SystemRoot is required")
    env["SystemDrive"] = system_root.drive
    env.update(CODEX_HOME=str(root/"home"), USERPROFILE=str(root/"home"), HOME=str(root/"home"),
               APPDATA=str(root/"appdata"), LOCALAPPDATA=str(root/"localappdata"),
               TEMP=str(root/"temp"), TMP=str(root/"temp"),
               PATH=str(Path(os.environ["SystemRoot"])/"System32"),
               ACS_EMPTY_SESSION_PROBE_TOKEN="local-dummy-not-an-account")
    return env


def pages(request, method, params):
    rows, seen = [], set()
    for _ in range(20):
        response = request(method, params)
        if not isinstance(response.get("data"), list):
            raise TypeError("invalid metadata page")
        rows.extend(response["data"])
        cursor = response.get("nextCursor")
        if cursor is None:
            return rows
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise ValueError("metadata pagination cursor invalid or repeated")
        seen.add(cursor)
        params = dict(params, cursor=cursor)
    raise ValueError("metadata pagination bound exceeded")


def features(request, thread_id=None):
    params = {"limit": 100}
    if thread_id is not None:
        params["threadId"] = thread_id
    rows = pages(request, "experimentalFeature/list", params)
    states = {}
    for row in rows:
        name, enabled = row.get("name"), row.get("enabled")
        if not isinstance(name, str) or type(enabled) is not bool or name in states:
            raise ValueError("ambiguous feature state")
        states[name] = enabled
    if any(states.get(name) is not False for name in DISABLED):
        raise ValueError("all disabled capabilities must be positively observed")
    return {name: states[name] for name in DISABLED}


def identity(thread, previous=None):
    actual = tuple(thread.get(name) for name in ("id", "sessionId"))
    if any(not isinstance(v, str) or not v for v in actual) or (previous is not None and actual != previous):
        raise ValueError("missing or changed Native thread/session identity")
    if thread.get("turns") != []:
        raise ValueError("probe expected an empty Native history")
    return actual


def settings(response, root):
    if (response.get("activePermissionProfile", {}).get("id") != PROFILE
            or response.get("approvalPolicy") != "never"
            or response.get("sandbox") != {"type": "readOnly", "networkAccess": False}
            or Path(response.get("cwd", "")) != root/"workspace"
            or response.get("modelProvider") != PROVIDER or response.get("model") != MODEL):
        raise ValueError("active Native settings did not match the fixed profile")
    return {key: response[key] for key in ("activePermissionProfile", "approvalPolicy", "sandbox", "modelProvider", "model")}


def phase(plan, result, previous=None):
    root = Path(plan["root"])
    supervisor, owned, client = WindowsJobSupervisor(), None, None
    evidence = {"phase": "start" if previous is None else "cold_resume", "methods": [], "owned_tree_stopped": False}
    result["phases"].append(evidence)
    deadline = time.monotonic()+45
    try:
        owned = supervisor.launch([plan["executable"], "app-server"], cwd=str(root/"workspace"),
                                  env=environment(root), label="acs-empty-session-probe",
                                  before_start=lambda: checked(root/"plan.json", executing=True))
        client = JsonRpcClient(owned.process.stdout, owned.process.stdin, stderr=owned.process.stderr, max_requests=85)

        def request(method, params):
            if method not in METHODS:
                raise ValueError("RPC outside approved probe scope")
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError("probe phase deadline")
            evidence["methods"].append(method)
            try:
                return client.request(method, params, timeout=min(10, remaining))
            except RpcError as error:
                # Keep the bounded raw error only in the private run directory.
                # The printed/shareable result contains a code and hash, never
                # arbitrary Native diagnostics or account/config values.
                raw = json.dumps(error.error, ensure_ascii=False).encode("utf-8")
                filename = "rpc-error-"+evidence["phase"]+".json"
                details = {"method": method, "error_sha256": hashlib.sha256(raw).hexdigest()}
                if type(error.error.get("code")) is int:
                    details["code"] = error.error["code"]
                if len(raw) <= 16384:
                    with (root/filename).open("xb") as artifact:
                        artifact.write(raw+b"\n")
                    details["private_artifact"] = filename
                else:
                    details["private_artifact"] = "omitted_over_16384_bytes"
                evidence["rpc_failure"] = details
                raise

        request("initialize", {"clientInfo": {"name": "acs-empty-session-probe", "version": "1"},
                               "capabilities": {"experimentalApi": True, "explicitGatewayOauth": True}})
        client.notify("initialized", {})
        evidence["global_features"] = features(request)
        available = pages(request, "permissionProfile/list", {"cwd": str(root/"workspace"), "limit": 100})
        matches = [row for row in available if row.get("id") == PROFILE]
        if len(matches) != 1 or matches[0].get("allowed") is not True:
            raise ValueError("fixed permission profile not positively allowed")
        params = {"cwd": str(root/"workspace"), "permissions": PROFILE, "approvalPolicy": "never",
                  "modelProvider": PROVIDER, "model": MODEL}
        if previous is None:
            params["ephemeral"] = False
            if plan.get("history_mode") == "paginated":
                params["historyMode"] = "paginated"
            result["session_start_requests"] += 1
            response = request("thread/start", params)
        else:
            params.update(threadId=previous[0], excludeTurns=plan.get("history_mode") == "paginated")
            response = request("thread/resume", params)
        selected = identity(response["thread"], previous)
        evidence["identity_sha256"] = hashlib.sha256(json.dumps(selected).encode()).hexdigest()
        evidence["settings"] = settings(response, root)
        evidence["thread_features"] = features(request, selected[0])
        paginated = plan.get("history_mode") == "paginated"
        readback = request("thread/read", {"threadId": selected[0], "includeTurns": not paginated})
        identity(readback["thread"], selected)
        if paginated:
            turns = pages(request, "thread/turns/list", {"threadId": selected[0], "itemsView": "full", "limit": 100,
                                                        "sortDirection": "desc"})
            if turns:
                raise ValueError("paginated Native history is not empty")
            evidence["paginated_empty_history_readback"] = True
        evidence.update(empty_history_readback=True, status="verified")
        return selected
    finally:
        if client is not None:
            try:
                client.close()
            except Exception as error:  # noqa: BLE001 - private diagnostics only.
                evidence["transport_close_error_type"] = type(error).__name__
        try:
            if owned is not None:
                proof = supervisor.terminate_tree(owned)
                evidence["owned_tree_stopped"] = (proof.get("verified") is True
                    and proof.get("root_exited") is True and proof.get("remaining_pids") == [])
        except Exception as error:  # noqa: BLE001 - stop uncertainty must remain visible.
            evidence["stop_error_type"] = type(error).__name__
        finally:
            try:
                supervisor.close()
            except Exception as error:  # noqa: BLE001 - cleanup does not authorize a second process.
                evidence.update(owned_tree_stopped=False, job_close_error_type=type(error).__name__)


def execute(path):
    if os.environ.get("ACS_EXECUTE_CODEX_EMPTY_SESSION_PROBE") != "approved":
        raise PermissionError("separate empty-Session/cold-resume operator approval required")
    plan = checked(path)
    root = Path(plan["root"])
    # Exclusive consumption precedes launch. Uncertain runs cannot replay.
    with (root/"execution-started.json").open("x", encoding="utf-8") as marker:
        json.dump({"started_at": datetime.now(UTC).isoformat()}, marker)
    result = {"started_at": datetime.now(UTC).isoformat(), "phases": [], "model_prompts": 0,
              "session_start_requests": 0, "evidence_class": "actual_empty_Native_settings_and_cold_resume_only"}
    try:
        selected = phase(plan, result)
        if result["phases"][-1]["owned_tree_stopped"] is not True:
            raise ValueError("original owned tree stop was not verified; no restart permitted")
        phase(plan, result, selected)
        if result["phases"][-1]["owned_tree_stopped"] is not True:
            raise ValueError("resumed owned tree stop was not verified")
        result["status"] = "empty_session_probe_complete"
    except Exception as error:  # noqa: BLE001 - never serialize raw private Native error/history.
        result.update(status="empty_session_probe_incomplete", error_type=type(error).__name__)
    finally:
        result["completed_at"] = datetime.now(UTC).isoformat()
        (root/"result.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    for name in ("executable", "schema", "directory"):
        prep.add_argument("--"+name, required=True)
    prep.add_argument("--history-mode", choices=("legacy", "paginated"), default="legacy")
    for name in ("check", "execute"):
        commands.add_parser(name).add_argument("--plan", required=True)
    args = parser.parse_args()
    value = (prepare(args.executable, args.schema, args.directory, args.history_mode) if args.command == "prepare" else
             checked(args.plan) if args.command == "check" else execute(args.plan))
    print(json.dumps(value, indent=2))
    if args.command == "execute" and (value.get("status") != "empty_session_probe_complete"
            or not all(p.get("owned_tree_stopped") is True for p in value["phases"])):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
