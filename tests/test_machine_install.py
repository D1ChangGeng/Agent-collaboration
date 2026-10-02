"""Machine selection and global setup regressions; no host is installed here."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("machine_install", ROOT / "scripts/acs_bootstrap.py")
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)
MACHINE = {"schema_version": "acs-install-machine/1", "machine_id": "a" * 64,
           "hostname": "selected-host", "platform": "linux", "account": "owner",
           "user_home": "/home/owner", "python": "3.12.3", "transport": "local", "locator": None}
METADATA = {"html_url": "https://github.com/D1ChangGeng/Agent-collaboration/releases/tag/v1.1.0",
            "assets": [{"name": "agent-collaboration-v1.1.0.zip", "browser_download_url": "archive"},
                       {"name": "SHA256SUMS.txt", "browser_download_url": "sums"}]}


def fake_fetch(url, path):
    if url == "sums":
        archive = path.parent / "agent-collaboration-v1.1.0.zip"
        path.write_text(bootstrap.digest(archive) + "  " + archive.name + "\n")
        return
    payload = {"scripts/acs_install.py": b"# verified Runtime installer\n"}
    manifest = {"schema_version": "acs-release-manifest/1", "version": "1.1.0",
                "commit": "b" * 40, "tree": "c" * 40,
                "files": {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                          for name, data in payload.items()}}
    payload.update({"RELEASE-MANIFEST.json": json.dumps(manifest).encode(),
                    "DEPENDENCIES.json": b"{}", "LICENSES.md": b"license"})
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in payload.items():
            entry = zipfile.ZipInfo("agent-collaboration-v1.1.0/" + name)
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data)


def runtime_result(state="authorized"):
    receipt = {"schema_version": "acs-install-plan/1", "state": "local_authority_ready",
               "runtime_config_ref": "/home/owner/.agent-collaboration/runtime-surface.json",
               "readback": {"runtime": {"state": state, "projects": []}}}
    return subprocess.CompletedProcess([], 0, "installer progress\n" + json.dumps(receipt), "")


class MachineInstallTests(unittest.TestCase):
    def test_unspecified_machine_needs_selection_and_apply_performs_no_io(self):
        with (mock.patch.object(bootstrap, "release_metadata", side_effect=AssertionError("network")),
              mock.patch.object(bootstrap, "ensure_install_root", side_effect=AssertionError("write"))):
            plan = bootstrap.install("v1.1.0", apply=False, project=None, project_id=None)
            self.assertEqual(plan["state"], "needs_machine_selection")
            with self.assertRaisesRegex(ValueError, "runtime-host"):
                bootstrap.install("v1.1.0", apply=True, project=None, project_id=None)

    def test_local_preview_and_identity_mismatch_do_not_create_state(self):
        with (mock.patch.object(bootstrap, "observe_machine", return_value=MACHINE),
              mock.patch.object(bootstrap, "release_metadata", return_value=METADATA),
              mock.patch.object(bootstrap, "ensure_install_root", side_effect=AssertionError("write"))):
            plan = bootstrap.install("v1.1.0", apply=False, project=None, project_id=None,
                                     runtime_host="local")
            self.assertEqual(plan["machine"]["machine_id"], MACHINE["machine_id"])
            with self.assertRaisesRegex(ValueError, "identity changed"):
                bootstrap.install("v1.1.0", apply=True, project=None, project_id=None,
                                  runtime_host="local", expected_machine_id="d" * 64)

    def test_account_and_home_drift_from_plan_block_before_any_installation_write(self):
        with (mock.patch.object(bootstrap, "observe_machine", return_value=MACHINE),
              mock.patch.object(bootstrap, "release_metadata", side_effect=AssertionError("download")),
              mock.patch.object(bootstrap, "ensure_install_root", side_effect=AssertionError("write"))):
            for expected in ({"expected_account": "another-owner"},
                             {"expected_user_home": "/home/another-owner"}):
                with self.assertRaisesRegex(ValueError, "since the installation plan"):
                    bootstrap.install("v1.1.0", apply=True, project=None, project_id=None,
                                      runtime_host="ssh", ssh_target="chosen-host",
                                      expected_machine_id=MACHINE["machine_id"], **expected)

    def test_global_install_without_project_runs_runtime_and_binds_machine(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "install"
            with (mock.patch.object(bootstrap, "install_root", return_value=target),
                  mock.patch.object(bootstrap, "observe_machine", return_value=MACHINE),
                  mock.patch.object(bootstrap, "release_metadata", return_value=METADATA),
                  mock.patch.object(bootstrap, "fetch", side_effect=fake_fetch),
                  mock.patch.object(bootstrap.subprocess, "run", return_value=runtime_result()) as execute):
                receipt = bootstrap.install("v1.1.0", apply=True, project=None, project_id=None,
                                            runtime_host="local", harnesses=["codex"])
                self.assertEqual(receipt["state"], "machine_ready")
                args = execute.call_args.args[0]
                self.assertIn("--apply", args)
                self.assertNotIn("--project", args)
                self.assertEqual(args[-1], "codex")
                self.assertEqual(execute.call_args.kwargs["env"]["ACS_INSTALL_MACHINE_ID"],
                                 MACHINE["machine_id"])
                state = json.loads((target / "state.json").read_text())
                self.assertEqual(state["machine"], MACHINE)
                self.assertEqual(state["current"], (target / "current").read_text())

    def test_failed_runtime_readback_preserves_previous_active_version(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / "current").write_text("previous")
            with (mock.patch.object(bootstrap, "install_root", return_value=target),
                  mock.patch.object(bootstrap, "observe_machine", return_value=MACHINE),
                  mock.patch.object(bootstrap, "release_metadata", return_value=METADATA),
                  mock.patch.object(bootstrap, "fetch", side_effect=fake_fetch),
                  mock.patch.object(bootstrap.subprocess, "run", return_value=runtime_result("unavailable")),
                  self.assertRaisesRegex(ValueError, "authorization readback")):
                bootstrap.install("v1.1.0", apply=True, project=None, project_id=None,
                                  runtime_host="local")
            self.assertEqual((target / "current").read_text(), "previous")

    def test_remote_machine_choice_uses_only_selected_target_during_preview(self):
        with mock.patch.object(bootstrap, "observe_machine", return_value=MACHINE) as probe:
            for kind, key, value in [("ssh", "ssh_target", "chosen-host"),
                                     ("wsl", "wsl_distribution", "Ubuntu")]:
                plan = bootstrap.install("v1.1.0", apply=False, project=None, project_id=None,
                                         runtime_host=kind, **{key: value})
                self.assertEqual(plan["state"], "planned")
                self.assertIn(mock.call(kind, value), probe.call_args_list)

    def test_remote_apply_pins_identity_and_returns_client_connection(self):
        receipt = {"machine": MACHINE, "current": "/home/owner/ACS Release/versions/1.1.0",
                   "runtime": json.loads(runtime_result().stdout.splitlines()[1]),
                   "state": "machine_ready"}
        with (mock.patch.object(bootstrap, "observe_machine", return_value=MACHINE),
              mock.patch.object(bootstrap.subprocess, "run", return_value=subprocess.CompletedProcess(
                  [], 0, "ACS_INSTALL_RECEIPT=" + json.dumps(receipt) + "\n", "")) as execute):
            result = bootstrap.install("v1.1.0", apply=True, project=None, project_id=None,
                                       runtime_host="ssh", ssh_target="chosen-host")
            sent = json.loads(execute.call_args.kwargs["input"])
            self.assertEqual(sent["machine_id"], MACHINE["machine_id"])
            self.assertEqual(sent["machine_binding"], bootstrap.machine_binding(MACHINE))
            self.assertIsNone(sent["project"])
            self.assertIn("chosen-host", execute.call_args.args[0])
            self.assertEqual(result["client_connection"]["command"], "ssh")
            self.assertIn("StrictHostKeyChecking=yes", result["client_connection"]["args"])
            self.assertEqual(result["client_connection"]["state"],
                             "requires_client_configuration_and_handshake")

    def test_windows_local_runtime_and_unsafe_ssh_target_are_rejected(self):
        with (mock.patch.object(bootstrap, "observe_machine", return_value={**MACHINE, "platform": "win32"}),
              self.assertRaisesRegex(ValueError, "Linux Runtime")):
            bootstrap.install("v1.1.0", apply=True, project=None, project_id=None,
                              runtime_host="local")
        for alias in ("-oProxyCommand=command", "host;command", "host\ncommand", None):
            with self.assertRaises(ValueError):
                bootstrap.transport_command("ssh", alias, bootstrap.HOST_PROBE)

    def test_existing_installation_on_other_machine_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / "state.json").write_text(json.dumps({"machine": {**MACHINE, "machine_id": "d" * 64}}))
            with (mock.patch.object(bootstrap, "install_root", return_value=target),
                  mock.patch.object(bootstrap, "observe_machine", return_value=MACHINE),
                  mock.patch.object(bootstrap, "release_metadata", return_value=METADATA),
                  mock.patch.object(bootstrap, "fetch", side_effect=AssertionError("download")),
                  self.assertRaisesRegex(ValueError, "different machine")):
                bootstrap.install("v1.1.0", apply=True, project=None, project_id=None,
                                  runtime_host="local")

    @unittest.skipIf(sys.version_info < (3, 12), "Runtime installer requires Python 3.12+")
    def test_runtime_only_skips_harness_installation_and_configuration(self):
        scripts = str(ROOT / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import acs_install as installer

        readiness = {"source_backend": {"available": True},
                     "tools": {name: {"available": True} for name in ("git", "uv", "docker")}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with (mock.patch.object(installer, "private_root", return_value=path),
                  mock.patch.object(installer.Path, "home", return_value=path),
                  mock.patch.object(installer, "observe_machine", return_value=MACHINE),
                  mock.patch.object(installer, "inspect", return_value=readiness),
                  mock.patch.object(installer, "run") as execute,
                  mock.patch.object(installer, "local_provider_environment", return_value=(path / "providers", {
                      "COMPOSE_PROJECT_NAME": "acs-isolated", "ACS_POSTGRES_PORT": "54330",
                      "ACS_TEMPORAL_PORT": "7240"})),
                  mock.patch.object(installer, "provider_readback", return_value=[]),
                  mock.patch.object(installer, "initialize_local_authority", return_value=path / "runtime.json"),
                  mock.patch.object(installer, "configure_harnesses", side_effect=AssertionError("client config"))):
                receipt = installer.install(harnesses=["codex"], project=None, project_id=None,
                                            apply=True, host_confirmed=True, runtime_only=True)
                self.assertEqual(receipt["harness_configs"], {})
                self.assertEqual(receipt["state"], "local_authority_ready")
                self.assertFalse(any("scripts/install_skill.py" in c.args for c in execute.call_args_list))
                bound = json.loads((path / "install-machine.json").read_text())
                self.assertEqual(bound["machine_id"], MACHINE["machine_id"])

    def test_remote_account_change_is_refused_before_installer_invocation(self):
        source = ("def observe_machine(): return " + repr({**MACHINE, "account": "other"}) + "\n"
                  "def machine_binding(m): return {k:m[k] for k in ('machine_id','account','user_home')}\n"
                  "def install(*a, **k): raise RuntimeError('installer must not run')\n").encode()
        request = {"bootstrap": base64.b64encode(source).decode("ascii"),
                   "sha256": hashlib.sha256(source).hexdigest(),
                   "machine_binding": bootstrap.machine_binding(MACHINE)}
        result = subprocess.run([sys.executable, "-c", bootstrap.REMOTE_INSTALL],
                                input=json.dumps(request), capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("account changed before installation", result.stderr)
        self.assertNotIn("installer must not run", result.stderr)

    def test_legacy_runtime_only_release_is_refused_before_runtime_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with (mock.patch.object(bootstrap, "install_root", return_value=target),
                  mock.patch.object(bootstrap, "observe_machine", return_value=MACHINE),
                  mock.patch.object(bootstrap, "release_metadata", return_value=METADATA),
                  mock.patch.object(bootstrap, "fetch", side_effect=fake_fetch),
                  mock.patch.object(bootstrap.subprocess, "run", side_effect=AssertionError("runtime")),
                  self.assertRaisesRegex(ValueError, "updated Runtime installer")):
                bootstrap.install("v1.1.0", apply=True, project=None, project_id=None,
                                  runtime_host="local", runtime_only=True)
            self.assertFalse((target / "current").exists())


if __name__ == "__main__":
    unittest.main()
