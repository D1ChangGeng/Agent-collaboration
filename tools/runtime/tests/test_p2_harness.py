from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.runtime import p2_harness as harness

ROOT = Path(os.environ.get("ACS_TEST_SOURCE_ROOT", Path(__file__).resolve().parents[3])).resolve()
CONTRACT = ROOT / "docs" / "runtime" / "gate-contract.json"
INVENTORY = ROOT / "docs" / "runtime" / "P2-INVENTORY-TEMPLATE.json"


class P2HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.output = self.base / "run"
        self.source = self.base / "source"
        self.source.mkdir()
        (self.source / "tracked.txt").write_text("baseline\n", encoding="utf-8")
        for command in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "runner@example.invalid"],
            ["git", "config", "user.name", "Runner Fixture"],
            ["git", "add", "."],
            ["git", "commit", "-qm", "fixture baseline"],
        ):
            subprocess.run(command, cwd=self.source, check=True, capture_output=True)
        self.inventory = harness.read_json(INVENTORY)
        self.contract = harness.read_json(CONTRACT)

    def tearDown(self):
        self.temp.cleanup()

    def test_contract_has_exact_ordered_p2_scenarios(self):
        scenarios = harness.contract_scenarios(self.contract)
        self.assertEqual(len(scenarios["P2-CODEX"]), 8)
        self.assertEqual(len(scenarios["P2-OPENCODE"]), 8)
        self.assertEqual(set(scenarios["P2-CODEX"] + scenarios["P2-OPENCODE"]), set(harness.FAULTS))

    def test_stable_machine_inventory_requires_runtime_reobservation(self):
        harness.validate_inventory(self.inventory)
        blockers = harness.blockers(self.inventory)
        self.assertIn("both physical Machines require runtime reobservation", blockers[0])
        self.assertIn("P1 Gate has not passed", blockers)
        self.assertIn("Linux Codex login is unavailable", blockers)
        self.assertIn("Linux receiver/Node supervised services are not active", blockers)

    def test_init_and_audit_emit_only_not_run(self):
        workspace = harness.initialize(INVENTORY, CONTRACT, self.output, self.source)
        self.assertEqual(workspace["status"], "not_run")
        self.assertEqual(workspace["execution_order"], ["P1", "P2-CODEX", "P2-OPENCODE"])
        observation = json.loads((self.output / "runtime-observation.json").read_text())
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.source,
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual(observation["source_commit"], commit)
        harness.audit(self.output, CONTRACT)
        for gate in ("P2-CODEX", "P2-OPENCODE"):
            record = json.loads((self.output / f"{gate}.json").read_text())
            self.assertEqual(record["status"], "not_run")
            self.assertTrue(all(item["status"] == "not_run" for item in record["scenarios"]))

    def test_two_process_labels_cannot_fake_two_machines(self):
        changed = copy.deepcopy(self.inventory)
        changed["machines"][1]["machine_id"] = changed["machines"][0]["machine_id"]
        with self.assertRaisesRegex(harness.HarnessError, "physical Machines"):
            harness.validate_inventory(changed)

    def test_credentials_cannot_enter_inventory(self):
        changed = copy.deepcopy(self.inventory)
        changed["machines"][0]["credentials_present"] = True
        with self.assertRaisesRegex(harness.HarnessError, "credentials"):
            harness.validate_inventory(changed)
        path = self.base / "secret.json"
        path.write_text('{"password":"forbidden"}', encoding="utf-8")
        with self.assertRaisesRegex(harness.HarnessError, "secret-like"):
            harness.read_json(path)

    def test_gate_status_or_hash_tampering_is_rejected(self):
        harness.initialize(INVENTORY, CONTRACT, self.output, self.source)
        record_path = self.output / "P2-CODEX.json"
        record = json.loads(record_path.read_text())
        record["status"] = "passed"
        harness.write_json(record_path, record)
        with self.assertRaisesRegex(harness.HarnessError, "hash mismatch"):
            harness.audit(self.output, CONTRACT)

    def test_output_inside_source_is_rejected(self):
        with self.assertRaisesRegex(harness.HarnessError, "outside"):
            harness.ensure_external(self.source / "gates" / "p2-run", self.source)

    def test_authentication_remains_manual_and_unattempted(self):
        auth = self.inventory["authentication"]
        self.assertEqual(auth["linux_codex_login"], "not_run")
        self.assertFalse(auth["login_attempted_by_harness"])

    def test_old_source_or_machine_observation_claims_are_rejected(self):
        for field, value in (
            ("source", {"commit": "a97d854", "tree": "old"}),
            ("host_fingerprint_sha256", "f" * 64),
            ("versions", {"codex": "old", "opencode": "old"}),
        ):
            changed = copy.deepcopy(self.inventory)
            changed["machines"][0][field] = value
            with self.assertRaisesRegex(harness.HarnessError, "cannot claim a current"):
                harness.validate_inventory(changed)

    def test_audit_reobserves_source_commit(self):
        harness.initialize(INVENTORY, CONTRACT, self.output, self.source)
        (self.source / "tracked.txt").write_text("new commit\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.source, check=True)
        subprocess.run(["git", "commit", "-qm", "changed"], cwd=self.source, check=True)
        with self.assertRaisesRegex(harness.HarnessError, "observation changed"):
            harness.audit(self.output, CONTRACT)


if __name__ == "__main__":
    unittest.main()
