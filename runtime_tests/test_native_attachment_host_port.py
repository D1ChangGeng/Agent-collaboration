"""Signed Receiver/SQLite Host-port conformance with controlled callbacks.

These tests do not run a model or qualify an installed desktop. The original
signature, preparation, marker, replay and default attachment-denial paths are
the actual Core implementations.
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from runtime.delivery_node import invocation_for
from runtime.native_attachment_delivery import native_attachment_delivery_supported
from runtime.orca_receiver_backend import ExistingOrcaReceiverBackend, OrcaReceiverRouter
from runtime.receiver_crypto import sha256
from runtime.receiver_delivery import RemoteNodeEndpointAdapter
from runtime.delivery_node import InvocationDeferred, InvocationPreCallRejected
from runtime.remote_endpoint import RemotePeerChanged, RemoteTransportRejected
from runtime.receiver_models import DispatchBody, PrepareBody, ReadinessBody
from runtime.sender import AdmissionFactory, DeliveryIdentity
from runtime_tests.test_attachment_native_guards import envelope
from runtime_tests.test_attachment_native_guards import signed as signed_fixture

signed = signed_fixture


def host_port(f, enabled):
    registration = f.config.binding.registration
    value = envelope(attached=True)
    invocation = invocation_for(value, "attempt")
    selection = {"endpoint_id": value.endpoint_id, "binding_revision": value.binding_revision,
        "machine_id": value.machine_id, "node_id": value.node_id, "boot_incarnation": value.boot_incarnation,
        "target_scope_id": value.packet.target_scope_id, "target_agent_slot_id": value.packet.target_agent_slot_id}
    body = PrepareBody(envelope=value.model_dump(mode="json"), invocation=invocation.model_dump(mode="json"), selection=selection)
    identity = DeliveryIdentity(invocation.message_id, invocation.command_id, invocation.operation_id, invocation.attempt_id,
        invocation.dispatch_id, invocation.accepted_revision, invocation.accepted_state_digest, invocation.envelope_digest,
        invocation.selection_digest, sha256(invocation.model_dump(mode="json")), f.time.authority() + timedelta(minutes=1))
    factory = AdmissionFactory(f.config, f.authority_key, identity, clock=f.service.clock)
    owner = {"receiverRef": registration.endpoint_id, "address": value.packet.recipient,
        "bindingEpoch": registration.endpoint_revision, "hostPrincipalRef": "fixture:host",
        "authorityId": registration.authority_id, "authorityIncarnation": registration.authority_incarnation,
        "scopeRef": registration.scope_id, "inputOwner": "orca", "ownerToken": object(),
        "session": {"providerRef": "fixture:provider", "sessionRef": "fixture:original-session",
            "hostRef": registration.machine_id, "generation": "fixture:original-generation", "authority": "orca"}}
    backend = ExistingOrcaReceiverBackend(f.service, current_ownership=lambda: owner,
        authorize_original_read=lambda _admission: None, native_attachments=enabled)
    request = factory.request("delivery.prepare", body)
    backend.prepare(request)
    return backend, factory, request


@pytest.mark.parametrize("value", [None, True, {"endpoint": True}, ["endpoint"], set()])
def test_only_a_trusted_installed_endpoint_registry_admits_native_attachments(value):
    authority = SimpleNamespace(_native_attachment_delivery_endpoints=value)
    assert not native_attachment_delivery_supported(authority, "endpoint")
    authority._native_attachment_delivery_endpoints = {"endpoint"}
    assert native_attachment_delivery_supported(authority, "endpoint")
    assert not native_attachment_delivery_supported(authority, "other-endpoint")


def test_installed_host_port_uses_signed_original_attachment_preparation_and_one_input(signed):
    backend, factory, prepared = host_port(signed, True)
    calls, probes = [], []

    def observe(_admission):
        probes.append(True)
        now = signed.time.authority()
        return {"activity": "idle", "observed_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=2)).isoformat(), "source": "controlled-host-port"}

    def admit(original):
        backend.assert_current(original)
        command = original["command"]
        calls.append(command["operation_id"])
        return {"schema_version": "acs-adapter/1", "operation_id": command["operation_id"],
            "outcome": "accepted", "effect_possible": True, "evidence_ref": "fixture:actual-port-callback",
            "native_input_ref": "fixture:original-input", "binding_epoch": command["binding_epoch"],
            "provider_generation": command["provider_generation"], "reason_code": None}

    router = OrcaReceiverRouter(backend, admit_original=admit, observe_readiness=observe)
    readiness = factory.request("delivery.readiness", ReadinessBody(prepare_request_id=prepared.admission.request_id))
    assert router.handle(readiness).receipt.evidence["activity"] == "idle" and probes == [True]
    request = factory.request("delivery.dispatch", DispatchBody(prepare_request_id=prepared.admission.request_id,
        marker_receipt_id="fixture:domain-marker"))
    result = router.handle(request)
    assert result.receipt.state == "runtime_acknowledged" and len(calls) == 1
    assert router.handle(request) == result and len(calls) == 1


def test_later_port_enablement_does_not_rewrite_an_original_preparation(signed):
    backend, factory, prepared = host_port(signed, False)
    backend.native_attachments = True
    router = OrcaReceiverRouter(backend, admit_original=lambda _original: pytest.fail("unattested attachment invoked"),
        observe_readiness=lambda _admission: pytest.fail("unattested attachment probed"))
    request = factory.request("delivery.dispatch", DispatchBody(prepare_request_id=prepared.admission.request_id,
        marker_receipt_id="fixture:domain-marker"))
    result = router.handle(request)
    assert result.receipt.state == "blocked"
    assert result.receipt.evidence["reason"] == "native_attachment_delivery_unsupported"


def test_remote_sender_reaches_installed_port_only_after_original_signed_preparation(signed):
    backend, factory, prepared = host_port(signed, True)
    endpoint = object.__new__(RemoteNodeEndpointAdapter)
    endpoint.store = SimpleNamespace(dispatch_admission=lambda _operation: None)
    def original_prepare(_invocation, purpose, body):
        assert purpose == "delivery.prepare" and body.model_dump(mode="json") == prepared.body
        return prepared

    endpoint._issue = original_prepare
    endpoint._send = backend.prepare
    entered = []

    class PreparedPortReached(Exception):
        pass

    def after_prepare(_invocation, receipt):
        assert receipt.receipt.evidence["adapter_receiver"]["orca_native_attachments"] is True
        entered.append(True)
        raise PreparedPortReached

    endpoint.after_prepare = after_prepare
    from runtime.delivery_models import InvocationRequest

    invocation = InvocationRequest.model_validate(prepared.body["invocation"])
    with pytest.raises(PreparedPortReached):
        endpoint.deliver(invocation.envelope, lambda: invocation.envelope, invocation,
            lambda *_args: pytest.fail("controlled test stops before the Domain marker"), lambda _invocation: False)
    assert entered == [True]


@pytest.mark.parametrize("peer_changed", [False, True])
def test_prepare_timeout_defers_original_request_but_peer_change_stays_rejected(signed, peer_changed):
    _backend, _factory, prepared = host_port(signed, True)
    from runtime.delivery_models import InvocationRequest

    invocation = InvocationRequest.model_validate(prepared.body["invocation"])
    endpoint = object.__new__(RemoteNodeEndpointAdapter)
    endpoint.store = SimpleNamespace(dispatch_admission=lambda _operation: None)
    endpoint._issue = lambda *_args: prepared

    def unavailable(_request):
        try:
            raise TimeoutError("controlled cold preparation wait")
        except TimeoutError as error:
            raise (RemotePeerChanged("controlled changed peer") if peer_changed
                   else RemoteTransportRejected("controlled unavailable response")) from error

    endpoint._send = unavailable
    with pytest.raises(InvocationPreCallRejected) as refusal:
        endpoint.deliver(invocation.envelope, lambda: invocation.envelope, invocation,
            lambda *_args: pytest.fail("preparation failure cannot mark Native dispatch"), lambda _invocation: False)
    assert isinstance(refusal.value, InvocationDeferred) is not peer_changed
