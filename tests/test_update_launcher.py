"""Active Runtime selection and unattended installation preservation."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = str(ROOT / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launcher = load("update_launcher", "acs_launcher.py")
MACHINE = {"machine_id": "a" * 64, "account": "owner", "user_home": "/home/owner",
           "platform": "linux"}


def owner_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def release_fixture(root, version):
    active = root / "versions" / version
    files = {"runtime/project_entry.py": b"# Runtime entry\n",
             "docs/runtime/p2-mcp-tool-contract.json": b'{"profiles":{"root_manager":[]}}'}
    for name, content in files.items():
        path = active / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    python = active / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\nprintf '%s\\n' " + version + "\n", encoding="utf-8")
    python.chmod(0o700)
    manifest = {"schema_version": "acs-release-manifest/1", "version": version,
                "commit": "b" * 40, "tree": "c" * 40,
                "files": {name: {"bytes": len(content),
                                 "sha256": hashlib.sha256(content).hexdigest()}
                          for name, content in files.items()}}
    (active / "RELEASE-MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    return active


def activate(root, active, machine=MACHINE):
    config = root / "private/runtime-surface.json"
    owner_file(config, "{}")
    state = {"schema_version": "acs-bootstrap-state/1", "current": str(active),
             "version": "v" + active.name, "commit": "b" * 40, "tree": "c" * 40,
             "machine": machine, "runtime_config_ref": str(config),
             "auto_update": {"enabled": False}}
    owner_file(root / "state.json", json.dumps(state))
    (root / "current").write_text(str(active), encoding="utf-8")
    return state


class UpdateLauncherTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.root.chmod(0o700)
        self.first = release_fixture(self.root, "1.2.0")
        self.second = release_fixture(self.root, "1.3.0")
        self.actual_probe = launcher.observe_machine
        self.machine = mock.patch.object(launcher, "observe_machine", return_value=MACHINE)
        self.machine.start()
        self.addCleanup(self.machine.stop)
        activate(self.root, self.first)

    def test_same_command_selects_activation_and_rollback(self):
        for active in (self.first, self.second, self.first):
            activate(self.root, active)
            cwd, command = launcher.resolve_launch(self.root)
            self.assertEqual(cwd, active)
            self.assertEqual(command[0], str(active / ".venv/bin/python"))
            self.assertEqual(command[-2:], ["--profile", "root_manager"])
            self.assertEqual(command[command.index("--catalog") + 1],
                             str(active / "docs/runtime/p2-mcp-tool-contract.json"))

    def test_legacy_mirror_does_not_override_atomic_identity(self):
        (self.root / "current").write_text(str(self.second), encoding="utf-8")
        selected, _ = launcher.resolve_launch(self.root)
        self.assertEqual(selected, self.first)
        state = activate(self.root, self.first)
        for key, value in (("version", "v9.0.0"), ("tree", "d" * 40), ("commit", "b" * 41)):
            owner_file(self.root / "state.json", json.dumps({**state, key: value}))
            with self.assertRaisesRegex(ValueError, "identity"):
                launcher.resolve_launch(self.root)

    def test_machine_account_and_home_drift_are_rejected(self):
        for key in ("machine_id", "account", "user_home"):
            activate(self.root, self.first, {**MACHINE, key: "different"})
            with self.assertRaisesRegex(ValueError, "machine or account"):
                launcher.resolve_launch(self.root)

    def test_entry_and_catalog_byte_drift_are_rejected(self):
        for name in ("runtime/project_entry.py", "docs/runtime/p2-mcp-tool-contract.json"):
            path = self.first / name
            before = path.read_bytes()
            path.write_bytes(before + b"drift")
            with self.assertRaisesRegex(ValueError, "digest"):
                launcher.resolve_launch(self.root)
            path.write_bytes(before)

    def test_external_version_and_missing_private_config_are_rejected(self):
        state = activate(self.root, self.first)
        owner_file(self.root / "state.json", json.dumps({**state, "current": str(self.root)}))
        (self.root / "current").write_text(str(self.root), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "outside"):
            launcher.resolve_launch(self.root)
        state = activate(self.root, self.first)
        Path(state["runtime_config_ref"]).unlink()
        with self.assertRaisesRegex(ValueError, "unavailable"):
            launcher.resolve_launch(self.root)

    @unittest.skipIf(os.name == "nt", "Windows symlink creation requires a separate privilege")
    def test_uv_interpreter_final_symlink_is_allowed_but_source_links_are_rejected(self):
        python = self.first / ".venv/bin/python"
        python.unlink()
        python.symlink_to(sys.executable)
        self.assertEqual(launcher.resolve_launch(self.root)[1][0], str(python))
        entry = self.first / "runtime/project_entry.py"
        saved = self.root / "external-entry.py"
        saved.write_bytes(entry.read_bytes())
        entry.unlink()
        entry.symlink_to(saved)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            launcher.resolve_launch(self.root)

    def test_failure_keeps_mcp_stdout_empty_and_hides_paths(self):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = launcher.main(["--installation-root", str(self.root / "private-secret-path")])
        self.assertEqual(result, 2)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(json.loads(errors.getvalue()), {"error": "active_runtime_unavailable"})
        self.assertNotIn("private-secret-path", errors.getvalue())

    @unittest.skipUnless(sys.platform.startswith("linux"), "Actual Linux exec and stdio lifecycle")
    def test_actual_stable_process_executes_selected_release_on_activation_and_rollback(self):
        # Probe without the fixture mock; child launcher performs the same probe.
        machine = self.actual_probe()
        for active in (self.first, self.second, self.first):
            activate(self.root, active, machine)
            result = subprocess.run([sys.executable, str(ROOT / "scripts/acs_launcher.py"),
                                     "--installation-root", str(self.root)], capture_output=True,
                                    text=True, check=True)
            self.assertEqual(result.stdout, active.name + "\n")
            self.assertEqual(result.stderr, "")

    def test_background_catchup_is_detached_and_opt_out_does_not_spawn(self):
        state = activate(self.root, self.first)
        owner_file(self.root / "acs_bootstrap.py", "# stable updater\n")
        with mock.patch.object(launcher.sys, "platform", "linux"), mock.patch.object(
            launcher.subprocess, "Popen") as spawn:
            launcher.spawn_catchup(self.root)
            spawn.assert_not_called()
            state["auto_update"]["enabled"] = True
            owner_file(self.root / "state.json", json.dumps(state))
            launcher.spawn_catchup(self.root)
            self.assertEqual(spawn.call_args.args[0][-2:], ["--update", "--apply"])
            self.assertTrue(spawn.call_args.kwargs["start_new_session"])
            self.assertEqual(spawn.call_args.kwargs["stdout"], subprocess.DEVNULL)
            self.assertEqual(spawn.call_args.kwargs["env"]["ACS_UPDATE_ROOT"], str(self.root))


@unittest.skipIf(sys.version_info < (3, 12), "Runtime installer requires Python 3.12+")
class AutomaticInstallerTests(unittest.TestCase):
    def setUp(self):
        self.installer = load("update_installer", "acs_install.py")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.private = self.home / "private"
        self.private.mkdir(mode=0o700)
        self.active = self.home / "versions/1.3.0"
        self.previous = self.home / "versions/1.2.0"
        self.config = self.private / "runtime-surface.json"
        python = self.active / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
        python.parent.mkdir(parents=True)
        python.touch()
        owner_file(self.home / "acs_launcher.py", "# stable launcher\n")
        self.patches = [mock.patch.object(self.installer, "ROOT", self.active),
                        mock.patch.object(self.installer.Path, "home", return_value=self.home),
                        mock.patch.object(self.installer, "private_root", return_value=self.private),
                        mock.patch.object(self.installer, "observe_machine", return_value=MACHINE)]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_migration_replaces_only_exact_owned_local_harness_commands(self):
        old = self.installer.release_command(self.previous, self.config)
        codex = self.home / ".codex/config.toml"
        owner_file(codex, "model = 'gpt-6'\n\n[mcp_servers.agent_collaboration]\ncommand = "
                   + json.dumps(old[0]) + "\nargs = " + json.dumps(old[1:])
                   + "\nenabled_tools = ['read_profile']\n\n[mcp_servers.other]\ncommand = 'other'\n")
        opencode = self.home / ".config/opencode/opencode.json"
        owner_file(opencode, json.dumps({"provider": {"existing": {}}, "mcp": {
            "agent_collaboration": {"type": "local", "command": old, "enabled": True}}}))
        with mock.patch.dict(os.environ, {"ACS_INSTALL_ROOT": str(self.home),
                                          "ACS_LAUNCHER_PYTHON": sys.executable,
                                          "ACS_PREVIOUS_RELEASE": str(self.previous)}):
            self.installer.configure_harnesses(["codex", "opencode"], self.config)
            first = (codex.read_bytes(), opencode.read_bytes())
            self.installer.configure_harnesses(["codex", "opencode"], self.config)
        self.assertEqual(first, (codex.read_bytes(), opencode.read_bytes()))
        self.assertIn("model = 'gpt-6'", codex.read_text())
        self.assertIn("enabled_tools = ['read_profile']", codex.read_text())
        self.assertIn("[mcp_servers.other]", codex.read_text())
        configured = json.loads(opencode.read_bytes())
        self.assertIn("existing", configured["provider"])
        self.assertEqual(configured["mcp"]["agent_collaboration"]["command"],
                         [sys.executable, str(self.home / "acs_launcher.py"),
                          "--installation-root", str(self.home)])

    def test_migration_refuses_different_config_or_profile_before_any_client_write(self):
        old = self.installer.release_command(self.previous, self.private / "different.json")
        path = self.home / ".codex/config.toml"
        owner_file(path, "[mcp_servers.agent_collaboration]\ncommand = " + json.dumps(old[0])
                   + "\nargs = " + json.dumps(old[1:]) + "\n")
        before = path.read_bytes()
        with mock.patch.dict(os.environ, {"ACS_INSTALL_ROOT": str(self.home),
                                          "ACS_PREVIOUS_RELEASE": str(self.previous)}), \
                self.assertRaisesRegex(ValueError, "differs"):
            self.installer.configure_harnesses(["codex", "opencode"], self.config)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.home / ".config/opencode/opencode.json").exists())

    def test_automatic_update_reuses_providers_and_authority_without_project_or_client_mutation(self):
        owner_file(self.private / "install-machine.json", json.dumps(MACHINE))
        profile = {"schema_version": "acs-local-providers/2", "password": "s" * 60,
                   "postgres_port": 54329, "temporal_port": 7239, "compose_project": "acs-test"}
        owner_file(self.private / "local-providers.json", json.dumps(profile))
        before = {path.name: path.read_bytes() for path in self.private.iterdir()}
        report = {"source_backend": {"available": True}, "next_actions": [],
                  "tools": {name: {"available": True} for name in ("git", "uv", "docker")},
                  "runtime": {"state": "authorized"}}
        with (mock.patch.dict(os.environ, {"ACS_AUTOMATIC_UPDATE": "1"}),
              mock.patch.object(self.installer, "check_machine"),
              mock.patch.object(self.installer, "inspect", return_value=report),
              mock.patch.object(self.installer, "run") as run,
              mock.patch.object(self.installer, "provider_readback", return_value=[{"state": "healthy"}]),
              mock.patch.object(self.installer, "initialize_local_authority", return_value=self.config) as auth,
              mock.patch.object(self.installer, "owner_file", side_effect=AssertionError("identity write")),
              mock.patch.object(self.installer, "local_provider_environment", side_effect=AssertionError("provision")),
              mock.patch.object(self.installer, "migrate_private_identity", side_effect=AssertionError("migration")),
              mock.patch.object(self.installer, "configure_harnesses", side_effect=AssertionError("client write"))):
            result = self.installer.install(harnesses=["codex"], project=None, project_id=None,
                                           apply=True, host_confirmed=True, chatgpt_web="skip")
        run.assert_called_once_with("uv", "sync", "--frozen")
        self.assertTrue(auth.call_args.kwargs["require_existing"])
        self.assertEqual(result["harness_configs"], {})
        self.assertEqual(result["runtime_only"], True)
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.private.iterdir()})

    def test_automatic_project_and_missing_binding_fail_before_mutation(self):
        with (mock.patch.dict(os.environ, {"ACS_AUTOMATIC_UPDATE": "1"}),
              mock.patch.object(self.installer, "inspect", side_effect=AssertionError("inspection")),
              self.assertRaisesRegex(ValueError, "Runtime-only")):
            self.installer.install(harnesses=["codex"], project=self.home, project_id="project-test",
                                   apply=True, host_confirmed=True, chatgpt_web="skip")
        report = {"source_backend": {"available": True}, "next_actions": [],
                  "tools": {name: {"available": True} for name in ("git", "uv", "docker")}}
        with (mock.patch.dict(os.environ, {"ACS_AUTOMATIC_UPDATE": "1"}),
              mock.patch.object(self.installer, "check_machine"),
              mock.patch.object(self.installer, "inspect", return_value=report),
              mock.patch.object(self.installer, "run", side_effect=AssertionError("mutation")),
              self.assertRaisesRegex(ValueError, "machine binding")):
            self.installer.install(harnesses=["codex"], project=None, project_id=None,
                                   apply=True, host_confirmed=True, chatgpt_web="skip")

    def test_required_existing_authority_never_bootstraps_missing_identity(self):
        modules = {
            "runtime.auth": SimpleNamespace(LocalCredentialAuthenticator=mock.Mock()),
            "runtime.domain": SimpleNamespace(DomainAuthority=mock.Mock()),
            "runtime.models": SimpleNamespace(AuthenticatedContext=mock.Mock()),
            "runtime.project_service": SimpleNamespace(ProjectService=mock.Mock()),
            "runtime.surfaces": SimpleNamespace(SharedService=mock.Mock()),
        }
        with (mock.patch.dict(sys.modules, modules), self.assertRaisesRegex(ValueError, "complete existing")):
            self.installer.initialize_local_authority({}, require_existing=True)
        modules["runtime.domain"].DomainAuthority.assert_not_called()
        self.assertEqual(list(self.private.iterdir()), [])

    def test_existing_authority_readback_propagates_revocation_without_reprovisioning(self):
        for name in ("runtime-dsn", "runtime-credential", "runtime-surface.json"):
            owner_file(self.private / name, "existing")
        context = mock.MagicMock()
        service = mock.Mock()
        service.authenticate.side_effect = ValueError("grant revoked")
        settings = mock.Mock()
        context.__enter__.return_value = (service, settings)
        modules = {
            "runtime.auth": SimpleNamespace(LocalCredentialAuthenticator=mock.Mock()),
            "runtime.domain": SimpleNamespace(DomainAuthority=mock.Mock()),
            "runtime.models": SimpleNamespace(AuthenticatedContext=mock.Mock()),
            "runtime.project_service": SimpleNamespace(ProjectService=mock.Mock()),
            "runtime.surfaces": SimpleNamespace(SharedService=mock.Mock()),
            "runtime.surface_config": SimpleNamespace(configured_service=mock.Mock(return_value=context)),
        }
        before = {path.name: path.read_bytes() for path in self.private.iterdir()}
        with (mock.patch.dict(sys.modules, modules), self.assertRaisesRegex(ValueError, "revoked")):
            self.installer.initialize_local_authority({}, require_existing=True)
        modules["runtime.domain"].DomainAuthority.assert_not_called()
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.private.iterdir()})


if __name__ == "__main__":
    unittest.main()
