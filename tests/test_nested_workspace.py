"""Behavioral coverage for management roots embedded in real Git checkouts."""

import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "nested_workspace_setup", ROOT / "scripts" / "workspace_setup.py"
)
workspace = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(workspace)


def tree_snapshot(root):
    """Include empty directories and links, and never follow a directory link."""
    result = {}
    if not root.exists():
        return result
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                result[relative] = ("link", os.readlink(path))
            elif path.is_dir():
                result[relative] = ("directory",)
            else:
                result[relative] = ("file", path.read_bytes())
    return result


@unittest.skipUnless(shutil.which("git"), "Git is required for nested checkout tests")
class NestedWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="achp-nested-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repo = self.base / "source"
        self.repo.mkdir()
        self.root = self.repo / "management" / "collaboration"

    def git(self, *args, cwd=None, expected=0):
        env = dict(os.environ)
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"):
            env.pop(name, None)
        env.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_SYSTEM=os.devnull,
            GIT_TERMINAL_PROMPT="0",
            GIT_OPTIONAL_LOCKS="0",
        )
        completed = subprocess.run(
            [
                "git",
                "-c", "core.autocrlf=false",
                "-c", "core.excludesFile=" + os.devnull,
                "-c", "user.name=ACHP Test",
                "-c", "user.email=achp-test@example.invalid",
                *args,
            ],
            cwd=cwd or self.repo,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            expected,
            f"git {args!r}\n{completed.stdout}\n{completed.stderr}",
        )
        return completed.stdout

    def init_repo(self):
        self.git("init", "--quiet", "--initial-branch=main")

    def write(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))

    def read_manifest(self, root=None):
        return json.loads(((root or self.root) / ".agents/manifest.json").read_text(encoding="utf-8"))

    def install(self, mode="adopt", *, root=None, dry_run=False):
        actions = workspace.workspace_install(root or self.root, mode, dry_run)
        self.assertFalse(
            any(action.startswith(("error ", "preserve-conflict ")) for action in actions),
            actions,
        )
        return actions

    def assert_valid(self, root=None):
        ok, problems = workspace.validate_workspace(root or self.root)
        self.assertTrue(ok, problems)

    def assert_refused_without_writes(self, mode="adopt", *, root=None, dry_run=False):
        before = tree_snapshot(self.base)
        actions = workspace.workspace_install(root or self.root, mode, dry_run)
        self.assertTrue(
            any(action.startswith(("error ", "preserve-conflict ")) for action in actions),
            actions,
        )
        self.assertEqual(before, tree_snapshot(self.base), actions)
        return actions

    def create_route(self, root=None):
        root = root or self.root
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = workspace.main(
                [
                    "route", "create", "--workspace", str(root),
                    "--path", "routes/research", "--route-id", "durable-research-id",
                    "--display-name", "Research",
                ]
            )
        self.assertEqual(result, 0, output.getvalue())
        return root / "routes/research"

    def legacy_workspace(self):
        # Install before git init to reproduce the original standalone layout.
        self.install()
        manifest_path = self.root / ".agents/manifest.json"
        manifest = self.read_manifest()
        manifest.pop("collaboration_root_mode", None)
        manifest["root_id"] = "durable-management-id"
        self.write(manifest_path, json.dumps(manifest, indent=2) + "\n")
        registry_path = self.root / ".agents/coordination/routes.yaml"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["root_id"] = manifest["root_id"]
        self.write(registry_path, json.dumps(registry, indent=2) + "\n")
        route = self.create_route()
        self.write(self.root / ".agents/knowledge/guides/root-note.md", "Keep Root knowledge.\n")
        self.write(route / ".agents/knowledge/guides/route-note.md", "Keep Route knowledge.\n")
        self.init_repo()
        self.write(self.repo / ".gitignore", "project-cache/\n")
        return route

    def assert_ignore_boundary(self, repo, root):
        relative = root.relative_to(repo).as_posix()
        runtime = root / ".agents/runtime/session.json"
        self.write(runtime, "{\"machine_local\": true}\n")
        self.git("check-ignore", "--quiet", "--", runtime.relative_to(repo).as_posix(), cwd=repo)
        for path in (
            "AGENTS.md",
            ".agents/manifest.json",
            ".agents/knowledge/index.yaml",
            "routes/research/AGENTS.md",
            "routes/research/.agents/route.yaml",
            "routes/research/.agents/knowledge/index.yaml",
        ):
            with self.subTest(path=path):
                self.assertTrue((root / path).is_file())
                self.git("check-ignore", "--quiet", "--", f"{relative}/{path}", cwd=repo, expected=1)
        # The anchored rule must not match the same suffix in another subtree.
        self.git(
            "check-ignore", "--quiet", "--", f"elsewhere/{relative}/.agents/runtime/session.json",
            cwd=repo, expected=1,
        )

    def test_new_nested_root_preserves_parent_rules_and_git_tracks_management(self):
        self.init_repo()
        existing = (
            "# User rules\nproject-cache/\n!project-cache/keep.txt\n\n"
            "# ACHP:BEGIN\ncustom-root-cache/\n# ACHP:END\n\n"
            "# ACHP-NESTED:other-team:BEGIN\ncustom-other-team-rule/\n"
            "# ACHP-NESTED:other-team:END\n"
        )
        self.write(self.repo / ".gitignore", existing)

        self.install()
        self.create_route()

        manifest = self.read_manifest()
        self.assertEqual(manifest["collaboration_root_mode"], "nested-repository")
        self.assertIs(manifest["execution_repository_required"], True)
        self.assertFalse((self.root / ".gitignore").exists())
        parent_ignore = (self.repo / ".gitignore").read_text(encoding="utf-8")
        self.assertTrue(parent_ignore.startswith(existing))
        self.assertIn("# ACHP-NESTED:management/collaboration:BEGIN\n", parent_ignore)
        self.assertIn("/management/collaboration/.agents/runtime/*\n", parent_ignore)
        self.assertIn("# ACHP-NESTED:management/collaboration:END\n", parent_ignore)
        self.assert_valid()
        self.assert_ignore_boundary(self.repo, self.root)
        self.git("check-ignore", "--quiet", "--", "custom-root-cache/result.txt")

    def test_literal_nested_path_escapes_git_patterns(self):
        self.init_repo()
        root = self.repo / "team [one]" / "collab #notes!"
        self.install(root=root)
        self.create_route(root)
        ignore = (self.repo / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(r"/team\ \[one\]/collab\ #notes!/.agents/runtime/*", ignore)
        self.assert_ignore_boundary(self.repo, root)
        self.git(
            "check-ignore", "--quiet", "--",
            "team o/collab #notes!/.agents/runtime/session.json", expected=1,
        )

    def test_multiple_roots_keep_each_block_and_all_modes_are_idempotent(self):
        self.init_repo()
        second = self.repo / "other-management"
        self.write(self.repo / ".gitignore", "existing-rule/\n")
        self.install()
        first_ignore = (self.repo / ".gitignore").read_bytes()
        self.install(root=second)
        self.assertTrue((self.repo / ".gitignore").read_bytes().startswith(first_ignore))
        before = tree_snapshot(self.base)
        for root in (self.root, second):
            for mode in ("adopt", "repair", "upgrade"):
                with self.subTest(root=root.name, mode=mode):
                    self.assertEqual(self.install(mode, root=root), [])
                    self.assert_valid(root)
                    self.assertEqual(before, tree_snapshot(self.base))
        ignore = (self.repo / ".gitignore").read_text(encoding="utf-8")
        self.assertEqual(ignore.count("# ACHP-NESTED:management/collaboration:BEGIN"), 1)
        self.assertEqual(ignore.count("# ACHP-NESTED:other-management:BEGIN"), 1)

    def test_new_nested_dry_run_leaves_entire_repository_unchanged(self):
        self.init_repo()
        self.write(self.repo / ".gitignore", "existing-rule/\n")
        self.write(self.repo / "uncommitted.txt", "User work.\n")
        before = tree_snapshot(self.base)
        for mode in ("bootstrap", "adopt"):
            with self.subTest(mode=mode):
                self.assertTrue(self.install(mode, dry_run=True))
                self.assertFalse(self.root.exists())
                self.assertEqual(before, tree_snapshot(self.base))

    def test_repair_restores_missing_parent_ignore_without_rewriting_root(self):
        self.init_repo()
        self.install()
        root_before = tree_snapshot(self.root)
        for missing in ("file", "block"):
            with self.subTest(missing=missing):
                ignore = self.repo / ".gitignore"
                if missing == "file":
                    ignore.unlink()
                else:
                    self.write(ignore, "preserved-project-rule/\n")
                ok, problems = workspace.validate_workspace(self.root)
                self.assertFalse(ok, problems)
                before = tree_snapshot(self.base)
                self.assertTrue(self.install("repair", dry_run=True))
                self.assertEqual(before, tree_snapshot(self.base))
                self.assertTrue(self.install("repair"))
                self.assert_valid()
                self.assertFalse((self.root / ".gitignore").exists())
                self.assertEqual(root_before, tree_snapshot(self.root))
                if missing == "block":
                    self.assertTrue(ignore.read_text(encoding="utf-8").startswith("preserved-project-rule/\n"))

    def test_legacy_adopt_and_repair_preserve_layout_and_missing_mode(self):
        self.legacy_workspace()
        before = tree_snapshot(self.base)
        for mode in ("adopt", "repair"):
            with self.subTest(mode=mode):
                self.assertEqual(self.install(mode), [])
                self.assert_valid()
                self.assertNotIn("collaboration_root_mode", self.read_manifest())
                self.assertIs(self.read_manifest()["execution_repository_required"], False)
                self.assertTrue((self.root / ".gitignore").is_file())
                self.assertEqual(before, tree_snapshot(self.base))

    def test_explicit_legacy_upgrade_moves_canonical_ignore_and_preserves_identity(self):
        route = self.legacy_workspace()
        preserved = {
            path: path.read_bytes()
            for path in (
                self.root / ".agents/coordination/routes.yaml",
                self.root / ".agents/knowledge/guides/root-note.md",
                route / ".agents/route.yaml",
                route / ".agents/knowledge/guides/route-note.md",
            )
        }
        before = tree_snapshot(self.base)
        self.assertTrue(self.install("upgrade", dry_run=True))
        self.assertEqual(before, tree_snapshot(self.base))

        self.install("upgrade")

        manifest = self.read_manifest()
        self.assertEqual(manifest["root_id"], "durable-management-id")
        self.assertEqual(manifest["collaboration_root_mode"], "nested-repository")
        self.assertIs(manifest["execution_repository_required"], True)
        self.assertFalse((self.root / ".gitignore").exists())
        self.assertTrue((self.repo / ".gitignore").read_text(encoding="utf-8").startswith("project-cache/\n"))
        for path, content in preserved.items():
            self.assertEqual(path.read_bytes(), content, str(path))
        self.assert_valid()
        self.assert_ignore_boundary(self.repo, self.root)
        after = tree_snapshot(self.base)
        self.assertEqual(self.install("upgrade"), [])
        self.assertEqual(after, tree_snapshot(self.base))

    def test_custom_child_ignore_refuses_migration_before_writes(self):
        self.legacy_workspace()
        child = self.root / ".gitignore"
        self.write(child, child.read_text(encoding="utf-8") + "\nproject-owned-cache/\n")
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                self.assert_refused_without_writes("upgrade", dry_run=dry_run)
        self.assertNotIn("collaboration_root_mode", self.read_manifest())

    def test_fresh_nested_root_refuses_existing_child_ignore(self):
        self.init_repo()
        canonical = (ROOT / "assets/scaffold/workspace/GITIGNORE_BLOCK.txt").read_text(encoding="utf-8")
        for content in ("user-owned-cache/\n", canonical):
            with self.subTest(content=content.splitlines()[0]):
                self.write(self.root / ".gitignore", content)
                self.assert_refused_without_writes()
                self.assertFalse((self.root / ".agents/manifest.json").exists())

    def test_custom_or_malformed_own_parent_block_refuses_before_writes(self):
        self.init_repo()
        begin = "# ACHP-NESTED:management/collaboration:BEGIN"
        end = "# ACHP-NESTED:management/collaboration:END"
        cases = {
            "custom": f"{begin}\nproject-owned-cache/\n{end}\n",
            "missing-end": f"{begin}\nunfinished\n",
            "missing-begin": f"orphaned\n{end}\n",
            "reversed": f"{end}\n{begin}\n",
            "duplicate": f"{begin}\nfirst\n{end}\n{begin}\nsecond\n{end}\n",
        }
        for name, content in cases.items():
            for dry_run in (True, False):
                with self.subTest(case=name, dry_run=dry_run):
                    self.write(self.repo / ".gitignore", "existing-rule/\n" + content)
                    self.assert_refused_without_writes(dry_run=dry_run)
                    self.assertFalse(self.root.exists())

    def test_invalid_parent_ignore_and_git_marker_refuse_before_writes(self):
        self.init_repo()
        (self.repo / ".gitignore").mkdir()
        self.assert_refused_without_writes()
        self.assertFalse(self.root.exists())

        invalid_repo = self.base / "invalid-repository"
        invalid_repo.mkdir()
        invalid_root = invalid_repo / "management"
        self.write(invalid_repo / ".git", "gitdir: missing-git-directory\n")
        self.assert_refused_without_writes(root=invalid_root)
        self.assertFalse(invalid_root.exists())

    def test_parent_ignore_symlink_is_rejected_without_touching_target(self):
        self.init_repo()
        target = self.base / "external-ignore"
        self.write(target, "external-user-rule/\n")
        try:
            (self.repo / ".gitignore").symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"file symlinks are unavailable: {exc}")
        self.assert_refused_without_writes()
        self.assertFalse(self.root.exists())
        self.assertEqual(target.read_bytes(), b"external-user-rule/\n")

    def test_non_string_manifest_mode_is_a_controlled_error_for_all_commands(self):
        self.init_repo()
        self.install()
        manifest = self.read_manifest()
        for invalid in ([], {}, None, True):
            with self.subTest(mode=invalid):
                manifest["collaboration_root_mode"] = invalid
                self.write(self.root / ".agents/manifest.json", json.dumps(manifest) + "\n")
                before = tree_snapshot(self.base)
                for action in ("adopt", "repair", "upgrade", "validate"):
                    with contextlib.redirect_stdout(io.StringIO()) as output:
                        result = workspace.main(["workspace", action, "--root", str(self.root)])
                    self.assertEqual(result, 1, output.getvalue())
                    self.assertIn("collaboration_root_mode", output.getvalue())
                    self.assertNotIn("Traceback", output.getvalue())
                    self.assertEqual(before, tree_snapshot(self.base))

    def checkout_from_agents(self, root):
        text = (root / "AGENTS.md").read_text(encoding="utf-8")
        match = re.search(r"Local source checkout relative to this Management Root: `([^`]+)`", text)
        self.assertIsNotNone(match, text)
        self.assertNotIn("{{SOURCE_CHECKOUT_RELATIVE}}", text)
        return match.group(1), (root / match.group(1)).resolve()

    def test_agents_binding_resolves_checkout_at_each_nesting_depth(self):
        self.init_repo()
        self.write(self.repo / "product.txt", "Source file outside management.\n")
        for relative, expected in (("lead", ".."), ("teams/lead", "../.."), ("teams/product/lead", "../../..")):
            with self.subTest(relative=relative):
                root = self.repo / relative
                self.install(root=root)
                pointer, checkout = self.checkout_from_agents(root)
                self.assertEqual(pointer, expected)
                self.assertEqual(checkout, self.repo.resolve())
                self.git("add", "--", "product.txt", cwd=checkout)
                self.assertEqual(self.git("diff", "--cached", "--name-only", cwd=checkout), "product.txt\n")
                self.assert_valid(root)

    def test_missing_agents_binding_repair_preserves_user_text_and_is_idempotent(self):
        self.init_repo()
        self.install()
        agents = self.root / "AGENTS.md"
        original = agents.read_text(encoding="utf-8")
        old_body = original.split(workspace.SOURCE_CHECKOUT_BEGIN, 1)[0]
        legacy = "# User startup\nKeep project rules.\n\n" + old_body + "\n## User local notes\nKeep me too.  \n\n\n"
        self.write(agents, legacy)
        self.assertFalse(workspace.validate_workspace(self.root)[0])
        before = tree_snapshot(self.base)
        self.assertTrue(self.install("repair", dry_run=True))
        self.assertEqual(before, tree_snapshot(self.base))
        self.install("repair")
        repaired = agents.read_text(encoding="utf-8")
        self.assertTrue(repaired.startswith(legacy))
        self.assertEqual(self.checkout_from_agents(self.root)[1], self.repo.resolve())
        self.assert_valid()
        for mode in ("adopt", "repair", "upgrade"):
            self.assertEqual(self.install(mode), [])
        self.assertEqual(agents.read_text(encoding="utf-8"), repaired)

    def test_custom_or_invalid_agents_binding_refuses_before_writes(self):
        self.init_repo()
        self.install()
        agents = self.root / "AGENTS.md"
        original = agents.read_text(encoding="utf-8")
        cases = (
            original.replace("Root: `../..`", "Root: `..`"),
            original.replace(workspace.SOURCE_CHECKOUT_END, ""),
            original + "\n" + workspace.SOURCE_CHECKOUT_BEGIN + "\nextra\n" + workspace.SOURCE_CHECKOUT_END,
        )
        for content in cases:
            self.write(agents, content)
            self.assertFalse(workspace.validate_workspace(self.root)[0])
            for mode in ("adopt", "repair", "upgrade"):
                for dry in (True, False):
                    self.assert_refused_without_writes(mode, dry_run=dry)

    def test_standalone_workspace_has_no_assumed_source_binding(self):
        self.install()
        self.assertNotIn(workspace.SOURCE_CHECKOUT_BEGIN, (self.root / "AGENTS.md").read_text(encoding="utf-8"))
        self.assert_valid()

    def test_linked_worktree_and_local_clone_preserve_layout_and_identity(self):
        self.init_repo()
        self.install()
        route = self.create_route()
        self.write(route / ".agents/knowledge/guides/shared.md", "Durable shared knowledge.\n")
        self.git("add", "--", ".")
        self.git("commit", "--quiet", "-m", "Create nested management fixture")
        expected = tree_snapshot(self.root)
        expected_manifest = self.read_manifest()
        relative = self.root.relative_to(self.repo)
        linked = self.base / "linked-checkout"
        cloned = self.base / "second-clone"
        self.git("worktree", "add", "--quiet", "-b", "linked-tests", str(linked))
        self.git("clone", "--quiet", "--local", str(self.repo), str(cloned), cwd=self.base)
        self.assertTrue((linked / ".git").is_file())
        self.assertTrue((cloned / ".git").is_dir())
        for checkout in (linked, cloned):
            with self.subTest(checkout=checkout.name):
                root = checkout / relative
                self.assertEqual(expected, tree_snapshot(root))
                self.assertEqual(expected_manifest, self.read_manifest(root))
                self.assertFalse((root / ".gitignore").exists())
                self.assertEqual(self.checkout_from_agents(root)[1], checkout.resolve())
                self.assert_valid(root)
                before = tree_snapshot(self.base)
                for mode in ("adopt", "repair", "upgrade"):
                    self.assertEqual(self.install(mode, root=root), [])
                    self.assertEqual(before, tree_snapshot(self.base))
                self.assert_ignore_boundary(checkout, root)
                self.assertEqual(self.git("status", "--porcelain", cwd=checkout), "")


if __name__ == "__main__":
    unittest.main()
