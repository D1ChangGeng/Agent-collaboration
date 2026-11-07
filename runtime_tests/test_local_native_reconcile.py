"""Pure local reconciliation: real SQLite/Drivers with explicit synthetic Native peers."""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from runtime.codex_driver import DriverRejected
from runtime.delivery_node import DeliveryBoundaryRejected, LocalNodeEndpoint, invocation_for
from runtime.node import NodeJournal
from runtime_tests.test_native_handoff import delivery, mutations
from runtime_tests.test_receiver_evidence_native import receiver as receiver_fixture

receiver = receiver_fixture


@pytest.fixture
def local(receiver, tmp_path):
    state, adapter, invocation = delivery(receiver)
    identity = state.driver.identity
    journal = NodeJournal(tmp_path / "local-reconciliation.sqlite", machine_id=invocation.envelope.machine_id,
        node_id=identity.node_id, boot_incarnation=identity.node_boot_id)
    endpoint = LocalNodeEndpoint(journal, invocation.envelope.packet.target_scope_id,
                                 identity.agent_slot_id, adapter)
    return state, adapter, invocation, endpoint


def submit(local):
    state, _adapter, invocation, endpoint = local
    markers = []

    def mark(value, evidence):
        assert value == invocation and evidence["dispatch_id"] == invocation.dispatch_id
        assert mutations(state) == 0
        markers.append(evidence)

    result = endpoint.deliver(invocation.envelope, lambda: invocation.envelope, invocation=invocation,
                              mark_dispatched=mark, read_dispatch_marker=lambda _: bool(markers))
    assert len(markers) == 1
    return result


def ack_lost(local):
    state = local[0]
    if state.driver.harness == "codex":
        state.state["drop_invoke_ack"] = True
    else:
        state.peer.drop_prompt_ack = True


def no_history(local):
    state = local[0]
    if state.driver.harness == "codex":
        state.state["turns"] = []
    else:
        state.peer.hide_message = True


def test_lost_outer_ack_projects_existing_native_ack_without_another_input(local, monkeypatch):
    state, adapter, invocation, endpoint = local
    invoke = adapter.invoke

    def lose_outer_observation(*args, **kwargs):
        invoke(*args, **kwargs)
        raise OSError("synthetic Node observation loss after Native ACK")

    monkeypatch.setattr(adapter, "invoke", lose_outer_observation)
    assert submit(local)["status"] == "uncertain"
    assert mutations(state) == 1
    assert "runtime_acknowledged" not in {r.layer for r in endpoint.journal.receipts(invocation.operation_id)}
    result = endpoint.reconcile_delivery(invocation)
    assert result["status"] == "delivered" and result["native_outcome"]["outcome"] == "accepted"
    assert mutations(state) == 1
    layers = [r.layer for r in endpoint.journal.receipts(invocation.operation_id)]
    assert "runtime_acknowledged" in layers and "response_received" not in layers
    before = endpoint.journal.receipts(invocation.operation_id)
    assert endpoint.reconcile_delivery(invocation)["status"] == "delivered"
    assert endpoint.journal.receipts(invocation.operation_id) == before
    assert mutations(state) == 1


def test_lost_native_ack_uses_exact_readback_and_never_resubmits(local):
    state, _adapter, invocation, endpoint = local
    ack_lost(local)
    assert submit(local)["status"] == "uncertain"
    result = endpoint.reconcile_delivery(invocation)
    assert result["status"] == "delivered"
    assert result["native_outcome"]["native_input_ref"]
    assert mutations(state) == 1
    assert not any(r.layer == "response_received" for r in endpoint.journal.receipts(invocation.operation_id))


def test_unknown_native_outcome_stays_unknown_on_repeat_read(local):
    state, _adapter, invocation, endpoint = local
    ack_lost(local)
    assert submit(local)["status"] == "uncertain"
    no_history(local)
    before = endpoint.journal.receipts(invocation.operation_id)
    for _ in range(2):
        result = endpoint.reconcile_delivery(invocation)
        assert result["status"] == "uncertain" and result["native_outcome"]["outcome"] == "unknown"
        assert endpoint.journal.receipts(invocation.operation_id) == before
        assert mutations(state) == 1


def test_persisted_node_ack_is_not_rewritten_by_cached_native_query(local):
    state, _adapter, invocation, endpoint = local
    assert submit(local)["status"] == "delivered"
    before = endpoint.journal.receipts(invocation.operation_id)
    result = endpoint.reconcile_delivery(invocation)
    assert result["status"] == "delivered"
    assert endpoint.journal.receipts(invocation.operation_id) == before
    assert mutations(state) == 1


def test_missing_invocation_never_becomes_native_negative_evidence(local, monkeypatch):
    state, adapter, invocation, endpoint = local
    monkeypatch.setattr(adapter, "reconcile_input", lambda *_: pytest.fail("missing Node input queried Native"))
    result = endpoint.reconcile_delivery(invocation)
    assert result["status"] == "uncertain" and result["receipts"] == []
    assert result["reason_code"] == "node_invocation_unavailable" and mutations(state) == 0


def test_missing_dispatch_marker_does_not_query_or_retry_native(local, monkeypatch):
    state, adapter, invocation, endpoint = local
    ack_lost(local)
    submit(local)
    with endpoint.journal._transaction() as connection:
        connection.execute("DELETE FROM lifecycle_receipts WHERE operation_id=? AND layer='runtime_dispatched'",
                           (invocation.operation_id,))
    monkeypatch.setattr(adapter, "reconcile_input", lambda *_: pytest.fail("absent marker queried Native"))
    result = endpoint.reconcile_delivery(invocation)
    assert result["status"] == "uncertain" and result["reason_code"] == "node_dispatch_marker_unavailable"
    assert mutations(state) == 1


@pytest.mark.parametrize("change", ["content", "selection", "slot", "boot", "marker"])
def test_changed_original_input_or_node_never_reaches_native_read(local, monkeypatch, change):
    state, adapter, invocation, endpoint = local
    ack_lost(local)
    submit(local)
    candidate = invocation
    if change == "content":
        packet = invocation.envelope.packet.model_copy(update={"content": "different original text"})
        candidate = invocation_for(invocation.envelope.model_copy(update={"packet": packet}), invocation.attempt_id)
    elif change == "selection":
        candidate = invocation.model_copy(update={"selection_digest": "b" * 64})
    elif change == "slot":
        monkeypatch.setattr(endpoint, "agent_slot_id", "foreign-slot")
    elif change == "boot":
        monkeypatch.setattr(endpoint.journal, "_identity", replace(endpoint.identity, boot_incarnation="foreign-boot"))
    else:
        with endpoint.journal._transaction() as connection:
            row = connection.execute("SELECT evidence_json FROM lifecycle_receipts WHERE operation_id=? "
                                     "AND layer='runtime_dispatched'", (invocation.operation_id,)).fetchone()
            evidence = json.loads(row[0])
            evidence["envelope_digest"] = "c" * 64
            connection.execute("UPDATE lifecycle_receipts SET evidence_json=? WHERE operation_id=? "
                "AND layer='runtime_dispatched'", (json.dumps(evidence), invocation.operation_id))
    monkeypatch.setattr(adapter, "reconcile_input", lambda *_: pytest.fail("changed original queried Native"))
    with pytest.raises(DeliveryBoundaryRejected):
        endpoint.reconcile_delivery(candidate)
    assert mutations(state) == 1


def test_revoked_observation_cannot_add_a_missing_ack(local, monkeypatch):
    state, _adapter, invocation, endpoint = local
    ack_lost(local)
    submit(local)

    def revoked(*_args):
        raise DriverRejected("synthetic read authorization revoked")

    monkeypatch.setattr(state.driver, "check_current", revoked)
    with pytest.raises(DriverRejected, match="revoked"):
        endpoint.reconcile_delivery(invocation)
    assert mutations(state) == 1
    assert not any(r.layer == "runtime_acknowledged" for r in endpoint.journal.receipts(invocation.operation_id))


def test_native_readback_does_not_hold_node_sqlite_writer(local, monkeypatch):
    _state, adapter, invocation, endpoint = local
    ack_lost(local)
    submit(local)
    readback = adapter.reconcile_input
    endpoint.journal._busy_timeout_ms = 20

    def query(value):
        with endpoint.journal._transaction() as connection:
            assert connection.execute("SELECT state FROM delivery_invocations WHERE operation_id=?",
                                      (invocation.operation_id,)).fetchone()[0] == "uncertain"
        return readback(value)

    monkeypatch.setattr(adapter, "reconcile_input", query)
    assert endpoint.reconcile_delivery(invocation)["status"] == "delivered"


def test_inspection_does_not_trust_optimistic_status_without_ack(local):
    _state, _adapter, invocation, endpoint = local
    ack_lost(local)
    submit(local)
    assert endpoint.inspect_delivery(invocation.operation_id, "delivered")["status"] == "uncertain"


def test_inbox_only_delivery_remains_delivered_without_native_ack(local):
    state, _adapter, invocation, endpoint = local
    envelope = invocation.envelope.model_copy(update={"packet": invocation.envelope.packet.model_copy(
        update={"activation": "message_only"})})
    assert endpoint.deliver(envelope, lambda: envelope)["status"] == "delivered"
    assert endpoint.inspect_delivery(invocation.operation_id, "delivered")["status"] == "delivered"
    assert mutations(state) == 0
