from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').is_file() and (p / 'runtime').is_dir())
OUT = ROOT / "integration_evidence/acs-stage-agnostic-20261107-completion"
env = dict(os.environ, PYTHONPATH=str(ROOT / ".tmp/openapi-check"), PYTHONUTF8="1")
pack = "RFC_TEMP_SOURCE/ACS-Core-Stage-Agnostic-Revision-Pack-v1.1.0/"
commands = [
    [sys.executable, pack + "tools/verify_checksums.py"],
    [sys.executable, pack + "tools/validate_pack.py"],
    [sys.executable, "tools/runtime/export_client_contracts.py", "--check"],
    [sys.executable, "tools/runtime/export_sdk_runtime_contracts.py", "--check"],
    [sys.executable, "tools/runtime/export_p1_openapi.py", "--check"],
    [sys.executable, "-m", "ruff", "check", "runtime/communication_http.py",
     "runtime_tests/test_communication_http_auth.py", "runtime_tests/test_communication_p2_exact_scenarios.py",
     "runtime_tests/test_communication_commit_crash.py", "runtime_tests/test_communication_installed_maintenance.py",
     "runtime_tests/test_communication_attachment_ssrf.py"],
    ["git", "diff", "--check", "--", "runtime/communication_http.py", "runtime_tests/test_communication_http_auth.py"],
]
record = {"started_at": datetime.now(UTC).isoformat(), "checks": []}
with (OUT / "static-verification.log").open("w", encoding="utf-8") as log:
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                encoding="utf-8", errors="replace", check=False, timeout=60)
        log.write(json.dumps(command) + "\n" + result.stdout + "\n")
        record["checks"].append({"command": command, "returncode": result.returncode})
record["completed_at"] = datetime.now(UTC).isoformat()
(OUT / "static-verification.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"checks": len(record["checks"]), "failed": sum(x["returncode"] != 0 for x in record["checks"])}))
raise SystemExit(any(x["returncode"] for x in record["checks"]))
