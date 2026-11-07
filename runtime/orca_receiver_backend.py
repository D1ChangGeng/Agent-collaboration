"""Concrete Core verifier/ledger adapter for an independently owned Orca Host.

This is a trusted in-process composition, not a public verification RPC. It
never owns a Native Driver, touches an Orca database or synthesizes a reply.
The Host supplies its actual ownership and serialized final-admission callback.
"""
from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy

from runtime.delivery_models import InvocationRequest
from runtime.delivery_node import invocation_for
from runtime.native_view_models import ProviderAdmission
from runtime.receiver import ReceiverRejected, ReceiverService, verified_prepare_body
from runtime.receiver_contract import NativeAdmissionCommand, NativeAdmissionResult
from runtime.receiver_crypto import sha256, verify
from runtime.receiver_models import DispatchBody, PrepareBody, ReadbackBody, SignedRequest


class ExistingOrcaReceiverBackend:
    format = "acs-delivery-admission/1"

    def __init__(self, service, *, current_ownership, authorize_original_read=None):
        if (not isinstance(service, ReceiverService) or not callable(current_ownership)
                or authorize_original_read is not None and not callable(authorize_original_read)):
            raise TypeError("the existing Receiver service, actual Host ownership and current Core read authority are required")
        self.service = service
        self._ownership = current_ownership
        self._read_authority = authorize_original_read or service.require_original_source_read

    def _owner(self):
        value = self._ownership()
        if (not isinstance(value, dict) or value.get("inputOwner") != "orca" or value.get("ownerToken") is None
                or not isinstance(value.get("session"), dict) or value["session"].get("authority") != "orca"):
            raise ReceiverRejected("actual Orca input ownership is unavailable")
        references = [value.get(k) for k in ("receiverRef", "address", "hostPrincipalRef", "authorityId", "authorityIncarnation", "scopeRef")]
        references += [value["session"].get(k) for k in ("providerRef", "sessionRef", "hostRef", "generation")]
        for item in references:
            if not isinstance(item, str) or not 1 <= len(item) <= 512:
                raise ReceiverRejected("complete actual Orca ownership references are required")
        return {**value, "session": dict(value["session"])}

    def _same_owner(self, expected):
        actual = self._owner()
        if actual["ownerToken"] is not expected["ownerToken"] or any(actual[k] != v for k, v in expected.items() if k != "ownerToken"):
            raise ReceiverRejected("Orca input owner changed during Core verification")

    def _scope(self, owner, invocation):
        envelope, packet = invocation.envelope, invocation.envelope.packet
        if ((owner["receiverRef"], owner["address"], owner.get("bindingEpoch"), owner["authorityId"], owner["authorityIncarnation"],
             owner["scopeRef"], owner["session"]["hostRef"]) !=
                (envelope.endpoint_id, packet.recipient, envelope.binding_revision, envelope.authority_id,
                 envelope.authority_incarnation, packet.target_scope_id, envelope.machine_id)):
            raise ReceiverRejected("Orca owner differs from the original Core receiving scope")

    def prepare(self, request):
        body, _request_hash = self.service._verify(request)
        if not isinstance(body, PrepareBody) or self.service.authorize_current(request.admission) is not True:
            raise ReceiverRejected("current Core preparation authority is unavailable")
        owner = self._owner()
        invocation = InvocationRequest.model_validate_json(json.dumps(body.invocation), strict=True)
        self._scope(owner, invocation)
        if (invocation.envelope.packet.schema_version not in {"acs-message/1", "acs-notice/1"}
                or invocation != invocation_for(invocation.envelope, request.admission.attempt_id)
                or invocation.envelope.model_dump(mode="json") != body.envelope
                or any(getattr(invocation, field) != getattr(request.admission, field) for field in
                    ("message_id", "command_id", "operation_id", "attempt_id", "dispatch_id", "accepted_state_digest",
                     "accepted_revision", "envelope_digest", "selection_digest"))
                or sha256(invocation) != request.admission.invocation_digest):
            raise ReceiverRejected("prepared Orca input differs from the sealed original invocation")
        revision = self.service.binding.registration.node_binding_revision
        auth = {"grant_ref": invocation.envelope.grant_ref, "authority_id": invocation.envelope.authority_id,
                "authority_incarnation": invocation.envelope.authority_incarnation, "binding_revision": revision,
                "accepted_state_digest": invocation.accepted_state_digest}
        fact = {"provider_generation": owner["session"]["generation"], "native_session_ref": owner["session"]["sessionRef"],
                "binding_epoch": owner["bindingEpoch"], "auth_revision": hashlib.sha256(json.dumps(auth, sort_keys=True).encode()).hexdigest(),
                "orca_host_principal": owner["hostPrincipalRef"], "orca_provider_ref": owner["session"]["providerRef"]}
        self._same_owner(owner)
        with self.service.ledger.execution_fence():
            self._same_owner(owner)
            return self.service.prepare(request, adapter_receiver=fact)

    def _verify(self, command, *, historical=False):
        command = NativeAdmissionCommand.model_validate_json(command.model_dump_json(), strict=True)
        if command.sealed_envelope.format != self.format:
            raise ReceiverRejected("Orca Core verifier requires the negotiated sealed receiver format")
        raw = base64.b64decode(command.sealed_envelope.data, validate=True)
        if not raw or len(raw) > self.service.config.maximum_body_bytes:
            raise ReceiverRejected("sealed Orca input exceeds the existing Receiver bound")
        request = SignedRequest.model_validate_json(raw, strict=True)
        body, _digest = self.service._verify_identity(request) if historical else self.service._verify(request)
        if not isinstance(body, DispatchBody) or request.admission.purpose != "delivery.dispatch":
            raise ReceiverRejected("Orca admission requires the original signed dispatch")
        if historical:
            if self._read_authority(request.admission) is not None:
                raise ReceiverRejected("current original-operation read authority is unavailable")
        elif self.service.authorize_current(request.admission) is not True:
            raise ReceiverRejected("current Core input authority is unavailable")
        owner = self._owner()
        with self.service.ledger.transaction() as connection:
            self.service._check_current_boot(connection, request.admission)
            prepared = self.service._prepared(connection, request.admission, body.prepare_request_id)
            self.service._match_prepare(prepared, request.admission)
            original = verified_prepare_body(prepared)
            invocation = InvocationRequest.model_validate_json(json.dumps(original.invocation), strict=True)
            receipt = self.service._stored(prepared)
            verify(self.service.binding.node_public_key, receipt.signature, receipt.receipt)
            fact = deepcopy(receipt.receipt.evidence.get("adapter_receiver"))
        self._scope(owner, invocation)
        if (not isinstance(fact, dict) or fact.get("orca_host_principal") != owner["hostPrincipalRef"]
                or fact.get("orca_provider_ref") != owner["session"]["providerRef"]
                or command.operation_id != invocation.invocation_id or command.receiver_id != invocation.envelope.endpoint_id
                or command.message_handles != ("message:" + invocation.envelope.packet.project_id + ":" + invocation.message_id,)
                or command.canonical_hash != invocation.envelope_digest or command.deadline != request.admission.deadline
                or (command.binding_epoch, command.provider_generation, command.auth_revision) !=
                   (fact.get("binding_epoch"), fact.get("provider_generation"), fact.get("auth_revision"))):
            raise ReceiverRejected("Orca outer command differs from the signed prepared operation")
        if not historical and (fact["native_session_ref"], fact["provider_generation"]) != (
                owner["session"]["sessionRef"], owner["session"]["generation"]):
            raise ReceiverRejected("Orca prepared Native session/generation is retired")
        self._same_owner(owner)
        if historical:
            if self._read_authority(request.admission) is not None:
                raise ReceiverRejected("original-operation read authority changed")
        elif self.service.authorize_current(request.admission) is not True:
            raise ReceiverRejected("Core input authority changed during verification")
        session = owner["session"] | {"sessionRef": fact["native_session_ref"], "generation": fact["provider_generation"]}
        value = {"command": command.model_dump(mode="json"), "session": session, "hostPrincipalRef": owner["hostPrincipalRef"],
            "address": invocation.envelope.packet.recipient, "authorityId": invocation.envelope.authority_id,
            "authorityIncarnation": invocation.envelope.authority_incarnation, "scopeRef": invocation.envelope.packet.target_scope_id,
            "activation": invocation.envelope.packet.activation, "sealedBytesSha256": hashlib.sha256(raw).hexdigest(),
            "verificationRef": "receiver-verified:" + sha256(receipt)}
        return value, command, request

    def verify_dispatch(self, command):
        return self._verify(command)[0]

    def command_from_dispatch(self, request):
        body, _digest = self.service._verify(request)
        if not isinstance(body, DispatchBody) or request.admission.purpose != "delivery.dispatch":
            raise ReceiverRejected("an original signed Host dispatch is required")
        with self.service.ledger.transaction() as connection:
            prepared = self.service._prepared(connection, request.admission, body.prepare_request_id)
            self.service._match_prepare(prepared, request.admission)
            original = verified_prepare_body(prepared)
            invocation = InvocationRequest.model_validate_json(json.dumps(original.invocation), strict=True)
            fact = self.service._stored(prepared).receipt.evidence["adapter_receiver"]
        return NativeAdmissionCommand(schema_version="acs-adapter/1", operation_id=invocation.invocation_id,
            receiver_id=invocation.envelope.endpoint_id,
            message_handles=("message:" + invocation.envelope.packet.project_id + ":" + invocation.message_id,),
            canonical_hash=invocation.envelope_digest, binding_epoch=fact["binding_epoch"], provider_generation=fact["provider_generation"],
            auth_revision=fact["auth_revision"], input_mode="structured", deadline=request.admission.deadline,
            sealed_envelope={"format": self.format, "encoding": "base64", "data": base64.b64encode(request.model_dump_json().encode()).decode()})

    def read_native_source(self, admission, provider):
        from runtime.client_contracts import ClientContracts

        self.service.require_original_source_read(admission)
        provider = ProviderAdmission.model_validate_json(json.dumps(provider), strict=True)
        with self.service.ledger.transaction() as connection:
            rows = connection.execute("SELECT * FROM receiver_requests WHERE operation_id=? AND dispatch_id=? "
                "AND purpose='delivery.dispatch' LIMIT 2", (admission.operation_id, admission.dispatch_id)).fetchall()
            if len(rows) != 1:
                raise ReceiverRejected("original Host source dispatch is missing or ambiguous")
            receipt = self.service._stored(rows[0])
        verify(self.service.binding.node_public_key, receipt.signature, receipt.receipt)
        verified = receipt.receipt.evidence.get("core_verified_input")
        raw_result = receipt.receipt.evidence.get("native_admission")
        if receipt.receipt.state != "runtime_acknowledged" or verified is None or raw_result is None:
            self.service.require_original_source_read(admission)
            return {"available": False, "value": None, "reason_code": "native_source_ack_missing", "evidence_ref": None}
        result = NativeAdmissionResult.model_validate(raw_result, strict=True)
        original = self.resolve_original(result.operation_id)
        sealed = base64.b64decode(original["command"]["sealed_envelope"]["data"], validate=True)
        original_request = SignedRequest.model_validate_json(sealed, strict=True)
        with self.service.ledger.transaction() as connection:
            prepared = self.service._prepared(connection, original_request.admission, original_request.body["prepare_request_id"])
            invocation = InvocationRequest.model_validate_json(json.dumps(verified_prepare_body(prepared).invocation), strict=True)
        from runtime.communication_client_native_source import _original_selection

        expected = _original_selection(invocation)
        session = original["session"]
        selection = provider.selection
        fields = ("tenant_id", "project_id", "scope_id", "agent_slot_id", "node_id", "boot_incarnation")
        bindings = ("receiver_id", "actor_address", "binding_epoch", "authority_id", "authority_incarnation", "execution_host_ref")
        if (provider.native_authority != "orca" or provider.provider_ref != session["providerRef"]
                or selection.host_ref != session["hostRef"] or selection.binding.binding_epoch != result.binding_epoch
                or any(getattr(selection, name) != getattr(expected, name) for name in fields)
                or any(getattr(selection.binding, name) != getattr(expected.binding, name) for name in bindings)
                or selection.binding.native_session_ref not in {None, session["sessionRef"]}
                or selection.binding.provider_generation not in {None, session["generation"]}
                or selection.node_binding_revision not in {None, self.service.binding.registration.node_binding_revision}
                or selection.runtime_id not in {None, admission.runtime_id}
                or selection.runtime_binding_revision not in {None, admission.runtime_revision}):
            raise ReceiverRejected("Host Native source provider differs from the original receiving scope")
        if result.outcome not in {"accepted", "queued"} or result.native_input_ref is None:
            self.service.require_original_source_read(admission)
            return {"available": False, "value": None, "reason_code": "native_source_input_ref_unobservable", "evidence_ref": None}
        value = {"messageHandle": original["command"]["message_handles"][0], "operationId": admission.operation_id,
                 "bindingEpoch": result.binding_epoch, "nativeSession": session, "nativeInputRef": result.native_input_ref}
        self.service.require_original_source_read(admission)
        return ClientContracts().validate("NativeSourceLookup", {"available": True, "value": value, "reason_code": None,
            "evidence_ref": "orca-source:" + sha256(receipt)})

    def assert_current(self, verified):
        actual = self.verify_dispatch(NativeAdmissionCommand.model_validate_json(json.dumps(verified["command"]), strict=True))
        if actual != verified:
            raise ReceiverRejected("original Core verification is no longer current")

    def resolve_original(self, operation_id):
        prefix = "delivery-invocation:"
        if not isinstance(operation_id, str) or not operation_id.startswith(prefix) or len(operation_id) > 512:
            raise ReceiverRejected("an exact original Native operation reference is required")
        with self.service.ledger.transaction() as connection:
            rows = connection.execute("SELECT * FROM receiver_requests WHERE purpose='delivery.dispatch' "
                "AND attempt_id=? LIMIT 2", (operation_id.removeprefix(prefix),)).fetchall()
        if len(rows) != 1:
            raise ReceiverRejected("original Orca dispatch is missing or ambiguous")
        original = self.service._stored(rows[0]).receipt.evidence.get("core_verified_input")
        if not isinstance(original, dict) or not isinstance(original.get("command"), dict):
            raise ReceiverRejected("original verified Orca input bytes are unavailable")
        command = NativeAdmissionCommand.model_validate_json(json.dumps(original["command"]), strict=True)
        if command.operation_id != operation_id:
            raise ReceiverRejected("stored Orca input belongs to another original operation")
        return self._verify(command, historical=True)[0]

    def reconcile_original(self, operation_id, read_original):
        """Read the same Host operation and settle its existing uncertain row.

        The callback must implement the Host's independently authorized original
        lookup. It cannot admit input. A missing or ambiguous original ACK leaves
        the original marker uncertain and is never permission for another send.
        """
        if not callable(read_original):
            raise TypeError("an actual Host original-operation reader is required")
        original = self.resolve_original(operation_id)
        request = SignedRequest.model_validate_json(base64.b64decode(
            original["command"]["sealed_envelope"]["data"], validate=True), strict=True)
        _body, hashed = self.service._verify_identity(request)
        with self.service.ledger.transaction() as connection:
            row = self.service._existing(connection, request, hashed)
            if row is None:
                raise ReceiverRejected("original Host dispatch disappeared")
            stored = self.service._stored(row)
            active = self.service._execution_lease_active(row)
        if stored.receipt.state == "runtime_acknowledged" or active:
            return stored
        if stored.receipt.state not in {"uncertain", "runtime_dispatched"}:
            return stored
        result = NativeAdmissionResult.model_validate(read_original(deepcopy(original)), strict=True)
        command = original["command"]
        if (result.operation_id, result.binding_epoch, result.provider_generation) != (
                operation_id, command["binding_epoch"], command["provider_generation"]):
            raise ReceiverRejected("Host original lookup returned another operation or generation")
        if self.resolve_original(operation_id) != original:
            raise ReceiverRejected("Host original source changed during reconciliation")
        if result.outcome not in {"accepted", "queued"}:
            return stored
        with self.service.ledger.transaction() as connection:
            self.service._check_current_boot(connection, request.admission)
            row = self.service._existing(connection, request, hashed)
            if row is None or self.service._stored(row).receipt.evidence.get("core_verified_input") != original:
                raise ReceiverRejected("original verified Host operation changed")
            if row["state"] == "runtime_acknowledged" or self.service._execution_lease_active(row):
                receipt = self.service._stored(row)
            elif row["state"] in {"uncertain", "runtime_dispatched"}:
                receipt = self.service._update(connection, request, hashed, "runtime_acknowledged",
                    {"native_admission": result.model_dump(mode="json"), "original_host_reconcile_ref": result.evidence_ref})
            else:
                raise ReceiverRejected("original Host operation cannot be settled from this state")
        self.resolve_original(operation_id)  # Read authority is current after any storage wait.
        return receipt

    def admit_verified(self, verified, admit_original):
        if not callable(admit_original):
            raise TypeError("actual serialized Orca Host admission is required")
        self.assert_current(verified)
        value, command, request = self._verify(NativeAdmissionCommand.model_validate_json(json.dumps(verified["command"]), strict=True))
        if value["activation"] != "invoke" or command.input_mode != "structured":
            return NativeAdmissionResult(schema_version="acs-adapter/1", operation_id=command.operation_id, outcome="unsupported",
                effect_possible=False, evidence_ref=None, native_input_ref=None, binding_epoch=command.binding_epoch,
                provider_generation=command.provider_generation, reason_code="orca_native_input_mode_unsupported")
        admitted = []

        def invoke(_admission):
            self.assert_current(value)
            self.service.record_verified_input(request, value)
            result = NativeAdmissionResult.model_validate(admit_original(deepcopy(value)), strict=True)
            if (result.operation_id, result.binding_epoch, result.provider_generation) != (
                    command.operation_id, command.binding_epoch, command.provider_generation):
                raise ReceiverRejected("Orca Host result differs from its original Core operation")
            admitted.append(result)
            if result.outcome not in {"accepted", "queued"}:
                raise ReceiverRejected("Orca Host has no positive Native admission evidence")
            return {"native_admission": result.model_dump(mode="json")}

        receipt = self.service.dispatch(request, invoke)
        if admitted:
            return admitted[0]
        original = receipt.receipt.evidence.get("native_admission")
        if original is not None:
            return NativeAdmissionResult.model_validate(original, strict=True)
        return NativeAdmissionResult(schema_version="acs-adapter/1", operation_id=command.operation_id, outcome="unknown",
            effect_possible=True, evidence_ref=None, native_input_ref=None, binding_epoch=command.binding_epoch,
            provider_generation=command.provider_generation, reason_code="original_orca_admission_unknown")


class OrcaReceiverRouter:
    """Existing Receiver wire operations composed with one actual Host owner.

    A trusted Host installs these callbacks alongside its private Core bridge.
    This router owns no Driver/PTY. It uses existing prepare/dispatch/readback
    paths and preserves the normal signed-receipt protocol.
    """

    def __init__(self, backend, *, admit_original, observe_readiness, reconcile_original=None):
        if (not isinstance(backend, ExistingOrcaReceiverBackend) or not callable(admit_original)
                or not callable(observe_readiness) or reconcile_original is not None and not callable(reconcile_original)):
            raise TypeError("actual Core backend, serialized Host admission and current Host observation are required")
        self.backend, self.admit_original, self.observe_readiness = backend, admit_original, observe_readiness
        self.reconcile_original = reconcile_original

    def handle(self, request):
        service = self.backend.service
        if request.admission.purpose == "delivery.prepare":
            return self.backend.prepare(request)
        if request.admission.purpose == "delivery.dispatch":
            command = self.backend.command_from_dispatch(request)
            self.backend.admit_verified(self.backend.verify_dispatch(command), self.admit_original)
            _body, hashed = service._verify_identity(request)
            with service.ledger.transaction() as connection:
                row = service._existing(connection, request, hashed)
                if row is None:
                    raise ReceiverRejected("original Host dispatch result is unavailable")
                return service._stored(row)
        if request.admission.purpose == "delivery.readback":
            if self.reconcile_original is not None:
                body, _hashed = service._verify(request)
                if not isinstance(body, ReadbackBody) or (body.operation_id, body.dispatch_id) != (
                        request.admission.operation_id, request.admission.dispatch_id):
                    raise ReceiverRejected("Host readback differs from its original operation")
                service.require_original_source_read(request.admission)
                original = self.backend.resolve_original("delivery-invocation:" + request.admission.attempt_id)
                sealed = SignedRequest.model_validate_json(base64.b64decode(
                    original["command"]["sealed_envelope"]["data"], validate=True), strict=True)
                expected, actual = service._identity(sealed.admission), service._identity(request.admission)
                expected.pop("deadline")
                actual.pop("deadline")
                if expected != actual:
                    raise ReceiverRejected("Host readback source differs from its original dispatch")
                self.backend.reconcile_original(original["command"]["operation_id"], self.reconcile_original)
            return service.readback(request, native_source_reader=self.backend.read_native_source)
        if request.admission.purpose == "delivery.readiness":
            return service.readiness(request, self.observe_readiness)
        raise ReceiverRejected("Host recovery requires original-operation reconcile; no automatic replacement dispatch")
