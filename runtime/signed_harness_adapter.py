"""Adapter 1 over the existing authenticated receiver/Native operation fences.

The sealed format is explicitly negotiated as the JSON SignedRequest containing
the existing acs-delivery-admission/1 signature. This facade introduces no signing
scheme and never calls a Native bridge outside ReceiverService.dispatch.
"""
from __future__ import annotations

import asyncio
import base64
import json

from runtime.delivery_models import InvocationRequest
from runtime.receiver import ReceiverRejected, ReceiverService
from runtime.receiver_contract import (
    NativeAdmissionCommand,
    NativeAdmissionResult,
    ReceiverBinding,
    ReceiverSnapshot,
    input_decision,
)
from runtime.receiver_crypto import sha256, verify
from runtime.receiver_delivery import ReceiverNativeDeliveryBridge
from runtime.receiver_evidence import unknown_receiver
from runtime.receiver_models import DispatchBody, PrepareBody, SignedRequest

SEALED_FORMAT = "acs-delivery-admission/1"


class SignedHarnessAdapter:
    def __init__(self, service, bridge, *, authorize_binding, binding_provider):
        if (not isinstance(service, ReceiverService) or not isinstance(bridge, ReceiverNativeDeliveryBridge)
                or not callable(authorize_binding) or not callable(binding_provider)
                or str(service.config.ledger_path) != str(bridge.ledger_path)):
            raise TypeError("an existing bound receiver, Native bridge and trusted authorizers are required")
        self.service, self.bridge = service, bridge
        self.native = bridge.native_adapter
        self.authorize_binding, self.binding_provider = authorize_binding, binding_provider

    def _binding(self, requested, *, generation=False):
        requested = ReceiverBinding.model_validate_json(requested.model_dump_json())
        if self.authorize_binding(requested) is not True:
            raise ReceiverRejected("receiver observation authorization denied")
        current = self.binding_provider()
        current = ReceiverBinding.model_validate_json(current.model_dump_json())
        registration = self.service.binding.registration
        if ((current.receiver_id, current.binding_epoch, current.authority_id,
             current.authority_incarnation, current.execution_host_ref) !=
                (registration.endpoint_id, registration.endpoint_revision, registration.authority_id,
                 registration.authority_incarnation, registration.machine_id)):
            raise ReceiverRejected("receiver registration changed")
        fields = ("receiver_id", "actor_address", "binding_epoch", "authority_id",
                  "authority_incarnation", "execution_host_ref")
        if any(getattr(requested, name) != getattr(current, name) for name in fields):
            raise ReceiverRejected("receiver binding changed")
        if generation and (requested.provider_generation != current.provider_generation
                           or requested.native_session_ref != current.native_session_ref):
            raise ReceiverRejected("receiver Native generation changed")
        return current

    def _authorized_request(self, request):
        body, _digest = self.service._verify(request)
        if self.service.authorize_current(request.admission) is not True:
            raise ReceiverRejected("receiver command authorization denied")
        return body

    def _snapshot(self, binding):
        current = self._binding(binding)
        try:
            snapshot = self.native.receiver_snapshot(current)
            snapshot = ReceiverSnapshot.model_validate_json(snapshot.model_dump_json())
            if ((snapshot.receiver_id, snapshot.address, snapshot.binding_epoch,
                 snapshot.native_session_ref, snapshot.capability_scope.execution_host_ref,
                 snapshot.capability_scope.provider_generation) !=
                    (current.receiver_id, current.actor_address, current.binding_epoch,
                     current.native_session_ref, current.execution_host_ref, current.provider_generation)):
                raise ValueError("Native snapshot belongs to another receiving scope")
        except (OSError, ValueError, RuntimeError):
            self._binding(current, generation=True)
            return unknown_receiver(current, reason="native_input_evidence_unavailable")
        self._binding(current, generation=True)
        return snapshot.current(self.service.clock.observation_time(), scope=snapshot.capability_scope)

    async def describe(self, binding):
        return await asyncio.to_thread(self._snapshot, binding)

    async def observe(self, binding):
        return (await self.describe(binding)).observations

    def _prepare(self, request, binding):
        body = self._authorized_request(request)
        if not isinstance(body, PrepareBody):
            raise ReceiverRejected("Adapter prepare requires an existing signed PrepareBody")
        invocation = InvocationRequest.model_validate_json(json.dumps(body.invocation), strict=True)
        if (sha256(invocation.envelope) != request.admission.envelope_digest
                or sha256(invocation.envelope) != sha256(body.envelope)
                or (invocation.operation_id, invocation.message_id, invocation.command_id,
                    invocation.attempt_id, invocation.dispatch_id) !=
                   (request.admission.operation_id, request.admission.message_id, request.admission.command_id,
                    request.admission.attempt_id, request.admission.dispatch_id)
                or invocation.envelope.packet.schema_version not in {"acs-message/1", "acs-notice/1"}
                or invocation.envelope.packet.activation != "invoke"):
            raise ReceiverRejected("Adapter prepare does not identify ordinary Native input")
        with self.service.ledger.execution_fence(), self.native.driver._lock:
            current = self._binding(binding)
            if invocation.envelope.packet.recipient != current.actor_address:
                raise ReceiverRejected("prepared recipient differs from the authorized receiver")
            operation = self.native._operation(invocation)
            context = self.native._handoff_context(invocation, operation)
            if (context.provider_generation != current.provider_generation
                    or context.native_session_ref != current.native_session_ref
                    or context.binding_epoch != current.binding_epoch
                    or context.binding_epoch != request.admission.endpoint_revision):
                raise ReceiverRejected("prepared Native generation changed")
            self._authorized_request(request)
            return self.service.prepare(request, adapter_receiver={
                "provider_generation": context.provider_generation,
                "native_session_ref": context.native_session_ref,
                "binding_epoch": context.binding_epoch, "auth_revision": context.auth_revision,
            })

    async def prepare_input(self, request, binding):
        return await asyncio.to_thread(self._prepare, request, binding)

    @staticmethod
    def _result(operation_id, binding, kind, *, evidence=None, reason=None):
        return NativeAdmissionResult(schema_version="acs-adapter/1", operation_id=operation_id,
            outcome=kind, effect_possible=kind in {"accepted", "queued", "unknown"}, evidence_ref=evidence,
            native_input_ref=None, binding_epoch=binding.binding_epoch,
            provider_generation=binding.provider_generation, reason_code=reason)

    def _decode(self, command):
        command = NativeAdmissionCommand.model_validate_json(command.model_dump_json())
        if command.sealed_envelope.format != SEALED_FORMAT:
            raise ReceiverRejected("sealed receiver format was not negotiated")
        raw = base64.b64decode(command.sealed_envelope.data, validate=True)
        if len(raw) > self.service.config.maximum_body_bytes:
            raise ReceiverRejected("sealed receiver request exceeds its configured bound")
        request = SignedRequest.model_validate_json(raw, strict=True)
        body = self._authorized_request(request)
        if not isinstance(body, DispatchBody) or request.admission.purpose != "delivery.dispatch":
            raise ReceiverRejected("Adapter input requires an existing signed dispatch")
        return command, request, body

    def _admit(self, command):
        command, request, body = self._decode(command)
        with self.service.ledger.execution_fence(), self.native.driver._lock:
            current = self._binding(self.binding_provider())
            invocation = self.bridge._invocation(request.admission)
            operation = self.native._operation(invocation)
            context = self.native._handoff_context(invocation, operation)
            if (sha256(invocation) != request.admission.invocation_digest
                    or invocation.envelope_digest != request.admission.envelope_digest
                    or command.canonical_hash != invocation.envelope_digest
                    or command.operation_id != invocation.invocation_id
                    or command.receiver_id != current.receiver_id
                    or command.binding_epoch != request.admission.endpoint_revision
                    or command.message_handles != (context.message_handle,)
                    or invocation.envelope.packet.recipient != current.actor_address
                    or command.deadline != request.admission.deadline):
                raise ReceiverRejected("outer Adapter input differs from the sealed original operation")
            with self.service.ledger.transaction() as connection:
                self.service._check_current_boot(connection, request.admission)
                prepared = self.service._prepared(connection, request.admission, body.prepare_request_id)
                self.service._match_prepare(prepared, request.admission)
                receipt = self.service._stored(prepared)
                verify(self.service.binding.node_public_key, receipt.signature, receipt.receipt)
                fact = receipt.receipt.evidence.get("adapter_receiver")
                marked = connection.execute("SELECT 1 FROM receiver_requests WHERE operation_id=? "
                    "AND dispatch_id=? AND local_dispatch_marker=1",
                    (request.admission.operation_id, request.admission.dispatch_id)).fetchone()
            if not isinstance(fact, dict):
                return self._result(command.operation_id, current, "unknown" if marked else "unsupported",
                    reason="prepared_native_scope_unavailable")
            if (command.provider_generation != fact.get("provider_generation")
                    or command.auth_revision != fact.get("auth_revision")
                    or command.binding_epoch != fact.get("binding_epoch")):
                raise ReceiverRejected("outer Adapter scope differs from the signed prepared fact")
            if marked:
                self._authorized_request(request)
                return self.native.reconcile_input(invocation)
            if (context.provider_generation != command.provider_generation
                    or context.native_session_ref != fact.get("native_session_ref")):
                raise ReceiverRejected("prepared Native scope differs; automatic rebind is forbidden")
            if invocation.envelope.packet.activation != "invoke" or command.input_mode != "structured":
                return self._result(command.operation_id, current, "unsupported", reason="native_input_mode_unsupported")
            snapshot = self._snapshot(current)
            decision = input_decision(snapshot, now=self.service.clock.observation_time(), scope=snapshot.capability_scope)
            self._authorized_request(request)
            self._binding(current, generation=True)
            if decision != "structured":
                return self._result(command.operation_id, current,
                    "unsupported" if decision == "unsupported" else "definitively_not_admitted",
                    evidence="receiver-readiness:" + sha256(snapshot), reason="native_input_" + decision)

            def invoke(admission):
                self._binding(current, generation=True)
                return self.bridge(admission)  # Only actual Native ACK may return successfully.

            try:
                self.service.dispatch(request, invoke)
                self._authorized_request(request)
                return self.native.reconcile_input(invocation)
            except Exception:  # noqa: BLE001 - preserve original effect uncertainty after dispatch entry.
                return self._result(command.operation_id, current, "unknown",
                                    reason="post_submit_observation_unavailable")

    async def admit_input(self, command):
        return await asyncio.to_thread(self._admit, command)

    def _reconcile(self, operation_id, binding):
        self._binding(binding)
        prefix = "delivery-invocation:"
        if not isinstance(operation_id, str) or not operation_id.startswith(prefix) or len(operation_id) > 512:
            raise ReceiverRejected("an original Native operation identity is required")
        with self.service.ledger.transaction() as connection:
            rows = connection.execute("SELECT signed_request_json FROM receiver_requests WHERE purpose='delivery.prepare' "
                "AND attempt_id=? LIMIT 2", (operation_id.removeprefix(prefix),)).fetchall()
        if not rows:
            return self._result(operation_id, binding, "unknown", reason="native_operation_not_found")
        if len(rows) != 1:
            raise ReceiverRejected("Native operation identity is ambiguous")
        request = SignedRequest.model_validate_json(rows[0][0], strict=True)
        self.service._verify_identity(request)
        self._binding(binding)
        invocation = self.bridge._invocation(request.admission)
        if invocation.invocation_id != operation_id or invocation.envelope.packet.recipient != binding.actor_address:
            raise ReceiverRejected("Native operation belongs to another binding")
        result = self.native.reconcile_input(invocation)
        self._binding(binding)
        return result

    async def reconcile(self, operation_id, binding):
        return await asyncio.to_thread(self._reconcile, operation_id, binding)


class ReadOnlySignedHarnessAdapter(SignedHarnessAdapter):
    """Authenticated terminal/unsupported-host port with no Native input owner.

    This is an actual rejection/read interface. It never types into a terminal
    and cannot turn an old uncertain dispatch into negative Native evidence.
    """

    def __init__(self, service, *, authorize_binding, binding_provider):
        if (not isinstance(service, ReceiverService) or not callable(authorize_binding)
                or not callable(binding_provider)):
            raise TypeError("a signed receiver and current binding read policy are required")
        self.service = service
        self.authorize_binding, self.binding_provider = authorize_binding, binding_provider

    def _snapshot(self, binding):
        current = self._binding(binding)
        result = unknown_receiver(current, reason="native_input_owner_unavailable")
        capabilities = tuple(c.model_copy(update={"support": "unsupported"})
            if c.name in {"native.structured_input", "native.safe_busy_enqueue", "native.safe_steer",
                          "native.terminal_pointer"} else c for c in result.capabilities)
        self._binding(current)
        return result.model_copy(update={"capabilities": capabilities})

    def _prepare(self, request, binding):
        body = self._authorized_request(request)
        current = self._binding(binding)
        if not isinstance(body, PrepareBody):
            raise ReceiverRejected("readonly preparation requires a signed prepare")
        invocation = InvocationRequest.model_validate_json(json.dumps(body.invocation), strict=True)
        if (invocation.envelope.packet.schema_version not in {"acs-message/1", "acs-notice/1"}
                or invocation.envelope.packet.recipient != current.actor_address
                or invocation.envelope.binding_revision != current.binding_epoch
                or sha256(invocation.envelope) != request.admission.envelope_digest):
            raise ReceiverRejected("readonly prepare binding differs")
        return self.service.prepare(request)

    def _admit(self, command):
        command, request, body = self._decode(command)
        current = self._binding(self.binding_provider())
        with self.service.ledger.execution_fence(), self.service.ledger.transaction() as connection:
            self.service._check_current_boot(connection, request.admission)
            row = self.service._prepared(connection, request.admission, body.prepare_request_id)
            self.service._match_prepare(row, request.admission)
            original = SignedRequest.model_validate_json(row["signed_request_json"], strict=True)
            prepared, _hash = self.service._verify_identity(original)
            invocation = InvocationRequest.model_validate_json(json.dumps(prepared.invocation), strict=True)
            packet = invocation.envelope.packet
            if packet.schema_version not in {"acs-message/1", "acs-notice/1"}:
                raise ReceiverRejected("readonly Adapter rejects retired task input")
            reference = (f"notification:{packet.project_id}:communication-{packet.notification_sequence}"
                if packet.schema_version == "acs-notice/1" else f"message:{packet.project_id}:{invocation.message_id}")
            if (command.operation_id != invocation.invocation_id or command.receiver_id != current.receiver_id
                    or command.binding_epoch != current.binding_epoch
                    or command.binding_epoch != request.admission.endpoint_revision
                    or command.canonical_hash != invocation.envelope_digest
                    or command.message_handles != (reference,) or packet.recipient != current.actor_address
                    or sha256(invocation) != request.admission.invocation_digest):
                raise ReceiverRejected("readonly Adapter command differs from sealed input")
            marked = connection.execute("SELECT 1 FROM receiver_requests WHERE operation_id=? "
                "AND dispatch_id=? AND local_dispatch_marker=1",
                (request.admission.operation_id, request.admission.dispatch_id)).fetchone()
        self._authorized_request(request)
        self._binding(current)
        return self._result(command.operation_id, current, "unknown" if marked else "unsupported",
                            reason="native_input_owner_unavailable")

    def _reconcile(self, operation_id, binding):
        current = self._binding(binding)
        if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 512:
            raise ReceiverRejected("an original operation identity is required")
        return self._result(operation_id, current, "unknown", reason="native_operation_unobservable")
