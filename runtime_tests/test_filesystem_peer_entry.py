"""Read-only peer routing, path boundaries and live identity checks."""
import pytest

from runtime.filesystem_peer_entry import read_request
from runtime.machine_filesystem import FilesystemError, MachineFilesystem


def test_peer_reads_current_bytes_and_rechecks_authority(tmp_path):
    document = tmp_path / "AGENTS.md"
    document.write_bytes(b"Current instructions\n")
    filesystem = MachineFilesystem("owner-machine", cwd=tmp_path)
    calls = []
    request = {"machine_id": "owner-machine", "operation": "read_file", "arguments": {"path": "AGENTS.md"}}
    first = read_request(request, filesystem, [tmp_path], lambda: calls.append(True))
    assert first["content"] == "Current instructions\n" and calls == [True, True]
    document.write_bytes(b"Updated instructions\n")
    assert read_request(request, filesystem, [tmp_path], lambda: None)["content"] == "Updated instructions\n"


@pytest.mark.parametrize("operation", ["write_file", "edit_file", "apply_patch", "send_message", "exec"])
def test_peer_refuses_mutations_and_execution(tmp_path, operation):
    with pytest.raises(FilesystemError, match="profile_denied"):
        read_request({"machine_id": "owner-machine", "operation": operation, "arguments": {}},
                     MachineFilesystem("owner-machine", cwd=tmp_path), [tmp_path], lambda: None)


def test_peer_refuses_an_outside_file_and_a_changed_live_identity(tmp_path):
    root = tmp_path / "management"
    root.mkdir()
    private = tmp_path / "private.txt"
    private.write_text("Private data")
    request = {"machine_id": "owner-machine", "operation": "read_file", "arguments": {"path": str(private)}}
    filesystem = MachineFilesystem("owner-machine", cwd=root)
    with pytest.raises(FilesystemError, match="profile_denied"):
        read_request(request, filesystem, [root], lambda: None)
    (root / "AGENTS.md").write_text("Instructions")
    request["arguments"]["path"] = "AGENTS.md"
    calls = []

    def revoked_after_read():
        calls.append(True)
        if len(calls) == 2:
            raise PermissionError("revoked")

    with pytest.raises(PermissionError):
        read_request(request, filesystem, [root], revoked_after_read)


def test_peer_refuses_a_cursor_that_changes_machine_or_path(tmp_path):
    from runtime.machine_filesystem import encode_cursor
    request = {"machine_id": "owner-machine", "operation": "read_file", "arguments": {"cursor": encode_cursor({
        "action": "read_file", "machine_id": "other", "path": str(tmp_path / "AGENTS.md"), "cwd": str(tmp_path)})}}
    with pytest.raises(FilesystemError, match="argument_conflict"):
        read_request(request, MachineFilesystem("owner-machine", cwd=tmp_path), [tmp_path], lambda: None)
