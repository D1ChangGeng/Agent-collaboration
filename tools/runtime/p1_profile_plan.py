"""Generate the P1 runner plan from a securely bound loopback provider profile."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from tools.runtime.p1_profile_probe import (
    EVIDENCE_FIELDS,
    KINDS,
    ScenarioCatalog,
    _secure_profile,
    _source_identity,
    availability,
)


def build_plan(profile_path: Path, *, sandbox_profile: str, expires_in: int = 3600):
    profile, profile_digest, _secrets = _secure_profile(profile_path)
    commit, _tree = _source_identity(Path(profile["source_root"]))
    available = availability(profile, commit)
    scenarios = {}
    for scenario in ScenarioCatalog.TESTS:
        if not available[scenario]["available"]:
            scenarios[scenario] = []
            continue
        commands = []
        for index, kind in enumerate(KINDS, start=1):
            commands.append({
                "command_id": f"{scenario.lower()}:{index}:{kind}",
                "kind": kind,
                "argv": [
                    profile["sandbox_python"], "/mnt/tools/runtime/p1_profile_probe.py", "run",
                    "--profile", sandbox_profile, "--scenario", scenario,
                    "--kind", kind, "--output", "/srv",
                ],
                "evidence_fields": list(EVIDENCE_FIELDS[kind]),
                "timeout_seconds": 900,
                "cwd": ".",
            })
        scenarios[scenario] = commands
    versions = profile["versions"]
    plan = {
        "schema_version": "acs-p1-gate-runner-plan/1",
        "profile": profile["profile"], "node_id": profile["node_id"],
        "engineer": "external-p1-probe-runner", "direction": profile["direction"],
        "expires_at": (datetime.now(UTC) + timedelta(seconds=expires_in)).isoformat(),
        "core_version": versions["core"],
        "temporal_version": versions["provider"]["temporal"],
        "postgresql_version": versions["database"]["postgresql"],
        "protocol_version": versions["protocol"],
        "credential_scope": "p1-loopback-provider:" + profile_digest,
        "policy": "owner-only-profile; loopback PG/Temporal; no formal Gate writes",
        "harness_versions": versions["harness"],
        "driver_versions": versions["driver"],
        "scenarios": scenarios, "prerequisites": {}, "review": {},
    }
    status = {
        "schema_version": "acs-p1-probe-plan-status/1",
        "source_commit": commit,
        "profile_digest": profile_digest,
        "runner_profile_mount": sandbox_profile,
        "runner_integration": (
            "pending Gate runner owner-only profile and reviewed runtime Python binds"
        ),
        "available_scenarios": [key for key, value in available.items() if value["available"]],
        "not_run": {key: value["reason"] for key, value in available.items()
                    if not value["available"]},
    }
    return plan, status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--sandbox-profile", default="/run/acs-p1/profile.json")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        plan, status = build_plan(args.profile, sandbox_profile=args.sandbox_profile)
        args.plan.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        args.status.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "prepared", "available": len(status["available_scenarios"]),
                          "not_run": len(status["not_run"])}))
        return 0
    except Exception as error:  # noqa: BLE001 - no profile values leave this boundary
        print(json.dumps({"status": "blocked", "error": type(error).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
