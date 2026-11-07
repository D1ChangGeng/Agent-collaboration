"""Real existing-Core verifier/ledger adapter, with an explicit Host double."""
from __future__ import annotations

import base64
import json
from copy import deepcopy

import pytest

from runtime.communication_client_native_source import _original_selection
from runtime.native_view_models import ProviderAdmission
from runtime.orca_receiver_backend import ExistingOrcaReceiverBackend, OrcaReceiverRouter
from runtime.receiver import ReceiverRejected
from runtime.receiver_contract import NativeAdmissionCommand
from runtime.receiver_models import DispatchBody, NativeSourceReadbackBody
from runtime_tests.test_receiver_evidence_native import receiver as receiver_fixture
from runtime_tests.test_signed_harness_adapter import signed as signed_fixture

receiver = receiver_fixture
signed = signed_fixture


def backend(signed):
    registration = signed.service.binding.registration
    owner = {"receiverRef": registration.endpoint_id, "address": signed.binding.actor_address,
        "bindingEpoch": registration.endpoint_revision, "hostPrincipalRef": "trusted-orca-host-principal",
        "authorityId": registration.authority_id, "authorityIncarnation": registration.authority_incarnation,
        "scopeRef": registration.scope_id, "ownerToken": object(), "inputOwner": "orca",
        "session": {"providerRef": "trusted-orca-provider", "sessionRef": "actual-orca-session",
            "hostRef": registration.machine_id, "generation": "actual-orca-generation", "authority": "orca"}}
    allowed = [True]

    def read(_admission):
        if not allowed[0]:
            raise ReceiverRejected("current original Core read is revoked")

    port = ExistingOrcaReceiverBackend(signed.service, current_ownership=lambda: owner, authorize_original_read=read)
    prepared = port.prepare(signed.prepare)
    fact = prepared.receipt.evidence["adapter_receiver"]
    request = signed.factory.request("delivery.dispatch", DispatchBody(prepare_request_id=signed.prepare.admission.request_id,
        marker_receipt_id="actual-Core-dispatch-marker"))
    command = NativeAdmissionCommand(schema_version="acs-adapter/1", operation_id=signed.invocation.invocation_id,
        receiver_id=registration.endpoint_id, message_handles=("message:fixture-project:fixture-message",),
        canonical_hash=signed.invocation.envelope_digest, binding_epoch=fact["binding_epoch"], provider_generation=fact["provider_generation"],
        auth_revision=fact["auth_revision"], input_mode="structured", deadline=request.admission.deadline,
        sealed_envelope={"format": port.format, "encoding": "base64", "data": base64.b64encode(request.model_dump_json().encode()).decode()})
    return port, owner, command, allowed


@pytest.mark.parametrize("outcome", ["accepted", "queued"])
def test_concrete_verifier_uses_existing_prepare_and_dispatch_ledger_without_native_driver(signed, outcome):
    port, owner, command, _allowed = backend(signed)
    with signed.driver.journal._connect() as connection:
        before = connection.execute("SELECT count(*) FROM driver_events").fetchone()
    verified = port.verify_dispatch(command)
    assert verified["session"] == owner["session"] and verified["activation"] == "invoke"
    calls = []

    def actual_host(value):
        port.assert_current(value)
        calls.append(value["command"]["operation_id"])
        return {"schema_version": "acs-adapter/1", "operation_id": command.operation_id, "outcome": outcome,
            "effect_possible": True, "evidence_ref": "actual-host-admission-receipt", "native_input_ref": "host-native-input",
            "binding_epoch": command.binding_epoch, "provider_generation": command.provider_generation, "reason_code": None}

    result = port.admit_verified(verified, actual_host)
    assert result.outcome == outcome
    assert port.admit_verified(verified, actual_host) == result and calls == [command.operation_id]
    original = port.resolve_original(command.operation_id)
    assert original["session"] == verified["session"] and original["command"] == verified["command"]
    with signed.driver.journal._connect() as connection:
        assert connection.execute("SELECT count(*) FROM driver_events").fetchone() == before


def test_retired_native_generation_cannot_admit_but_original_lookup_keeps_historical_scope(signed):
    port, owner, command, allowed = backend(signed)
    verified = port.verify_dispatch(command)
    admitted = {"schema_version": "acs-adapter/1", "operation_id": command.operation_id, "outcome": "accepted",
        "effect_possible": True, "evidence_ref": "original-host-receipt", "native_input_ref": "original-host-input",
        "binding_epoch": command.binding_epoch, "provider_generation": command.provider_generation, "reason_code": None}
    port.admit_verified(verified, lambda _value: admitted)
    owner["session"] = owner["session"] | {"sessionRef": "new-native-session", "generation": "new-native-generation"}
    owner["ownerToken"] = object()
    with pytest.raises(ReceiverRejected, match="retired"):
        port.verify_dispatch(command)
    old = port.resolve_original(command.operation_id)
    assert old["session"]["sessionRef"] == "actual-orca-session" and old["session"]["generation"] == command.provider_generation
    allowed[0] = False
    with pytest.raises(ReceiverRejected, match="revoked"):
        port.resolve_original(command.operation_id)


def test_forged_outer_values_or_core_revocation_never_enter_host(signed):
    port, _owner, command, _allowed = backend(signed)
    wrong = command.model_copy(update={"auth_revision": "forged-auth"})
    with pytest.raises(ReceiverRejected):
        port.verify_dispatch(wrong)
    verified = port.verify_dispatch(command)
    signed.state.authorized = False
    with pytest.raises(ReceiverRejected, match="authority"):
        port.admit_verified(verified, lambda _value: pytest.fail("revoked Core cannot invoke Host"))


def test_host_uncertainty_preserves_original_dispatch_and_never_replays(signed):
    port, _owner, command, _allowed = backend(signed)
    verified = port.verify_dispatch(command)
    calls = []

    def unknown(_value):
        calls.append(True)
        raise OSError("Host ACK lost after possible native input")

    assert port.admit_verified(verified, unknown).outcome == "unknown"
    assert port.admit_verified(verified, unknown).outcome == "unknown" and calls == [True]
    assert port.resolve_original(command.operation_id)["command"] == command.model_dump(mode="json")


def test_host_cannot_substitute_another_original_operation(signed):
    port, _owner, command, _allowed = backend(signed)
    verified = port.verify_dispatch(command)
    before = deepcopy(verified)
    assert port.verify_dispatch(command) == before
    result = port.admit_verified(verified, lambda _value: {"schema_version": "acs-adapter/1", "operation_id": "foreign-operation",
        "outcome": "accepted", "effect_possible": True, "evidence_ref": "wrong-receipt", "native_input_ref": "wrong-input",
        "binding_epoch": command.binding_epoch, "provider_generation": command.provider_generation, "reason_code": None})
    assert result.outcome == "unknown"


def test_default_original_reader_uses_current_read_policy_without_renewing_expired_input(signed, monkeypatch):
    port, owner, command, _allowed = backend(signed)
    verified = port.verify_dispatch(command)
    result = {"schema_version": "acs-adapter/1", "operation_id": command.operation_id, "outcome": "accepted",
        "effect_possible": True, "evidence_ref": "historical-host-receipt", "native_input_ref": "historical-input",
        "binding_epoch": command.binding_epoch, "provider_generation": command.provider_generation, "reason_code": None}
    port.admit_verified(verified, lambda _value: result)
    reads = []

    def current_read(admission):
        assert admission.purpose == "delivery.readback" and admission.deadline is None
        reads.append(admission.operation_id)
        return True

    monkeypatch.setattr(signed.service, "authorize_source_read", current_read)
    monkeypatch.setattr(signed.service, "_time_valid", lambda _admission: False)
    current = ExistingOrcaReceiverBackend(signed.service, current_ownership=lambda: owner)
    with pytest.raises(ReceiverRejected, match="deadline"):
        current.verify_dispatch(command)
    assert current.resolve_original(command.operation_id)["command"] == command.model_dump(mode="json")
    assert reads and set(reads) == {signed.invocation.operation_id}


def test_router_reconciles_original_host_ack_into_existing_unknown_row_without_another_admission(signed):
    port, owner, command, _allowed = backend(signed)
    calls = []
    original_result = {"schema_version": "acs-adapter/1", "operation_id": command.operation_id, "outcome": "accepted",
        "effect_possible": True, "evidence_ref": "durable-original-host-receipt", "native_input_ref": "original-host-input",
        "binding_epoch": command.binding_epoch, "provider_generation": command.provider_generation, "reason_code": None}

    def lost_ack(_value):
        calls.append("admit")
        raise OSError("Host accepted the original input but its ACK was lost")

    assert port.admit_verified(port.verify_dispatch(command), lost_ack).outcome == "unknown"
    owner["session"] = owner["session"] | {"sessionRef": "later-current-session", "generation": "later-current-generation"}
    owner["ownerToken"] = object()

    def read_original(value):
        calls.append("read_original")
        assert value["command"]["operation_id"] == command.operation_id
        assert value["session"]["sessionRef"] == "actual-orca-session"
        return original_result

    router = OrcaReceiverRouter(port, admit_original=lost_ack, observe_readiness=lambda *_args: {}, reconcile_original=read_original)
    provider = ProviderAdmission(provider_ref=owner["session"]["providerRef"], native_authority="orca",
                                 selection=_original_selection(signed.invocation))
    request = signed.factory.request("delivery.readback", NativeSourceReadbackBody(
        operation_id=signed.invocation.operation_id, dispatch_id=signed.invocation.dispatch_id,
        native_source=True, provider_admission=provider.model_dump(mode="json")))
    receipt = router.handle(request)
    source = receipt.receipt.evidence["native_source"]
    assert source["available"] and source["value"]["nativeInputRef"] == "original-host-input"
    assert source["value"]["nativeSession"]["sessionRef"] == "actual-orca-session"
    assert source["value"]["operationId"] == signed.invocation.operation_id
    assert router.handle(request) == receipt and calls == ["admit", "read_original"]
    dispatch = json.loads(base64.b64decode(command.sealed_envelope.data))
    with signed.service.ledger.transaction() as connection:
        assert connection.execute("SELECT state FROM receiver_requests WHERE request_id=?",
            (dispatch["admission"]["request_id"],)).fetchone()[0] == "runtime_acknowledged"
        assert connection.execute("SELECT count(*) FROM receiver_requests WHERE local_dispatch_marker=1").fetchone()[0] == 1


def test_original_host_reader_cannot_settle_another_generation_or_revoke_during_lookup(signed):
    port, _owner, command, allowed = backend(signed)
    port.admit_verified(port.verify_dispatch(command), lambda _value: (_ for _ in ()).throw(OSError("ACK lost")))
    result = {"schema_version": "acs-adapter/1", "operation_id": command.operation_id, "outcome": "accepted",
        "effect_possible": True, "evidence_ref": "host-receipt", "native_input_ref": "host-input",
        "binding_epoch": command.binding_epoch, "provider_generation": "foreign-generation", "reason_code": None}
    with pytest.raises(ReceiverRejected, match="another operation or generation"):
        port.reconcile_original(command.operation_id, lambda _value: result)

    def revoked(_value):
        allowed[0] = False
        return result | {"provider_generation": command.provider_generation}

    with pytest.raises(ReceiverRejected, match="revoked"):
        port.reconcile_original(command.operation_id, revoked)
    with signed.service.ledger.transaction() as connection:
        assert connection.execute("SELECT state FROM receiver_requests WHERE local_dispatch_marker=1").fetchone()[0] == "uncertain"
