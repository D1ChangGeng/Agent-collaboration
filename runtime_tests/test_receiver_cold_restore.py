"""Original-session cold restore through real lifecycle crypto/journal guards.

Core and Native peers are controlled here; this is implementation regression,
not an installed-Provider or physical-host qualification claim.
"""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from runtime.codex_driver import CodexAppServerDriver, DriverRejected
from runtime.native_restore import restoration_history, stopped_process
from runtime.receiver_lifecycle import lifecycle_operation_id
from runtime.receiver_lifecycle_contract import (
    LifecycleChallenge,
    capacity_restore_ref,
    sign_challenge,
    to_driver_operation,
)
from runtime.supervisor import OwnedProcess
from runtime_tests.test_receiver_lifecycle_capacity import capacity as capacity_fixture
from runtime_tests.test_receiver_lifecycle_node import node as node_fixture

capacity = capacity_fixture
node = node_fixture


def created_and_stopped(node):
    node.prepare("spawn")
    assert node.execute().receipt.outcome == "acknowledged"
    node.driver.owned.process.poll = lambda: 0
    node.capacity.proof.update(root_exited=True, remaining_pids=[])
    node.source = node.source.model_copy(update={"operation_ref": "restore-source", "command_id": "restore-command"})
    return stopped_process(node.driver)


def controlled_transport(node, monkeypatch):
    starts = []

    def launch(operation, *, lifecycle_action):
        assert lifecycle_action == "resume"
        prior = restoration_history(node.driver, exclude_operation_id=operation.operation_id)
        assert operation.restore_process_ref == prior["evidence_ref"]
        node.driver.check_current(operation, node.driver.identity)
        node.driver.journal.event(operation.operation_id, "process_dispatch", {"binding": asdict(node.driver.identity)})
        number = len(starts) + 1
        owned = OwnedProcess(SimpleNamespace(pid=49152 + number, poll=lambda: None),
                             "restored-job-" + str(number), "restored-birth-" + str(number))
        node.driver.owned = owned
        node.driver.ownership = "exclusive_owned"
        node.driver.client = type(node.client)()
        node.driver._owned_transport_identity = (id(owned), id(node.driver.client))
        node.capacity.proof.update(root_exited=False, remaining_pids=[owned.process.pid], pid=owned.process.pid,
            root_pid=owned.process.pid, birth_ref=owned.birth_ref, containment_id=owned.containment_id)
        node.driver.journal.event(operation.operation_id, "process_started", {"pid": owned.process.pid,
            "birth_ref": owned.birth_ref, "containment_id": owned.containment_id})
        starts.append(operation.operation_id)

    monkeypatch.setattr(node.driver, "_launch_owned_transport", launch)
    if isinstance(node.driver, CodexAppServerDriver):
        monkeypatch.setattr(node.driver, "_initialize", lambda operation: node.driver.check_current(operation, node.driver.identity))
    return starts


def test_stopped_capacity_is_original_session_evidence_without_claiming_native_readiness(node):
    original = created_and_stopped(node)
    before = list(node.native_calls)
    permit = node.prepare("resume")
    capacity = permit.permit.plan.capacity
    assert capacity.state == "stopped" and capacity.input_state == capacity.blocker == "unknown"
    assert capacity_restore_ref(capacity) == original["evidence_ref"]
    assert capacity.native_session_ref == (getattr(node.driver, "thread_id", None) or node.driver.session_id)
    assert node.native_calls == before
    operation = to_driver_operation(permit.permit.plan)
    assert operation.restore_process_ref == original["evidence_ref"]
    assert operation.operation_id != lifecycle_operation_id(node.source.operation_ref, "resume")


def test_signed_cold_restore_restarts_transport_once_and_never_creates_another_session_or_input(node, monkeypatch):
    created_and_stopped(node)
    starts = controlled_transport(node, monkeypatch)
    original_session = getattr(node.driver, "thread_id", None) or node.driver.session_id
    node.prepare("resume")
    receipt = node.execute().receipt
    assert receipt.outcome == "acknowledged" and receipt.native_session_ref == original_session
    assert receipt.restore_process_ref is not None and len(starts) == 1
    assert node.execute().receipt.outcome == node.reconcile().receipt.outcome == "acknowledged"
    assert len(starts) == 1
    if isinstance(node.driver, CodexAppServerDriver):
        assert [m for m, _params in node.native_calls].count("thread/start") == 1
        assert [m for m, _params in node.native_calls].count("thread/resume") == 1
        assert not any(m == "turn/start" for m, _params in node.native_calls)
    else:
        assert sum(method == "POST" and path == "/session" for method, path in node.native_calls) == 1
        assert not any(method == "POST" and "prompt" in path for method, path in node.native_calls)


@pytest.mark.parametrize("damage", ["unverified", "survivor", "birth", "pending"])
def test_cold_restore_needs_original_isolation_and_no_unresolved_input(node, damage):
    created_and_stopped(node)
    if damage == "unverified":
        node.capacity.proof["verified"] = False
    elif damage == "survivor":
        node.capacity.proof["remaining_pids"] = [49152]
    elif damage == "birth":
        node.capacity.proof["birth_ref"] = "different-process"
    else:
        with node.driver.journal._connect() as connection:
            connection.execute("UPDATE driver_operations SET state='uncertain'")
    # Observation must remain unknown; no invalid plan or Native mutation is made.
    raw = LifecycleChallenge(source=node.source, target=node.snapshot.target(), authority_key_id=node.config.authority_key_id,
        authority_key_revision=node.config.authority_key_revision, request_id="denied-restore", nonce="9" * 64,
        issued_at=node.driver_time.now, deadline=node.driver_time.now + timedelta(seconds=20))
    observed = node.controller.observe(sign_challenge(raw, node.key)).observation.capacity
    assert observed.state == "unknown"
    assert not node.effects[1:]


def test_restoration_identity_cannot_be_moved_to_another_stopped_process(node):
    original = created_and_stopped(node)
    permit = node.prepare("resume")
    operation = to_driver_operation(permit.permit.plan)
    changed = replace(operation, restore_process_ref="stopped-process:" + "0" * 64)
    with pytest.raises(DriverRejected):
        changed.validate(node.driver.clock)
    assert operation.restore_process_ref == original["evidence_ref"]
