"""Read-only installation and project readiness report for ACS."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
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


def runtime_readback(config: Path, catalog: Path, profile: str, *, deep: bool = True, project_id: str | None = None) -> dict:
    try:
        from runtime.project_service import ProjectService
        from runtime.project_source import ProjectSources
        from runtime.surface_config import configured_service

        contract = json.loads(catalog.read_text(encoding="utf-8"))
        with configured_service(config) as (service, settings), ExitStack() as resources:
            credential = settings.credential()
            service.authenticate(credential)
            providers = settings.artifact_configs()
            sources = None
            if providers and any(item.authorized_source_roots for item in providers):
                roots = (
                    providers[0].authorized_source_roots
                    if len(providers) == 1
                    else {
                        item.scope_id: item.authorized_source_roots
                        for item in providers
                        if item.authorized_source_roots
                    }
                )
                sources = ProjectSources(service.authority._artifact_store, roots)
                resources.callback(sources.close)
            projects = ProjectService(service, contract, profile=profile, sources=sources)
            _, snapshot, _ = projects.execute("read_profile", {}, credential)
            _, found, _ = projects.execute("list_projects", {}, credential)
            contexts = []
            for project in found["items"] if deep else []:
                if project_id is not None and project["project_id"] != project_id:
                    continue
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
    harnesses: list[str] | None = None,
    deep: bool = True,
    tools_snapshot: dict | None = None,
    project_id: str | None = None,
) -> dict:
    started = time.monotonic()
    selected = ["codex", "opencode"] if harnesses is None else harnesses
    probes = {"git": ("--version",), "uv": ("--version",),
              "docker": ("compose", "version"),
              **{name: ("--version",) for name in selected}}
    if tools_snapshot is None:
        with ThreadPoolExecutor(max_workers=len(probes)) as pool:
            futures = {name: pool.submit(command_version, name, *args) for name, args in probes.items()}
            tools = {name: future.result() for name, future in futures.items()}
    else:
        tools = dict(tools_snapshot)
    report: dict = {
        "schema_version": "acs-install-readiness/1",
        "platform": sys.platform,
        "source_backend": {
            "available": sys.platform.startswith("linux"),
            "required_host": "linux",
        },
        "python": sys.version.split()[0],
        "source_root": str(ROOT),
        "tools": tools,
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
            config, catalog or ROOT / "docs/runtime/p2-mcp-tool-contract.json", profile, deep=deep or project_id is not None, project_id=project_id
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
    report["tool_probes_reused"] = tools_snapshot is not None
    report["validation_scope"] = "selected_project" if project_id else "project_contexts" if deep else "machine"
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--profile", default="root_manager")
    parser.add_argument("--deep", action="store_true", help="Also load every visible project context")
    parser.add_argument("--project-id", help="Load just this registered project context")
    parser.add_argument("--harness", nargs="*", choices=("codex", "opencode"))
    args = parser.parse_args()
    print(
        json.dumps(
            inspect(args.project, config=args.config, catalog=args.catalog, profile=args.profile,
                    deep=args.deep, project_id=args.project_id, harnesses=args.harness),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
