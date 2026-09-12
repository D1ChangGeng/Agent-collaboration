"""Prepare and audit a NOT_RUN P2 execution workspace; never perform Gate faults."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

INVENTORY_SCHEMA = "acs-p2-readonly-inventory/2"
WORKSPACE_SCHEMA = "acs-p2-runner-workspace/1"
MANIFEST_SCHEMA = "acs-p2-runner-manifest/1"
REQUIRED_EVIDENCE = (
    "command_ids", "operation_ids", "message_ids", "event_ids", "receipts",
    "raw_outputs", "fault_injection", "source_readback", "artifact_readback",
    "effect_readback", "recovery_trace", "observer", "owner", "unresolved_items",
)
FAULTS = {
    "P2-CODEX-TWO-MACHINE-LOOP": "bidirectional TLS receiver delivery and response",
    "P2-CODEX-UI-EXIT": "exit one Codex UI after durable marker",
    "P2-CODEX-NETWORK-PARTITION": "controlled receiver route partition",
    "P2-CODEX-NODE-RESTART": "restart enrolled Node under supervisor",
    "P2-CODEX-SESSION-REPLACEMENT": "replace receiving Codex session",
    "P2-CODEX-ACK-LOSS": "drop receiver acknowledgement after commit",
    "P2-CODEX-STALE-OWNER": "replace lease owner and exercise fencing",
    "P2-CODEX-UNCERTAIN-EFFECT": "interrupt after protected effect marker",
    "P2-OPENCODE-CROSS-HARNESS-LOOP": "Codex to OpenCode and response loop",
    "P2-OPENCODE-CAPABILITY-PROBE": "expire and refresh scoped capability observation",
    "P2-OPENCODE-TRANSPORT-SWITCH": "fail active transport then resolve another provider",
    "P2-OPENCODE-LIFECYCLE-RECOVERY": "replace OpenCode process/session after dispatch",
    "P2-OPENCODE-PERMISSION-DATA-POLICY": "deny revoked scope and protected data access",
    "P2-OPENCODE-LATE-DEDUP": "deliver late duplicate after successful response",
    "P2-HUMAN-BRIDGE-RECOVERY": "exhaust automatic paths, manual return, successful reprobe race",
    "P2-SOURCE-ARTIFACT-EFFECT-READBACK": "mutate and read back source/artifact/effect boundaries",
}
SECRET = re.compile(
    r"(?i)\"?(password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|authorization)\"?\s*[:=]"
)


class HarnessError(RuntimeError):
    pass


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def write_json(path: Path, value: object) -> None:
    write_atomic(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode() + b"\n")


def read_json(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) > 4 * 1024 * 1024 or SECRET.search(data.decode("utf-8", errors="replace")):
        raise HarnessError("inventory contains secret-like material")
    try:
        value = json.loads(data)
    except json.JSONDecodeError as error:
        raise HarnessError("invalid JSON") from error
    if not isinstance(value, dict):
        raise HarnessError("JSON object required")
    return value


def contract_scenarios(contract: dict[str, Any]) -> dict[str, list[str]]:
    gates = contract.get("gates", {})
    result = {
        gate: gates.get(gate, {}).get("scenarios")
        for gate in ("P2-CODEX", "P2-OPENCODE")
    }
    if (not all(isinstance(value, list) for value in result.values())
            or any(len(value) != 8 or len(set(value)) != 8 for value in result.values())
            or set(result["P2-CODEX"] + result["P2-OPENCODE"]) != set(FAULTS)):
        raise HarnessError("P2 contract scenario set changed")
    return result


def validate_inventory(inventory: dict[str, Any]) -> None:
    if inventory.get("schema_version") != INVENTORY_SCHEMA:
        raise HarnessError("invalid inventory schema")
    machines = inventory.get("machines")
    if not isinstance(machines, list) or len(machines) != 2:
        raise HarnessError("exactly two observed Machines required")
    ids = [machine.get("machine_id") for machine in machines]
    if (len(set(ids)) != 2 or set(ids) != {"windows-local", "linux-1302-1"}
            or {(machine.get("machine_id"), machine.get("host_label")) for machine in machines}
            != {("windows-local", "Local"), ("linux-1302-1", "1302-1")}
            or {machine.get("os_family") for machine in machines} != {"windows", "linux"}):
        raise HarnessError("two process labels cannot substitute for two physical Machines")
    for machine in machines:
        if any(field in machine for field in ("source", "host_fingerprint_sha256", "versions", "observed_at")):
            raise HarnessError("stored inventory cannot claim a current runtime observation")
        if machine.get("runtime_observation") != "not_run":
            raise HarnessError("machine facts must be reobserved by the execution run")
        if machine.get("credentials_present") is not False:
            raise HarnessError("credentials must not enter P2 inventory")
    auth = inventory.get("authentication")
    if not isinstance(auth, dict) or auth.get("login_attempted_by_harness") is not False:
        raise HarnessError("harness must not initiate login")


def blockers(inventory: dict[str, Any]) -> list[str]:
    result = ["both physical Machines require runtime reobservation on one exact source commit"]
    if inventory.get("p1_gate_status") not in {"passed", "supported"}:
        result.append("P1 Gate has not passed")
    if inventory["authentication"].get("linux_codex_login") is not True:
        result.append("Linux Codex login is unavailable")
    services = inventory.get("services", {})
    if services.get("linux_receiver") != "active" or services.get("linux_node") != "active":
        result.append("Linux receiver/Node supervised services are not active")
    return result


def runtime_observation(source_root: Path) -> dict[str, Any]:
    def git(*args):
        result = subprocess.run(
            ["git", *args], cwd=source_root, capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()

    machine = ""
    for path in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
        try:
            machine = path.read_text(encoding="ascii").strip()
            if machine:
                break
        except OSError:
            continue
    facts = {
        "schema_version": "acs-p2-runtime-observation/1",
        "observed_at": datetime.now(UTC).isoformat(),
        "source_root": str(source_root.resolve()),
        "source_commit": git("rev-parse", "HEAD"),
        "source_tree": git("rev-parse", "HEAD^{tree}"),
        "tracked_status": git("status", "--porcelain", "--untracked-files=no"),
        "host_fingerprint_sha256": sha(canonical({
            "hostname": platform.node(), "machine_id": machine,
            "architecture": platform.machine(),
        })),
    }
    if facts["tracked_status"]:
        raise HarnessError("P2 runtime observation requires a clean tracked source")
    return facts


def gate_record(gate: str, scenarios: list[str], phase_blockers: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "acs-gate-record/1",
        "gate": gate,
        "status": "not_run",
        "scenarios": [
            {
                "scenario_id": scenario,
                "status": "not_run",
                "fault": FAULTS[scenario],
                "required_evidence_fields": list(REQUIRED_EVIDENCE),
                "blockers": phase_blockers,
            }
            for scenario in scenarios
        ],
    }


def ensure_external(output: Path, source_root: Path) -> None:
    candidate = output.resolve(strict=False)
    source = source_root.resolve(strict=True)
    try:
        candidate.relative_to(source)
    except ValueError:
        return
    raise HarnessError("P2 run directory must remain outside the formal source checkout")


def build_manifest(root: Path, inventory: dict[str, Any]) -> dict[str, Any]:
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "RUN-MANIFEST.json":
            files[path.relative_to(root).as_posix()] = sha(path.read_bytes())
    return {
        "schema_version": MANIFEST_SCHEMA,
        "status": "not_run",
        "created_at": datetime.now(UTC).isoformat(),
        "inventory_sha256": sha(canonical(inventory)),
        "files": files,
    }


def initialize(inventory_path: Path, contract_path: Path, output: Path, source_root: Path) -> dict[str, Any]:
    ensure_external(output, source_root)
    if output.exists():
        raise HarnessError("output already exists")
    inventory = read_json(inventory_path)
    contract = read_json(contract_path)
    validate_inventory(inventory)
    scenarios = contract_scenarios(contract)
    blocked = blockers(inventory)
    observed = runtime_observation(source_root)
    output.mkdir(parents=True)
    write_json(output / "inventory.json", inventory)
    write_json(output / "runtime-observation.json", observed)
    workspace = {
        "schema_version": WORKSPACE_SCHEMA,
        "status": "not_run",
        "execution_order": ["P1", "P2-CODEX", "P2-OPENCODE"],
        "blockers": blocked,
        "credentials_copied": False,
        "login_attempted": False,
        "local_runtime_observation": "runtime-observation.json",
        "remote_runtime_reobservation": "required",
    }
    write_json(output / "workspace.json", workspace)
    write_json(output / "P2-CODEX.json", gate_record("P2-CODEX", scenarios["P2-CODEX"], blocked))
    opencode_blockers = blocked + ["P2-CODEX prerequisite has not passed"]
    write_json(output / "P2-OPENCODE.json", gate_record("P2-OPENCODE", scenarios["P2-OPENCODE"], opencode_blockers))
    write_json(output / "RUN-MANIFEST.json", build_manifest(output, inventory))
    return workspace


def audit(output: Path, contract_path: Path) -> None:
    contract = read_json(contract_path)
    scenarios = contract_scenarios(contract)
    manifest = read_json(output / "RUN-MANIFEST.json")
    if manifest.get("schema_version") != MANIFEST_SCHEMA or manifest.get("status") != "not_run":
        raise HarnessError("P2 skeleton manifest cannot claim execution")
    observed = read_json(output / "runtime-observation.json")
    source_root = Path(observed.get("source_root", ""))
    current = runtime_observation(source_root)
    for field in ("source_commit", "source_tree", "host_fingerprint_sha256"):
        if current[field] != observed.get(field):
            raise HarnessError("P2 runtime source or Machine observation changed")
    for name, expected in manifest.get("files", {}).items():
        path = output / name
        if not path.is_file() or sha(path.read_bytes()) != expected:
            raise HarnessError("P2 workspace hash mismatch")
    for gate, expected_ids in scenarios.items():
        record = read_json(output / f"{gate}.json")
        if record.get("status") != "not_run":
            raise HarnessError("P2 harness skeleton cannot promote a Gate")
        actual = [item.get("scenario_id") for item in record.get("scenarios", [])]
        if actual != expected_ids or any(item.get("status") != "not_run" for item in record["scenarios"]):
            raise HarnessError("P2 scenario set or status changed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init")
    init.add_argument("--inventory", type=Path, required=True)
    init.add_argument("--output", type=Path, required=True)
    init.add_argument("--source-root", type=Path, required=True)
    check = sub.add_parser("audit")
    check.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "init":
            result = initialize(args.inventory, args.contract, args.output, args.source_root)
            print(json.dumps(result, sort_keys=True))
        else:
            audit(args.output, args.contract)
            print(json.dumps({"status": "not_run", "audit": "passed"}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, HarnessError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)[:300]}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
