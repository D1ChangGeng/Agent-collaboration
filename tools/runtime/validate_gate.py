#!/usr/bin/env python3
"""Validate offline Gate completeness/integrity, never execution or authorization.

The selected contract and evidence directory are review inputs, not trust roots.
Digests and observer/reviewer labels cannot authenticate facts or subjects. Gate
references are relative to evidence_root; bootstrap logs are report-relative.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

UNKNOWN = {"unknown", "unverified", "not_run", "not-measured", "not_measured", "uncertain",
           "", "tbd", "n/a", "none", "null", "latest", "*", "any", "auto", "not_applicable"}
READBACKS = ("source_readback", "artifact_readback", "effect_readback", "recovery_trace")
IDS = ("command_ids", "operation_ids", "message_ids", "event_ids")
BOOTSTRAP_CHECKS = {"git-state", "git-head", "python", "setup-version", "skill-validate",
                    "repository-validate", "workspace-validate", "workspace-upgrade-dry-run", "route-validate"}
MAX_BYTES = 64 * 1024 * 1024
MAX_JSON_BYTES = 4 * 1024 * 1024


def known(value, depth=0):
    if depth > 12:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in UNKNOWN
    if isinstance(value, dict):
        return bool(value) and all(known(k, depth + 1) and known(v, depth + 1) for k, v in value.items())
    if isinstance(value, list):
        return bool(value) and all(known(v, depth + 1) for v in value)
    return False


def strings(value, nonempty=True):
    return (isinstance(value, list) and (bool(value) or not nonempty)
            and all(isinstance(v, str) and known(v) for v in value) and len(set(value)) == len(value))


def sha(value, length=64):
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{%d}" % length, value)) and value != "0" * length


def stamp(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.tzinfo is not None and result.utcoffset() is not None else None
    except (ValueError, OverflowError):
        return None


def binding_digest(binding):
    return hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def load_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    def constant(_):
        raise ValueError("nonfinite JSON number")
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("JSON input exceeds limit")
    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def no_alias(path):
    for component in (path, *path.parents):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
            raise ValueError("symlink/reparse path")


class GateValidator:
    def __init__(self, contract, root, now):
        self.contract, self.root, self.now = contract, root, now
        self.errors, self.active = [], set()

    def fail(self, where, message):
        self.errors.append(f"{where}: {message}")

    def reference(self, ref, where, directory=None, structured=False):
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or not sha(ref.get("sha256")):
            self.fail(where, "expected relative path and SHA-256 reference")
            return None
        for field in ("status", "evidence_state", "evidence_class"):
            if field in ref and ref[field] not in ("passed", "supported", "complete", "directly_verified"):
                self.fail(where, "stale, incomplete or unverified reference")
                return None
        if "expires_at" in ref and (stamp(ref["expires_at"]) is None or stamp(ref["expires_at"]) <= self.now):
            self.fail(where, "expired reference")
            return None
        try:
            name = ref["path"]
            path = Path(name)
            if not name or path.is_absolute() or ".." in path.parts or any(c in name for c in ("\\", ":", "\x00")):
                raise ValueError("path must be relative and contained")
            candidate = (directory or self.root) / path
            candidate.relative_to(self.root)
            no_alias(candidate)
            candidate = candidate.resolve(strict=True)
            candidate.relative_to(self.root)
            if not candidate.is_file() or not 0 < candidate.stat().st_size <= MAX_BYTES:
                raise ValueError("empty, oversized or nonregular evidence")
            data = candidate.read_bytes()
            if hashlib.sha256(data).hexdigest() != ref["sha256"]:
                raise ValueError("digest mismatch")
            parsed = load_json(data) if structured else data
            if structured and not isinstance(parsed, dict):
                raise ValueError("referenced JSON must be an object")
            return candidate, parsed
        except (OSError, ValueError, TypeError, RecursionError, OverflowError) as exc:
            self.fail(where, f"invalid evidence ({type(exc).__name__}: {str(exc)[:100]})")
            return None

    def interval(self, item, where, ceiling=None):
        observed, expiry = stamp(item.get("observed_at")), stamp(item.get("expires_at"))
        if observed is None or expiry is None or not observed <= self.now < expiry or observed >= expiry:
            self.fail(where, "missing, future, expired or invalid observation interval")
        elif ceiling is not None and expiry > ceiling:
            self.fail(where, "evidence expiry exceeds binding expiry")

    def contract_valid(self):
        c = self.contract
        if not isinstance(c, dict) or c.get("schema_version") != "acs-gate-contract/1" or not isinstance(c.get("contract_revision"), str) or not known(c["contract_revision"]) or not sha(c.get("instruction_sha256")):
            self.fail("contract", "invalid contract identity")
            return False
        for field in ("binding_fields", "scenario_evidence_fields", "supported_evidence_layers"):
            if not strings(c.get(field)):
                self.fail("contract", f"invalid {field}")
        gates = c.get("gates")
        if not isinstance(gates, dict) or not gates:
            self.fail("contract", "missing Gate definitions")
            return False
        for name, definition in gates.items():
            if not isinstance(name, str) or not isinstance(definition, dict) or not strings(definition.get("scenarios")) or not strings(definition.get("requires"), nonempty=False):
                self.fail("contract", "invalid Gate definition")
                return False
        visited = set()
        def visit(name, chain):
            if name in chain or len(chain) > 32:
                self.fail("contract", "cyclic or excessive Gate prerequisite graph")
                return
            if name in visited:
                return
            for dep in gates[name]["requires"]:
                if dep == "BOOTSTRAP":
                    continue
                if dep not in gates:
                    self.fail("contract", "unknown prerequisite")
                else:
                    visit(dep, chain | {name})
            visited.add(name)
        for name in gates:
            visit(name, set())
        return not self.errors

    def bootstrap(self, ref, report_path, report, where):
        if report.get("schema_version") != "bootstrap-evidence/1" or report.get("gate") != "passed":
            self.fail(where, "referenced BOOTSTRAP report has not passed")
        if ref.get("contract_revision") != self.contract["contract_revision"] or not sha(ref.get("source_baseline"), 40):
            self.fail(where, "BOOTSTRAP requires adopted contract and explicit setup baseline pin")
        if stamp(ref.get("expires_at")) is None or stamp(ref["expires_at"]) <= self.now:
            self.fail(where, "BOOTSTRAP reference expiry missing or expired")
        recorded = stamp(report.get("recorded_at"))
        if recorded is None or recorded > self.now:
            self.fail(where, "invalid BOOTSTRAP observation time")
        if report.get("setup_version") != "0.4.0" or report.get("workspace_schema") != "0.3":
            self.fail(where, "BOOTSTRAP setup-only version/schema mismatch")
        for field in ("profile", "machine", "os", "root_id", "setup_surface", "policy"):
            if not isinstance(report.get(field), str) or not known(report[field]):
                self.fail(where, f"missing BOOTSTRAP {field}")
        if report.get("preservation_changes") != [] or type(report.get("tracked_file_count")) is not int or report.get("tracked_file_count", 0) <= 0:
            self.fail(where, "BOOTSTRAP preservation is incomplete or changed")
        permissions = report.get("permissions")
        if not isinstance(permissions, dict) or permissions.get("source_read") is not True or permissions.get("source_write") is not True:
            self.fail(where, "BOOTSTRAP permission read-back missing")
        inventory = self.reference(ref.get("preservation_inventory"), where + ".preservation_inventory", structured=True)
        if inventory:
            entries = inventory[1]
            if len(entries) != report.get("tracked_file_count"):
                self.fail(where, "preservation inventory count mismatch")
            configs = report.get("config_refs")
            if not isinstance(configs, dict) or set(configs) != {".agents/config.yaml", ".agents/settings.yaml", ".agents/manifest.json"}:
                self.fail(where, "configuration digests missing")
            else:
                for name, digest in configs.items():
                    matches = [v for k, v in entries.items() if k.endswith("/" + name) and isinstance(v, dict) and v.get("sha256") == digest]
                    if not sha(digest) or not matches:
                        self.fail(where, "configuration digest absent from preservation inventory")
        checks = report.get("checks")
        if not isinstance(checks, list) or any(not isinstance(c, dict) for c in checks):
            self.fail(where, "BOOTSTRAP checks malformed")
            return
        ids = [c.get("scenario_id") for c in checks]
        if not strings(ids) or not BOOTSTRAP_CHECKS <= set(ids):
            self.fail(where, "required fresh-process checks missing or duplicated")
        for check in checks:
            command = check.get("command")
            if check.get("status") != "passed" or type(check.get("exit_code")) is not int or check["exit_code"] != 0 or check.get("evidence_class") != "directly_verified" or not isinstance(command, list) or not command or any(not isinstance(v, str) or not v for v in command):
                self.fail(where, "fresh-process check did not pass")
            started, completed = stamp(check.get("started_at")), stamp(check.get("completed_at"))
            if started is None or completed is None or not started <= completed <= self.now or (recorded is not None and completed > recorded):
                self.fail(where, "invalid fresh-process timestamps")
            output = self.reference({"path": check.get("raw_output"), "sha256": check.get("sha256")}, where + ".check", directory=report_path.parent)
            if output and check.get("scenario_id") in ("git-head", "setup-version"):
                actual = output[1].split(b"\n--- stderr ---", 1)[0].decode("utf-8", errors="replace").strip()
                expected = ref.get("source_baseline") if check["scenario_id"] == "git-head" else report.get("setup_version")
                if actual != expected:
                    self.fail(where, "BOOTSTRAP raw version/baseline read-back mismatch")

    def topology(self, binding, gate, where):
        machines, nodes = binding.get("machines"), binding.get("nodes")
        if not strings(machines) or not strings(nodes):
            self.fail(where, "distinct machine and node IDs required")
            return
        if gate.startswith("P2") and len(machines) < 2:
            self.fail(where, "P2 requires two distinct observed machines")
        os_versions = binding.get("os")
        if not isinstance(os_versions, dict) or set(os_versions) != set(machines) or any(not isinstance(v, str) or not known(v) for v in os_versions.values()):
            self.fail(where, "OS versions must cover observed machines exactly")
            os_versions = {}
        machine_refs = binding.get("machine_evidence")
        if not isinstance(machine_refs, dict) or set(machine_refs) != set(machines):
            self.fail(where, "machine observation references must cover binding exactly")
            return
        fingerprints, observed_nodes, machine_nodes = [], [], {}
        for machine, ref in machine_refs.items():
            result = self.reference(ref, where + ".machine_evidence", structured=True)
            if not result:
                continue
            data = result[1]
            if data.get("schema_version") != "acs-machine-observation/1" or data.get("machine_id") != machine or data.get("node_id") not in nodes or data.get("profile") != binding.get("profile") or data.get("evidence_class") != "directly_verified":
                self.fail(where, "machine observation identity/Profile mismatch")
            if not isinstance(data.get("host_fingerprint"), str) or not known(data["host_fingerprint"]) or not known(data.get("os")):
                self.fail(where, "machine observation requires host identity and OS")
            if data.get("os") != os_versions.get(machine):
                self.fail(where, "machine OS version disagrees with binding")
            fingerprints.append(data.get("host_fingerprint"))
            observed_nodes.append(data.get("node_id"))
            machine_nodes[machine] = data.get("node_id")
            self.interval(data, where + ".machine_evidence")
            self.reference(data.get("evidence"), where + ".machine_evidence.raw")
        if not strings(fingerprints) or not strings(observed_nodes) or set(observed_nodes) != set(nodes):
            self.fail(where, "duplicate host fingerprint or mismatched observed Nodes")
        if not gate.startswith("P2"):
            return
        refs = binding.get("session_evidence")
        if not isinstance(refs, list) or len(refs) < 2:
            self.fail(where, "P2 requires observed cross-session topology")
            return
        sessions, participants = [], []
        for ref in refs:
            result = self.reference(ref, where + ".session_evidence", structured=True)
            if not result:
                continue
            data = result[1]
            harness, machine = data.get("harness"), data.get("machine_id")
            if not isinstance(harness, str) or not isinstance(machine, str):
                self.fail(where, "invalid session Harness/machine")
                continue
            versions, drivers = binding.get("harness"), binding.get("driver")
            if (data.get("schema_version") != "acs-session-observation/1" or data.get("profile") != binding.get("profile")
                    or machine not in machines or data.get("node_id") != machine_nodes.get(machine)
                    or data.get("evidence_class") != "directly_verified" or not isinstance(versions, dict)
                    or data.get("harness_version") != versions.get(harness) or not isinstance(drivers, dict)
                    or data.get("driver_version") != drivers.get(harness)):
                self.fail(where, "session topology/version/Profile mismatch")
            sessions.append(data.get("session_id"))
            participants.append((harness, machine))
            self.interval(data, where + ".session_evidence")
            self.reference(data.get("evidence"), where + ".session_evidence.raw")
        if not strings(sessions):
            self.fail(where, "session IDs missing or duplicated")
        required = {"codex"} if gate == "P2-CODEX" else {"codex", "opencode"}
        usable = [(h, m) for h, m in participants if h in required]
        if not required <= {h for h, _ in usable} or len({m for _, m in usable}) < 2:
            self.fail(where, "required Harnesses on distinct machines not evidenced")

    def gate(self, record, where="record", expected_gate=None, parent=None, depth=0):
        if not isinstance(record, dict):
            self.fail(where, "Gate record must be an object")
            return
        if depth > 16:
            self.fail(where, "Gate recursion limit")
            return
        if record.get("schema_version") != "acs-gate-record/1" or record.get("contract_revision") != self.contract["contract_revision"]:
            self.fail(where, "record schema/contract revision mismatch")
        gate = record.get("gate")
        if not isinstance(gate, str) or gate not in self.contract["gates"]:
            self.fail(where, "unknown Gate")
            return
        if expected_gate is not None and gate != expected_gate:
            self.fail(where, "referenced prerequisite Gate identity mismatch")
        status = record.get("status")
        if not isinstance(status, str) or status not in ("not_run", "blocked", "unknown", "passed", "supported"):
            self.fail(where, "invalid Gate status")
        definition = self.contract["gates"][gate]
        scenarios = record.get("scenarios")
        if not isinstance(scenarios, list) or any(not isinstance(s, dict) for s in scenarios):
            self.fail(where, "scenarios must be objects")
            return
        ids = [s.get("scenario_id") for s in scenarios]
        if not strings(ids) or set(ids) != set(definition["scenarios"]):
            self.fail(where, "scenario set must match contract exactly without duplicates")
        for s in scenarios:
            if not isinstance(s.get("status"), str) or s["status"] not in ("not_run", "blocked", "unknown", "passed"):
                self.fail(where, "invalid scenario status")
        claimed = status in ("passed", "supported")
        passing = [s for s in scenarios if s.get("status") == "passed"]
        if not claimed and not passing:
            return
        if claimed and len(passing) != len(scenarios):
            self.fail(where, "passing Gate requires all mandatory scenarios")
        binding = record.get("binding")
        if not isinstance(binding, dict):
            self.fail(where, "binding must be an object")
            return
        for field in self.contract["binding_fields"]:
            if not known(binding.get(field)):
                self.fail(where, f"binding.{field} missing or unknown")
        expiry = stamp(binding.get("expires_at"))
        if expiry is None or expiry <= self.now:
            self.fail(where, "binding expired or invalid")
        baseline = record.get("source_baseline")
        if not sha(baseline, 40):
            self.fail(where, "source baseline must be a full Git commit")
        if not isinstance(record.get("engineer"), str) or not known(record["engineer"]):
            self.fail(where, "engineer identity required")
        if parent:
            if parent.get("source_baseline") != baseline or parent["binding"].get("profile") != binding.get("profile"):
                self.fail(where, "prerequisite baseline/Profile mismatch")
            for key in ("core", "provider", "driver", "harness", "database", "protocol", "credential_scope", "policy"):
                if parent["binding"].get(key) != binding.get(key):
                    self.fail(where, f"prerequisite {key} version/scope mismatch")
            earlier = [stamp(s.get("observed_at")) for s in passing]
            later = [stamp(s.get("observed_at")) for s in parent["scenarios"] if s.get("status") == "passed"]
            if earlier and later and all(earlier) and all(later) and max(earlier) > min(later):
                self.fail(where, "prerequisite evidence postdates dependent Gate execution")
        for component in ("core", "protocol", "credential_scope", "policy", "profile", "direction"):
            if not isinstance(binding.get(component), str) or not known(binding[component]):
                self.fail(where, f"binding.{component} must be pinned text")
        for component in ("provider", "database", "driver", "harness"):
            if not isinstance(binding.get(component), dict) or not known(binding[component]) or any(not isinstance(v, str) for v in binding[component].values()):
                self.fail(where, f"binding.{component} requires named pinned versions")
        if not isinstance(binding.get("provider"), dict) or "temporal" not in binding["provider"]:
            self.fail(where, "reference Profile requires Temporal version evidence")
        if not isinstance(binding.get("database"), dict) or "postgresql" not in binding["database"]:
            self.fail(where, "reference Profile requires PostgreSQL version evidence")
        for component in ("driver", "harness"):
            if not isinstance(binding.get(component), dict) or not {"codex", "opencode"} <= binding[component].keys():
                self.fail(where, f"{component} must pin Codex and OpenCode")
        self.topology(binding, gate, where)
        for scenario in passing:
            location = where + "." + str(scenario.get("scenario_id"))
            if scenario.get("source_baseline") != baseline or scenario.get("binding_sha256") != binding_digest(binding):
                self.fail(location, "stale baseline or different Profile/binding")
            if scenario.get("evidence_class") != "directly_verified" or scenario.get("evidence_state") != "complete":
                self.fail(location, "direct, complete evidence required")
            self.interval(scenario, location, expiry)
            for field in self.contract["scenario_evidence_fields"]:
                if field == "unresolved_items":
                    if scenario.get(field) != []:
                        self.fail(location, "unresolved items require resolution")
                elif not known(scenario.get(field)):
                    self.fail(location, f"{field} missing or unknown")
            for field in IDS:
                if not strings(scenario.get(field)):
                    self.fail(location, f"{field} must be nonempty unique identity strings")
            for field in ("observer", "owner"):
                if not isinstance(scenario.get(field), str) or not known(scenario[field]):
                    self.fail(location, f"{field} identity required")
            for field in ("receipts", "raw_outputs", "fault_injection", *READBACKS):
                refs = scenario.get(field)
                if not isinstance(refs, list) or not refs:
                    self.fail(location, f"{field}: nonempty evidence references required; no contract applicability exemption")
                else:
                    for ref in refs:
                        self.reference(ref, location + "." + field)
        prereqs = record.get("prerequisites")
        if not isinstance(prereqs, dict) or set(prereqs) != set(definition["requires"]):
            self.fail(where, "prerequisites must match the contract exactly")
        else:
            for required, ref in prereqs.items():
                location = where + ".prerequisite." + required
                result = self.reference(ref, location, structured=True)
                if not result:
                    continue
                path, data = result
                if path in self.active:
                    self.fail(location, "cyclic prerequisite reference")
                    continue
                self.active.add(path)
                if required == "BOOTSTRAP":
                    self.bootstrap(ref, path, data, location)
                    actual_status = data.get("gate")
                else:
                    self.gate(data, location, expected_gate=required, parent=record, depth=depth + 1)
                    actual_status = data.get("status")
                self.active.remove(path)
                if actual_status not in ("passed", "supported") or ("status" in ref and ref["status"] != actual_status):
                    self.fail(location, "referenced prerequisite has not passed or status label disagrees")
        if not claimed:
            return
        review = record.get("review")
        if (not isinstance(review, dict) or not isinstance(review.get("reviewer"), str) or not known(review["reviewer"])
                or review.get("reviewer") == record.get("engineer") or review.get("source_baseline") != baseline or review.get("decision") != "pass"):
            self.fail(where, "independent review of exact baseline required")
        else:
            result = self.reference(review.get("evidence"), where + ".review.evidence", structured=True)
            if result:
                data = result[1]
                expected = {"schema_version": "acs-gate-review/1", "gate": gate, "reviewer": review["reviewer"], "engineer": record.get("engineer"),
                            "source_baseline": baseline, "decision": "pass", "profile": binding.get("profile"), "contract_revision": self.contract["contract_revision"],
                            "binding_sha256": binding_digest(binding), "unresolved_items": []}
                for field, value in expected.items():
                    if data.get(field) != value:
                        self.fail(where, f"actual review {field} mismatch")
                self.interval(data, where + ".review", expiry)
                scenario_times = [stamp(s.get("observed_at")) for s in passing]
                reviewed = stamp(data.get("observed_at"))
                if reviewed is not None and scenario_times and all(scenario_times) and reviewed < max(scenario_times):
                    self.fail(where, "independent review predates Gate evidence")
                self.reference(data.get("evidence"), where + ".review.raw")
        if gate == "P2-REVIEW":
            result = self.reference(record.get("product_owner_decision"), where + ".product_owner_decision", structured=True)
            if result:
                data = result[1]
                if data.get("schema_version") != "acs-product-owner-decision/1" or data.get("decision") != "approve" or data.get("source_baseline") != baseline or data.get("profile") != binding.get("profile") or data.get("contract_revision") != self.contract["contract_revision"] or not isinstance(data.get("product_owner"), str) or not known(data["product_owner"]):
                    self.fail(where, "product owner decision content mismatch; offline labels do not authenticate approval")
                self.interval(data, where + ".product_owner_decision", expiry)
                self.reference(data.get("evidence"), where + ".product_owner_decision.raw")
        if status == "supported":
            layers = record.get("support_evidence")
            if not isinstance(layers, dict) or set(layers) != set(self.contract["supported_evidence_layers"]):
                self.fail(where, "all five support layers required")
            else:
                for layer, ref in layers.items():
                    location = where + ".support_evidence." + layer
                    result = self.reference(ref, location, structured=True)
                    if result:
                        data = result[1]
                        expected = {"schema_version": "acs-support-layer/1", "layer": layer, "gate": gate,
                                    "profile": binding.get("profile"), "source_baseline": baseline,
                                    "binding_sha256": binding_digest(binding), "contract_revision": self.contract["contract_revision"]}
                        if any(data.get(k) != v for k, v in expected.items()):
                            self.fail(location, "support layer scope/baseline mismatch")
                        self.interval(data, location, expiry)
                        self.reference(data.get("evidence"), location + ".raw")


def validate(record, contract, evidence_root: Path, now: datetime | None = None):
    try:
        now = now or datetime.now(timezone.utc)
        if not isinstance(now, datetime) or now.tzinfo is None:
            return ["invalid validation clock"]
        root = Path(evidence_root).absolute()
        no_alias(root)
        root = root.resolve(strict=True)
        if not root.is_dir():
            return ["evidence root must be a directory"]
        checker = GateValidator(contract, root, now)
        if checker.contract_valid():
            checker.gate(record)
        return checker.errors
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as exc:
        return [f"invalid input: {type(exc).__name__}"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--contract", type=Path, default=Path(__file__).resolve().parents[2] / "docs/runtime/gate-contract.json")
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--require-passed", action="store_true")
    args = parser.parse_args()
    try:
        record, contract = load_json(args.record.read_bytes()), load_json(args.contract.read_bytes())
        errors = validate(record, contract, args.evidence_root or args.record.parent)
        if args.require_passed and (not isinstance(record, dict) or record.get("status") not in ("passed", "supported")):
            errors.append("Gate has not passed")
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as exc:
        errors = [f"invalid input: {type(exc).__name__}"]
    print(json.dumps({"valid": not errors, "errors": errors, "scope": "offline completeness and integrity only; not execution proof or authorization"}))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
