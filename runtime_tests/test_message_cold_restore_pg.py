"""Original Message wake cycles on actual PG; signed Native facts are fixtures."""
from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta

from runtime.delivery_node import InvocationDeferred
from runtime.receiver_contract import native_generation
from runtime.receiver_crypto import sha256
from runtime.receiver_lifecycle_contract import (
    CapacityObservation,
    LifecycleReceipt,
    OwnedProcessEvidence,
    capacity_restore_ref,
    sign_observation,
    sign_receipt,
)
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send
from runtime_tests.test_communication_message_wake_pg import due, identity, install, saved
from runtime_tests.test_receiver_lifecycle_issuance_pg import RECEIVER, fact
from runtime_tests.test_receiver_lifecycle_issuance_pg import registered as registered_fixture

comm = comm_fixture
registered = registered_fixture


def test_same_waiting_message_restores_original_context_twice_without_new_message_or_recovery(registered, monkeypatch):
    f = registered
    calls, state = install(f)
    transport = f.authority._receiver_lifecycle_transports[RECEIVER]
    permits = []
    stopped_generation = [0]

    def visible(source, *, mutation):
        with f.authority._connect() as connection:
            value = connection.execute("SELECT payload FROM outbox WHERE operation_id=%s FOR UPDATE NOWAIT",
                (source.operation_ref,)).fetchone()[0]
            wake = value["receiver_wake"]
            if mutation:
                assert wake["lifecycle"]["phase"] == "executing"
            else:
                assert wake["lifecycle"]["phase"] in {"observing", "settled"}
            assert connection.execute("SELECT count(*) FROM delivery_receipts WHERE message_id=%s AND layer='runtime_dispatched'",
                (value["message_id"],)).fetchone() == (0,)

    def observe(challenge):
        c = challenge.challenge
        visible(c.source, mutation=False)
        calls.append("observe")
        capacity = fact(f, state="fresh" if state.capacity == "fresh" else "existing")
        if state.capacity != "fresh":
            selected = "controlled-message-wake-session"
            values = {"native_session_ref": selected, "provider_generation": native_generation(
                capacity.driver_binding_id, asdict(capacity.binding), selected)}
            if state.capacity == "stopped":
                reference = "stopped-process:" + sha256({"controlled_stop": stopped_generation[0]})
                values.update(state="stopped", input_state="unknown", blocker="unknown",
                    process=OwnedProcessEvidence(pid=4321 + stopped_generation[0], birth_ref="controlled-stop-birth-" + str(stopped_generation[0]),
                        containment_id="controlled-old-containment", evidence_ref=reference),
                    evidence_refs=(*[ref for ref in capacity.evidence_refs if ref != capacity.process.evidence_ref], reference))
            capacity = capacity.model_copy(update=values)
        return sign_observation(CapacityObservation(challenge_digest=sha256(c), request_id=c.request_id,
            nonce=c.nonce, source_digest=sha256(c.source), target=c.target, node_key_id=c.target.node_key_id, capacity=capacity), f.node_key)

    def execute(signed, **_options):
        p = signed.permit
        visible(p.plan.source, mutation=True)
        permits.append(signed)
        calls.append("execute")
        state.capacity = "existing"
        now = f.authority.canonical_now()
        selected = "controlled-message-wake-session"
        return sign_receipt(LifecycleReceipt(source=p.plan.source, target=p.plan.target, driver_operation_id=p.plan.driver_operation_id,
            action=p.plan.action, permit_digest=sha256(p), semantic_digest=p.semantic_digest, request_id=p.request_id,
            nonce=p.nonce, node_key_id=p.plan.target.node_key_id, outcome="acknowledged", effect_possible=True,
            evidence_refs=("controlled-cold-restore-ack",), native_session_ref=selected,
            provider_generation=native_generation(p.plan.capacity.driver_binding_id, asdict(p.plan.capacity.binding), selected),
            reason_code=None, observed_at=now, issued_at=now, deadline=now + timedelta(seconds=10),
            restore_process_ref=capacity_restore_ref(p.plan.capacity)), f.node_key)

    transport.observe, transport.execute = observe, execute
    driver = f.comm.drivers["b"]
    original_prepare = driver.prepare
    hold = [True]

    def preparing(invocation):
        if hold[0]:
            raise InvocationDeferred("controlled temporary Native transport outage")
        return original_prepare(invocation)

    monkeypatch.setattr(driver, "prepare", preparing)
    message = send(f.comm)["data"]
    with f.authority._connect() as connection:
        original_command = connection.execute("SELECT command_json FROM delivery_messages WHERE operation_id=%s", (message["operation_id"],)).fetchone()[0]
        operations_before = connection.execute("SELECT count(*) FROM operations").fetchone()[0]
    assert f.comm.dispatcher.dispatch(identity(f, message))["status"] == "retry_wait"
    assert saved(f, message)["receiver_wake"]["operation"]["state"] == "completed"
    for cycle in (1, 2):
        stopped_generation[0] = cycle
        state.capacity = "stopped"
        due(f, message)
        assert f.comm.dispatcher.dispatch(identity(f, message))["status"] == "retry_wait"
        wake = saved(f, message)["receiver_wake"]
        assert wake["operation"]["state"] == "completed"
        assert len(wake["lifecycle"]["history"]) == cycle
        assert wake["lifecycle"]["original_capacity_digest"]
        assert wake["lifecycle"]["plan"]["action"] == "resume"
        assert driver.calls == []
    assert [p.permit.plan.action for p in permits] == ["spawn", "resume", "resume"]
    assert len({p.permit.plan.driver_operation_id for p in permits}) == 3
    hold[0] = False
    due(f, message)
    assert f.comm.dispatcher.dispatch(identity(f, message))["status"] == "delivered"
    assert len(driver.calls) == 1
    with f.authority._connect() as connection:
        assert connection.execute("SELECT command_json FROM delivery_messages WHERE operation_id=%s", (message["operation_id"],)).fetchone()[0] == original_command
        assert connection.execute("SELECT count(*) FROM operations").fetchone() == (operations_before,)
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM outbox WHERE topic='communication.receiver.recovery'").fetchone() == (0,)
