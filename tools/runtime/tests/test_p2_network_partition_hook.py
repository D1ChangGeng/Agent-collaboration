from types import SimpleNamespace

from runtime.receiver_delivery import RemoteNodeEndpointAdapter


def test_after_dispatch_mark_runs_after_marker_and_before_dispatch():
    events = []
    adapter = object.__new__(RemoteNodeEndpointAdapter)
    adapter.evidence_class = "authenticated_receiver_transport"
    adapter.after_dispatch_mark = lambda invocation: events.append(("fault", invocation))
    adapter._selection = lambda invocation: {"selection": invocation}
    prepared = SimpleNamespace(
        receipt=SimpleNamespace(receipt_id="prepared-receipt", request_id="prepared-request")
    )
    adapter._issue = lambda invocation, purpose, body: events.append(("issue", purpose)) or body

    def send(request):
        purpose = events[-1][1]
        events.append(("send", purpose))
        if purpose == "delivery.prepare":
            return prepared
        from runtime.remote_endpoint import RemoteTransportRejected

        raise RemoteTransportRejected("partitioned transport")

    adapter._send = send
    adapter.inspect_delivery = lambda operation_id, status: {"status": status, "receipts": []}
    adapter._projection = lambda receipts, status: {"status": status, "receipts": []}
    invocation = SimpleNamespace(
        operation_id="operation", dispatch_id="dispatch",
        runtime_dispatched_receipt_id="marker",
        model_dump=lambda mode: {"invocation": True},
    )
    envelope = SimpleNamespace(
        model_dump=lambda mode: {"envelope": True}
    )
    adapter._selection = lambda value: {"selection": True}
    adapter._factory = lambda value: None

    # Avoid the full Pydantic models; exercise the ordering seam directly by
    # replacing the constructors with shape-compatible fixtures.
    import runtime.receiver_delivery as module
    old_prepare, old_dispatch, old_logical = module.PrepareBody, module.DispatchBody, module.logical_payload
    module.PrepareBody = lambda **kwargs: SimpleNamespace(model_dump=lambda mode: kwargs)
    module.DispatchBody = lambda **kwargs: SimpleNamespace(model_dump=lambda mode: kwargs)
    module.logical_payload = lambda value: "same"
    try:
        result = adapter.deliver(
            envelope, lambda: envelope, invocation=invocation,
            mark_dispatched=lambda value, evidence: events.append(("marker", value)),
        )
    finally:
        module.PrepareBody, module.DispatchBody, module.logical_payload = old_prepare, old_dispatch, old_logical

    assert result["status"] == "uncertain"
    assert [event[0:2] for event in events] == [
        ("issue", "delivery.prepare"), ("send", "delivery.prepare"),
        ("marker", invocation), ("fault", invocation),
        ("issue", "delivery.dispatch"), ("send", "delivery.dispatch"),
    ]
