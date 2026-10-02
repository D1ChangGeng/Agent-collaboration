import importlib.util
import io
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


def make_knowledge_sources(source: Path, content: str) -> None:
    for name in mod.KNOWLEDGE_NAMES:
        skill = source / mod.KNOWLEDGE_SOURCE / name
        (skill / "references").mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"name: {name}\n{content}\n", encoding="utf-8")
        (skill / "references" / "model.md").write_text(content + "\n", encoding="utf-8")


def installed_bytes(root: Path):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*") if path.is_file()
    }


class InstallSkillSafetyTests(unittest.TestCase):
    def test_verified_previous_copy_migrates_to_new_source_and_remains_owned(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            previous = make_source(root / "old", "0.4.0")
            source = make_source(root / "new", "0.4.1")
            (previous / "README.md").write_text("Prior documentation\n", encoding="utf-8")
            (source / "scripts" / "tool.py").write_text("VALUE = 3\n", encoding="utf-8")
            dest = root / "installed"
            mod.install_one(previous, dest, "copy")

            with self.assertRaises(ValueError):
                mod.install_one(source, dest, "copy")
            self.assertEqual(mod.install_one(source, dest, "copy", previous_source=previous), "copied")
            self.assertFalse((dest / "README.md").exists())
            self.assertEqual((dest / "scripts" / "tool.py").read_text(encoding="utf-8"), "VALUE = 3\n")
            marker = json.loads((dest / mod.INSTALL_MARKER).read_text(encoding="utf-8"))
            self.assertEqual(marker["source"], str(source.resolve()))
            self.assertEqual(marker["version"], "0.4.1")
            self.assertEqual(mod.check_one(source, dest), (True, "copy digest=match"))
            self.assertEqual(mod.install_one(source, dest, "copy", previous_source=previous), "copied")
            with self.assertRaises(ValueError):
                mod._remove_owned_destination(previous, dest)
            mod._remove_owned_destination(source, dest)
            self.assertFalse(dest.exists())

    def test_previous_copy_migration_preserves_drift_extras_and_foreign_ownership(self):
        for change in ("installed-drift", "extra", "foreign-marker", "prior-source-drift", "bad-digest"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                previous = make_source(root / "old")
                source = make_source(root / "new", "0.4.1")
                dest = root / "installed"
                mod.install_one(previous, dest, "copy")
                if change == "installed-drift":
                    (dest / "scripts" / "tool.py").write_text("LOCAL = True\n", encoding="utf-8")
                elif change == "extra":
                    (dest / "scripts" / "local.py").write_text("LOCAL = True\n", encoding="utf-8")
                elif change == "prior-source-drift":
                    (previous / "scripts" / "tool.py").write_text("LOCAL = True\n", encoding="utf-8")
                else:
                    marker_path = dest / mod.INSTALL_MARKER
                    marker = json.loads(marker_path.read_text(encoding="utf-8"))
                    if change == "foreign-marker":
                        marker["source"] = str(root / "third-source")
                    else:
                        marker["content_sha256"] = "0" * 64
                    marker_path.write_text(json.dumps(marker) + "\n", encoding="utf-8")
                before = installed_bytes(dest)

                with self.assertRaises(ValueError):
                    mod.install_one(source, dest, "copy", previous_source=previous)

                self.assertEqual(installed_bytes(dest), before)
                self.assertEqual(list(root.glob(".installed.*")), [])

    def test_previous_source_must_match_exact_marker_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            previous = make_source(root / "version-0.4.0")
            other = make_source(root / "other-version-0.4.0")
            source = make_source(root / "version-0.4.1", "0.4.1")
            dest = root / "installed"
            mod.install_one(other, dest, "copy")
            before = installed_bytes(dest)

            with self.assertRaises(ValueError):
                mod.install_one(source, dest, "copy", previous_source=previous)

            self.assertEqual(installed_bytes(dest), before)

    def test_previous_symlink_migrates_to_new_payload(self):
        for mode in ("copy", "symlink"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                previous = make_source(root / "old")
                source = make_source(root / "new", "0.4.1")
                dest = root / "installed"
                try:
                    dest.symlink_to(previous, target_is_directory=True)
                except (OSError, NotImplementedError) as exc:
                    self.skipTest(f"symlink creation unavailable: {exc}")
                before = installed_bytes(previous)

                result = mod.install_one(source, dest, mode, previous_source=previous)

                self.assertEqual(result, "copied" if mode == "copy" else "linked")
                self.assertTrue(mod.check_one(source, dest)[0])
                self.assertEqual(installed_bytes(previous), before)
                mod._remove_owned_destination(source, dest)
                self.assertFalse(dest.exists())

    def test_previous_source_link_through_foreign_alias_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            previous = make_source(root / "old")
            source = make_source(root / "new", "0.4.1")
            alias = root / "alias"
            dest = root / "installed"
            try:
                alias.symlink_to(previous, target_is_directory=True)
                dest.symlink_to(alias, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            with self.assertRaises(ValueError):
                mod.install_one(source, dest, "copy", previous_source=previous)

            self.assertTrue(dest.is_symlink())
            self.assertEqual(dest.readlink(), alias)

    def test_relative_link_to_exact_previous_source_can_migrate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            previous = make_source(root / "old")
            source = make_source(root / "new", "0.4.1")
            dest = root / "installed"
            try:
                dest.symlink_to(Path("old/source"), target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            self.assertEqual(mod.install_one(source, dest, "copy", previous_source=previous), "copied")
            self.assertTrue(mod.check_one(source, dest)[0])

    def test_reparse_source_ancestors_are_refused_before_resolution(self):
        for source_to_link in ("current", "previous", "destination-parent"):
            with self.subTest(source_to_link=source_to_link), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                previous = make_source(root / "old")
                source = make_source(root / "new", "0.4.1")
                dest = root / "skills" / "installed"
                mod.install_one(previous, dest, "copy")
                before = installed_bytes(dest)
                linked = {
                    "current": source.parent,
                    "previous": previous.parent,
                    "destination-parent": dest.parent,
                }[source_to_link]
                original = mod._is_reparse

                with mock.patch.object(mod, "_is_reparse", side_effect=lambda path: path == linked or original(path)):
                    with self.assertRaises(ValueError):
                        mod.install_one(source, dest, "copy", previous_source=previous)

                self.assertEqual(installed_bytes(dest), before)

    def test_staged_replace_rechecks_previous_copy_before_rename(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            previous = make_source(root / "old")
            source = make_source(root / "new", "0.4.1")
            dest = root / "installed"
            mod.install_one(previous, dest, "copy")
            before = installed_bytes(dest)
            original = mod._copy_skill

            def add_local_extension(skill_source, staged):
                original(skill_source, staged)
                (dest / "scripts" / "local.py").write_text("LOCAL = True\n", encoding="utf-8")

            with mock.patch.object(mod, "_copy_skill", side_effect=add_local_extension):
                with self.assertRaises(ValueError):
                    mod.install_one(source, dest, "copy", previous_source=previous)

            self.assertEqual((dest / "VERSION").read_bytes(), before["VERSION"])
            self.assertEqual((dest / mod.INSTALL_MARKER).read_bytes(), before[mod.INSTALL_MARKER])
            self.assertTrue((dest / "scripts" / "local.py").exists())
            self.assertEqual(list(root.glob(".installed.*")), [])

    def test_batch_preflight_preserves_earlier_skill_when_later_skill_is_unowned(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            previous = make_source(root / "old")
            source = make_source(root / "new", "0.4.1")
            first = root / "skills" / "first"
            second = root / "skills" / "second"
            mod.install_one(previous, first, "copy")
            second.mkdir()
            (second / "USER.txt").write_text("keep\n", encoding="utf-8")
            before = installed_bytes(first)

            with self.assertRaises(ValueError):
                mod._install_many([(source, first, previous), (source, second, previous)], "copy")

            self.assertEqual(installed_bytes(first), before)
            self.assertEqual((second / "USER.txt").read_text(encoding="utf-8"), "keep\n")
            self.assertEqual(list(first.parent.glob(".*")), [])

    def test_batch_later_replacement_failure_restores_prior_copies_and_absent_entries(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            previous = make_source(root / "old")
            source = make_source(root / "new", "0.4.1")
            first = root / "skills" / "first"
            fresh = root / "skills" / "fresh"
            last = root / "skills" / "last"
            mod.install_one(previous, first, "copy")
            mod.install_one(previous, last, "copy")
            before_first, before_last = installed_bytes(first), installed_bytes(last)
            original = mod._replace_with_staged

            def fail_last(skill_source, dest, staged, previous_source=None, keep_backup=False):
                if dest == last:
                    raise OSError("last replacement failed")
                return original(skill_source, dest, staged, previous_source, keep_backup=keep_backup)

            installs = [(source, dest, previous) for dest in (first, fresh, last)]
            with mock.patch.object(mod, "_replace_with_staged", side_effect=fail_last):
                with self.assertRaisesRegex(OSError, "last replacement failed"):
                    mod._install_many(installs, "copy")

            self.assertEqual(installed_bytes(first), before_first)
            self.assertEqual(installed_bytes(last), before_last)
            self.assertFalse(fresh.exists())
            self.assertEqual(list(first.parent.glob(".*")), [])

    def test_batch_later_replacement_failure_restores_prior_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            previous = make_source(root / "old")
            source = make_source(root / "new", "0.4.1")
            first = root / "skills" / "first"
            last = root / "skills" / "last"
            first.parent.mkdir()
            try:
                first.symlink_to(previous, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            mod.install_one(previous, last, "copy")
            original = mod._replace_with_staged

            def fail_last(skill_source, dest, staged, previous_source=None, keep_backup=False):
                if dest == last:
                    raise OSError("last replacement failed")
                return original(skill_source, dest, staged, previous_source, keep_backup=keep_backup)

            with mock.patch.object(mod, "_replace_with_staged", side_effect=fail_last):
                with self.assertRaisesRegex(OSError, "last replacement failed"):
                    mod._install_many([(source, dest, previous) for dest in (first, last)], "copy")

            self.assertTrue(first.is_symlink())
            self.assertEqual(first.resolve(), previous.resolve())
            self.assertTrue(mod.check_one(previous, last)[0])
            self.assertEqual(list(first.parent.glob(".*")), [])

    def test_batch_recovers_destinations_split_between_current_and_previous_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            previous = make_source(root / "old")
            source = make_source(root / "new", "0.4.1")
            first = root / "skills" / "first"
            second = root / "skills" / "second"
            mod.install_one(source, first, "copy")
            mod.install_one(previous, second, "copy")

            self.assertEqual(
                mod._install_many([(source, dest, previous) for dest in (first, second)], "copy"),
                ["copied", "copied"],
            )

            self.assertTrue(mod.check_one(source, first)[0])
            self.assertTrue(mod.check_one(source, second)[0])
            self.assertEqual(list(first.parent.glob(".*")), [])

    def test_cli_maps_all_previous_knowledge_sources_and_supports_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            previous = make_source(root / "old", "0.4.0")
            source = make_source(root / "new", "0.4.1")
            make_knowledge_sources(previous, "old knowledge")
            make_knowledge_sources(source, "new knowledge")
            project = root / "project"

            def run_cli(payload, prior=None):
                args = ["install_skill.py", "--harness", "all", "--scope", "project", "--project", str(project),
                        "--knowledge", "--mode", "copy", "--source", str(payload)]
                if prior is not None:
                    args.extend(["--previous-source", str(prior)])
                with mock.patch.object(mod.sys, "argv", args), mock.patch("sys.stdout", new_callable=io.StringIO):
                    return mod.main()

            self.assertEqual(run_cli(previous), 0)
            self.assertEqual(run_cli(source, previous), 0)
            self.assertEqual(run_cli(source, previous), 0)
            for harness_dir in (".agents", ".claude"):
                skills = project / harness_dir / "skills"
                self.assertTrue(mod.check_one(source, skills / mod.SKILL_NAME)[0])
                for name in mod.KNOWLEDGE_NAMES:
                    dest = skills / name
                    self.assertTrue(mod.check_one(source / mod.KNOWLEDGE_SOURCE / name, dest)[0])
                    marker = json.loads((dest / mod.INSTALL_MARKER).read_text(encoding="utf-8"))
                    self.assertEqual(marker["version"], "0.4.1")

            self.assertEqual(run_cli(previous, source), 0)
            self.assertEqual(run_cli(previous, source), 0)
            for harness_dir in (".agents", ".claude"):
                skills = project / harness_dir / "skills"
                self.assertTrue(mod.check_one(previous, skills / mod.SKILL_NAME)[0])
                for name in mod.KNOWLEDGE_NAMES:
                    dest = skills / name
                    self.assertTrue(mod.check_one(previous / mod.KNOWLEDGE_SOURCE / name, dest)[0])
                    marker = json.loads((dest / mod.INSTALL_MARKER).read_text(encoding="utf-8"))
                    self.assertEqual(marker["version"], "0.4.0")
                    mod._remove_owned_destination(previous / mod.KNOWLEDGE_SOURCE / name, dest)
                mod._remove_owned_destination(previous, skills / mod.SKILL_NAME)

    def test_runtime_knowledge_copy_checks_digest_and_owned_removal(self):
        source = ROOT / "docs/runtime/skills/acs-project-context"
        with tempfile.TemporaryDirectory() as td:
            destination = Path(td) / "acs-project-context"
            self.assertEqual(mod.install_one(source, destination, "copy"), "copied")
            self.assertEqual(mod.check_one(source, destination), (True, "copy digest=match"))
            marker = json.loads((destination / mod.INSTALL_MARKER).read_text(encoding="utf-8"))
            self.assertEqual(marker["skill"], "acs-project-context")
            self.assertTrue((destination / "references/model.md").is_file())
            (destination / "references/model.md").write_text("changed", encoding="utf-8")
            self.assertFalse(mod.check_one(source, destination)[0])
            with self.assertRaises(ValueError):
                mod._remove_owned_destination(source, destination)

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

    def test_nested_document_payload_copy_remains_owned_on_repeat_and_uninstall(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_source(root)
            documents = {
                "docs/GETTING-STARTED.md": "Setup instructions\n",
                "docs/runtime/P2-PRIVATE-TUNNEL-PROFILE.md": "Private Tunnel instructions\n",
                "docs/runtime/PROJECT-ADOPTION.md": "Project adoption instructions\n",
            }
            for name, content in documents.items():
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            (source / "docs/private.md").write_text("Project-owned document\n", encoding="utf-8")
            dest = root / "installed"

            self.assertEqual(mod.install_one(source, dest, "copy"), "copied")
            for name, content in documents.items():
                self.assertEqual((dest / name).read_text(encoding="utf-8"), content)
            self.assertFalse((dest / "docs/private.md").exists())
            self.assertEqual(mod._unknown_entries(source, dest), set())
            self.assertEqual(mod.install_one(source, dest, "copy"), "copied")
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

    def test_linked_parent_of_nested_document_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_source(root)
            external = root / "external-documents"
            external.mkdir()
            protected = external / "P2-PRIVATE-TUNNEL-PROFILE.md"
            protected.write_text("Private external content\n", encoding="utf-8")
            (source / "docs").mkdir()
            try:
                (source / "docs/runtime").symlink_to(external, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            dest = root / "installed"

            with self.assertRaises(ValueError):
                mod.install_one(source, dest, "copy")

            self.assertFalse(dest.exists())
            self.assertEqual(protected.read_text(encoding="utf-8"), "Private external content\n")

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
