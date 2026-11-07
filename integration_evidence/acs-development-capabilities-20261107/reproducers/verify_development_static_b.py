from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / "integration_evidence/acs-development-capabilities-20261107"
env = dict(os.environ, PYTHONPATH=str(root / ".tmp/openapi-check"), PYTHONUTF8="1")
pack = "RFC_TEMP_SOURCE/ACS-Core-Stage-Agnostic-Revision-Pack-v1.1.0/"
source = ["runtime/" + p + ".py" for p in (
    "codex_driver", "opencode_driver", "native_restore", "native_restore_origin", "receiver_lifecycle",
    "receiver_lifecycle_contract", "receiver_lifecycle_capacity", "receiver_lifecycle_node", "receiver_lifecycle_issuance",
    "communication_message_wake", "communication_message_restore", "receiver", "receiver_models", "receiver_delivery",
    "remote_endpoint", "native_provider_registry", "remote_native_source", "communication_client_native_source", "orca_receiver_backend")]
source += ["runtime_deployment/receiver_lifecycle.py", "runtime_deployment/receiver_authority.py"]
source += ["runtime_tests/" + p + ".py" for p in (
    "test_receiver_cold_restore", "test_native_cold_restore_transport", "test_native_restore_origin",
    "test_message_cold_restore_pg", "test_receiver_restore_factory_pg", "test_remote_native_source",
    "test_remote_native_source_tls", "test_orca_receiver_backend", "test_communication_remote_source_pg", "test_receiver_lifecycle_wire_pg")]
checks = [[sys.executable, pack + "tools/verify_checksums.py"], [sys.executable, pack + "tools/validate_pack.py"]]
checks += [[sys.executable, p, "--check"] for p in (
    "tools/runtime/export_client_contracts.py", "tools/runtime/export_receiver_contracts.py",
    "tools/runtime/export_sdk_runtime_contracts.py", "tools/runtime/export_p1_openapi.py")]
checks += [[sys.executable, "-m", "ruff", "check", *source], ["git", "diff", "--check", "--", *source]]
prior_sdk = json.loads((root / "integration_evidence/acs-stage-agnostic-20261107-completion/sdk-verification.json").read_text())
checks += [entry["command"] for entry in prior_sdk["checks"]]
record = {"started_at": datetime.now(UTC).isoformat(), "checks": []}
with (out / "development-static-b.log").open("w", encoding="utf-8") as log:
    for command in checks:
        result = subprocess.run(command, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", timeout=120, check=False)
        log.write(json.dumps(command) + "\n" + result.stdout + "\n")
        log.flush()
        record["checks"].append({"command": command, "returncode": result.returncode})
record["completed_at"] = datetime.now(UTC).isoformat()
(out / "development-static-b.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
wheel = root / ".tmp/development-capabilities-wheel/agent_collaboration_runtime-2.3.1-py3-none-any.whl"
installed = root / ".tmp/development-capabilities-installed"
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
files = {}
with zipfile.ZipFile(wheel) as archive:
    for name in archive.namelist():
        if name.startswith(("runtime/", "runtime_deployment/")) and not name.endswith("/"):
            hashed = hashlib.sha256(archive.read(name)).hexdigest()
            assert digest(root / name) == hashed == digest(installed / name), name
            files[name] = hashed
facts = {"schema_version": "acs-candidate-package-facts/1", "observed_at": datetime.now(UTC).isoformat(),
    "wheel": wheel.relative_to(root).as_posix(), "sha256": digest(wheel), "version": "2.3.1 candidate",
    "installation": installed.relative_to(root).as_posix(), "installation_scope": "temporary target; existing services untouched",
    "source_and_installed_package_match": True, "package_files": files}
(out / "package-facts.json").write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"checks": len(checks), "failed": sum(x["returncode"] != 0 for x in record["checks"]), "package_files": len(files)}))
raise SystemExit(any(x["returncode"] for x in record["checks"]))

