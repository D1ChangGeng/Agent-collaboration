"""Explicitly gated, private no-Session Codex metadata probe on Windows.

Prepare/check writes only an isolated plan. Execute is a separate operator
choice, sends no thread/turn/prompt RPC, inherits no account or API credentials,
and tears down its own Job. This is not ACS Native receiving qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from runtime.codex_jsonrpc import JsonRpcClient
from runtime.receiver_paths import private_parent
from runtime.supervisor import WindowsJobSupervisor

METHODS = ("initialize", "experimentalFeature/list", "permissionProfile/list")
CONFIG = '''model_provider = "acs_metadata_probe"
model = "acs-no-model"
approval_policy = "never"
sandbox_mode = "read-only"
web_search = "disabled"
cli_auth_credentials_store = "file"
[model_providers.acs_metadata_probe]
name = "ACS metadata-only loopback"
base_url = "http://127.0.0.1:9/v1"
env_key = "ACS_METADATA_PROBE_TOKEN"
wire_api = "responses"
[features]
multi_agent = false
multi_agent_v2 = false
apps = false
plugins = false
[otel]
exporter = "none"
log_user_prompt = false
'''


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def private_directory(path):
    if os.name != "nt":
        raise ValueError("this probe is Windows-only")
    path.mkdir(exist_ok=False)
    user = subprocess.run(["whoami.exe"],capture_output=True,text=True,check=True,timeout=10).stdout.strip()
    subprocess.run(["icacls.exe",str(path),"/inheritance:r"],capture_output=True,check=True,timeout=10)
    subprocess.run(["icacls.exe",str(path),"/grant:r",f"{user}:(OI)(CI)F","/T","/C"],
        capture_output=True,check=True,timeout=10)
    private_parent(path)


def prepare(executable, schema, directory):
    executable, schema, directory = (Path(p).resolve() for p in (executable, schema, directory))
    if directory.exists() or not executable.is_file() or not schema.is_file():
        raise ValueError("new private directory and actual executable/schema required")
    private_directory(directory)
    for name in ("home", "workspace", "temp", "appdata", "localappdata"):
        (directory/name).mkdir()
    config = directory/"home/config.toml"
    config.write_text(CONFIG, encoding="utf-8")
    plan = {"schema_version":"acs-codex-metadata-probe/1", "created_at":datetime.now(UTC).isoformat(),
        "root":str(directory), "executable":str(executable), "executable_sha256":digest(executable),
        "schema":str(schema), "schema_sha256":digest(schema), "config_sha256":digest(config),
        "methods":list(METHODS), "notify":["initialized"], "Native_Sessions":0, "model_prompts":0,
        "environment_policy":"explicit OS paths and private dirs only; no inherited credentials/proxy/MCP",
        "provider":"loopback127.0.0.1:9 only, no model method is issued",
        "containment":"new owned unnamed Windows Job; no process-name matching or external stop"}
    (directory/"plan.json").write_text(json.dumps(plan,indent=2)+"\n",encoding="utf-8")
    return plan


def checked(path):
    path = Path(path).absolute()
    if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("probe plan must be an actual regular file")
    plan = json.loads(path.read_text(encoding="utf-8"))
    root = Path(plan["root"]).resolve()
    private_parent(root)
    for name in ("home", "workspace", "temp", "appdata", "localappdata"):
        selected = root/name
        private_parent(selected)
        if selected.is_symlink() or not stat.S_ISDIR(selected.lstat().st_mode):
            raise ValueError("probe directories must remain actual private directories")
    if (path != root/"plan.json" or plan["schema_version"] != "acs-codex-metadata-probe/1"
            or plan["methods"] != list(METHODS) or plan["notify"] != ["initialized"]
            or plan["Native_Sessions"] != 0 or plan["model_prompts"] != 0
            or digest(plan["executable"]) != plan["executable_sha256"]
            or digest(plan["schema"]) != plan["schema_sha256"]
            or digest(root/"home/config.toml") != plan["config_sha256"]
            or (root/"home/config.toml").read_text(encoding="utf-8") != CONFIG):
        raise ValueError("metadata probe plan or pinned files changed")
    if (root/"result.json").exists() or (root/"result.json").is_symlink():
        raise ValueError("a completed probe is not replayed; prepare a fresh plan")
    for name in ("auth.json", "credentials.json", "config.local.toml"):
        if (root/"home"/name).exists():
            raise ValueError("private probe home contains unexpected account/config state")
    return plan


def execute(path):
    if os.environ.get("ACS_EXECUTE_CODEX_METADATA_PROBE") != "approved":
        raise PermissionError("explicit metadata-process probe approval switch required")
    plan = checked(path)
    root = Path(plan["root"])
    env = {name:os.environ[name] for name in ("SystemRoot","WINDIR","COMSPEC") if name in os.environ}
    env.update(CODEX_HOME=str(root/"home"), USERPROFILE=str(root/"home"), HOME=str(root/"home"),
        APPDATA=str(root/"appdata"), LOCALAPPDATA=str(root/"localappdata"), TEMP=str(root/"temp"), TMP=str(root/"temp"),
        PATH=str(Path(os.environ["SystemRoot"])/"System32"), ACS_METADATA_PROBE_TOKEN="local-dummy-not-an-account")
    result = {"started_at":datetime.now(UTC).isoformat(), "evidence_class":"actual_CLI_metadata_only_not_receiving_or_model",
        "methods":[], "Native_Sessions":0, "model_prompts":0}
    supervisor, owned, client = WindowsJobSupervisor(), None, None
    try:
        owned = supervisor.launch([plan["executable"],"app-server"],cwd=str(root/"workspace"),env=env,
            label="acs-metadata-probe",before_start=lambda:checked(path))
        client = JsonRpcClient(owned.process.stdout,owned.process.stdin,stderr=owned.process.stderr,max_requests=4)
        initialized = client.request("initialize",{"clientInfo":{"name":"acs-metadata-probe","version":"1"},
            "capabilities":{"experimentalApi":True,"explicitGatewayOauth":True}},timeout=10)
        result["methods"].append("initialize")
        result["initialize_response_keys"] = sorted(initialized)
        client.notify("initialized",{})
        features = client.request("experimentalFeature/list",{"limit":100},timeout=10)
        result["methods"].append("experimentalFeature/list")
        result["features"] = [{"name":item.get("name"),"enabled":item.get("enabled")} for item in features.get("data",[])]
        permissions = client.request("permissionProfile/list",{"cwd":str(root/"workspace"),"limit":100},timeout=10)
        result["methods"].append("permissionProfile/list")
        result["permission_profile_response_keys"] = sorted(permissions)
        result["status"] = "metadata_complete"
    except Exception as error:  # noqa: BLE001 - private probe diagnostics do not expose raw account/config data.
        result.update(status="metadata_failed",error_type=type(error).__name__)
    finally:
        try:
            if client is not None:
                client.close()
            if owned is not None:
                proof = supervisor.terminate_tree(owned)
                result["owned_tree_stopped"] = proof.get("verified") is True and proof.get("root_exited") is True and proof.get("remaining_pids")==[]
        except Exception as error:  # noqa: BLE001 - cleanup failure is evidence, never a successful stop.
            result.update(owned_tree_stopped=False,cleanup_error_type=type(error).__name__)
        finally:
            try:
                supervisor.close()
            except Exception as error:  # noqa: BLE001 - preserve the first result and final cleanup uncertainty.
                result.update(owned_tree_stopped=False,job_close_error_type=type(error).__name__)
            result["completed_at"] = datetime.now(UTC).isoformat()
            (root/"result.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command",required=True)
    prep = commands.add_parser("prepare")
    for name in ("executable","schema","directory"):
        prep.add_argument("--"+name,required=True)
    for name in ("check","execute"):
        command = commands.add_parser(name);command.add_argument("--plan",required=True)
    args = parser.parse_args()
    value = prepare(args.executable,args.schema,args.directory) if args.command=="prepare" else (
        checked(args.plan) if args.command=="check" else execute(args.plan))
    print(json.dumps(value,indent=2))
    if args.command == "execute" and (value.get("status") != "metadata_complete" or not value.get("owned_tree_stopped")):
        raise SystemExit(1)


if __name__=="__main__":
    main()
