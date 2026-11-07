from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').is_file() and (p / 'runtime').is_dir())
OUT = ROOT / "integration_evidence/acs-stage-agnostic-20261107-completion"
paths = sorted(p for p in (ROOT / "sdk").rglob("*") if p.is_file())
paths.append(ROOT / "runtime/client_models.schema.json")
hashes = lambda: {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
result = {"started_at": datetime.now(UTC).isoformat(), "before": hashes(), "checks": []}
commands = [
    ("sdk", ["node", "--test", "sdk/tests/*.test.mjs"]),
    ("typescript", ["node", ".tmp/tsc-package/compiler/package/bin/tsc", "--noEmit", "--strict", "--target", "es2022",
        "--module", "esnext", "--moduleResolution", "bundler", "--allowImportingTsExtensions", "--lib", "es2022,dom,dom.iterable",
        *[p.relative_to(ROOT).as_posix() for p in sorted((ROOT / "sdk").glob("*.ts"))]]),
]
for name, command in commands:
    with (OUT / (name + ".log")).open("w", encoding="utf-8") as stream:
        process = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=180, check=False)
    result["checks"].append({"name": name, "command": command, "returncode": process.returncode})
result.update(completed_at=datetime.now(UTC).isoformat(), after=hashes())
result["source_unchanged"] = result["before"] == result["after"]
(OUT / "sdk-verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"checks": result["checks"], "source_unchanged": result["source_unchanged"]}))
raise SystemExit(any(c["returncode"] for c in result["checks"]) or not result["source_unchanged"])
