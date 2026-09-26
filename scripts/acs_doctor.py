#!/usr/bin/env python3
"""Read-only installation and project readiness report for ACS."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def command_version(name: str, *args: str) -> dict[str, str | bool]:
    executable = shutil.which(name)
    if not executable:
        return {"available": False, "detail": "not found"}
    try:
        result = subprocess.run(
            [executable, *args], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "detail": "probe failed"}
    line = (result.stdout or result.stderr).strip().splitlines()
    return {
        "available": result.returncode == 0,
        "detail": line[0][:160] if line else f"exit {result.returncode}",
    }


def runtime_readback(config: Path, catalog: Path, profile: str) -> dict:
    try:
        from runtime.project_service import ProjectService
        from runtime.surface_config import configured_service

        contract = json.loads(catalog.read_text(encoding="utf-8"))
        with configured_service(config) as (service, settings):
            credential = settings.credential()
            service.authenticate(credential)
            projects = ProjectService(service, contract, profile=profile)
            _, snapshot, _ = projects.execute("read_profile", {}, credential)
            _, found, _ = projects.execute("list_projects", {}, credential)
            contexts = []
            for project in found["items"]:
                state, pack, _ = projects.execute(
                    "load_project", {"project_id": project["project_id"]}, credential
                )
                contexts.append(
                    {
                        "project_id": project["project_id"],
                        "state": state,
                        "root_handle": pack.get("root_handle"),
                        "context_completeness": pack.get("context_completeness"),
                    }
                )
            return {
                "state": snapshot["connection_state"],
                "profile": snapshot["profile"],
                "grant": snapshot["grant"],
                "projects": found["items"],
                "project_contexts": contexts,
                "tools": projects.available_tools(credential),
            }
    except Exception:  # noqa: BLE001 - configuration and backend details stay private
        return {"state": "unavailable", "reason": "runtime_readback_failed"}


def inspect(
    project: Path | None = None,
    *,
    config: Path | None = None,
    catalog: Path | None = None,
    profile: str = "root_manager",
) -> dict:
    report: dict = {
        "schema_version": "acs-install-readiness/1",
        "platform": sys.platform,
        "source_backend": {
            "available": sys.platform.startswith("linux"),
            "required_host": "linux",
        },
        "python": sys.version.split()[0],
        "source_root": str(ROOT),
        "tools": {
            "git": command_version("git", "--version"),
            "uv": command_version("uv", "--version"),
            "docker": command_version("docker", "compose", "version"),
            "codex": command_version("codex", "--version"),
            "opencode": command_version("opencode", "--version"),
        },
    }
    interpreter = (
        ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    )
    report["runtime_environment"] = (
        command_version(
            str(interpreter),
            "-c",
            "import runtime, mcp, psycopg, temporalio; print('ACS Runtime imports ready')",
        )
        if interpreter.is_file()
        else {"available": False, "detail": "not installed"}
    )
    report["setup_skill"] = (
        Path.home() / ".agents/skills/agent-collaboration-setup/SKILL.md"
    ).is_file()
    if project is not None:
        target = project.expanduser().resolve()
        report["project"] = {"path": str(target), "exists": target.is_dir()}
        manifest = target / ".agents/manifest.json"
        if manifest.is_file():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                report["project"].update(
                    {
                        "root_id": data.get("root_id"),
                        "project_id": data.get("project_id"),
                        "schema_version": data.get("schema_version"),
                    }
                )
            except (OSError, UnicodeError, json.JSONDecodeError):
                report["project"]["manifest_state"] = "invalid"
    if config is not None:
        report["runtime"] = runtime_readback(
            config, catalog or ROOT / "docs/runtime/p2-mcp-tool-contract.json", profile
        )
    report["next_actions"] = []
    if not report["tools"]["docker"]["available"]:
        report["next_actions"].append(
            "Install and start Docker Compose with the user's system authorization."
        )
    if not report["tools"]["uv"]["available"]:
        report["next_actions"].append("Install uv for the Python Runtime environment.")
    if not report["runtime_environment"]["available"]:
        report["next_actions"].append("Run uv sync --frozen in the verified ACS checkout.")
    if not report["setup_skill"]:
        report["next_actions"].append("Install the setup Skill from this checkout.")
    if not report["source_backend"]["available"]:
        report["next_actions"].append(
            "Run the Source/CAS Runtime service in a verified Linux or WSL environment."
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--profile", default="root_manager")
    args = parser.parse_args()
    print(
        json.dumps(
            inspect(args.project, config=args.config, catalog=args.catalog, profile=args.profile),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
