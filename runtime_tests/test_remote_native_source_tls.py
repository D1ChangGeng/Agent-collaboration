"""TLS wire composition of the real original Native provenance readback."""
from __future__ import annotations

import socket
import threading
from dataclasses import replace

import pytest

from runtime.remote_endpoint import ReceiverHTTPServer, RemoteNodeTransport, RemoteTransportRejected
from runtime_tests.test_receiver_evidence_native import receiver as receiver_fixture
from runtime_tests.test_remote_native_source import completed
from runtime_tests.test_signed_harness_adapter import signed as signed_fixture

receiver = receiver_fixture
signed = signed_fixture


@pytest.mark.parametrize("original_input_revoked", [False, True])
def test_existing_receiver_tls_route_returns_original_refs_without_invocation(signed, original_input_revoked):
    request = completed(signed)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    config = replace(signed.service.config, binding=signed.service.binding.model_copy(update={"locator_port": port}))
    signed.service.ledger.close()

    class OwnedHost:
        def native_invoke(self, _admission):
            raise AssertionError("source read cannot invoke Native")

        def read_native_source(self, admission, provider):
            return signed.bridge.read_native_source(admission, provider)

    owner = OwnedHost()
    reading = [True]
    server = ReceiverHTTPServer(config, signed.node_key, lambda _admission: signed.state.authorized, owner.native_invoke,
                                authorize_source_read=lambda _admission: reading[0])
    signed.state.authorized = not original_input_revoked
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        transport = RemoteNodeTransport(config, clock=server.service.clock)
        value = transport.send(request).receipt.evidence["native_source"]
        assert value["available"]
        assert value["value"]["operationId"] == signed.invocation.operation_id
        assert value["value"]["nativeSession"]["providerRef"] == "trusted-remote-original"
        reading[0] = False
        with pytest.raises(RemoteTransportRejected):
            transport.send(request)  # A cached source is also withheld after current read revocation.
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
        server.service.ledger.close()
        assert not thread.is_alive()
