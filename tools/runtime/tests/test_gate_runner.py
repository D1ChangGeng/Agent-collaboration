from __future__ import annotations

import base64
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from tools.runtime import gate_runner as runner

FORMAL_ROOT = Path(os.environ.get("ACS_TEST_SOURCE_ROOT", Path(__file__).resolve().parents[3])).resolve()
FORMAL_CONTRACT = FORMAL_ROOT / "docs" / "runtime" / "gate-contract.json"


class GateRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        (self.source / "docs" / "runtime").mkdir(parents=True)
        (self.source / "tools" / "runtime").mkdir(parents=True)
        (self.source / "gates").mkdir()
        shutil.copy2(FORMAL_CONTRACT, self.source / "docs" / "runtime" / "gate-contract.json")
        shutil.copy2(
            FORMAL_ROOT / "tools" / "runtime" / "validate_gate.py",
            self.source / "tools" / "runtime" / "validate_gate.py",
        )
        (self.source / "tracked.txt").write_text("tracked baseline\n", encoding="utf-8")
        (self.source / "gates" / "existing.json").write_text("{}\n", encoding="utf-8")
        (self.source / ".gitignore").write_text("ignored/\n", encoding="utf-8")
        for command in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "runner@example.invalid"],
            ["git", "config", "user.name", "Runner Fixture"],
            ["git", "add", "."],
            ["git", "commit", "-qm", "fixture baseline"],
        ):
            subprocess.run(command, cwd=self.source, check=True, capture_output=True)
        self.contract_path = self.source / "docs" / "runtime" / "gate-contract.json"
        self.run_dir = self.base / "run"
        self.contract = runner.load_contract(self.contract_path)
        self.plan = self.make_plan()
        self.plan_path = self.base / "plan.json"
        self.write_plan()

    def tearDown(self):
        self.temp.cleanup()

    def make_plan(self):
        scenarios = {
            scenario: [] for scenario in self.contract["gates"]["P1"]["scenarios"]
        }
        return {
            "schema_version": runner.PLAN_SCHEMA,
            "profile": "fixture-local-p1",
            "node_id": "fixture-node",
            "engineer": "fixture-engineer",
            "direction": "local-bidirectional",
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "core_version": "fixture-core-1",
            "temporal_version": "fixture-temporal-1",
            "postgresql_version": "fixture-postgresql-1",
            "protocol_version": "fixture-protocol-1",
            "credential_scope": "fixture-scope-1",
            "policy": "fixture-policy-1",
            "harness_versions": {"codex": "fixture-codex-1", "opencode": "fixture-opencode-1"},
            "driver_versions": {"codex": "fixture-driver-codex-1", "opencode": "fixture-driver-opencode-1"},
            "scenarios": scenarios,
            "prerequisites": {},
            "review": {},
        }

    def write_plan(self):
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")

    def initialize(self):
        return runner.initialize(self.plan_path, self.run_dir, self.source, self.contract_path)

    def configure_runtime_profile(self):
        profile_parent = self.base / "profile-private"
        profile_parent.mkdir(mode=0o700)
        profile_parent.chmod(0o700)
        profile = profile_parent / "profile.json"
        profile.write_text(json.dumps({
            "schema_version": "acs-p1-loopback-probe-profile/1",
            "profile": "p1-loopback-provider", "source_root": str(self.source),
            "python": sys.executable,
            "sandbox_python": "/run/acs-p1/runtime/bin/python",
            "postgres_dsn": (
                "postgresql://fixture:private-value@127.0.0.1:54329/temporal"
            ),
            "temporal_endpoint": "127.0.0.1:7239", "temporal_namespace": "default",
            "versions": {
                "core": "fixture-core-1",
                "provider": {"temporal": "fixture-temporal-1"},
                "database": {"postgresql": "fixture-postgresql-1", "sqlite": "fixture"},
                "protocol": "fixture-protocol-1",
                "harness": {"codex": "fixture-codex-1", "opencode": "fixture-opencode-1"},
                "driver": {
                    "codex": "fixture-driver-codex-1",
                    "opencode": "fixture-driver-opencode-1",
                },
                "os": {"fixture": "fixture"},
            },
            "node_id": "fixture-node", "direction": "local-bidirectional",
            "codex_model_evidence": None, "opencode_model_evidence": None,
        }), encoding="utf-8")
        profile.chmod(0o600)
        environment = self.base / "runtime-private"
        environment.mkdir(mode=0o700)
        environment.chmod(0o700)
        probe = environment / "p1_profile_probe.py"
        probe.write_text("print('fixture')\n", encoding="utf-8")
        probe.chmod(0o700)
        binary = environment / "bin"
        binary.mkdir(mode=0o700)
        python_wrapper = binary / "python"
        python_wrapper.write_text("#!/bin/sh\nexec /usr/bin/python3 \"$@\"\n", encoding="utf-8")
        python_wrapper.chmod(0o700)
        manifest = environment / "manifest.json"
        manifest.write_text(json.dumps({
            "schema_version": "acs-p1-runtime-environment/1",
            "files": {
                "p1_profile_probe.py": {
                    "sha256": runner.digest_bytes(probe.read_bytes()), "mode": 0o700,
                },
                "bin/python": {
                    "sha256": runner.digest_bytes(python_wrapper.read_bytes()), "mode": 0o700,
                },
            },
        }), encoding="utf-8")
        manifest.chmod(0o600)
        self.plan["runtime_profile"] = {
            "profile_path": str(profile),
            "profile_sha256": runner.digest_bytes(profile.read_bytes()),
            "runtime_environment_root": str(environment),
            "runtime_environment_manifest_sha256": runner.digest_bytes(manifest.read_bytes()),
            "network_mode": "host_loopback_providers",
            "postgresql_endpoint": "127.0.0.1:54329",
            "temporal_endpoint": "127.0.0.1:7239",
        }
        self.plan["profile"] = "p1-loopback-provider"
        self.write_plan()
        return profile, environment, manifest

    def test_init_emits_only_not_run_and_invokes_offline_validator(self):
        state = self.initialize()
        record = json.loads((self.run_dir / "gate-record.json").read_text())
        validation = json.loads((self.run_dir / "validation.json").read_text())
        self.assertEqual(record["status"], "not_run")
        self.assertEqual(len(record["scenarios"]), 18)
        self.assertTrue(all(item["status"] == "not_run" for item in record["scenarios"]))
        self.assertTrue(validation["output"]["valid"])
        self.assertEqual(state["source_commit"], runner.source_identity(self.source).commit)
        self.assertEqual(state["source_tree"], runner.source_identity(self.source).tree)

    def test_missing_evidence_kinds_and_fields_remains_not_run(self):
        self.initialize()
        scenario = self.contract["gates"]["P1"]["scenarios"][0]
        with self.assertRaises(runner.EvidenceError):
            runner.run_scenario(self.run_dir, self.source, self.contract_path, scenario)
        state = json.loads((self.run_dir / "state.json").read_text())
        record = json.loads((self.run_dir / "gate-record.json").read_text())
        self.assertEqual(state["scenarios"][scenario]["status"], "not_run")
        self.assertEqual(record["status"], "not_run")

    def test_wrong_hash_is_rejected_on_resume_audit(self):
        self.initialize()
        path = self.run_dir / "evidence" / "machine" / "raw-os.json"
        path.write_bytes(path.read_bytes() + b"tampered")
        with self.assertRaises(runner.EvidenceError):
            runner.audit_run(self.run_dir, self.source, self.contract_path)

    def test_command_evidence_ref_cannot_point_to_other_scenario_or_command(self):
        state = self.initialize()
        scenario = next(iter(self.plan["scenarios"]))
        command = {
            "command_id": "logical:one:command", "kind": "command_output",
            "argv": ["/usr/bin/python3", "-c", "print('{}')"],
            "evidence_fields": ["raw_outputs"],
        }
        expected = "evidence/" + scenario + "/" + runner.digest(command["command_id"]) + (
            "/stdout.json"
        )
        path = self.run_dir / expected
        runner.write_json(path, {"run_id": state["run_id"], "scenario_id": scenario,
                                 "command_id": command["command_id"],
                                 "source_commit": state["source_commit"],
                                 "source_tree": state["source_tree"],
                                 "binding_sha256": state["binding_sha256"]})
        stored = {
            "kind": command["kind"], "evidence_fields": command["evidence_fields"],
            "argv_sha256": runner.digest(command["argv"]),
            "output": runner.file_ref(path, self.run_dir),
        }
        state["scenarios"][scenario]["commands"][command["command_id"]] = stored
        self.plan["scenarios"][scenario] = [command]
        alternate = self.run_dir / "evidence" / "OTHER" / runner.digest("other") / "stdout.json"
        runner.write_json(alternate, runner.strict_json(path.read_bytes()))
        stored["output"] = runner.file_ref(alternate, self.run_dir)
        with self.assertRaisesRegex(runner.EvidenceError, "path differs"):
            runner.audit_commands(state, self.plan, self.run_dir)

    def test_mixed_baseline_is_rejected(self):
        self.initialize()
        state_path = self.run_dir / "state.json"
        state = json.loads(state_path.read_text())
        state["source_commit"] = "f" * 40
        runner.write_json(state_path, state)
        with self.assertRaisesRegex(runner.RunnerError, "HMAC"):
            runner.load_run(self.run_dir, self.source, self.contract_path)

    def test_state_machine_binding_and_source_tampering_fails_hmac(self):
        self.initialize()
        path = self.run_dir / "state.json"
        original = path.read_bytes()
        for field, changed in (
            ("machine_id", "forged-machine"),
            ("source_commit", "f" * 40),
            ("source_tree", "e" * 40),
            ("binding_sha256", "d" * 64),
        ):
            with self.subTest(field=field):
                state = json.loads(original)
                state[field] = changed
                runner.write_json(path, state)
                with self.assertRaisesRegex(runner.RunnerError, "HMAC"):
                    runner.load_state(self.run_dir)
                path.write_bytes(original)

    def test_declared_two_machine_process_alias_is_rejected(self):
        self.plan["machines"] = ["process-a", "process-b"]
        with self.assertRaises(runner.PlanError):
            runner.validate_plan(self.plan, self.contract)

    def test_resume_reobserves_physical_machine(self):
        self.initialize()
        with (mock.patch.object(runner, "host_fingerprint", return_value=("f" * 64, {})),
              self.assertRaisesRegex(runner.RunnerError, "physical Machine")):
            runner.load_run(self.run_dir, self.source, self.contract_path)

    def test_run_directory_inside_formal_source_is_rejected(self):
        with self.assertRaisesRegex(runner.RunnerError, "outside the formal source"):
            runner.require_external_run_dir(self.source / "gates" / "forbidden-run", self.source)

    def test_old_component_or_second_process_probe_cannot_change_run_identity(self):
        state = self.initialize()
        command = {
            "command_id": "probe-1", "kind": "os", "argv": ["probe"],
            "evidence_fields": ["raw_outputs"],
        }
        started = datetime.now(UTC) - timedelta(seconds=1)
        finished = datetime.now(UTC) + timedelta(seconds=1)
        value = self.probe_value(state, command)
        for field, changed in (
            ("run_id", "old-run"),
            ("source_commit", "e" * 40),
            ("source_tree", "d" * 40),
            ("machine_id", "process-two-as-machine"),
            ("binding_sha256", "c" * 64),
            ("versions", {"core": "old-component"}),
        ):
            with self.subTest(field=field):
                candidate = dict(value)
                candidate[field] = changed
                with self.assertRaises(runner.EvidenceError):
                    runner.validate_probe(candidate, state, next(iter(self.plan["scenarios"])), command, started, finished)

    def probe_value(self, state, command):
        scenario = next(iter(self.plan["scenarios"]))
        return {
            "schema_version": runner.PROBE_SCHEMA,
            "status": "passed",
            "run_id": state["run_id"],
            "scenario_id": scenario,
            "command_id": command["command_id"],
            "evidence_kind": command["kind"],
            "source_commit": state["source_commit"],
            "source_tree": state["source_tree"],
            "binding_sha256": state["binding_sha256"],
            "profile": state["binding"]["profile"],
            "machine_id": state["machine_id"],
            "node_id": state["node_id"],
            "direction": state["binding"]["direction"],
            "versions": state["version_binding"],
            "observed_at": datetime.now(UTC).isoformat(),
            "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            "operation_ids": ["operation-1"],
            "message_ids": ["message-1"],
            "event_ids": ["event-1"],
            "receipt_ids": ["receipt-1"],
            "observer": "fixture-observer",
            "owner": "fixture-owner",
            "facts": {
                "fault_injected": True,
                "source_readback_verified": True,
                "artifact_readback_verified": True,
                "effect_readback_verified": True,
                "recovery_verified": True,
            },
        }

    def test_actual_command_output_is_bound_and_hashed_without_passing_gate(self):
        state = self.initialize()
        scenario = next(iter(self.plan["scenarios"]))
        command = {
            "command_id": "actual-probe", "kind": "command_output",
            "argv": ["/usr/bin/python3", "-c", (
                "import json,os;from datetime import datetime,timezone;"
                "v={k.lower().replace('acs_gate_',''):os.environ[k] for k in "
                "['ACS_GATE_RUN_ID','ACS_GATE_SCENARIO_ID','ACS_GATE_COMMAND_ID',"
                "'ACS_GATE_EVIDENCE_KIND','ACS_GATE_SOURCE_COMMIT','ACS_GATE_SOURCE_TREE',"
                "'ACS_GATE_BINDING_SHA256','ACS_GATE_PROFILE','ACS_GATE_MACHINE_ID',"
                "'ACS_GATE_NODE_ID','ACS_GATE_DIRECTION']};"
                "v.update(schema_version='acs-p1-gate-probe-result/1',status='passed',"
                "versions=json.loads(os.environ['ACS_GATE_VERSIONS_JSON']),"
                "observed_at=datetime.now(timezone.utc).isoformat(),"
                "expires_at=os.environ['ACS_GATE_EXPIRES_AT'],operation_ids=['op'],"
                "message_ids=['msg'],event_ids=['evt'],receipt_ids=['rcpt'],"
                "observer='observer',owner='owner',facts={});print(json.dumps(v))"
            )],
            "evidence_fields": ["raw_outputs"],
        }
        if not state["sandbox"]["available"]:
            with self.assertRaises(runner.SandboxUnavailable):
                runner.execute_command(state, self.plan, scenario, command, self.run_dir, self.source)
            return
        result = runner.execute_command(state, self.plan, scenario, command, self.run_dir, self.source)
        path = runner.validate_ref(result["output"], self.run_dir)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["output"]["sha256"], runner.digest_bytes(path.read_bytes()))
        record = json.loads((self.run_dir / "gate-record.json").read_text())
        self.assertEqual(record["status"], "not_run")

    def test_secret_output_is_redacted_and_blocked(self):
        state = self.initialize()
        scenario = next(iter(self.plan["scenarios"]))
        command = {
            "command_id": "secret-probe", "kind": "command_output",
            "argv": ["/usr/bin/python3", "-c", "print('password=hunter2')"],
            "evidence_fields": ["raw_outputs"],
        }
        if not state["sandbox"]["available"]:
            with self.assertRaises(runner.SandboxUnavailable):
                runner.execute_command(state, self.plan, scenario, command, self.run_dir, self.source)
            return
        with self.assertRaisesRegex(runner.EvidenceError, "secret-like"):
            runner.execute_command(state, self.plan, scenario, command, self.run_dir, self.source)
        failure = self.run_dir / "evidence" / scenario / runner.digest("secret-probe") / (
            "redacted-failure.txt"
        )
        self.assertNotIn("hunter2", failure.read_text())
        self.assertIn("[REDACTED]", failure.read_text())

    def test_secret_in_plan_is_rejected_before_run_directory_creation(self):
        self.plan["policy"] = "password=hunter2"
        self.write_plan()
        with self.assertRaisesRegex(runner.PlanError, "forbidden in the runner plan"):
            self.initialize()
        self.assertFalse(self.run_dir.exists())

    def test_uri_userinfo_secret_scanner_covers_encoded_and_ipv6_boundaries(self):
        values = (
            b"postgresql://user:private-value@127.0.0.1:54329/db",
            b"postgres://user%3Aprivate-value@[::1]:54329/db",
            b"postgres://user%3aprivate-value@localhost/db",
            b"custom+transport://token-only@host.invalid:7443/path",
            b"custom://:password-only@host.invalid/path",
        )
        for value in values:
            with self.subTest(value=value):
                self.assertTrue(runner.secret_findings(value))
                sanitized = runner.redacted(value)
                self.assertIn(b"[REDACTED]", sanitized)
                self.assertNotIn(b"private-value", sanitized)
                self.assertNotIn(b"password-only", sanitized)
                self.assertNotIn(b"token-only", sanitized)
        self.assertEqual(runner.secret_findings(b"C:\\Users\\runner\\profile.json"), [])

    def test_former_source_write_commands_are_contained_and_blocked(self):
        state = self.initialize()
        scenario = next(iter(self.plan["scenarios"]))
        commands = [
            ["/usr/bin/python3", "-c", "from pathlib import Path;Path('gates/fake-pass.json').write_text('{}');print('{}')"],
            ["/usr/bin/python3", "-c", "from pathlib import Path;Path('tracked.txt').write_text('changed');print('{}')"],
            ["/usr/bin/python3", "-c", "from pathlib import Path;Path('ignored').mkdir(exist_ok=True);Path('ignored/secret.txt').write_text('password=hunter2');print('{}')"],
            ["git", "add", "tracked.txt"],
            ["git", "reset", "--hard"],
            ["/usr/bin/python3", "-c", "from pathlib import Path;Path('gates/existing.json').write_text('replaced');print('{}')"],
        ]
        for index, argv in enumerate(commands):
            command = {
                "command_id": f"contained-{index}", "kind": "command_output",
                "argv": argv, "evidence_fields": ["raw_outputs"],
            }
            with self.subTest(argv=argv), self.assertRaises(runner.EvidenceError):
                runner.execute_command(
                    state, self.plan, scenario, command, self.run_dir, self.source,
                )
            current = runner.collect_source_guard(self.source)
            self.assertEqual(current["inventory_sha256"], state["source_guard"]["inventory_sha256"])
        self.assertFalse((self.source / "gates" / "fake-pass.json").exists())
        self.assertEqual((self.source / "tracked.txt").read_text(), "tracked baseline\n")
        self.assertEqual((self.source / "gates" / "existing.json").read_text(), "{}\n")
        self.assertFalse((self.source / "ignored").exists())

    def test_encoded_formal_path_is_invisible_inside_os_sandbox(self):
        state = self.initialize()
        scenario = next(iter(self.plan["scenarios"]))
        encoded = base64.b64encode(str(self.source / "tracked.txt").encode()).decode()
        command = {
            "command_id": "encoded-path", "kind": "command_output",
            "argv": ["/usr/bin/python3", "-c", (
                "import base64,pathlib;"
                f"p=pathlib.Path(base64.b64decode('{encoded}').decode());"
                "p.write_text('transient');p.write_text('tracked baseline\\n');print('{}')"
            )],
            "evidence_fields": ["raw_outputs"],
        }
        with self.assertRaises(runner.EvidenceError):
            runner.execute_command(state, self.plan, scenario, command, self.run_dir, self.source)
        self.assertEqual((self.source / "tracked.txt").read_text(), "tracked baseline\n")

    def test_snapshot_mode_change_is_rejected_before_probe(self):
        state = self.initialize()
        if not state["sandbox"]["available"]:
            return
        path = self.run_dir / "source-snapshot" / "tracked.txt"
        path.chmod(0o600)
        command = {
            "command_id": "snapshot-mode", "kind": "command_output",
            "argv": ["/usr/bin/true"], "evidence_fields": ["raw_outputs"],
        }
        with self.assertRaisesRegex(runner.EvidenceError, "snapshot file is writable"):
            runner.execute_command(
                state, self.plan, next(iter(self.plan["scenarios"])), command,
                self.run_dir, self.source,
            )

    def test_new_clean_commit_cannot_resume_or_be_synced_by_state_edit(self):
        self.initialize()
        (self.source / "tracked.txt").write_text("new commit\n", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=self.source, check=True)
        subprocess.run(["git", "commit", "-qm", "new clean commit"], cwd=self.source, check=True)
        with self.assertRaises(runner.SourceMutationError):
            runner.load_run(self.run_dir, self.source, self.contract_path)
        state = runner.load_state(self.run_dir)
        self.assertTrue(state["source_compromised"])
        current = runner.source_identity(self.source)
        forged = dict(state, source_commit=current.commit, source_tree=current.tree,
                      source_compromised=False)
        runner.write_json(self.run_dir / "state.json", forged)
        with self.assertRaisesRegex(runner.RunnerError, "HMAC"):
            runner.load_state(self.run_dir)

    def test_source_guard_records_mutation_without_finalizing(self):
        self.initialize()
        validation = self.run_dir / "validation.json"
        validation_hash = runner.digest_bytes(validation.read_bytes())
        attack = self.source / "gates" / "fake-pass.json"
        attack.write_text('{"status":"passed"}', encoding="utf-8")
        with self.assertRaisesRegex(runner.SourceMutationError, "source inventory"):
            runner.load_run(self.run_dir, self.source, self.contract_path)
        state = json.loads((self.run_dir / "state.json").read_text())
        report = json.loads((self.run_dir / "source-mutation.json").read_text())
        self.assertTrue(state["source_compromised"])
        self.assertEqual(state["gate_status"], "blocked")
        self.assertEqual(report["result"], "blocked-no-finalize")
        self.assertIn("gates/fake-pass.json", report["delta"]["changed_paths"])
        self.assertEqual(runner.digest_bytes(validation.read_bytes()), validation_hash)
        attack.unlink()

    def test_guard_detects_tracked_untracked_ignored_index_and_gate_replacement(self):
        def changed_since(before):
            return runner.collect_source_guard(self.source)["inventory_sha256"] != before["inventory_sha256"]

        before = runner.collect_source_guard(self.source)
        fake = self.source / "gates" / "untracked.json"
        fake.write_text("{}", encoding="utf-8")
        self.assertTrue(changed_since(before))
        fake.unlink()

        before = runner.collect_source_guard(self.source)
        (self.source / "tracked.txt").write_text("changed", encoding="utf-8")
        self.assertTrue(changed_since(before))
        subprocess.run(["git", "restore", "tracked.txt"], cwd=self.source, check=True)

        before = runner.collect_source_guard(self.source)
        ignored = self.source / "ignored"
        ignored.mkdir()
        (ignored / "secret.key").write_text("private", encoding="utf-8")
        self.assertTrue(changed_since(before))
        shutil.rmtree(ignored)

        (self.source / "tracked.txt").write_text("staged", encoding="utf-8")
        before_add = runner.collect_source_guard(self.source)
        subprocess.run(["git", "add", "tracked.txt"], cwd=self.source, check=True)
        self.assertTrue(changed_since(before_add))
        before_reset = runner.collect_source_guard(self.source)
        subprocess.run(["git", "reset", "--mixed", "HEAD"], cwd=self.source, check=True, capture_output=True)
        self.assertTrue(changed_since(before_reset))
        subprocess.run(["git", "restore", "tracked.txt"], cwd=self.source, check=True)

        gate = self.source / "gates" / "existing.json"
        before = runner.collect_source_guard(self.source)
        replacement = self.source / "gate-replacement.tmp"
        replacement.write_text("{}\n", encoding="utf-8")
        os.replace(replacement, gate)
        self.assertTrue(changed_since(before))
        subprocess.run(["git", "restore", "gates/existing.json"], cwd=self.source, check=True)
        self.assertEqual(
            subprocess.run(
                ["git", "status", "--porcelain"], cwd=self.source,
                check=True, capture_output=True, text=True,
            ).stdout,
            "",
        )

    def test_large_source_guard_is_chunked_outside_bounded_state_and_resumes(self):
        bulk = self.source / "bulk"
        bulk.mkdir()
        for index in range(10_800):
            (bulk / f"untracked-{index:05d}-long-inventory-name.txt").write_text(
                "x", encoding="utf-8",
            )
        state = self.initialize()
        state_bytes = (self.run_dir / "state.json").read_bytes()
        self.assertLess(len(state_bytes), runner.MAX_OUTPUT_BYTES)
        self.assertNotIn(b"untracked-10799", state_bytes)
        summary = state["source_guard"]
        manifest_path = runner.validate_ref(summary["manifest"], self.run_dir)
        manifest = runner.strict_json(manifest_path.read_bytes())
        self.assertGreater(manifest["chunk_count"], 1)
        self.assertEqual(summary["entry_count"], manifest["entry_count"])
        restored = runner.load_source_guard(state, self.run_dir)
        self.assertIn("bulk/untracked-10799-long-inventory-name.txt", restored["untracked"])
        self.assertEqual(runner.audit_run(
            self.run_dir, self.source, self.contract_path,
        )["status"], "not_run")

    def test_initialize_failure_removes_private_stage_and_never_adopts_run(self):
        with (
            mock.patch.object(
                runner, "persist_source_guard",
                side_effect=runner.RunnerError("injected guard failure"),
            ),
            self.assertRaisesRegex(runner.RunnerError, "injected guard failure"),
        ):
            self.initialize()
        self.assertFalse(self.run_dir.exists())
        self.assertEqual(list(self.base.glob(f".{self.run_dir.name}.stage-*")), [])

    @unittest.skipUnless(os.name == "posix", "runtime profile mount is POSIX-only")
    def test_runtime_profile_is_pinned_and_probe_receives_only_fixed_sandbox_paths(self):
        profile, environment, _manifest = self.configure_runtime_profile()
        state = self.initialize()
        public = state["runtime_profile"]
        self.assertNotIn(str(profile), json.dumps(public))
        self.assertNotIn(str(environment), json.dumps(public))
        probe_env = runner.probe_environment(state, "P1-DOMAIN-TRANSACTION", {
            "command_id": "profile", "kind": "os", "argv": ["/bin/true"],
            "evidence_fields": ["raw_outputs"],
        })
        self.assertEqual(probe_env["ACS_GATE_RUNTIME_PROFILE"], "/run/acs-p1/profile.json")
        self.assertEqual(probe_env["ACS_GATE_RUNTIME_ROOT"], "/run/acs-p1/runtime")
        self.assertNotIn(str(profile), json.dumps(probe_env))
        if state["sandbox"]["available"]:
            command = {
                "command_id": "profile-secret", "kind": "command_output",
                "argv": ["/usr/bin/python3", "-c", (
                    "print(open('/run/acs-p1/profile.json',encoding='utf-8').read())"
                )],
                "evidence_fields": ["raw_outputs"],
            }
            with self.assertRaisesRegex(runner.EvidenceError, "secret-like"):
                runner.execute_command(
                    state, self.plan, "P1-DOMAIN-TRANSACTION", command,
                    self.run_dir, self.source,
                )
            failure = self.run_dir / "evidence" / "P1-DOMAIN-TRANSACTION" / (
                runner.digest("profile-secret")
            ) / "redacted-failure.txt"
            self.assertNotIn("private-value", failure.read_text())

    @unittest.skipUnless(os.name == "posix", "sandbox argv is POSIX-only")
    def test_default_profile_has_no_runtime_mount(self):
        state = self.initialize()
        if not state["sandbox"]["available"]:
            self.skipTest("reviewed bubblewrap unavailable")
        command = {
            "command_id": "default-mounts", "kind": "os", "argv": ["/bin/true"],
            "evidence_fields": ["raw_outputs"],
        }
        argv, _output = runner.sandbox_command(
            state, self.plan, self.run_dir, "P1-DOMAIN-TRANSACTION", command,
            runner.probe_environment(state, "P1-DOMAIN-TRANSACTION", command),
        )
        self.assertNotIn("/run/acs-p1/profile.json", argv)
        self.assertNotIn("/run/acs-p1/runtime", argv)

    @unittest.skipUnless(os.name == "posix", "runtime profile mount is POSIX-only")
    def test_runtime_profile_rejects_mode_symlink_digest_extra_and_remote_endpoint(self):
        profile, environment, _manifest = self.configure_runtime_profile()
        valid = dict(self.plan["runtime_profile"])
        original_profile = profile.read_bytes()
        profile.chmod(0o644)
        with self.assertRaises(runner.PlanError):
            runner.validate_runtime_profile(valid)
        profile.chmod(0o600)
        for changed in (
            {**valid, "profile_sha256": "f" * 64},
            {**valid, "postgresql_endpoint": "10.0.0.8:5432"},
        ):
            with self.assertRaises(runner.PlanError):
                runner.validate_runtime_profile(changed)
        changed_profile = json.loads(profile.read_text())
        changed_profile["postgres_dsn"] = "postgresql://user:value@10.0.0.8:5432/db"
        profile.write_text(json.dumps(changed_profile), encoding="utf-8")
        profile.chmod(0o600)
        with self.assertRaisesRegex(runner.PlanError, "not reviewed loopback"):
            runner.validate_runtime_profile({
                **valid, "profile_sha256": runner.digest_bytes(profile.read_bytes()),
            })
        profile.write_bytes(original_profile)
        profile.chmod(0o600)
        extra = environment / "extra.py"
        extra.write_text("x", encoding="utf-8")
        extra.chmod(0o600)
        with self.assertRaises(runner.PlanError):
            runner.validate_runtime_profile(valid)
        extra.unlink()
        link = profile.parent / "linked.json"
        link.symlink_to(profile)
        with self.assertRaises((runner.PlanError, OSError)):
            runner.validate_runtime_profile({**valid, "profile_path": str(link)})
        self.assertEqual(runner.validate_runtime_profile(valid)["network_mode"], (
            "host_loopback_providers"
        ))

    @unittest.skipUnless(os.name == "posix", "descriptor walk is POSIX-only")
    def test_profile_and_environment_ancestor_symlinks_are_rejected(self):
        profile, environment, _manifest = self.configure_runtime_profile()
        alias = self.base / "ancestor-link"
        alias.symlink_to(profile.parent, target_is_directory=True)
        changed = {
            **self.plan["runtime_profile"],
            "profile_path": str(alias / profile.name),
        }
        with self.assertRaises((runner.PlanError, OSError)):
            runner.validate_runtime_profile(changed)
        alias.unlink()
        alias.symlink_to(environment, target_is_directory=True)
        changed = {
            **self.plan["runtime_profile"],
            "runtime_environment_root": str(alias),
        }
        with self.assertRaises((runner.PlanError, OSError)):
            runner.validate_runtime_profile(changed)

    @unittest.skipUnless(os.name == "posix", "descriptor walk is POSIX-only")
    def test_pinned_mount_rejects_parent_swap_without_spawning_probe(self):
        profile, _environment, _manifest = self.configure_runtime_profile()
        with runner.pinned_runtime_mounts(self.plan) as (sources, descriptors):
            displaced = self.base / "displaced-private"
            profile.parent.rename(displaced)
            profile.parent.mkdir(mode=0o700)
            profile.parent.chmod(0o700)
            (profile.parent / profile.name).write_bytes((displaced / profile.name).read_bytes())
            (profile.parent / profile.name).chmod(0o600)
            with self.assertRaises(runner.SandboxUnavailable):
                runner.assert_runtime_mounts_unchanged(self.plan, sources, descriptors)

    @unittest.skipUnless(os.name == "posix", "descriptor walk is POSIX-only")
    def test_nested_environment_symlink_and_invalid_bus_are_rejected(self):
        _profile, environment, manifest = self.configure_runtime_profile()
        binary = environment / "bin"
        displaced = environment / "bin-original"
        binary.rename(displaced)
        binary.symlink_to(displaced, target_is_directory=True)
        with self.assertRaises((runner.PlanError, OSError)):
            runner.validate_runtime_profile(self.plan["runtime_profile"])
        binary.unlink()
        displaced.rename(binary)
        original_stat = runner.os.stat

        def not_socket(path, *args, **kwargs):
            value = original_stat(path, *args, **kwargs)
            if path == "bus" and kwargs.get("dir_fd") is not None:
                data = list(value)
                data[0] = stat.S_IFREG | 0o600
                return os.stat_result(data)
            return value

        with (
            mock.patch.object(runner.os, "stat", side_effect=not_socket),
            self.assertRaisesRegex(runner.SandboxUnavailable, "user bus"),
            runner.pinned_runtime_mounts(self.plan),
        ):
            pass
        self.assertEqual(manifest.stat().st_mode & 0o777, 0o600)

    @unittest.skipUnless(os.name == "posix", "descriptor walk is POSIX-only")
    def test_wrong_user_bus_peer_uid_is_rejected(self):
        self.configure_runtime_profile()
        original = runner.socket.socket

        class WrongPeer:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def settimeout(self, _value):
                pass

            def connect(self, _path):
                pass

            def getsockopt(self, *_args):
                return struct.pack("3i", 1, os.geteuid() + 1, 1)

        def socket_factory(family, *args, **kwargs):
            return WrongPeer() if family == runner.socket.AF_UNIX else original(
                family, *args, **kwargs,
            )

        with (
            mock.patch.object(runner.socket, "socket", side_effect=socket_factory),
            self.assertRaisesRegex(runner.SandboxUnavailable, "peer changed"),
            runner.pinned_runtime_mounts(self.plan),
        ):
            pass


if __name__ == "__main__":
    unittest.main()
