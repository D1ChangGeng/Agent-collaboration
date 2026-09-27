#!/usr/bin/env python3
"""Read back the setup-only bootstrap profile in fresh processes.

This produces evidence, never a Runtime or cross-machine support decision.
Output contains local paths and belongs in an ignored private evidence directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root: Path) -> dict[str, dict]:
    paths = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=root
    ).decode("utf-8").split("\0")
    result = {}
    for name in paths:
        if not name:
            continue
        path = root / name
        if path.is_symlink():
            result[name] = {"symlink": os.readlink(path)}
        elif path.is_file():
            result[name] = {"bytes": path.stat().st_size, "sha256": digest(path)}
        else:
            result[name] = {"state": "missing"}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--management", default="agent-collabration")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-tests", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    management = (root / args.management).resolve(strict=True)
    management.relative_to(root)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        parser.error("output must be a new empty directory; preserve prior evidence")

    before = inventory(root)
    results = []

    def run(name: str, command: list[str], timeout: int = 120) -> dict:
        started = datetime.now(timezone.utc).isoformat()
        try:
            completed = subprocess.run(
                command, cwd=root, capture_output=True, timeout=timeout,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            raw = completed.stdout + b"\n--- stderr ---\n" + completed.stderr
            code = completed.returncode
        except subprocess.TimeoutExpired as exc:
            raw = (exc.stdout or b"") + b"\n--- timeout stderr ---\n" + (exc.stderr or b"")
            code = None
        path = output / f"{name}.log"
        path.write_bytes(raw)
        result = {
            "scenario_id": name, "command": command, "started_at": started,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "exit_code": code, "status": "passed" if code == 0 else "blocked",
            "raw_output": path.name, "sha256": digest(path),
            "observer": "local-management-subprocess", "evidence_class": "directly_verified",
        }
        results.append(result)
        return result

    run("git-state", ["git", "status", "--porcelain=v1", "--branch"])
    run("git-head", ["git", "rev-parse", "HEAD"])
    run("python", [sys.executable, "--version"])
    run("setup-version", [sys.executable, "-c", "from pathlib import Path; print(Path('VERSION').read_text().strip())"])
    run("skill-validate", [sys.executable, "scripts/validate_skill.py"])
    run("repository-validate", [sys.executable, "scripts/project_setup.py", "validate", "--root", str(root)])
    run("workspace-validate", [sys.executable, "scripts/project_setup.py", "workspace", "validate", "--root", str(management)])
    run("workspace-upgrade-dry-run", [sys.executable, "scripts/project_setup.py", "workspace", "upgrade", "--root", str(management), "--dry-run"])
    run("route-validate", [sys.executable, "scripts/project_setup.py", "route", "validate", "--workspace", str(management), "--path", "routes/collaboration-runtime"])
    if args.include_tests:
        run("setup-regression-tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], timeout=600)
    after = inventory(root)
    changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    (output / "preservation-inventory.json").write_text(json.dumps(before, indent=2) + "\n", encoding="utf-8")
    manifest = json.loads((management / ".agents/manifest.json").read_text(encoding="utf-8"))
    setup_version = (root / "VERSION").read_text().strip()
    report = {
        "schema_version": "bootstrap-evidence/1",
        "profile": f"{platform.system().lower()}-source-setup-{setup_version}",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "machine": platform.node(), "os": platform.platform(),
        "source_root": str(root), "setup_surface": "explicit-source-cli",
        "installed_skill_discovery": "not_measured", "setup_version": setup_version,
        "workspace_schema": manifest["schema_version"], "root_id": manifest["root_id"],
        "authority": "git-source-observation", "runtime_domain_authority": "not_run",
        "policy": "setup-only-readback", "permissions": {
            "source_read": os.access(root, os.R_OK), "source_write": os.access(root, os.W_OK),
            "observed_write": "private-evidence-output", "background_autostart": "not_enabled_by_audit",
            "credential_values_read": False,
        },
        "config_refs": {p: digest(management / p) for p in (".agents/config.yaml", ".agents/settings.yaml", ".agents/manifest.json")},
        "checks": results, "tracked_file_count": len(before), "preservation_changes": changed,
        "gate": "passed" if not changed and all(r["status"] == "passed" for r in results) else "blocked",
        "scope_limit": "setup source, schema, configuration digests and fresh-process checks only",
        "p1_runtime_gate": "not_run", "p2_cross_machine_gate": "not_run",
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": report["gate"], "checks": len(results), "preserved_files": len(before), "changed": changed, "report": str(output / 'report.json')}))
    return 0 if report["gate"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
