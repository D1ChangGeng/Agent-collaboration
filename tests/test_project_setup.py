import importlib.util
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_02_FIXTURES = ROOT / "tests" / "fixtures" / "schema-0.2"
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

    def test_repository_managed_block_markers_fail_before_any_write(self):
        targets = (
            ("AGENTS.md", mod.AGENTS_BEGIN, mod.AGENTS_END),
            ("CLAUDE.md", mod.CLAUDE_BEGIN, mod.CLAUDE_END),
            (".gitignore", mod.GITIGNORE_BEGIN, mod.GITIGNORE_END),
        )
        malformed = {
            "incomplete": lambda begin, end: f"before\n{begin}\nunfinished\n",
            "duplicate": lambda begin, end: (
                f"{begin}\nfirst\n{end}\n{begin}\nsecond\n{end}\n"
            ),
            "reversed": lambda begin, end: f"{end}\n{begin}\n",
        }
        for filename, begin, end in targets:
            for case, make_text in malformed.items():
                with self.subTest(filename=filename, case=case):
                    with tempfile.TemporaryDirectory() as td:
                        root = Path(td)
                        mod.install_or_upgrade(root, "adopt", False)
                        (root / filename).write_text(
                            make_text(begin, end), encoding="utf-8"
                        )
                        before = {
                            str(path.relative_to(root)): path.read_bytes()
                            for path in root.rglob("*")
                            if path.is_file()
                        }

                        with self.assertRaises(ValueError):
                            mod.install_or_upgrade(root, "upgrade", False)

                        after = {
                            str(path.relative_to(root)): path.read_bytes()
                            for path in root.rglob("*")
                            if path.is_file()
                        }
                        self.assertEqual(before, after)
                        ok, problems = mod.validate(root)
                        self.assertFalse(ok)
                        self.assertTrue(
                            any("managed block markers invalid" in item for item in problems),
                            problems,
                        )

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

    def test_repository_uninstall_rejects_malformed_markers_without_traceback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            agents = root / "AGENTS.md"
            agents.write_text(
                f"{mod.AGENTS_BEGIN}\nunclosed\n", encoding="utf-8"
            )
            before = agents.read_bytes()
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "project_setup.py"),
                    "uninstall",
                    "--root",
                    str(root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertNotIn("Traceback", completed.stdout + completed.stderr)
            self.assertEqual(before, agents.read_bytes())

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

    def test_workspace_repeated_adopt_is_idempotent_on_windows_newlines(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspace"
            mod.workspace_install(root, "adopt", False)
            actions = mod.workspace_install(root, "adopt", False)
            self.assertEqual(actions, [])

    def test_workspace_managed_block_markers_fail_before_any_write(self):
        targets = (
            (
                "AGENTS.md",
                "<!-- ACHP-WORKSPACE:BEGIN -->",
                "<!-- ACHP-WORKSPACE:END -->",
            ),
            ("CLAUDE.md", mod.CLAUDE_BEGIN, mod.CLAUDE_END),
            (
                ".gitignore",
                "# ACHP-WORKSPACE:BEGIN",
                "# ACHP-WORKSPACE:END",
            ),
        )
        malformed = {
            "incomplete": lambda begin, end: f"before\n{begin}\nunfinished\n",
            "duplicate": lambda begin, end: (
                f"{begin}\nfirst\n{end}\n{begin}\nsecond\n{end}\n"
            ),
            "reversed": lambda begin, end: f"{end}\n{begin}\n",
        }
        for filename, begin, end in targets:
            for case, make_text in malformed.items():
                with self.subTest(filename=filename, case=case):
                    with tempfile.TemporaryDirectory() as td:
                        root = Path(td) / "workspace"
                        mod.workspace_install(root, "adopt", False)
                        (root / filename).write_text(
                            make_text(begin, end), encoding="utf-8"
                        )
                        before = {
                            str(path.relative_to(root)): path.read_bytes()
                            for path in root.rglob("*")
                            if path.is_file()
                        }

                        actions = mod.workspace_install(root, "upgrade", False)

                        self.assertTrue(
                            any(
                                action.startswith("error managed block markers:")
                                for action in actions
                            ),
                            actions,
                        )
                        after = {
                            str(path.relative_to(root)): path.read_bytes()
                            for path in root.rglob("*")
                            if path.is_file()
                        }
                        self.assertEqual(before, after)
                        ok, problems = mod.validate_workspace(root)
                        self.assertFalse(ok)
                        self.assertTrue(
                            any("managed block markers invalid" in item for item in problems),
                            problems,
                        )

    def test_schema_02_legacy_managed_blocks_validate_and_adopt_preserve(self):
        """A known v0.2 managed block is readable and not silently rewritten."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspace"
            mod.workspace_install(root, "adopt", False)
            for fixture, target, begin, end in (
                (
                    SCHEMA_02_FIXTURES / "AGENTS_BLOCK.md",
                    "AGENTS.md",
                    "<!-- ACHP-WORKSPACE:BEGIN -->",
                    "<!-- ACHP-WORKSPACE:END -->",
                ),
                (
                    SCHEMA_02_FIXTURES / "GITIGNORE_BLOCK.txt",
                    ".gitignore",
                    "# ACHP-WORKSPACE:BEGIN",
                    "# ACHP-WORKSPACE:END",
                ),
            ):
                legacy = fixture.read_text(encoding="utf-8")
                legacy_body = legacy.split(begin, 1)[1].split(end, 1)[0].strip()
                path = root / target
                current = path.read_text(encoding="utf-8")
                left, rest = current.split(begin, 1)
                _, right = rest.split(end, 1)
                path.write_text(
                    left + begin + "\n" + legacy_body + "\n" + end + right,
                    encoding="utf-8",
                )

            manifest_path = root / ".agents" / "manifest.json"
            manifest = mod.read_json(manifest_path)
            manifest["schema_version"] = "0.2"
            manifest["version"] = "0.2"
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            registry_path = root / ".agents" / "coordination" / "routes.yaml"
            registry = mod.read_json(registry_path)
            registry["schema_version"] = "0.2"
            registry_path.write_text(
                json.dumps(registry, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            before = {
                target: (root / target).read_bytes()
                for target in ("AGENTS.md", ".gitignore")
            }
            self.assertEqual(mod.validate_workspace(root), (True, []))
            self.assertEqual(mod.workspace_install(root, "adopt", False), [])
            self.assertEqual(
                before,
                {target: (root / target).read_bytes() for target in before},
            )
            self.assertEqual(mod.workspace_install(root, "repair", False), [])
            self.assertEqual(
                before,
                {target: (root / target).read_bytes() for target in before},
            )
            self.assertEqual(mod.validate_workspace(root), (True, []))

    def test_schema_02_upgrade_replaces_legacy_managed_blocks(self):
        """Only explicit upgrade installs the current managed block bodies."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspace"
            mod.workspace_install(root, "adopt", False)
            for fixture, target, begin, end in (
                (
                    SCHEMA_02_FIXTURES / "AGENTS_BLOCK.md",
                    "AGENTS.md",
                    "<!-- ACHP-WORKSPACE:BEGIN -->",
                    "<!-- ACHP-WORKSPACE:END -->",
                ),
                (
                    SCHEMA_02_FIXTURES / "GITIGNORE_BLOCK.txt",
                    ".gitignore",
                    "# ACHP-WORKSPACE:BEGIN",
                    "# ACHP-WORKSPACE:END",
                ),
            ):
                legacy = fixture.read_text(encoding="utf-8")
                legacy_body = legacy.split(begin, 1)[1].split(end, 1)[0].strip()
                path = root / target
                current = path.read_text(encoding="utf-8")
                left, rest = current.split(begin, 1)
                _, right = rest.split(end, 1)
                path.write_text(
                    left + begin + "\n" + legacy_body + "\n" + end + right,
                    encoding="utf-8",
                )
            manifest_path = root / ".agents" / "manifest.json"
            manifest = mod.read_json(manifest_path)
            manifest["schema_version"] = "0.2"
            manifest["version"] = "0.2"
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            registry_path = root / ".agents" / "coordination" / "routes.yaml"
            registry = mod.read_json(registry_path)
            registry["schema_version"] = "0.2"
            registry_path.write_text(
                json.dumps(registry, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            actions = mod.workspace_install(root, "upgrade", False)
            self.assertFalse(any(action.startswith("error ") for action in actions), actions)
            self.assertNotIn(
                "Machine/session-local observations",
                (root / ".gitignore").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "Harness/session context and capability observations",
                (root / "AGENTS.md").read_text(encoding="utf-8"),
            )
            self.assertEqual(mod.validate_workspace(root), (True, []))

    def test_workspace_adopt_and_repair_are_idempotent_with_registered_route(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspace"
            mod.workspace_install(root, "adopt", False)
            create_args = type("Args", (), {
                "workspace": root,
                "action": "create",
                "path": "A Route",
                "route_id": "a-route",
                "display_name": "A Route",
                "state": None,
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(create_args), 0)
            registry_path = root / ".agents" / "coordination" / "routes.yaml"
            before = registry_path.read_bytes()

            self.assertEqual(mod.workspace_install(root, "adopt", False), [])
            self.assertEqual(mod.workspace_install(root, "repair", False), [])
            self.assertEqual(before, registry_path.read_bytes())
            self.assertEqual(mod.validate_workspace(root), (True, []))

    def test_schema_02_workspace_adopt_repair_reject_new_discovery_without_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspace"
            mod.workspace_install(root, "adopt", False)
            registry_path = root / ".agents" / "coordination" / "routes.yaml"
            registry = mod.read_json(registry_path)
            registry["schema_version"] = "0.2"
            registry_path.write_text(
                json.dumps(registry, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            route = root / "Discovered Route"
            (route / ".agents").mkdir(parents=True)
            (route / "AGENTS.md").write_text("# Existing Route\n", encoding="utf-8")

            before = {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            for mode in ("adopt", "repair"):
                for dry_run in (True, False):
                    with self.subTest(mode=mode, dry_run=dry_run):
                        actions = mod.workspace_install(root, mode, dry_run)
                        self.assertTrue(
                            any(
                                "schema 0.2" in action
                                and "explicit workspace upgrade" in action
                                for action in actions
                            ),
                            actions,
                        )
                        after = {
                            str(path.relative_to(root)): path.read_bytes()
                            for path in root.rglob("*")
                            if path.is_file()
                        }
                        self.assertEqual(before, after)

    def test_schema_02_registry_without_manifest_requires_explicit_upgrade(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspace"
            mod.workspace_install(root, "adopt", False)
            manifest_path = root / ".agents" / "manifest.json"
            registry_path = root / ".agents" / "coordination" / "routes.yaml"
            manifest_path.unlink()
            registry = mod.read_json(registry_path)
            registry["schema_version"] = "0.2"
            registry_path.write_text(
                json.dumps(registry, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            before = {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }

            for dry_run in (True, False):
                with self.subTest(dry_run=dry_run):
                    actions = mod.workspace_install(root, "adopt", dry_run)
                    self.assertTrue(
                        any(
                            "workspace manifest missing" in action
                            and "schema 0.2" in action
                            and "explicit workspace upgrade" in action
                            for action in actions
                        ),
                        actions,
                    )
                    after = {
                        str(path.relative_to(root)): path.read_bytes()
                        for path in root.rglob("*")
                        if path.is_file()
                    }
                    self.assertEqual(before, after)
                    self.assertFalse(manifest_path.exists())
                    self.assertEqual(
                        mod.read_json(registry_path)["schema_version"], "0.2"
                    )

    def test_schema_02_route_create_adopt_reject_v03_writes_without_write(self):
        for action in ("create", "adopt"):
            for dry_run in (True, False):
                with self.subTest(action=action, dry_run=dry_run):
                    with tempfile.TemporaryDirectory() as td:
                        root = Path(td) / "workspace"
                        mod.workspace_install(root, "adopt", False)
                        registry_path = root / ".agents" / "coordination" / "routes.yaml"
                        registry = mod.read_json(registry_path)
                        registry["schema_version"] = "0.2"
                        registry_path.write_text(
                            json.dumps(registry, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8",
                        )
                        route = root / "New Route"
                        if action == "adopt":
                            route.mkdir()

                        before = {
                            str(path.relative_to(root)): path.read_bytes()
                            for path in root.rglob("*")
                            if path.is_file()
                        }
                        args = type("Args", (), {
                            "workspace": root,
                            "action": action,
                            "path": "New Route",
                            "route_id": "new-route",
                            "display_name": "New Route",
                            "state": None,
                            "dry_run": dry_run,
                        })()

                        self.assertEqual(mod.route_operation(args), 1)
                        after = {
                            str(path.relative_to(root)): path.read_bytes()
                            for path in root.rglob("*")
                            if path.is_file()
                        }
                        self.assertEqual(before, after)
                        self.assertFalse((route / ".agents" / "route.yaml").exists())

    def test_schema_02_route_create_adopt_allow_complete_registered_noop(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspace"
            mod.workspace_install(root, "adopt", False)
            create = type("Args", (), {
                "workspace": root,
                "action": "create",
                "path": "Existing Route",
                "route_id": "existing-route",
                "display_name": "Existing Route",
                "state": None,
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(create), 0)

            registry_path = root / ".agents" / "coordination" / "routes.yaml"
            registry = mod.read_json(registry_path)
            registry["schema_version"] = "0.2"
            registry_path.write_text(
                json.dumps(registry, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            route_meta_path = root / "Existing Route" / ".agents" / "route.yaml"
            route_meta = mod.read_json(route_meta_path)
            route_meta.update(
                {
                    "schema_version": "0.2",
                    "display_name": "Existing Route",
                    "state": "active",
                }
            )
            route_meta_path.write_text(
                json.dumps(route_meta, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            before = {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }

            for action in ("create", "adopt"):
                for dry_run in (True, False):
                    with self.subTest(action=action, dry_run=dry_run):
                        args = type("Args", (), {
                            "workspace": root,
                            "action": action,
                            "path": "Existing Route",
                            "route_id": "existing-route",
                            "display_name": "Existing Route",
                            "state": None,
                            "dry_run": dry_run,
                        })()
                        self.assertEqual(mod.route_operation(args), 0)
                        after = {
                            str(path.relative_to(root)): path.read_bytes()
                            for path in root.rglob("*")
                            if path.is_file()
                        }
                        self.assertEqual(before, after)

    def test_workspace_adopt_and_repair_preserve_bound_managed_content(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspace"
            mod.workspace_install(root, "adopt", False)
            managed = root / ".agents" / "README.md"
            managed.write_text("legacy managed content\n", encoding="utf-8")
            manifest_path = root / ".agents" / "manifest.json"
            manifest = mod.read_json(manifest_path)
            legacy_hash = hashlib.sha256(managed.read_bytes()).hexdigest()
            manifest["schema_version"] = "0.2"
            manifest["managed_files"] = [".agents/README.md"]
            manifest["managed_hashes"] = {".agents/README.md": legacy_hash}
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

            for mode in ("adopt", "repair"):
                actions = mod.workspace_install(root, mode, False)
                self.assertFalse(any(action.startswith("error ") for action in actions), actions)
                self.assertEqual(
                    managed.read_text(encoding="utf-8"), "legacy managed content\n"
                )
                current = mod.read_json(manifest_path)
                self.assertEqual(current["managed_hashes"][".agents/README.md"], legacy_hash)
                self.assertEqual(mod.validate_workspace(root), (True, []))

    def test_route_create_dry_run_plans_new_route(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            args = type("Args", (), {
                "workspace": root,
                "action": "create",
                "path": "New Route",
                "route_id": "new-route",
                "display_name": "New Route",
                "state": None,
                "dry_run": True,
            })()
            self.assertEqual(mod.route_operation(args), 0)
            self.assertFalse((root / "New Route").exists())

    def test_route_create_preflights_existing_route_surfaces(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            existing_args = type("Args", (), {
                "workspace": root,
                "action": "create",
                "path": "Existing Route",
                "route_id": "existing-route",
                "display_name": "Existing Route",
                "state": None,
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(existing_args), 0)
            existing_meta = root / "Existing Route" / ".agents" / "route.yaml"
            existing_meta.write_text("{bad", encoding="utf-8")
            before = (root / ".agents" / "coordination" / "routes.yaml").read_bytes()

            for dry_run in (True, False):
                new_args = type("Args", (), {
                    "workspace": root,
                    "action": "create",
                    "path": "New Route",
                    "route_id": "new-route",
                    "display_name": "New Route",
                    "state": None,
                    "dry_run": dry_run,
                })()
                self.assertEqual(mod.route_operation(new_args), 1)
                self.assertFalse((root / "New Route").exists())
                self.assertEqual(
                    before,
                    (root / ".agents" / "coordination" / "routes.yaml").read_bytes(),
                )

    def test_workspace_route_scaffold_carries_agents_evolution_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspace"
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
            text = (root / "C Route" / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("Always-on content boundary", text)
            self.assertIn("self-evolution", text)
            self.assertIn("work log", text)

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
            registry = mod.read_json(root / ".agents" / "coordination" / "routes.yaml")
            entry = next(item for item in registry["routes"] if item["id"] == "c-route")
            self.assertEqual(entry["status"], "paused")
            # v0.3 keeps lifecycle state in the Root registry.  Route metadata
            # is identity-only and must not become a second lifecycle source.
            meta = mod.read_json(route / ".agents" / "route.yaml")
            self.assertNotIn("state", meta)

            ok, problems = mod.validate_workspace(root)
            self.assertTrue(ok, problems)

    def test_route_create_does_not_emit_empty_source_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            args = type("Args", (), {
                "workspace": root,
                "action": "create",
                "path": "Lazy Source Route",
                "route_id": "lazy-source-route",
                "display_name": "Lazy Source Route",
                "state": None,
                "dry_run": False,
            })()

            self.assertEqual(mod.route_operation(args), 0)
            route = root / "Lazy Source Route"
            source_state = route / ".agents" / "state" / "source-state.yaml"
            self.assertFalse(source_state.exists())
            self.assertEqual(mod.route_operation(args), 0)
            self.assertFalse(source_state.exists())

            validate_args = type("Args", (), {
                "workspace": root,
                "action": "validate",
                "path": "Lazy Source Route",
                "route_id": "lazy-source-route",
                "display_name": None,
                "state": None,
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(validate_args), 0)
            self.assertEqual(mod.validate_workspace(root), (True, []))

    def test_route_adopt_preserves_existing_source_state_and_allows_absence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)

            existing = root / "Bound Source Route"
            (existing / ".agents" / "knowledge").mkdir(parents=True)
            (existing / ".agents" / "state").mkdir(parents=True)
            (existing / "AGENTS.md").write_text("# Existing bound route\n", encoding="utf-8")
            (existing / ".agents" / "knowledge" / "index.yaml").write_text(
                'schema_version: "2.0"\ndocuments: []\n', encoding="utf-8"
            )
            source_state = existing / ".agents" / "state" / "source-state.yaml"
            source_bytes = (
                "kind: git\n"
                "repository:\n"
                "  locator: D:/src/example\n"
                "  commit: abc123\n"
                "evidence:\n"
                "  class: direct\n"
            ).encode("utf-8")
            source_state.write_bytes(source_bytes)

            missing = root / "Unbound Source Route"
            (missing / ".agents" / "knowledge").mkdir(parents=True)
            (missing / "AGENTS.md").write_text("# Existing unbound route\n", encoding="utf-8")
            (missing / ".agents" / "knowledge" / "index.yaml").write_text(
                'schema_version: "2.0"\ndocuments: []\n', encoding="utf-8"
            )

            def adopt(path: str, route_id: str):
                return type("Args", (), {
                    "workspace": root,
                    "action": "adopt",
                    "path": path,
                    "route_id": route_id,
                    "display_name": path,
                    "state": None,
                    "dry_run": False,
                })()

            self.assertEqual(
                mod.route_operation(adopt("Bound Source Route", "bound-source-route")),
                0,
            )
            self.assertEqual(source_bytes, source_state.read_bytes())

            self.assertEqual(
                mod.route_operation(adopt("Unbound Source Route", "unbound-source-route")),
                0,
            )
            self.assertFalse(
                (missing / ".agents" / "state" / "source-state.yaml").exists()
            )
            self.assertEqual(mod.validate_workspace(root), (True, []))

    def test_schema_02_registered_route_without_source_state_remains_noop(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            create_args = type("Args", (), {
                "workspace": root,
                "action": "create",
                "path": "Legacy Lazy Route",
                "route_id": "legacy-lazy-route",
                "display_name": "Legacy Lazy Route",
                "state": None,
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(create_args), 0)
            route = root / "Legacy Lazy Route"
            source_state = route / ".agents" / "state" / "source-state.yaml"
            self.assertFalse(source_state.exists())

            manifest_path = root / ".agents" / "manifest.json"
            manifest = mod.read_json(manifest_path)
            manifest.update({"schema_version": "0.2", "version": "0.2"})
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            registry_path = root / ".agents" / "coordination" / "routes.yaml"
            registry = mod.read_json(registry_path)
            registry["schema_version"] = "0.2"
            registry_path.write_text(
                json.dumps(registry, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            route_meta_path = route / ".agents" / "route.yaml"
            route_meta = mod.read_json(route_meta_path)
            route_meta["schema_version"] = "0.2"
            route_meta["version"] = "0.2"
            route_meta["display_name"] = "Legacy Lazy Route"
            route_meta["state"] = "active"
            route_meta_path.write_text(
                json.dumps(route_meta, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            before = {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            adopt_args = type("Args", (), {
                "workspace": root,
                "action": "adopt",
                "path": "Legacy Lazy Route",
                "route_id": "legacy-lazy-route",
                "display_name": "Legacy Lazy Route",
                "state": None,
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(adopt_args), 0)
            self.assertEqual(
                before,
                {
                    str(path.relative_to(root)): path.read_bytes()
                    for path in root.rglob("*")
                    if path.is_file()
                },
            )
            self.assertFalse(source_state.exists())

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
            meta = mod.read_json(route_meta)
            # Legacy lifecycle metadata is still read for compatibility, but a
            # conflicting value must fail closed against the registry status.
            meta["state"] = "paused"
            route_meta.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

            ok, problems = mod.validate_workspace(root)

            self.assertFalse(ok)
            self.assertTrue(
                any(
                    "schema 0.3 route metadata contains deprecated fields" in problem
                    for problem in problems
                ),
                problems,
            )

    def test_workspace_validate_detects_managed_file_hash_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            managed = root / ".agents" / "README.md"
            manifest_path = root / ".agents" / "manifest.json"
            manifest = mod.read_json(manifest_path)
            # Fresh v0.3 manifests may omit the integrity ledger.  Exercise
            # drift detection explicitly by opting this legacy managed file
            # into the optional ledger.
            manifest["managed_files"] = [".agents/README.md"]
            manifest["managed_hashes"] = {
                ".agents/README.md": hashlib.sha256(managed.read_bytes()).hexdigest()
            }
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            managed.write_text(managed.read_text(encoding="utf-8") + "\nlocal drift\n", encoding="utf-8")

            ok, problems = mod.validate_workspace(root)

            self.assertFalse(ok)
            self.assertTrue(any("hash mismatch" in problem for problem in problems), problems)

    def test_workspace_upgrade_preserves_custom_managed_file_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            custom = root / "custom.txt"
            custom.write_text("project-owned setup input\n", encoding="utf-8")
            manifest_path = root / ".agents" / "manifest.json"
            manifest = mod.read_json(manifest_path)
            manifest["managed_files"] = ["custom.txt"]
            manifest["managed_hashes"] = {}
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

            actions = mod.workspace_install(root, "upgrade", False)

            self.assertFalse(any(action.startswith("error ") for action in actions), actions)
            upgraded = mod.read_json(manifest_path)
            self.assertIn("custom.txt", upgraded["managed_hashes"])
            ok, problems = mod.validate_workspace(root)
            self.assertTrue(ok, problems)

    def test_workspace_upgrade_does_not_rebaseline_custom_managed_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            custom = root / "custom.txt"
            custom.write_text("baseline\n", encoding="utf-8")
            manifest_path = root / ".agents" / "manifest.json"
            manifest = mod.read_json(manifest_path)
            original_hash = hashlib.sha256(custom.read_bytes()).hexdigest()
            manifest["managed_files"] = ["custom.txt"]
            manifest["managed_hashes"] = {"custom.txt": original_hash}
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            custom.write_text("drifted\n", encoding="utf-8")

            actions = mod.workspace_install(root, "upgrade", False)

            self.assertFalse(any(action.startswith("error ") for action in actions), actions)
            upgraded = mod.read_json(manifest_path)
            self.assertEqual(upgraded["managed_hashes"]["custom.txt"], original_hash)
            ok, problems = mod.validate_workspace(root)
            self.assertFalse(ok)
            self.assertTrue(any("hash mismatch" in problem for problem in problems), problems)

    def test_workspace_upgrade_accepts_legacy_raw_hash_with_crlf(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            managed = root / ".agents" / "README.md"
            managed.write_bytes(managed.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"))
            manifest_path = root / ".agents" / "manifest.json"
            manifest = mod.read_json(manifest_path)
            manifest["managed_files"] = [".agents/README.md"]
            manifest["managed_hashes"] = {
                ".agents/README.md": hashlib.sha256(managed.read_bytes()).hexdigest()
            }
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

            actions = mod.workspace_install(root, "upgrade", True)

            self.assertFalse(any(action.startswith("preserve-conflict ") for action in actions), actions)

    def test_workspace_upgrade_accepts_partial_hash_map_for_unbound_asset(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            readme = root / ".agents" / "README.md"
            capability = root / ".agents" / "protocol" / "CAPABILITIES.md"
            manifest_path = root / ".agents" / "manifest.json"
            manifest = mod.read_json(manifest_path)
            manifest["schema_version"] = "0.2"
            manifest["managed_files"] = [
                ".agents/README.md",
                ".agents/protocol/CAPABILITIES.md",
            ]
            manifest["managed_hashes"] = {
                ".agents/protocol/CAPABILITIES.md": hashlib.sha256(
                    capability.read_bytes()
                ).hexdigest()
            }
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            readme.write_text("legacy unbound scaffold\n", encoding="utf-8")

            actions = mod.workspace_install(root, "upgrade", True)

            self.assertFalse(
                any(action.startswith("preserve-conflict ") for action in actions),
                actions,
            )

    def test_workspace_upgrade_preserves_manifest_extension(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            manifest_path = root / ".agents" / "manifest.json"
            manifest = mod.read_json(manifest_path)
            manifest["x-extension"] = {"owner": "project", "enabled": True}
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

            actions = mod.workspace_install(root, "upgrade", False)

            self.assertFalse(any(action.startswith("error ") for action in actions), actions)
            upgraded = mod.read_json(manifest_path)
            self.assertEqual(
                upgraded["x-extension"], {"owner": "project", "enabled": True}
            )

    def test_workspace_operations_support_custom_root_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            manifest_path = root / ".agents" / "manifest.json"
            registry_path = root / ".agents" / "coordination" / "routes.yaml"
            manifest = mod.read_json(manifest_path)
            registry = mod.read_json(registry_path)
            manifest["root_id"] = "acme-root"
            registry["root_id"] = "acme-root"
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
            create_args = type("Args", (), {
                "workspace": root,
                "action": "create",
                "path": "A Route",
                "route_id": "a-route",
                "display_name": "A Route",
                "state": None,
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(create_args), 0)

            self.assertEqual(mod.workspace_install(root, "adopt", False), [])
            self.assertEqual(mod.workspace_install(root, "repair", False), [])
            actions = mod.workspace_install(root, "upgrade", False)
            self.assertFalse(any(action.startswith("error ") for action in actions), actions)
            self.assertEqual(mod.validate_workspace(root), (True, []))

    def test_route_rename_keeps_route_agents_display_name_neutral(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            create_args = type("Args", (), {
                "workspace": root,
                "action": "create",
                "path": "A Route",
                "route_id": "a-route",
                "display_name": "Old Display",
                "state": None,
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(create_args), 0)
            agents = root / "A Route" / "AGENTS.md"
            before = agents.read_text(encoding="utf-8")
            self.assertNotIn("Old Display", before)
            rename_args = type("Args", (), {
                "workspace": root,
                "action": "rename",
                "path": None,
                "route_id": "a-route",
                "display_name": "New Display",
                "state": None,
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(rename_args), 0)
            self.assertEqual(before, agents.read_text(encoding="utf-8"))

    def test_route_rename_requires_explicit_nonempty_display_name(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            create_args = type("Args", (), {
                "workspace": root,
                "action": "create",
                "path": "A Route",
                "route_id": "a-route",
                "display_name": "Current Display",
                "state": None,
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(create_args), 0)
            registry_path = root / ".agents" / "coordination" / "routes.yaml"

            for display_name in (None, "", "   "):
                with self.subTest(display_name=display_name):
                    before = registry_path.read_bytes()
                    rename_args = type("Args", (), {
                        "workspace": root,
                        "action": "rename",
                        "path": None,
                        "route_id": "a-route",
                        "display_name": display_name,
                        "state": None,
                        "dry_run": False,
                    })()
                    self.assertEqual(mod.route_operation(rename_args), 1)
                    self.assertEqual(before, registry_path.read_bytes())

    def test_route_create_rejects_id_path_mismatch_without_orphan(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            create = type("Args", (), {
                "workspace": root,
                "action": "create",
                "path": "A Route",
                "route_id": "a-route",
                "display_name": "A Route",
                "state": None,
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(create), 0)
            before = (root / ".agents" / "coordination" / "routes.yaml").read_bytes()
            mismatch = type("Args", (), {
                "workspace": root,
                "action": "create",
                "path": "B Route",
                "route_id": "a-route",
                "display_name": "B Route",
                "state": None,
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(mismatch), 1)
            self.assertFalse((root / "B Route").exists())
            self.assertEqual(before, (root / ".agents" / "coordination" / "routes.yaml").read_bytes())

    def test_route_api_invalid_types_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            bad_create = type("Args", (), {
                "workspace": root,
                "action": "create",
                "path": "A Route",
                "route_id": {"bad": True},
                "display_name": "A Route",
                "state": None,
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(bad_create), 1)
            good_create = type("Args", (), {
                "workspace": root,
                "action": "create",
                "path": "A Route",
                "route_id": "a-route",
                "display_name": "A Route",
                "state": None,
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(good_create), 0)
            bad_state = type("Args", (), {
                "workspace": root,
                "action": "set-state",
                "path": None,
                "route_id": "a-route",
                "display_name": None,
                "state": [],
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(bad_state), 1)

    def test_workspace_manifest_schema_alias_conflict_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            manifest_path = root / ".agents" / "manifest.json"
            manifest = mod.read_json(manifest_path)
            manifest["schema_version"] = "0.2"
            manifest["version"] = "0.3"
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            before = {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }

            actions = mod.workspace_install(root, "upgrade", False)

            self.assertTrue(any("schema_version conflicts" in action for action in actions), actions)
            after = {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)

    def test_route_upgrade_preserves_extension_and_canonicalizes_registry(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            create_args = type("Args", (), {
                "workspace": root,
                "action": "create",
                "path": "C Route",
                "route_id": "c-route",
                "display_name": "C Route",
                "state": None,
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(create_args), 0)

            route_meta_path = root / "C Route" / ".agents" / "route.yaml"
            route_meta = mod.read_json(route_meta_path)
            route_meta["x-extension"] = {"owner": "route-test"}
            route_meta_path.write_text(json.dumps(route_meta, indent=2) + "\n", encoding="utf-8")

            registry_path = root / ".agents" / "coordination" / "routes.yaml"
            registry = mod.read_json(registry_path)
            registry["routes"][0]["x-extension"] = {"owner": "registry-test"}
            registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")

            upgrade_args = type("Args", (), {
                "workspace": root,
                "action": "upgrade",
                "path": None,
                "route_id": "c-route",
                "display_name": None,
                "state": None,
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(upgrade_args), 0)

            upgraded_meta = mod.read_json(route_meta_path)
            upgraded_registry = mod.read_json(registry_path)
            self.assertEqual(upgraded_meta["x-extension"], {"owner": "route-test"})
            self.assertEqual(upgraded_registry["routes"][0]["x-extension"], {"owner": "registry-test"})
            self.assertEqual(upgraded_registry["schema_version"], "0.3")
            self.assertTrue(mod.validate_workspace(root)[0])

    def test_workspace_upgrade_preserves_root_registry_extension(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            registry_path = root / ".agents" / "coordination" / "routes.yaml"
            registry = mod.read_json(registry_path)
            registry["x-root-extension"] = {"owner": "root-test", "enabled": True}
            registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")

            actions = mod.workspace_install(root, "upgrade", False)

            self.assertFalse(any(action.startswith("error ") for action in actions), actions)
            upgraded = mod.read_json(registry_path)
            self.assertEqual(
                upgraded["x-root-extension"], {"owner": "root-test", "enabled": True}
            )
            self.assertTrue(mod.validate_workspace(root)[0])

    def test_workspace_rejects_non_json_registry_extension_before_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            registry_path = root / ".agents" / "coordination" / "routes.yaml"
            registry = mod.read_json(registry_path)
            registry["x-root-extension"] = float("nan")
            registry_path.write_text(
                json.dumps(registry, indent=2, allow_nan=True) + "\n", encoding="utf-8"
            )
            before = registry_path.read_bytes()
            actions = mod.workspace_install(root, "upgrade", False)
            self.assertTrue(any(action.startswith("error ") for action in actions), actions)
            self.assertEqual(before, registry_path.read_bytes())

    def test_workspace_supports_multiple_routes_and_rejects_alias_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            for route_id, name in (("a-route", "A Route"), ("b-route", "B Route"), ("c-route", "C Route")):
                args = type("Args", (), {
                    "workspace": root,
                    "action": "create",
                    "path": name,
                    "route_id": route_id,
                    "display_name": name,
                    "state": None,
                    "dry_run": False,
                })()
                self.assertEqual(mod.route_operation(args), 0)

            registry_path = root / ".agents" / "coordination" / "routes.yaml"
            registry = mod.read_json(registry_path)
            self.assertEqual(
                {item["id"] for item in registry["routes"]},
                {"a-route", "b-route", "c-route"},
            )
            self.assertEqual(
                {item["path"] for item in registry["routes"]},
                {"A Route", "B Route", "C Route"},
            )
            self.assertEqual(mod.validate_workspace(root), (True, []))

            before = registry_path.read_bytes()
            alias_args = type("Args", (), {
                "workspace": root,
                "action": "create",
                "path": "A Route/",
                "route_id": "alias-route",
                "display_name": "Alias Route",
                "state": None,
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(alias_args), 1)
            self.assertEqual(before, registry_path.read_bytes())

    def test_workspace_validate_checks_root_instruction_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspace"
            mod.workspace_install(root, "adopt", False)
            agents = root / "AGENTS.md"
            agents.write_text(agents.read_text(encoding="utf-8").replace("<!-- ACHP-WORKSPACE:BEGIN -->", "<!-- removed -->"), encoding="utf-8")
            ok, problems = mod.validate_workspace(root)
            self.assertFalse(ok)
            self.assertTrue(any("AGENTS.md ACHP managed block" in problem for problem in problems), problems)

    def test_workspace_validate_rejects_root_managed_block_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspace"
            mod.workspace_install(root, "adopt", False)
            agents = root / "AGENTS.md"
            agents.write_text(agents.read_text(encoding="utf-8").replace("Project Collaboration Root", "Altered Root"), encoding="utf-8")
            ok, problems = mod.validate_workspace(root)
            self.assertFalse(ok)
            self.assertTrue(any("managed block drift" in problem for problem in problems), problems)

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

    def test_schema_03_registry_rejects_deprecated_endpoint_fields(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            create_args = type("Args", (), {
                "workspace": root,
                "action": "create",
                "path": "A Route",
                "route_id": "a-route",
                "display_name": "A Route",
                "state": None,
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(create_args), 0)
            registry_path = root / ".agents" / "coordination" / "routes.yaml"
            base = mod.read_json(registry_path)

            for field, value in (
                ("source_repository", {"status": "unknown"}),
                ("execution_endpoints", {"status": "unknown"}),
            ):
                with self.subTest(field=field):
                    candidate = json.loads(json.dumps(base))
                    candidate["routes"][0][field] = value
                    registry_path.write_text(
                        json.dumps(candidate, indent=2) + "\n", encoding="utf-8"
                    )
                    ok, problems = mod.validate_workspace(root)
                    self.assertFalse(ok, field)
                    self.assertTrue(
                        any("schema 0.3 route registry entry contains deprecated fields" in item for item in problems),
                        problems,
                    )

    def test_schema_03_route_metadata_rejects_deprecated_fields(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            create_args = type("Args", (), {
                "workspace": root,
                "action": "create",
                "path": "A Route",
                "route_id": "a-route",
                "display_name": "A Route",
                "state": None,
                "dry_run": False,
            })()
            self.assertEqual(mod.route_operation(create_args), 0)
            route_meta_path = root / "A Route" / ".agents" / "route.yaml"
            base = mod.read_json(route_meta_path)

            for field, value in (
                ("state", "active"),
                ("display_name", "A Route"),
                ("source_repository", {"status": "unknown"}),
            ):
                with self.subTest(field=field):
                    candidate = json.loads(json.dumps(base))
                    candidate[field] = value
                    route_meta_path.write_text(
                        json.dumps(candidate, indent=2) + "\n", encoding="utf-8"
                    )
                    ok, problems = mod.validate_workspace(root)
                    self.assertFalse(ok, field)
                    self.assertTrue(
                        any("schema 0.3 route metadata contains deprecated fields" in item for item in problems),
                        problems,
                    )

    def test_workspace_root_baseline_current_contract_allows_project_text(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            baseline = root / ".agents" / "coordination" / "ROOT-BASELINE.md"
            baseline.write_text(
                baseline.read_text(encoding="utf-8")
                + "\n## Project-specific constraints\n\nKeep this project-owned text.\n",
                encoding="utf-8",
            )

            actions = mod.workspace_install(root, "upgrade", False)

            self.assertFalse(any(action.startswith("error ") for action in actions), actions)
            self.assertIn(
                "Keep this project-owned text.",
                baseline.read_text(encoding="utf-8"),
            )
            self.assertEqual(mod.validate_workspace(root), (True, []))

    def test_workspace_root_baseline_rejects_schema_02_before_any_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            baseline = root / ".agents" / "coordination" / "ROOT-BASELINE.md"
            baseline.write_text(
                baseline.read_text(encoding="utf-8")
                + "\n## Retained legacy contract\n\n"
                + "Status: adopted Root baseline for ACHP Workspace schema 0.2.\n",
                encoding="utf-8",
            )
            before = {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }

            for dry_run in (True, False):
                with self.subTest(dry_run=dry_run):
                    actions = mod.workspace_install(root, "upgrade", dry_run)
                    self.assertTrue(
                        any(
                            action.startswith("error Root baseline:")
                            and "schema 0.2" in action
                            for action in actions
                        ),
                        actions,
                    )
                    after = {
                        str(path.relative_to(root)): path.read_bytes()
                        for path in root.rglob("*")
                        if path.is_file()
                    }
                    self.assertEqual(before, after)

            ok, problems = mod.validate_workspace(root)
            self.assertFalse(ok)
            self.assertTrue(
                any("Root baseline invalid" in item and "schema 0.2" in item for item in problems),
                problems,
            )

    def test_workspace_root_baseline_rejects_obsolete_registry_pointer_wording(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            baseline = root / ".agents" / "coordination" / "ROOT-BASELINE.md"
            baseline.write_text(
                baseline.read_text(encoding="utf-8")
                + "\nSource Repository and Execution Endpoint fields are metadata pointers only at this stage.\n",
                encoding="utf-8",
            )
            before = {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }

            actions = mod.workspace_install(root, "upgrade", False)

            self.assertTrue(
                any(
                    action.startswith("error Root baseline:")
                    and "obsolete Root registry pointer wording" in action
                    for action in actions
                ),
                actions,
            )
            after = {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)
            ok, problems = mod.validate_workspace(root)
            self.assertFalse(ok)
            self.assertTrue(
                any("obsolete Root registry pointer wording" in item for item in problems),
                problems,
            )

    def test_schema_02_workspace_reads_legacy_root_baseline_for_validate_adopt_repair(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            baseline = root / ".agents" / "coordination" / "ROOT-BASELINE.md"
            legacy_baseline = (SCHEMA_02_FIXTURES / "ROOT-BASELINE.md").read_bytes()
            baseline.write_bytes(legacy_baseline)

            manifest_path = root / ".agents" / "manifest.json"
            manifest = mod.read_json(manifest_path)
            manifest.update(
                {
                    "schema_version": "0.2",
                    "root_path": str(root),
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                    "mode": "adopt",
                    "baseline_path": ".agents/coordination/ROOT-BASELINE.md",
                    "source_state_path": ".agents/protocol/SOURCE-STATE.md",
                    "preserved_route_paths": [],
                    "managed_files": [],
                    "project_owned_files": [],
                    "managed_hashes": {},
                }
            )
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            registry_path = root / ".agents" / "coordination" / "routes.yaml"
            registry = mod.read_json(registry_path)
            registry["schema_version"] = "0.2"
            registry_path.write_text(
                json.dumps(registry, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            self.assertEqual(mod.validate_workspace(root), (True, []))
            baseline_before = baseline.read_bytes()
            for mode in ("adopt", "repair"):
                with self.subTest(mode=mode):
                    dry_actions = mod.workspace_install(root, mode, True)
                    self.assertFalse(
                        any(action.startswith("error ") for action in dry_actions),
                        dry_actions,
                    )
                    self.assertEqual(baseline_before, baseline.read_bytes())
                    actions = mod.workspace_install(root, mode, False)
                    self.assertFalse(
                        any(action.startswith("error ") for action in actions),
                        actions,
                    )
                    self.assertEqual(baseline_before, baseline.read_bytes())
                    self.assertEqual(mod.validate_workspace(root), (True, []))

    def test_schema_02_upgrade_requires_review_for_legacy_root_baseline(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            baseline = root / ".agents" / "coordination" / "ROOT-BASELINE.md"
            baseline.write_bytes(
                (SCHEMA_02_FIXTURES / "ROOT-BASELINE.md").read_bytes()
            )
            manifest_path = root / ".agents" / "manifest.json"
            manifest = mod.read_json(manifest_path)
            manifest["schema_version"] = "0.2"
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            registry_path = root / ".agents" / "coordination" / "routes.yaml"
            registry = mod.read_json(registry_path)
            registry["schema_version"] = "0.2"
            registry_path.write_text(
                json.dumps(registry, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            before = {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }

            for dry_run in (True, False):
                with self.subTest(dry_run=dry_run):
                    actions = mod.workspace_install(root, "upgrade", dry_run)
                    self.assertTrue(
                        any(
                            action.startswith("error Root baseline upgrade review required:")
                            for action in actions
                        ),
                        actions,
                    )
                    after = {
                        str(path.relative_to(root)): path.read_bytes()
                        for path in root.rglob("*")
                        if path.is_file()
                    }
                    self.assertEqual(before, after)

            self.assertEqual(mod.validate_workspace(root), (True, []))

    def test_schema_02_upgrade_accepts_reviewed_schema_03_root_baseline(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.workspace_install(root, "adopt", False)
            manifest_path = root / ".agents" / "manifest.json"
            manifest = mod.read_json(manifest_path)
            manifest["schema_version"] = "0.2"
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            registry_path = root / ".agents" / "coordination" / "routes.yaml"
            registry = mod.read_json(registry_path)
            registry["schema_version"] = "0.2"
            registry_path.write_text(
                json.dumps(registry, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            actions = mod.workspace_install(root, "upgrade", False)

            self.assertFalse(any(action.startswith("error ") for action in actions), actions)
            self.assertEqual(mod.read_json(manifest_path)["schema_version"], "0.3")
            self.assertEqual(mod.read_json(registry_path)["schema_version"], "0.3")
            self.assertEqual(mod.validate_workspace(root), (True, []))

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
