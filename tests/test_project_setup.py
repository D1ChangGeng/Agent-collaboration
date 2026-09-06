import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("project_setup", ROOT / "scripts" / "project_setup.py")
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(mod)


class ProjectSetupTests(unittest.TestCase):
    def test_adopt_preserves_existing_guidance_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "AGENTS.md").write_text("# Existing\nKeep me.\n", encoding="utf-8")
            (root / "CLAUDE.md").write_text("# Existing Claude\nKeep this too.\n", encoding="utf-8")
            (root / ".gitignore").write_text("node_modules/\n", encoding="utf-8")

            mod.install_or_upgrade(root, "adopt", False)
            first_agents = (root / "AGENTS.md").read_text(encoding="utf-8")
            first_claude = (root / "CLAUDE.md").read_text(encoding="utf-8")

            self.assertIn("Keep me.", first_agents)
            self.assertIn(mod.AGENTS_BEGIN, first_agents)
            self.assertEqual(first_agents.count(mod.AGENTS_BEGIN), 1)

            self.assertIn("Keep this too.", first_claude)
            self.assertIn("@AGENTS.md", first_claude)
            self.assertEqual(first_claude.count(mod.CLAUDE_BEGIN), 1)

            self.assertIn("node_modules/", (root / ".gitignore").read_text(encoding="utf-8"))

            mod.install_or_upgrade(root, "upgrade", False)
            second_agents = (root / "AGENTS.md").read_text(encoding="utf-8")
            second_claude = (root / "CLAUDE.md").read_text(encoding="utf-8")

            self.assertEqual(first_agents, second_agents)
            self.assertEqual(first_claude, second_claude)

            ok, problems = mod.validate(root)
            self.assertTrue(ok, problems)

    def test_upgrade_preserves_project_owned_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.install_or_upgrade(root, "adopt", False)
            profile = root / ".agents" / "coordination" / "PROJECT.md"
            profile.write_text("# My project profile\nDO NOT OVERWRITE\n", encoding="utf-8")

            mod.install_or_upgrade(root, "upgrade", False)
            self.assertEqual(
                profile.read_text(encoding="utf-8"),
                "# My project profile\nDO NOT OVERWRITE\n",
            )

    def test_legacy_manifest_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.install_or_upgrade(root, "adopt", False)
            manifest = root / ".agents" / "manifest.json"
            first = manifest.read_text(encoding="utf-8")

            mod.install_or_upgrade(root, "upgrade", False)

            self.assertEqual(first, manifest.read_text(encoding="utf-8"))

    def test_default_uninstall_preserves_project_knowledge(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.install_or_upgrade(root, "adopt", False)
            knowledge = root / ".agents" / "knowledge" / "guides" / "important.md"
            knowledge.write_text("keep", encoding="utf-8")

            mod.uninstall(root, False, purge_data=False)

            self.assertTrue(knowledge.exists())
            self.assertNotIn(
                mod.AGENTS_BEGIN,
                (root / "AGENTS.md").read_text(encoding="utf-8") if (root / "AGENTS.md").exists() else "",
            )

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            actions = mod.install_or_upgrade(root, "adopt", True)
            self.assertTrue(actions)
            self.assertFalse((root / "AGENTS.md").exists())

    def test_workspace_adopt_is_non_git_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspace"
            actions = mod.workspace_install(root, "adopt", True)
            self.assertTrue(actions)
            self.assertFalse(root.exists())

            mod.workspace_install(root, "adopt", False)
            manifest = root / ".agents" / "manifest.json"
            first = manifest.read_text(encoding="utf-8")
            mod.workspace_install(root, "upgrade", False)
            self.assertEqual(first, manifest.read_text(encoding="utf-8"))

            ok, problems = mod.validate_workspace(root)
            self.assertTrue(ok, problems)
            self.assertFalse((root / ".git").exists())

    def test_workspace_route_create_and_state_are_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            args = type("Args", (), {
                "workspace": root,
                "action": "create",
                "path": "C Route",
                "route_id": "c-route",
                "display_name": "C Route",
                "state": None,
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(args), 0)
            self.assertEqual(mod.route_operation(args), 0)
            route = root / "C Route"
            self.assertTrue((route / "AGENTS.md").exists())
            self.assertTrue((route / ".agents" / "knowledge" / "index.yaml").exists())

            state_args = type("Args", (), {
                "workspace": root,
                "action": "set-state",
                "path": "C Route",
                "route_id": "c-route",
                "display_name": "C Route",
                "state": "paused",
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(state_args), 0)
            meta = mod.read_json(route / ".agents" / "route.yaml")
            self.assertEqual(meta["state"], "paused")

            ok, problems = mod.validate_workspace(root)
            self.assertTrue(ok, problems)

    def test_route_adopt_preserves_existing_route_assets(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            route = root / "Legacy Route"
            (route / ".agents" / "knowledge" / "guides").mkdir(parents=True)
            (route / "AGENTS.md").write_text("# Keep this route\n", encoding="utf-8")
            keep = route / ".agents" / "knowledge" / "guides" / "keep.md"
            keep.write_text("keep", encoding="utf-8")
            (route / ".agents" / "knowledge" / "index.yaml").write_text('schema_version: "2.0"\ndocuments: []\n', encoding="utf-8")
            mod.workspace_install(root, "adopt", False)
            args = type("Args", (), {
                "workspace": root,
                "action": "adopt",
                "path": "Legacy Route",
                "route_id": None,
                "display_name": "Legacy Route",
                "state": None,
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(args), 0)
            self.assertEqual(mod.route_operation(args), 0)
            self.assertEqual("# Keep this route\n", (route / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertEqual("keep", keep.read_text(encoding="utf-8"))

    def test_workspace_registry_rejects_escape_and_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            registry = root / ".agents" / "coordination" / "routes.yaml"
            registry.write_text('{"schema_version":"0.2","root_id":"agent-collaboration-root","routes":[{"id":"bad","path":"../outside","status":"active"}]}\n', encoding="utf-8")
            ok, problems = mod.validate_workspace(root)
            self.assertFalse(ok)
            self.assertTrue(any("escapes workspace" in p for p in problems), problems)

    def test_workspace_malformed_registry_fails_before_scaffold_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry = root / ".agents" / "coordination" / "routes.yaml"
            registry.parent.mkdir(parents=True)
            registry.write_text("routes: [", encoding="utf-8")

            actions = mod.workspace_install(root, "adopt", False)

            self.assertTrue(any(action.startswith("error ") for action in actions), actions)
            self.assertFalse((root / "AGENTS.md").exists())
            self.assertFalse((root / ".agents" / "manifest.json").exists())

    def test_workspace_file_target_is_rejected_without_traceback(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "workspace"
            target.write_text("not a directory", encoding="utf-8")

            actions = mod.workspace_install(target, "adopt", False)

            self.assertEqual(len(actions), 1)
            self.assertIn("not a directory", actions[0])
            self.assertEqual(mod.workspace_cli_main(["workspace", "adopt", "--root", str(target)]), 1)

    def test_route_file_collision_is_rejected_without_registry_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            route_file = root / "C Route"
            route_file.write_text("not a route", encoding="utf-8")
            before = (root / ".agents" / "coordination" / "routes.yaml").read_text(encoding="utf-8")
            args = type("Args", (), {
                "workspace": root,
                "action": "create",
                "path": "C Route",
                "route_id": "c-route",
                "display_name": "C Route",
                "state": None,
                "dry_run": False,
            })()

            self.assertEqual(mod.route_operation(args), 1)
            self.assertEqual(before, (root / ".agents" / "coordination" / "routes.yaml").read_text(encoding="utf-8"))

    def test_malformed_route_metadata_is_rejected_before_adopt_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            route = root / "Legacy Route"
            (route / ".agents").mkdir(parents=True)
            (route / "AGENTS.md").write_text("# Existing\n", encoding="utf-8")
            (route / ".agents" / "route.yaml").write_text("{bad", encoding="utf-8")
            before = (root / ".agents" / "coordination" / "routes.yaml").read_text(encoding="utf-8")
            args = type("Args", (), {
                "workspace": root,
                "action": "adopt",
                "path": "Legacy Route",
                "route_id": None,
                "display_name": "Legacy Route",
                "state": None,
                "dry_run": False,
            })()

            self.assertEqual(mod.route_operation(args), 1)
            self.assertEqual(before, (root / ".agents" / "coordination" / "routes.yaml").read_text(encoding="utf-8"))

    def test_workspace_adopt_rejects_malformed_discovered_route_before_root_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspace"
            route = root / "Bad Route"
            (route / ".agents").mkdir(parents=True)
            (route / "AGENTS.md").write_text("# Existing\n", encoding="utf-8")
            (route / ".agents" / "route.yaml").write_text("{bad", encoding="utf-8")

            actions = mod.workspace_install(root, "adopt", False)

            self.assertTrue(any(action.startswith("error discovered route:") for action in actions), actions)
            self.assertFalse((root / "AGENTS.md").exists())
            self.assertFalse((root / ".agents" / "manifest.json").exists())

    def test_workspace_validate_checks_existing_route_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            args = type("Args", (), {
                "workspace": root,
                "action": "create",
                "path": "C Route",
                "route_id": "c-route",
                "display_name": "C Route",
                "state": None,
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(args), 0)
            route_meta = root / "C Route" / ".agents" / "route.yaml"
            route_meta.write_text(route_meta.read_text(encoding="utf-8").replace('"state": "active"', '"state": "paused"'), encoding="utf-8")

            ok, problems = mod.validate_workspace(root)

            self.assertFalse(ok)
            self.assertTrue(any("does not match registry" in problem for problem in problems), problems)

    def test_workspace_validate_detects_managed_file_hash_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            managed = root / ".agents" / "README.md"
            managed.write_text(managed.read_text(encoding="utf-8") + "\nlocal drift\n", encoding="utf-8")

            ok, problems = mod.validate_workspace(root)

            self.assertFalse(ok)
            self.assertTrue(any("hash mismatch" in problem for problem in problems), problems)

    def test_workspace_upgrade_rejects_discovery_id_collision_before_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            legacy = root / "legacy"
            discovered = root / "New"
            legacy.mkdir()
            discovered.mkdir()
            (discovered / "AGENTS.md").write_text("# discovered\n", encoding="utf-8")
            registry_path = root / ".agents" / "coordination" / "routes.yaml"
            registry_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.2",
                        "root_id": "agent-collaboration-root",
                        "routes": [
                            {
                                "id": "new",
                                "display_name": "Legacy",
                                "path": "legacy",
                                "work_scope": "unknown",
                                "status": "discovered",
                                "migration_status": "legacy-unmigrated",
                                "agents_path": "unknown",
                                "knowledge_root": "unknown",
                                "knowledge_index": "unknown",
                                "knowledge_index_status": "present",
                                "source_repository": {"status": "unknown"},
                                "execution_endpoints": {"status": "unknown"},
                                "migration_contract": "0.2-required",
                                "evidence": {"path": "local-verified", "execution": "unknown"},
                            }
                        ],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            before = {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }

            actions = mod.workspace_install(root, "upgrade", False)

            self.assertTrue(any(action.startswith("error merged registry:") for action in actions), actions)
            after = {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)

    def test_workspace_validate_rejects_malformed_registry_field_types(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            route = root / "A Route"
            route.mkdir()
            (route / "AGENTS.md").write_text("# route\n", encoding="utf-8")
            registry_path = root / ".agents" / "coordination" / "routes.yaml"
            base = {
                "schema_version": "0.2",
                "root_id": "agent-collaboration-root",
                "routes": [{
                    "id": "a-route",
                    "display_name": "A Route",
                    "path": "A Route",
                    "status": "discovered",
                    "agents_path": "A Route/AGENTS.md",
                    "knowledge_root": "A Route/.agents/knowledge",
                    "knowledge_index": "A Route/.agents/knowledge/index.yaml",
                    "migration_status": "legacy-unmigrated",
                    "migration_contract": "0.2-required",
                    "knowledge_index_status": "present",
                    "source_repository": {"status": "unknown"},
                    "execution_endpoints": {"status": "unknown"},
                    "evidence": {"path": "local-verified", "execution": "unknown"},
                }],
            }
            for field, bad_value in {
                "source_repository": "broken",
                "execution_endpoints": [],
                "migration_status": [],
                "agents_path": 7,
                "knowledge_root": {},
                "evidence": "broken",
            }.items():
                candidate = json.loads(json.dumps(base))
                candidate["routes"][0][field] = bad_value
                registry_path.write_text(json.dumps(candidate), encoding="utf-8")
                ok, problems = mod.validate_workspace(root)
                self.assertFalse(ok, field)
                self.assertTrue(problems, field)

    def test_workspace_rejects_noncanonical_baseline_or_source_state_pointer(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            manifest_path = root / ".agents" / "manifest.json"
            manifest = mod.read_json(manifest_path)
            manifest["baseline_path"] = "custom/baseline.md"
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            before = {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }

            actions = mod.workspace_install(root, "upgrade", False)
            ok, problems = mod.validate_workspace(root)

            self.assertTrue(any(action.startswith("error ") for action in actions), actions)
            self.assertFalse(ok)
            self.assertTrue(any("baseline_path" in problem for problem in problems), problems)
            after = {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)

    def test_workspace_uninstall_guard_is_non_mutating(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            before = {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }

            result = mod.workspace_cli_main(["workspace", "uninstall", "--root", str(root)])

            self.assertEqual(result, 1)
            after = {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)

    def test_workspace_custom_registry_parent_collision_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            manifest_path = root / ".agents" / "manifest.json"
            manifest = mod.read_json(manifest_path)
            manifest["registry_path"] = "meta/registry.json"
            manifest["project_owned_files"] = [
                ".agents/coordination/ROOT-BASELINE.md",
                ".agents/coordination/PROJECT.md",
            ]
            import json
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            (root / "meta").write_text("a file, not a directory", encoding="utf-8")
            before = {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }

            actions = mod.workspace_install(root, "upgrade", False)

            self.assertTrue(any(action.startswith("error ") for action in actions), actions)
            self.assertFalse((root / "meta" / "registry.json").exists())
            after = {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)

    def test_unified_cli_entrypoint_runs_workspace_and_route_operations(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspace"
            script = ROOT / "scripts" / "project_setup.py"

            commands = [
                ["workspace", "adopt", "--root", str(root)],
                [
                    "route", "create", "--workspace", str(root),
                    "--path", "C Route", "--route-id", "c-route",
                    "--display-name", "C Route",
                ],
                ["route", "list", "--workspace", str(root)],
                ["route", "validate", "--workspace", str(root), "--route-id", "c-route"],
                ["workspace", "validate", "--root", str(root)],
            ]
            outputs = []
            for command in commands:
                completed = subprocess.run(
                    [sys.executable, str(script)] + command,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                outputs.append(completed.stdout)

            self.assertIn("c-route", outputs[2])
            self.assertIn("Project Collaboration Root validated", outputs[4])


if __name__ == "__main__":
    unittest.main()
