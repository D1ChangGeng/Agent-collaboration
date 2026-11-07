"""Signed receiver/Driver conformance with real journals and synthetic Native peers.

Policy observations and the Domain marker callback are explicitly synthetic. The
receiver signature, canonical-input checks, private path admission and SQLite
dispatch fence are the actual implementations; no model or production contact
is used.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from nacl.signing import SigningKey

from runtime.codex_driver import AuthorizedOperation, DriverRejected
from runtime.delivery_models import DeliveryEnvelope, MessagePacket
from runtime.delivery_node import invocation_for
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.receiver import ReceiverRejected, ReceiverService
from runtime.receiver_config import ReceiverRuntimeConfig
from runtime.receiver_contract import (
    NativeAdmissionCommand,
    ReceiverBinding,
    ReceiverSnapshot,
    SealedEnvelope,
    native_generation,
)
from runtime.receiver_crypto import key_fingerprint, public_key, sha256, sign, verify
from runtime.receiver_delivery import ReceiverNativeDeliveryBridge
from runtime.receiver_models import (
    DispatchBody,
    EndpointBinding,
    EndpointRegistration,
    PrepareBody,
)
from runtime.sender import AdmissionFactory, DeliveryIdentity
from runtime.signed_harness_adapter import SignedHarnessAdapter
from runtime_tests.probe_receiver_windows_backend import certificate, private_root
from runtime_tests.test_native_handoff import mutations
from runtime_tests.test_receiver_contract import snapshot
from runtime_tests.test_receiver_evidence_native import receiver as receiver_fixture

receiver = receiver_fixture
REAL_POPEN = subprocess.Popen


@pytest.fixture
def signed(receiver, tmp_path, monkeypatch):
    _module, native, _unused_adapter, _unused_binding = receiver
    driver = native.driver
    # The Codex wire fixture replaces global Popen for its synthetic launch.
    # That launch is complete; restore the real process primitive so Windows
    # ACL admission below executes icacls instead of the synthetic wire peer.
    monkeypatch.setattr(subprocess, "Popen", REAL_POPEN)
    private = tmp_path / "signed-receiver"
    if os.name == "nt":
        private_root(private)
    else:
        private.mkdir(mode=0o700)
    cert, tls_key, cert_hash = certificate(private)
    authority_key, node_key = SigningKey.generate(), SigningKey.generate()
    node_seed = private / "node.seed"
    node_seed.write_text(node_key.encode().hex(), encoding="ascii")
    if os.name == "posix":
        for path in (cert, tls_key, node_seed):
            path.chmod(0o600)
    identity = driver.identity
    registration = EndpointRegistration(registration_id="fixture-registration", endpoint_id="fixture-receiver",
        endpoint_revision=3, connection_ref="fixture-connection", tenant_id="fixture-tenant",
        authority_id="fixture-authority", authority_incarnation="fixture-incarnation", node_id=identity.node_id,
        node_binding_revision=identity.revision, runtime_id=identity.runtime_id, runtime_revision=1,
        machine_id="fixture-host", boot_incarnation=identity.node_boot_id, scope_id="fixture-scope",
        agent_slot_id=identity.agent_slot_id, tls_certificate_sha256=cert_hash, config_sha256="a" * 64)
    endpoint = EndpointBinding(registration=registration, locator_host="127.0.0.1", locator_port=44321,
        route_class="loopback", node_key_id="fixture-node-key", node_public_key=public_key(node_key),
        registration_signature=sign(node_key, registration))
    config = ReceiverRuntimeConfig(binding=endpoint, authority_key_id="fixture-authority-key", authority_key_revision=1,
        authority_public_key=public_key(authority_key), authority_public_key_fingerprint=key_fingerprint(public_key(authority_key)),
        expected_boot_incarnation=identity.node_boot_id, journal_generation=1,
        tls_cert_path=str(cert), tls_key_path=str(tls_key), node_signing_key_path=str(node_seed),
        ledger_path=str(private / "receiver.sqlite"), access_mode="owner")
    state = SimpleNamespace(authorized=True, readiness="ready", blocker="none", probes=0)

    def current_binding():
        session = driver.thread_id if driver.harness == "codex" else driver.session_id
        return ReceiverBinding(receiver_id=registration.endpoint_id,
            actor_address="collaborator:fixture-project:" + identity.agent_slot_id,
            binding_epoch=registration.endpoint_revision,
            provider_generation=native_generation(driver.binding_id, asdict(driver.identity), session),
            native_session_ref=session, authority_id=registration.authority_id,
            authority_incarnation=registration.authority_incarnation, execution_host_ref=registration.machine_id)

    def authorize_binding(binding):
        return state.authorized and (binding.receiver_id, binding.actor_address, binding.binding_epoch,
            binding.authority_id, binding.authority_incarnation, binding.execution_host_ref) == (
            registration.endpoint_id, "collaborator:fixture-project:" + identity.agent_slot_id, registration.endpoint_revision,
            registration.authority_id, registration.authority_incarnation, registration.machine_id)

    def authorize_invocation(invocation, observed):
        if not state.authorized or observed != identity:
            raise DriverRejected("synthetic receiver authorization revoked")
        return AuthorizedOperation(invocation.invocation_id, invocation.command_id, invocation.message_id,
                                   "fixture-native-grant", invocation.envelope.packet.deadline)

    adapter = NativeDeliveryAdapter(driver, authorize_invocation=authorize_invocation, record_handoff=True)

    def observe(binding):
        state.probes += 1
        current = current_binding()
        item = snapshot(readiness=state.readiness, blocker=state.blocker)
        now, expiry = datetime.now(UTC), datetime.now(UTC) + timedelta(seconds=2)
        return item.model_copy(update={"receiver_id": binding.receiver_id, "address": binding.actor_address,
            "binding_epoch": binding.binding_epoch, "revision": binding.binding_epoch,
            "native_session_ref": current.native_session_ref,
            "capability_scope": item.capability_scope.model_copy(update={
                "harness_kind": driver.harness, "harness_version": driver.profile.version,
                "execution_host_ref": binding.execution_host_ref, "connection_epoch": binding.binding_epoch,
                "provider_generation": current.provider_generation}),
            "capabilities": tuple(c.model_copy(update={"valid_until": expiry}) for c in item.capabilities),
            "observations": tuple(o.model_copy(update={"observed_at": now, "expires_at": expiry,
                "binding_epoch": binding.binding_epoch, "provider_generation": current.provider_generation}) for o in item.observations)})

    monkeypatch.setattr(adapter, "receiver_snapshot", observe)
    service = ReceiverService(config, node_key, authorize_current=lambda _admission: state.authorized)
    service.claim_boot(config.expected_boot_incarnation, config.journal_generation)
    bridge = ReceiverNativeDeliveryBridge(config.ledger_path, adapter, read_domain_marker=lambda _invocation: True)
    facade = SignedHarnessAdapter(service, bridge, authorize_binding=authorize_binding, binding_provider=current_binding)
    packet = MessagePacket(project_id="fixture-project", sender="collaborator:fixture-project:a",
        recipient=current_binding().actor_address, content="Synthetic signed message; no model is called",
        target_scope_id=registration.scope_id, target_agent_slot_id=registration.agent_slot_id)
    envelope = DeliveryEnvelope(tenant_id=registration.tenant_id, authority_id=registration.authority_id,
        authority_incarnation=registration.authority_incarnation, principal_ref="fixture-sender", grant_ref="fixture-send-grant",
        message_id="fixture-message", command_id="fixture-command", operation_id="fixture-core-operation",
        endpoint_id=registration.endpoint_id, binding_revision=registration.endpoint_revision,
        machine_id=registration.machine_id, node_id=registration.node_id, boot_incarnation=registration.boot_incarnation,
        accepted_state_digest="a" * 64, packet=packet)
    invocation = invocation_for(envelope, "fixture-attempt")
    selection = {"endpoint_id": envelope.endpoint_id, "binding_revision": envelope.binding_revision,
        "machine_id": envelope.machine_id, "node_id": envelope.node_id, "boot_incarnation": envelope.boot_incarnation,
        "target_scope_id": packet.target_scope_id, "target_agent_slot_id": packet.target_agent_slot_id}
    body = PrepareBody(envelope=envelope.model_dump(mode="json"), invocation=invocation.model_dump(mode="json"), selection=selection)
    assert sha256(body.envelope) == invocation.envelope_digest
    assert sha256(body.selection) == invocation.selection_digest
    delivery = DeliveryIdentity(invocation.message_id, invocation.command_id, invocation.operation_id,
        invocation.attempt_id, invocation.dispatch_id, invocation.accepted_revision, invocation.accepted_state_digest,
        invocation.envelope_digest, invocation.selection_digest, sha256(body.invocation), None)
    factory = AdmissionFactory(config, authority_key, delivery)
    prepare = factory.request("delivery.prepare", body)
    value = SimpleNamespace(native=native, driver=driver, state=state, service=service, adapter=adapter, bridge=bridge,
        facade=facade, binding=current_binding(), current_binding=current_binding, factory=factory, prepare=prepare,
        invocation=invocation, node_key=node_key, authority_key=authority_key)
    try:
        yield value
    finally:
        service.ledger.close()


def run(awaitable):
    return asyncio.run(awaitable)


def prepare_command(f):
    prepared = run(f.facade.prepare_input(f.prepare, f.binding))
    verify(public_key(f.node_key), prepared.signature, prepared.receipt)
    assert prepared.receipt.state == "prepared"
    fact = prepared.receipt.evidence["adapter_receiver"]
    assert fact["provider_generation"] == f.binding.provider_generation
    request = f.factory.request("delivery.dispatch", DispatchBody(prepare_request_id=f.prepare.admission.request_id,
                                                                marker_receipt_id="synthetic-domain-marker"))
    context = f.adapter._handoff_context(f.invocation, f.adapter._operation(f.invocation))
    command = NativeAdmissionCommand(schema_version="acs-adapter/1", operation_id=f.invocation.invocation_id,
        receiver_id=f.binding.receiver_id, message_handles=("message:fixture-project:fixture-message",),
        canonical_hash=f.invocation.envelope_digest, binding_epoch=f.binding.binding_epoch,
        provider_generation=f.binding.provider_generation, auth_revision=context.auth_revision, input_mode="structured",
        sealed_envelope=SealedEnvelope(format="acs-delivery-admission/1", encoding="base64",
            data=base64.b64encode(request.model_dump_json().encode()).decode()), deadline=request.admission.deadline)
    return command


def markers(f):
    with f.service.ledger.connect() as connection:
        return connection.execute("SELECT count(*) FROM receiver_requests WHERE local_dispatch_marker=1").fetchone()[0]


def rejected(awaitable):
    try:
        result = run(awaitable)
    except (ReceiverRejected, ValueError, PermissionError):
        return
    assert result.outcome in {"unknown", "unsupported", "definitively_not_admitted"}


def test_signed_prepare_admission_replay_and_reconcile_use_one_original_native_input(signed):
    f = signed
    command = prepare_command(f)
    assert command.operation_id != f.prepare.admission.operation_id  # Native and Core operations are distinct.
    first = run(f.facade.admit_input(command))
    assert first.outcome == "accepted" and first.effect_possible and first.evidence_ref
    assert first.operation_id == f.invocation.invocation_id
    assert mutations(f.native) == markers(f) == 1
    replay = run(f.facade.admit_input(command))
    assert replay.outcome == "accepted" and mutations(f.native) == markers(f) == 1
    assert run(f.facade.reconcile(command.operation_id, f.binding)).outcome == "accepted"
    assert mutations(f.native) == 1


@pytest.mark.parametrize("field,value", [("operation_id", "another-native-operation"),
    ("receiver_id", "another-receiver"), ("canonical_hash", "b" * 64), ("binding_epoch", 4),
    ("provider_generation", "retired-provider"), ("auth_revision", "forged-revision"),
    ("message_handles", ("message:other-project:secret",))])
def test_outer_fields_cannot_override_protected_prepared_input(signed, field, value):
    f = signed
    command = prepare_command(f).model_copy(update={field: value})
    rejected(f.facade.admit_input(command))
    assert mutations(f.native) == markers(f) == 0


def test_forged_authority_signature_never_reaches_native(signed):
    f = signed
    command = prepare_command(f)
    body = json.loads(base64.b64decode(command.sealed_envelope.data))
    body["signature"] = "0" * 128
    forged = command.model_copy(update={"sealed_envelope": command.sealed_envelope.model_copy(update={
        "data": base64.b64encode(json.dumps(body).encode()).decode()})})
    rejected(f.facade.admit_input(forged))
    assert mutations(f.native) == markers(f) == 0


@pytest.mark.parametrize("readiness,blocker", [("busy", "none"), ("ready", "approval"),
    ("ready", "question"), ("ready", "user_draft"), ("ready", "paused")])
def test_busy_or_human_input_blockers_defer_before_native_marker(signed, readiness, blocker):
    f = signed
    command = prepare_command(f)
    f.state.readiness, f.state.blocker = readiness, blocker
    result = run(f.facade.admit_input(command))
    assert result.outcome == "definitively_not_admitted" and not result.effect_possible
    assert result.evidence_ref and mutations(f.native) == markers(f) == 0


@pytest.mark.parametrize("mode", ["safe_queue", "terminal_pointer"])
def test_unsupported_input_modes_do_not_type_into_a_terminal(signed, mode):
    f = signed
    command = prepare_command(f).model_copy(update={"input_mode": mode})
    result = run(f.facade.admit_input(command))
    assert result.outcome == "unsupported" and not result.effect_possible
    assert mutations(f.native) == markers(f) == 0


def test_unknown_dispatch_marker_never_causes_another_native_call(signed, monkeypatch):
    f = signed
    command = prepare_command(f)
    if f.driver.harness == "codex":
        f.native.state["drop_invoke_ack"] = True
    else:
        f.native.peer.drop_prompt_ack = True
    original = f.adapter.invoke

    def lose_readback(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        finally:
            if f.driver.harness == "codex":
                f.native.state["turns"] = []
            else:
                f.native.peer.hide_message = True

    monkeypatch.setattr(f.adapter, "invoke", lose_readback)
    result = run(f.facade.admit_input(command))
    assert result.effect_possible and mutations(f.native) == markers(f) == 1
    if f.driver.harness == "codex":
        f.native.state["turns"] = []
    else:
        f.native.peer.hide_message = True
    replay = run(f.facade.admit_input(command))
    assert replay.outcome == "unknown" and replay.effect_possible
    assert mutations(f.native) == markers(f) == 1


def test_read_queries_are_authorized_and_never_prepare_or_invoke(signed):
    f = signed
    observed = run(f.facade.describe(f.binding))
    assert observed.receiver_id == f.binding.receiver_id
    assert run(f.facade.observe(f.binding))
    assert mutations(f.native) == markers(f) == 0
    before = f.state.probes
    f.state.authorized = False
    with pytest.raises((ReceiverRejected, ValueError, PermissionError)):
        run(f.facade.describe(f.binding))
    assert f.state.probes == before
    assert mutations(f.native) == markers(f) == 0


def test_prepare_rejects_revoked_authority_without_recording_input(signed):
    f = signed
    f.state.authorized = False
    with pytest.raises((ReceiverRejected, ValueError, PermissionError)):
        run(f.facade.prepare_input(f.prepare, f.binding))
    with f.service.ledger.connect() as connection:
        assert connection.execute("SELECT count(*) FROM receiver_requests").fetchone()[0] == 0
    assert mutations(f.native) == 0


def test_prepared_generation_cannot_be_moved_to_a_replacement_session(signed, monkeypatch):
    f = signed
    command = prepare_command(f)
    name = "thread_id" if f.driver.harness == "codex" else "session_id"
    monkeypatch.setattr(f.driver, name, "replacement-session")
    assert f.current_binding().provider_generation != command.provider_generation
    rejected(f.facade.admit_input(command))
    assert mutations(f.native) == markers(f) == 0
    # Repeating prepare preserves the original signed fact rather than replacing
    # it with a new Session selected after the original preparation committed.
    repeated = run(f.facade.prepare_input(f.prepare, f.current_binding()))
    assert repeated.receipt.evidence["adapter_receiver"]["provider_generation"] == command.provider_generation
    assert mutations(f.native) == markers(f) == 0


def test_revocation_during_observation_cannot_leak_a_snapshot_or_admit_input(signed, monkeypatch):
    f = signed
    command = prepare_command(f)
    original = f.adapter.receiver_snapshot

    def observe_then_revoke(binding):
        item = original(binding)
        f.state.authorized = False
        return item

    monkeypatch.setattr(f.adapter, "receiver_snapshot", observe_then_revoke)
    rejected(f.facade.admit_input(command))
    assert mutations(f.native) == markers(f) == 0


@pytest.mark.parametrize("format_name", ["acs-signed-request/1", "unnegotiated-format"])
def test_unnegotiated_sealed_formats_are_rejected(signed, format_name):
    f = signed
    command = prepare_command(f)
    invalid = command.model_copy(update={"sealed_envelope": command.sealed_envelope.model_copy(
        update={"format": format_name})})
    rejected(f.facade.admit_input(invalid))
    assert mutations(f.native) == markers(f) == 0


def test_post_submit_authorization_loss_preserves_unknown_effect_without_receipt_disclosure(signed, monkeypatch):
    f = signed
    command = prepare_command(f)
    original = f.adapter.invoke

    def acknowledge_then_revoke(*args, **kwargs):
        observation = original(*args, **kwargs)
        f.state.authorized = False
        return observation

    monkeypatch.setattr(f.adapter, "invoke", acknowledge_then_revoke)
    result = run(f.facade.admit_input(command))
    assert result.outcome == "unknown" and result.effect_possible
    assert result.reason_code == "post_submit_observation_unavailable"
    assert result.evidence_ref is None and result.native_input_ref is None
    assert mutations(f.native) == markers(f) == 1


def test_expired_signed_admission_remains_readable_only_with_current_read_authorization(signed):
    """Real admission expiry is distinct from the fixture's current read grant.

    Only the signed transport admission is short-lived. The synthetic Native
    authorizer still issues a current, deadline-free observation permission;
    this does not model expiry or renewal of a real production identity.
    """
    f = signed
    deadline = datetime.now(UTC) + timedelta(seconds=10)
    f.factory = AdmissionFactory(f.service.config, f.authority_key,
                                 replace(f.factory.identity, deadline=deadline))
    f.prepare = f.factory.request("delivery.prepare", f.prepare.body)
    assert f.prepare.admission.deadline == deadline
    assert f.invocation.envelope.packet.deadline is None
    command = prepare_command(f)
    admitted = run(f.facade.admit_input(command))
    assert admitted.outcome == "accepted" and admitted.effect_possible
    assert mutations(f.native) == markers(f) == 1

    stop = time.monotonic() + 12
    while f.service._time_valid(f.prepare.admission):
        assert time.monotonic() < stop, "the explicitly bounded admission did not expire"
        time.sleep(0.02)
    assert f.state.authorized  # The current read authorization did not expire.
    # Negative controls: neither a new prepare nor replaying the original
    # dispatch may bypass its elapsed admission deadline.
    with pytest.raises(ReceiverRejected, match="deadline|clock"):
        run(f.facade.prepare_input(f.prepare, f.binding))
    with pytest.raises(ReceiverRejected, match="deadline|clock"):
        run(f.facade.admit_input(command))

    observed = run(f.facade.reconcile(command.operation_id, f.binding))
    assert observed.outcome == "accepted" and observed.evidence_ref
    assert mutations(f.native) == markers(f) == 1
    f.state.authorized = False
    with pytest.raises((ReceiverRejected, ValueError, PermissionError)):
        run(f.facade.reconcile(command.operation_id, f.binding))
    assert mutations(f.native) == markers(f) == 1


def test_fresh_but_retired_native_snapshot_cannot_admit_current_receiver_input(signed, monkeypatch):
    f = signed
    command = prepare_command(f)
    original = f.adapter.receiver_snapshot
    current = f.current_binding()

    def retired_snapshot(binding):
        item = original(binding)
        now = datetime.now(UTC)
        expiry = now + timedelta(seconds=2)
        retired = item.model_copy(update={
            "native_session_ref": "retired-session",
            "capability_scope": item.capability_scope.model_copy(update={"provider_generation": "retired-generation"}),
            "capabilities": tuple(c.model_copy(update={"valid_until": expiry}) for c in item.capabilities),
            "observations": tuple(o.model_copy(update={"provider_generation": "retired-generation",
                "observed_at": now, "expires_at": expiry}) for o in item.observations),
        })
        # This is schema-valid, internally consistent and freshly observed.
        # Only comparison with the actual current receiving binding can reject it.
        return ReceiverSnapshot.model_validate_json(retired.model_dump_json())

    monkeypatch.setattr(f.adapter, "receiver_snapshot", retired_snapshot)
    assert f.current_binding() == current
    rejected(f.facade.admit_input(command))
    assert f.current_binding() == current
    assert mutations(f.native) == markers(f) == 0
