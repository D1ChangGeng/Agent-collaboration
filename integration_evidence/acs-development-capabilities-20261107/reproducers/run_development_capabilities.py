"""Scoped, credential-redacted local acceptance for the v1.1 continuation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.runtime.cross_harness_verify import TEST_CONTAINER, isolated_environment

OUT = ROOT / "integration_evidence/acs-development-capabilities-20261107"


def manifest():
    files = sorted(p for folder in ("runtime", "runtime_deployment", "runtime_tests", "sdk")
                   for p in (ROOT / folder).rglob("*")
                   if p.is_file() and p.suffix in {".py", ".sql", ".json", ".ts", ".mjs"})
    files += [ROOT / p for p in ("pyproject.toml", "uv.lock", "tools/runtime/cross_harness_verify.py",
                                ".tmp/run_development_capabilities.py")]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--pg", action="store_true")
    parser.add_argument("targets", nargs="+")
    args = parser.parse_args()
    if any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in args.name):
        parser.error("use a simple evidence name")
    OUT.mkdir(exist_ok=True)
    result_file = OUT / (args.name + ".json")
    if result_file.exists():
        parser.error("evidence already exists; choose a fresh name")
    environment = isolated_environment(TEST_CONTAINER) if args.pg else dict(os.environ)
    for name in tuple(environment):
        if (name.startswith("ACS_REAL_") or name in {"ACS_NATIVE_FACTORY_TEST", "ACS_EXECUTE_ISOLATED_NATIVE_MODEL_TEST"}
                or (not args.pg and name in {"ACS_COMMUNICATION_TEST_DSN", "ACS_P1_DSN"})):
            environment.pop(name)
    environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    xml = OUT / (args.name + ".xml")
    log = OUT / (args.name + ".log")
    command = [sys.executable, "-m", "pytest", *args.targets, "-o", "addopts=", "-q", "-ra", "--tb=short",
               "--basetemp=" + str(ROOT / ".tmp" / ("capability-development-" + args.name)), "--junitxml=" + str(xml)]
    result = {"schema_version": "acs-local-acceptance/1", "started_at": datetime.now(UTC).isoformat(),
              "command": command, "evidence_class": "E2_controlled_integration" if args.pg else "E1_components",
              "isolated_database": "acs_communication_test" if args.pg else None,
              "actual_model_invocation": False, "production_access": False,
              "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
              "fixed_before": manifest()}
    result_file.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    secrets = [environment[name] for name in ("ACS_COMMUNICATION_TEST_DSN", "ACS_P1_DSN") if environment.get(name)]
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        for line in process.stdout:
            for secret in secrets:
                line = line.replace(secret, "<redacted-test-dsn>")
            stream.write(line)
            stream.flush()
        result["returncode"] = process.wait()
    result.update(completed_at=datetime.now(UTC).isoformat(), fixed_after=manifest())
    result["changed_sources"] = sorted(k for k in result["fixed_before"].keys() | result["fixed_after"].keys()
                                       if result["fixed_before"].get(k) != result["fixed_after"].get(k))
    if xml.exists():
        suites = ElementTree.parse(xml).getroot()
        cases = list(suites.iter("testcase"))
        result["counts"] = {"tests": len(cases), "failed": sum(c.find("failure") is not None for c in cases),
                            "errors": sum(c.find("error") is not None for c in cases),
                            "skipped": sum(c.find("skipped") is not None for c in cases)}
        result["counts"]["passed"] = len(cases) - sum(result["counts"][k] for k in ("failed", "errors", "skipped"))
    result_file.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result.get(k) for k in ("returncode", "counts", "changed_sources")}))
    return result["returncode"] or bool(result["changed_sources"])


if __name__ == "__main__":
    raise SystemExit(main())
