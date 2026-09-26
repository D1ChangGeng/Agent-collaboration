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
from pathlib import Path
from urllib.parse import quote

from acs_doctor import ROOT, inspect


def run(*arguments: str, environment: dict[str, str] | None = None) -> None:
    subprocess.run(arguments, check=True, cwd=ROOT, env=environment)


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
        check=True, capture_output=True, text=True, cwd=ROOT, env=environment,
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


def git_observation(source: Path, *arguments: str) -> str:
    result = subprocess.run(["git", "-C", str(source), *arguments], capture_output=True,
                            text=True, check=True, timeout=30)
    return result.stdout.strip()


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


def initialize_local_authority(environment: dict[str, str]) -> Path:
    """Create one owner credential; retries only read existing authority state."""
    from runtime.auth import LocalCredentialAuthenticator
    from runtime.domain import DomainAuthority
    from runtime.models import AuthenticatedContext
    from runtime.project_service import ProjectService
    from runtime.surfaces import SharedService

    root = private_root()
    if root.is_symlink():
        raise ValueError("private runtime directory path is unsafe")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix" and stat.S_IMODE(root.stat().st_mode) & 0o077:
        raise ValueError("private runtime directory permissions are unsafe")
    config_path = root / "runtime-surface.json"
    credential_path = root / "runtime-credential"
    dsn_path = root / "runtime-dsn"
    paths = (config_path, credential_path, dsn_path)
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
    authority.bootstrap_local_grant(tuple(sorted(permissions)))
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
    *, harnesses: list[str], project: Path | None, project_id: str | None, apply: bool
) -> dict:
    report = inspect(project)
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
        "Install the setup Skill for " + ", ".join(harnesses),
        "Start and check owner-local PostgreSQL and Temporal",
    ]
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
    legacy = Path.home() / ".local/share/agent-collaboration/local-providers.json"
    if not (private_root() / "local-providers.json").exists() and legacy.is_file():
        previous = json.loads(legacy.read_text(encoding="utf-8"))
        if previous.get("schema_version") != "acs-local-providers/2":
            raise ValueError("existing provider profile requires explicit migration")
        root = private_root()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if root.is_symlink() or (os.name == "posix" and stat.S_IMODE(root.stat().st_mode) & 0o077):
            raise ValueError("provider directory permissions are unsafe")
        owner_file(root / "local-providers.json", json.dumps(previous) + "\n")
    if project is not None:
        from workspace_setup import workspace_install

        preview = workspace_install(project, "adopt", True)
        if any(item.startswith(("error ", "preserve-conflict ", "refused ")) for item in preview):
            raise ValueError("Management Root adoption preview has conflicts")
    run("uv", "sync", "--frozen")
    run(
        "uv",
        "run",
        "--frozen",
        "python",
        "scripts/install_skill.py",
        "--harness",
        *harnesses,
        "--knowledge",
    )
    secret_path, environment = local_provider_environment()
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
    config_path = initialize_local_authority(environment)
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
    result["remaining"].append(
        "Configure Codex and OpenCode MCP entries and verify tools/list from each client."
    )
    result["readback"] = inspect(project, config=config_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--harness", nargs="+", choices=["codex", "opencode"], default=["codex", "opencode"]
    )
    parser.add_argument("--project", type=Path)
    parser.add_argument("--project-id")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = install(
            harnesses=args.harness,
            project=args.project,
            project_id=args.project_id,
            apply=args.apply,
        )
    except (ValueError, OSError, subprocess.CalledProcessError):
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
