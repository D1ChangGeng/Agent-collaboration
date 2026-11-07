"""Strict wire/actual Node-controller E1; Native APIs are controlled in process."""
from __future__ import annotations

from datetime import timedelta

import pytest

from runtime.receiver_crypto import sha256, sign
from runtime.receiver_lifecycle_contract import LifecycleContractRejected
from runtime.receiver_lifecycle_transport import (
    EXECUTE,
    OBSERVE,
    READBACK,
    LifecycleExecutionRequest,
    LifecycleReadAdmission,
    LifecycleReceiverRouter,
    SignedLifecycleReadRequest,
    _read_body,
)
from runtime_tests.test_receiver_lifecycle_capacity import capacity as capacity_fixture
from runtime_tests.test_receiver_lifecycle_node import node as node_fixture

capacity, node = capacity_fixture, node_fixture


def request(n):
    return LifecycleExecutionRequest(permit=n.permit, challenge=n.challenge, observation=n.observation)


def read_request(n, *, expired=False):
    execution = request(n)
    now = n.driver_time.now
    admission = LifecycleReadAdmission(source=n.source, original_target=n.permit.permit.plan.target,
        execution_digest=sha256(execution), authority_key_id=n.config.authority_key_id,
        authority_key_revision=n.config.authority_key_revision, request_id="fresh-read-request", nonce="b" * 64,
        issued_at=now - timedelta(seconds=20) if expired else now,
        deadline=now - timedelta(seconds=10) if expired else now + timedelta(seconds=10))
    return SignedLifecycleReadRequest(admission=admission, execution=execution,
        signature=sign(n.key, _read_body(admission, execution)))


def test_signed_execute_and_fresh_authenticated_original_readback_use_actual_controller(node):
    node.prepare()
    router = LifecycleReceiverRouter(node.config, node.controller)
    result = router.handle(EXECUTE, request(node).model_dump_json().encode())
    assert result.receipt.outcome == "acknowledged" and node.effects == ["spawn"]
    before = len(node.native_calls)
    node.driver_time.now += timedelta(minutes=1)
    node.monotonic[0] += 60
    historical = router.handle(READBACK, read_request(node).model_dump_json().encode())
    assert historical.receipt.native_session_ref == result.receipt.native_session_ref
    assert historical.receipt.outcome == "acknowledged" and len(node.native_calls) == before


@pytest.mark.parametrize("defect", ["old_execute_request", "expired", "signature", "bundle", "target", "purpose"])
def test_old_or_mismatched_admission_cannot_authenticate_network_read(node, defect):
    node.prepare()
    router = LifecycleReceiverRouter(node.config, node.controller)
    router.handle(EXECUTE, request(node).model_dump_json().encode())
    before = len(node.read_calls)
    body = read_request(node, expired=defect == "expired")
    if defect == "old_execute_request":
        raw = request(node).model_dump_json().encode()
    elif defect == "signature":
        raw = body.model_copy(update={"signature": "0" * 128}).model_dump_json().encode()
    elif defect == "bundle":
        raw = body.model_dump_json().replace('"execution_digest":"', '"execution_digest":"0').encode()
    elif defect == "target":
        admission = body.admission.model_copy(update={"original_target": body.admission.original_target.model_copy(update={"binding_epoch": 999})})
        raw = body.model_copy(update={"admission": admission}).model_dump_json().encode()
    elif defect == "purpose":
        raw = body.model_dump_json().replace("receiver.lifecycle.readback", "receiver.lifecycle.execute").encode()
    else:
        raw = body.model_dump_json().encode()
    with pytest.raises(ValueError):
        router.handle(READBACK, raw)
    assert len(node.read_calls) == before


def test_read_authority_is_rechecked_and_no_rpc_or_resession_occurs(node):
    node.prepare()
    router = LifecycleReceiverRouter(node.config, node.controller)
    router.handle(EXECUTE, request(node).model_dump_json().encode())
    node.read_allowed = False
    before = len(node.native_calls)
    with pytest.raises(PermissionError):
        router.handle(READBACK, read_request(node).model_dump_json().encode())
    assert len(node.native_calls) == before and node.effects == ["spawn"]


def test_observe_wire_never_creates_native_state_and_rejects_duplicate_json(node):
    node.prepare()
    router = LifecycleReceiverRouter(node.config, node.controller)
    result = router.handle(OBSERVE, node.challenge.model_dump_json().encode())
    assert result.observation.capacity.state == "fresh" and node.effects == []
    raw = node.challenge.model_dump_json().replace('"signature":', '"signature":"' + "0" * 128 + '","signature":').encode()
    with pytest.raises(ValueError, match="duplicate"):
        router.handle(OBSERVE, raw)


def test_read_response_cannot_escape_after_fresh_transport_budget_expires(node, monkeypatch):
    node.prepare()
    router = LifecycleReceiverRouter(node.config, node.controller)
    router.handle(EXECUTE, request(node).model_dump_json().encode())
    signed = read_request(node)
    actual = node.controller.reconcile

    def delayed(*args, **kwargs):
        result = actual(*args, **kwargs)
        node.driver_time.now += timedelta(seconds=12)
        node.monotonic[0] += 12
        return result

    monkeypatch.setattr(node.controller, "reconcile", delayed)
    with pytest.raises(LifecycleContractRejected):
        router.handle(READBACK, signed.model_dump_json().encode())
