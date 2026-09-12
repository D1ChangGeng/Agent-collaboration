from __future__ import annotations

# ruff: noqa: I001 -- standalone candidate and repository classify local imports differently.

import json
import multiprocessing
import os
import signal
import shutil
import stat
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from runtime import human_bridge_file_provider as provider
from runtime.human_bridge_file_provider import (
    CopyReadyEnvelope,
    LocalHumanBridgeTransport,
    ManualReturn,
    NotificationIntent,
    ProviderConflict,
    ProviderRejected,
    TrustedSurfaceContext,
    provider_attempt_id,
)

NOW = datetime.now(UTC)
DIGEST = "a" * 64


def make_root(tmp_path: Path) -> Path:
    root = tmp_path / "provider"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    return root


def intent(**changes) -> NotificationIntent:
    effect_id = changes.get("effect_id", "effect-1")
    values = {
        "effect_id": effect_id,
        "provider_attempt_id": provider_attempt_id(effect_id),
        "incident_id": "incident",
        "request_id": "request",
        "generation": 3,
        "expires_at": NOW + timedelta(minutes=5),
        "packet_digest": DIGEST,
        "artifact_digest": "b" * 64,
    }
    values.update(changes)
    values.setdefault("envelope", CopyReadyEnvelope(
        values["incident_id"], values["request_id"], values["generation"],
        values["expires_at"], values["packet_digest"], values["artifact_digest"],
    ))
    return NotificationIntent(**values)


def context(**changes) -> TrustedSurfaceContext:
    values = {
        "authenticated": True,
        "tenant_id": "tenant",
        "principal_ref": "human:operator",
        "grant_ref": "grant:manual",
        "incident_id": "incident",
        "incident_generation": 3,
        "incident_state": "human_requested",
        "expected_revision": 7,
        "accepted_state_digest": DIGEST,
        "deadline": NOW + timedelta(minutes=5),
    }
    values.update(changes)
    return TrustedSurfaceContext(**values)


def manual(**changes) -> ManualReturn:
    values = {
        "schema_version": "acs-human-bridge-manual-return/1",
        "packet_id": "packet-1",
        "tenant_id": "tenant",
        "incident_id": "incident",
        "generation": 3,
        "message_id": "message",
        "operation_id": "operation",
        "direction": "response",
        "expected_revision": 7,
        "accepted_state_digest": DIGEST,
        "payload_digest": "c" * 64,
        "artifact_digest": "d" * 64,
        "expires_at": NOW + timedelta(minutes=5),
    }
    values.update(changes)
    value = ManualReturn(**values)
    value.validate()
    return value


def write_manual(root: Path, name: str, value: ManualReturn) -> None:
    inbox = root / "inbox"
    temporary = inbox / (".tmp-" + name)
    data = provider._canonical(value)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, inbox / name)
    directory = os.open(inbox, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def notification_files(root: Path) -> list[Path]:
    return list((root / "notifications").glob("notification-*.json"))


def wait_process_gone(process: subprocess.Popen, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert process.poll() is not None


def process_publish(root: str, value: NotificationIntent, fail_after_publish: bool, queue) -> None:
    def fail():
        raise RuntimeError("injected process loss after publish")

    try:
        result = LocalHumanBridgeTransport(
            root, fault_after_publish=fail if fail_after_publish else None,
        ).publish(value)
        queue.put(("result", result))
    except Exception as error:  # noqa: BLE001 - process boundary returns only type/message
        queue.put(("error", type(error).__name__, str(error)))


pytestmark = pytest.mark.skipif(os.name != "posix", reason="real POSIX filesystem tests")


def test_layout_is_owner_only_and_journal_is_0600(tmp_path):
    root = make_root(tmp_path)
    transport = LocalHumanBridgeTransport(root)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "notifications").stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "inbox").stat().st_mode) == 0o700
    assert stat.S_IMODE(transport.database.stat().st_mode) == 0o600


def test_symlink_component_and_insecure_root_are_rejected(tmp_path):
    real = make_root(tmp_path)
    link = tmp_path / "linked"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises((ProviderRejected, OSError)):
        LocalHumanBridgeTransport(link)
    parent = tmp_path / "real-parent"
    parent.mkdir(mode=0o700)
    nested = parent / "provider"
    nested.mkdir(mode=0o700)
    parent_link = tmp_path / "parent-link"
    parent_link.symlink_to(parent, target_is_directory=True)
    with pytest.raises((ProviderRejected, OSError)):
        LocalHumanBridgeTransport(parent_link / "provider")
    real.chmod(0o755)
    with pytest.raises(ProviderRejected):
        LocalHumanBridgeTransport(real)


def test_notification_payload_is_digest_only_owner_file(tmp_path):
    root = make_root(tmp_path)
    transport = LocalHumanBridgeTransport(root)
    result = transport.publish(intent())
    path = root / "notifications" / result["filename"]
    payload = json.loads(path.read_bytes())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    sidecars = list((root / "notifications").glob(".identity-*.json"))
    assert len(sidecars) == 1 and stat.S_IMODE(sidecars[0].stat().st_mode) == 0o600
    assert set(payload) == {
        "schema_version", "effect_id", "provider_attempt_id", "incident_id", "request_id",
        "generation", "expires_at", "packet_digest", "artifact_digest", "copy_ready_envelope",
    }
    assert "secret" not in path.read_text().lower()
    assert "body" not in payload and "payload" not in payload
    with pytest.raises(ProviderRejected, match="expired"):
        transport.publish(intent(
            effect_id="expired", provider_attempt_id=provider_attempt_id("expired"),
            expires_at=NOW - timedelta(seconds=1),
        ))


def test_exact_publish_and_ack_replay_do_not_replace_notification(tmp_path):
    root = make_root(tmp_path)
    transport = LocalHumanBridgeTransport(root)
    first = transport.publish(intent())
    path = root / "notifications" / first["filename"]
    identity = path.stat().st_ino, path.stat().st_mtime_ns
    second = transport.publish(intent())
    assert second["created"] is False
    assert (path.stat().st_ino, path.stat().st_mtime_ns) == identity
    acknowledged = transport.acknowledge(first["effect_id"], first["file_digest"])
    assert acknowledged["state"] == "acknowledged"
    assert transport.publish(intent())["state"] == "acknowledged"
    with pytest.raises(ProviderConflict):
        transport.publish(intent(packet_digest="e" * 64))


def test_ack_loss_recovers_by_digest_after_process_restart(tmp_path):
    root = make_root(tmp_path)
    fired = {"value": False}

    def crash():
        if not fired["value"]:
            fired["value"] = True
            raise RuntimeError("injected ACK loss")

    transport = LocalHumanBridgeTransport(root, fault_after_publish=crash)
    with pytest.raises(RuntimeError, match="ACK loss"):
        transport.publish(intent())
    files = notification_files(root)
    assert len(files) == 1
    identity = files[0].stat().st_ino
    restarted = LocalHumanBridgeTransport(root)
    recovered = restarted.publish(intent())
    assert recovered["created"] is False
    assert files[0].stat().st_ino == identity
    assert recovered["state"] == "published"


def test_actual_process_restart_recovers_same_effect_without_second_file(tmp_path):
    root = make_root(tmp_path)
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    first = ctx.Process(target=process_publish, args=(str(root), intent(), True, queue))
    first.start()
    first.join(10)
    assert first.exitcode == 0
    assert queue.get(timeout=2)[:2] == ("error", "RuntimeError")
    files = notification_files(root)
    assert len(files) == 1
    inode = files[0].stat().st_ino
    second = ctx.Process(target=process_publish, args=(str(root), intent(), False, queue))
    second.start()
    second.join(10)
    assert second.exitcode == 0
    kind, result = queue.get(timeout=2)
    assert kind == "result" and result["created"] is False
    assert files[0].stat().st_ino == inode
    assert len(notification_files(root)) == 1


def test_concurrent_same_effect_creates_one_file(tmp_path):
    root = make_root(tmp_path)
    transport = LocalHumanBridgeTransport(root)
    results = []
    errors = []

    def publish():
        try:
            results.append(transport.publish(intent()))
        except Exception as error:  # noqa: BLE001 - independent concurrency evidence
            errors.append(error)

    threads = [threading.Thread(target=publish) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert errors == []
    assert len(notification_files(root)) == 1
    assert sum(item["created"] for item in results) == 1


def test_manual_file_never_authenticates_itself(tmp_path):
    root = make_root(tmp_path)
    transport = LocalHumanBridgeTransport(root)
    write_manual(root, "manual.json", manual())
    with pytest.raises(ProviderRejected, match="not an authorization"):
        transport.receive_manual(
            "manual.json", context=context(authenticated=False), now=NOW,
        )
    assert transport.journal_snapshot()["manual_returns"] == []


@pytest.mark.parametrize("changed", [
    {"tenant_id": "other"}, {"incident_id": "other"},
])
def test_manual_cross_tenant_or_incident_is_rejected(tmp_path, changed):
    root = make_root(tmp_path)
    transport = LocalHumanBridgeTransport(root)
    write_manual(root, "manual.json", manual(**changed))
    with pytest.raises(ProviderRejected, match="crosses"):
        transport.receive_manual("manual.json", context=context(), now=NOW)
    assert transport.journal_snapshot()["manual_returns"] == []


def test_manual_receive_replay_conflict_and_restart(tmp_path):
    root = make_root(tmp_path)
    transport = LocalHumanBridgeTransport(root)
    write_manual(root, "manual.json", manual())
    first = transport.receive_manual("manual.json", context=context(), now=NOW)
    assert first["disposition"] == "committed"
    restarted = LocalHumanBridgeTransport(root)
    assert restarted.receive_manual("manual.json", context=context(), now=NOW) == first
    (root / "inbox" / "manual.json").unlink()
    write_manual(root, "manual.json", manual(payload_digest="e" * 64))
    with pytest.raises(ProviderConflict):
        restarted.receive_manual("manual.json", context=context(), now=NOW)


@pytest.mark.parametrize("changed", [
    {"incident_generation": 4},
    {"incident_state": "resolved_automatic"},
    {"incident_state": "expired"},
    {"expected_revision": 8},
    {"accepted_state_digest": "e" * 64},
    {"deadline": NOW - timedelta(seconds=1)},
])
def test_reprobe_expiry_or_revision_change_is_fenced(tmp_path, changed):
    root = make_root(tmp_path)
    transport = LocalHumanBridgeTransport(root)
    write_manual(root, "manual.json", manual())
    result = transport.receive_manual(
        "manual.json", context=context(**changed), now=NOW,
    )
    assert result["disposition"] == "fenced_late"


def test_manual_file_mode_symlink_and_traversal_are_rejected(tmp_path):
    root = make_root(tmp_path)
    transport = LocalHumanBridgeTransport(root)
    write_manual(root, "manual.json", manual())
    (root / "inbox" / "manual.json").chmod(0o644)
    with pytest.raises(ProviderRejected):
        transport.receive_manual("manual.json", context=context(), now=NOW)
    (root / "inbox" / "manual.json").unlink()
    target = root / "target.json"
    target.write_bytes(provider._canonical(manual()))
    target.chmod(0o600)
    (root / "inbox" / "manual.json").symlink_to(target)
    with pytest.raises(ProviderRejected):
        transport.receive_manual("manual.json", context=context(), now=NOW)
    with pytest.raises(ProviderRejected):
        transport.receive_manual("../target.json", context=context(), now=NOW)


def test_journal_mode_or_identity_change_fails_closed(tmp_path):
    root = make_root(tmp_path)
    transport = LocalHumanBridgeTransport(root)
    transport.database.chmod(0o644)
    with pytest.raises(ProviderRejected):
        transport.journal_snapshot()
    transport.database.unlink()
    target = root / "other.sqlite"
    target.touch(mode=0o600)
    transport.database.symlink_to(target)
    with pytest.raises((ProviderRejected, OSError)):
        transport.journal_snapshot()


def test_same_bytes_new_journal_inode_is_rejected_by_live_and_restart_witness(tmp_path):
    root = make_root(tmp_path)
    transport = LocalHumanBridgeTransport(root)
    original = transport.database.read_bytes()
    replacement = root / "replacement.sqlite"
    replacement.write_bytes(original)
    replacement.chmod(0o600)
    os.replace(replacement, transport.database)
    with pytest.raises(ProviderRejected, match="witness"):
        transport.journal_snapshot()
    transport.close()
    with pytest.raises(ProviderRejected, match="persistent witness"):
        LocalHumanBridgeTransport(root)


def test_two_provider_witnesses_cannot_substitute_for_connection_fd(tmp_path):
    root = make_root(tmp_path)
    first = LocalHumanBridgeTransport(root)
    second = LocalHumanBridgeTransport(root)
    assert first.journal_snapshot()["notifications"] == []
    assert second.journal_snapshot()["notifications"] == []
    replacement = root / "replacement.sqlite"
    shutil.copyfile(first.database, replacement)
    replacement.chmod(0o600)
    os.replace(replacement, first.database)
    with pytest.raises(ProviderRejected, match="witness"):
        first.journal_snapshot()
    with pytest.raises(ProviderRejected, match="witness"):
        second.journal_snapshot()


def test_unrelated_original_inode_fds_cannot_mask_replaced_sqlite_path(tmp_path):
    root = make_root(tmp_path)
    first = LocalHumanBridgeTransport(root)
    second = LocalHumanBridgeTransport(root)
    held = [os.dup(first._database_witness_fd) for _ in range(8)]
    stop = threading.Event()

    def churn_original_inode():
        while not stop.is_set():
            descriptor = os.dup(held[0])
            os.fstat(descriptor)
            os.close(descriptor)

    churn = threading.Thread(target=churn_original_inode)
    churn.start()
    try:
        replacement = root / "replacement.sqlite"
        shutil.copyfile(first.database, replacement)
        replacement.chmod(0o600)
        os.replace(replacement, first.database)
        with pytest.raises(ProviderRejected, match="witness"):
            first.journal_snapshot()
        with pytest.raises(ProviderRejected, match="witness"):
            second.journal_snapshot()
    finally:
        stop.set()
        churn.join(5)
        for descriptor in held:
            os.close(descriptor)


def test_stopped_helper_request_times_out_and_is_killed(tmp_path):
    root = make_root(tmp_path)
    transport = LocalHumanBridgeTransport(root, helper_timeout_seconds=0.1)
    connection = transport._connect()
    process = connection.process
    os.kill(process.pid, signal.SIGSTOP)
    with pytest.raises(ProviderRejected, match="deadline|timed out"):
        connection.execute("SELECT 1")
    wait_process_gone(process)
    connection.close()
    connection.close()


def test_killed_helper_close_is_idempotent_and_reaps_all_streams(tmp_path):
    root = make_root(tmp_path)
    transport = LocalHumanBridgeTransport(root, helper_timeout_seconds=0.1)
    connection = transport._connect()
    process = connection.process
    os.kill(process.pid, signal.SIGKILL)
    connection.close()
    connection.close()
    wait_process_gone(process)
    assert process.stdin is not None and process.stdin.closed
    assert process.stdout is not None and process.stdout.closed
    assert process.stderr is not None and process.stderr.closed


def test_broken_pipe_while_closing_does_not_skip_other_cleanup(tmp_path):
    root = make_root(tmp_path)
    transport = LocalHumanBridgeTransport(root, helper_timeout_seconds=0.1)
    connection = transport._connect()
    process = connection.process
    original_stdin = process.stdin
    assert original_stdin is not None

    class BrokenClose:
        def fileno(self):
            return original_stdin.fileno()

        def close(self):
            original_stdin.close()
            raise BrokenPipeError("injected close failure")

    process.stdin = BrokenClose()
    os.kill(process.pid, signal.SIGKILL)
    connection.close()
    connection.close()
    wait_process_gone(process)
    assert process.stdout is not None and process.stdout.closed
    assert process.stderr is not None and process.stderr.closed


@pytest.mark.parametrize("child_code", [
    "import sys; sys.stdin.buffer.readline()",
    (
        "import sys,time; sys.stdin.buffer.readline(); "
        "sys.stdout.buffer.write(b'not-json\\n'); sys.stdout.buffer.flush(); time.sleep(10)"
    ),
    (
        "import sys,time; sys.stdin.buffer.readline(); "
        "sys.stdout.buffer.write(b'{\"status\":'); sys.stdout.buffer.flush(); time.sleep(10)"
    ),
])
def test_helper_eof_malformed_or_partial_response_is_controlled_and_reaped(
    monkeypatch, tmp_path, child_code,
):
    real_popen = subprocess.Popen
    processes = []

    def fake_popen(*_args, **_kwargs):
        process = real_popen(
            [sys.executable, "-c", child_code],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0, close_fds=True,
        )
        processes.append(process)
        return process

    monkeypatch.setattr(provider.subprocess, "Popen", fake_popen)
    with pytest.raises(ProviderRejected, match="helper"):
        provider._SQLiteHelperConnection(
            tmp_path, (1, 2, os.geteuid(), 0o600, 1), False, 0.1,
        )
    assert len(processes) == 1
    wait_process_gone(processes[0])
    assert processes[0].stdin is not None and processes[0].stdin.closed
    assert processes[0].stdout is not None and processes[0].stdout.closed
    assert processes[0].stderr is not None and processes[0].stderr.closed


def test_replaced_child_directory_is_revalidated_on_single_open(tmp_path):
    root = make_root(tmp_path)
    transport = LocalHumanBridgeTransport(root)
    notifications = root / "notifications"
    notifications.rmdir()
    notifications.mkdir(mode=0o777)
    notifications.chmod(0o777)
    with pytest.raises(ProviderRejected, match="child directory"):
        transport.publish(intent())


def test_same_bytes_new_notification_inode_is_rejected(tmp_path):
    root = make_root(tmp_path)
    transport = LocalHumanBridgeTransport(root)
    result = transport.publish(intent())
    notification = root / "notifications" / result["filename"]
    original_inode = notification.stat().st_ino
    replacement = root / "notifications" / "replacement.json"
    shutil.copyfile(notification, replacement)
    replacement.chmod(0o600)
    os.replace(replacement, notification)
    assert notification.stat().st_ino != original_inode
    with pytest.raises(ProviderConflict, match="identity"):
        transport.readback(result["effect_id"])
    with pytest.raises(ProviderConflict, match="identity"):
        transport.publish(intent())


def test_crash_sidecar_prevents_replacement_adoption_on_restart(tmp_path):
    root = make_root(tmp_path)

    def crash():
        raise RuntimeError("injected loss after durable identity sidecar")

    transport = LocalHumanBridgeTransport(root, fault_after_publish=crash)
    with pytest.raises(RuntimeError, match="durable identity"):
        transport.publish(intent())
    notification = notification_files(root)[0]
    old_inode = notification.stat().st_ino
    replacement = root / "notifications" / "replacement.json"
    shutil.copyfile(notification, replacement)
    replacement.chmod(0o600)
    os.replace(replacement, notification)
    assert notification.stat().st_ino != old_inode
    transport.close()
    restarted = LocalHumanBridgeTransport(root)
    with pytest.raises(ProviderConflict, match="sidecar"):
        restarted.publish(intent())


def test_crash_replacement_and_deleted_sidecar_cannot_be_adopted(tmp_path):
    root = make_root(tmp_path)

    def crash():
        raise RuntimeError("injected loss after publish")

    transport = LocalHumanBridgeTransport(root, fault_after_publish=crash)
    with pytest.raises(RuntimeError, match="after publish"):
        transport.publish(intent())
    notification = notification_files(root)[0]
    original_inode = notification.stat().st_ino
    replacement = notification.with_name("replacement.json")
    shutil.copyfile(notification, replacement)
    replacement.chmod(0o600)
    os.replace(replacement, notification)
    assert notification.stat().st_ino != original_inode
    next((root / "notifications").glob(".identity-*.json")).unlink()
    transport.close()
    restarted = LocalHumanBridgeTransport(root)
    with pytest.raises((ProviderRejected, ProviderConflict)):
        restarted.publish(intent())


def test_crash_missing_sidecar_is_not_rebuilt_from_notification(tmp_path):
    root = make_root(tmp_path)

    def crash():
        raise RuntimeError("injected loss after publish")

    transport = LocalHumanBridgeTransport(root, fault_after_publish=crash)
    with pytest.raises(RuntimeError, match="after publish"):
        transport.publish(intent())
    next((root / "notifications").glob(".identity-*.json")).unlink()
    transport.close()
    restarted = LocalHumanBridgeTransport(root)
    with pytest.raises((ProviderRejected, ProviderConflict)):
        restarted.publish(intent())
    assert list((root / "notifications").glob(".identity-*.json")) == []


def test_crash_same_bytes_replaced_sidecar_is_rejected_by_journal_intent(tmp_path):
    root = make_root(tmp_path)

    def crash():
        raise RuntimeError("injected loss after publish")

    transport = LocalHumanBridgeTransport(root, fault_after_publish=crash)
    with pytest.raises(RuntimeError, match="after publish"):
        transport.publish(intent())
    sidecar = next((root / "notifications").glob(".identity-*.json"))
    original_inode = sidecar.stat().st_ino
    replacement = root / "notifications" / "replacement-sidecar.json"
    shutil.copyfile(sidecar, replacement)
    replacement.chmod(0o600)
    os.replace(replacement, sidecar)
    assert sidecar.stat().st_ino != original_inode
    transport.close()
    restarted = LocalHumanBridgeTransport(root)
    with pytest.raises(ProviderConflict, match="sidecar inode"):
        restarted.publish(intent())


def test_windows_profile_is_fail_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(provider, "IS_POSIX", False)
    with pytest.raises(ProviderRejected, match="requires POSIX"):
        LocalHumanBridgeTransport(tmp_path / "provider")
