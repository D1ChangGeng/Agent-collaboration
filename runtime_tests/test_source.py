from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from runtime.artifacts import LocalArtifactStore
from runtime.models import ArtifactRef
from runtime.source import (
    SourceArtifactError,
    SourceAuthorizationError,
    SourceBackendUnavailable,
    SourceChangedDuringSnapshot,
    SourceCommitMismatch,
    SourceDirtyError,
    SourceOversizeError,
    SourcePathError,
    SourceReadbackError,
    SourceRepositoryError,
    SourceSecretError,
    SourceService,
)
from runtime.source_models import SourceRequest

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="the first Source/Artifact backend is explicitly Linux dirfd-only",
)


def git(repo: Path, *args: str) -> bytes:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
        "PAGER": "cat",
        "LC_ALL": "C",
        "LANG": "C",
    }
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=environment,
        check=True,
        capture_output=True,
    )
    return completed.stdout


def make_repo(root: Path) -> Path:
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "source-test@example.invalid")
    git(root, "config", "user.name", "Source Test")
    return root


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def request_for(
    repo: Path,
    *,
    expected_commit: str | None = None,
    expected_tree: str | None = None,
    allow_dirty: bool = False,
    include_untracked: bool = True,
    max_bytes: int | None = None,
) -> SourceRequest:
    return SourceRequest(
        root=repo,
        tenant_id="tenant-source",
        scope_id="scope-source",
        root_id="root-source",
        route_id="route-source",
        expected_commit=expected_commit,
        expected_tree=expected_tree,
        allow_dirty=allow_dirty,
        include_untracked=include_untracked,
        max_bytes=max_bytes,
    )


def service_for(
    tmp_path: Path,
    repo: Path,
    *,
    max_bytes: int = 16 * 1024 * 1024,
    max_files: int = 100_000,
    secret_patterns: tuple[str, ...] | None = None,
) -> tuple[SourceService, LocalArtifactStore]:
    store = LocalArtifactStore(
        tmp_path / "cas",
        "scope-source",
    )
    options = {
        "max_bytes": max_bytes,
        "max_files": max_files,
    }
    if secret_patterns is not None:
        options["secret_patterns"] = secret_patterns
    service = SourceService(store, authorized_roots=[tmp_path], **options)
    return service, store


def allow(request: SourceRequest) -> bool:
    return (
        request.tenant_id == "tenant-source"
        and request.scope_id == "scope-source"
        and request.root_id == "root-source"
        and request.route_id == "route-source"
    )


def test_clean_snapshot_captures_commit_tree_real_bytes_and_readback(
    tmp_path: Path,
):
    repo = make_repo(tmp_path / "repo")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    (repo / "binary.dat").write_bytes(b"\x00\xff\x01\x00")
    commit_all(repo, "initial")

    expected_commit = git(repo, "rev-parse", "HEAD").decode().strip()
    expected_tree = git(repo, "rev-parse", "HEAD^{tree}").decode().strip()
    service, store = service_for(tmp_path, repo)

    observed_requests: list[SourceRequest] = []
    snapshot = service.admit(
        request_for(
            repo,
            expected_commit=expected_commit,
            expected_tree=expected_tree,
        ),
        lambda request: observed_requests.append(request) or allow(request),
    )

    assert snapshot.source_commit == expected_commit
    assert snapshot.source_tree == expected_tree
    assert snapshot.dirty is False
    assert snapshot.source_class == "directly_verified"
    assert snapshot.snapshot_sha256
    assert snapshot.manifest_ref["sha256"] == snapshot.snapshot_sha256
    assert {item.path for item in snapshot.files} == {
        "README.md",
        "binary.dat",
    }
    assert all(item.artifact_ref["immutable"] is True for item in snapshot.files)
    assert observed_requests[0].scope_id == "scope-source"
    assert observed_requests[0].root_id == "root-source"
    assert store.read(
        __import__("runtime.models", fromlist=["ArtifactRef"]).ArtifactRef.model_validate(
            snapshot.files[0].artifact_ref
        )
    )
    assert service.readback(snapshot, allow) == snapshot


def test_dirty_and_untracked_require_explicit_policy_and_are_snapshotted(
    tmp_path: Path,
):
    repo = make_repo(tmp_path / "repo")
    (repo / "tracked.txt").write_text("one\n", encoding="utf-8")
    commit_all(repo, "initial")
    (repo / "tracked.txt").write_text("two\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("new\n", encoding="utf-8")

    service, _store = service_for(tmp_path, repo)

    with pytest.raises(SourceDirtyError):
        service.admit(request_for(repo), allow)

    snapshot = service.admit(
        request_for(repo, allow_dirty=True),
        allow,
    )
    assert snapshot.dirty is True
    assert "untracked.txt" in {item.path for item in snapshot.files}
    assert "tracked.txt" in {item.path for item in snapshot.files}
    assert service.readback(snapshot, allow) == snapshot


def test_untracked_files_can_be_rejected_without_being_read(
    tmp_path: Path,
):
    repo = make_repo(tmp_path / "repo")
    (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    commit_all(repo, "initial")
    (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")

    service, _store = service_for(tmp_path, repo)

    with pytest.raises(SourceDirtyError):
        service.admit(
            request_for(
                repo,
                allow_dirty=True,
                include_untracked=False,
            ),
            allow,
        )


def test_secret_paths_are_excluded_from_cas_and_snapshot_contents(
    tmp_path: Path,
):
    repo = make_repo(tmp_path / "repo")
    (repo / ".env").write_text("TOKEN=do-not-copy\n", encoding="utf-8")
    (repo / "public.txt").write_text("public\n", encoding="utf-8")
    commit_all(repo, "secret-and-public")

    service, _store = service_for(
        tmp_path,
        repo,
        secret_patterns=("*.env",),
    )
    snapshot = service.admit(request_for(repo), allow)

    assert ".env" in snapshot.excluded_paths
    assert {item.path for item in snapshot.files} == {"public.txt"}
    assert all(item.path != ".env" for item in snapshot.files)


def test_changed_secret_path_fails_closed_without_diff_leakage(
    tmp_path: Path,
):
    repo = make_repo(tmp_path / "repo")
    (repo / ".env").write_text("TOKEN=one\n", encoding="utf-8")
    (repo / "public.txt").write_text("public\n", encoding="utf-8")
    commit_all(repo, "secret")
    (repo / ".env").write_text("TOKEN=two\n", encoding="utf-8")

    service, _store = service_for(
        tmp_path,
        repo,
        secret_patterns=("*.env",),
    )

    with pytest.raises(SourceSecretError):
        service.admit(
            request_for(repo, allow_dirty=True),
            allow,
        )


def test_commit_tree_mismatch_is_rejected(
    tmp_path: Path,
):
    repo = make_repo(tmp_path / "repo")
    (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    commit_all(repo, "initial")
    service, _store = service_for(tmp_path, repo)

    with pytest.raises(SourceCommitMismatch):
        service.admit(
            request_for(
                repo,
                expected_commit="0" * 40,
            ),
            allow,
        )

    with pytest.raises(SourceCommitMismatch):
        service.admit(
            request_for(
                repo,
                expected_tree="0" * 40,
            ),
            allow,
        )


def test_wrong_repository_and_path_escape_are_rejected(
    tmp_path: Path,
):
    authorized_repo = make_repo(tmp_path / "repo")
    (authorized_repo / "file.txt").write_text("ok\n", encoding="utf-8")
    commit_all(authorized_repo, "initial")
    outside = make_repo(tmp_path / "outside")
    (outside / "outside.txt").write_text("outside\n", encoding="utf-8")
    commit_all(outside, "outside")

    service, _store = service_for(tmp_path / "service", authorized_repo)

    with pytest.raises(SourceAuthorizationError):
        service.admit(request_for(outside), allow)

    with pytest.raises(SourceAuthorizationError):
        service.admit(
            SourceRequest(
                root=tmp_path / "not-authorized",
                tenant_id="tenant-source",
                scope_id="scope-source",
                root_id="root-source",
                route_id="route-source",
            ),
            allow,
        )


def test_nested_repository_is_rejected(
    tmp_path: Path,
):
    repo = make_repo(tmp_path / "repo")
    (repo / "root.txt").write_text("root\n", encoding="utf-8")
    commit_all(repo, "root")
    nested = make_repo(repo / "nested")
    (nested / "nested.txt").write_text("nested\n", encoding="utf-8")
    commit_all(nested, "nested")

    service, _store = service_for(tmp_path, repo)

    with pytest.raises(SourceRepositoryError):
        service.admit(request_for(repo), allow)


def test_ignored_directory_is_not_inspected_or_admitted(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    (repo / "source.txt").write_text("source\n", encoding="utf-8")
    commit_all(repo, "source")
    ignored = repo / "ignored"
    ignored.mkdir()
    (ignored / "outside-link").symlink_to(tmp_path / "outside")
    service, _store = service_for(tmp_path, repo)

    snapshot = service.admit(request_for(repo), allow)

    assert {item.path for item in snapshot.files} == {".gitignore", "source.txt"}


def test_linked_worktree_metadata_must_stay_in_authorized_control_root(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    (repo / "source.txt").write_text("source\n", encoding="utf-8")
    commit_all(repo, "source")
    worktree = tmp_path / "linked"
    git(repo, "worktree", "add", "-q", "--detach", str(worktree), "HEAD")
    service, _store = service_for(tmp_path, worktree)

    snapshot = service.admit(request_for(worktree), allow)

    assert snapshot.source_commit == git(repo, "rev-parse", "HEAD").decode().strip()
    assert {item.path for item in snapshot.files} == {"source.txt"}


def test_git_metadata_outside_authorized_root_is_rejected(tmp_path: Path):
    outer = make_repo(tmp_path / "outer")
    (outer / "source.txt").write_text("source\n", encoding="utf-8")
    commit_all(outer, "source")
    worktree = tmp_path / "linked"
    git(outer, "worktree", "add", "-q", "--detach", str(worktree), "HEAD")
    isolated = tmp_path / "authorized"
    isolated.mkdir()
    moved = isolated / "linked"
    worktree.rename(moved)
    store = LocalArtifactStore(tmp_path / "cas-metadata", "scope-source")
    service = SourceService(store, authorized_roots=[isolated])

    with pytest.raises(SourceAuthorizationError, match="control metadata"):
        service.admit(request_for(moved), allow)


def test_repository_config_cannot_include_external_files(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    (repo / "source.txt").write_text("source\n", encoding="utf-8")
    commit_all(repo, "source")
    outside = tmp_path / "outside.config"
    outside.write_text("[credential]\nhelper = arbitrary\n", encoding="utf-8")
    with (repo / ".git" / "config").open("a", encoding="utf-8") as stream:
        stream.write(f"\n[include]\npath = {outside}\n")
    service, _store = service_for(tmp_path, repo)

    with pytest.raises(SourceRepositoryError, match="unsafe include/filter/diff"):
        service.admit(request_for(repo), allow)


def test_repository_filter_driver_is_rejected_without_execution(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    sentinel = tmp_path / "filter-executed"
    (repo / ".gitattributes").write_text("*.txt filter=external\n", encoding="utf-8")
    (repo / "source.txt").write_text("source\n", encoding="utf-8")
    commit_all(repo, "source")
    with (repo / ".git" / "config").open("a", encoding="utf-8") as stream:
        stream.write(
            "\n[filter \"external\"]\n"
            f"clean = /bin/sh -c 'touch {sentinel}'\n"
            f"smudge = /bin/sh -c 'touch {sentinel}'\n"
            "required = true\n"
        )
    service, _store = service_for(tmp_path, repo)

    with pytest.raises(SourceRepositoryError, match="unsafe include/filter/diff"):
        service.admit(request_for(repo), allow)
    assert not sentinel.exists()


def test_repository_filter_added_after_metadata_check_cannot_execute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path / "repo")
    sentinel = tmp_path / "raced-filter-executed"
    (repo / ".gitattributes").write_text("*.txt filter=raced\n", encoding="utf-8")
    (repo / "source.txt").write_text("source\n", encoding="utf-8")
    commit_all(repo, "source")
    (repo / "source.txt").write_text("changed\n", encoding="utf-8")
    service, _store = service_for(tmp_path, repo)
    original_metadata = service._repository_metadata
    injected = False

    def inject_filter_after_check(root, authorized_roots):
        nonlocal injected
        checked = original_metadata(root, authorized_roots)
        if not injected:
            injected = True
            git(
                repo,
                "config",
                "filter.raced.clean",
                f"/bin/sh -c 'touch {shlex.quote(str(sentinel))}'; cat",
            )
        return checked

    monkeypatch.setattr(service, "_repository_metadata", inject_filter_after_check)

    with pytest.raises(SourceRepositoryError):
        service.admit(request_for(repo, allow_dirty=True), allow)
    assert not sentinel.exists()


def test_git_object_alternates_are_rejected(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    (repo / "source.txt").write_text("authorized\n", encoding="utf-8")
    commit_all(repo, "source")
    foreign = make_repo(tmp_path / "foreign")
    (foreign / "source.txt").write_text("outside\n", encoding="utf-8")
    commit_all(foreign, "outside")
    alternates = repo / ".git" / "objects" / "info" / "alternates"
    alternates.write_text(str(foreign / ".git" / "objects") + "\n", encoding="utf-8")
    store = LocalArtifactStore(tmp_path / "cas-alternates", "scope-source")
    service = SourceService(store, authorized_roots=[repo])

    with pytest.raises(SourceRepositoryError, match="alternates"):
        service.admit(request_for(repo), allow)


def test_tracked_symlink_is_rejected(
    tmp_path: Path,
):
    repo = make_repo(tmp_path / "repo")
    target = tmp_path / "target.txt"
    target.write_text("outside\n", encoding="utf-8")
    (repo / "link.txt").symlink_to(target)
    git(repo, "add", "link.txt")
    git(repo, "commit", "-q", "-m", "symlink")

    service, _store = service_for(tmp_path, repo)

    with pytest.raises(SourcePathError):
        service.admit(request_for(repo), allow)


def test_binary_and_rename_are_read_from_the_actual_worktree(
    tmp_path: Path,
):
    repo = make_repo(tmp_path / "repo")
    (repo / "old.bin").write_bytes(b"\x00\x01\xff\x00")
    commit_all(repo, "binary")
    (repo / "old.bin").rename(repo / "new.bin")
    commit_all(repo, "rename")

    service, _store = service_for(tmp_path, repo)
    snapshot = service.admit(request_for(repo), allow)

    assert {item.path for item in snapshot.files} == {"new.bin"}
    new_file = next(item for item in snapshot.files if item.path == "new.bin")
    assert new_file.sha256 == hashlib.sha256(
        b"\x00\x01\xff\x00"
    ).hexdigest()
    assert service.readback(snapshot, allow) == snapshot


def test_worktree_executable_mode_is_captured_and_present_in_diff(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    script = repo / "run.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o644)
    commit_all(repo, "script")
    script.chmod(0o755)
    service, store = service_for(tmp_path, repo)

    snapshot = service.admit(request_for(repo, allow_dirty=True), allow)
    source_file = next(item for item in snapshot.files if item.path == "run.sh")
    diff = store.read(ArtifactRef.model_validate(snapshot.diff_ref))

    assert source_file.mode == "100755"
    assert b"old mode 100644" in diff
    assert b"new mode 100755" in diff


def test_readback_rejects_mode_change_even_when_status_code_is_unchanged(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    script = repo / "run.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o644)
    commit_all(repo, "script")
    script.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    service, _store = service_for(tmp_path, repo)
    snapshot = service.admit(request_for(repo, allow_dirty=True), allow)
    script.chmod(0o755)

    with pytest.raises(SourceChangedDuringSnapshot, match="mode changed"):
        service.readback(snapshot, allow)


def test_oversize_source_file_is_rejected_before_cas_admission(
    tmp_path: Path,
):
    repo = make_repo(tmp_path / "repo")
    (repo / "large.txt").write_bytes(b"12345")
    commit_all(repo, "large")

    service, store = service_for(tmp_path, repo, max_bytes=4)

    with pytest.raises(SourceOversizeError):
        service.admit(request_for(repo), allow)

    assert not list(store.root.rglob("*")) or all(
        path.name == ".scope" for path in store.root.rglob("*")
    )


def test_source_file_count_limit_applies_to_selected_paths(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    (repo / "one.txt").write_text("one\n", encoding="utf-8")
    (repo / "two.txt").write_text("two\n", encoding="utf-8")
    commit_all(repo, "two files")
    service, _store = service_for(tmp_path, repo, max_files=1)

    with pytest.raises(SourceOversizeError, match="file count"):
        service.admit(request_for(repo), allow)


def test_source_byte_limit_applies_to_the_complete_snapshot(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    (repo / "one.txt").write_bytes(b"123")
    (repo / "two.txt").write_bytes(b"456")
    commit_all(repo, "six bytes")
    service, _store = service_for(tmp_path, repo, max_bytes=5)

    with pytest.raises(SourceOversizeError):
        service.admit(request_for(repo), allow)


def test_fifo_is_rejected_without_blocking_for_a_writer(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    (repo / "source.txt").write_text("source\n", encoding="utf-8")
    commit_all(repo, "source")
    os.mkfifo(repo / "untracked.fifo")
    service, _store = service_for(tmp_path, repo)

    with pytest.raises(SourcePathError, match="not a regular file"):
        service._read_bounded(repo, "untracked.fifo", 1024)


def test_gcloud_credential_children_are_excluded(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    credentials = repo / ".config" / "gcloud"
    credentials.mkdir(parents=True)
    (credentials / "application_default_credentials.json").write_text(
        '{"token":"do-not-copy"}\n',
        encoding="utf-8",
    )
    (repo / "public.txt").write_text("public\n", encoding="utf-8")
    commit_all(repo, "credentials and public")
    service, _store = service_for(tmp_path, repo)

    snapshot = service.admit(request_for(repo), allow)

    secret_path = ".config/gcloud/application_default_credentials.json"
    assert secret_path in snapshot.excluded_paths
    assert {item.path for item in snapshot.files} == {"public.txt"}


def test_authorized_root_anchor_survives_parent_path_replacement(tmp_path: Path):
    authorized_parent = tmp_path / "authorized-parent"
    authorized_parent.mkdir()
    repo = make_repo(authorized_parent / "repo")
    (repo / "source.txt").write_bytes(b"authorized bytes\n")
    commit_all(repo, "source")
    foreign_parent = tmp_path / "foreign-parent"
    foreign_repo = foreign_parent / "repo"
    foreign_repo.mkdir(parents=True)
    (foreign_repo / "source.txt").write_bytes(b"outside bytes\n")
    store = LocalArtifactStore(tmp_path / "cas-anchor", "scope-source")
    service = SourceService(store, authorized_roots=[repo])
    original_read = service._read_bounded

    def read_while_parent_path_points_elsewhere(root, relative_path, max_bytes):
        held = tmp_path / "held-parent"
        authorized_parent.rename(held)
        authorized_parent.symlink_to(foreign_parent, target_is_directory=True)
        try:
            return original_read(root, relative_path, max_bytes)
        finally:
            authorized_parent.unlink()
            held.rename(authorized_parent)

    service._read_bounded = read_while_parent_path_points_elsewhere
    snapshot = service.admit(request_for(repo), allow)
    source_file = next(item for item in snapshot.files if item.path == "source.txt")

    assert store.read(ArtifactRef.model_validate(source_file.artifact_ref)) == b"authorized bytes\n"


def test_excluded_file_change_before_diff_never_enters_cas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path / "repo")
    (repo / "safe.txt").write_bytes(b"safe\n")
    (repo / ".env").write_bytes(b"excluded baseline\n")
    commit_all(repo, "source")
    service, store = service_for(tmp_path, repo)
    original_git = service._run_git
    marker = b"excluded-race-marker"
    injected = False

    def change_excluded_file_before_diff(root, args, **kwargs):
        nonlocal injected
        if args[0] == "diff" and not injected:
            injected = True
            (repo / ".env").write_bytes(marker + b"\n")
        return original_git(root, args, **kwargs)

    monkeypatch.setattr(service, "_run_git", change_excluded_file_before_diff)

    with pytest.raises(SourceChangedDuringSnapshot):
        service.admit(request_for(repo, allow_dirty=True), allow)
    assert not any(
        marker in path.read_bytes()
        for path in store.root.rglob("*")
        if path.is_file()
    )


def test_diff_is_derived_from_the_captured_file_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path / "repo")
    (repo / "safe.txt").write_bytes(b"baseline\n")
    commit_all(repo, "source")
    captured = b"captured-version-a\n"
    transient = b"diff-only-version-b\n"
    (repo / "safe.txt").write_bytes(captured)
    service, store = service_for(tmp_path, repo)
    original_git = service._run_git
    injected = False

    def swap_live_file_during_diff(root, args, **kwargs):
        nonlocal injected
        if args[0] != "diff" or injected:
            return original_git(root, args, **kwargs)
        injected = True
        target = repo / "safe.txt"
        before = target.stat()
        target.write_bytes(transient)
        try:
            return original_git(root, args, **kwargs)
        finally:
            target.write_bytes(captured)
            os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))

    monkeypatch.setattr(service, "_run_git", swap_live_file_during_diff)
    snapshot = service.admit(request_for(repo, allow_dirty=True), allow)
    diff = store.read(ArtifactRef.model_validate(snapshot.diff_ref))

    assert captured.rstrip() in diff
    assert transient.rstrip() not in diff


def test_cas_corruption_is_detected_on_source_readback(
    tmp_path: Path,
):
    repo = make_repo(tmp_path / "repo")
    (repo / "file.txt").write_text("safe\n", encoding="utf-8")
    commit_all(repo, "initial")

    service, store = service_for(tmp_path, repo)
    snapshot = service.admit(request_for(repo), allow)

    manifest_path = store.root / snapshot.manifest_ref["path"]
    manifest_path.chmod(0o600)
    manifest_path.write_bytes(b'{"corrupted":true}')

    with pytest.raises((SourceArtifactError, SourceReadbackError)):
        service.readback(snapshot, allow)


def test_source_change_during_snapshot_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path / "repo")
    (repo / "file.txt").write_text("before\n", encoding="utf-8")
    commit_all(repo, "initial")

    service, _store = service_for(tmp_path, repo)
    original_read = service._read_bounded
    changed = False

    def read_then_change(root: Path, relative_path: str, max_bytes: int):
        nonlocal changed
        payload, signature = original_read(root, relative_path, max_bytes)
        if not changed and relative_path == "file.txt":
            changed = True
            (repo / "file.txt").write_text("after\n", encoding="utf-8")
        return payload, signature

    monkeypatch.setattr(service, "_read_bounded", read_then_change)

    with pytest.raises(SourceChangedDuringSnapshot):
        service.admit(request_for(repo), allow)


def test_authorization_callback_is_required_and_cannot_expand_root(
    tmp_path: Path,
):
    repo = make_repo(tmp_path / "repo")
    (repo / "file.txt").write_text("safe\n", encoding="utf-8")
    commit_all(repo, "initial")
    service, _store = service_for(tmp_path, repo)

    with pytest.raises(SourceAuthorizationError):
        service.admit(request_for(repo), None)

    with pytest.raises(SourceAuthorizationError):
        service.admit(request_for(repo), lambda _request: False)


def test_git_executable_is_pinned_and_caller_path_is_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path / "repo")
    (repo / "source.txt").write_text("pinned git\n", encoding="utf-8")
    commit_all(repo, "source")
    service, _store = service_for(tmp_path, repo)
    malicious = tmp_path / "malicious-bin"
    malicious.mkdir()
    fake = malicious / "git"
    fake.write_text("#!/bin/sh\nexit 91\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(malicious))

    snapshot = service.admit(request_for(repo), allow)

    assert snapshot.git_executable == "/usr/bin/git"
    assert len(snapshot.git_executable_sha256) == 64


def test_authorizer_exception_text_is_not_exposed(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    (repo / "source.txt").write_text("source\n", encoding="utf-8")
    commit_all(repo, "source")
    service, _store = service_for(tmp_path, repo)

    def failed(_request):
        raise RuntimeError("private authorization implementation detail")

    with pytest.raises(SourceAuthorizationError) as error:
        service.admit(request_for(repo), failed)
    assert "private authorization" not in str(error.value)


def test_non_linux_backend_fails_closed_before_source_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = make_repo(tmp_path / "repo")
    (repo / "file.txt").write_text("safe\n", encoding="utf-8")
    commit_all(repo, "initial")

    monkeypatch.setattr("runtime.source.sys.platform", "win32")

    with pytest.raises(SourceBackendUnavailable):
        SourceService(
            object(),
            authorized_roots=[tmp_path],
        )
