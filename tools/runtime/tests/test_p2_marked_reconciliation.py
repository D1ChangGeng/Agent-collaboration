from types import SimpleNamespace

from runtime.receiver_delivery import RemoteNodeEndpointAdapter


def test_marked_reconciliation_replays_exact_persisted_dispatch_once():
    invocation = SimpleNamespace(
        operation_id="operation", attempt_id="attempt", dispatch_id="dispatch",
    )
    signed_dispatch = SimpleNamespace(
        admission=SimpleNamespace(dispatch_id="dispatch"),
    )
    prepared = SimpleNamespace(receipt=SimpleNamespace(state="prepared"))
    acknowledged = SimpleNamespace(receipt=SimpleNamespace(state="runtime_acknowledged"))
    sends = []
    adapter = object.__new__(RemoteNodeEndpointAdapter)
    adapter.store = SimpleNamespace(
        dispatch_admission=lambda operation_id: signed_dispatch,
        prepared_recovery_evidence=lambda operation_id, attempt_id, dispatch_id: (
            SimpleNamespace(), prepared,
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
