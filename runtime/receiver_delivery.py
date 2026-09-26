"""Delivery endpoint backed by the authenticated TLS receiver protocol."""
from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass, field

from nacl.signing import SigningKey

from runtime.delivery_models import InvocationRequest
from runtime.delivery_node import (
    DeliveryTransportError,
    InvocationPreCallRejected,
    logical_payload,
)
from runtime.receiver_config import ReceiverClientConfig, ReceiverRuntimeConfig
from runtime.receiver_crypto import load_owner_signing_key, sha256
from runtime.receiver_models import (
    DispatchBody,
    EndpointBinding,
    EndpointRegistration,
    PrepareBody,
    ReadbackBody,
    RecoveryBody,
)
from runtime.remote_endpoint import RemoteNodeTransport, RemoteTransportRejected
from runtime.sender import AdmissionFactory, DeliveryIdentity


@dataclass(frozen=True, slots=True)
class ReceiverDeployment:
    authority_signing_key_path: str
    tls_cert_path: str
    tls_key_path: str
    node_signing_key_path: str
    ledger_path: str
    expected_boot_incarnation: str
    journal_generation: int
    old_boot_isolation_ref: str | None = None


@dataclass(frozen=True, slots=True)
class RemoteSenderDeployment:
    """Sender-owned authority credential and receiver generation binding.

    Receiver-local certificate, Node key and SQLite paths never cross the
    machine boundary. The signing key is process-injected and omitted from the
    dataclass representation so command output cannot reveal it accidentally.
    """

    authority_signing_key: SigningKey = field(repr=False)
    expected_boot_incarnation: str = ""
    journal_generation: int = 1
    old_boot_isolation_ref: str | None = None

    def validate(self) -> None:
        if not isinstance(self.authority_signing_key, SigningKey):
            raise TypeError("sender authority signing key is unavailable")
        if (not self.expected_boot_incarnation or self.journal_generation < 1
                or (self.journal_generation == 1) != (self.old_boot_isolation_ref is None)):
            raise ValueError("sender receiver-generation binding is invalid")


class ReceiverNativeDeliveryBridge:
    """Recover the immutable prepared invocation and enter a NativeDeliveryAdapter once."""

    def __init__(
        self,
        ledger_path: str,
        native_adapter,
        *,
        read_domain_marker,
        response_collector=None,
    ):
        if not callable(read_domain_marker):
            raise TypeError("authoritative Domain marker readback is required")
        self.ledger_path = ledger_path
        self.native_adapter = native_adapter
        self.read_domain_marker = read_domain_marker
        self.response_collector = response_collector

    def _invocation(self, admission):
        with sqlite3.connect(self.ledger_path) as connection:
            row = connection.execute(
                "SELECT body_json FROM receiver_requests WHERE operation_id=? AND attempt_id=? "
                "AND dispatch_id=? AND purpose='delivery.prepare'",
                (admission.operation_id, admission.attempt_id, admission.dispatch_id),
            ).fetchone()
        if row is None:
            raise RuntimeError("receiver prepared invocation is unavailable")
        invocation = InvocationRequest.model_validate_json(
            json.dumps(json.loads(row[0])["invocation"]), strict=True,
        )
        if (invocation.operation_id, invocation.attempt_id, invocation.dispatch_id,
                invocation.message_id, invocation.command_id) != (
                admission.operation_id, admission.attempt_id, admission.dispatch_id,
                admission.message_id, admission.command_id):
            raise RuntimeError("receiver native invocation lineage differs")
        return invocation

    def __call__(self, admission):
        invocation = self._invocation(admission)
        self.native_adapter.prepare(invocation)

        def dispatch_readback():
            if self.read_domain_marker(invocation) is not True:
                raise RuntimeError("authoritative Domain dispatch marker is unavailable")

        observation = self.native_adapter.invoke(invocation, on_dispatch=dispatch_readback)
        if observation.native_ack_ref is None:
            raise RuntimeError("native result is uncertain")
        return {"native_observation": observation.model_dump(mode="json")}

    def collect_response(self, admission):
        """Project a delayed terminal response without invoking or resuming native work."""
        if self.response_collector is None:
            raise RuntimeError("receiver response collector is unavailable")
        invocation = self._invocation(admission)
        result = self.response_collector.collect_and_project(invocation)
        return {
            "projection_id": result.projection_id,
            "canonical_digest": result.canonical_digest,
            "disposition": result.disposition,
        }


class RemoteNodeEndpointAdapter:
    """Resolve only committed registration data and preserve Delivery marker order."""

    evidence_class = "authenticated_receiver_transport"

    def __init__(self, authority, endpoint_id: str,
                 deployment: ReceiverDeployment | RemoteSenderDeployment,
                 *, timeout: float = 5.0, after_dispatch_mark=None):
        if after_dispatch_mark is not None and not callable(after_dispatch_mark):
            raise TypeError("after_dispatch_mark must be callable")
        self.after_dispatch_mark = after_dispatch_mark
        self.authority = authority
        self.store = authority.receiver_transport
        committed = self.store.load_endpoint(endpoint_id)
        registration = EndpointRegistration.model_validate_json(
            json.dumps(committed["registration"]["registration_json"]), strict=True,
        )
        connection = committed["connection"]
        binding = EndpointBinding(
            registration=registration,
            locator_host=connection["locator_host"],
            locator_port=connection["locator_port"],
            route_class=connection["route_class"],
            node_key_id=committed["registration"]["node_key_id"],
            node_public_key=committed["node_public_key"],
            registration_signature=committed["registration"]["registration_signature"],
        )
        key = self.store.load_authority_key()
        self.config = ReceiverClientConfig(
            binding=binding, authority_key_id=key["key_id"], authority_key_revision=key["revision"],
            authority_public_key=key["public_key"],
            authority_public_key_fingerprint=key["fingerprint"],
            expected_boot_incarnation=deployment.expected_boot_incarnation,
            journal_generation=deployment.journal_generation,
            old_boot_isolation_ref=deployment.old_boot_isolation_ref,
        )
        self.config.validate()
        if (registration.endpoint_id != endpoint_id
                or registration.boot_incarnation != deployment.expected_boot_incarnation):
            raise ValueError("receiver deployment differs from committed endpoint")
        if isinstance(deployment, RemoteSenderDeployment):
            deployment.validate()
            self._signing_key = deployment.authority_signing_key
        else:
            self._signing_key = load_owner_signing_key(deployment.authority_signing_key_path)
        self.transport = RemoteNodeTransport(self.config, timeout=timeout)

    @property
    def identity(self):
        return self.config.binding.registration

    def descriptor(self):
        registration = self.identity
        return {
            "machine_id": registration.machine_id,
            "node_id": registration.node_id,
            "boot_incarnation": registration.boot_incarnation,
            "scope_id": registration.scope_id,
            "agent_slot_id": registration.agent_slot_id,
            "supports_invoke": True,
            "evidence_class": self.evidence_class,
        }

    @staticmethod
    def _selection(invocation):
        envelope = invocation.envelope
        return {
            "endpoint_id": envelope.endpoint_id,
            "binding_revision": envelope.binding_revision,
            "machine_id": envelope.machine_id,
            "node_id": envelope.node_id,
            "boot_incarnation": envelope.boot_incarnation,
            "target_scope_id": envelope.packet.target_scope_id,
            "target_agent_slot_id": envelope.packet.target_agent_slot_id,
        }

    def _factory(self, invocation):
        identity = DeliveryIdentity(
            message_id=invocation.message_id,
            command_id=invocation.command_id,
            operation_id=invocation.operation_id,
            attempt_id=invocation.attempt_id,
            dispatch_id=invocation.dispatch_id,
            accepted_revision=invocation.accepted_revision,
            accepted_state_digest=invocation.accepted_state_digest,
            envelope_digest=invocation.envelope_digest,
            selection_digest=invocation.selection_digest,
            invocation_digest=sha256(invocation.model_dump(mode="json")),
            deadline=invocation.envelope.packet.deadline,
        )
        return AdmissionFactory(self.config, self._signing_key, identity)

    def _issue(self, invocation, purpose, body):
        request_id = f"receiver:{invocation.attempt_id}:{invocation.dispatch_id}:{purpose}"
        existing = self.store.admission(request_id)
        if existing is not None:
            if existing.body != body.model_dump(mode="json"):
                raise DeliveryTransportError("receiver request replay changed")
            return existing
        request = self._factory(invocation).request(
            purpose, body, request_id=request_id, nonce=secrets.token_hex(32),
            boot_incarnation=self.identity.boot_incarnation,
            journal_generation=self.config.journal_generation,
        )
        return self.store.persist_admission(request)

    def _send(self, request):
        receipt = self.transport.send(request)
        return self.store.persist_receipt(receipt)

    @staticmethod
    def _projection(receipts, status):
        projected = []
        for signed in receipts:
            receipt = signed.receipt
            if receipt.state == "prepared":
                layer = "target_inbox_committed"
            elif (receipt.state == "runtime_acknowledged"
                  or (receipt.state == "readback"
                  and receipt.evidence.get("stored_state") == "runtime_acknowledged")):
                layer = "runtime_acknowledged"
            elif receipt.state in {"readback", "runtime_dispatched", "uncertain", "blocked"}:
                continue
            projected.append({
                "receipt_id": receipt.receipt_id,
                "layer": layer,
                "evidence": {"source": "authenticated_receiver_transport",
                             "signed_receipt": signed.model_dump(mode="json")},
            })
        return {"status": status, "receipts": projected}

    def deliver(self, envelope, authorize, invocation=None, mark_dispatched=None,
                read_dispatch_marker=None):
        authorized = authorize()
        if (authorized != envelope or logical_payload(authorized) != logical_payload(envelope)
                or invocation is None or mark_dispatched is None):
            raise InvocationPreCallRejected("receiver committed authorization differs")
        prepare_body = PrepareBody(
            envelope=envelope.model_dump(mode="json"),
            invocation=invocation.model_dump(mode="json"),
            selection=self._selection(invocation),
        )
        try:
            prepared = self._send(self._issue(invocation, "delivery.prepare", prepare_body))
        except (RemoteTransportRejected, ValueError, RuntimeError) as error:
            raise InvocationPreCallRejected("receiver prepare rejected before Domain marker") from error
        mark_dispatched(
            invocation,
            {"source": self.evidence_class, "dispatch_id": invocation.dispatch_id,
             "receiver_prepare_receipt_id": prepared.receipt.receipt_id,
             "receiver_prepare_request_id": prepared.receipt.request_id},
        )
        dispatch_body = DispatchBody(
            prepare_request_id=prepared.receipt.request_id,
            marker_receipt_id=invocation.runtime_dispatched_receipt_id,
        )
        dispatch_request = self._issue(invocation, "delivery.dispatch", dispatch_body)
        # The signed dispatch admission is now durably persisted, while no
        # transport send has occurred. Fault scenarios may isolate that exact
        # request; ordinary production callers leave the hook unset.
        if self.after_dispatch_mark is not None:
            self.after_dispatch_mark(invocation, dispatch_request)
        try:
            dispatched = self._send(dispatch_request)
        except (RemoteTransportRejected, ValueError, RuntimeError):
            try:
                observed = self.inspect_delivery(invocation.operation_id, "uncertain")
            except Exception:
                observed = {"status": "uncertain", "receipts": []}
            prepared_projection = self._projection([prepared], observed["status"])
            prepared_projection["receipts"].extend(observed["receipts"])
            return prepared_projection
        state = dispatched.receipt.state
        status = "delivered" if state == "runtime_acknowledged" else state
        return self._projection([prepared, dispatched], status)

    def inspect_delivery(self, operation_id, status="uncertain"):
        dispatch = self.store.dispatch_admission(operation_id)
        if dispatch is None:
            return {"status": status, "receipts": []}
        admission = dispatch.admission
        identity = DeliveryIdentity(
            message_id=admission.message_id, command_id=admission.command_id,
            operation_id=admission.operation_id, attempt_id=admission.attempt_id,
            dispatch_id=admission.dispatch_id, accepted_revision=admission.accepted_revision,
            accepted_state_digest=admission.accepted_state_digest,
            envelope_digest=admission.envelope_digest, selection_digest=admission.selection_digest,
            invocation_digest=admission.invocation_digest, deadline=admission.deadline,
        )
        body = ReadbackBody(operation_id=operation_id, dispatch_id=admission.dispatch_id)
        request_id = f"receiver:{admission.attempt_id}:{admission.dispatch_id}:delivery.readback"
        request = self.store.admission(request_id)
        if request is None:
            request = AdmissionFactory(self.config, self._signing_key, identity).request(
                "delivery.readback", body, request_id=request_id, nonce=secrets.token_hex(32),
                boot_incarnation=admission.boot_incarnation,
                journal_generation=admission.journal_generation,
            )
            self.store.persist_admission(request)
        try:
            readback = self._send(request)
        except (RemoteTransportRejected, ValueError, RuntimeError):
            return {"status": status, "receipts": []}
        stored_state = readback.receipt.evidence.get("stored_state")
        observed_status = "delivered" if stored_state == "runtime_acknowledged" else stored_state or status
        return self._projection([readback], observed_status)

    def reconcile_marked(self, invocation):
        """Resend the exact persisted dispatch after a marked transport outage.

        The admission was durably created before the original network send.  A
        reconciliation may replay only that byte-identical signed request; the
        receiver ledger and native dispatch identity remain the dedup boundary.
        """
        dispatch = self.store.dispatch_admission(invocation.operation_id)
        if dispatch is None:
            raise DeliveryTransportError("marked dispatch admission is unavailable")
        admission = dispatch.admission
        expected = (
            "delivery.dispatch",
            f"receiver:{invocation.attempt_id}:{invocation.dispatch_id}:delivery.dispatch",
            invocation.message_id, invocation.command_id, invocation.operation_id,
            invocation.attempt_id, invocation.dispatch_id, invocation.accepted_revision,
            invocation.accepted_state_digest, invocation.envelope_digest,
            invocation.selection_digest, sha256(invocation.model_dump(mode="json")),
            invocation.envelope.endpoint_id, invocation.envelope.machine_id,
            invocation.envelope.node_id, invocation.envelope.boot_incarnation,
            invocation.envelope.packet.target_scope_id,
            invocation.envelope.packet.target_agent_slot_id,
        )
        actual = (
            admission.purpose, admission.request_id, admission.message_id,
            admission.command_id, admission.operation_id, admission.attempt_id,
            admission.dispatch_id, admission.accepted_revision,
            admission.accepted_state_digest, admission.envelope_digest,
            admission.selection_digest, admission.invocation_digest,
            admission.endpoint_id, admission.machine_id, admission.node_id,
            admission.boot_incarnation, admission.scope_id, admission.agent_slot_id,
        )
        if actual != expected:
            raise DeliveryTransportError("marked dispatch admission lineage changed")
        body = DispatchBody.model_validate_json(json.dumps(dispatch.body), strict=True)
        if body.marker_receipt_id != invocation.runtime_dispatched_receipt_id:
            raise DeliveryTransportError("marked dispatch body changed")
        prepare = self.store.prepared_recovery_evidence(
            invocation.operation_id, invocation.attempt_id, invocation.dispatch_id,
        )
        if prepare is None:
            raise DeliveryTransportError("marked prepare receipt is unavailable")
        prepared_request, prepared_receipt = prepare
        if body.prepare_request_id != prepared_request.admission.request_id:
            raise DeliveryTransportError("marked dispatch prepare reference changed")
        try:
            dispatched = self._send(dispatch)
        except (RemoteTransportRejected, ValueError, RuntimeError):
            observed = self.inspect_delivery(invocation.operation_id, "uncertain")
            result = self._projection([prepared_receipt], observed["status"])
            result["receipts"].extend(observed["receipts"])
            return result
        state = dispatched.receipt.state
        return self._projection(
            [prepared_receipt, dispatched],
            "delivered" if state == "runtime_acknowledged" else state,
        )

    def recover_prepared(self, invocation, original_prepare, original_receipt,
                         authorize, mark_dispatched):
        """Route one unmarked old-boot preparation through the current signed boot.

        The caller owns the Domain Attempt lock/marker. A committed dispatch or
        recovery admission is never replaced with a different native request.
        """
        authorized = authorize()
        old = original_prepare.admission
        current = self.identity
        if (logical_payload(authorized) != logical_payload(invocation.envelope)
                or old.purpose != "delivery.prepare"
                or original_receipt.receipt.request_id != old.request_id
                or original_receipt.receipt.state != "prepared"
                or (old.message_id, old.command_id, old.operation_id, old.attempt_id,
                    old.dispatch_id, old.envelope_digest, old.selection_digest,
                    old.invocation_digest) != (
                        invocation.message_id, invocation.command_id,
                        invocation.operation_id, invocation.attempt_id,
                        invocation.dispatch_id, invocation.envelope_digest,
                        invocation.selection_digest,
                        sha256(invocation.model_dump(mode="json")),
                    )
                or (old.tenant_id, old.authority_id, old.authority_incarnation,
                    old.node_id, old.machine_id, old.scope_id, old.agent_slot_id,
                    old.endpoint_id) != (
                        current.tenant_id, current.authority_id,
                        current.authority_incarnation, current.node_id,
                        current.machine_id, current.scope_id,
                        current.agent_slot_id, current.endpoint_id,
                    )
                or old.boot_incarnation == current.boot_incarnation
                or old.endpoint_revision >= current.endpoint_revision
                or self.config.journal_generation <= old.journal_generation
                or not self.config.old_boot_isolation_ref):
            raise InvocationPreCallRejected("receiver recovery identity rejected")
        prior = self.store.dispatch_admission(invocation.operation_id)
        if prior is not None and prior.admission.purpose != "delivery.recover":
            raise InvocationPreCallRejected("marked receiver dispatch cannot recover")
        body = RecoveryBody(
            prepare_request_id=old.request_id,
            marker_receipt_id=invocation.runtime_dispatched_receipt_id,
            old_boot_incarnation=old.boot_incarnation,
            new_boot_incarnation=current.boot_incarnation,
            journal_generation=self.config.journal_generation,
            old_boot_isolation_ref=self.config.old_boot_isolation_ref,
            old_endpoint_revision=old.endpoint_revision,
            new_endpoint_revision=current.endpoint_revision,
            old_runtime_revision=old.runtime_revision,
            new_runtime_revision=current.runtime_revision,
            old_runtime_id=old.runtime_id,
            new_runtime_id=current.runtime_id,
        )
        request = self._issue(invocation, "delivery.recover", body)
        if prior is not None and prior != request:
            raise InvocationPreCallRejected("receiver recovery admission changed")
        mark_dispatched(invocation, {
            "source": self.evidence_class,
            "dispatch_id": invocation.dispatch_id,
            "receiver_prepare_receipt_id": original_receipt.receipt.receipt_id,
            "receiver_prepare_request_id": old.request_id,
            "receiver_recovery_request_id": request.admission.request_id,
            "old_boot_isolation_ref": self.config.old_boot_isolation_ref,
        })
        try:
            recovered = self._send(request)
        except (RemoteTransportRejected, ValueError, RuntimeError):
            observed = self.inspect_delivery(invocation.operation_id, "uncertain")
            prepared_projection = self._projection([original_receipt], observed["status"])
            prepared_projection["receipts"].extend(observed["receipts"])
            return prepared_projection
        state = recovered.receipt.state
        status = "delivered" if state == "runtime_acknowledged" else state
        return self._projection([original_receipt, recovered], status)
