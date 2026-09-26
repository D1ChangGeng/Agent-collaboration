#!/usr/bin/env python3
"""Guarded local ACS installation entry point for an assisting Agent."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
from pathlib import Path

from acs_doctor import ROOT, inspect


def run(*arguments: str, environment: dict[str, str] | None = None) -> None:
    subprocess.run(arguments, check=True, cwd=ROOT, env=environment)


def private_root() -> Path:
    return Path.home() / ".local" / "share" / "agent-collaboration"


def local_provider_environment() -> tuple[Path, dict[str, str]]:
    root = private_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    secret_path = root / "local-providers.json"
    if secret_path.exists():
        if secret_path.is_symlink():
            raise ValueError("provider configuration path is unsafe")
        data = json.loads(secret_path.read_text(encoding="utf-8"))
        if data.get("schema_version") != "acs-local-providers/1":
            raise ValueError("existing provider configuration differs")
    else:
        data = {"schema_version": "acs-local-providers/1", "password": secrets.token_urlsafe(40)}
        with secret_path.open("x", encoding="utf-8") as stream:
            json.dump(data, stream)
        if os.name == "posix":
            secret_path.chmod(0o600)
    environment = dict(os.environ)
    environment["ACS_POSTGRES_PASSWORD"] = data["password"]
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
    result["state"] = "local_services_ready"
    result["remaining"] = [
        "Initialize the Runtime authority and bind scoped credentials.",
        "Register the exact clean project Source and read back ProjectContextPack.",
        "Configure Codex and OpenCode MCP entries and verify tools/list from each client.",
    ]
    result["readback"] = inspect(project)
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
