"""Real OS filesystem, paging, patch and session-context behavior."""
import base64
from types import SimpleNamespace

import pytest

from runtime.filesystem_gateway import FilesystemGateway
from runtime.machine_filesystem import FilesystemError, MachineFilesystem


def read_all(fs, path, **values):
    args = {"path": str(path), **values}
    result = fs.execute("read_file", args)
    parts = [result["content"]]
    while result["next_cursor"]:
        result = fs.execute("read_file", {"cursor": result["next_cursor"]})
        parts.append(result["content"])
    if result["encoding"] == "base64":
        return b"".join(base64.b64decode(item) for item in parts)
    return "".join(parts)


def test_reads_non_git_hidden_parent_and_symlink_paths(tmp_path):
    home = tmp_path / "home"
    work = home / "work"
    work.mkdir(parents=True)
    secret = home / ".env"
    secret.write_bytes(b"SYNTHETIC_VALUE=readable\n")
    fs = MachineFilesystem("test", cwd=work)
    assert fs.execute("read_file", {"path": "../.env"})["content"] == secret.read_text()
    assert read_all(fs, secret) == secret.read_text()
    try:
        (work / "linked.env").symlink_to(secret)
    except (OSError, NotImplementedError):
        return
    result = fs.execute("read_file", {"path": "linked.env"})
    assert result["content"] == secret.read_text()
    assert result["resolved_path"] == str(secret.resolve())


def test_multibyte_long_line_and_binary_paging(tmp_path):
    fs = MachineFilesystem("test", cwd=tmp_path, output_bytes=13)
    text = "汉字🌍" * 400 + "\nnext line\n"
    (tmp_path / "unicode.txt").write_bytes(text.encode("utf-8"))
    assert read_all(fs, "unicode.txt") == text
    binary = bytes(range(256)) * 100
    (tmp_path / "binary.dat").write_bytes(binary)
    assert read_all(fs, "binary.dat", encoding="base64") == binary
    assert read_all(fs, "binary.dat", offset_bytes=11, length_bytes=203, encoding="base64") == binary[11:214]


def test_line_ranges_and_file_changes(tmp_path):
    path = tmp_path / "readme"
    path.write_bytes(b"one\ntwo\nthree\n")
    fs = MachineFilesystem(cwd=tmp_path)
    assert fs.execute("read_file", {"path": "readme", "start_line": 2, "end_line": 2})["content"] == "two\n"
    assert fs.execute("read_file", {"path": "readme", "start_line": 10})["content"] == ""
    first = fs.execute("read_file", {"path": "readme", "max_output_bytes": 5})
    path.write_text("changed\n")
    with pytest.raises(FilesystemError, match="file_changed"):
        fs.execute("read_file", {"cursor": first["next_cursor"]})


def test_listing_glob_and_grep_include_hidden_and_nested_files(tmp_path):
    (tmp_path / ".hidden").write_text("needle one\n")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested/other.txt").write_text("needle two\n")
    fs = MachineFilesystem(cwd=tmp_path)
    listing = fs.execute("list_directory", {"limit": 1})
    entries = listing["entries"]
    while listing["next_cursor"]:
        listing = fs.execute("list_directory", {"cursor": listing["next_cursor"], "limit": 1})
        entries += listing["entries"]
    assert {item["relative_path"] for item in entries} == {".hidden", "nested"}
    assert [item["relative_path"] for item in fs.execute("glob", {"pattern": "**/*.txt"})["entries"]] == ["nested/other.txt"]
    first = fs.execute("grep", {"pattern": "needle", "limit": 1})
    second = fs.execute("grep", {"cursor": first["next_cursor"]})
    assert len(first["entries"]) == 1 and len(second["entries"]) == 1
    assert {first["entries"][0]["path"], second["entries"][0]["path"]} == {str(tmp_path/".hidden"), str(tmp_path/"nested/other.txt")}


def test_write_edit_and_patch_with_moves(tmp_path):
    fs = MachineFilesystem(cwd=tmp_path)
    fs.execute("write_file", {"path": "new/file.txt", "content": "old\n"})
    fs.execute("edit_file", {"path": "new/file.txt", "old_text": "old", "new_text": "new"})
    assert (tmp_path/"new/file.txt").read_text() == "new\n"
    with pytest.raises(FilesystemError, match="edit_conflict"):
        fs.execute("edit_file", {"path": "new/file.txt", "old_text": "old", "new_text": "new"})
    patch = "*** Begin Patch\n*** Add File: added.txt\n+added\n*** Update File: new/file.txt\n*** Move to: moved.txt\n@@\n-new\n+changed\n*** End Patch\n"
    changed = fs.execute("apply_patch", {"patch": patch})["changed_paths"]
    assert str(tmp_path/"moved.txt") in changed
    assert (tmp_path/"moved.txt").read_text() == "changed\n"
    assert (tmp_path/"added.txt").read_text() == "added\n"
    fs.execute("apply_patch", {"patch": "*** Begin Patch\n*** Delete File: added.txt\n*** End Patch\n"})
    assert not (tmp_path/"added.txt").exists()


def test_sessions_and_cursor_keep_selected_actual_target(tmp_path):
    remote_dir = tmp_path / "remote"
    remote_dir.mkdir()
    (remote_dir/"same.txt").write_text("remote contents\n")
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    (local_dir/"same.txt").write_bytes(b"local contents\n")
    remote_fs = MachineFilesystem("remote", cwd=remote_dir, output_bytes=7)
    endpoint = SimpleNamespace(descriptor=lambda: {"machine_id": "remote"},
        filesystem=lambda ctx, op, args: remote_fs.context(args.get("cwd"), args.get("base_cwd")) if op == "filesystem_context" else remote_fs.execute(op, args))
    authority = SimpleNamespace(context=None, _delivery_endpoints={"endpoint": endpoint})
    settings = SimpleNamespace(cwd=str(local_dir), default_machine_id="local", ssh_machines=[])
    one, two = FilesystemGateway(authority, settings), FilesystemGateway(authority, settings)
    one.execute("select_filesystem", {"machine_id": "remote"})
    first = one.execute("read_file", {"path": "same.txt"})
    assert two.execute("read_file", {"path": "same.txt"})["content"] == "local contents\n"
    one.execute("select_filesystem", {"machine_id": "local"})
    continuation = one.execute("read_file", {"cursor": first["next_cursor"]})
    assert continuation["machine_id"] == "remote"
    with pytest.raises(FilesystemError, match="argument_conflict"):
        one.execute("read_file", {"cursor": first["next_cursor"], "machine_id": "local"})


def test_large_sparse_file_reads_requested_bytes_and_symbolic_cycle_terminates(tmp_path):
    fs = MachineFilesystem(cwd=tmp_path)
    path = tmp_path/"large.bin"
    with path.open("wb") as target:
        target.seek(101 * 1024 * 1024)
        target.write(b"tail")
    result = fs.execute("read_file", {"path": str(path), "offset_bytes": 101 * 1024 * 1024,
                                      "length_bytes": 4})
    assert base64.b64decode(result["content"]) == b"tail"
    assert result["complete"]
    assert result["size_bytes"] > 100 * 1024 * 1024
    directory = tmp_path/"loop"
    directory.mkdir()
    try:
        (directory/"up").symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        return
    result = fs.execute("glob", {"pattern": "**/*"})
    assert result["complete"]
    assert len(result["entries"]) < 10


@pytest.mark.skipif(__import__("os").name != "posix" or __import__("os").geteuid() == 0,
                    reason="OS denies must be observed under an ordinary POSIX account")
def test_permission_denied_is_the_operating_system_result(tmp_path):
    path = tmp_path/"unreadable"
    path.write_bytes(b"unreadable by selected OS account")
    path.chmod(0)
    try:
        with pytest.raises(FilesystemError, match="permission_denied"):
            MachineFilesystem(cwd=tmp_path).execute("read_file", {"path": str(path)})
    finally:
        path.chmod(0o600)


def test_relative_session_directories_and_cursor_conflicts(tmp_path):
    (tmp_path/"runtime").mkdir()
    (tmp_path/"docs/runtime").mkdir(parents=True)
    (tmp_path/"docs/runtime/file.txt").write_text("correct directory contents")
    authority = SimpleNamespace(context=None, _delivery_endpoints={})
    settings = SimpleNamespace(cwd=str(tmp_path), default_machine_id="local", ssh_machines=[])
    gateway = FilesystemGateway(authority, settings)
    gateway.execute("select_filesystem", {"cwd": "runtime"})
    data = gateway.execute("read_file", {"cwd": "../docs/runtime", "path": "file.txt", "max_output_bytes": 7})
    assert data["path"] == str(tmp_path/"docs/runtime/file.txt")
    gateway.execute("select_filesystem", {"cwd": "../docs/runtime"})
    assert gateway.execute("filesystem_context", {})["cwd"] == str(tmp_path/"docs/runtime")
    with pytest.raises(FilesystemError, match="argument_conflict"):
        gateway.execute("read_file", {"cursor": data["next_cursor"], "cwd": str(tmp_path)})
    with pytest.raises(FilesystemError, match="argument_conflict"):
        gateway.local.execute("read_file", {"cursor": data["next_cursor"], "cwd": str(tmp_path)})


def test_patch_eof_targets_only_the_tail_and_reports_move_failure(tmp_path):
    fs = MachineFilesystem(cwd=tmp_path)
    path = tmp_path/"repeat.txt"
    path.write_text("head\nold\nmiddle\nold\n")
    fs.execute("apply_patch", {"patch": "*** Begin Patch\n*** Update File: repeat.txt\n@@\n-old\n+new\n*** End of File\n*** End Patch\n"})
    assert path.read_text() == "head\nold\nmiddle\nnew\n"
    with pytest.raises(FilesystemError, match="edit_conflict"):
        fs.execute("apply_patch", {"patch": "*** Begin Patch\n*** Update File: repeat.txt\n@@\n-old\n+wrong\n*** End of File\n*** End Patch\n"})
    (tmp_path/"blocker").write_text("not a directory")
    with pytest.raises(FilesystemError) as caught:
        fs.execute("apply_patch", {"patch": "*** Begin Patch\n*** Update File: repeat.txt\n*** Move to: blocker/moved.txt\n@@\n-new\n+final\n*** End of File\n*** End Patch\n"})
    assert path.read_text().endswith("final\n")
    assert caught.value.details["completed_paths"] == [str(path)]
    assert caught.value.details["pending_paths"] == [str(tmp_path/"blocker/moved.txt")]


def test_common_glob_patterns_respect_path_segments(tmp_path):
    (tmp_path/"top.py").write_text("top")
    (tmp_path/"a/nested").mkdir(parents=True)
    (tmp_path/"a/b.py").write_text("zero depth")
    (tmp_path/"a/nested/b.py").write_text("one depth")
    fs = MachineFilesystem(cwd=tmp_path)
    assert {e["relative_path"] for e in fs.execute("glob", {"pattern": "*.py"})["entries"]} == {"top.py"}
    assert {e["relative_path"] for e in fs.execute("glob", {"pattern": "a/**/b.py"})["entries"]} == {"a/b.py", "a/nested/b.py"}


def test_two_session_edits_are_serialized(tmp_path, monkeypatch):
    import threading
    authority = SimpleNamespace(context=None, _delivery_endpoints={})
    settings = SimpleNamespace(cwd=str(tmp_path), default_machine_id="local", ssh_machines=[])
    one, two = FilesystemGateway(authority, settings), FilesystemGateway(authority, settings)
    (tmp_path/"file.txt").write_text("seed")
    entered, release, attempted = threading.Event(), threading.Event(), threading.Event()
    original = one.local._write_file

    def write(path, args):
        entered.set()
        assert release.wait(5)
        return original(path, args)

    monkeypatch.setattr(one.local, "_write_file", write)
    outcomes = []

    def edit(gateway, content):
        attempted.set()
        try:
            gateway.execute("edit_file", {"path": "file.txt", "old_text": "seed", "new_text": content})
            outcomes.append(content)
        except FilesystemError as error:
            outcomes.append(error.code)

    first = threading.Thread(target=edit, args=(one, "first"))
    second = threading.Thread(target=edit, args=(two, "second"))
    first.start()
    assert entered.wait(5)
    attempted.clear()
    second.start()
    assert attempted.wait(5)
    release.set()
    first.join(5)
    second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert sorted(outcomes) == ["edit_conflict", "first"]
    assert (tmp_path/"file.txt").read_text() == "first"


def test_regular_write_failure_preserves_original_and_link_writes_follow_native(tmp_path, monkeypatch):
    import os
    fs = MachineFilesystem(cwd=tmp_path)
    path = tmp_path/"file.txt"
    path.write_text("original")
    original = os.replace

    def fail(source, destination):
        if destination == path:
            raise OSError("replace failed")
        return original(source, destination)

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(FilesystemError, match="filesystem_error"):
        fs.execute("write_file", {"path": str(path), "content": "replacement"})
    assert path.read_text() == "original"
    assert set(tmp_path.iterdir()) == {path}
    monkeypatch.setattr(os, "replace", original)
    link = tmp_path/"hardlink.txt"
    os.link(path, link)
    fs.execute("write_file", {"path": str(path), "content": "shared inode"})
    assert link.read_text() == "shared inode"


def test_grep_skipped_diagnostics_are_paginated_within_delivery_budget(tmp_path):
    for index in range(40):
        (tmp_path/f"binary-{index:03}.dat").write_bytes(b"\x00binary")
    fs = MachineFilesystem(cwd=tmp_path)
    page = fs.execute("grep", {"pattern": "needle", "max_output_bytes": 300})
    skipped = []
    while True:
        skipped.extend(page["skipped"])
        assert sum(len(__import__("json").dumps(r, ensure_ascii=False).encode()) for r in page["skipped"] + page["entries"]) <= 300
        if not page["next_cursor"]:
            break
        page = fs.execute("grep", {"cursor": page["next_cursor"], "max_output_bytes": 300})
    assert len(skipped) == 40
    assert len({r["path"] for r in skipped}) == 40
