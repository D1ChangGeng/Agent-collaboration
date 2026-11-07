"""Persistent Native handoff/reconciliation on real SQLite and synthetic wire peers."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from runtime.codex_driver import AuthorizedOperation, DriverRejected
from runtime.delivery_models import DeliveryEnvelope, MessagePacket
from runtime.delivery_node import InvocationDeferred, InvocationPreCallRejected, invocation_for
from runtime.native_delivery import NativeDeliveryAdapter
from runtime_tests.test_receiver_evidence_native import receiver as receiver_fixture

receiver = receiver_fixture


def delivery(receiver, *, record=True):
    _module, state, _adapter, _binding = receiver
    driver = state.driver
    packet = MessagePacket(project_id="fixture-project", sender="collaborator:fixture-project:a",
        recipient="collaborator:fixture-project:" + driver.identity.agent_slot_id,
        content="Synthetic isolated input", target_scope_id="fixture-scope",
        target_agent_slot_id=driver.identity.agent_slot_id)
    envelope = DeliveryEnvelope(tenant_id="fixture-tenant", authority_id="fixture-authority",
        authority_incarnation="fixture-incarnation", principal_ref="fixture-sender", grant_ref="fixture-send-grant",
        message_id="fixture-message", command_id="fixture-command", operation_id="fixture-operation",
        endpoint_id="fixture-receiver", binding_revision=3, machine_id="fixture-host",
        node_id=driver.identity.node_id, boot_incarnation=driver.identity.node_boot_id,
        accepted_state_digest="a" * 64, packet=packet)

    def authorize(invocation, identity):
        assert identity == driver.identity
        return AuthorizedOperation(invocation.invocation_id, invocation.command_id,
            invocation.message_id, "fixture-native-grant", None)

    adapter = NativeDeliveryAdapter(driver, authorize_invocation=authorize, record_handoff=record)
    return state, adapter, invocation_for(envelope, "fixture-attempt")


def mutations(state):
    if state.driver.harness == "codex":
        return state.state["turn_calls"]
    return sum(path.endswith("/prompt_async") for _, path, _ in state.peer.requests)


def test_handoff_is_durable_before_native_dispatch_and_not_part_of_prompt(receiver):
    state, adapter, invocation = delivery(receiver)
    markers = []

    def mark():
        record = state.driver.journal.read(invocation.invocation_id)
        assert record["state"] == "intent"
        context = record["input"]["payload"]["handoff_context"]
        assert context["operation_id"] == invocation.invocation_id
        assert context["binding_epoch"] == 3
        assert context["canonical_hash"] == invocation.envelope_digest
        assert context["message_handle"] == "message:fixture-project:fixture-message"
        assert context["provider_generation"]
        assert "acs-native-handoff/1" not in record["input"]["payload"]["text"]
        assert mutations(state) == 0
        markers.append(context)

    observed = adapter.invoke(invocation, on_dispatch=mark)
    assert observed.native_ack_ref and len(markers) == mutations(state) == 1
    reconciled = adapter.reconcile_input(invocation)
    assert reconciled.outcome == "accepted" and reconciled.effect_possible
    assert reconciled.binding_epoch == 3 and reconciled.provider_generation == markers[0]["provider_generation"]
    assert reconciled.native_input_ref and mutations(state) == 1


@pytest.mark.parametrize("fault", ["ack_lost", "journal_write_lost"])
def test_unknown_handoff_reconciles_original_input_without_resubmission(receiver, monkeypatch, fault):
    state, adapter, invocation = delivery(receiver)
    original_finish = state.driver.journal.finish
    if fault == "ack_lost":
        if state.driver.harness == "codex":
            state.state["drop_invoke_ack"] = True
        else:
            state.peer.drop_prompt_ack = True
    else:
        def unavailable(*_args):
            raise OSError("synthetic crash window after Native ACK")
        monkeypatch.setattr(state.driver.journal, "finish", unavailable)
    with pytest.raises((OSError, RuntimeError, TimeoutError)):
        adapter.invoke(invocation, on_dispatch=lambda: None)
    assert mutations(state) == 1
    assert state.driver.journal.read(invocation.invocation_id)["state"] in {"intent", "uncertain"}
    monkeypatch.setattr(state.driver.journal, "finish", original_finish)
    if state.driver.harness == "codex":
        state.state["drop_invoke_ack"] = False
    else:
        state.peer.drop_prompt_ack = False
    for _ in range(2):
        assert adapter.reconcile_input(invocation).outcome == "accepted"
        assert mutations(state) == 1


def test_missing_operation_or_missing_provider_evidence_is_not_negative_evidence(receiver):
    state, adapter, invocation = delivery(receiver)
    result = adapter.reconcile_input(invocation)
    assert result.outcome == "unknown" and result.effect_possible and mutations(state) == 0
    if state.driver.harness == "codex":
        state.state["drop_invoke_ack"] = True
    else:
        state.peer.drop_prompt_ack = True
    with pytest.raises((OSError, RuntimeError, TimeoutError)):
        adapter.invoke(invocation, on_dispatch=lambda: None)
    if state.driver.harness == "codex":
        state.state["turns"] = []
    else:
        state.peer.hide_message = True
    result = adapter.reconcile_input(invocation)
    assert result.outcome == "unknown" and result.effect_possible
    assert mutations(state) == 1


@pytest.mark.parametrize("unknown", [False, True])
def test_changed_generation_preserves_positive_facts_and_never_submits_input(receiver, monkeypatch, unknown):
    state, adapter, invocation = delivery(receiver)
    if unknown:
        if state.driver.harness == "codex":
            state.state["drop_invoke_ack"] = True
        else:
            state.peer.drop_prompt_ack = True
        with pytest.raises((OSError, RuntimeError, TimeoutError)):
            adapter.invoke(invocation, on_dispatch=lambda: None)
    else:
        adapter.invoke(invocation, on_dispatch=lambda: None)
    name = "thread_id" if state.driver.harness == "codex" else "session_id"
    monkeypatch.setattr(state.driver, name, "replacement-native-session")
    result = adapter.reconcile_input(invocation)
    assert result.outcome == ("unknown" if unknown else "accepted")
    assert result.reason_code == ("receiver_generation_changed" if unknown else "historical_native_ack")
    assert result.effect_possible and mutations(state) == 1


def test_persisted_ack_survives_lost_native_history_without_new_input(receiver):
    state, adapter, invocation = delivery(receiver)
    adapter.invoke(invocation, on_dispatch=lambda: None)
    if state.driver.harness == "codex":
        state.state["turns"] = []
    else:
        state.peer.hide_message = True
    result = adapter.reconcile_input(invocation)
    assert result.outcome == "accepted" and result.reason_code == "persisted_native_ack"
    assert result.evidence_ref and mutations(state) == 1


def test_changed_handoff_identity_cannot_reuse_an_operation(receiver):
    state, adapter, invocation = delivery(receiver)
    adapter.invoke(invocation, on_dispatch=lambda: None)
    operation = adapter._operation(invocation)
    context = adapter._handoff_context(invocation, operation).model_copy(update={"binding_epoch": 4})
    with pytest.raises(DriverRejected):
        state.driver.invoke(operation, adapter.prompt(invocation), handoff_context=context)
    assert mutations(state) == 1


def test_definite_pre_call_refusal_has_journal_evidence_and_no_input(receiver):
    state, adapter, invocation = delivery(receiver)
    if state.driver.harness == "codex":
        state.state["turns"] = [{"id": "external-work", "status": "inProgress", "items": []}]
    else:
        state.peer.busy = True
    with pytest.raises(InvocationDeferred):
        adapter.invoke(invocation, on_dispatch=lambda: None)
    result = adapter.reconcile_input(invocation)
    assert result.outcome == "definitively_not_admitted" and not result.effect_possible
    assert result.evidence_ref and mutations(state) == 0


def test_legacy_record_is_not_rewritten_when_handoff_recording_is_enabled(receiver):
    state, adapter, invocation = delivery(receiver, record=False)
    adapter.invoke(invocation, on_dispatch=lambda: None)
    before = state.driver.journal.read(invocation.invocation_id)
    adapter._record_handoff = True  # Trusted configuration change in this synthetic fixture.
    with pytest.raises(InvocationPreCallRejected, match="native_replay_without_domain_dispatch_marker"):
        adapter.invoke(invocation, on_dispatch=lambda: None)
    assert state.driver.journal.read(invocation.invocation_id) == before
    result = adapter.reconcile_input(invocation)
    assert result.outcome == "accepted" and result.binding_epoch == 0 and result.provider_generation is None
    assert result.reason_code == "legacy_receiving_epoch_unrecorded" and mutations(state) == 1


@pytest.mark.parametrize("field,value", [("canonical_hash", "corrupted"), ("driver_binding_id", "retired"),
    ("operation_id", "another-operation"), ("input_digest", "b" * 64), ("provider_generation", "c" * 64)])
def test_corrupted_handoff_evidence_does_not_become_negative_proof(receiver, field, value):
    state, adapter, invocation = delivery(receiver)
    adapter.invoke(invocation, on_dispatch=lambda: None)
    with state.driver.journal._connect() as connection:
        row = connection.execute("SELECT input_json FROM driver_operations WHERE operation_id=?",
                                 (invocation.invocation_id,)).fetchone()
        body = json.loads(row[0])
        body["payload"]["handoff_context"][field] = value
        connection.execute("UPDATE driver_operations SET input_json=? WHERE operation_id=?",
                           (json.dumps(body), invocation.invocation_id))
    result = adapter.reconcile_input(invocation)
    assert result.outcome == "unknown" and result.effect_possible
    assert result.reason_code in {"native_journal_unavailable", "receiver_generation_changed"}
    assert mutations(state) == 1


def test_refusal_with_mutation_evidence_stays_unknown(receiver):
    state, adapter, invocation = delivery(receiver)
    adapter.invoke(invocation, on_dispatch=lambda: None)
    state.driver.journal.finish(invocation.invocation_id, "rejected", {"synthetic": "conflicting state"})
    result = adapter.reconcile_input(invocation)
    assert result.outcome == "unknown" and result.effect_possible
    assert result.reason_code == "native_effect_evidence_present" and mutations(state) == 1


def test_session_change_before_journal_lock_cannot_submit_stale_handoff(receiver, monkeypatch):
    state, adapter, invocation = delivery(receiver)
    original = state.driver._run
    name = "thread_id" if state.driver.harness == "codex" else "session_id"

    def replace_before_lock(*args, **kwargs):
        with monkeypatch.context() as changed:
            changed.setattr(state.driver, name, "replacement-session-before-journal")
            return original(*args, **kwargs)

    monkeypatch.setattr(state.driver, "_run", replace_before_lock)
    with pytest.raises(InvocationPreCallRejected):
        adapter.invoke(invocation, on_dispatch=lambda: pytest.fail("stale handoff crossed Native boundary"))
    assert state.driver.journal.read(invocation.invocation_id) is None
    assert mutations(state) == 0


def test_cached_reconcile_rechecks_authorization_after_lock_wait(receiver, monkeypatch):
    state, adapter, invocation = delivery(receiver)
    adapter.invoke(invocation, on_dispatch=lambda: None)
    original = adapter.observation_operation
    revoked = []

    def current(*_args):
        if revoked:
            raise DriverRejected("synthetic authorization revoked before lock admission")

    def authorize_then_revoke(value):
        operation = original(value)
        revoked.append(True)
        return operation

    monkeypatch.setattr(state.driver, "check_current", current)
    monkeypatch.setattr(adapter, "observation_operation", authorize_then_revoke)
    with pytest.raises(DriverRejected, match="revoked"):
        adapter.reconcile_input(invocation)
    assert mutations(state) == 1


def test_removing_context_cannot_downgrade_a_record_to_legacy(receiver):
    state, adapter, invocation = delivery(receiver)
    adapter.invoke(invocation, on_dispatch=lambda: None)
    with state.driver.journal._connect() as connection:
        raw = connection.execute("SELECT input_json FROM driver_operations WHERE operation_id=?",
                                 (invocation.invocation_id,)).fetchone()[0]
        body = json.loads(raw)
        del body["payload"]["handoff_context"]
        connection.execute("UPDATE driver_operations SET input_json=? WHERE operation_id=?",
                           (json.dumps(body), invocation.invocation_id))
    result = adapter.reconcile_input(invocation)
    assert result.outcome == "unknown" and result.reason_code == "native_journal_unavailable"
    assert result.effect_possible and mutations(state) == 1


@pytest.mark.parametrize("blocker", ["approval", "question", "user_draft", "paused", "unknown"])
def test_opted_in_existing_native_chain_stops_at_observed_human_blocker(receiver, blocker):
    state, adapter, invocation = delivery(receiver)
    now = datetime.now(UTC)
    values = {"connection": "connected", "process": "present", "session": "present", "input": "ready", "blocker": blocker}
    adapter._observe_input = lambda: {"binding_id": state.driver.binding_id,
        "native_session_ref": state.driver.thread_id if state.driver.harness == "codex" else state.driver.session_id,
        "ownership": "exclusive_owned", "schema_verified": True, "dedicated_input": True,
        "observed_at": now.isoformat(), "expires_at": (now + timedelta(seconds=2)).isoformat(),
        "evidence_ref": "synthetic:current-blocker", "axes": {key: {"knowledge": "observed", "value": value}
        for key, value in values.items()}}
    with pytest.raises(InvocationDeferred):
        adapter.invoke(invocation, on_dispatch=lambda: pytest.fail("human blocker crossed Native boundary"))
    assert mutations(state) == 0 and state.driver.journal.read(invocation.invocation_id) is None
