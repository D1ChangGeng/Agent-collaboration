"""Formal application service for delayed response and Human Bridge recovery."""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any, ClassVar

from runtime.delivery_models import DeliveryEnvelope, InvocationRequest
from runtime.errors import IdempotencyConflict
from runtime.models import CommandEnvelope, CommandResult
from runtime.recovery import (
    AuthoritySnapshot,
    BridgeAuthoritySnapshot,
    IncidentOpenCommand,
    PostgresDelayedResponseAuthority,
    PostgresHumanBridgeAuthority,
)
from runtime.recovery_models import (
    BoundaryRejected,
    DispatchIdentity,
    ManualPacket,
    NativeResponseObservation,
    NormalReceipt,
    RecoveryPath,
)


def _json(value: Any) -> Any:
    return json.loads(json.dumps(value, default=lambda item: item.isoformat()))


def _when(value: Any) -> datetime:
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def _observation(value: dict[str, Any]) -> NativeResponseObservation:
    body = dict(value)
    body["identity"] = DispatchIdentity(**body["identity"])
    body["observed_at"] = _when(body["observed_at"])
    return NativeResponseObservation(**body)


def _manual_packet(value: dict[str, Any]) -> ManualPacket:
    body = dict(value)
    body["expires_at"] = _when(body["expires_at"])
    return ManualPacket(**body)


def _normal_receipt(value: dict[str, Any]) -> NormalReceipt:
    return NormalReceipt(**value)


class RecoveryService:
    """One authenticated Surface seam over the PostgreSQL recovery authorities."""

    PERMISSIONS: ClassVar[dict[str, str]] = {
        "delivery.project_native_response": "delivery.project",
        "delivery.projection.status": "delivery.read",
        "delivery.response.consume": "delivery.consume",
        "recovery.incident.open": "recovery.manage",
        "recovery.human.request": "human_bridge.send",
        "recovery.automatic.reprobe": "recovery.manage",
        "recovery.manual.receive": "human_bridge.receive",
        "recovery.manual.confirm": "human_bridge.receive",
        "recovery.incident.expire": "recovery.manage",
        "recovery.incident.status": "recovery.read",
    }

    def __init__(self, authority: Any, *, fault: Callable[[str], None] | None = None) -> None:
        self.authority = authority
        self._fault = fault or (lambda _stage: None)

    def _complete(
        self, command: CommandEnvelope, name: str, payload: dict[str, Any], state: str,
    ) -> CommandResult:
        self._fault("after_action")
        result = self._record(command, name, payload, state)
        self._fault("after_finalize")
        return result

    @staticmethod
    def _incident(cursor: Any, tenant_id: str, incident_id: str) -> dict[str, Any] | None:
        cursor.execute(
            "SELECT generation,message_id,operation_id,source_scope_id,target_scope_id,"
            "accepted_revision,accepted_state_digest,expires_at,state,applied_packet_id "
            "FROM recovery_incidents WHERE tenant_id=%s AND incident_id=%s",
            (tenant_id, incident_id),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        keys = (
            "generation", "message_id", "operation_id", "source_scope_id",
            "target_scope_id", "accepted_revision", "accepted_state_digest",
            "expires_at", "state", "applied_packet_id",
        )
        return dict(zip(keys, row, strict=True))

    def _authorize(self, cursor: Any, command: CommandEnvelope, name: str, scope_id: str) -> None:
        permission = self.PERMISSIONS[name]
        self.authority._authorize(command, cursor, permission, scope_id)

    def _projection_snapshot(
        self, cursor: Any, command: CommandEnvelope, observation: NativeResponseObservation,
    ) -> AuthoritySnapshot:
        identity = observation.identity
        cursor.execute(
            "SELECT m.envelope_json,m.packet_json,m.deadline,m.accepted_state_digest,m.policy_hash,"
            "a.invocation_json,a.dispatch_id,a.attempt_id "
            "FROM delivery_messages m JOIN delivery_attempts a "
            "ON a.tenant_id=m.tenant_id AND a.message_id=m.message_id "
            "WHERE m.tenant_id=%s AND m.message_id=%s AND a.attempt_id=%s",
            (identity.tenant_id, identity.message_id, identity.attempt_id),
        )
        row = cursor.fetchone()
        if row is None or row[5] is None:
            raise BoundaryRejected("committed invocation is unavailable")
        envelope = DeliveryEnvelope.model_validate(row[0])
        invocation = InvocationRequest.model_validate(row[5])
        packet = envelope.packet
        committed = DispatchIdentity(
            tenant_id=envelope.tenant_id,
            message_id=invocation.message_id,
            operation_id=invocation.operation_id,
            invocation_id=invocation.invocation_id,
            attempt_id=invocation.attempt_id,
            dispatch_id=invocation.dispatch_id,
            endpoint_id=envelope.endpoint_id,
            binding_revision=envelope.binding_revision,
            machine_id=envelope.machine_id,
            node_id=envelope.node_id,
            boot_incarnation=envelope.boot_incarnation,
            accepted_revision=invocation.accepted_revision,
            accepted_state_digest=invocation.accepted_state_digest,
        )
        self._authorize(cursor, command, "delivery.project_native_response", packet.target_scope_id)
        cursor.execute(
            "SELECT attempt_id FROM delivery_attempts WHERE tenant_id=%s AND message_id=%s "
            "ORDER BY ordinal DESC LIMIT 1",
            (identity.tenant_id, identity.message_id),
        )
        latest = cursor.fetchone()
        cursor.execute(
            "SELECT execution_status FROM work_items WHERE tenant_id=%s AND work_item_id=%s",
            (identity.tenant_id, packet.work_item_id),
        )
        work = cursor.fetchone()
        cursor.execute(
            "SELECT count(*) FROM enrolled_nodes n JOIN enrolled_node_bindings b "
            "ON b.tenant_id=n.tenant_id AND b.node_id=n.node_id "
            "WHERE n.tenant_id=%s AND n.node_id=%s AND n.status='active' "
            "AND b.binding_revision=%s AND b.boot_incarnation=%s AND b.status='active' "
            "AND b.expires_at>clock_timestamp()",
            (identity.tenant_id, identity.node_id, identity.binding_revision,
             identity.boot_incarnation),
        )
        producer_authenticated = cursor.fetchone()[0] == 1
        return AuthoritySnapshot(
            committed_identity=committed,
            producer_authenticated=producer_authenticated,
            current_authority_valid=True,
            task_valid=work is not None and work[0] not in {"failed", "cancelled"},
            current_attempt_id=str(latest[0]) if latest else "unavailable",
            current_accepted_revision=packet.accepted_revision,
            current_accepted_state_digest=str(row[3]),
            deadline=min(command.deadline, row[2]),
            principal_ref=command.principal_ref,
            grant_ref=command.grant_ref,
            policy_version=str(row[4]),
        )

    def _bridge_snapshot(
        self,
        cursor: Any,
        command: CommandEnvelope,
        name: str,
        incident_id: str,
        seed: dict[str, Any],
    ) -> BridgeAuthoritySnapshot:
        incident = self._incident(cursor, command.tenant_id, incident_id)
        message_id = incident["message_id"] if incident else seed.get("message_id")
        if not isinstance(message_id, str):
            raise BoundaryRejected("recovery message identity is unavailable")
        cursor.execute(
            "SELECT packet_json,deadline,accepted_state_digest,policy_hash FROM delivery_messages "
            "WHERE tenant_id=%s AND message_id=%s",
            (command.tenant_id, message_id),
        )
        message = cursor.fetchone()
        if message is None:
            raise BoundaryRejected("recovery delivery message is unavailable")
        packet = message[0]
        scope_id = incident["source_scope_id"] if incident else seed.get("source_scope_id")
        self._authorize(cursor, command, name, str(scope_id))
        cursor.execute(
            "SELECT execution_status FROM work_items WHERE tenant_id=%s AND work_item_id=%s",
            (command.tenant_id, packet["work_item_id"]),
        )
        work = cursor.fetchone()
        revision = incident["accepted_revision"] if incident else seed["accepted_revision"]
        accepted_digest = (
            incident["accepted_state_digest"] if incident else seed["accepted_state_digest"]
        )
        deadline = min(
            command.deadline,
            message[1],
            incident["expires_at"] if incident else seed["expires_at"],
        )
        return BridgeAuthoritySnapshot(
            authenticated=True,
            current_authority_valid=True,
            task_valid=work is not None and work[0] not in {"failed", "cancelled"},
            send_authorized=True,
            current_accepted_revision=int(revision),
            current_accepted_state_digest=str(accepted_digest),
            deadline=deadline,
            principal_ref=command.principal_ref,
            grant_ref=command.grant_ref,
            policy_version=str(message[3]),
        )

    def _record(
        self,
        command: CommandEnvelope,
        name: str,
        payload: dict[str, Any],
        state: str,
    ) -> CommandResult:
        result = self._result(command, state)
        extra = {"recovery": name, "payload": _json(payload)}
        digest = self.authority._hash(command, extra)
        with self.authority._connect() as connection, connection.cursor() as cursor:
            scope = self._scope(cursor, command, name, payload)
            self._authorize(cursor, command, name, scope)
            cursor.execute(
                "SELECT idempotency_key,command_type,target_id,canonical_digest,state,result_json "
                "FROM recovery_command_claims WHERE tenant_id=%s AND command_id=%s FOR UPDATE",
                (command.tenant_id, command.command_id),
            )
            claim = cursor.fetchone()
            expected = (
                command.idempotency_key, name, command.target_id, digest,
            )
            if claim is None or claim[:4] != expected:
                raise IdempotencyConflict(command.idempotency_key)
            if claim[4] == "completed":
                replay = CommandResult.model_validate(claim[5])
                return replay.model_copy(update={"duplicate": True})
            cursor.execute(
                "SELECT canonical_hash,payload_hash,hash_version,migration_state,replay_policy "
                "FROM command_dedup WHERE tenant_id=%s AND command_id=%s "
                "AND idempotency_key=%s FOR UPDATE",
                (command.tenant_id, command.command_id, command.idempotency_key),
            )
            journal = cursor.fetchone()
            if journal != (digest, digest, "v2", "current", "replay_safe"):
                raise IdempotencyConflict(command.idempotency_key)
            cursor.execute(
                "UPDATE command_dedup SET result_json=%s WHERE tenant_id=%s AND command_id=%s",
                (result.model_dump_json(), command.tenant_id, command.command_id),
            )
            self.authority._operation(cursor, command, result.operation_id)
            cursor.execute(
                "INSERT INTO domain_events(tenant_id,work_item_id,target_kind,target_id,"
                "related_work_item_id,to_state,initiated_by,lineage_mode,command_id,"
                "resulting_revision,evidence_refs,command_hash_version,canonical_hash) "
                "VALUES (%s,NULL,'recovery',%s,NULL,%s,%s,'external_command',%s,%s,'[]','v2',%s)",
                (command.tenant_id, command.target_id, state, command.principal_ref,
                 command.command_id, result.revision, digest),
            )
            self.authority._outbox(
                cursor, command, result.operation_id, "recovery.command_committed",
                {"command_type": name, "target_id": command.target_id, "state": state},
            )
            cursor.execute(
                "UPDATE recovery_command_claims SET state='completed',result_json=%s,"
                "updated_at=clock_timestamp() WHERE tenant_id=%s AND command_id=%s",
                (result.model_dump_json(), command.tenant_id, command.command_id),
            )
        return result

    @staticmethod
    def _result(command: CommandEnvelope, state: str) -> CommandResult:
        return CommandResult(
            command_id=command.command_id,
            operation_id="recovery:" + command.command_id,
            target_id=command.target_id,
            revision=command.expected_revision + 1,
            state=state,
        )

    def _scope(
        self, cursor: Any, command: CommandEnvelope, name: str, payload: dict[str, Any],
    ) -> str:
        scope = payload.get("source_scope_id") or payload.get("scope_id")
        if scope is None and "incident_id" in payload:
            incident = self._incident(cursor, command.tenant_id, payload["incident_id"])
            scope = incident["source_scope_id"] if incident else None
        if scope is None and name == "delivery.project_native_response":
            identity = payload["observation"]["identity"]
            cursor.execute(
                "SELECT packet_json FROM delivery_messages WHERE tenant_id=%s AND message_id=%s",
                (command.tenant_id, identity["message_id"]),
            )
            message = cursor.fetchone()
            scope = message[0]["target_scope_id"] if message else None
        if not isinstance(scope, str):
            raise BoundaryRejected("recovery scope is unavailable")
        return scope

    def _reserve(
        self, command: CommandEnvelope, name: str, payload: dict[str, Any],
    ) -> CommandResult | None:
        pending = self._result(command, "recovery_pending")
        extra = {"recovery": name, "payload": _json(payload)}
        digest = self.authority._hash(command, extra)
        with self.authority._connect() as connection, connection.cursor() as cursor:
            scope = self._scope(cursor, command, name, payload)
            self._authorize(cursor, command, name, scope)
            cursor.execute(
                "SELECT command_id,idempotency_key,command_type,target_id,canonical_digest,"
                "state,result_json FROM recovery_command_claims WHERE tenant_id=%s "
                "AND (command_id=%s OR idempotency_key=%s) ORDER BY command_id FOR UPDATE",
                (command.tenant_id, command.command_id, command.idempotency_key),
            )
            claims = cursor.fetchall()
            if claims:
                expected = (
                    command.command_id, command.idempotency_key, name,
                    command.target_id, digest,
                )
                if len(claims) != 1 or claims[0][:5] != expected:
                    raise IdempotencyConflict(command.idempotency_key)
                if claims[0][5] == "completed":
                    replay = CommandResult.model_validate(claims[0][6])
                    return replay.model_copy(update={"duplicate": True})
                cursor.execute(
                    "SELECT canonical_hash,payload_hash,hash_version,migration_state,replay_policy "
                    "FROM command_dedup WHERE tenant_id=%s AND command_id=%s "
                    "AND idempotency_key=%s FOR UPDATE",
                    (command.tenant_id, command.command_id, command.idempotency_key),
                )
                if cursor.fetchone() != (digest, digest, "v2", "current", "replay_safe"):
                    raise IdempotencyConflict(command.idempotency_key)
                return None
            duplicate, _digest_value = self.authority._dedup(cursor, command, pending, extra)
            if duplicate is not None:
                if duplicate.state == "recovery_pending":
                    raise IdempotencyConflict(command.idempotency_key)
                return duplicate
            cursor.execute(
                "INSERT INTO recovery_command_claims(tenant_id,command_id,idempotency_key,"
                "command_type,target_id,canonical_digest,state,result_json) "
                "VALUES (%s,%s,%s,%s,%s,%s,'pending',NULL)",
                (command.tenant_id, command.command_id, command.idempotency_key,
                 name, command.target_id, digest),
            )
        return None

    def execute(self, command: CommandEnvelope, name: str, payload: dict[str, Any]) -> Any:
        if name not in {"delivery.projection.status", "recovery.incident.status"}:
            duplicate = self._reserve(command, name, payload)
            if duplicate is not None:
                return duplicate
            self._fault("after_reserve")
        if name == "delivery.project_native_response":
            observation = _observation(payload["observation"])
            projector = PostgresDelayedResponseAuthority(
                self.authority._dsn,
                lambda cursor, item: self._projection_snapshot(cursor, command, item),
            )
            disposition = projector.project(observation)
            return self._complete(command, name, payload, disposition.disposition)
        if name == "delivery.projection.status":
            with self.authority._connect() as connection, connection.cursor() as cursor:
                self._authorize(cursor, command, name, payload["scope_id"])
                cursor.execute(
                    "SELECT projection_id,receipt_id,message_id,operation_id,disposition,"
                    "native_outcome,response_artifact_ref,response_digest,evidence_digest "
                    "FROM native_response_observations WHERE tenant_id=%s AND projection_id=%s",
                    (command.tenant_id, payload["projection_id"]),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                keys = (
                    "projection_id", "receipt_id", "message_id", "operation_id", "disposition",
                    "native_outcome", "response_artifact_ref", "response_digest", "evidence_digest",
                )
                return dict(zip(keys, row, strict=True))
        if name == "delivery.response.consume":
            with self.authority._connect() as connection, connection.cursor() as cursor:
                self._authorize(cursor, command, name, payload["scope_id"])
                cursor.execute(
                    "SELECT message_id,operation_id,response_artifact_ref,response_digest,"
                    "evidence_digest,disposition FROM native_response_observations "
                    "WHERE tenant_id=%s AND projection_id=%s FOR UPDATE",
                    (command.tenant_id, payload["projection_id"]),
                )
                row = cursor.fetchone()
                if row is None or row[5] != "applied":
                    raise BoundaryRejected("applied native response is unavailable")
                cursor.execute(
                    "SELECT consumer_command_id FROM native_response_consumptions "
                    "WHERE tenant_id=%s AND projection_id=%s FOR UPDATE",
                    (command.tenant_id, payload["projection_id"]),
                )
                prior = cursor.fetchone()
                if prior is not None and prior[0] != command.command_id:
                    raise BoundaryRejected("native response was already consumed")
                if prior is None:
                    cursor.execute(
                        "INSERT INTO native_response_consumptions(tenant_id,projection_id,"
                        "consumer_command_id) VALUES (%s,%s,%s)",
                        (command.tenant_id, payload["projection_id"], command.command_id),
                    )
            return self._complete(command, name, payload, "response_consumed")

        seed = payload
        bridge = PostgresHumanBridgeAuthority(
            self.authority._dsn,
            lambda cursor, action, incident: self._bridge_snapshot(
                cursor, command, name, incident, seed,
            ),
        )
        if name == "recovery.incident.open":
            paths = tuple(RecoveryPath(**item) for item in payload["paths"])
            incident = IncidentOpenCommand(
                incident_id=payload["incident_id"], generation=payload["generation"],
                tenant_id=command.tenant_id, message_id=payload["message_id"],
                operation_id=payload["operation_id"],
                source_scope_id=payload["source_scope_id"],
                target_scope_id=payload["target_scope_id"],
                accepted_revision=payload["accepted_revision"],
                accepted_state_digest=payload["accepted_state_digest"],
                expires_at=_when(payload["expires_at"]),
                eligible_path_ids=tuple(payload["eligible_path_ids"]), paths=paths,
                command_id=command.command_id,
            )
            state = bridge.open_incident(incident)
        elif name == "recovery.human.request":
            state = bridge.request_human(
                tenant_id=command.tenant_id, incident_id=payload["incident_id"],
                request_id=payload["request_id"], command_id=command.command_id,
            )
        elif name == "recovery.automatic.reprobe":
            state = bridge.reprobe(
                tenant_id=command.tenant_id, incident_id=payload["incident_id"],
                reprobe_id=payload["reprobe_id"], observation_ref=payload["observation_ref"],
                succeeded=payload["succeeded"], command_id=command.command_id,
            )
        elif name == "recovery.manual.receive":
            state = bridge.receive_manual(
                _manual_packet(payload["packet"]), command_id=command.command_id,
            )
        elif name == "recovery.manual.confirm":
            state = bridge.confirm_manual(
                _normal_receipt(payload["receipt"]), command_id=command.command_id,
            )
        elif name == "recovery.incident.expire":
            state = bridge.expire(
                tenant_id=command.tenant_id, incident_id=payload["incident_id"],
                command_id=command.command_id,
            )
        elif name == "recovery.incident.status":
            with self.authority._connect() as connection, connection.cursor() as cursor:
                self._authorize(cursor, command, name, payload["scope_id"])
                return self._incident(cursor, command.tenant_id, payload["incident_id"])
        else:
            raise BoundaryRejected("unsupported recovery command")
        return self._complete(command, name, payload, state)
