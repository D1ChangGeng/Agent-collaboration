"""Optional web choice and AI setup steps, with no Platform or Tunnel changes."""
from __future__ import annotations

import importlib.util
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("web_bootstrap", ROOT / "scripts/acs_bootstrap.py")
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)
MACHINE = {"schema_version": "acs-install-machine/1", "machine_id": "a" * 64,
           "hostname": "chosen-host", "account": "owner", "user_home": "/home/owner",
           "platform": "linux", "python": "3.12.3", "transport": "local", "locator": None}


class WebSetupTests(unittest.TestCase):
    def test_missing_web_choice_prompts_and_apply_does_not_write_or_download(self):
        with (mock.patch.object(bootstrap, "observe_machine", return_value=MACHINE),
              mock.patch.object(bootstrap, "ensure_install_root", side_effect=AssertionError("write")),
              mock.patch.object(bootstrap, "release_metadata", side_effect=AssertionError("network"))):
            plan = bootstrap.install("v1.1.0", apply=False, project=None, project_id=None,
                                     runtime_host="local")
            self.assertEqual(plan["state"], "needs_web_choice")
            self.assertEqual(plan["web_setup"]["choices"], ["enable", "skip", "later"])
            with self.assertRaisesRegex(ValueError, "chatgpt-web"):
                bootstrap.install("v1.1.0", apply=True, project=None, project_id=None,
                                  runtime_host="local")

    def test_skip_and_later_have_distinct_states_and_no_tunnel_commands(self):
        for choice, state in (("skip", "skipped"), ("later", "deferred")):
            plan = bootstrap.chatgpt_setup(choice)
            self.assertEqual(plan["state"], state)
            self.assertNotIn("commands", plan)
            self.assertNotIn("owner_actions", plan)

    def test_enable_returns_owner_actions_and_actual_runtime_command(self):
        plan = bootstrap.chatgpt_setup("enable", "/home/owner/ACS Release/versions/next",
                                      "/home/owner/.agent-collaboration/runtime-surface.json",
                                      "tunnel_test12345")
        self.assertEqual(plan["state"], "awaiting_owner_actions")
        self.assertEqual(plan["runtime_process"]["command"], "sh")
        initialize = plan["commands"]["init"]
        self.assertIn("tunnel_test12345", initialize)
        command = initialize[initialize.index("--mcp-command") + 1]
        self.assertEqual(shlex.split(command), [plan["runtime_process"]["command"],
                                               *plan["runtime_process"]["args"]])
        self.assertIn("runtime.project_entry", command)
        self.assertIn("CONTROL_PLANE_API_KEY", json.dumps(plan["owner_actions"]))
        self.assertEqual(plan["verification"]["initial"], ["tools/list", "read_profile", "list_projects"])
        self.assertIn("load_project", plan["verification"]["after_project_adoption"])

    def test_enable_without_tunnel_id_gives_guidance_but_no_executable_init(self):
        plan = bootstrap.chatgpt_setup("enable", "/home/owner/release", "/home/owner/runtime.json")
        self.assertIsNone(plan["commands"]["init"])
        self.assertEqual(len(plan["owner_actions"]), 4)
        self.assertIn("developer", plan["official_documentation"]["connect"])

    def test_web_setup_rejects_secret_in_id_and_unsafe_remote_paths(self):
        for identifier in ("private-key-example", "tunnel_test\nextra"):
            with self.assertRaises(ValueError) as error:
                bootstrap.chatgpt_setup("enable", tunnel_id=identifier)
            self.assertNotIn(identifier, str(error.exception))
        with self.assertRaisesRegex(ValueError, "absolute paths"):
            bootstrap.chatgpt_setup("enable", "relative/root", "/absolute/config")

    def test_read_only_cli_contains_steps_and_no_private_key_argument(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/acs_web_setup.py"),
                                 "--choice", "enable", "--json"],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["state"], "awaiting_owner_actions")
        self.assertIn("official_documentation", plan)
        help_result = subprocess.run([sys.executable, str(ROOT / "scripts/acs_web_setup.py"), "--help"],
                                     capture_output=True, text=True, check=False)
        self.assertNotIn("--api-key", help_result.stdout)

    def test_remote_transports_forward_web_choice_and_public_tunnel_id(self):
        receipt = {"state": "machine_ready", "machine": MACHINE,
                   "current": "/home/owner/release", "runtime": {
                       "runtime_config_ref": "/home/owner/runtime.json"},
                   "web_setup": bootstrap.chatgpt_setup("enable", "/home/owner/release",
                                                        "/home/owner/runtime.json", "tunnel_example")}
        for kind, key, locator in (("ssh", "ssh_target", "authorized-host"),
                                   ("wsl", "wsl_distribution", "Ubuntu")):
            with (mock.patch.object(bootstrap, "observe_machine", return_value=MACHINE),
                  mock.patch.object(bootstrap.subprocess, "run", return_value=subprocess.CompletedProcess(
                      [], 0, "ACS_INSTALL_RECEIPT=" + json.dumps(receipt), "")) as execute):
                result = bootstrap.install("v1.1.0", apply=True, project=None, project_id=None,
                                           runtime_host=kind, chatgpt_web="enable",
                                           tunnel_id="tunnel_example", **{key: locator})
                request = json.loads(execute.call_args.kwargs["input"])
                self.assertEqual(request["chatgpt_web"], "enable")
                self.assertEqual(request["tunnel_id"], "tunnel_example")
                self.assertEqual(result["web_setup"]["state"], "awaiting_owner_actions")
                self.assertNotIn("CONTROL_PLANE_API_KEY", request)

    @unittest.skipIf(sys.platform == "win32", "applied Runtime host paths are Linux paths")
    def test_web_plan_and_choice_are_persisted_by_project_free_install(self):
        from tests.test_machine_install import METADATA, fake_fetch, runtime_result

        for tunnel_id in (None, "tunnel_example"):
            with self.subTest(tunnel_id=tunnel_id), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with (mock.patch.dict(os.environ, {"ACS_INSTALL_TUNNEL_ID": "tunnel_stale"}),
                      mock.patch.object(bootstrap, "install_root", return_value=root),
                      mock.patch.object(bootstrap, "observe_machine", return_value=MACHINE),
                      mock.patch.object(bootstrap, "release_metadata", return_value=METADATA),
                      mock.patch.object(bootstrap, "fetch", side_effect=fake_fetch),
                      mock.patch.object(bootstrap.subprocess, "run", return_value=runtime_result()) as execute):
                    receipt = bootstrap.install("v1.1.0", apply=True, project=None, project_id=None,
                                                runtime_host="local", chatgpt_web="enable",
                                                tunnel_id=tunnel_id)
                    state = json.loads((root / "state.json").read_text())
                    self.assertEqual(state["chatgpt_web"], "enable")
                    self.assertEqual(state["web_setup"]["state"], "awaiting_owner_actions")
                    self.assertEqual(state["web_setup"]["runtime_process"]["cwd"], receipt["current"])
                    environment = execute.call_args.kwargs["env"]
                    if tunnel_id is None:
                        self.assertNotIn("ACS_INSTALL_TUNNEL_ID", environment)
                    else:
                        self.assertEqual(environment["ACS_INSTALL_TUNNEL_ID"], tunnel_id)
                    self.assertEqual(state["web_setup"]["tunnel_id"], tunnel_id)
                    self.assertEqual(receipt["next_action"], receipt["web_setup"]["next_action"])

    @unittest.skipIf(sys.platform == "win32", "rollback Runtime version paths are Linux paths")
    def test_rollback_regenerates_tunnel_command_for_restored_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / "versions/previous"
            previous.mkdir(parents=True)
            (previous / "RELEASE-MANIFEST.json").write_text(json.dumps({
                "version": "1.0.0", "commit": "b" * 40, "tree": "c" * 40}))
            current = str(root / "versions/current")
            state = {"schema_version": bootstrap.SCHEMA, "machine": MACHINE, "current": current,
                     "previous": str(previous), "chatgpt_web": "enable", "runtime_config_ref": "/home/owner/config.json",
                     "web_setup": bootstrap.chatgpt_setup("enable", current, "/home/owner/config.json", "tunnel_example")}
            (root / "state.json").write_text(json.dumps(state))
            with (mock.patch.object(bootstrap, "install_root", return_value=root),
                  mock.patch.object(bootstrap, "observe_machine", return_value=MACHINE)):
                result = bootstrap.rollback()
            self.assertEqual(result["web_setup"]["runtime_process"]["cwd"], str(previous))
            self.assertNotIn(current, json.dumps(result["web_setup"]["commands"]))
            self.assertEqual(result["web_setup"]["state"], "awaiting_owner_actions")

    @unittest.skipIf(sys.version_info < (3, 12), "Runtime installer requires Python 3.12+")
    def test_runtime_cli_requires_web_decision_after_host_confirmation(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/acs_install.py"),
                                 "--host-confirmed", "--apply"],
                                capture_output=True, text=True, check=False,
                                env={key: value for key, value in os.environ.items()
                                     if key != "ACS_INSTALL_CHATGPT_WEB"})
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["state"], "needs_web_choice")

    @unittest.skipIf(sys.version_info < (3, 12), "Runtime installer requires Python 3.12+")
    def test_runtime_cli_receives_web_choice_and_public_id_from_bootstrap_environment(self):
        scripts = str(ROOT / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import acs_install as installer

        with (mock.patch.dict(os.environ, {"ACS_INSTALL_CHATGPT_WEB": "enable", "ACS_INSTALL_TUNNEL_ID": "tunnel_example"}),
              mock.patch.object(sys, "argv", ["acs_install.py", "--host-confirmed", "--apply"]),
              mock.patch.object(installer, "install", return_value={"state": "planned"}) as install,
              mock.patch("builtins.print")):
            self.assertEqual(installer.main(), 0)
        self.assertEqual(install.call_args.kwargs["chatgpt_web"], "enable")
        self.assertEqual(install.call_args.kwargs["tunnel_id"], "tunnel_example")


if __name__ == "__main__":
    unittest.main()
