"""Guarded local ACS installation entry point for an assisting Agent."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import socket
import stat
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from urllib.parse import quote

from acs_bootstrap import (
    WEB_CHOICES,
    chatgpt_setup,
    check_machine,
    machine_binding,
    observe_machine,
)
from acs_doctor import ROOT, inspect


def run(*arguments: str, environment: dict[str, str] | None = None) -> None:
    subprocess.run(arguments, check=True, cwd=ROOT, env=environment, timeout=1200)


def private_root() -> Path:
    # Operator file reads pin every parent directory and reject symlink hops.
    return Path.home() / ".agent-collaboration"


def available_loopback_port(start: int) -> int:
    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise ValueError("no local provider port is available in the configured range")


def provider_readback(environment: dict[str, str]) -> list[dict[str, str]]:
    observed = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.acs-local.yml", "ps", "--format", "json"],
        check=True, capture_output=True, text=True, cwd=ROOT, env=environment, timeout=30,
    )
    services = {}
    payload = observed.stdout.strip()
    items = json.loads(payload) if payload.startswith("[") else [
        json.loads(line) for line in payload.splitlines()
    ]
    for item in items:
        if item.get("Project") == environment["COMPOSE_PROJECT_NAME"]:
            services[item["Service"]] = {"service": item["Service"], "state": item.get("State"),
                                         "health": item.get("Health")}
    if set(services) != {"postgres", "temporal"} or any(
        item["state"] != "running" or item["health"] != "healthy" for item in services.values()
    ):
        raise ValueError("local provider health readback failed")
    return [services[name] for name in ("postgres", "temporal")]


def owner_file(path: Path, content: str) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError("private runtime identity path already exists")
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)
    if os.name == "posix":
        path.chmod(0o600)


def migrate_private_identity(legacy: Path, destination: Path) -> None:
    files = ("runtime-dsn", "runtime-credential", "runtime-surface.json")
    if not all((legacy / name).is_file() for name in files):
        return
    if any((destination / name).exists() for name in files):
        if not all((destination / name).is_file() for name in files):
            raise ValueError("private runtime identity migration needs explicit repair")
        return
    from runtime.surface_config import SurfaceSettings

    previous = SurfaceSettings.model_validate_json((legacy / files[2]).read_bytes(), strict=True)
    if (previous.context.grant_ref != "grant:root"
            or previous.dsn_ref.kind != "file" or previous.credential_ref.kind != "file"
            or previous.dsn_ref.name != str(legacy / files[0])
            or previous.credential_ref.name != str(legacy / files[1])):
        raise ValueError("existing Runtime identity requires explicit migration")
    for name in files:
        path = legacy / name
        if path.is_symlink() or (os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077):
            raise ValueError("legacy Runtime identity file permissions are unsafe")
    old_dsn = (legacy / files[0]).read_text(encoding="utf-8")
    old_credential = (legacy / files[1]).read_text(encoding="utf-8")
    owner_file(destination / files[0], old_dsn)
    owner_file(destination / files[1], old_credential)
    data = previous.model_dump(mode="json")
    data["dsn_ref"]["name"] = str(destination / files[0])
    data["credential_ref"]["name"] = str(destination / files[1])
    owner_file(destination / files[2], json.dumps(data, indent=2) + "\n")


def git_observation(source: Path, *arguments: str) -> str:
    result = subprocess.run(["git", "-C", str(source), *arguments], capture_output=True,
                            text=True, check=True, timeout=30)
    return result.stdout.strip()


def release_command(root: Path, config_path: Path) -> list[str]:
    python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return [str(python), "-m", "runtime.project_entry", "--config", str(config_path),
            "--catalog", str(root / "docs/runtime/p2-mcp-tool-contract.json"),
            "--profile", "root_manager"]


def replace_codex_command(text: str, command: list[str]) -> str:
    """Update the two installer-owned values while preserving other TOML fields."""
    import re

    marker = re.search(r"(?m)^\s*\[mcp_servers\.agent_collaboration\]\s*(?:#.*)?$", text)
    if marker is None:
        raise ValueError("existing Codex ACS table requires explicit review")
    tail = text[marker.end():]
    boundary = re.search(r"(?m)^\s*\[\[?[A-Za-z_\"']", tail)
    end = marker.end() + boundary.start() if boundary else len(text)
    block = text[marker.end():end]
    for key, value in (("command", json.dumps(command[0])), ("args", json.dumps(command[1:]))):
        expression = r"(?m)^([ \t]*" + key + r"[ \t]*=[ \t]*)(.*)$"
        match = re.search(expression, block)
        # Earlier installer versions write command and args on one line. A
        # custom multiline value is kept for an explicit operator migration.
        if match is None:
            raise ValueError("existing Codex ACS command requires explicit review")
        if key == "args":
            try:
                json.loads(match.group(2))
            except ValueError as exc:
                raise ValueError("existing Codex ACS arguments require explicit review") from exc
        block = block[:match.start()] + match.group(1) + value + block[match.end():]
    return text[:marker.end()] + block + text[end:]


def configure_harnesses(harnesses: list[str], config_path: Path) -> dict[str, str]:
    pinned = release_command(ROOT, config_path)
    python = Path(pinned[0])
    if not python.is_file():
        raise ValueError("locked Runtime interpreter is unavailable")
    command = pinned
    installation_root = os.environ.get("ACS_INSTALL_ROOT")
    if installation_root:
        root = Path(installation_root)
        launcher = root / "acs_launcher.py"
        if not root.is_absolute() or launcher.is_symlink() or not launcher.is_file():
            raise ValueError("stable Runtime launcher is unavailable")
        launcher_python = os.environ.get("ACS_LAUNCHER_PYTHON", sys.executable)
        if not Path(launcher_python).is_absolute() or not Path(launcher_python).is_file():
            raise ValueError("stable launcher interpreter is unavailable")
        command = [launcher_python, str(launcher),
                   "--installation-root", str(root)]
    previous = os.environ.get("ACS_PREVIOUS_RELEASE")
    allowed_previous = release_command(Path(previous), config_path) if previous else None
    configured: dict[str, str] = {}
    rollback = private_root() / "rollback" / ("harness-" + str(int(time.time())))
    changes = []
    for harness in harnesses:
        if harness not in {"codex", "opencode"}:
            raise ValueError("unsupported Harness configuration target")
        if harness == "codex":
            path = Path.home() / ".codex" / "config.toml"
            marker = "[mcp_servers.agent_collaboration]"
            block = marker + "\ncommand = " + json.dumps(command[0]) + "\nargs = " + json.dumps(command[1:]) + "\n"
            if path.exists():
                text = path.read_text(encoding="utf-8")
                entry = tomllib.loads(text).get("mcp_servers", {}).get("agent_collaboration")
                if entry is not None:
                    if not isinstance(entry, dict) or not isinstance(entry.get("args"), list):
                        raise ValueError("existing Codex ACS MCP entry requires explicit review")
                    observed = [entry.get("command"), *entry["args"]]
                    if observed != command:
                        if not installation_root or observed not in [pinned, allowed_previous]:
                            raise ValueError("existing Codex ACS MCP entry differs; review it explicitly")
                        changes.append((path, replace_codex_command(text, command), "codex-config.toml"))
                if entry is None:
                    changes.append((path, text.rstrip() + "\n\n" + block, "codex-config.toml"))
            else:
                changes.append((path, block, "codex-config.toml"))
            configured[harness] = str(path)
        elif harness == "opencode":
            path = Path.home() / ".config" / "opencode" / "opencode.json"
            entry = {"type": "local", "command": command, "enabled": True}
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            if not isinstance(data, dict) or not isinstance(data.get("mcp", {}), dict):
                raise ValueError("OpenCode configuration shape requires explicit review")
            servers = data.setdefault("mcp", {})
            if "agent_collaboration" in servers and servers["agent_collaboration"] != entry:
                old = servers["agent_collaboration"]
                if (not installation_root or not isinstance(old, dict)
                        or old != {"type": "local", "command": old.get("command"), "enabled": True}
                        or old.get("command") not in [pinned, allowed_previous]):
                    raise ValueError("existing OpenCode ACS MCP entry differs; review it explicitly")
                servers["agent_collaboration"] = entry
                changes.append((path, json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                "opencode.json"))
            if "agent_collaboration" not in servers:
                servers["agent_collaboration"] = entry
                changes.append((path, json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                "opencode.json"))
            configured[harness] = str(path)
    for path, content, backup_name in changes:
        if path.exists():
            rollback.mkdir(parents=True, exist_ok=True, mode=0o700)
            (rollback / backup_name).write_bytes(path.read_bytes())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return configured


def source_metadata_roots(source: Path) -> list[str]:
    roots = [str(source)]
    for option in ("--absolute-git-dir", "--git-common-dir"):
        observed = Path(git_observation(source, "rev-parse", option))
        resolved = observed if observed.is_absolute() else source / observed
        value = str(resolved.resolve())
        if value not in roots:
            roots.append(value)
    return roots


def register_local_project(project: Path, project_id: str, config_path: Path,
                           source_name: str) -> dict:
    from runtime_project_registration import apply, preview

    from runtime.project_common import digest
    from runtime.surface_config import load_settings

    source = Path(git_observation(project, "rev-parse", "--show-toplevel")).resolve()
    if git_observation(source, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("Runtime registration requires a clean committed Source")
    root = private_root()
    catalog = json.loads((ROOT / "docs/runtime/p2-mcp-tool-contract.json").read_text(encoding="utf-8"))
    route_registry = json.loads((project / ".agents/coordination/routes.yaml").read_text(encoding="utf-8"))
    scope_ids = ["local-scope"] + [
        "scope-" + digest(["local-tenant", project_id, route["id"]])
        for route in route_registry["routes"]
    ]
    artifacts = [{"root": str(root / "cas" / scope), "scope_id": scope,
                  "authorized_source_roots": source_metadata_roots(source),
                  "max_bytes": 16 * 1024 * 1024} for scope in scope_ids]
    data = json.loads(config_path.read_text(encoding="utf-8"))
    selected = [data["artifacts"]] if data.get("artifacts") else []
    selected.extend(data.get("additional_artifacts", []))
    if selected:
        if selected != artifacts:
            raise ValueError("existing Source/CAS configuration requires explicit review")
    else:
        data["artifacts"] = artifacts[0]
        data["additional_artifacts"] = artifacts[1:]
        config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        if os.name == "posix":
            config_path.chmod(0o600)
    specification = {"schema_version": "acs-runtime-registration/1", "source_root": str(source),
                     "expected_commit": git_observation(source, "rev-parse", "HEAD"),
                     "expected_tree": git_observation(source, "rev-parse", "HEAD^{tree}"),
                     "scope_id": "local-scope", "agent_slot_id": "local-slot",
                     "name": source_name, "source_id": "source-root",
                     "repository_identity": {"kind": "git", "name": source_name},
                     "route_goals": {route["id"]: route["display_name"]
                                     for route in route_registry["routes"]},
                     "max_source_bytes": 16 * 1024 * 1024}
    skill_catalog = "docs/runtime/p2-skill-contract.json"
    if (source / skill_catalog).is_file() and git_observation(source, "ls-files", "--", skill_catalog):
        specification["skill_catalog_path"] = skill_catalog
    planned = preview(project, specification, load_settings(config_path), catalog)
    return apply(project, specification, config_path, catalog, planned["plan_digest"])


def initialize_local_authority(environment: dict[str, str], *, require_existing: bool = False) -> Path:
    """Create one owner credential; retries only read existing authority state."""
    from runtime.auth import LocalCredentialAuthenticator
    from runtime.domain import DomainAuthority
    from runtime.models import AuthenticatedContext
    from runtime.project_service import ProjectService
    from runtime.surfaces import SharedService

    root = private_root()
    if root.is_symlink():
        raise ValueError("private runtime directory path is unsafe")
    if require_existing and not root.is_dir():
        raise ValueError("automatic update requires an existing Runtime identity")
    if not require_existing:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix" and stat.S_IMODE(root.stat().st_mode) & 0o077:
        raise ValueError("private runtime directory permissions are unsafe")
    config_path = root / "runtime-surface.json"
    credential_path = root / "runtime-credential"
    dsn_path = root / "runtime-dsn"
    paths = (config_path, credential_path, dsn_path)
    if require_existing and not all(path.is_file() and not path.is_symlink() for path in paths):
        raise ValueError("automatic update requires a complete existing Runtime identity")
    if any(path.exists() or path.is_symlink() for path in paths):
        if not all(path.is_file() and not path.is_symlink() and
                   (os.name != "posix" or not stat.S_IMODE(path.stat().st_mode) & 0o077)
                   for path in paths):
            raise ValueError("private runtime identity requires explicit repair")
        from runtime.surface_config import configured_service
        with configured_service(config_path) as (service, settings):
            service.authenticate(settings.credential())
            if settings.context.grant_ref != "grant:root":
                raise ValueError("existing Runtime authority requires explicit enrollment")
        return config_path

    catalog = json.loads((ROOT / "docs/runtime/p2-mcp-tool-contract.json").read_text(encoding="utf-8"))
    permissions = {"profile.root_manager", "profile.engineer", "profile.reviewer",
                   "project.adopt", "source.manage", "source.read", "artifact.read", "artifact.write",
                   "work_item.create", "work_item.read", "work_item.transition", "message.send",
                   "message.read", "review.assign", "review.record", "acceptance.finalize",
                   "runtime.invoke", "runtime.control", "delivery.manage", "evidence.record"}
    for name in catalog["profiles"]["root_manager"]:
        permissions.update(catalog["tools"][name]["security_scopes"])
    secret = secrets.token_urlsafe(48)
    context = AuthenticatedContext("local-tenant", "acs-p1-authority", "local-1",
                                   "agent:root", "grant:root",
                                   hashlib.sha256(secret.encode()).hexdigest())
    dsn = ("postgresql://acs:" + quote(environment["ACS_POSTGRES_PASSWORD"], safe="")
           + "@127.0.0.1:" + environment["ACS_POSTGRES_PORT"] + "/acs")
    authority = DomainAuthority(dsn, context=context)
    authority.initialize()
    with authority._connect() as connection:
        existing = connection.execute("SELECT count(*) FROM grants").fetchone()[0]
    if existing:
        raise ValueError("existing Runtime authority requires explicit enrollment")
    authority.bootstrap_local_grant(tuple(sorted(permissions)), preserve_existing=True)
    service = SharedService(authority, LocalCredentialAuthenticator(context))
    ProjectService(service, catalog, profile="root_manager").initialize()
    owner_file(dsn_path, dsn + "\n")
    owner_file(credential_path, secret + "\n")
    surface = {"schema_version": "acs-surfaces/1", "context": {
        "tenant_id": context.tenant_id, "authority_id": context.authority_id,
        "authority_incarnation": context.authority_incarnation,
        "principal_ref": context.principal_ref, "grant_ref": context.grant_ref,
        "credential_hash": context.credential_hash},
        "dsn_ref": {"kind": "file", "name": str(dsn_path)},
        "credential_ref": {"kind": "file", "name": str(credential_path)}}
    owner_file(config_path, json.dumps(surface, indent=2) + "\n")
    return config_path


def existing_provider_environment() -> tuple[Path, dict[str, str]]:
    """Read the admitted provider profile without provisioning or migration."""
    root = private_root()
    path = root / "local-providers.json"
    for current in (path, *path.parents):
        if current.is_symlink():
            raise ValueError("existing provider path is unsafe")
    if (not root.is_dir() or not path.is_file() or
            (os.name == "posix" and (stat.S_IMODE(root.stat().st_mode) & 0o077
                                    or stat.S_IMODE(path.stat().st_mode) & 0o077))):
        raise ValueError("automatic update requires a private existing provider profile")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (data.get("schema_version") != "acs-local-providers/2"
            or not isinstance(data.get("password"), str) or len(data["password"]) < 48
            or any(type(data.get(key)) is not int or not 1024 <= data[key] <= 65535
                   for key in ("postgres_port", "temporal_port"))
            or data["postgres_port"] == data["temporal_port"]
            or not isinstance(data.get("compose_project"), str)
            or not data["compose_project"].startswith("acs-")
            or not data["compose_project"].replace("-", "").isalnum()):
        raise ValueError("existing provider profile requires explicit migration")
    return path, dict(os.environ, ACS_POSTGRES_PASSWORD=data["password"],
                      ACS_POSTGRES_PORT=str(data["postgres_port"]),
                      ACS_TEMPORAL_PORT=str(data["temporal_port"]),
                      COMPOSE_PROJECT_NAME=data["compose_project"])


def local_provider_environment() -> tuple[Path, dict[str, str]]:
    root = private_root()
    if root.is_symlink():
        raise ValueError("provider directory path is unsafe")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not root.is_dir() or (os.name == "posix" and stat.S_IMODE(root.stat().st_mode) & 0o077):
        raise ValueError("provider directory permissions are unsafe")
    secret_path = root / "local-providers.json"
    if secret_path.exists():
        if (
            secret_path.is_symlink()
            or not secret_path.is_file()
            or (os.name == "posix" and stat.S_IMODE(secret_path.stat().st_mode) & 0o077)
        ):
            raise ValueError("provider configuration path is unsafe")
        data = json.loads(secret_path.read_text(encoding="utf-8"))
        if (data.get("schema_version") not in {"acs-local-providers/1", "acs-local-providers/2"}
                or not isinstance(data.get("password"), str) or len(data["password"]) < 48):
            raise ValueError("existing provider configuration differs")
        if data["schema_version"] == "acs-local-providers/1":
            data = {**data, "postgres_port": 54329, "temporal_port": 7239,
                    "compose_project": "acs-local"}
        elif (type(data.get("postgres_port")) is not int
              or type(data.get("temporal_port")) is not int
              or not all(1024 <= data[key] <= 65535 for key in ("postgres_port", "temporal_port"))
              or data["postgres_port"] == data["temporal_port"]
              or not isinstance(data.get("compose_project"), str)
              or not data["compose_project"].startswith("acs-")
              or not data["compose_project"].replace("-", "").isalnum()):
            raise ValueError("existing provider configuration differs")
    else:
        postgres_port = available_loopback_port(54329)
        temporal_port = available_loopback_port(7239)
        data = {"schema_version": "acs-local-providers/2",
                "password": secrets.token_urlsafe(40),
                "postgres_port": postgres_port, "temporal_port": temporal_port,
                "compose_project": "acs-" + secrets.token_hex(6)}
        with secret_path.open("x", encoding="utf-8") as stream:
            json.dump(data, stream)
        if os.name == "posix":
            secret_path.chmod(0o600)
    environment = dict(os.environ)
    environment["ACS_POSTGRES_PASSWORD"] = data["password"]
    environment["ACS_POSTGRES_PORT"] = str(data["postgres_port"])
    environment["ACS_TEMPORAL_PORT"] = str(data["temporal_port"])
    environment["COMPOSE_PROJECT_NAME"] = data["compose_project"]
    return secret_path, environment


def install(
    *, harnesses: list[str], project: Path | None, project_id: str | None, apply: bool,
    host_confirmed: bool = False, expected_machine_id: str | None = None,
    runtime_only: bool = False,
    expected_account: str | None = None, expected_user_home: str | None = None,
    chatgpt_web: str | None = None, tunnel_id: str | None = None,
) -> dict:
    if apply and not host_confirmed:
        raise ValueError("confirm this Runtime host with --host-confirmed before installation")
    automatic = os.environ.get("ACS_AUTOMATIC_UPDATE") == "1"
    if automatic:
        if project is not None or project_id is not None:
            raise ValueError("automatic updates require a Runtime-only installation")
        runtime_only = True
    machine = observe_machine()
    if apply:
        check_machine(machine, expected_machine_id, expected_account, expected_user_home)
    web = chatgpt_setup(chatgpt_web, tunnel_id=tunnel_id)
    if apply and chatgpt_web is None:
        raise ValueError("confirm --chatgpt-web enable, skip or later before installation")
    report = inspect(project, harnesses=[] if runtime_only else harnesses, deep=False)
    if runtime_only:
        report["next_actions"] = [action for action in report.get("next_actions", [])
                                  if action != "Install the setup Skill from this checkout."]
    if project_id and project is None:
        raise ValueError("project_id requires a Management Root path")
    if project is not None and not project_id:
        raise ValueError("a stable project_id is required with the Management Root path")
    if project is not None:
        project = project.expanduser().resolve()
        if not project.is_dir():
            raise ValueError("Management Root must be an existing directory")
        if (project / ".agents/manifest.json").is_file():
            from runtime_project_adoption import plan

            plan(project, project_id)
    actions = [
        "Create or verify the locked Runtime Python environment",
        ("Check existing owner-local PostgreSQL and Temporal" if automatic else
         "Start and check owner-local PostgreSQL and Temporal"),
    ]
    if not runtime_only:
        actions.insert(1, "Install the setup Skill for " + ", ".join(harnesses))
    if project is not None:
        actions.extend(
            [
                "Preview and adopt the Management Root",
                "Preview and adopt the Runtime project identity",
                "Validate the Management Root and project identity",
            ]
        )
    result = {
        "schema_version": "acs-install-plan/1",
        "state": "planned",
        "source_root": str(ROOT),
        "project": str(project) if project else None,
        "project_id": project_id,
        "machine": machine,
        "runtime_only": runtime_only,
        "host_confirmation": "confirmed" if host_confirmed else "required_before_apply",
        "web_setup": web,
        "actions": actions,
        "readiness": report,
    }
    result["prerequisites"] = {
        name: detail["available"]
        for name, detail in report["tools"].items()
        if name in {"git", "uv", "docker"}
    }
    if not apply:
        return result
    if not report["source_backend"]["available"]:
        raise ValueError("this host cannot run the Source/CAS Runtime service")
    if not all(result["prerequisites"].values()):
        raise ValueError("required local tools are unavailable")
    machine_path = private_root() / "install-machine.json"
    if automatic and not machine_path.is_file():
        raise ValueError("automatic update requires an existing machine binding")
    if machine_path.exists():
        if machine_path.is_symlink():
            raise ValueError("installation machine binding path is unsafe")
        existing_machine = json.loads(machine_path.read_text(encoding="utf-8"))
        if machine_binding(existing_machine) != machine_binding(machine):
            raise ValueError("existing Runtime installation belongs to a different machine or account")
    legacy = Path.home() / ".local/share/agent-collaboration/local-providers.json"
    if not automatic and not (private_root() / "local-providers.json").exists() and legacy.is_file():
        previous = json.loads(legacy.read_text(encoding="utf-8"))
        if previous.get("schema_version") != "acs-local-providers/2":
            raise ValueError("existing provider profile requires explicit migration")
        root = private_root()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if root.is_symlink() or (os.name == "posix" and stat.S_IMODE(root.stat().st_mode) & 0o077):
            raise ValueError("provider directory permissions are unsafe")
        owner_file(root / "local-providers.json", json.dumps(previous) + "\n")
    if not automatic and legacy.is_file() and (private_root() / "local-providers.json").is_file():
        migrate_private_identity(legacy.parent, private_root())
    if project is not None:
        from workspace_setup import workspace_install

        preview = workspace_install(project, "adopt", True)
        if any(item.startswith(("error ", "preserve-conflict ", "refused ")) for item in preview):
            raise ValueError("Management Root adoption preview has conflicts")
    run("uv", "sync", "--frozen")
    if not runtime_only:
        skill_arguments = ["uv", "run", "--frozen", "python", "scripts/install_skill.py",
                           "--harness", *harnesses, "--knowledge"]
        if os.environ.get("ACS_PREVIOUS_RELEASE"):
            skill_arguments.extend(["--previous-source", os.environ["ACS_PREVIOUS_RELEASE"]])
        run(*skill_arguments)
    secret_path, environment = (existing_provider_environment() if automatic else
                                local_provider_environment())
    if not machine_path.exists():
        owner_file(machine_path, json.dumps(machine, indent=2) + "\n")
    if not automatic:
        run(
            "docker",
            "compose",
            "-f",
            "docker-compose.acs-local.yml",
            "up",
            "-d",
            "--wait",
            environment=environment,
        )
    result["provider_config_ref"] = str(secret_path)
    result["providers"] = {
        "compose_project": environment["COMPOSE_PROJECT_NAME"],
        "postgres_endpoint": "127.0.0.1:" + environment["ACS_POSTGRES_PORT"],
        "temporal_endpoint": "127.0.0.1:" + environment["ACS_TEMPORAL_PORT"],
        "services": provider_readback(environment),
    }
    config_path = (initialize_local_authority(environment, require_existing=True) if automatic else
                   initialize_local_authority(environment))
    result["runtime_config_ref"] = str(config_path)
    if project is not None:
        from runtime_project_adoption import adopt, validate
        from workspace_setup import validate_workspace, workspace_install

        changes = workspace_install(project, "adopt", False)
        if any(item.startswith(("error ", "preserve-conflict ", "refused ")) for item in changes):
            raise ValueError("Management Root adoption failed")
        valid, problems = validate_workspace(project)
        if not valid:
            raise ValueError("Management Root validation failed: " + "; ".join(problems))
        identity_preview = adopt(project, project_id, dry_run=True)
        if identity_preview["changed"]:
            backup = (
                Path.home()
                / ".local"
                / "share"
                / "agent-collaboration"
                / "rollback"
                / os.urandom(12).hex()
            )
            receipt = adopt(project, project_id, rollback_dir=backup)
            result["rollback_dir"] = receipt["rollback_dir"]
        validate(project, project_id)
    result["state"] = "local_authority_ready"
    result["remaining"] = []
    if project is not None:
        source = Path(git_observation(project, "rev-parse", "--show-toplevel"))
        if git_observation(source, "status", "--porcelain=v1", "--untracked-files=all"):
            result["remaining"].append(
                "Review and commit adopted Management Root files, then register the exact clean Source."
            )
        else:
            result["registration"] = register_local_project(project, project_id, config_path,
                                                            source.name)
            result["state"] = "project_registered"
    result["harness_configs"] = {} if runtime_only else configure_harnesses(harnesses, config_path)
    result["remaining"].append("Verify read_profile and tool discovery in each configured Harness.")
    result["next_action"] = (
        "Open the Management Root as a Root Agent." if project is not None else
        "Use the setup Skill in a chosen project to create or adopt its Management Root."
    )
    result["readback"] = inspect(project, config=config_path,
                                harnesses=[] if runtime_only else harnesses, deep=False,
                                tools_snapshot=report["tools"],
                                project_id=project_id if result["state"] == "project_registered" else None)
    result["web_setup"] = chatgpt_setup(chatgpt_web, str(ROOT), str(config_path), tunnel_id)
    if chatgpt_web == "enable":
        result["next_action"] = result["web_setup"]["next_action"]
    if runtime_only:
        result["readback"]["next_actions"] = [
            action for action in result["readback"].get("next_actions", [])
            if action != "Install the setup Skill from this checkout."
        ]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--harness", nargs="+", choices=["codex", "opencode"], default=["codex", "opencode"]
    )
    parser.add_argument("--project", type=Path)
    parser.add_argument("--project-id")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--host-confirmed", action="store_true")
    parser.add_argument("--expected-machine-id")
    parser.add_argument("--expected-account")
    parser.add_argument("--expected-user-home")
    parser.add_argument("--runtime-only", action="store_true")
    parser.add_argument("--chatgpt-web", choices=WEB_CHOICES)
    parser.add_argument("--tunnel-id")
    args = parser.parse_args()
    host_confirmed = args.host_confirmed or bool(os.environ.get("ACS_INSTALL_MACHINE_ID"))
    if args.apply and not host_confirmed:
        print(json.dumps({"schema_version": "acs-install-plan/1", "state": "needs_machine_confirmation",
                          "reason": "confirm_the_selected_Runtime_host_before_apply"}))
        return 2
    chatgpt_web = args.chatgpt_web or os.environ.get("ACS_INSTALL_CHATGPT_WEB")
    if args.apply and chatgpt_web is None:
        print(json.dumps({"schema_version": "acs-install-plan/1", "state": "needs_web_choice",
                          "web_setup": chatgpt_setup(None)}))
        return 2
    try:
        result = install(
            harnesses=args.harness,
            project=args.project,
            project_id=args.project_id,
            apply=args.apply,
            host_confirmed=host_confirmed,
            expected_machine_id=args.expected_machine_id or os.environ.get("ACS_INSTALL_MACHINE_ID"),
            expected_account=args.expected_account or os.environ.get("ACS_INSTALL_ACCOUNT"),
            expected_user_home=args.expected_user_home or os.environ.get("ACS_INSTALL_USER_HOME"),
            runtime_only=args.runtime_only,
            chatgpt_web=chatgpt_web, tunnel_id=args.tunnel_id or os.environ.get("ACS_INSTALL_TUNNEL_ID"),
        )
    except (ValueError, OSError, subprocess.SubprocessError):
        print(
            json.dumps(
                {
                    "schema_version": "acs-install-plan/1",
                    "state": "blocked",
                    "reason": "installation_prerequisite_or_step_failed",
                }
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
