"""Read-only Source discovery on exact local and selected remote paths."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("source_discovery", ROOT / "scripts/acs_source_discovery.py")
discovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(discovery)
MACHINE = {"schema_version": "acs-install-machine/1", "machine_id": "a" * 64,
           "hostname": "source-host", "platform": "linux", "account": "owner",
           "user_home": "/home/owner", "python": "3.12.3", "transport": "local", "locator": None}


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def repository(path):
    path.mkdir()
    git(path, "init", "--quiet")
    git(path, "config", "user.email", "source-test@example.test")
    git(path, "config", "user.name", "Source Test")
    (path / "source.txt").write_text("verified source\n", encoding="utf-8")
    management = path / "management"
    (management / ".agents").mkdir(parents=True)
    (management / ".agents/manifest.json").write_text(json.dumps({
        "kind": "project-collaboration-root", "root_id": "root-existing",
        "project_id": "project-existing"}), encoding="utf-8")
    git(path, "add", ".")
    git(path, "commit", "--quiet", "-m", "test source")
    return management


class SourceDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def observe(self, path, **kwargs):
        return discovery.discover_source(str(path), **kwargs)

    def test_existing_project_reads_source_and_identity_without_file_changes(self):
        source = self.root / "source"
        management = repository(source)
        before = {str(path.relative_to(source)): path.read_bytes()
                  for path in source.rglob("*") if path.is_file()}
        observed = self.observe(management, expected_project_id="project-existing",
                                expected_root_id="root-existing")
        self.assertEqual(observed["state"], "observed_candidate")
        self.assertEqual(Path(observed["repository_root"]), source)
        self.assertEqual(Path(observed["management_root"]), management)
        self.assertEqual(observed["commit"], git(source, "rev-parse", "HEAD"))
        self.assertEqual(observed["tree"], git(source, "rev-parse", "HEAD^{tree}"))
        self.assertEqual(observed["working_tree"], "tracked_clean_untracked_unobserved")
        self.assertEqual(observed["working_tree_scope"], "tracked_only")
        self.assertFalse(observed["binding_created"])
        after = {str(path.relative_to(source)): path.read_bytes()
                 for path in source.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_missing_path_reports_location_and_does_not_create_it(self):
        absent = self.root / "absent" / "project"
        observed = self.observe(absent)
        self.assertEqual(observed["state"], "need_location")
        self.assertEqual(observed["reason"], "source_directory_missing")
        self.assertFalse(absent.parent.exists())

    def test_non_git_directory_remains_unchanged(self):
        existing = self.root / "assets"
        existing.mkdir()
        (existing / "notes.txt").write_text("existing knowledge", encoding="utf-8")
        observed = self.observe(existing)
        self.assertEqual(observed["state"], "need_location")
        self.assertEqual(list(existing.iterdir()), [existing / "notes.txt"])

    def test_wrong_expected_commit_conflicts_with_real_checkout(self):
        source = self.root / "source"
        repository(source)
        observed = self.observe(source, expected_commit="b" * 40)
        self.assertEqual(observed["state"], "conflict")
        self.assertEqual(observed["conflicts"], ["commit"])

    def test_wrong_project_identity_does_not_adopt_or_replace_it(self):
        management = repository(self.root / "source")
        observed = self.observe(management, expected_project_id="another-project")
        self.assertEqual(observed["state"], "conflict")
        self.assertEqual(observed["project_id"], "project-existing")

    def test_dirty_and_optional_untracked_observations(self):
        source = self.root / "source"
        repository(source)
        (source / "source.txt").write_text("local edits", encoding="utf-8")
        (source / "untracked.txt").write_text("local asset", encoding="utf-8")
        observed = self.observe(source)
        self.assertEqual(observed["working_tree"], "dirty")
        self.assertFalse(observed["untracked_observed"])
        self.assertFalse(any("untracked.txt" in value for value in observed["status"]))
        observed = self.observe(source, include_untracked=True)
        self.assertTrue(observed["untracked_observed"])
        self.assertTrue(any("untracked.txt" in value for value in observed["status"]))

    def test_untracked_only_source_does_not_claim_complete_clean_state(self):
        source = self.root / "source"
        repository(source)
        (source / "pending.txt").write_text("uncommitted file", encoding="utf-8")
        observed = self.observe(source)
        self.assertEqual(observed["working_tree"], "tracked_clean_untracked_unobserved")
        self.assertFalse(observed["untracked_observed"])
        complete = self.observe(source, include_untracked=True)
        self.assertEqual(complete["working_tree"], "dirty")
        self.assertEqual(complete["working_tree_scope"], "tracked_and_untracked")

    def test_pinned_tree_and_head_movement_produce_unavailable_not_incoherent_candidate(self):
        source = self.root / "source"
        repository(source)
        commit = git(source, "rev-parse", "HEAD")
        environment = {"__name__": "source_probe_test"}
        definition = discovery.SOURCE_PROBE.split("request = json.load(sys.stdin)")[0]
        exec(definition, environment)  # noqa: S102 - checked-in static probe; no external code.
        environment["request"] = {"path": str(source), "remote": False,
                                  "include_untracked": True, "management_path": None}
        real_git = environment["git"]
        observed_calls = []
        heads = 0

        def moving_git(path, *arguments, **kwargs):
            nonlocal heads
            observed_calls.append(arguments)
            if arguments == ("rev-parse", "--verify", "HEAD"):
                heads += 1
                if heads == 2:
                    return "b" * 40
            return real_git(path, *arguments, **kwargs)

        environment["git"] = moving_git
        with self.assertRaisesRegex(ValueError, "source_head_changed_during_probe"):
            environment["probe"]()
        self.assertIn(("rev-parse", commit + "^{tree}"), observed_calls)
        self.assertNotIn(("rev-parse", "HEAD^{tree}"), observed_calls)
        heads = 0
        entry = "request = json.load(sys.stdin)" + discovery.SOURCE_PROBE.split(
            "request = json.load(sys.stdin)", 1)[1]
        output = io.StringIO()
        with (mock.patch.object(sys, "stdin", io.StringIO(json.dumps(environment["request"]))),
              mock.patch.object(sys, "stdout", output)):
            exec(entry, environment)  # noqa: S102 - checked-in static probe; no external code.
        observed = json.loads(output.getvalue())
        self.assertEqual(observed["state"], "unavailable")
        self.assertEqual(observed["reason"], "source_head_changed_during_probe")

    def test_nested_management_path_is_bounded_to_checkout(self):
        source = self.root / "source"
        management = repository(source)
        observed = self.observe(source, management_path=str(management))
        self.assertEqual(Path(observed["management_root"]), management)
        outside = self.observe(source, management_path=str(self.root))
        self.assertEqual(outside["state"], "unavailable")
        self.assertEqual(outside["reason"], "management_path_outside_source_checkout")

    def test_credential_remotes_are_redacted_and_repository_identity_is_checked(self):
        source = self.root / "source"
        repository(source)
        git(source, "remote", "add", "origin",
            "https://user:SECRET@example.test/owner/project.git?token=PRIVATE#hidden")
        observed = self.observe(source, expected_repository="git@example.test:owner/project.git")
        self.assertEqual(observed["state"], "observed_candidate")
        self.assertEqual(observed["remotes"], [{
            "name": "origin", "locator": "https://example.test/owner/project.git"}])
        output = json.dumps(observed)
        self.assertNotIn("SECRET", output)
        self.assertNotIn("PRIVATE", output)
        conflict = self.observe(source, expected_repository="https://example.test/another.git")
        self.assertEqual(conflict["state"], "conflict")
        self.assertIn("repository_identity", conflict["conflicts"])

    def test_remote_namespace_and_metacharacters_are_stdin_data(self):
        remote_path = "/srv/code with spaces/quote';$(echo sensitive)"
        recorded = {}

        def invoke(command, **kwargs):
            recorded.update(command=command, request=json.loads(kwargs["input"]))
            return subprocess.CompletedProcess(command, 0, json.dumps({
                "state": "need_location", "requested_path": remote_path,
                "observed_path": remote_path, "reason": "source_directory_missing",
                "source_machine_observation": MACHINE}), "")

        with (mock.patch.object(discovery, "observe_machine", return_value=MACHINE) as observed,
              mock.patch.object(discovery.subprocess, "run", side_effect=invoke)):
            result = discovery.discover_source(remote_path, ssh_target="selected-host")
        observed.assert_called_once_with("ssh", "selected-host")
        self.assertEqual(recorded["request"]["path"], remote_path)
        self.assertTrue(recorded["request"]["remote"])
        self.assertNotIn(remote_path, " ".join(recorded["command"]))
        self.assertEqual(result["observed_path"], remote_path)
        self.assertEqual(result["source_machine"]["hostname"], MACHINE["hostname"])

    def test_actual_source_process_machine_and_account_drift_are_conflicts(self):
        source = self.root / "source"
        repository(source)
        actual_machine = discovery.observe_machine()
        for field, changed in (("machine_id", "b" * 64), ("account", "different-owner"),
                               ("user_home", "/home/different-owner")):
            initial_machine = {**actual_machine, field: changed}
            with (self.subTest(field=field),
                  mock.patch.object(discovery, "observe_machine", return_value=initial_machine),
                  mock.patch.object(discovery, "transport_command", side_effect=
                                    lambda kind, target, code: [sys.executable, "-c", code])):
                result = discovery.discover_source(str(source), ssh_target="selected-source")
            self.assertEqual(result["state"], "conflict")
            self.assertEqual(result["reason"], "source_host_or_account_changed_during_probe")
            self.assertEqual(result["source_machine_binding"], discovery.machine_binding(actual_machine))
            self.assertEqual(result["source_machine_binding_before_probe"][field], changed)
            self.assertEqual(Path(result["repository_root"]), source)
            self.assertFalse(result["binding_created"])

    def test_remote_relative_path_requires_location_in_target_namespace(self):
        result = subprocess.run([sys.executable, "-c", discovery.SOURCE_PROBE],
                                input=json.dumps({"path": "source", "remote": True,
                                                  "include_untracked": False}),
                                text=True, check=True, capture_output=True)
        observed = json.loads(result.stdout)
        self.assertEqual(observed["state"], "unavailable")
        self.assertEqual(observed["reason"], "remote_source_path_requires_absolute_path")

    def test_source_machine_is_independent_of_runtime_and_mismatch_stops_probe(self):
        with (mock.patch.object(discovery, "observe_machine", return_value=MACHINE),
              mock.patch.object(discovery.subprocess, "run", side_effect=AssertionError("probe"))):
            result = discovery.discover_source("/srv/source", ssh_target="source-host",
                                               expected_machine_id="b" * 64)
        self.assertEqual(result["state"], "conflict")
        self.assertEqual(result["source_target"], "source-host")
        self.assertEqual(result["source_machine_binding"]["machine_id"], "a" * 64)
        self.assertNotIn("runtime_host", result)

    def test_selected_host_alias_rejects_shell_injection(self):
        for alias in ["-oProxyCommand=bad", "host;echo bad", "host$(bad)", "host\nother"]:
            with self.subTest(alias=alias), mock.patch.object(discovery, "observe_machine",
                                                             return_value=MACHINE):
                result = discovery.discover_source("/srv/source", ssh_target=alias)
                self.assertEqual(result["state"], "unavailable")

    def test_symlink_source_is_refused(self):
        source = self.root / "source"
        repository(source)
        alias = self.root / "alias"
        try:
            alias.symlink_to(source, target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation permission unavailable")
        observed = self.observe(alias)
        self.assertEqual(observed["state"], "unavailable")
        self.assertEqual(observed["reason"], "source_path_contains_link_or_reparse_alias")

    def test_traversal_path_does_not_alias_checkout(self):
        source = self.root / "source"
        repository(source)
        observed = self.observe(str(source / "management" / ".."))
        self.assertEqual(observed["state"], "unavailable")
        self.assertEqual(observed["reason"], "source_path_contains_traversal")

    def test_two_matching_clones_require_selection_unless_session_is_exact(self):
        first = {"state": "observed_candidate", "repository_root": "/work/first",
                 "source_machine_binding": {"machine_id": "a", "account": "owner", "user_home": "/home/owner"}}
        second = {**first, "repository_root": "/work/second"}
        self.assertEqual(discovery.analyze_candidates([first, second])["state"], "needs_selection")
        chosen = discovery.analyze_candidates([first, second], session_source=second)
        self.assertEqual(chosen["candidate"], second)
        self.assertEqual(chosen["selection_basis"], "current_session")
        self.assertEqual(discovery.analyze_candidates([
            first, {"state": "conflict"}])["state"], "needs_selection")

    def test_inherited_git_directory_does_not_redirect_source_probe(self):
        source = self.root / "source"
        repository(source)
        with mock.patch.dict(os.environ, {"GIT_DIR": str(self.root / "unrelated.git")}):
            observed = self.observe(source)
        self.assertEqual(observed["state"], "observed_candidate")
        self.assertEqual(Path(observed["repository_root"]), source)


if __name__ == "__main__":
    unittest.main()
