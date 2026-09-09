import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "install_skill", ROOT / "scripts" / "install_skill.py"
)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(mod)


def make_source(root: Path, version: str = "0.4.0") -> Path:
    source = root / "source"
    (source / "scripts").mkdir(parents=True)
    (source / "SKILL.md").write_text(
        "---\nname: agent-collaboration-setup\ndescription: test\n---\n",
        encoding="utf-8",
    )
    (source / "VERSION").write_text(version + "\n", encoding="utf-8")
    (source / "scripts" / "tool.py").write_text("VALUE = 1\n", encoding="utf-8")
    return source


class InstallSkillSafetyTests(unittest.TestCase):
    def test_copy_install_records_ownership_and_detects_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_source(root)
            dest = root / "installed"

            self.assertEqual(mod.install_one(source, dest, "copy"), "copied")
            marker = json.loads((dest / mod.INSTALL_MARKER).read_text(encoding="utf-8"))
            self.assertEqual(marker["skill"], mod.SKILL_NAME)
            self.assertEqual(marker["content_sha256"], mod.content_digest(source))
            self.assertEqual(mod.check_one(source, dest), (True, "copy digest=match"))

            (dest / "scripts" / "tool.py").write_text("VALUE = 2\n", encoding="utf-8")
            ok, detail = mod.check_one(source, dest)
            self.assertFalse(ok)
            self.assertEqual(detail, "copy digest=mismatch")

    def test_unknown_existing_destination_is_never_replaced_or_removed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_source(root)
            dest = root / "installed"
            dest.mkdir()
            keep = dest / "USER.txt"
            keep.write_text("keep\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                mod.install_one(source, dest, "copy")
            with self.assertRaises(ValueError):
                mod._remove_owned_destination(source, dest)

            self.assertEqual(keep.read_text(encoding="utf-8"), "keep\n")

    def test_owned_copy_can_be_updated_and_uninstalled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_source(root, "0.4.0")
            dest = root / "installed"
            mod.install_one(source, dest, "copy")

            (source / "VERSION").write_text("0.4.1\n", encoding="utf-8")
            (source / "scripts" / "tool.py").write_text("VALUE = 3\n", encoding="utf-8")
            self.assertEqual(mod.install_one(source, dest, "copy"), "copied")
            self.assertEqual((dest / "VERSION").read_text(encoding="utf-8"), "0.4.1\n")
            self.assertEqual(mod.check_one(source, dest), (True, "copy digest=match"))

            mod._remove_owned_destination(source, dest)
            self.assertFalse(dest.exists())

    def test_install_payload_excludes_repository_development_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_source(root)
            (source / ".agents").mkdir()
            (source / ".agents" / "secret-development-state.txt").write_text(
                "not installable\n", encoding="utf-8"
            )
            (source / "dist").mkdir()
            (source / "dist" / "old.zip").write_text("old\n", encoding="utf-8")
            dest = root / "installed"

            mod.install_one(source, dest, "copy")

            self.assertFalse((dest / ".agents").exists())
            self.assertFalse((dest / "dist").exists())

    def test_malformed_marker_is_reported_as_failed_check(self):
        """A damaged marker must not escape the check path as a traceback."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_source(root)
            dest = root / "installed"
            mod.install_one(source, dest, "copy")

            (dest / mod.INSTALL_MARKER).write_bytes(b"\xff\xfe not utf-8")

            ok, detail = mod.check_one(source, dest)
            self.assertFalse(ok)
            self.assertIn("marker", detail.lower())

    def test_marker_source_mismatch_refuses_update_and_uninstall(self):
        """A copy owned by another checkout is not ours to replace or remove."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_source(root)
            dest = root / "installed"
            mod.install_one(source, dest, "copy")
            marker_path = dest / mod.INSTALL_MARKER
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            marker["source"] = str(root / "another-source")
            marker_path.write_text(json.dumps(marker) + "\n", encoding="utf-8")
            before = (dest / "scripts" / "tool.py").read_bytes()

            with self.assertRaises(ValueError):
                mod.install_one(source, dest, "copy")
            with self.assertRaises(ValueError):
                mod._remove_owned_destination(source, dest)

            self.assertEqual(before, (dest / "scripts" / "tool.py").read_bytes())
            self.assertTrue(dest.exists())

    def test_nested_user_file_blocks_replace_and_uninstall(self):
        """An owned copy with an extension must be preserved for review."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_source(root)
            dest = root / "installed"
            mod.install_one(source, dest, "copy")
            custom = dest / "scripts" / "local-tool.py"
            custom.write_text("LOCAL = True\n", encoding="utf-8")
            before = custom.read_bytes()

            with self.assertRaises(ValueError):
                mod.install_one(source, dest, "copy")
            with self.assertRaises(ValueError):
                mod._remove_owned_destination(source, dest)

            self.assertEqual(before, custom.read_bytes())
            self.assertTrue(dest.exists())

    def test_missing_core_payload_is_rejected_without_creating_destination(self):
        """A partial checkout cannot be published as a Skill installation."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_source(root)
            (source / "SKILL.md").unlink()
            dest = root / "installed"

            with self.assertRaises(ValueError):
                mod.install_one(source, dest, "copy")

            self.assertFalse(dest.exists())

    def test_auto_mode_falls_back_when_symlink_creation_is_unavailable(self):
        """Auto mode may fall back only when creating the link itself fails."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_source(root)
            dest = root / "installed"

            with mock.patch.object(Path, "symlink_to", side_effect=OSError("link unavailable")):
                result = mod.install_one(source, dest, "auto")

            self.assertEqual(result, "copied")
            self.assertTrue((dest / "SKILL.md").exists())
            self.assertEqual(mod.check_one(source, dest)[0], True)

    def test_auto_mode_does_not_hide_replacement_failure(self):
        """An error after link creation must not be misreported as copy fallback."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_source(root)
            dest = root / "installed"

            with mock.patch.object(Path, "symlink_to", return_value=None), mock.patch.object(
                mod, "_replace_with_staged", side_effect=OSError("replace failed")
            ):
                with self.assertRaises(OSError):
                    mod.install_one(source, dest, "auto")

            self.assertFalse(dest.exists())

    def test_payload_digest_and_copy_agree_on_ignored_files(self):
        """Ignored cache files must not make a fresh copy fail its check."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_source(root)
            (source / "scripts" / ".DS_Store").write_bytes(b"cache")
            (source / "scripts" / "__pycache__").mkdir()
            (source / "scripts" / "__pycache__" / "tool.cpython-39.pyc").write_bytes(
                b"cache"
            )
            dest = root / "installed"

            self.assertEqual(mod.install_one(source, dest, "copy"), "copied")
            self.assertEqual(mod.check_one(source, dest), (True, "copy digest=match"))

    def test_symlink_inside_allowlisted_payload_is_rejected(self):
        """The installer must never copy an allowlisted link target."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_source(root)
            external = root / "external-secret.txt"
            external.write_text("secret\n", encoding="utf-8")
            references = source / "references"
            references.mkdir()
            link = references / "linked.txt"
            try:
                link.symlink_to(external)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            dest = root / "installed"

            with self.assertRaises(ValueError):
                mod.install_one(source, dest, "copy")

            self.assertFalse(dest.exists())
            self.assertEqual(external.read_text(encoding="utf-8"), "secret\n")

    def test_symlink_in_excluded_development_state_does_not_expand_payload(self):
        """Excluded development state is outside the install payload boundary."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_source(root)
            external = root / "external-development.txt"
            external.write_text("development\n", encoding="utf-8")
            agents = source / ".agents"
            agents.mkdir()
            link = agents / "external.txt"
            try:
                link.symlink_to(external)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            dest = root / "installed"

            self.assertEqual(mod.install_one(source, dest, "copy"), "copied")
            self.assertFalse((dest / ".agents").exists())
            self.assertEqual(mod.check_one(source, dest)[0], True)

    def test_existing_source_symlink_is_idempotent(self):
        """A link already owned by this checkout can be safely re-run."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_source(root)
            dest = root / "installed"
            try:
                dest.symlink_to(source, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            self.assertEqual(mod.install_one(source, dest, "auto"), "linked")
            self.assertTrue(dest.is_symlink())
            self.assertEqual(mod.check_one(source, dest)[0], True)

    def test_non_source_destination_symlink_is_refused(self):
        """A link to another location must never be followed or replaced."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_source(root)
            external = root / "external"
            external.mkdir()
            (external / "keep.txt").write_text("keep\n", encoding="utf-8")
            dest = root / "installed"
            try:
                dest.symlink_to(external, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            with self.assertRaises(ValueError):
                mod.install_one(source, dest, "auto")

            self.assertTrue(dest.is_symlink())
            self.assertEqual((external / "keep.txt").read_text(encoding="utf-8"), "keep\n")


if __name__ == "__main__":
    unittest.main()
