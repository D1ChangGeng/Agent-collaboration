"""Default policy, unattended boundaries, recovery and owner-local scheduling."""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import acs_bootstrap as bootstrap
import acs_update as updater

from tests.test_machine_install import MACHINE, METADATA, fake_fetch, runtime_result


class AutomaticUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = {"schema_version": bootstrap.SCHEMA, "version": "v1.3.0", "machine": MACHINE,
                      "current": str(self.root / "versions/1.3.0"), "previous": "older",
                      "harnesses": ["codex"], "runtime_only": True, "chatgpt_web": "later",
                      "auto_update": {"enabled": True, "next_check": 0}}
        bootstrap.write_state(self.root, self.state)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(bootstrap, "install_root", return_value=self.root).start()
        mock.patch.object(bootstrap, "observe_machine", return_value=MACHINE).start()

    def read(self):
        return json.loads((self.root / "state.json").read_text())

    def latest(self, version="v1.4.0"):
        return mock.patch.object(updater, "latest_release", return_value={"tag_name": version})

    def test_disabled_and_not_due_do_not_contact_provider(self):
        with mock.patch.object(updater, "latest_release", side_effect=AssertionError("network")):
            self.state["auto_update"]["enabled"] = False
            bootstrap.write_state(self.root, self.state)
            self.assertEqual(updater.run_update(self.root, apply=True)["state"], "disabled")
            self.state["auto_update"].update(enabled=True, next_check=10**12)
            bootstrap.write_state(self.root, self.state)
            self.assertEqual(updater.run_update(self.root, apply=True)["state"], "not_due")

    def test_no_downgrade_major_or_held_version_activation(self):
        for version, expected in (("v1.2.0", "up_to_date"), ("v1.3.0", "up_to_date"),
                                  ("v2.0.0", "review_required"), ("v1.4.0", "review_required")):
            self.state["auto_update"]["held_version"] = "v1.4.0"
            bootstrap.write_state(self.root, self.state)
            with self.latest(version), mock.patch.object(bootstrap, "_install", side_effect=AssertionError("install")):
                self.assertEqual(updater.run_update(self.root, apply=True, force=True)["state"], expected)
                self.assertEqual(self.read()["previous"], "older")

    def test_legacy_state_normalization_remains_readable(self):
        self.state.pop("auto_update")
        self.state.pop("harnesses")
        bootstrap.write_state(self.root, self.state)
        with self.latest():
            for _ in range(2):
                self.assertEqual(updater.run_update(self.root, apply=True, force=True)["state"], "enrollment_required")
                self.assertTrue(self.read()["auto_update"]["enabled"])

    def test_machine_drift_precedes_network_and_all_writes(self):
        before = (self.root / "state.json").read_bytes()
        with (mock.patch.object(bootstrap, "observe_machine", return_value={**MACHINE, "account": "foreign"}),
              self.latest(), self.assertRaisesRegex(ValueError, "binding_changed")):
            updater.run_update(self.root, apply=True)
        self.assertEqual((self.root / "state.json").read_bytes(), before)

    def test_concurrent_update_loser_has_no_provider_or_state_effect(self):
        before = (self.root / "state.json").read_bytes()
        with bootstrap.installation_lock(self.root), mock.patch.object(updater, "latest_release", side_effect=AssertionError("network")):
            self.assertEqual(updater.run_update(self.root, apply=True)["state"], "busy")
        self.assertEqual((self.root / "state.json").read_bytes(), before)

    def test_unattended_upgrade_reuses_bounded_install_choices(self):
        with self.latest(), mock.patch.object(bootstrap, "_install") as install:
            self.assertEqual(updater.run_update(self.root, apply=True)["state"], "updated")
        arguments = install.call_args.kwargs
        self.assertIsNone(arguments["project"])
        self.assertIsNone(arguments["project_id"])
        self.assertTrue(arguments["automatic"])
        self.assertTrue(arguments["runtime_only"])
        self.assertEqual(arguments["harnesses"], ["codex"])
        self.assertEqual(arguments["expected_account"], MACHINE["account"])
        self.assertEqual(arguments["chatgpt_web"], "later")

    def test_offline_failure_retains_activation_and_records_private_error_category(self):
        with mock.patch.object(updater, "latest_release", side_effect=OSError("private-credential-value")):
            result = updater.run_update(self.root, apply=True)
        state = self.read()
        self.assertEqual(result["state"], "failed")
        self.assertEqual(state["current"], self.state["current"])
        self.assertEqual(state["previous"], "older")
        self.assertNotIn("private-credential-value", json.dumps(state) + json.dumps(result))
        self.assertEqual(state["auto_update"]["last_error"], "update_failed")

    def test_latest_rejects_unpublished_or_nonstable_versions(self):
        for fields in ({"draft": True}, {"prerelease": True}, {"tag_name": "v1.4.0-rc1"}, {"tag_name": None}):
            payload = {"tag_name": "v1.4.0", "draft": False, "prerelease": False, **fields}
            with (mock.patch.object(updater.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(payload).encode())),
                  self.assertRaises(ValueError)):
                updater.latest_release(bootstrap.REPOSITORY)

    def test_compatibility_guards_schema_provider_and_catalog(self):
        files = {name: {"sha256": "same"} for name in
                 ("docker-compose.acs-local.yml", "docs/runtime/p2-mcp-tool-contract.json", "runtime/schema.sql", "LICENSE")}
        old = {"files": files}
        candidate = {"files": dict(files), "auto_update": {"compatibility": updater.COMPATIBILITY}}
        self.assertTrue(updater.compatible(old, candidate))
        for name in files:
            altered = {**candidate, "files": {**files, name: {"sha256": "changed"}}}
            self.assertFalse(updater.compatible(old, altered))
        self.assertFalse(updater.compatible(old, {"files": files}))

    def test_atomic_activation_failure_preserves_authoritative_state(self):
        before = (self.root / "state.json").read_bytes()
        (self.root / "current").write_text("old mirror")
        with mock.patch.object(bootstrap, "write_state", side_effect=OSError("disk")), self.assertRaises(OSError):
            bootstrap.activation(self.root, {**self.state, "current": "candidate"})
        self.assertEqual((self.root / "state.json").read_bytes(), before)
        self.assertEqual((self.root / "current").read_text(), "old mirror")

    def test_default_enabled_and_optout_persisted_by_install(self):
        for enabled in (True, False):
            (self.root / "state.json").unlink(missing_ok=True)
            with (mock.patch.object(bootstrap, "release_metadata", return_value=METADATA),
                  mock.patch.object(bootstrap, "fetch", side_effect=fake_fetch),
                  mock.patch.object(bootstrap.subprocess, "run", return_value=runtime_result()),
                  mock.patch.object(bootstrap, "update_module", return_value=mock.Mock(configure_schedule=mock.Mock(return_value={"backend": "connection"})))):
                arguments = {} if enabled else {"automatic_updates": False}
                bootstrap.install("v1.1.0", apply=True, project=None, project_id=None,
                                  runtime_host="local", chatgpt_web="skip", **arguments)
            self.assertEqual(self.read()["auto_update"]["enabled"], enabled)
            self.assertEqual(self.read()["harnesses"], ["codex", "opencode"])
            if not enabled:
                previous = self.read()["previous"]
                with (mock.patch.object(bootstrap, "release_metadata", return_value=METADATA),
                      mock.patch.object(bootstrap, "fetch", side_effect=fake_fetch),
                      mock.patch.object(bootstrap.subprocess, "run", return_value=runtime_result()),
                      mock.patch.object(bootstrap, "update_module", return_value=mock.Mock(configure_schedule=mock.Mock(return_value={"backend": "connection"})))):
                    bootstrap.install("v1.1.0", apply=True, project=None, project_id=None,
                                      runtime_host="local", chatgpt_web="skip")
                self.assertFalse(self.read()["auto_update"]["enabled"])
                self.assertEqual(self.read()["previous"], previous)

    def test_helper_changes_restored_after_failed_runtime_readback(self):
        old = self.root / "versions/1.0.0"
        old.mkdir(parents=True)
        (old / "RELEASE-MANIFEST.json").write_text(json.dumps({"version": "1.0.0", "files": {}}))
        self.state.update(current=str(old), version="v1.0.0", helper_digests={})
        for name in ("acs_bootstrap.py", "acs_update.py", "acs_launcher.py"):
            (self.root / name).write_bytes(b"old")
            self.state["helper_digests"][name] = hashlib.sha256(b"old").hexdigest()
        bootstrap.write_state(self.root, self.state)
        with (mock.patch.object(bootstrap, "release_metadata", return_value=METADATA),
              mock.patch.object(bootstrap, "fetch", side_effect=fake_fetch),
              mock.patch.object(bootstrap.subprocess, "run", return_value=runtime_result("unavailable")),
              self.assertRaisesRegex(ValueError, "authorization readback")):
            bootstrap.install("v1.1.0", apply=True, project=None, project_id=None,
                              runtime_host="local", chatgpt_web="skip")
        self.assertEqual(self.read(), self.state)
        for name in self.state["helper_digests"]:
            self.assertEqual((self.root / name).read_bytes(), b"old")

    def test_scheduler_units_owned_and_live_status_observed(self):
        with (mock.patch.object(updater.sys, "platform", "linux"),
              mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root / "config")}),
              mock.patch.object(updater.shutil, "which", side_effect=lambda name: "/usr/bin/systemctl" if name == "systemctl" else None),
              mock.patch.object(updater.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "active", "")) as execute):
            schedule = updater.configure_schedule(self.root, True, "/usr/bin/python3")
            self.assertEqual(schedule["backend"], "systemd_user")
            self.state["auto_update"]["schedule"] = schedule
            bootstrap.write_state(self.root, self.state)
            service = self.root / "config/systemd/user/acs-auto-update.service"
            service.write_text(service.read_text() + "# custom change\n")
            before = service.read_bytes()
            with self.assertRaisesRegex(ValueError, "ownership_review"):
                updater.configure_schedule(self.root, True, "/usr/bin/python3")
            self.assertEqual(service.read_bytes(), before)
            execute.return_value = subprocess.CompletedProcess([], 3, "inactive", "")
            self.assertEqual(updater.schedule_status(self.root, self.state["auto_update"])["state"], "inactive")

    def test_cron_rejects_newline_before_any_mutation(self):
        with (mock.patch.object(updater.sys, "platform", "linux"),
              mock.patch.object(updater.subprocess, "run", side_effect=AssertionError("mutation")),
              self.assertRaisesRegex(ValueError, "invalid_scheduler_path")):
            updater.configure_schedule(self.root, True, "/usr/bin/python3\ncommand")


if __name__ == "__main__":
    unittest.main()
