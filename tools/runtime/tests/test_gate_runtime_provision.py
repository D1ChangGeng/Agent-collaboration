from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.runtime import gate_runner
from tools.runtime import gate_runtime_provision as provisioner


@unittest.skipUnless(os.name == "posix", "provisioner is POSIX-only")
class GateRuntimeProvisionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.root.chmod(0o700)
        self.source = self.root / "site-source"
        self.source.mkdir(mode=0o700)
        (self.source / "dependency.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.profile_parent = self.root / "profile"
        self.profile_parent.mkdir(mode=0o700)
        self.profile = self.profile_parent / "profile.json"
        self.profile.write_text(json.dumps({
            "schema_version": "acs-p1-loopback-probe-profile/1",
            "profile": "p1-loopback-provider", "source_root": str(self.root),
            "python": sys.executable, "sandbox_python": "/run/acs-p1/runtime/bin/python",
            "postgres_dsn": "postgresql://fixture:value@127.0.0.1:54329/temporal",
            "temporal_endpoint": "127.0.0.1:7239", "temporal_namespace": "default",
            "versions": {
                "core": "fixture", "provider": {"temporal": "fixture"},
                "database": {"postgresql": "fixture", "sqlite": "fixture"},
                "protocol": "fixture", "harness": {"codex": "fixture", "opencode": "fixture"},
                "driver": {"codex": "fixture", "opencode": "fixture"},
                "os": {"linux": "fixture"},
            },
            "node_id": "fixture-node", "direction": "local-bidirectional",
            "codex_model_evidence": None, "opencode_model_evidence": None,
        }), encoding="utf-8")
        self.profile.chmod(0o600)
        self.destination = self.root / "installed"

    def tearDown(self):
        self.temporary.cleanup()

    def test_provision_writes_complete_manifest_and_postflight(self):
        result = provisioner.provision(self.source, self.destination, self.profile)
        self.assertEqual(result["file_count"], 3)
        self.assertEqual(self.destination.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.destination / "manifest.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            gate_runner.validate_runtime_profile({
                key: value for key, value in result.items() if key != "file_count"
            })["profile_sha256"],
            result["profile_sha256"],
        )
        plan = self.root / "plan.json"
        plan.write_text('{"runtime_profile":null}', encoding="utf-8")
        provisioner.attach_plan(plan, result)
        attached = json.loads(plan.read_text())["runtime_profile"]
        self.assertEqual(attached["runtime_environment_root"], str(self.destination))
        self.assertNotIn("file_count", attached)

    def test_symlink_source_and_postflight_failure_leave_no_destination(self):
        link = self.source / "linked.py"
        link.symlink_to(self.source / "dependency.py")
        with self.assertRaises(RuntimeError):
            provisioner.provision(self.source, self.destination, self.profile)
        self.assertFalse(self.destination.exists())
        link.unlink()
        original = provisioner.validate_runtime_profile
        calls = 0

        def fail_postflight(value):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise gate_runner.PlanError("postflight failure")
            return original(value)

        with (
            mock.patch.object(provisioner, "validate_runtime_profile", side_effect=fail_postflight),
            self.assertRaisesRegex(gate_runner.PlanError, "postflight failure"),
        ):
            provisioner.provision(self.source, self.destination, self.profile)
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.root.glob(".installed.stage-*")), [])

    def test_codex_owner_refs_are_paired_and_attached_to_plan(self):
        from tools.runtime.tests.test_p1_codex_lifecycle import scene_profile

        private = self.root / "codex-private"
        private.mkdir(mode=0o700)
        scene = private / "scene.json"
        scene.write_text(json.dumps(scene_profile()), encoding="utf-8")
        scene.chmod(0o600)
        budget = private / "budget.json"
        budget.write_text("{}", encoding="utf-8")
        budget.chmod(0o600)
        loopback = json.loads(self.profile.read_text(encoding="utf-8"))
        loopback["schema_version"] = "acs-p1-loopback-probe-profile/2"
        loopback["codex_scene_mode"] = "same-run-host-node"
        self.profile.write_text(json.dumps(loopback), encoding="utf-8")
        self.profile.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, "must be paired"):
            provisioner.provision(
                self.source,
                self.destination,
                self.profile,
                codex_scene_profile=scene,
            )
        self.assertFalse(self.destination.exists())
        budget.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, "bounded 0600"):
            provisioner.provision(
                self.source,
                self.destination,
                self.profile,
                codex_scene_profile=scene,
                budget_decision=budget,
            )
        self.assertFalse(self.destination.exists())
        budget.chmod(0o600)
        result = provisioner.provision(
            self.source,
            self.destination,
            self.profile,
            codex_scene_profile=scene,
            budget_decision=budget,
        )
        plan = self.root / "codex-plan.json"
        plan.write_text('{"runtime_profile":null}', encoding="utf-8")
        provisioner.attach_plan(plan, result)
        attached = json.loads(plan.read_text(encoding="utf-8"))["runtime_profile"]
        for name, path in (("codex_scene_profile", scene), ("budget_decision", budget)):
            self.assertEqual(attached[name]["path"], str(path))
            self.assertEqual(attached[name]["sha256"], provisioner.sha256(path))

    def test_opencode_owner_refs_are_paired_and_attached_to_plan(self):
        from tools.runtime.tests.test_p1_opencode_gate import scene as opencode_scene

        private = self.root / "opencode-private"
        private.mkdir(mode=0o700)
        scene = private / "scene.json"
        scene.write_text(json.dumps(opencode_scene()), encoding="utf-8")
        scene.chmod(0o600)
        budget = private / "budget.json"
        budget.write_text("{}", encoding="utf-8")
        budget.chmod(0o600)
        loopback = json.loads(self.profile.read_text(encoding="utf-8"))
        loopback["schema_version"] = "acs-p1-loopback-probe-profile/2"
        loopback["opencode_scene_mode"] = "same-run-host-node"
        self.profile.write_text(json.dumps(loopback), encoding="utf-8")
        self.profile.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, "must be paired"):
            provisioner.provision(
                self.source, self.destination, self.profile,
                opencode_scene_profile=scene,
            )
        self.assertFalse(self.destination.exists())
        result = provisioner.provision(
            self.source, self.destination, self.profile,
            opencode_scene_profile=scene,
            opencode_budget_decision=budget,
        )
        plan = self.root / "opencode-plan.json"
        plan.write_text('{"runtime_profile":null}', encoding="utf-8")
        provisioner.attach_plan(plan, result)
        attached = json.loads(plan.read_text(encoding="utf-8"))["runtime_profile"]
        for name, path in (
            ("opencode_scene_profile", scene), ("opencode_budget_decision", budget),
        ):
            self.assertEqual(attached[name]["path"], str(path))
            self.assertEqual(attached[name]["sha256"], provisioner.sha256(path))


class GateRuntimeProvisionWindowsTests(unittest.TestCase):
    def test_windows_fails_closed_before_destination_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                mock.patch.object(provisioner.os, "name", "nt"),
                self.assertRaisesRegex(RuntimeError, "POSIX-only"),
            ):
                provisioner.provision(root, root / "destination", root / "profile")
            self.assertFalse((root / "destination").exists())


if __name__ == "__main__":
    unittest.main()
