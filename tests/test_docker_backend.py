"""Existing provider data and explicit shared-runtime repair contracts."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "backend_under_test", ROOT / "scripts/acs_docker_backend.py"
)
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class DockerBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.provider = self.root / "providers.json"
        self.provider.write_text(
            json.dumps({"compose_project": "acs-test", "password": "fixture-secret"})
        )
        self.store = self.root / "docker/containerd/daemon"
        meta = self.store / "io.containerd.metadata.v1.bolt/meta.db"
        meta.parent.mkdir(parents=True)
        meta.write_bytes(b"fixture-metadata")
        snapshots = self.store / "io.containerd.snapshotter.v1.overlayfs/snapshots"
        snapshots.mkdir(parents=True)
        (snapshots / "existing-layer").mkdir()
        container = self.root / "docker/containers/fixture/config.v2.json"
        container.parent.mkdir(parents=True)
        container.write_text(
            json.dumps(
                {"ID": "fixture", "Config": {"Labels": {"com.docker.compose.project": "acs-test"}}}
            )
        )
        self.config = self.root / "config.toml"
        self.info = {
            "data_root": str(self.root / "docker"),
            "containerd_address": "/run/containerd/containerd.sock",
            "storage_driver": "overlayfs",
            "server_version": "fixture",
        }
        self.running = ""
        self.host = "unix:///var/run/docker.sock"

    def output(self, *args):
        if args[:3] == ("ctr", "namespaces", "list"):
            return "moby"
        if args[0] == "ctr":
            return self.running
        if args[:3] == ("docker", "context", "inspect"):
            return json.dumps([{"Endpoints": {"docker": {"Host": self.host}}}])
        raise AssertionError(args)

    def plan(self, readable=False):
        with (
            mock.patch.object(backend, "docker_backend", return_value=self.info),
            mock.patch.object(
                backend, "readable_services", return_value={"count": 1, "named": readable}
            ),
            mock.patch.object(backend, "output", side_effect=self.output),
            mock.patch.dict(backend.os.environ, {"DOCKER_HOST": ""}),
        ):
            return backend.repair_plan(self.provider, config=self.config)

    def test_plan_keeps_original_data_and_excludes_provider_secret(self):
        plan = self.plan()
        self.assertEqual(plan["state"], "planned")
        self.assertEqual(plan["existing_root"], str(self.store))
        self.assertEqual(plan["existing_provider_container_count"], 1)
        self.assertNotIn("fixture-secret", json.dumps(plan))
        self.assertFalse(self.config.exists())
        self.assertTrue((self.store / "io.containerd.metadata.v1.bolt/meta.db").exists())
        self.assertEqual(plan["plan_digest"], self.plan()["plan_digest"])

    def test_readable_provider_has_ready_state_without_repair(self):
        plan = self.plan(readable=True)
        self.assertEqual(plan["state"], "ready")
        self.assertEqual(plan["changes"], [])
        self.assertFalse(self.config.exists())

    def test_active_shared_tasks_and_existing_config_require_review(self):
        self.running = "other-live-task"
        self.config.write_text('version = 3\nroot = "/existing"\n')
        plan = self.plan()
        self.assertEqual(plan["state"], "review_required")
        self.assertIn("shared_runtime_has_running_tasks", plan["reasons"])
        self.assertIn("existing_containerd_configuration_requires_merge", plan["reasons"])
        self.assertEqual(self.config.read_text(), 'version = 3\nroot = "/existing"\n')

    def test_remote_daemon_does_not_offer_local_backend_mutation(self):
        self.host = "tcp://remote.example:2376"
        self.assertIn("selected_docker_context_is_remote", self.plan()["reasons"])

    def test_missing_owned_containers_cannot_bind_unrelated_store(self):
        path = self.root / "docker/containers/fixture/config.v2.json"
        path.write_text(
            json.dumps({"Config": {"Labels": {"com.docker.compose.project": "other-project"}}})
        )
        with self.assertRaisesRegex(ValueError, "existing_provider"):
            self.plan()

    def test_apply_needs_explicit_shared_runtime_authority_before_probing(self):
        with (
            mock.patch.object(backend, "repair_plan") as inspect,
            mock.patch.object(backend.subprocess, "run") as mutate,
            self.assertRaisesRegex(ValueError, "confirm_shared"),
        ):
            backend.apply_repair(self.provider, "digest", self.root / "backup", confirmed=False)
        inspect.assert_not_called()
        mutate.assert_not_called()

    def test_changed_plan_cannot_modify_system_config(self):
        with (
            mock.patch.object(backend.os, "geteuid", return_value=0, create=True),
            mock.patch.object(
                backend,
                "repair_plan",
                return_value={"state": "planned", "plan_digest": "new-digest"},
            ),
            mock.patch.object(backend.subprocess, "run") as mutate,
            self.assertRaisesRegex(ValueError, "plan_changed"),
        ):
            backend.apply_repair(self.provider, "old-digest", self.root / "backup", confirmed=True)
        mutate.assert_not_called()
        self.assertFalse((self.root / "backup").exists())

    def test_config_permission_failure_removes_only_new_config(self):
        plan = {
            "schema_version": "acs-docker-backend-repair/1",
            "state": "planned",
            "plan_digest": "digest",
            "config": str(self.config),
            "existing_root": str(self.store),
            "project": "acs-test",
            "existing_provider_container_count": 1,
        }
        original = Path.chmod

        def chmod(path, mode, *args, **kwargs):
            if path == self.config:
                raise OSError("fixture chmod failure")
            return original(path, mode, *args, **kwargs)

        with (
            mock.patch.object(backend.os, "geteuid", return_value=0, create=True),
            mock.patch.object(backend, "repair_plan", return_value=plan),
            mock.patch.object(backend, "output", return_value="fixture unit"),
            mock.patch.object(Path, "chmod", new=chmod),
            mock.patch.object(backend.subprocess, "run") as mutate,
            self.assertRaises(OSError),
        ):
            backend.apply_repair(self.provider, "digest", self.root / "backup", confirmed=True)
        self.assertFalse(self.config.exists())
        mutate.assert_not_called()

    def test_failed_readback_rolls_back_the_new_config(self):
        backup = self.root / "backup"
        plan = {
            "schema_version": "acs-docker-backend-repair/1",
            "state": "planned",
            "plan_digest": "digest",
            "config": str(self.config),
            "existing_root": str(self.store),
            "project": "acs-test",
            "existing_provider_container_count": 1,
        }
        with (
            mock.patch.object(backend.os, "geteuid", return_value=0, create=True),
            mock.patch.object(backend, "repair_plan", return_value=plan),
            mock.patch.object(backend, "output", return_value="fixture unit"),
            mock.patch.object(
                backend, "readable_services", return_value={"count": 0, "named": False}
            ),
            mock.patch.object(backend.subprocess, "run") as mutate,
            self.assertRaisesRegex(ValueError, "readback_failed"),
        ):
            backend.apply_repair(self.provider, "digest", backup, confirmed=True)
        self.assertFalse(self.config.exists())
        self.assertTrue((backup / "repair-plan.json").exists())
        self.assertEqual(mutate.call_count, 11)
        self.assertEqual(mutate.call_args_list[1].args[0], ["systemctl", "stop", "docker.socket"])


if __name__ == "__main__":
    unittest.main()
