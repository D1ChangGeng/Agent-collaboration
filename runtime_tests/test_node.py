from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest

from runtime.node import (
    JournalCorruptionError,
    JournalOperation,
    NodeJournal,
    NotFoundError,
    OperationIdentityConflict,
    ReceiptOrderError,
    UncertainSpawnError,
)


def operation(
    *,
    operation_id: str = "operation-1",
    command_id: str = "command-1",
    message_id: str = "message-1",
    operation_kind: str = "invoke",
    payload: object = b"payload",
) -> JournalOperation:
    return JournalOperation(
        operation_id=operation_id,
        command_id=command_id,
        message_id=message_id,
        operation_kind=operation_kind,
        payload_sha256=hashlib.sha256(
            json.dumps(
                ({"kind": "bytes", "value": payload.hex()} if isinstance(payload, bytes)
                 else {"kind": "json", "value": payload}),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    )


def test_legacy_append_read_and_digest_roundtrip(tmp_path: Path):
    journal = NodeJournal(tmp_path / "node.sqlite")
    item = operation()

    assert journal.append(item) == item
    assert journal.append(item) == item
    assert journal.read(item.operation_id) == item
    assert journal.digest(item) == journal.digest(item)
    assert journal.identity.machine_id
    assert journal.identity.node_id
    assert journal.identity.boot_incarnation


def test_operation_command_message_and_payload_conflicts_are_rejected(
    tmp_path: Path,
):
    journal = NodeJournal(tmp_path / "node.sqlite")
    item = operation()
    journal.append(item)

    with pytest.raises(OperationIdentityConflict):
        journal.append(
            operation(
                payload=b"different",
            )
        )

    with pytest.raises(OperationIdentityConflict):
        journal.append(
            operation(
                operation_id="operation-2",
                payload=b"different",
            )
        )

    with pytest.raises(OperationIdentityConflict):
        journal.append(
            operation(
                operation_id="operation-3",
                command_id="command-3",
                message_id=item.message_id,
            )
        )


def test_concurrent_append_is_exactly_once(tmp_path: Path):
    path = tmp_path / "node.sqlite"
    journal = NodeJournal(path)
    item = operation()

    def append_once() -> JournalOperation:
        return journal.append(item)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: append_once(), range(24)))

    assert results == [item] * 24

    with sqlite3.connect(path) as connection:
        count = connection.execute(
            "SELECT count(*) FROM journal WHERE operation_id=?",
            (item.operation_id,),
        ).fetchone()
    assert count == (1,)


def test_fresh_process_preserves_machine_and_node_and_rotates_boot(
    tmp_path: Path,
):
    path = tmp_path / "node.sqlite"
    first = NodeJournal(
        path,
        machine_id="machine-fixed",
        node_id="node-fixed",
    )

    script = """
import json
import sys
from runtime.node import NodeJournal

journal = NodeJournal(
    sys.argv[1],
    machine_id="machine-fixed",
    node_id="node-fixed",
)
print(json.dumps({
    "machine_id": journal.machine_id,
    "node_id": journal.node_id,
    "boot_incarnation": journal.boot_incarnation,
}))
"""
    environment = dict(os.environ)
    project_root = str(Path.cwd())
    environment["PYTHONPATH"] = (
        project_root
        + os.pathsep
        + environment.get("PYTHONPATH", "")
    )

    completed = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    observed = json.loads(completed.stdout)

    assert observed["machine_id"] == first.machine_id == "machine-fixed"
    assert observed["node_id"] == first.node_id == "node-fixed"
    assert observed["boot_incarnation"] != first.boot_incarnation


def test_mailbox_and_distinct_lifecycle_receipts_survive_ack_loss(
    tmp_path: Path,
):
    journal = NodeJournal(tmp_path / "node.sqlite")
    item = operation(operation_kind="delivery", payload={"request": "hello", "attempt": 1})
    journal.append(item)

    message = journal.enqueue(
        message_id=item.message_id,
        command_id=item.command_id,
        operation_id=item.operation_id,
        payload={"request": "hello", "attempt": 1},
    )
    assert message.state == "committed"

    accepted = journal.record_receipt(
        item.operation_id,
        "accepted_by_authority",
        evidence={"authority": "postgres"},
    )
    target = journal.record_receipt(
        item.operation_id,
        "target_inbox_committed",
        evidence={"mailbox": item.message_id},
    )
    dispatched = journal.record_receipt(
        item.operation_id,
        "runtime_dispatched",
        evidence={"endpoint": "local-test"},
    )

    # The caller loses the ACK after the target mailbox commit. Re-recording
    # the same layer is an exact replay, not a duplicate mailbox insertion.
    target_replay = journal.record_receipt(
        item.operation_id,
        "target_inbox_committed",
        evidence={"mailbox": item.message_id},
    )
    acknowledged = journal.record_receipt(
        item.operation_id,
        "runtime_acknowledged",
        evidence={"ack": "native-readback"},
    )

    assert target_replay == target
    assert [receipt.layer for receipt in journal.receipts(item.operation_id)] == [
        "accepted_by_authority",
        "target_inbox_committed",
        "runtime_dispatched",
        "runtime_acknowledged",
    ]
    assert accepted.status == "observed"
    assert dispatched.status == "observed"
    assert acknowledged.evidence["ack"] == "native-readback"

    reopened = NodeJournal(
        tmp_path / "node.sqlite",
        machine_id=journal.machine_id,
        node_id=journal.node_id,
    )
    recovered_message = reopened.get_message(item.message_id)
    assert recovered_message is not None
    assert recovered_message.state == "runtime_acknowledged"
    assert reopened.recover()["pending_mailbox"][0]["message_id"] == item.message_id


def test_receipt_order_and_receipt_identity_conflicts_fail_closed(
    tmp_path: Path,
):
    journal = NodeJournal(tmp_path / "node.sqlite")
    item = operation(operation_kind="delivery")
    journal.append(item)

    journal.record_receipt(item.operation_id, "response_received")

    with pytest.raises(ReceiptOrderError):
        journal.record_receipt(item.operation_id, "runtime_acknowledged")

    with pytest.raises(OperationIdentityConflict):
        journal.record_receipt(
            item.operation_id,
            "response_received",
            status="different-status",
        )


def test_mailbox_payload_conflicts_are_rejected(tmp_path: Path):
    journal = NodeJournal(tmp_path / "node.sqlite")
    item = operation(operation_kind="delivery", payload={"value": "first"})
    journal.append(item)

    journal.enqueue(
        message_id=item.message_id,
        command_id=item.command_id,
        operation_id=item.operation_id,
        payload={"value": "first"},
    )

    with pytest.raises(OperationIdentityConflict):
        journal.enqueue(
            message_id=item.message_id,
            command_id=item.command_id,
            operation_id=item.operation_id,
            payload={"value": "changed"},
        )

    with pytest.raises(OperationIdentityConflict):
        journal.enqueue(
            message_id=item.message_id,
            command_id=item.command_id,
            operation_id=item.operation_id,
            payload={"value": "first"},
            payload_sha256="0" * 64,
        )


def test_uncertain_spawn_cannot_automatically_spawn_again(
    tmp_path: Path,
):
    path = tmp_path / "node.sqlite"
    journal = NodeJournal(path)
    item = operation(
        operation_id="spawn-operation",
        command_id="spawn-command",
        message_id="spawn-message",
        operation_kind="spawn",
    )

    journal.begin_spawn(item, process_label="owned-test-process")
    journal.mark_spawn_dispatched(item.operation_id, process_label="owned-test-process")
    # Explicit trusted Node input fixture, not an asserted OS containment proof.
    journal.record_process_observation(item.operation_id, process_label="owned-test-process",
                                       pid=1234, start_identity="start-identity-1")
    journal.mark_spawn_uncertain(
        item.operation_id,
        reason="completion-record-lost-after-process-start",
    )

    reopened = NodeJournal(
        path,
        machine_id=journal.machine_id,
        node_id=journal.node_id,
    )
    assert reopened.spawn_state(item.operation_id)[0] == "uncertain"

    with pytest.raises(UncertainSpawnError):
        reopened.begin_spawn(item, process_label="owned-test-process")

    detail = reopened.reconcile_spawn(
        item.operation_id,
        outcome="completed",
        evidence={
            "process_label": "owned-test-process",
            "pid": 1234,
            "start_identity": "start-identity-1",
        },
    )
    assert detail["reconciliation"]["pid"] == 1234
    assert reopened.spawn_state(item.operation_id)[0] == "completed"

    # Explicit reconciliation closes the uncertainty; it does not execute a
    # second spawn. A later begin_spawn is an exact durable replay.
    assert reopened.begin_spawn(item) == item


def test_process_observations_are_not_containment_claims(tmp_path: Path):
    journal = NodeJournal(tmp_path / "node.sqlite")
    item = operation(operation_kind="spawn")
    journal.begin_spawn(item, process_label="observed-process")
    assert journal.mark_spawn_dispatched(item.operation_id, process_label="observed-process")

    observed = journal.record_process_observation(
        item.operation_id,
        process_label="observed-process",
        pid=4321,
        start_identity="proc-start-1",
    )
    assert observed.containment_claimed is False
    assert journal.process_observations(item.operation_id) == (observed,)

    with pytest.raises(ValueError):
        journal.record_process_observation(
            item.operation_id,
            process_label="observed-process",
            pid=4321,
            start_identity="proc-start-1",
            containment_claimed=True,
        )


def test_missing_operation_and_corrupt_journal_fail_closed(tmp_path: Path):
    path = tmp_path / "node.sqlite"
    journal = NodeJournal(path)

    with pytest.raises(NotFoundError):
        journal.enqueue(
            message_id="message-missing",
            command_id="command-missing",
            operation_id="operation-missing",
            payload={"value": "missing"},
        )

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE node_meta SET value=? WHERE key='schema_version'",
            ("corrupt-schema",),
        )

    with pytest.raises(JournalCorruptionError):
        NodeJournal(path)


def observed_spawn(tmp_path):
    journal = NodeJournal(tmp_path / "spawn.sqlite")
    item = operation(operation_kind="spawn")
    journal.begin_spawn(item, process_label="trusted-node-label")
    assert journal.mark_spawn_dispatched(item.operation_id)
    # Synthetic identity supplied by a trusted Node observer for validation
    # tests. No test treats this tuple as OS containment or Domain authority.
    proof = {"process_label": "trusted-node-label", "pid": 4321, "start_identity": "fixture-start-1"}
    journal.record_process_observation(item.operation_id, **proof)
    return journal, item, proof


def test_mailbox_bytes_must_match_the_registered_operation_digest(tmp_path):
    journal = NodeJournal(tmp_path / "mailbox.sqlite")
    item = operation(operation_kind="delivery", payload={"body": "registered"})
    journal.append(item)
    changed = {"body": "different actual input"}
    with pytest.raises(OperationIdentityConflict):
        journal.enqueue(message_id=item.message_id, command_id=item.command_id, operation_id=item.operation_id,
                        payload=changed, payload_sha256=NodeJournal.payload_digest(changed))
    assert journal.list_mailbox() == ()
    assert journal.read(item.operation_id) == item
    with pytest.raises(ValueError, match="payload_sha256"):
        journal.enqueue(message_id=item.message_id, command_id=item.command_id, operation_id=item.operation_id,
                        payload={"body": "registered"}, payload_sha256="")


def test_concurrent_preparation_has_one_atomic_dispatch_permission(tmp_path):
    journal = NodeJournal(tmp_path / "dispatch.sqlite")
    item = operation(operation_kind="spawn")
    barrier = threading.Barrier(8)
    marker = tmp_path / "actual-child-dispatches.txt"
    child = "import sys\nwith open(sys.argv[1], 'a') as output:\n    output.write('dispatch\\n')\n"
    def dispatch(_):
        journal.begin_spawn(item, process_label="one-dispatch")
        barrier.wait(timeout=10)
        permitted = journal.mark_spawn_dispatched(item.operation_id, process_label="one-dispatch")
        if permitted:
            subprocess.run([sys.executable, "-c", child, str(marker)], check=True, timeout=10)
        return permitted
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(dispatch, range(8)))
    assert results.count(True) == 1
    assert results.count(False) == 7
    assert marker.read_text().splitlines() == ["dispatch"]
    assert journal.spawn_state(item.operation_id)[0] == "dispatched"


@pytest.mark.parametrize("state", ["dispatched", "still_running"])
def test_begin_cannot_reenter_a_dispatched_or_running_spawn(tmp_path, state):
    journal, item, proof = observed_spawn(tmp_path)
    if state == "still_running":
        journal.mark_spawn_uncertain(item.operation_id, reason="lost-response")
        journal.reconcile_spawn(item.operation_id, outcome="still_running", evidence=proof)
    before = journal.spawn_state(item.operation_id)
    with pytest.raises(UncertainSpawnError):
        journal.begin_spawn(item, process_label=proof["process_label"])
    assert journal.mark_spawn_dispatched(item.operation_id) is False
    assert journal.spawn_state(item.operation_id) == before


def test_terminal_replay_never_authorizes_another_dispatch(tmp_path):
    journal, item, proof = observed_spawn(tmp_path)
    journal.mark_spawn_completed(item.operation_id, evidence=proof)
    before = journal.spawn_state(item.operation_id)
    assert journal.begin_spawn(item) == item
    assert journal.mark_spawn_dispatched(item.operation_id) is False
    journal.mark_spawn_completed(item.operation_id, evidence=proof)
    with pytest.raises(OperationIdentityConflict, match="cannot regress"):
        journal.mark_spawn_uncertain(item.operation_id, reason="rewrite-completed")
    with pytest.raises(OperationIdentityConflict, match="label"):
        journal.mark_spawn_dispatched(item.operation_id, process_label="other-process")
    assert journal.spawn_state(item.operation_id) == before


@pytest.mark.parametrize("target", ["intent", "absent", "still_running"])
def test_direct_state_setter_cannot_reset_or_invent_reconciliation(tmp_path, target):
    journal, item, _ = observed_spawn(tmp_path)
    before = journal.spawn_state(item.operation_id)
    with pytest.raises(ValueError, match="explicit preparation or reconciliation"):
        journal._set_spawn_state(item.operation_id, target)
    assert journal.spawn_state(item.operation_id) == before


def test_process_label_cannot_be_rebound_or_erased(tmp_path):
    journal = NodeJournal(tmp_path / "labels.sqlite")
    item = operation(operation_kind="spawn")
    journal.begin_spawn(item, process_label="stable-label")
    before = journal.spawn_state(item.operation_id)
    with pytest.raises(OperationIdentityConflict, match="label"):
        journal.begin_spawn(item, process_label="different-label")
    with pytest.raises(OperationIdentityConflict, match="label"):
        journal.mark_spawn_dispatched(item.operation_id, process_label="different-label")
    assert journal.spawn_state(item.operation_id) == before
    assert journal.mark_spawn_dispatched(item.operation_id)
    journal.mark_spawn_uncertain(item.operation_id, reason="observation-lost")
    assert journal.spawn_state(item.operation_id)[1]["process_label"] == "stable-label"


@pytest.mark.parametrize("change", [
    {"process_label": "other-label"}, {"pid": 9999}, {"start_identity": "reused-pid-new-start"}, {},
])
def test_reconciliation_requires_label_pid_and_start_identity(tmp_path, change):
    journal, item, proof = observed_spawn(tmp_path)
    journal.mark_spawn_uncertain(item.operation_id, reason="completion-not-recorded")
    before = journal.spawn_state(item.operation_id)
    evidence = proof | change if change else {}
    with pytest.raises(OperationIdentityConflict):
        journal.reconcile_spawn(item.operation_id, outcome="completed", evidence=evidence)
    assert journal.spawn_state(item.operation_id) == before


def test_reconciliation_does_not_mint_a_process_observation(tmp_path):
    journal = NodeJournal(tmp_path / "unobserved.sqlite")
    item = operation(operation_kind="spawn")
    journal.begin_spawn(item, process_label="known-label")
    journal.mark_spawn_dispatched(item.operation_id)
    journal.mark_spawn_uncertain(item.operation_id, reason="process-observation-lost")
    with pytest.raises(OperationIdentityConflict, match="PID/start"):
        journal.reconcile_spawn(item.operation_id, outcome="completed",
                                evidence={"process_label": "known-label", "pid": 1234, "start_identity": "unobserved"})
    assert journal.process_observations(item.operation_id) == ()
    assert journal.spawn_state(item.operation_id)[0] == "uncertain"


@pytest.mark.parametrize("change", [
    {"process_label": "other-label"}, {"pid": 9999}, {"start_identity": "new-start-for-reused-pid"},
])
def test_process_observation_cannot_replace_the_bound_identity(tmp_path, change):
    journal, item, proof = observed_spawn(tmp_path)
    before = journal.process_observations(item.operation_id)
    with pytest.raises(OperationIdentityConflict):
        journal.record_process_observation(item.operation_id, **(proof | change))
    assert journal.process_observations(item.operation_id) == before


@pytest.mark.parametrize("pid,error,message", [
    (0, ValueError, "positive integer"), (-1, ValueError, "positive integer"),
    (True, TypeError, "must be an integer"),
])
def test_process_observation_requires_a_positive_integer_pid(tmp_path, pid, error, message):
    journal, item, proof = observed_spawn(tmp_path)
    with pytest.raises(error, match=message):
        journal.record_process_observation(item.operation_id, **(proof | {"pid": pid}))


def test_reconciliation_requires_a_reconcilable_state(tmp_path):
    journal, item, proof = observed_spawn(tmp_path)
    with pytest.raises(OperationIdentityConflict, match="requires uncertainty"):
        journal.reconcile_spawn(item.operation_id, outcome="completed", evidence=proof)
    assert journal.spawn_state(item.operation_id)[0] == "dispatched"


def test_explicit_absence_is_terminal_and_does_not_trigger_respawn(tmp_path):
    journal = NodeJournal(tmp_path / "absence.sqlite")
    item = operation(operation_kind="spawn")
    journal.begin_spawn(item, process_label="absent-label")
    journal.mark_spawn_uncertain(item.operation_id, reason="interrupted-before-dispatch-record")
    with pytest.raises(OperationIdentityConflict, match="explicit"):
        journal.reconcile_spawn(item.operation_id, outcome="absent", evidence={"process_label": "absent-label"})
    observation = {"process_label": "absent-label", "observation": "absent"}
    detail = journal.reconcile_spawn(item.operation_id, outcome="absent", evidence=observation)
    assert journal.reconcile_spawn(item.operation_id, outcome="absent", evidence=observation) == detail
    assert journal.begin_spawn(item) == item
    assert journal.mark_spawn_dispatched(item.operation_id) is False
    with pytest.raises(OperationIdentityConflict, match="terminal"):
        journal.reconcile_spawn(item.operation_id, outcome="still_running", evidence=observation)


@pytest.mark.parametrize("state", ["intent", "dispatched", "still_running"])
def test_fresh_boot_recovers_unrecorded_uncertainty_and_retires_old_writer(tmp_path, state):
    path = tmp_path / "recovery.sqlite"
    old = NodeJournal(path, boot_incarnation="old-boot")
    item = operation(operation_kind="spawn")
    old.begin_spawn(item, process_label="recovery-label")
    if state != "intent":
        old.mark_spawn_dispatched(item.operation_id)
    if state == "still_running":
        proof = {"process_label": "recovery-label", "pid": 1234, "start_identity": "fixture-start"}
        old.record_process_observation(item.operation_id, **proof)
        old.mark_spawn_uncertain(item.operation_id, reason="lost-state")
        old.reconcile_spawn(item.operation_id, outcome="still_running", evidence=proof)
    child = """
import json,sys
from runtime.node import NodeJournal
j=NodeJournal(sys.argv[1])
print(json.dumps({'boot':j.boot_incarnation,'state':j.spawn_state('operation-1')[0],
                  'pending':len(j.recover()['uncertain_spawns'])}))
"""
    env = dict(os.environ, PYTHONPATH=str(Path.cwd()) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    result = subprocess.run([sys.executable, "-c", child, str(path)], check=True, capture_output=True,
                            text=True, env=env, timeout=10)
    new = json.loads(result.stdout)
    assert new["boot"] != old.boot_incarnation and new["state"] == "uncertain" and new["pending"] == 1
    with pytest.raises(OperationIdentityConflict, match="retired"):
        old.append(item)
    with pytest.raises(OperationIdentityConflict, match="retired"):
        old.mark_spawn_dispatched(item.operation_id)
    with pytest.raises(OperationIdentityConflict, match="retired"):
        old.record_receipt(item.operation_id, "runtime_dispatched")
    with pytest.raises(OperationIdentityConflict, match="retired"):
        NodeJournal(path, boot_incarnation="old-boot")
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT value FROM node_meta WHERE key='boot_incarnation'").fetchone()[0] == new["boot"]
        assert connection.execute("SELECT count(*) FROM lifecycle_receipts").fetchone()[0] == 0


def test_transaction_body_locked_error_is_not_retried_or_yielded_twice(tmp_path):
    journal = NodeJournal(tmp_path / "transaction.sqlite")
    bodies = 0
    with (
        pytest.raises(sqlite3.OperationalError, match="database is locked"),
        journal._transaction() as connection,
    ):
        bodies += 1
        connection.execute("INSERT INTO node_meta(key,value) VALUES ('body-probe','uncommitted')")
        raise sqlite3.OperationalError("database is locked")
    assert bodies == 1
    with closing(sqlite3.connect(tmp_path / "transaction.sqlite")) as connection:
        assert connection.execute("SELECT value FROM node_meta WHERE key='body-probe'").fetchone() is None


@pytest.mark.parametrize("pragma", ["foreign_keys", "busy_timeout", "journal_mode", "synchronous"])
def test_connect_closes_connection_if_a_pragma_fails(tmp_path, monkeypatch, pragma):
    journal = NodeJournal(tmp_path / "pragma.sqlite")
    original = sqlite3.connect
    opened = []
    class FailingConnection(sqlite3.Connection):
        closed = False
        def execute(self, statement, *args, **kwargs):
            if statement.startswith(f"PRAGMA {pragma}"):
                raise sqlite3.OperationalError("injected PRAGMA failure")
            return super().execute(statement, *args, **kwargs)
        def close(self):
            self.closed = True
            return super().close()
    def connect(*args, **kwargs):
        connection = original(*args, **kwargs, factory=FailingConnection)
        opened.append(connection)
        return connection
    monkeypatch.setattr(sqlite3, "connect", connect)
    with pytest.raises(sqlite3.OperationalError, match="injected PRAGMA failure"):
        journal._connect()
    assert len(opened) == 1 and opened[0].closed
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        sqlite3.Connection.execute(opened[0], "SELECT 1")


def test_all_public_read_paths_close_connections(tmp_path, monkeypatch):
    journal = NodeJournal(tmp_path / "readers.sqlite")
    item = operation()
    journal.append(item)
    original = sqlite3.connect
    opened = []
    class TrackedConnection(sqlite3.Connection):
        closed = False
        def close(self):
            self.closed = True
            return super().close()
    def connect(*args, **kwargs):
        connection = original(*args, **kwargs, factory=TrackedConnection)
        opened.append(connection)
        return connection
    monkeypatch.setattr(sqlite3, "connect", connect)
    journal.read(item.operation_id)
    journal.get_message(item.message_id)
    journal.list_mailbox()
    journal.receipts(item.operation_id)
    journal.spawn_state(item.operation_id)
    journal.process_observations(item.operation_id)
    journal.recover()
    assert len(opened) == 7 and all(connection.closed for connection in opened)


@pytest.mark.parametrize("path", ["", ":memory:"])
def test_ephemeral_journal_storage_is_rejected(path):
    with pytest.raises(ValueError):
        NodeJournal(path)


def test_response_before_enqueue_is_not_pending_after_fresh_process_restart(tmp_path):
    path = tmp_path / "early-response.sqlite"
    journal = NodeJournal(path)
    payload = {"request": "completed-before-enqueue"}
    item = operation(operation_kind="delivery", payload=payload)
    journal.append(item)
    response = journal.record_receipt(item.operation_id, "response_received", evidence={"response": "done"})
    message = journal.enqueue(message_id=item.message_id, command_id=item.command_id,
                              operation_id=item.operation_id, payload=payload)
    assert message.state == "response_received"
    assert journal.record_receipt(item.operation_id, "response_received", evidence={"response": "done"}) == response
    assert journal.get_message(item.message_id).state == "response_received"
    assert journal.recover()["pending_mailbox"] == ()
    child = """
import json,sys
from runtime.node import NodeJournal
j=NodeJournal(sys.argv[1])
print(json.dumps({'state':j.get_message('message-1').state,'pending':j.recover()['pending_mailbox']}))
"""
    env = dict(os.environ, PYTHONPATH=str(Path.cwd()) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    completed = subprocess.run([sys.executable, "-c", child, str(path)], check=True,
                               capture_output=True, text=True, env=env, timeout=10)
    assert json.loads(completed.stdout) == {"state": "response_received", "pending": []}


def test_enqueue_inherits_highest_receipt_and_earlier_replay_does_not_regress(tmp_path):
    journal = NodeJournal(tmp_path / "receipt-state.sqlite")
    item = operation(operation_kind="delivery", payload=b"ordered")
    journal.append(item)
    accepted = journal.record_receipt(item.operation_id, "accepted_by_authority")
    dispatched = journal.record_receipt(item.operation_id, "runtime_dispatched")
    journal.enqueue(message_id=item.message_id, command_id=item.command_id,
                    operation_id=item.operation_id, payload=b"ordered")
    assert journal.get_message(item.message_id).state == "runtime_dispatched"
    assert journal.record_receipt(item.operation_id, "accepted_by_authority") == accepted
    assert journal.get_message(item.message_id).state == "runtime_dispatched"
    journal.record_receipt(item.operation_id, "response_received")
    assert journal.record_receipt(item.operation_id, "runtime_dispatched") == dispatched
    assert journal.get_message(item.message_id).state == "response_received"
    assert journal.recover()["pending_mailbox"] == ()


@pytest.mark.parametrize("original,replacement", [
    (b"a", {"encoding": "hex", "value": "61"}),
    ({"encoding": "hex", "value": "61"}, b"a"),
    (b"a", {"kind": "bytes", "value": "61"}),
])
def test_bytes_and_json_type_swaps_cannot_replay_an_operation(tmp_path, original, replacement):
    journal = NodeJournal(tmp_path / "type-tags.sqlite")
    item = operation(operation_kind="delivery", payload=original)
    journal.append(item)
    message = journal.enqueue(message_id=item.message_id, command_id=item.command_id,
                              operation_id=item.operation_id, payload=original)
    assert NodeJournal.payload_digest(original) != NodeJournal.payload_digest(replacement)
    assert json.loads(message.payload_json)["kind"] == ("bytes" if isinstance(original, bytes) else "json")
    with pytest.raises(OperationIdentityConflict):
        journal.append(operation(operation_kind="delivery", payload=replacement))
    with pytest.raises(OperationIdentityConflict):
        journal.enqueue(message_id=item.message_id, command_id=item.command_id,
                        operation_id=item.operation_id, payload=replacement)
    assert journal.get_message(item.message_id) == message
    assert journal.read(item.operation_id) == item


def test_five_column_legacy_journal_migration_preserves_original_digest_bytes(tmp_path):
    path = tmp_path / "legacy-five-columns.sqlite"
    original_digest = hashlib.sha256(b"original legacy payload bytes").hexdigest()
    legacy = JournalOperation("legacy-operation", "legacy-command", "legacy-message", "invoke", original_digest)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE journal(operation_id TEXT PRIMARY KEY,command_id TEXT NOT NULL,"
                           "message_id TEXT NOT NULL,operation_kind TEXT NOT NULL,payload_sha256 TEXT NOT NULL)")
        connection.execute("INSERT INTO journal VALUES (?,?,?,?,?)",
                           (legacy.operation_id, legacy.command_id, legacy.message_id, legacy.operation_kind, original_digest))
        connection.commit()
    journal = NodeJournal(path)
    assert journal.read(legacy.operation_id) == legacy
    assert journal.append(legacy) == legacy
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT payload_sha256 FROM journal WHERE operation_id=?",
                                  (legacy.operation_id,)).fetchone()[0].encode("ascii") == original_digest.encode("ascii")
