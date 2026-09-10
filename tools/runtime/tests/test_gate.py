"""Synthetic negative fixtures for the offline checker; never Runtime evidence."""
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools/runtime/validate_gate.py"
SPEC = importlib.util.spec_from_file_location("runtime_gate", SCRIPT)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)
NOW = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)
OBSERVED = "2026-09-11T10:00:00Z"
EXPIRY = "2026-09-12T10:00:00Z"
BASELINE = "1" * 40
SETUP_BASELINE = "2" * 40


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.contract = json.loads((ROOT / "docs/runtime/gate-contract.json").read_text())
        self.raw = self.write("fixture.txt", b"SYNTHETIC UNIT FIXTURE. No runtime was executed.\n")
        configs = {name: self.write("bootstrap/" + Path(name).name, b"fixture-config\n")["sha256"]
                   for name in (".agents/config.yaml", ".agents/settings.yaml", ".agents/manifest.json")}
        inventory = {"management/" + k: {"sha256": v, "bytes": 15} for k, v in configs.items()}
        self.inventory_ref = self.write("bootstrap/preservation-inventory.json", inventory)
        checks = []
        for sid in sorted(gate.BOOTSTRAP_CHECKS):
            output = SETUP_BASELINE if sid == "git-head" else "0.4.0" if sid == "setup-version" else "SYNTHETIC UNIT FIXTURE"
            ref = self.write("bootstrap/" + sid + ".log", (output + "\n\n--- stderr ---\n").encode())
            checks.append({"scenario_id": sid, "command": ["fixture-process", sid], "status": "passed", "exit_code": 0,
                           "started_at": OBSERVED, "completed_at": OBSERVED, "evidence_class": "directly_verified",
                           "raw_output": sid + ".log", "sha256": ref["sha256"]})
        self.bootstrap = {"schema_version": "bootstrap-evidence/1", "gate": "passed", "recorded_at": OBSERVED,
                          "setup_version": "0.4.0", "workspace_schema": "0.3", "profile": "fixture-setup", "machine": "machine-a",
                          "os": "fixture-os-1", "root_id": "fixture-root", "setup_surface": "explicit-source-cli", "policy": "setup-only-readback",
                          "preservation_changes": [], "tracked_file_count": len(inventory), "permissions": {"source_read": True, "source_write": True},
                          "config_refs": configs, "checks": checks}
        self.bootstrap_ref = self.write("bootstrap/report.json", self.bootstrap)
        self.bootstrap_ref.update(status="passed", source_baseline=SETUP_BASELINE, contract_revision=self.contract["contract_revision"],
                                  expires_at=EXPIRY, preservation_inventory=self.inventory_ref)
        self.binding = {"profile": "SYNTHETIC-conformance-fixture", "machines": ["machine-a", "machine-b"], "nodes": ["node-a", "node-b"],
                        "os": {"machine-a": "fixture-os-1", "machine-b": "fixture-os-2"}, "core": "0.1.0", "provider": {"temporal": "1.2.3"},
                        "database": {"postgresql": "17.0"}, "driver": {"codex": "0.1.0", "opencode": "0.1.0"},
                        "harness": {"codex": "1.0.0", "opencode": "2.0.0"}, "protocol": "v0", "credential_scope": "fixture-only",
                        "policy": "fixture-policy/1", "direction": "bidirectional", "expires_at": EXPIRY, "machine_evidence": {}, "session_evidence": []}
        self.machines, self.sessions = {}, []
        for suffix in ("a", "b"):
            data = {"schema_version": "acs-machine-observation/1", "machine_id": "machine-" + suffix, "node_id": "node-" + suffix,
                    "profile": self.binding["profile"], "host_fingerprint": "SYNTHETIC-host-" + suffix, "os": "fixture-os-" + ("1" if suffix == "a" else "2"),
                    "observed_at": OBSERVED, "expires_at": EXPIRY, "evidence_class": "directly_verified", "evidence": self.raw}
            self.machines[suffix] = data
            self.binding["machine_evidence"]["machine-" + suffix] = self.write("machine-" + suffix + ".json", data)
        for harness, suffix in (("codex", "a"), ("codex", "b"), ("opencode", "b")):
            data = {"schema_version": "acs-session-observation/1", "session_id": harness + "-" + suffix, "machine_id": "machine-" + suffix,
                    "node_id": "node-" + suffix, "profile": self.binding["profile"], "harness": harness,
                    "harness_version": self.binding["harness"][harness], "driver_version": self.binding["driver"][harness],
                    "observed_at": OBSERVED, "expires_at": EXPIRY, "evidence_class": "directly_verified", "evidence": self.raw}
            self.sessions.append(data)
            self.binding["session_evidence"].append(self.write("session-" + harness + "-" + suffix + ".json", data))
        self.records, self.reviews, self.refs = {}, {}, {}
        for name, definition in self.contract["gates"].items():
            scenarios = []
            for sid in definition["scenarios"]:
                scenario = {"scenario_id": sid, "status": "passed", "source_baseline": BASELINE, "binding_sha256": gate.binding_digest(self.binding),
                            "evidence_class": "directly_verified", "evidence_state": "complete", "observed_at": OBSERVED, "expires_at": EXPIRY,
                            "observer": "fixture-observer", "owner": "fixture-owner", "unresolved_items": []}
                for field in gate.IDS:
                    scenario[field] = [sid + "-" + field]
                for field in ("raw_outputs", "receipts", "fault_injection", *gate.READBACKS):
                    scenario[field] = [self.raw]
                scenarios.append(scenario)
            review = {"schema_version": "acs-gate-review/1", "gate": name, "engineer": "fixture-engineer", "reviewer": "fixture-reviewer",
                      "source_baseline": BASELINE, "decision": "pass", "profile": self.binding["profile"], "contract_revision": self.contract["contract_revision"],
                      "binding_sha256": gate.binding_digest(self.binding), "unresolved_items": [], "observed_at": OBSERVED, "expires_at": EXPIRY, "evidence": self.raw}
            self.reviews[name] = review
            self.records[name] = {"schema_version": "acs-gate-record/1", "contract_revision": self.contract["contract_revision"], "gate": name,
                                  "status": "passed", "engineer": "fixture-engineer", "source_baseline": BASELINE, "binding": copy.deepcopy(self.binding),
                                  "scenarios": scenarios, "prerequisites": {}, "review": {"reviewer": "fixture-reviewer", "source_baseline": BASELINE,
                                  "decision": "pass", "evidence": self.write(name + "-review.json", review)}}
        owner = {"schema_version": "acs-product-owner-decision/1", "decision": "approve", "source_baseline": BASELINE, "profile": self.binding["profile"],
                 "contract_revision": self.contract["contract_revision"], "product_owner": "fixture-user", "observed_at": OBSERVED, "expires_at": EXPIRY, "evidence": self.raw}
        self.records["P2-REVIEW"]["product_owner_decision"] = self.write("owner.json", owner)
        self.reseal()

    def write(self, name, value):
        data = json.dumps(value).encode() if not isinstance(value, bytes) else value
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {"path": name, "sha256": hashlib.sha256(data).hexdigest()}

    def reseal(self):
        self.bootstrap_ref.update(self.write("bootstrap/report.json", self.bootstrap))
        for name, definition in self.contract["gates"].items():
            record = self.records[name]
            record["prerequisites"] = {dep: copy.deepcopy(self.bootstrap_ref if dep == "BOOTSTRAP" else self.refs[dep]) for dep in definition["requires"]}
            self.refs[name] = {**self.write(name + ".json", record), "status": record["status"]}

    def check(self, record=None, contract=None):
        return gate.validate(self.records["P2-REVIEW"] if record is None else record,
                             self.contract if contract is None else contract, self.root, NOW)

    def rejected(self, fragment, record=None):
        errors = self.check(record)
        self.assertTrue(any(fragment in e for e in errors), errors)

    def test_complete_synthetic_chain_is_offline_valid_only(self):
        self.assertEqual(self.check(), [])

    def test_planned_gate_is_valid_but_not_passed(self):
        record = {"schema_version": "acs-gate-record/1", "contract_revision": self.contract["contract_revision"], "gate": "P1", "status": "not_run",
                  "scenarios": [{"scenario_id": sid, "status": "not_run"} for sid in self.contract["gates"]["P1"]["scenarios"]]}
        self.assertEqual(self.check(record), [])
        path = self.write("planned.json", record)["path"]
        cp = subprocess.run([sys.executable, str(SCRIPT), str(self.root / path), "--require-passed"], capture_output=True, text=True)
        self.assertEqual(cp.returncode, 1, cp.stderr)
        self.assertIn("Gate has not passed", json.loads(cp.stdout)["errors"])

    def test_forged_outer_prerequisite_status_cannot_hide_not_run(self):
        self.records["P1"]["status"] = "not_run"
        for scenario in self.records["P1"]["scenarios"]:
            scenario["status"] = "not_run"
        self.reseal()
        self.records["P2-CODEX"]["prerequisites"]["P1"]["status"] = "passed"
        self.rejected("referenced prerequisite has not passed", self.records["P2-CODEX"])

    def test_deep_prerequisite_checks_its_raw_digests(self):
        self.records["P1"]["scenarios"][0]["raw_outputs"] = [{"path": "fixture.txt", "sha256": "f" * 64}]
        self.reseal()
        self.rejected("digest mismatch")

    def test_prerequisite_identity_contract_baseline_and_profile(self):
        original = copy.deepcopy(self.records["P1"])
        for field, value, fragment in (("gate", "P2-CODEX", "Gate identity"), ("contract_revision", "old", "contract revision"),
                                      ("source_baseline", "a" * 40, "baseline/Profile")):
            with self.subTest(field=field):
                self.records["P1"] = copy.deepcopy(original)
                self.records["P1"][field] = value
                self.reseal()
                self.rejected(fragment)
        self.records["P1"] = copy.deepcopy(original)
        self.records["P1"]["binding"]["profile"] = "other-profile"
        self.reseal()
        self.rejected("baseline/Profile")

    def test_prerequisite_component_version_mismatch(self):
        self.records["P1"]["binding"]["provider"]["temporal"] = "9.9.9"
        self.reseal()
        self.rejected("provider version/scope mismatch")

    def test_contract_cycle_is_rejected_without_recursing_forever(self):
        self.contract["gates"]["P1"]["requires"] = ["P2-REVIEW"]
        self.rejected("cyclic")

    def test_reference_cycle_guard_rejects_active_path(self):
        checker = gate.GateValidator(self.contract, self.root, NOW)
        checker.active.add((self.root / "P1.json").resolve())
        checker.gate(self.records["P2-CODEX"])
        self.assertTrue(any("cyclic prerequisite" in e for e in checker.errors), checker.errors)

    def test_bootstrap_actual_report_not_label(self):
        self.bootstrap["gate"] = "blocked"
        self.reseal()
        self.rejected("BOOTSTRAP report has not passed")

    def test_bootstrap_fresh_process_checks_mandatory(self):
        self.bootstrap["checks"] = self.bootstrap["checks"][1:]
        self.reseal()
        self.rejected("fresh-process checks missing")

    def test_bootstrap_nonzero_exit_and_false_boolean_exit_rejected(self):
        for code in (1, False):
            self.bootstrap["checks"][0]["exit_code"] = code
            self.reseal()
            self.rejected("fresh-process check did not pass")

    def test_bootstrap_setup_baseline_is_pinned_to_actual_stdout(self):
        self.bootstrap_ref["source_baseline"] = "3" * 40
        self.reseal()
        self.rejected("raw version/baseline read-back mismatch")

    def test_bootstrap_pinning_does_not_require_runtime_commit_equal_setup_commit(self):
        self.assertNotEqual(SETUP_BASELINE, BASELINE)
        self.assertEqual(self.check(), [])

    def test_bootstrap_inventory_and_config_cannot_be_omitted(self):
        self.bootstrap["config_refs"][".agents/config.yaml"] = "f" * 64
        self.reseal()
        self.rejected("configuration digest absent")
        self.bootstrap["preservation_changes"] = ["AGENTS.md"]
        self.reseal()
        self.rejected("preservation is incomplete or changed")

    def test_bootstrap_expiry_and_unknown_setup_version(self):
        self.bootstrap_ref["expires_at"] = "2026-09-10T10:00:00Z"
        self.reseal()
        self.rejected("expired reference")
        self.bootstrap_ref["expires_at"] = EXPIRY
        self.bootstrap["setup_version"] = "unknown"
        self.reseal()
        self.rejected("version/schema mismatch")

    def test_malformed_records_do_not_crash_or_pass(self):
        for value in (None, [], "passed", 1, True, {"gate": []}, {"gate": {}}):
            with self.subTest(value=value):
                self.assertTrue(gate.validate(value, self.contract, self.root, NOW))
        for field, value in (("scenario_id", []), ("scenario_id", {}), ("status", []), ("command_ids", [{}]),
                             ("observed_at", True), ("expires_at", {}), ("observer", True)):
            record = copy.deepcopy(self.records["P1"])
            record["scenarios"][0][field] = value
            with self.subTest(field=field, value=value):
                self.assertTrue(self.check(record))

    def test_malformed_contract_does_not_crash_or_pass(self):
        for value in ([], None, "contract", {}, {"schema_version": "acs-gate-contract/1", "contract_revision": []}):
            self.assertTrue(gate.validate(self.records["P1"], value, self.root, NOW))

    def test_empty_evidence_or_self_declared_applicability_never_passes(self):
        for field in (*gate.READBACKS, "fault_injection", "receipts", "raw_outputs"):
            for value in ([], {"not_applicable": "unknown"}, {"not_applicable": "not needed for this case"}, ["raw output"]):
                with self.subTest(field=field, value=value):
                    record = copy.deepcopy(self.records["P1"])
                    record["scenarios"][0][field] = value
                    self.assertTrue(self.check(record))

    def test_unknown_and_unpinned_versions_never_pass(self):
        for value in ("unknown", "latest", "*", True, {}, ["17"]):
            record = copy.deepcopy(self.records["P1"])
            record["binding"]["database"] = {"postgresql": value}
            with self.subTest(value=value):
                self.assertTrue(self.check(record))

    def test_expired_stale_incomplete_future_scenario_rejected(self):
        for field, value, fragment in (("expires_at", "2026-09-10T10:00:00Z", "expired"),
                                      ("observed_at", "2026-09-12T10:00:00Z", "future"),
                                      ("evidence_state", "incomplete", "complete evidence"),
                                      ("evidence_class", "stale", "complete evidence"),
                                      ("source_baseline", "a" * 40, "stale baseline")):
            record = copy.deepcopy(self.records["P1"])
            record["scenarios"][0][field] = value
            self.rejected(fragment, record)

    def test_path_traversal_missing_digest_and_empty_file_rejected(self):
        self.write("empty.txt", b"")
        for ref in ({"path": "../outside", "sha256": "f" * 64}, {"path": "C:/secret", "sha256": "f" * 64},
                    {"path": "fixture.txt"}, {"path": "fixture.txt\x00", "sha256": "f" * 64},
                    {"path": "empty.txt", "sha256": hashlib.sha256(b"").hexdigest()}):
            record = copy.deepcopy(self.records["P1"])
            record["scenarios"][0]["raw_outputs"] = [ref]
            self.assertTrue(self.check(record))

    def test_review_requires_engineer_and_independent_actual_reviewer(self):
        record = copy.deepcopy(self.records["P1"])
        del record["engineer"]
        self.rejected("engineer identity required", record)
        record["engineer"] = record["review"]["reviewer"]
        self.rejected("independent review", record)
        self.reviews["P1"]["reviewer"] = "fixture-engineer"
        self.records["P1"]["review"]["evidence"] = self.write("P1-review.json", self.reviews["P1"])
        self.reseal()
        self.rejected("actual review reviewer mismatch")

    def test_review_file_cannot_be_arbitrary_text(self):
        self.records["P1"]["review"]["evidence"] = self.raw
        self.reseal()
        self.rejected("invalid evidence")

    def test_two_machine_labels_with_same_physical_observation_rejected(self):
        self.machines["b"]["host_fingerprint"] = self.machines["a"]["host_fingerprint"]
        ref = self.write("machine-b.json", self.machines["b"])
        self.records["P2-CODEX"]["binding"]["machine_evidence"]["machine-b"] = ref
        self.rejected("duplicate host fingerprint", self.records["P2-CODEX"])

    def test_p2_requires_two_observed_sessions_and_correct_versions(self):
        record = copy.deepcopy(self.records["P2-CODEX"])
        record["binding"]["session_evidence"] = []
        self.rejected("cross-session topology", record)
        self.sessions[1]["harness_version"] = "old-version"
        record["binding"]["session_evidence"] = copy.deepcopy(self.binding["session_evidence"])
        record["binding"]["session_evidence"][1] = self.write("session-codex-b.json", self.sessions[1])
        self.rejected("session topology/version/Profile mismatch", record)

    def test_expired_prerequisite_and_review_rejected(self):
        self.records["P1"]["binding"]["expires_at"] = "2026-09-10T10:00:00Z"
        self.reviews["P1"]["expires_at"] = "2026-09-10T10:00:00Z"
        self.records["P1"]["review"]["evidence"] = self.write("P1-review.json", self.reviews["P1"])
        self.reseal()
        self.rejected("binding expired")
        self.rejected("review: missing, future, expired")

    def test_partial_pass_does_not_skip_prerequisites(self):
        record = copy.deepcopy(self.records["P1"])
        record["status"] = "not_run"
        record["prerequisites"] = {}
        self.rejected("prerequisites must match", record)

    def test_supported_requires_all_five_layers(self):
        self.records["P1"]["status"] = "supported"
        self.reseal()
        self.rejected("all five support layers")

    def test_support_layers_from_other_profile_cannot_be_reused(self):
        record = self.records["P1"]
        record["status"] = "supported"
        record["support_evidence"] = {}
        for layer in self.contract["supported_evidence_layers"]:
            data = {"schema_version": "acs-support-layer/1", "layer": layer, "gate": "P1", "profile": "other-profile",
                    "source_baseline": BASELINE, "binding_sha256": gate.binding_digest(self.binding), "contract_revision": self.contract["contract_revision"],
                    "observed_at": OBSERVED, "expires_at": EXPIRY, "evidence": self.raw}
            record["support_evidence"][layer] = self.write("support-" + layer + ".json", data)
        self.rejected("support layer scope/baseline mismatch", record)

    def test_prerequisite_cannot_be_observed_after_dependent_gate(self):
        self.records["P1"]["scenarios"][0]["observed_at"] = "2026-09-11T11:00:00Z"
        self.reseal()
        self.rejected("postdates dependent Gate execution")

    def test_independent_review_cannot_predate_evidence(self):
        self.reviews["P1"]["observed_at"] = "2026-09-11T09:00:00Z"
        self.records["P1"]["review"]["evidence"] = self.write("P1-review.json", self.reviews["P1"])
        self.rejected("review predates Gate evidence", self.records["P1"])

    def test_machine_os_observation_must_match_binding(self):
        self.machines["b"]["os"] = "other-os"
        ref = self.write("machine-b.json", self.machines["b"])
        self.records["P2-CODEX"]["binding"]["machine_evidence"]["machine-b"] = ref
        self.rejected("machine OS version disagrees", self.records["P2-CODEX"])

    def test_product_owner_decision_requires_actual_structured_content(self):
        ref = self.records["P2-REVIEW"]["product_owner_decision"]
        value = json.loads((self.root / ref["path"]).read_text())
        value["decision"] = "not_run"
        self.records["P2-REVIEW"]["product_owner_decision"] = self.write("owner.json", value)
        self.rejected("product owner decision content mismatch")

    def test_cli_duplicate_keys_arrays_and_nonfinite_numbers_fail_cleanly(self):
        for raw in (b'[]', b'{"status":"passed","status":"not_run"}', b'{"gate":NaN}'):
            self.write("malformed.json", raw)
            cp = subprocess.run([sys.executable, str(SCRIPT), str(self.root / "malformed.json")], capture_output=True, text=True)
            self.assertEqual(cp.returncode, 1, cp.stderr)
            self.assertFalse(json.loads(cp.stdout)["valid"])
            self.assertNotIn("Traceback", cp.stderr)
            self.assertIn("not execution proof or authorization", cp.stdout)

    def test_missing_root_and_naive_clock_return_errors(self):
        self.assertTrue(gate.validate(self.records["P1"], self.contract, self.root / "missing", NOW))
        self.assertTrue(gate.validate(self.records["P1"], self.contract, self.root, NOW.replace(tzinfo=None)))


if __name__ == "__main__":
    unittest.main()
