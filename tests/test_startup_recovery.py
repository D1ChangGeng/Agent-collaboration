"""Startup recovery lifecycle, ownership and stdio isolation tests."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("startup_under_test", ROOT / "scripts/acs_startup.py")
startup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(startup)


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux owner startup and fcntl supervision")
class StartupRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.active = self.root / "active"
        self.active.mkdir()
        self.private = self.root / "private"
        self.private.mkdir(mode=0o700)
        compose = self.active / "docker-compose.acs-local.yml"
        compose.write_text("services: {}\n")
        (self.active / "RELEASE-MANIFEST.json").write_text(json.dumps({"files": {
            compose.name: {"sha256": hashlib.sha256(compose.read_bytes()).hexdigest()}}}))
        self.write(self.root / "state.json", {"runtime_config_ref": str(self.private / "surface.json")})
        self.write(self.private / "local-providers.json", {"schema_version": "acs-local-providers/2",
            "compose_project": "acs-test", "password": "p" * 50, "postgres_port": 54329, "temporal_port": 7239})
        self.profile = self.root / "ssh.json"
        self.data = {"schema_version": "acs-private-ssh-startup/1", "root": str(self.root),
                     "target": "fixture-target", "control_socket": "control.sock",
                     "supervisor_lock": "supervisor.lock", "launch_lock": "launch.lock",
                     "local_forwards": [{"bind_port": 56443, "target_port": 56443}],
                     "remote_forwards": [{"bind_port": 55429, "target_port": 54329}]}
        self.write(self.profile, self.data)

    def write(self, path, value):
        path.write_text(json.dumps(value))
        path.chmod(0o600)

    def test_core_uses_saved_identity_private_environment_and_bounded_health(self):
        with mock.patch.object(startup, "command") as run:
            result = startup.ensure_core(self.root, self.active)
        self.assertEqual(result["core"], "services_ready")
        self.assertIn("--wait", run.call_args.args)
        self.assertIn("acs-test", run.call_args.args)
        self.assertNotIn("p" * 50, run.call_args.args)
        self.assertEqual(run.call_args.kwargs["env"]["ACS_POSTGRES_PASSWORD"], "p" * 50)
        self.assertEqual(run.call_args.kwargs["timeout"], 90)

    def test_core_failure_does_not_skip_independent_tunnel_recovery(self):
        self.write(self.root / "state.json", {"startup": {
            "web_profile_ref": str(self.root / "web.json"),
            "ssh_profile_ref": str(self.profile)}})
        with (mock.patch.object(startup, "ensure_core", side_effect=startup.StartupUnavailable("failure")),
              mock.patch.object(startup, "ensure_web", return_value={"web_tunnel": "supervision_requested"}) as web,
              mock.patch.object(startup, "ensure_ssh", side_effect=startup.StartupUnavailable("network")) as ssh):
            result = startup.restore_configured(self.root, self.active)
        web.assert_called_once()
        ssh.assert_called_once()
        self.assertEqual(result, {"core": "owner_repair_required", "web_tunnel": "supervision_requested", "ssh_tunnel": "owner_repair_required"})

    def test_login_maintenance_retries_after_recovery_failure(self):
        self.write(self.root / "state.json", {"runtime_config_ref": str(self.private / "surface.json"), "current": str(self.active)})
        with (mock.patch.object(startup, "restore_configured", side_effect=[startup.StartupUnavailable("offline"), {}]) as restore,
              mock.patch.object(startup.time, "sleep", side_effect=[None, KeyboardInterrupt]) as sleep,
              self.assertRaises(KeyboardInterrupt)):
            startup.maintain(self.root)
        self.assertEqual(restore.call_count, 2)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [30, 30])

    def test_tampered_compose_never_starts_services(self):
        (self.active / "docker-compose.acs-local.yml").write_text("changed")
        with mock.patch.object(startup, "command") as run, self.assertRaises(startup.StartupUnavailable):
            startup.ensure_core(self.root, self.active)
        run.assert_not_called()

    def test_missing_provider_does_not_provision_or_bootstrap(self):
        (self.private / "local-providers.json").unlink()
        with mock.patch.object(startup, "command") as run, self.assertRaises(OSError):
            startup.ensure_core(self.root, self.active)
        run.assert_not_called()

    def test_owner_opt_out_prevents_service_mutation(self):
        self.write(self.root / "state.json", {"runtime_config_ref": str(self.private / "surface.json"),
                                              "startup": {"enabled": False}})
        with mock.patch.object(startup, "command") as run:
            self.assertEqual(startup.ensure_core(self.root, self.active)["core"], "owner_disabled")
        run.assert_not_called()

    def test_forward_profile_closes_arbitrary_hosts_and_unsafe_paths(self):
        for changes in ({"target": "-oProxyCommand=bad"}, {"control_socket": "../escape"},
                        {"remote_forwards": [{"bind_port": 1, "target_port": 54329}]}):
            self.write(self.profile, dict(self.data, **changes))
            with self.assertRaises(startup.StartupUnavailable):
                startup.ssh_profile(self.profile)
        self.write(self.profile, self.data)
        command = startup.ssh_command(self.data)
        self.assertIn("127.0.0.1:55429:127.0.0.1:54329", command)
        self.assertIn("BatchMode=yes", command)
        self.assertIn("ServerAliveInterval=15", command)

    def test_concurrent_owned_supervisor_is_not_spawned_twice(self):
        with (mock.patch.object(startup, "supervisor_running", return_value=True),
              mock.patch.object(startup, "ssh_ready", return_value=True),
              mock.patch.object(startup.subprocess, "Popen") as spawn):
            self.assertEqual(startup.ensure_ssh(self.profile)["private_ssh"], "supervised")
        spawn.assert_not_called()

    def test_missing_supervisor_is_detached_and_stdio_is_not_inherited(self):
        with (mock.patch.object(startup, "supervisor_running", side_effect=[False, True]),
              mock.patch.object(startup, "ssh_ready", return_value=True),
              mock.patch.object(startup.subprocess, "Popen") as spawn):
            startup.ensure_ssh(self.profile)
        self.assertTrue(spawn.call_args.kwargs["start_new_session"])
        for stream in ("stdin", "stdout", "stderr"):
            self.assertEqual(spawn.call_args.kwargs[stream], startup.subprocess.DEVNULL)

    def test_dead_transport_retries_without_busy_loop(self):
        process = mock.Mock()
        with (mock.patch.object(startup, "ssh_ready", return_value=False),
              mock.patch.object(startup.subprocess, "Popen", return_value=process) as spawn,
              mock.patch.object(startup.time, "sleep", side_effect=[None, None, KeyboardInterrupt]) as sleep,
              self.assertRaises(KeyboardInterrupt)):
            startup.supervise_ssh(self.profile)
        self.assertEqual(spawn.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2, 4])

    def test_active_owner_lock_has_real_single_instance_semantics(self):
        with startup.locked(self.root / "supervisor.lock"):
            self.assertTrue(startup.supervisor_running(self.data))
        self.assertFalse(startup.supervisor_running(self.data))

    def test_lock_symlink_cannot_redirect_writes(self):
        other = self.root / "other"
        self.write(other, {})
        lock = self.root / "link.lock"
        lock.symlink_to(other)
        with self.assertRaises(OSError), startup.locked(lock):
            pass

    def web_fixture(self):
        binary = self.root / "tunnel-client"
        binary.write_text("#!/bin/sh\nexit 1\n")
        binary.chmod(0o700)
        profile = self.root / "private-tunnel.json"
        self.write(profile, {"control_plane": {"api_key": "fixture-private-key"}})
        descriptor = self.root / "web.json"
        self.write(descriptor, {"schema_version": "acs-secure-tunnel-startup/1", "root": str(self.root),
            "binary": str(binary), "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "profile_file": str(profile), "pid_file": str(self.root / "pid"),
            "health_url_file": str(self.root / "health.url")})
        return descriptor, binary

    def test_web_start_requests_supervision_without_waiting_for_remote_health(self):
        descriptor, _ = self.web_fixture()
        with (mock.patch.object(startup, "supervisor_running", return_value=False),
              mock.patch.object(startup.subprocess, "Popen") as spawn):
            result = startup.ensure_web(descriptor)
        self.assertEqual(result["web_tunnel"], "supervision_requested")
        self.assertNotIn("fixture-private-key", spawn.call_args.args[0])
        self.assertTrue(spawn.call_args.kwargs["start_new_session"])

    def test_web_binary_drift_cannot_start_a_new_process(self):
        descriptor, binary = self.web_fixture()
        binary.write_text("changed")
        with mock.patch.object(startup.subprocess, "Popen") as spawn, self.assertRaises(startup.StartupUnavailable):
            startup.ensure_web(descriptor)
        spawn.assert_not_called()

    def test_web_crash_restarts_with_bounded_backoff_and_loopback_only_flags(self):
        descriptor, _ = self.web_fixture()
        with (mock.patch.object(startup, "web_pid", return_value=None),
              mock.patch.object(startup.subprocess, "Popen", return_value=mock.Mock()) as spawn,
              mock.patch.object(startup.time, "sleep", side_effect=[None, None, KeyboardInterrupt]) as sleep,
              self.assertRaises(KeyboardInterrupt)):
            startup.supervise_web(descriptor)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2, 4])
        args = spawn.call_args.args[0]
        self.assertIn("127.0.0.1:0", args)
        self.assertIn("--allow-remote-ui=false", args)
        self.assertIn("--open-web-ui=false", args)
        self.assertNotIn("fixture-private-key", args)
