from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(os.environ.get("ACS_TEST_SOURCE_ROOT", Path(__file__).resolve().parents[3])).resolve()


class GateIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        (self.source / "docs" / "runtime").mkdir(parents=True)
        (self.source / "tools" / "runtime").mkdir(parents=True)
        (self.source / "gates").mkdir()
        shutil.copy2(ROOT / "docs" / "runtime" / "gate-contract.json",
                     self.source / "docs" / "runtime" / "gate-contract.json")
        shutil.copy2(ROOT / "tools" / "runtime" / "validate_gate.py",
                     self.source / "tools" / "runtime" / "validate_gate.py")
        (self.source / "gates" / "existing-not-run.json").write_text(
            '{"status":"not_run"}\n', encoding="utf-8",
        )
        (self.source / "tracked.txt").write_text("baseline\n", encoding="utf-8")
        for command in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "runner@example.invalid"],
            ["git", "config", "user.name", "Runner Fixture"],
            ["git", "add", "."],
            ["git", "commit", "-qm", "fixture baseline"],
        ):
            subprocess.run(command, cwd=self.source, check=True, capture_output=True)
        self.contract = self.source / "docs" / "runtime" / "gate-contract.json"

    def tearDown(self):
        self.temp.cleanup()

    def git_status(self):
        return subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=self.source, check=True, capture_output=True, text=True,
        ).stdout

    def run_cli(self, script, *arguments):
        return subprocess.run(
            [sys.executable, str(ROOT / "tools" / "runtime" / script), *map(str, arguments)],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )

    def test_p1_cli_init_audit_and_missing_evidence_leave_source_and_gate_unchanged(self):
        before = (self.source / "gates" / "existing-not-run.json").read_bytes()
        run = self.base / "p1-run"
        initialized = self.run_cli(
            "gate_runner.py", "--source-root", self.source, "--contract", self.contract,
            "init", "--plan", ROOT / "docs" / "runtime" / "gate-plan-template.json",
            "--run-dir", run,
        )
        self.assertEqual(initialized.returncode, 0, initialized.stderr + initialized.stdout)
        self.assertEqual(json.loads(initialized.stdout)["status"], "not_run")
        scenario = "P1-DOMAIN-TRANSACTION"
        missing = self.run_cli(
            "gate_runner.py", "--source-root", self.source, "--contract", self.contract,
            "run", "--run-dir", run, "--scenario", scenario,
        )
        self.assertEqual(missing.returncode, 2)
        record = json.loads((run / "gate-record.json").read_text())
        self.assertEqual(record["status"], "not_run")
        self.assertTrue(all(item["status"] == "not_run" for item in record["scenarios"]))
        audited = self.run_cli(
            "gate_runner.py", "--source-root", self.source, "--contract", self.contract,
            "audit", "--run-dir", run,
        )
        self.assertEqual(audited.returncode, 0, audited.stderr + audited.stdout)
        self.assertEqual(json.loads(audited.stdout)["status"], "not_run")
        self.assertEqual(self.git_status(), "")
        self.assertEqual((self.source / "gates" / "existing-not-run.json").read_bytes(), before)

    def test_p2_cli_reobserves_current_source_and_preserves_dependency_order(self):
        output = self.base / "p2-run"
        initialized = self.run_cli(
            "p2_harness.py", "--contract", self.contract, "init",
            "--inventory", ROOT / "docs" / "runtime" / "P2-INVENTORY-TEMPLATE.json",
            "--output", output, "--source-root", self.source,
        )
        self.assertEqual(initialized.returncode, 0, initialized.stderr + initialized.stdout)
        workspace = json.loads((output / "workspace.json").read_text())
        self.assertEqual(workspace["execution_order"], ["P1", "P2-CODEX", "P2-OPENCODE"])
        observation = json.loads((output / "runtime-observation.json").read_text())
        current = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.source,
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual(observation["source_commit"], current)
        opencode = json.loads((output / "P2-OPENCODE.json").read_text())
        self.assertTrue(all("P2-CODEX prerequisite has not passed" in item["blockers"]
                            for item in opencode["scenarios"]))
        audited = self.run_cli(
            "p2_harness.py", "--contract", self.contract,
            "audit", "--output", output,
        )
        self.assertEqual(audited.returncode, 0, audited.stderr + audited.stdout)
        self.assertEqual(json.loads(audited.stdout), {"audit": "passed", "status": "not_run"})
        self.assertEqual(self.git_status(), "")
        self.assertFalse(any(value.get("status") == "passed" for value in (
            json.loads((output / "P2-CODEX.json").read_text()), opencode,
        )))


if __name__ == "__main__":
    unittest.main()
