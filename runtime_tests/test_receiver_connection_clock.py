"""Adversarial receiver timing tests with independent trusted and host clocks."""
from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from nacl.signing import SigningKey
from pydantic import ValidationError

from runtime.connection_clock import ClockUnavailable, ConnectionClock
from runtime.receiver import ReceiverRejected, ReceiverService
from runtime.receiver_config import (
    BootstrapRejected,
    ReceiverClientConfig,
    receiver_clock_identity,
    resolve_connection_clock,
)
from runtime.receiver_crypto import key_fingerprint, public_key, sha256, sign, verify
from runtime.receiver_delivery import RemoteNodeEndpointAdapter
from runtime.receiver_models import (
    EndpointBinding,
    EndpointRegistration,
    PrepareBody,
    ReceiverReceipt,
    SignedReceipt,
)
from runtime.remote_endpoint import RemoteNodeTransport, RemoteTransportRejected
from runtime.sender import AdmissionFactory, DeliveryIdentity
from runtime_tests import test_receiver_protocol


class IndependentTime:
    def __init__(self):
        self.utc = datetime.now(UTC)
        self.elapsed = 0.0
        self.wall_shift = timedelta()

    def authority(self):
        return self.utc + timedelta(seconds=self.elapsed)

    def monotonic(self):
        return self.elapsed

    def wall(self):
        return self.authority() + self.wall_shift

    def clock(self, config, **bounds):
        return ConnectionClock("domain:authority:incarnation", self.authority,
                               identity=receiver_clock_identity(config),
                               monotonic=self.monotonic, wall=self.wall, **bounds)


@pytest.fixture
def temporal():
    time = IndependentTime()
    authority_key, node_key = SigningKey.generate(), SigningKey.generate()
    registration = EndpointRegistration(
        registration_id="registration", endpoint_id="endpoint", endpoint_revision=1,
        connection_ref="connection", tenant_id="tenant", authority_id="authority",
        authority_incarnation="incarnation", node_id="node", node_binding_revision=1,
        runtime_id="runtime", runtime_revision=1, machine_id="machine", boot_incarnation="boot",
        scope_id="scope", agent_slot_id="slot", tls_certificate_sha256="a" * 64,
        config_sha256="b" * 64, expires_at=time.authority() + timedelta(minutes=5),
    )
    binding = EndpointBinding(
        registration=registration, locator_host="127.0.0.1", locator_port=12345,
        route_class="loopback", node_key_id="node-key", node_public_key=public_key(node_key),
        registration_signature=sign(node_key, registration),
    )
    config = ReceiverClientConfig(
        binding=binding, authority_key_id="authority-key", authority_key_revision=1,
        authority_public_key=public_key(authority_key),
        authority_public_key_fingerprint=key_fingerprint(public_key(authority_key)),
        expected_boot_incarnation="boot", journal_generation=1,
    )
    body = PrepareBody(envelope={"message_id": "message"}, invocation={"dispatch_id": "dispatch"},
                       selection={"endpoint_id": "endpoint"})
    identity = DeliveryIdentity(
        "message", "command", "operation", "attempt", "dispatch", 1, "c" * 64,
        sha256(body.envelope), sha256(body.selection), sha256(body.invocation),
        time.authority() + timedelta(seconds=60),
    )
    return SimpleNamespace(time=time, config=config, body=body, identity=identity,
                           authority_key=authority_key, node_key=node_key)


def verifier(config, clock):
    # Exercise real packet verification without provisioning a Runtime journal.
    service = ReceiverService.__new__(ReceiverService)
    service.config, service.binding, service.clock = config, config.binding, clock
    return service


@pytest.fixture
def receiver_env(tmp_path):
    return test_receiver_protocol.env.__wrapped__(tmp_path)


def signed_receipt(state, request, observed_at):
    admission = request.admission
    values = {name: getattr(admission, name) for name in ReceiverReceipt.model_fields
              if hasattr(admission, name)}
    values.update(schema_version="acs-receiver-receipt/1", receipt_id=f"receiver:{admission.request_id}:prepared",
                  challenge_nonce=admission.nonce, state="prepared",
                  target_request_id=admission.request_id, node_binding_revision=1,
                  request_sha256=sha256({"admission": admission.model_dump(mode="json"),
                                        "body": request.body}),
                  observed_at=observed_at)
    receipt = ReceiverReceipt(**values)
    return SignedReceipt(receipt=receipt, node_key_id="node-key", signature=sign(state.node_key, receipt))


@pytest.mark.parametrize("hours", [-24, 24])
def test_sender_and_receiver_use_authority_time_across_host_skew(temporal, hours):
    temporal.time.wall_shift = timedelta(hours=hours)
    sender = temporal.time.clock(temporal.config)
    receiver = temporal.time.clock(temporal.config)
    request = AdmissionFactory(temporal.config, temporal.authority_key, temporal.identity,
                               clock=sender).request("delivery.prepare", temporal.body)
    assert request.admission.issued_at <= temporal.time.authority()
    assert abs(sender.snapshot()["offset_seconds"]) >= 23 * 3600
    assert verifier(temporal.config, receiver)._verify(request)[0] == temporal.body
    transport = RemoteNodeTransport(temporal.config, clock=sender)
    receipt = signed_receipt(temporal, request, receiver.now())
    transport.validate_receipt(request, receipt)


def test_receiver_clock_never_comes_from_remote_issued_timestamp(temporal):
    request = AdmissionFactory(temporal.config, temporal.authority_key, temporal.identity,
                               clock=temporal.time.clock(temporal.config)).request(
                                   "delivery.prepare", temporal.body)
    # issued_at is signed audit data. Authenticated time and the task's absolute
    # expiry are independent of its proximity to this host's wall clock.
    changed = request.admission.model_copy(update={
        "issued_at": temporal.time.authority() - timedelta(days=365)})
    request = request.model_copy(update={"admission": changed,
                                         "signature": sign(temporal.authority_key, changed)})
    assert verifier(temporal.config, temporal.time.clock(temporal.config))._verify(request)[0] == temporal.body


def test_cached_receipt_identity_survives_host_wall_jump_but_expiry_does_not(temporal):
    clock = temporal.time.clock(temporal.config)
    request = AdmissionFactory(temporal.config, temporal.authority_key, temporal.identity,
                               clock=clock).request("delivery.prepare", temporal.body)
    receipt = signed_receipt(temporal, request, clock.now())
    transport = RemoteNodeTransport(temporal.config, clock=clock)
    temporal.time.elapsed += 20
    temporal.time.wall_shift = timedelta(days=30)
    transport.validate_receipt(request, receipt)
    temporal.time.elapsed += 45
    with pytest.raises(RemoteTransportRejected):
        transport.validate_receipt(request, receipt)


def test_expired_authority_deadline_rejects_even_when_node_wall_is_behind(temporal):
    clock = temporal.time.clock(temporal.config)
    request = AdmissionFactory(temporal.config, temporal.authority_key, temporal.identity,
                               clock=clock).request("delivery.prepare", temporal.body)
    temporal.time.wall_shift = -timedelta(days=30)
    temporal.time.elapsed = 61
    with pytest.raises(ReceiverRejected, match="deadline"):
        verifier(temporal.config, clock)._verify(request)
    with pytest.raises(ClockUnavailable):
        AdmissionFactory(temporal.config, temporal.authority_key, temporal.identity,
                         clock=clock).request("delivery.prepare", temporal.body)


@pytest.mark.parametrize("route", ["private", "tunnel"])
def test_nonlocal_connection_requires_bound_clock_not_host_wall(temporal, route):
    config = replace(temporal.config, binding=temporal.config.binding.model_copy(update={"route_class": route}))
    config.validate()  # structural / crypto startup is independent of node time
    with pytest.raises(BootstrapRejected, match="Authority clock"):
        AdmissionFactory(config, temporal.authority_key, temporal.identity)
    with pytest.raises(BootstrapRejected, match="Authority clock"):
        RemoteNodeTransport(config)
    bound = temporal.time.clock(config)
    assert resolve_connection_clock(config, bound) is bound


def test_clock_from_other_authority_or_boot_cannot_be_reused(temporal):
    for field in ("authority_id", "authority_incarnation", "boot_incarnation", "endpoint_revision"):
        identity = {**receiver_clock_identity(temporal.config), field: "changed"}
        clock = ConnectionClock("wrong", temporal.time.authority, identity=identity,
                                monotonic=temporal.time.monotonic, wall=temporal.time.wall)
        with pytest.raises(BootstrapRejected, match="identity"):
            RemoteNodeTransport(temporal.config, clock=clock)


def test_receipt_timezone_validation_preserves_legacy_signed_offsets(temporal):
    request = AdmissionFactory(temporal.config, temporal.authority_key, temporal.identity,
                               clock=temporal.time.clock(temporal.config)).request(
                                   "delivery.prepare", temporal.body)
    offset = temporal.time.authority().astimezone(timezone(timedelta(hours=9)))
    receipt = signed_receipt(temporal, request, offset)
    encoded = receipt.model_dump_json()
    restored = SignedReceipt.model_validate_json(encoded, strict=True)
    assert restored.model_dump_json() == encoded
    assert "+09:00" in encoded
    verify(public_key(temporal.node_key), restored.signature, restored.receipt)
    with pytest.raises(ValidationError):
        ReceiverReceipt.model_validate({**receipt.receipt.model_dump(),
                                        "observed_at": offset.replace(tzinfo=None)})


def test_uncertain_clock_rejects_before_receiver_packet_is_admitted(temporal):
    def slow_reference():
        temporal.time.elapsed += 5
        return temporal.time.authority()
    clock = ConnectionClock("authority", slow_reference,
                            identity=receiver_clock_identity(temporal.config),
                            monotonic=temporal.time.monotonic, wall=temporal.time.wall)
    with pytest.raises(BootstrapRejected, match="time"):
        RemoteNodeTransport(temporal.config, clock=clock)


@pytest.mark.skipif(os.name == "nt", reason="POSIX receiver journal fixture")
def test_journal_replay_and_native_fence_survive_wall_jump(receiver_env):
    from runtime_tests.test_receiver_protocol import dispatch_request

    env = receiver_env
    time = IndependentTime()
    clock = time.clock(env.config)
    factory = AdmissionFactory(env.config, env.authority_key, env.identity, clock=clock)
    service = ReceiverService(env.config, env.node_key, authorize_current=lambda _admission: True,
                              clock=clock)
    service.claim_boot("boot-1", 1)
    prepared = factory.request("delivery.prepare", env.prepare_body)
    first = service.prepare(prepared)
    time.wall_shift = timedelta(days=100)
    assert service.prepare(prepared) == first
    dispatch = dispatch_request(SimpleNamespace(factory=factory), prepared)
    calls = []

    def jump_wall(_admission):
        time.wall_shift = -timedelta(days=100)
        calls.append("native")
        return {"called": len(calls)}

    result = service.dispatch(dispatch, jump_wall)
    assert result.receipt.state == "runtime_acknowledged"
    assert service.dispatch(dispatch, lambda _admission: calls.append("replay")) == result
    assert calls == ["native"]
    assert "monotonic" not in json.dumps(result.receipt.evidence["connection_clock"])



def test_private_connection_cannot_use_local_reference_with_matching_metadata(temporal):
    config = replace(temporal.config, binding=temporal.config.binding.model_copy(
        update={"route_class": "private"}))
    clock = ConnectionClock.local(reference=temporal.time.authority,
                                  identity=receiver_clock_identity(config),
                                  monotonic=temporal.time.monotonic, wall=temporal.time.wall)
    with pytest.raises(BootstrapRejected, match="Authority identity"):
        RemoteNodeTransport(config, clock=clock)


def test_execution_lease_uses_monotonic_and_stops_at_endpoint_expiry(temporal, monkeypatch):
    from runtime import receiver

    registration = temporal.config.binding.registration.model_copy(
        update={"expires_at": temporal.time.authority() + timedelta(seconds=5)})
    binding = temporal.config.binding.model_copy(
        update={"registration": registration, "registration_signature": sign(temporal.node_key, registration)})
    config = replace(temporal.config, binding=binding)
    clock = temporal.time.clock(config)
    request = AdmissionFactory(config, temporal.authority_key, temporal.identity,
                               clock=clock).request("delivery.prepare", temporal.body)
    service = verifier(config, clock)
    monkeypatch.setattr(receiver, "_process_start", lambda _pid: "same-process-birth")
    row = {"execution_lease_id": "local-lease", "execution_lease_expires_at": "audit-only",
           "execution_process_id": os.getpid(), "execution_process_start": "same-process-birth",
           "admitted_boot": "boot", "journal_generation": 1}
    with service._lease(request, "local-lease"):
        temporal.time.wall_shift = timedelta(days=100)
        temporal.time.elapsed = 4
        assert service._execution_lease_active(row)
        temporal.time.wall_shift = -timedelta(days=100)
        temporal.time.elapsed = 6
        assert not service._execution_lease_active(row)
    assert "local-lease" not in receiver._ACTIVE_EXECUTION_LEASES

def test_private_clock_requires_every_connection_identity_field(temporal):
    config = replace(temporal.config, binding=temporal.config.binding.model_copy(
        update={"route_class": "private"}))
    identity = receiver_clock_identity(config)
    for missing in identity:
        incomplete = {name: value for name, value in identity.items() if name != missing}
        clock = ConnectionClock("domain:authority:incarnation", temporal.time.authority,
                                identity=incomplete, monotonic=temporal.time.monotonic,
                                wall=temporal.time.wall)
        with pytest.raises(BootstrapRejected, match="identity"):
            RemoteNodeTransport(config, clock=clock)

@pytest.mark.skipif(os.name == "nt", reason="POSIX receiver journal fixture")
def test_default_readiness_lifetime_accounts_for_producer_uncertainty(receiver_env):
    from runtime.receiver_models import ReadinessBody

    env = receiver_env
    time = IndependentTime()

    def reference_at_reply():
        time.elapsed += 1
        return time.authority()

    clock = ConnectionClock("domain:authority:incarnation", reference_at_reply,
                            identity=receiver_clock_identity(env.config),
                            monotonic=time.monotonic, wall=time.wall)
    factory = AdmissionFactory(env.config, env.authority_key, env.identity, clock=clock)
    service = ReceiverService(env.config, env.node_key, authorize_current=lambda _admission: True,
                              clock=clock)
    service.claim_boot("boot-1", 1)
    prepared = factory.request("delivery.prepare", env.prepare_body)
    service.prepare(prepared)
    request = factory.request("delivery.readiness", ReadinessBody(
        prepare_request_id=prepared.admission.request_id))
    result = service.readiness(request, None)
    observed = result.receipt.evidence
    assert clock.reading().uncertainty_seconds >= 0.5
    assert datetime.fromisoformat(observed["expires_at"]) <= time.authority() + timedelta(seconds=2)
    assert datetime.fromisoformat(observed["observed_at"]) <= time.authority()


@pytest.mark.parametrize("route", ["private", "tunnel"])
def test_recovery_readback_uses_bound_authority_clock_across_host_skew(temporal, route):
    config = replace(temporal.config, binding=temporal.config.binding.model_copy(
        update={"route_class": route}))
    temporal.time.wall_shift = timedelta(days=-30)
    clock = temporal.time.clock(config)
    dispatch = AdmissionFactory(config, temporal.authority_key, temporal.identity,
                                clock=clock).request("delivery.prepare", temporal.body)
    captured = []
    adapter = RemoteNodeEndpointAdapter.__new__(RemoteNodeEndpointAdapter)
    adapter.config, adapter.clock, adapter._signing_key = config, clock, temporal.authority_key
    adapter.store = SimpleNamespace(dispatch_admission=lambda _operation: dispatch,
                                    admission=lambda _request: None,
                                    persist_admission=captured.append)

    def send(request):
        receipt = signed_receipt(temporal, request, clock.now()).receipt.model_copy(
            update={"state": "readback", "receipt_id": f"receiver:{request.admission.request_id}:readback",
                    "readback_request_id": request.admission.request_id,
                    "target_request_id": dispatch.admission.request_id,
                    "evidence": {"stored_state": "runtime_acknowledged",
                                 "target_request_id": dispatch.admission.request_id}})
        signed = SignedReceipt(receipt=receipt, node_key_id="node-key",
                               signature=sign(temporal.node_key, receipt))
        RemoteNodeTransport(config, clock=clock).validate_receipt(request, signed)
        return signed

    adapter._send = send
    result = adapter.inspect_delivery("operation")
    assert result["status"] == "delivered"
    assert captured[0].admission.purpose == "delivery.readback"
    assert captured[0].admission.issued_at <= temporal.time.authority()
    verify(public_key(temporal.authority_key), captured[0].signature, captured[0].admission)


@pytest.mark.skipif(os.name == "nt", reason="POSIX receiver journal fixture")
def test_slow_producer_receipt_is_fresh_for_fast_consumer(receiver_env):
    env = receiver_env
    time = IndependentTime()
    def reference_at_reply():
        time.elapsed += 0.6
        return time.authority()
    producer = ConnectionClock("domain:authority:incarnation", reference_at_reply,
                               identity=receiver_clock_identity(env.config),
                               monotonic=time.monotonic, wall=time.wall)
    consumer = time.clock(env.config)
    factory = AdmissionFactory(env.config, env.authority_key, env.identity, clock=consumer)
    service = ReceiverService(env.config, env.node_key, authorize_current=lambda _admission: True,
                              clock=producer)
    service.claim_boot("boot-1", 1)
    request = factory.request("delivery.prepare", env.prepare_body)
    receipt = service.prepare(request)
    assert receipt.receipt.observed_at <= time.authority()
    RemoteNodeTransport(env.config, clock=consumer).validate_receipt(request, receipt)
