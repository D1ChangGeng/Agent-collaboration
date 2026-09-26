"""PostgreSQL authority for authenticated receiver transport records."""
from __future__ import annotations

import ipaddress
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from nacl.bindings import crypto_core_ed25519_is_valid_point
from pydantic import BaseModel, ConfigDict, Field

from runtime.enrollment_models import NodeCommandProof
from runtime.errors import AcceptanceGuardFailed, AuthorizationDenied, RevisionConflict
from runtime.models import CommandEnvelope, CommandResult
from runtime.receiver_crypto import key_fingerprint, sha256, verify
from runtime.receiver_models import EndpointRegistration, SignedReceipt, SignedRequest


class ReceiverDomainInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AuthorityTransportKeyRegistration(ReceiverDomainInput):
    key_id: str = Field(min_length=1, max_length=256)
    revision: int = Field(ge=1, strict=True)
    public_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    expires_at: datetime


class ConnectionReferenceRegistration(ReceiverDomainInput):
    connection_ref: str = Field(min_length=1, max_length=256)
    revision: int = Field(ge=1, strict=True)
    locator_host: str
    locator_port: int = Field(ge=1, le=65535, strict=True)
    route_class: Literal["loopback", "private", "tunnel"]
    policy_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    expires_at: datetime


class EndpointRegistrationCommand(ReceiverDomainInput):
    registration: EndpointRegistration
    registration_signature: str = Field(pattern=r"^[a-f0-9]{128}$")
    proof: NodeCommandProof


def _time(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise AcceptanceGuardFailed("receiver timestamp requires timezone")
    return value.astimezone(UTC)


def _model(model, value):
    return model.model_validate_json(json.dumps(value, default=str), strict=True)


class ReceiverTransportAuthority:
    """One transactional PostgreSQL writer for receiver trust and evidence."""

    def __init__(self, authority: Any) -> None:
        self.authority = authority

    @staticmethod
    def _result(command: CommandEnvelope, revision: int, state: str) -> CommandResult:
        return CommandResult(
            command_id=command.command_id,
            operation_id=f"op-{uuid.uuid4()}",
            target_id=command.target_id,
            revision=revision,
            state=state,
        )

    def _event(self, cursor, command, result, digest, state):
        cursor.execute(
            "INSERT INTO domain_events(tenant_id,work_item_id,target_kind,target_id,"
            "related_work_item_id,to_state,initiated_by,lineage_mode,command_id,"
            "resulting_revision,evidence_refs,command_hash_version,canonical_hash) "
            "VALUES (%s,NULL,%s,%s,NULL,%s,%s,'external_command',%s,%s,'[]','v2',%s)",
            (command.tenant_id, command.target_kind, command.target_id, state,
             command.principal_ref, command.command_id, result.revision, digest),
        )
        self.authority._operation(cursor, command, result.operation_id)
        self.authority._outbox(
            cursor, command, result.operation_id, state,
            {"target_kind": command.target_kind, "target_id": command.target_id},
        )

    def register_authority_key(self, command: CommandEnvelope,
                               request: AuthorityTransportKeyRegistration) -> CommandResult:
        if command.command_type != "receiver.key.register" or command.target_kind != "authority_transport_key":
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        request = AuthorityTransportKeyRegistration.model_validate_json(request.model_dump_json(), strict=True)
        if command.target_id != request.key_id or request.revision != command.expected_revision + 1:
            raise RevisionConflict(command.target_id, command.expected_revision, request.revision - 1)
        if not crypto_core_ed25519_is_valid_point(bytes.fromhex(request.public_key)):
            raise AcceptanceGuardFailed("receiver authority key is not a valid Ed25519 point")
        fingerprint = key_fingerprint(request.public_key)
        result = self._result(command, request.revision, "receiver_authority_key_registered")
        extra = {"request": request.model_dump(mode="json"), "fingerprint": fingerprint}
        with self.authority._connect() as connection, connection.cursor() as cursor:
            self.authority._authorize(command, cursor, "receiver.manage")
            duplicate, digest = self.authority._dedup(cursor, command, result, extra)
            if duplicate:
                return duplicate
            cursor.execute(
                "SELECT revision FROM authority_transport_keys WHERE tenant_id=%s "
                "AND authority_id=%s AND authority_incarnation=%s ORDER BY revision DESC LIMIT 1 FOR UPDATE",
                (command.tenant_id, command.authority_id, command.authority_incarnation),
            )
            prior = cursor.fetchone()
            actual_revision = int(prior[0]) if prior else 0
            if actual_revision != command.expected_revision:
                raise RevisionConflict(command.target_id, command.expected_revision, actual_revision)
            if _time(request.expires_at) <= datetime.now(UTC):
                raise AcceptanceGuardFailed("receiver authority key is expired")
            cursor.execute(
                "UPDATE authority_transport_keys SET status='retired',retired_at=clock_timestamp() "
                "WHERE tenant_id=%s AND authority_id=%s AND authority_incarnation=%s AND status='active'",
                (command.tenant_id, command.authority_id, command.authority_incarnation),
            )
            self.authority._authorize(command, cursor, "receiver.manage")
            cursor.execute(
                "INSERT INTO authority_transport_keys(tenant_id,authority_id,authority_incarnation,key_id,"
                "revision,public_key,fingerprint,status,expires_at,command_id,operation_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s)",
                (command.tenant_id, command.authority_id, command.authority_incarnation,
                 request.key_id, request.revision, request.public_key, fingerprint,
                 request.expires_at, command.command_id, result.operation_id),
            )
            self._event(cursor, command, result, digest, "receiver.authority_key_registered")
        return result

    def register_connection(self, command: CommandEnvelope,
                            request: ConnectionReferenceRegistration) -> CommandResult:
        if command.command_type != "receiver.connection.register" or command.target_kind != "connection":
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        request = ConnectionReferenceRegistration.model_validate_json(request.model_dump_json(), strict=True)
        if command.target_id != request.connection_ref:
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        address = ipaddress.ip_address(request.locator_host)
        if ((request.route_class == "loopback" and not address.is_loopback)
                or (request.route_class in {"private", "tunnel"} and not address.is_private)):
            raise AcceptanceGuardFailed("receiver connection route is outside its allowlist class")
        result = self._result(command, request.revision, "receiver_connection_registered")
        with self.authority._connect() as connection, connection.cursor() as cursor:
            self.authority._authorize(command, cursor, "receiver.manage")
            duplicate, digest = self.authority._dedup(
                cursor, command, result, {"request": request.model_dump(mode="json")},
            )
            if duplicate:
                return duplicate
            cursor.execute(
                "SELECT revision FROM deployment_connection_refs WHERE tenant_id=%s AND connection_ref=%s FOR UPDATE",
                (command.tenant_id, request.connection_ref),
            )
            prior = cursor.fetchone()
            actual_revision = int(prior[0]) if prior else 0
            if actual_revision != command.expected_revision or request.revision != actual_revision + 1:
                raise RevisionConflict(command.target_id, command.expected_revision, actual_revision)
            if _time(request.expires_at) <= datetime.now(UTC):
                raise AcceptanceGuardFailed("receiver connection reference is expired")
            self.authority._authorize(command, cursor, "receiver.manage")
            cursor.execute(
                "INSERT INTO deployment_connection_refs(tenant_id,connection_ref,revision,locator_host,"
                "locator_port,route_class,policy_digest,status,expires_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,'active',%s) "
                "ON CONFLICT(tenant_id,connection_ref) DO UPDATE SET revision=EXCLUDED.revision,"
                "locator_host=EXCLUDED.locator_host,locator_port=EXCLUDED.locator_port,"
                "route_class=EXCLUDED.route_class,policy_digest=EXCLUDED.policy_digest,"
                "status='active',valid_from=clock_timestamp(),expires_at=EXCLUDED.expires_at",
                (command.tenant_id, request.connection_ref, request.revision, request.locator_host,
                 request.locator_port, request.route_class, request.policy_digest, request.expires_at),
            )
            self._event(cursor, command, result, digest, "receiver.connection_registered")
        return result

    def register_endpoint(self, command: CommandEnvelope,
                          request: EndpointRegistrationCommand) -> CommandResult:
        if command.command_type != "endpoint.register" or command.target_kind != "endpoint":
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        request = EndpointRegistrationCommand.model_validate_json(request.model_dump_json(), strict=True)
        registration = request.registration
        if (command.target_id != registration.endpoint_id
                or registration.tenant_id != command.tenant_id
                or (registration.authority_id, registration.authority_incarnation)
                != (command.authority_id, command.authority_incarnation)):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        node_input = {
            "registration": registration.model_dump(mode="json"),
            "registration_signature": request.registration_signature,
        }
        result = self._result(command, registration.endpoint_revision, "receiver_endpoint_registered")
        with self.authority._connect() as connection, connection.cursor() as cursor:
            node, binding, valid_until = self.authority.enrollment.verify_node_command(
                cursor, command, node_input, request.proof, "endpoint.register",
                node_id=registration.node_id,
            )
            duplicate, digest = self.authority._dedup(cursor, command, result, node_input)
            if duplicate:
                return duplicate
            cursor.execute(
                "SELECT to_jsonb(r) FROM enrolled_runtimes r WHERE tenant_id=%s AND runtime_id=%s "
                "AND status='active' FOR UPDATE",
                (command.tenant_id, registration.runtime_id),
            )
            runtime_row = cursor.fetchone()
            cursor.execute(
                "SELECT key_id,public_key FROM enrolled_node_keys WHERE tenant_id=%s AND node_id=%s "
                "AND key_id=%s AND status='active' FOR UPDATE",
                (command.tenant_id, registration.node_id, binding["key_id"]),
            )
            key_row = cursor.fetchone()
            cursor.execute(
                "SELECT 1 FROM deployment_connection_refs WHERE tenant_id=%s AND connection_ref=%s "
                "AND status='active' AND expires_at>clock_timestamp() FOR UPDATE",
                (command.tenant_id, registration.connection_ref),
            )
            connection_current = cursor.fetchone()
            expected = (
                node["scope_id"], node["agent_slot_id"], binding["binding_revision"],
                binding["machine_id"], binding["boot_incarnation"],
            )
            actual = (
                registration.scope_id, registration.agent_slot_id,
                registration.node_binding_revision, registration.machine_id,
                registration.boot_incarnation,
            )
            if (runtime_row is None or key_row is None or connection_current is None
                    or actual != expected):
                raise AcceptanceGuardFailed("receiver endpoint Node/Runtime/connection is not current")
            runtime_value = runtime_row[0]
            if (runtime_value["node_id"] != registration.node_id
                    or runtime_value["node_binding_revision"] != registration.node_binding_revision
                    or runtime_value["revision"] != registration.runtime_revision
                    or runtime_value["node_boot_incarnation"] != registration.boot_incarnation):
                raise AcceptanceGuardFailed("receiver endpoint Runtime binding differs")
            verify(key_row[1], request.registration_signature, registration)
            if not datetime.now(UTC) < _time(registration.expires_at) <= _time(valid_until):
                raise AcceptanceGuardFailed("receiver endpoint expiry exceeds current Node proof")
            cursor.execute(
                "SELECT endpoint_revision FROM delivery_endpoint_registrations WHERE tenant_id=%s "
                "AND endpoint_id=%s ORDER BY endpoint_revision DESC LIMIT 1 FOR UPDATE",
                (command.tenant_id, registration.endpoint_id),
            )
            prior = cursor.fetchone()
            actual_revision = int(prior[0]) if prior else 0
            if command.expected_revision != actual_revision or registration.endpoint_revision != actual_revision + 1:
                raise RevisionConflict(command.target_id, command.expected_revision, actual_revision)
            cursor.execute(
                "UPDATE delivery_endpoint_registrations SET status='retired' WHERE tenant_id=%s "
                "AND endpoint_id=%s AND status='active'",
                (command.tenant_id, registration.endpoint_id),
            )
            self.authority._authorize(command, cursor, "endpoint.register", registration.scope_id)
            cursor.execute(
                "INSERT INTO delivery_endpoint_registrations(tenant_id,authority_id,authority_incarnation,"
                "endpoint_id,endpoint_revision,registration_id,connection_ref,node_id,node_binding_revision,"
                "runtime_id,runtime_revision,machine_id,boot_incarnation,scope_id,agent_slot_id,"
                "tls_certificate_sha256,config_sha256,node_key_id,registration_json,registration_sha256,"
                "registration_signature,proof_ref,status,expires_at,command_id,operation_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s)",
                (command.tenant_id, command.authority_id, command.authority_incarnation,
                 registration.endpoint_id, registration.endpoint_revision, registration.registration_id,
                 registration.connection_ref, registration.node_id, registration.node_binding_revision,
                 registration.runtime_id, registration.runtime_revision, registration.machine_id,
                 registration.boot_incarnation, registration.scope_id, registration.agent_slot_id,
                 registration.tls_certificate_sha256, registration.config_sha256, key_row[0],
                 registration.model_dump_json(), sha256(registration), request.registration_signature,
                 request.proof.challenge_id, registration.expires_at, command.command_id, result.operation_id),
            )
            self._event(cursor, command, result, digest, "receiver.endpoint_registered")
        return result

    def load_endpoint(self, endpoint_id: str) -> dict[str, Any]:
        with self.authority._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_jsonb(e),to_jsonb(c),k.public_key FROM delivery_endpoint_registrations e "
                "JOIN deployment_connection_refs c ON c.tenant_id=e.tenant_id AND c.connection_ref=e.connection_ref "
                "JOIN enrolled_node_keys k ON k.key_id=e.node_key_id "
                "WHERE e.tenant_id=%s AND e.endpoint_id=%s AND e.status='active' "
                "AND c.status='active' AND k.status='active' AND e.expires_at>clock_timestamp() "
                "AND c.expires_at>clock_timestamp()",
                (self.authority.tenant_id, endpoint_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise AcceptanceGuardFailed("committed receiver endpoint is unavailable")
            return {"registration": row[0], "connection": row[1], "node_public_key": row[2]}

    def load_authority_key(self) -> dict[str, Any]:
        with self.authority._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT key_id,revision,public_key,fingerprint,expires_at FROM authority_transport_keys "
                "WHERE tenant_id=%s AND authority_id=%s AND authority_incarnation=%s AND status='active' "
                "AND expires_at>clock_timestamp()",
                (self.authority.tenant_id, self.authority.context.authority_id,
                 self.authority.context.authority_incarnation),
            )
            row = cursor.fetchone()
            if row is None:
                raise AcceptanceGuardFailed("current receiver authority key is unavailable")
            return {"key_id": row[0], "revision": row[1], "public_key": row[2],
                    "fingerprint": row[3], "expires_at": row[4]}

    def delivery_receipts(self, operation_id: str) -> list[dict[str, Any]]:
        with self.authority._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT receipt_id,state,receipt_json FROM delivery_receiver_receipts "
                "WHERE tenant_id=%s AND operation_id=%s ORDER BY recorded_at,receipt_id",
                (self.authority.tenant_id, operation_id),
            )
            return [{"receipt_id": row[0], "state": row[1], "receipt": row[2]}
                    for row in cursor.fetchall()]

    def dispatch_admission(self, operation_id: str) -> SignedRequest | None:
        with self.authority._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT signed_request_json FROM delivery_transport_admissions WHERE tenant_id=%s "
                "AND operation_id=%s AND purpose IN ('delivery.dispatch','delivery.recover') "
                "ORDER BY recorded_at DESC LIMIT 1",
                (self.authority.tenant_id, operation_id),
            )
            row = cursor.fetchone()
            return _model(SignedRequest, row[0]) if row else None

    def dispatch_marker_current(self, invocation) -> bool:
        with self.authority._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM delivery_receipts WHERE tenant_id=%s AND message_id=%s "
                "AND layer='runtime_dispatched' AND receipt_id=%s AND attempt_id=%s AND dispatch_id=%s",
                (self.authority.tenant_id, invocation.message_id,
                 invocation.runtime_dispatched_receipt_id, invocation.attempt_id,
                 invocation.dispatch_id),
            )
            return cursor.fetchone() is not None

    def current_authority(self, admission) -> bool:
        try:
            with self.authority._connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    "SELECT m.command_json,e.endpoint_revision,e.runtime_id,e.runtime_revision,e.node_id,"
                    "e.machine_id,e.boot_incarnation,e.scope_id,e.agent_slot_id "
                    "FROM delivery_messages m JOIN delivery_endpoint_registrations e "
                    "ON e.tenant_id=m.tenant_id AND e.endpoint_id=m.endpoint_id "
                    "JOIN authority_transport_keys k ON k.tenant_id=m.tenant_id "
                    "AND k.authority_id=%s AND k.authority_incarnation=%s "
                    "WHERE m.tenant_id=%s AND m.message_id=%s AND m.operation_id=%s "
                    "AND e.endpoint_id=%s AND e.endpoint_revision=%s AND e.status='active' "
                    "AND e.expires_at>clock_timestamp() AND k.key_id=%s AND k.revision=%s "
                    "AND k.status='active' AND k.expires_at>clock_timestamp() FOR UPDATE OF m,e,k",
                    (admission.authority_id, admission.authority_incarnation, admission.tenant_id,
                     admission.message_id, admission.operation_id, admission.endpoint_id,
                     admission.endpoint_revision, admission.authority_key_id,
                     admission.authority_key_revision),
                )
                row = cursor.fetchone()
                if row is None or tuple(row[1:]) != (
                    admission.endpoint_revision, admission.runtime_id, admission.runtime_revision,
                    admission.node_id, admission.machine_id, admission.boot_incarnation,
                    admission.scope_id, admission.agent_slot_id,
                ):
                    return False
                command = _model(CommandEnvelope, row[0])
                self.authority._authorize(command, cursor, "message.send", admission.scope_id)
                if admission.purpose in {"delivery.dispatch", "delivery.recover"}:
                    self.authority._authorize(command, cursor, "runtime.invoke", admission.scope_id)
                return command.deadline > datetime.now(UTC) and admission.deadline > datetime.now(UTC)
        except (AuthorizationDenied, AcceptanceGuardFailed, ValueError):
            return False

    def admission(self, request_id: str) -> SignedRequest | None:
        with self.authority._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT signed_request_json FROM delivery_transport_admissions "
                "WHERE tenant_id=%s AND request_id=%s",
                (self.authority.tenant_id, request_id),
            )
            row = cursor.fetchone()
            return _model(SignedRequest, row[0]) if row else None

    def persist_admission(self, request: SignedRequest) -> SignedRequest:
        admission = request.admission
        body = request.body
        with self.authority._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT public_key FROM authority_transport_keys WHERE tenant_id=%s AND key_id=%s "
                "AND revision=%s AND status='active' AND expires_at>clock_timestamp() FOR UPDATE",
                (admission.tenant_id, admission.authority_key_id, admission.authority_key_revision),
            )
            key = cursor.fetchone()
            if key is None:
                raise AuthorizationDenied("receiver", admission.authority_key_id)
            verify(key[0], request.signature, admission)
            if admission.body_sha256 != sha256(body) or admission.deadline <= datetime.now(UTC):
                raise AcceptanceGuardFailed("receiver admission body or deadline rejected")
            cursor.execute(
                "SELECT m.command_json,m.envelope_hash,m.accepted_state_digest,"
                "a.invocation_json ->> 'selection_digest',"
                "a.invocation_digest,a.endpoint_id,a.deadline FROM delivery_messages m "
                "JOIN delivery_attempts a ON a.tenant_id=m.tenant_id AND a.message_id=m.message_id "
                "WHERE m.tenant_id=%s AND m.message_id=%s AND m.operation_id=%s AND a.attempt_id=%s "
                "AND a.dispatch_id=%s FOR UPDATE OF m,a",
                (admission.tenant_id, admission.message_id, admission.operation_id,
                 admission.attempt_id, admission.dispatch_id),
            )
            lineage = cursor.fetchone()
            if lineage is None:
                raise AcceptanceGuardFailed("receiver admission delivery lineage is unavailable")
            command = _model(CommandEnvelope, lineage[0])
            self.authority._authorize(command, cursor, "message.send", admission.scope_id)
            if admission.purpose in {"delivery.dispatch", "delivery.recover"}:
                self.authority._authorize(command, cursor, "runtime.invoke", admission.scope_id)
            cursor.execute(
                "SELECT to_jsonb(e) FROM delivery_endpoint_registrations e WHERE tenant_id=%s "
                "AND endpoint_id=%s AND endpoint_revision=%s AND status='active' "
                "AND expires_at>clock_timestamp() FOR UPDATE",
                (admission.tenant_id, admission.endpoint_id, admission.endpoint_revision),
            )
            endpoint = cursor.fetchone()
            if endpoint is None:
                raise AcceptanceGuardFailed("receiver admission endpoint is not current")
            endpoint = endpoint[0]
            expected = (
                admission.authority_id, admission.authority_incarnation,
                admission.envelope_digest, admission.accepted_state_digest,
                admission.selection_digest, admission.invocation_digest,
                admission.endpoint_id, admission.deadline,
            )
            actual = (
                self.authority.context.authority_id, self.authority.context.authority_incarnation,
                lineage[1], lineage[2], lineage[3], lineage[4], lineage[5], lineage[6],
            )
            endpoint_expected = (
                endpoint["runtime_id"], endpoint["runtime_revision"], endpoint["node_id"],
                endpoint["machine_id"], endpoint["boot_incarnation"], endpoint["scope_id"],
                endpoint["agent_slot_id"],
            )
            endpoint_actual = (
                admission.runtime_id, admission.runtime_revision, admission.node_id,
                admission.machine_id, admission.boot_incarnation, admission.scope_id,
                admission.agent_slot_id,
            )
            if expected != actual or endpoint_expected != endpoint_actual:
                lineage_names = (
                    "authority_id", "authority_incarnation", "envelope_digest",
                    "accepted_state_digest", "selection_digest", "invocation_digest",
                    "endpoint_id", "deadline",
                )
                endpoint_names = (
                    "runtime_id", "runtime_revision", "node_id", "machine_id",
                    "boot_incarnation", "scope_id", "agent_slot_id",
                )
                changed = [name for name, left, right in zip(lineage_names, expected, actual, strict=True)
                           if left != right]
                changed.extend(name for name, left, right in zip(
                    endpoint_names, endpoint_expected, endpoint_actual, strict=True,
                ) if left != right)
                raise AcceptanceGuardFailed(
                    "receiver admission immutable lineage differs: " + ",".join(changed)
                )
            signed_json = request.model_dump(mode="json")
            cursor.execute(
                "SELECT signed_request_sha256 FROM delivery_transport_admissions WHERE tenant_id=%s "
                "AND request_id=%s FOR UPDATE",
                (admission.tenant_id, admission.request_id),
            )
            prior = cursor.fetchone()
            signed_digest = sha256(request)
            if prior:
                if prior[0] != signed_digest:
                    raise AcceptanceGuardFailed("receiver admission replay changed")
                return request
            cursor.execute(
                "INSERT INTO delivery_transport_admissions(tenant_id,request_id,nonce,purpose,authority_id,"
                "authority_incarnation,authority_key_id,authority_key_revision,method,path,message_id,command_id,"
                "operation_id,attempt_id,dispatch_id,endpoint_id,endpoint_revision,runtime_id,runtime_revision,"
                "node_id,machine_id,admitted_boot_incarnation,scope_id,agent_slot_id,accepted_revision,"
                "accepted_state_digest,envelope_digest,selection_digest,invocation_digest,journal_generation,"
                "body_sha256,admission_sha256,signed_request_sha256,admission_json,body_json,signed_request_json,"
                "signature,state,issued_at,deadline) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'issued',%s,%s)",
                (admission.tenant_id, admission.request_id, admission.nonce, admission.purpose,
                 admission.authority_id, admission.authority_incarnation, admission.authority_key_id,
                 admission.authority_key_revision, admission.method, admission.path, admission.message_id,
                 admission.command_id, admission.operation_id, admission.attempt_id, admission.dispatch_id,
                 admission.endpoint_id, admission.endpoint_revision, admission.runtime_id,
                 admission.runtime_revision, admission.node_id, admission.machine_id,
                 admission.boot_incarnation, admission.scope_id, admission.agent_slot_id,
                 admission.accepted_revision, admission.accepted_state_digest, admission.envelope_digest,
                 admission.selection_digest, admission.invocation_digest, admission.journal_generation,
                 admission.body_sha256, sha256(admission), signed_digest,
                 admission.model_dump_json(), json.dumps(body, sort_keys=True),
                 json.dumps(signed_json, sort_keys=True), request.signature,
                 admission.issued_at, admission.deadline),
            )
        return request

    def persist_receipt(self, signed: SignedReceipt) -> SignedReceipt:
        receipt = signed.receipt
        with self.authority._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT a.signed_request_json,e.node_key_id,k.public_key FROM delivery_transport_admissions a "
                "JOIN delivery_endpoint_registrations e ON e.tenant_id=a.tenant_id "
                "AND e.endpoint_id=a.endpoint_id AND e.endpoint_revision=a.endpoint_revision "
                "JOIN enrolled_node_keys k ON k.key_id=e.node_key_id "
                "WHERE a.tenant_id=%s AND a.request_id=%s AND e.status='active' AND k.status='active' FOR UPDATE",
                (receipt.tenant_id, receipt.request_id),
            )
            row = cursor.fetchone()
            if row is None or row[1] != signed.node_key_id:
                raise AcceptanceGuardFailed("receiver receipt current Node key is unavailable")
            request = _model(SignedRequest, row[0])
            verify(row[2], signed.signature, receipt)
            admission = request.admission
            fields = (
                "tenant_id", "authority_id", "authority_incarnation", "message_id", "command_id",
                "operation_id", "attempt_id", "dispatch_id", "endpoint_id", "endpoint_revision",
                "runtime_id", "runtime_revision", "node_id", "machine_id", "boot_incarnation",
                "scope_id", "agent_slot_id", "accepted_revision", "accepted_state_digest",
                "envelope_digest", "selection_digest", "invocation_digest", "journal_generation",
            )
            if (any(getattr(receipt, field) != getattr(admission, field) for field in fields)
                    or receipt.challenge_nonce != admission.nonce
                    or receipt.request_sha256 != sha256({"admission": admission.model_dump(mode="json"),
                                                        "body": request.body})):
                raise AcceptanceGuardFailed("receiver receipt identity differs from admission")
            receipt_json = receipt.model_dump(mode="json")
            signed_json = signed.model_dump(mode="json")
            cursor.execute(
                "INSERT INTO delivery_receiver_receipts(tenant_id,receipt_id,request_id,target_request_id,"
                "readback_request_id,challenge_nonce,node_id,node_binding_revision,node_key_id,operation_id,"
                "attempt_id,dispatch_id,state,receipt_json,receipt_sha256,signed_receipt_sha256,"
                "signed_receipt_json,signature,observed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                "%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,receipt_id) DO NOTHING",
                (receipt.tenant_id, receipt.receipt_id, receipt.request_id, receipt.target_request_id,
                 receipt.readback_request_id, receipt.challenge_nonce, receipt.node_id,
                 receipt.node_binding_revision, signed.node_key_id, receipt.operation_id,
                 receipt.attempt_id, receipt.dispatch_id, receipt.state,
                 json.dumps(receipt_json, sort_keys=True), sha256(receipt), sha256(signed),
                 json.dumps(signed_json, sort_keys=True), signed.signature, receipt.observed_at),
            )
            state = {
                "prepared": "prepared", "runtime_dispatched": "runtime_dispatched",
                "runtime_acknowledged": "completed", "uncertain": "uncertain",
                "blocked": "blocked", "readback": "completed",
            }[receipt.state]
            cursor.execute(
                "UPDATE delivery_transport_admissions SET state=%s WHERE tenant_id=%s AND request_id=%s",
                (state, receipt.tenant_id, receipt.request_id),
            )
        return signed
