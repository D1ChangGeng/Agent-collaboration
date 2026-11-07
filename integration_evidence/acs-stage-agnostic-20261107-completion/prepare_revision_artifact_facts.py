from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').is_file() and (p / 'runtime').is_dir())
OUT = ROOT / "integration_evidence/acs-stage-agnostic-20261107-completion"
PRIOR = ROOT / "integration_evidence/acs-stage-agnostic-20261106"
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
now = datetime.now(UTC).isoformat()
wheel = ROOT / ".tmp/revision-completion-wheel-final/agent_collaboration_runtime-2.3.1-py3-none-any.whl"
installed = ROOT / ".tmp/revision-completion-installed-final"
files = {}
with zipfile.ZipFile(wheel) as archive:
    for name in archive.namelist():
        if name.startswith(("runtime/", "runtime_deployment/")) and not name.endswith("/"):
            expected = hashlib.sha256(archive.read(name)).hexdigest()
            assert digest(ROOT / name) == expected == digest(installed / name), name
            files[name] = expected
    entrypoints = archive.read("agent_collaboration_runtime-2.3.1.dist-info/entry_points.txt").decode()
    assert "acs-project-runtime = runtime.project_entry:main" in entrypoints
package = {"schema_version": "acs-candidate-package-facts/1", "observed_at": now,
    "wheel": wheel.relative_to(ROOT).as_posix(), "sha256": digest(wheel), "version": "2.3.1",
    "installation": installed.relative_to(ROOT).as_posix(), "installation_scope": "temporary --target; existing services untouched",
    "build_command": "uv build --wheel --offline --out-dir .tmp/revision-completion-wheel-final",
    "install_command": "uv pip install --target .tmp/revision-completion-installed-final --no-deps --offline --cache-dir .tmp/uv-completion-cache .tmp/revision-completion-wheel-final/agent_collaboration_runtime-2.3.1-py3-none-any.whl",
    "source_and_installed_package_match": True, "package_files": files,
    "installed_service_test": "p0-p1-final.xml::test_t090_installed_wheel_maintains_committed_message_after_its_client_process_exits"}
(OUT / "package-facts.json").write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")

driver_paths = ["runtime/codex_driver.py", "runtime/opencode_driver.py", "runtime/native_handoff.py",
    "runtime/receiver_lifecycle_node.py", "runtime/receiver_lifecycle_issuance.py", "runtime_deployment/receiver_codex.py",
    "runtime_deployment/receiver_opencode.py", "runtime_deployment/receiver_lifecycle.py"]
records = []
for name, harness, version, os_name, capability in [
    ("actual-native-lifecycle-pg-g", "Codex", "0.166.0", "Windows", "signed prepare; lost-start ACK readback; same-owned-session warm resume; zero model prompts"),
    ("opencode-wsl-lifecycle-pg-b", "OpenCode", "1.18.34", "Ubuntu WSL on the same Windows hardware", "signed receiver lifecycle and actual existing session/MCP; zero model prompts"),
]:
    path = PRIOR / "native-history-contract-20261107" / (name + ".json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["returncode"] == 0 and not data["changed_sources"]
    assert all(digest(ROOT / p) == data["fixed_before"][p] for p in driver_paths)
    drift = [p for p, h in data["fixed_before"].items() if (ROOT / p).is_file() and digest(ROOT / p) != h]
    records.append({"capability": capability, "harness": harness, "version": version, "os": os_name,
        "host": "local isolated development capacity", "auth_mode": "owner/native",
        "adapter_version": {p: digest(ROOT / p) for p in driver_paths}, "runtime_version": "2.3.1 dirty candidate",
        "evidence_class": "native_protocol", "actual_command_and_artifacts": {"command": data["command"], "result": path.relative_to(ROOT).as_posix()},
        "result": "passed", "current_scope": "Exact current Native/lifecycle stack hashes. Does not requalify changed Core wait code by itself.",
        "changed_product_files_since_run": [p for p in drift if p.startswith(("runtime/", "runtime_deployment/"))],
        "current_Core_wait_coverage": "E4 cross-Harness result-e with reviewed unrelated HTTP-only delta, plus p0-p1-final wait connection/revocation/disconnect cases"})
native_path = PRIOR / "native-agent-e2e-20261107/native-e2e-e.json"
native = json.loads(native_path.read_text())
assert native["returncode"] == 0 and not native["changed_sources"] and native["owned_tree_stopped"]
native_delta = [p for p,h in native["fixed_before"].items() if digest(ROOT / p) != h]
assert set(native_delta) <= {"runtime/communication_http.py", "runtime_tests/test_communication_http_auth.py"}
records.append({"capability": "ordinary independent A to B; one receiving Native prompt; explicit reply_to and actual satisfied MCP wait",
    "harness": "Codex -> OpenCode", "version": "0.166.0 -> 1.18.34", "os": "Windows -> Ubuntu WSL",
    "host": "same physical hardware, separate OS/processes", "auth_mode": "owner/native",
    "adapter_version": {p: digest(ROOT / p) for p in driver_paths}, "runtime_version": "2.3.1 dirty candidate",
    "evidence_class": "independent_agent_e2e", "actual_command_and_artifacts": native_path.relative_to(ROOT).as_posix(),
    "result": "passed", "all_901_original_source_files_match_current": not native_delta,
    "reviewed_source_delta": native_delta,
    "retention_scope": "Native/signed-receiver/Project-MCP send/reply/wait mechanisms remain identical; ordinary HTTP facade default-keyword compatibility is separately requalified. No single new E4 run is claimed.",
    "cleanup": "Windows owned Job empty; WSL owned process group empty; subtree_containment=false on WSL",
    "new_model_call_in_this_continuation": False})
codex_path = PRIOR / "native-agent-e2e-20261107/native-e2e-b.json"
codex = json.loads(codex_path.read_text())
assert codex["returncode"] == 0 and codex["owned_tree_stopped"] and not codex["changed_sources"]
assert all(digest(ROOT / p) == codex["fixed_before"][p] for p in driver_paths)
codex_facts_path = PRIOR / "native-agent-e2e-20261107/actor-evidence-b/invoke-0d90cf25d3a7/native-invoke-facts.json"
codex_facts = json.loads(codex_facts_path.read_text())
assert len(codex_facts["messages"]) == 2 and len(codex_facts["reply_relationships"]) == 1
assert codex_facts["native_turn_start_count"] == 1 and codex_facts["production_receiver_factory"]
records.append({"capability": "actual Codex receiving factory; independent ordinary B replies through its own MCP; one Native input",
    "harness": "Codex -> Codex", "version": "0.166.0", "os": "Windows", "host": "local isolated development capacities",
    "auth_mode": "owner/native", "adapter_version": {p: digest(ROOT / p) for p in driver_paths},
    "runtime_version": "2.3.1 dirty candidate", "evidence_class": "independent_agent_e2e",
    "actual_command_and_artifacts": {"result": codex_path.relative_to(ROOT).as_posix(), "facts": codex_facts_path.relative_to(ROOT).as_posix()},
    "result": "passed", "facts_sha256": digest(codex_facts_path),
    "scope_limit": "Retains receiving/input/explicit-reply evidence on identical Native stack hashes. Core wait changed later; b alone does not qualify the final wait path or prove a single combined later run.",
    "changed_product_files_since_run": [p for p,h in codex["fixed_before"].items() if p.startswith(("runtime/", "runtime_deployment/")) and digest(ROOT / p) != h],
    "current_wait_evidence": "Separate exact-byte full cross-Harness E4 result-e and current PG wait cases",
    "new_model_call_in_this_continuation": False})
for capability, harness, reason, result in [
    ("actual Host integration", "Orca", "No installed authorized Orca Host extension was exercised. P1 delegation/typed-unavailable contracts are separately verified.", "blocked"),
    ("physical two-machine Native exchange", "Codex/OpenCode", "Current Native evidence is Windows/WSL on one physical machine; no isolated second machine was qualified for this dirty candidate.", "unverified"),
    ("Shared/restricted Windows Native", "Codex", "No current E3/E4 qualification for these profiles; owner/native results do not widen their permissions or reviewed version allowlist.", "unverified"),
    ("automatic stopped-process cold resume", "Codex/OpenCode", "Production recovery requires the original owned process/session/generation evidence. Separate empty-session CLI probing is not an installed safe recovery path; missing proof stays unknown/unsupported.", "unsupported_verified"),
    ("safe Native enqueue/steer", "Codex/OpenCode", "No attested enqueue profile in the current support set; busy is deferred and queue/steer unsupported.", "unsupported_verified"),
    ("Native binary attachment injection", "Codex/OpenCode", "HTTP/CAS attachment service is verified; Native attachment delivery is explicitly held unsupported without changing Inbox facts.", "unsupported_verified"),
    ("additional full Driver", "Claude/Pi", "Conditional extension has no exact installed/versioned/authorized target in this package's 25 change items. Typed fallback is retained; no support is advertised.", "unverified"),
]:
    records.append({"capability": capability, "harness": harness, "version": "not-qualified", "os": "not-qualified",
        "host": "not-qualified", "auth_mode": "not-qualified", "adapter_version": "current source candidate",
        "runtime_version": "2.3.1 dirty candidate", "evidence_class": "controlled_integration_or_scope_record",
        "actual_command_and_artifacts": "acceptance-audit.json", "result": result, "reason": reason})
(OUT / "qualification-matrix.json").write_text(json.dumps({"schema_version": "acs-qualification-revision/1",
    "observed_at": now, "records": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"package_files": len(files), "wheel_sha256": digest(wheel), "qualification_records": len(records)}))
