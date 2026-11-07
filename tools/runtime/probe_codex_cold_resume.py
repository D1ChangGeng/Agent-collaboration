"""Resume only the positively identified, stopped empty Session from a probe.

This is a bounded qualification tool, not production receiver cold recovery.
It never creates a Session, imports history, or issues a model turn.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from runtime.codex_jsonrpc import JsonRpcClient, RpcError
from runtime.receiver_paths import private_parent
from runtime.supervisor import WindowsJobSupervisor
from tools.runtime import probe_codex_session_settings as common

METHODS = ("initialize", "experimentalFeature/list", "permissionProfile/list", "thread/resume", "thread/read")


def empty_rollout(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024*1024:
        raise ValueError("bounded actual rollout file required")
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not records or records[0].get("type") != "session_meta":
        raise ValueError("original Session metadata must precede other records")
    selected, metadata_cwd = None, None
    for row in records:
        payload = row["payload"]
        if row.get("type") == "event_msg":
            settings = payload.get("thread_settings", {})
            permission = settings.get("permission_profile", {})
            filesystem = permission.get("file_system", {})
            if (set(payload) != {"type", "thread_id", "thread_settings"}
                    or payload.get("type") != "thread_settings_applied"
                    or selected is None or payload.get("thread_id") != selected[0]
                    or settings.get("active_permission_profile", {}).get("id") != common.PROFILE
                    or settings.get("approval_policy") != "never"
                    or settings.get("model") != common.MODEL or settings.get("model_provider_id") != common.PROVIDER
                    or (metadata_cwd is not None and settings.get("cwd") != metadata_cwd)
                    or permission.get("type") != "managed" or permission.get("network") != "restricted"
                    or filesystem.get("type") != "restricted" or not filesystem.get("entries")
                    or any(entry.get("access") != "read" for entry in filesystem["entries"])):
                raise ValueError("unknown event or unsafe settings are not empty-Session metadata")
            continue
        if row.get("type") != "session_meta":
            raise ValueError("conversation/turn or unknown records are not an empty rollout")
        actual = (payload.get("id"), payload.get("session_id"))
        if any(not isinstance(v, str) or not v for v in actual) or selected not in (None, actual):
            raise ValueError("rollout Native identity is incomplete or changed")
        selected = actual
        metadata_cwd = payload.get("cwd")
    return selected


def original(path):
    path = Path(path).absolute()
    if path.is_symlink() or not path.is_file():
        raise ValueError("actual source plan required")
    plan = json.loads(path.read_text(encoding="utf-8"))
    root = Path(plan["root"])
    private_parent(root)
    for name in common.DIRECTORIES:
        private_parent(root/name)
    if (path != root/"plan.json" or plan.get("schema_version") != "acs-codex-empty-session-probe/1"
            or common.digest(plan["executable"]) != common.PINNED_EXE
            or common.digest(plan["schema"]) != common.PINNED_SCHEMA
            or common.digest(root/"home/config.toml") != plan["config_sha256"]
            or (root/"home/config.toml").read_text(encoding="utf-8") != common.configuration(root, Path(plan["executable"]))):
        raise ValueError("original executable/schema/config differs from the reviewed empty probe")
    result_path = root/"result.json"
    if result_path.is_symlink() or not result_path.is_file():
        raise ValueError("original actual result required")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("session_start_requests") != 1 or result.get("model_prompts") != 0 or len(result.get("phases", [])) != 1:
        raise ValueError("one original empty Session start required")
    phase = result["phases"][0]
    if (phase.get("owned_tree_stopped") is not True
            or phase.get("methods", []).count("thread/start") != 1
            or any(name not in common.METHODS for name in phase["methods"])
            or phase.get("thread_features") != dict.fromkeys(common.DISABLED, False)
            or phase.get("global_features") != dict.fromkeys(common.DISABLED, False)):
        raise ValueError("original Native settings and owned-tree stop evidence required")
    common.settings(dict(phase["settings"], cwd=str(root/"workspace")), root)
    files = list((root/"home/sessions").rglob("*.jsonl"))
    if len(files) != 1:
        raise ValueError("exactly one original empty rollout required")
    selected = empty_rollout(files[0])
    identity_hash = hashlib.sha256(json.dumps(selected).encode()).hexdigest()
    if phase.get("identity_sha256") != identity_hash:
        raise ValueError("stored identity must match the actual original start response")
    for name in ("auth.json", "credentials.json", "config.local.toml"):
        if (root/"home"/name).exists():
            raise ValueError("unexpected account/config state")
    return plan, selected, files[0]


def prepare(source_plan, directory):
    source_plan, directory = Path(source_plan).resolve(), Path(directory).resolve()
    source, selected, rollout = original(source_plan)
    common.private_directory(directory)
    plan = {"schema_version": "acs-codex-empty-cold-resume-probe/1", "root": str(directory),
            "source_plan": str(source_plan), "source_plan_sha256": common.digest(source_plan),
            "source_result_sha256": common.digest(Path(source["root"])/"result.json"),
            "original_rollout": str(rollout), "original_rollout_sha256": common.digest(rollout),
            "original_identity_sha256": hashlib.sha256(json.dumps(selected).encode()).hexdigest(),
            "script_sha256": common.digest(Path(__file__)),
            "dependencies": {name: common.digest(ROOT/name) for name in common.DEPENDENCIES},
            "methods": list(METHODS), "notify": ["initialized"], "new_Sessions_max": 0,
            "owned_processes_max": 1, "model_prompts": 0, "deadline_seconds": 45,
            "history_evidence": "actual owned rollout contains Session metadata and strictly bound restricted settings events; no conversation/turn records",
            "failure_policy": "one resume of original identity; no start, history import, substitution or retry"}
    (directory/"plan.json").write_text(json.dumps(plan, indent=2)+"\n", encoding="utf-8")
    return plan


def checked(path):
    path = Path(path).absolute()
    if path.is_symlink() or not path.is_file():
        raise ValueError("actual regular plan required")
    plan = json.loads(path.read_text(encoding="utf-8"))
    root = Path(plan["root"])
    private_parent(root)
    source, selected, rollout = original(plan["source_plan"])
    if (path != root/"plan.json" or plan.get("schema_version") != "acs-codex-empty-cold-resume-probe/1"
            or plan.get("methods") != list(METHODS) or plan.get("notify") != ["initialized"]
            or plan.get("new_Sessions_max") != 0 or plan.get("owned_processes_max") != 1
            or plan.get("model_prompts") != 0 or plan.get("deadline_seconds") != 45
            or common.digest(plan["source_plan"]) != plan["source_plan_sha256"]
            or common.digest(Path(source["root"])/"result.json") != plan["source_result_sha256"]
            or str(rollout) != plan["original_rollout"] or common.digest(rollout) != plan["original_rollout_sha256"]
            or hashlib.sha256(json.dumps(selected).encode()).hexdigest() != plan["original_identity_sha256"]
            or common.digest(Path(__file__)) != plan["script_sha256"]
            or plan["dependencies"] != {name: common.digest(ROOT/name) for name in common.DEPENDENCIES}
            or (root/"result.json").exists()):
        raise ValueError("pinned original Session or probe plan changed")
    return plan, source, selected, rollout


def execute(path):
    if os.environ.get("ACS_EXECUTE_CODEX_EMPTY_SESSION_PROBE") != "approved":
        raise PermissionError("bounded local empty-Session probe approval required")
    plan, source, selected, rollout = checked(path)
    root, source_root = Path(plan["root"]), Path(source["root"])
    with (root/"execution-started.json").open("x", encoding="utf-8") as marker:
        json.dump({"started_at": datetime.now(UTC).isoformat()}, marker)
    result = {"started_at": datetime.now(UTC).isoformat(), "methods": [], "new_Sessions": 0,
              "model_prompts": 0, "owned_tree_stopped": False, "original_identity_sha256": plan["original_identity_sha256"],
              "history_scope": "metadata-only RPC plus actual owned empty rollout; full-history RPC unsupported in preceding probe"}
    supervisor, owned, client = WindowsJobSupervisor(), None, None
    deadline = time.monotonic()+45
    try:
        owned = supervisor.launch([source["executable"], "app-server"], cwd=str(source_root/"workspace"),
                                  env=common.environment(source_root), label="acs-empty-cold-resume",
                                  before_start=lambda: checked(path))
        client = JsonRpcClient(owned.process.stdout, owned.process.stdin, stderr=owned.process.stderr, max_requests=85)

        def request(method, params):
            remaining = deadline-time.monotonic()
            if method not in METHODS or remaining <= 0:
                raise ValueError("RPC outside probe scope or deadline")
            result["methods"].append(method)
            try:
                return client.request(method, params, timeout=min(10, remaining))
            except RpcError as error:
                raw = json.dumps(error.error, ensure_ascii=False).encode()
                failure = {"method": method, "error_sha256": hashlib.sha256(raw).hexdigest()}
                if type(error.error.get("code")) is int:
                    failure["code"] = error.error["code"]
                if len(raw) <= 16384:
                    with (root/"rpc-error.json").open("xb") as artifact:
                        artifact.write(raw+b"\n")
                    failure["private_artifact"] = "rpc-error.json"
                result["rpc_failure"] = failure
                raise

        request("initialize", {"clientInfo": {"name": "acs-empty-cold-resume", "version": "1"},
                               "capabilities": {"experimentalApi": True, "explicitGatewayOauth": True}})
        client.notify("initialized", {})
        result["global_features"] = common.features(request)
        profiles = common.pages(request, "permissionProfile/list", {"cwd": str(source_root/"workspace"), "limit": 100})
        matches = [row for row in profiles if row.get("id") == common.PROFILE]
        if len(matches) != 1 or matches[0].get("allowed") is not True:
            raise ValueError("original named profile not currently allowed")
        response = request("thread/resume", {"threadId": selected[0], "excludeTurns": True,
            "cwd": str(source_root/"workspace"), "permissions": common.PROFILE, "approvalPolicy": "never",
            "modelProvider": common.PROVIDER, "model": common.MODEL})
        common.identity(response["thread"], selected)
        result["original_identity_resumed"] = True
        result["settings"] = common.settings(response, source_root)
        result["thread_features"] = common.features(request, selected[0])
        readback = request("thread/read", {"threadId": selected[0], "includeTurns": False})
        common.identity(readback["thread"], selected)
        result.update(metadata_readback_same_identity=True, status="cold_resume_complete")
    except Exception as error:  # noqa: BLE001 - arbitrary private diagnostics are not printed.
        result.update(status="cold_resume_incomplete", error_type=type(error).__name__)
    finally:
        if client is not None:
            try:
                client.close()
            except Exception as error:  # noqa: BLE001 - still terminate owned Job.
                result["transport_close_error_type"] = type(error).__name__
        try:
            if owned is not None:
                proof = supervisor.terminate_tree(owned)
                result["owned_tree_stopped"] = (proof.get("verified") is True
                    and proof.get("root_exited") is True and proof.get("remaining_pids") == [])
        except Exception as error:  # noqa: BLE001 - keep cleanup uncertainty visible.
            result["cleanup_error_type"] = type(error).__name__
        finally:
            try:
                supervisor.close()
            except Exception as error:  # noqa: BLE001 - no successful stop claim on close failure.
                result.update(owned_tree_stopped=False, job_close_error_type=type(error).__name__)
        try:
            if empty_rollout(rollout) != selected:
                raise ValueError("original rollout identity changed")
            result["empty_rollout_after_stop"] = True
        except Exception as error:  # noqa: BLE001 - history uncertainty cannot qualify cold restore.
            result.update(empty_rollout_after_stop=False, history_error_type=type(error).__name__)
        if not result["owned_tree_stopped"] or not result.get("empty_rollout_after_stop"):
            result["status"] = "cold_resume_incomplete"
        result["completed_at"] = datetime.now(UTC).isoformat()
        (root/"result.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--source-plan", required=True)
    prep.add_argument("--directory", required=True)
    for name in ("check", "execute"):
        commands.add_parser(name).add_argument("--plan", required=True)
    args = parser.parse_args()
    value = (prepare(args.source_plan, args.directory) if args.command == "prepare" else
             checked(args.plan)[0] if args.command == "check" else execute(args.plan))
    print(json.dumps(value, indent=2))
    if args.command == "execute" and value.get("status") != "cold_resume_complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
