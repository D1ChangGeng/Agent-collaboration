"""Read-only Adapter contract on actual signatures/SQL/ACL and synthetic Native peers.

The hidden Native peer is used only to establish a genuine uncertain dispatch
for the fallback test. The read-only port itself has no bridge or input owner.
"""
from __future__ import annotations

import base64
import json

import pytest

from runtime.receiver import ReceiverRejected
from runtime.receiver_contract import NativeAdmissionCommand, SealedEnvelope
from runtime.receiver_crypto import public_key, verify
from runtime.receiver_models import DispatchBody
from runtime.signed_harness_adapter import ReadOnlySignedHarnessAdapter
from runtime_tests.test_native_handoff import mutations
from runtime_tests.test_signed_harness_adapter import markers, prepare_command, run
from runtime_tests.test_signed_harness_adapter import receiver as receiver_fixture
from runtime_tests.test_signed_harness_adapter import signed as signed_fixture

receiver = receiver_fixture
signed = signed_fixture


@pytest.fixture
def readonly(signed):
    f = signed
    port = ReadOnlySignedHarnessAdapter(f.service, authorize_binding=f.facade.authorize_binding,
                                      binding_provider=f.current_binding)
    return f, port


def readonly_command(f, port):
    prepared = run(port.prepare_input(f.prepare, f.binding))
    verify(public_key(f.node_key), prepared.signature, prepared.receipt)
    assert prepared.receipt.state == "prepared"
    assert "adapter_receiver" not in prepared.receipt.evidence
    request = f.factory.request("delivery.dispatch", DispatchBody(prepare_request_id=f.prepare.admission.request_id,
                                                                marker_receipt_id="synthetic-domain-marker"))
    # These are fixture DTO values, not a Native capability or permission
    # manufactured by the read-only port; it does not interpret them as input authority.
    context = f.adapter._handoff_context(f.invocation, f.adapter._operation(f.invocation))
    return NativeAdmissionCommand(schema_version="acs-adapter/1", operation_id=f.invocation.invocation_id,
        receiver_id=f.binding.receiver_id, message_handles=("message:fixture-project:fixture-message",),
        canonical_hash=f.invocation.envelope_digest, binding_epoch=f.binding.binding_epoch,
        provider_generation=f.binding.provider_generation, auth_revision=context.auth_revision, input_mode="structured",
        sealed_envelope=SealedEnvelope(format="acs-delivery-admission/1", encoding="base64",
            data=base64.b64encode(request.model_dump_json().encode()).decode()), deadline=request.admission.deadline)


def test_readonly_signed_prepare_and_unsupported_admission_never_enter_native(readonly):
    f, port = readonly
    command = readonly_command(f, port)
    result = run(port.admit_input(command))
    assert result.outcome == "unsupported" and not result.effect_possible
    assert result.operation_id == f.invocation.invocation_id
    assert result.native_input_ref is None and result.evidence_ref is None
    assert markers(f) == mutations(f.native) == 0
    repeated = run(port.admit_input(command))
    assert repeated.outcome == "unsupported" and not repeated.effect_possible
    assert markers(f) == mutations(f.native) == 0


@pytest.mark.parametrize("field,value", [("operation_id", "another-operation"),
    ("receiver_id", "another-receiver"), ("binding_epoch", 4), ("canonical_hash", "c" * 64)])
def test_readonly_rejects_outer_identity_that_differs_from_signed_original(readonly, field, value):
    f, port = readonly
    command = readonly_command(f, port).model_copy(update={field: value})
    with pytest.raises((ReceiverRejected, ValueError, PermissionError)):
        run(port.admit_input(command))
    assert markers(f) == mutations(f.native) == 0


def test_readonly_rejects_invalid_existing_authority_signature(readonly):
    f, port = readonly
    command = readonly_command(f, port)
    request = json.loads(base64.b64decode(command.sealed_envelope.data))
    request["signature"] = "0" * 128
    invalid = command.model_copy(update={"sealed_envelope": command.sealed_envelope.model_copy(update={
        "data": base64.b64encode(json.dumps(request).encode()).decode()})})
    with pytest.raises((ReceiverRejected, ValueError, PermissionError)):
        run(port.admit_input(invalid))
    assert markers(f) == mutations(f.native) == 0


def test_readonly_describe_and_observe_do_not_prepare_or_claim_a_native_session(readonly):
    f, port = readonly
    observed = run(port.describe(f.binding))
    assert observed.receiver_id == f.binding.receiver_id
    assert observed.native_session_ref is None and observed.allowed_actions == ()
    structured = next(c for c in observed.capabilities if c.name == "native.structured_input")
    assert structured.support in {"unknown", "unsupported"} and structured.availability != "available"
    assert all(o.knowledge in {"unknown", "unsupported"} and o.value is None for o in observed.observations)
    assert run(port.observe(f.binding)) == observed.observations
    assert f.state.probes == 0  # The unrelated Native owner was not inspected.
    with f.service.ledger.connect() as connection:
        assert connection.execute("SELECT count(*) FROM receiver_requests").fetchone()[0] == 0
    assert markers(f) == mutations(f.native) == 0


def test_readonly_reconcile_never_invents_negative_proof_or_native_consumption(readonly):
    f, port = readonly
    result = run(port.reconcile(f.invocation.invocation_id, f.binding))
    assert result.outcome == "unknown" and result.effect_possible
    assert result.reason_code == "native_operation_unobservable"
    assert result.native_input_ref is None and result.evidence_ref is None
    assert markers(f) == mutations(f.native) == 0


def test_readonly_queries_and_command_replays_recheck_current_authorization(readonly):
    f, port = readonly
    command = readonly_command(f, port)
    f.state.authorized = False
    for request in (port.describe(f.binding), port.observe(f.binding),
                    port.reconcile(command.operation_id, f.binding), port.admit_input(command),
                    port.prepare_input(f.prepare, f.binding)):
        with pytest.raises((ReceiverRejected, ValueError, PermissionError)):
            run(request)
    assert markers(f) == mutations(f.native) == 0


def test_readonly_fallback_preserves_an_actual_unknown_dispatch_marker(readonly, monkeypatch):
    f, port = readonly
    command = prepare_command(f)  # Original input owner, actual signed receiver preparation.
    if f.driver.harness == "codex":
        f.native.state["drop_invoke_ack"] = True
    else:
        f.native.peer.drop_prompt_ack = True
    original = f.adapter.invoke

    def lose_ack_and_readback(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        finally:
            if f.driver.harness == "codex":
                f.native.state["turns"] = []
            else:
                f.native.peer.hide_message = True

    monkeypatch.setattr(f.adapter, "invoke", lose_ack_and_readback)
    uncertain = run(f.facade.admit_input(command))
    assert uncertain.outcome == "unknown" and uncertain.effect_possible
    assert markers(f) == mutations(f.native) == 1
    with f.service.ledger.connect() as connection:
        assert connection.execute("SELECT state FROM receiver_requests WHERE local_dispatch_marker=1").fetchone()[0] == "uncertain"
    result = run(port.admit_input(command))
    assert result.outcome == "unknown" and result.effect_possible
    assert result.native_input_ref is None and result.evidence_ref is None
    observed = run(port.reconcile(command.operation_id, f.binding))
    assert observed.outcome == "unknown" and observed.effect_possible
    assert markers(f) == mutations(f.native) == 1
