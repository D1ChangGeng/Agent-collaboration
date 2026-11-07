"""Actual Receiver TLS/HTTP with signed lifecycle wire and controlled Native APIs.

No model/Native process/PG is contacted. Authority clocks and Native protocol
responses are fixtures. This qualifies local transport, not a real Harness.
"""
from __future__ import annotations

import os
import threading
from dataclasses import fields, replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from runtime.receiver_config import ReceiverClientConfig, ReceiverRuntimeConfig
from runtime.receiver_crypto import sign
from runtime.receiver_lifecycle_transport import EXECUTE, RemoteLifecycleTransport
from runtime.remote_endpoint import ReceiverHTTPServer, RemoteNodeTransport, RemoteTransportRejected
from runtime_tests.probe_receiver_windows_backend import private_root
from runtime_tests.test_receiver_lifecycle_capacity import capacity as capacity_fixture
from runtime_tests.test_receiver_lifecycle_node import node as node_fixture
from runtime_tests.test_receiver_protocol import certificate, free_port

capacity, node = capacity_fixture, node_fixture


@pytest.fixture
def wire(node, tmp_path, request):
    n = node
    private = tmp_path / "receiver-private"
    if os.name == "nt":
        private_root(private)
    else:
        private.mkdir(mode=0o700)
    cert, key, fingerprint = certificate(private)
    node_key = private / "node-key.seed"
    node_key.write_text(n.node_key.encode().hex(), encoding="ascii")
    node_key.chmod(0o600)
    registration = n.config.binding.registration.model_copy(update={"tls_certificate_sha256": fingerprint})
    binding = n.config.binding.model_copy(update={"registration": registration, "locator_port": free_port(),
        "registration_signature": sign(n.node_key, registration)})
    config = replace(n.config, binding=binding)
    # The test constructs the actual listener's declared public transport binding
    # before any lifecycle request; Native/Driver identity stays unchanged.
    n.config = n.controller.config = config
    n.snapshot = replace(n.snapshot, binding=binding)
    values = {field.name: getattr(config, field.name) for field in fields(ReceiverClientConfig)}
    drop = EXECUTE if getattr(request, "param", None) == "drop" else None
    runtime = ReceiverRuntimeConfig(**values, tls_cert_path=str(cert), tls_key_path=str(key),
        node_signing_key_path=str(node_key), ledger_path=str(private / "receiver.sqlite"),
        drop_response_after_commit_once=drop)

    def forbidden(*_args):
        pytest.fail("ordinary delivery or unfenced Native callback was entered")

    server = ReceiverHTTPServer(runtime, n.node_key, forbidden, forbidden, clock=n.clock, lifecycle_node=n.controller)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    worker.start()
    try:
        server.verify_presented_certificate()
        remote = RemoteNodeTransport(config, timeout=5, clock=n.clock)
        yield SimpleNamespace(node=n, server=server, remote=remote, client=RemoteLifecycleTransport(remote, n.key))
    finally:
        server.shutdown()
        worker.join(timeout=6)
        assert not worker.is_alive()
        server.server_close()


def test_real_tls_observe_execute_and_fresh_late_readback_preserve_original_operation(wire):
    n, client = wire.node, wire.client
    n.prepare()
    observed = client.observe(n.challenge)
    assert observed.observation.capacity.state == "fresh" and n.effects == []
    result = client.execute(n.permit, challenge=n.challenge, observation=n.observation)
    assert result.receipt.outcome == "acknowledged" and n.effects == ["spawn"]
    before = len(n.native_calls)
    n.driver_time.now += timedelta(minutes=1)
    n.monotonic[0] += 60
    n.core_allowed = False  # A past ACK is read under its separate current-read hook.
    history = client.readback(n.permit, challenge=n.challenge, observation=n.observation)
    assert history.receipt.native_session_ref == result.receipt.native_session_ref
    assert history.receipt.provider_generation == result.receipt.provider_generation
    assert len(n.native_calls) == before and n.effects == ["spawn"]


@pytest.mark.parametrize("wire", ["drop"], indirect=True)
def test_lost_tls_ack_uses_original_journal_readback_with_no_second_native_call(wire):
    n = wire.node
    n.prepare()
    with pytest.raises(RemoteTransportRejected):
        wire.client.execute(n.permit, challenge=n.challenge, observation=n.observation)
    assert n.effects == ["spawn"]
    before = len(n.native_calls)
    recovered = wire.client.readback(n.permit, challenge=n.challenge, observation=n.observation)
    assert recovered.receipt.outcome == "acknowledged" and len(n.native_calls) == before


def test_real_tls_pin_mismatch_stops_before_controller_or_native_state(wire):
    n = wire.node
    n.prepare()
    wrong = n.config.binding.registration.model_copy(update={"tls_certificate_sha256": "0" * 64})
    binding = n.config.binding.model_copy(update={"registration": wrong, "registration_signature": sign(n.node_key, wrong)})
    remote = RemoteNodeTransport(replace(n.config, binding=binding), timeout=3, clock=n.clock)
    client = RemoteLifecycleTransport(remote, n.key)
    with pytest.raises(RemoteTransportRejected):
        client.observe(n.challenge.model_copy(update={"challenge": n.challenge.challenge.model_copy(update={
            "target": n.challenge.challenge.target.model_copy(update={"registration": wrong})})}))
    assert n.effects == []


def test_current_original_read_denial_is_private_wire_rejection_without_resend(wire):
    n = wire.node
    n.prepare()
    wire.client.execute(n.permit, challenge=n.challenge, observation=n.observation)
    n.read_allowed = False
    before = len(n.native_calls)
    with pytest.raises(RemoteTransportRejected):
        wire.client.readback(n.permit, challenge=n.challenge, observation=n.observation)
    assert len(n.native_calls) == before and n.effects == ["spawn"]
