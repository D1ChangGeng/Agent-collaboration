from types import SimpleNamespace

from runtime.receiver_delivery import RemoteNodeEndpointAdapter
from runtime.receiver_crypto import sha256


def test_marked_reconciliation_replays_exact_persisted_dispatch_once():
    envelope = SimpleNamespace(
        endpoint_id="endpoint", machine_id="machine", node_id="node",
        boot_incarnation="boot", packet=SimpleNamespace(
            target_scope_id="scope", target_agent_slot_id="slot",
        ),
    )
    invocation = SimpleNamespace(
        message_id="message", command_id="command", operation_id="operation",
        attempt_id="attempt", dispatch_id="dispatch", accepted_revision=0,
        accepted_state_digest="a" * 64, envelope_digest="b" * 64,
        selection_digest="c" * 64, envelope=envelope,
        model_dump=lambda mode: {"invocation": "same"},
    )
    signed_dispatch = SimpleNamespace(
        admission=SimpleNamespace(
            purpose="delivery.dispatch", request_id="receiver:attempt:dispatch:delivery.dispatch",
            message_id="message", command_id="command", operation_id="operation",
            attempt_id="attempt", dispatch_id="dispatch", accepted_revision=0,
            accepted_state_digest="a" * 64, envelope_digest="b" * 64,
            selection_digest="c" * 64,
            invocation_digest=sha256({"invocation": "same"}),
            endpoint_id="endpoint", machine_id="machine", node_id="node",
            boot_incarnation="boot", scope_id="scope", agent_slot_id="slot",
        ),
        body={"prepare_request_id": "prepared-request", "marker_receipt_id": "marker"},
    )
    invocation.runtime_dispatched_receipt_id = "marker"
    prepared = SimpleNamespace(receipt=SimpleNamespace(state="prepared"))
    acknowledged = SimpleNamespace(receipt=SimpleNamespace(state="runtime_acknowledged"))
    sends = []
    adapter = object.__new__(RemoteNodeEndpointAdapter)
    adapter.store = SimpleNamespace(
        dispatch_admission=lambda operation_id: signed_dispatch,
        prepared_recovery_evidence=lambda operation_id, attempt_id, dispatch_id: (
            SimpleNamespace(admission=SimpleNamespace(request_id="prepared-request")), prepared,
        ),
    )
    adapter._send = lambda request: sends.append(request) or acknowledged
    adapter._projection = lambda receipts, status: {
        "status": status, "receipts": receipts,
    }

    result = adapter.reconcile_marked(invocation)

    assert sends == [signed_dispatch]
    assert result["status"] == "delivered"
    assert result["receipts"] == [prepared, acknowledged]
