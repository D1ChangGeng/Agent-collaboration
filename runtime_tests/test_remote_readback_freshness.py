"""Fresh receiver snapshots with actual signed receipts/SQLite, no POST replay.

The transport call and Authority-side store are controlled in-process fixtures;
the receiver, Node signature, Native Driver and private journal are real code.
"""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

from runtime.receiver_crypto import public_key, verify
from runtime.receiver_delivery import RemoteNodeEndpointAdapter
from runtime.receiver_models import SignedRequest
from runtime_tests.test_native_handoff import mutations
from runtime_tests.test_signed_harness_adapter import prepare_command, run
from runtime_tests.test_signed_harness_adapter import receiver as receiver_fixture
from runtime_tests.test_signed_harness_adapter import signed as signed_fixture

receiver = receiver_fixture
signed = signed_fixture


def test_readback_refreshes_same_operation_and_keeps_original_inbox_receipt(signed, monkeypatch):
    f = signed
    command = prepare_command(f)
    dispatch = SignedRequest.model_validate_json(base64.b64decode(command.sealed_envelope.data), strict=True)
    with f.service.ledger.connect() as connection:
        prepared = f.service._stored(connection.execute("SELECT * FROM receiver_requests WHERE purpose='delivery.prepare'").fetchone())
    requests = []
    peer = object.__new__(RemoteNodeEndpointAdapter)
    peer.config, peer.clock, peer._signing_key = f.service.config, f.service.clock, f.authority_key
    peer.store = SimpleNamespace(dispatch_admission=lambda operation: dispatch if operation == f.invocation.operation_id else None,
        persist_admission=lambda request: requests.append(request) or request,
        prepared_recovery_evidence=lambda *_args: (f.prepare, prepared))

    def read_only(request):
        assert request.admission.purpose == "delivery.readback"
        result = f.service.readback(request)
        verify(public_key(f.node_key), result.signature, result.receipt)
        return result

    peer._send = read_only
    entered, release = Event(), Event()
    original = f.adapter.invoke

    def hold_ack(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(f.adapter, "invoke", hold_ack)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(run, f.facade.admit_input(command))
        assert entered.wait(10)
        try:
            first = peer.inspect_delivery(f.invocation.operation_id)
            assert first["status"] == "uncertain"
            assert any(item["layer"] == "target_inbox_committed" for item in first["receipts"])
        finally:
            release.set()
        assert pending.result(timeout=10).outcome == "accepted"
    second = peer.inspect_delivery(f.invocation.operation_id)
    assert second["status"] == "delivered"
    assert {item["layer"] for item in second["receipts"]} == {"target_inbox_committed", "runtime_acknowledged"}
    assert len(requests) == 2
    assert requests[0].admission.request_id != requests[1].admission.request_id
    assert requests[0].admission.nonce != requests[1].admission.nonce
    assert requests[0].admission.operation_id == requests[1].admission.operation_id == f.invocation.operation_id
    assert requests[0].admission.dispatch_id == requests[1].admission.dispatch_id == f.invocation.dispatch_id
    assert mutations(f.native) == 1
