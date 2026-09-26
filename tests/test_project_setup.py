import importlib.util
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


if __name__ == "__main__":
    unittest.main()
