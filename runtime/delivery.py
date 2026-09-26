from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

import psycopg

from runtime.delivery_models import (
    TERMINAL_STATES,
    DeliveryEnvelope,
    DeliveryPacket,
    EndpointBindingRequest,
    InvocationRequest,
)
from runtime.delivery_node import (
    DeliveryBoundaryRejected,
    DeliveryTransportError,
    InvocationPreCallRejected,
    LocalNodeEndpoint,
    invocation_for,
    logical_payload,
)
from runtime.errors import AuthorizationDenied, RevisionConflict
from runtime.models import AuthenticatedContext, CommandEnvelope, CommandResult
from runtime.node import RECEIPT_LAYERS, OperationIdentityConflict


def digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


class DeliveryRejected(RuntimeError):
    def __init__(self, code, state="blocked"):
        self.code, self.state = code, state
        super().__init__(code)


class DeliveryService:
    """One authenticated Domain command service and its explicitly bound endpoints."""

    def __init__(self, authority, endpoints: dict[str, LocalNodeEndpoint]):
        self.authority, self.endpoints = authority, dict(endpoints)

    @staticmethod
    def _now(cursor):
        cursor.execute("SELECT clock_timestamp()")
        return cursor.fetchone()[0]

    @staticmethod
    def _event(cursor, command, result, hashed, state, work_item_id=None):
        cursor.execute(
            "INSERT INTO domain_events(tenant_id,work_item_id,target_kind,target_id,related_work_item_id,"
            "to_state,initiated_by,lineage_mode,command_id,resulting_revision,evidence_refs,command_hash_version,canonical_hash) "
            "VALUES (%s,NULL,'message',%s,%s,%s,%s,'external_command',%s,%s,'[]','v2',%s)",
            (command.tenant_id, command.target_id, work_item_id, state, command.principal_ref,
             command.command_id, result.revision, hashed),
        )

    def bind_endpoint(self, command: CommandEnvelope, request: EndpointBindingRequest):
        if command.command_type != "message.bind" or command.target_kind != "message":
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        request = EndpointBindingRequest.model_validate_json(request.model_dump_json(), strict=True)
        endpoint = self.endpoints.get(command.target_id)
        if endpoint is None:
            raise DeliveryRejected("endpoint_not_configured")
        description = endpoint.descriptor()
        if (description["scope_id"], description["agent_slot_id"]) != (request.scope_id, request.agent_slot_id):
            raise DeliveryRejected("endpoint_scope_mismatch")
        result = CommandResult(command_id=command.command_id, operation_id=f"op-{uuid.uuid4()}",
                               target_id=command.target_id, revision=command.expected_revision + 1, state="endpoint_bound")
        with self.authority._connect() as connection, connection.cursor() as cursor:
            self.authority._authorize(command, cursor, "delivery.manage", request.scope_id)
            duplicate, hashed = self.authority._dedup(cursor, command, result, {"binding": request.model_dump(mode="json"), "node": description})
            if duplicate:
                return duplicate
            cursor.execute("SELECT 1 FROM agent_slots WHERE tenant_id=%s AND scope_id=%s AND agent_slot_id=%s AND status='active' FOR UPDATE",
                           (command.tenant_id, request.scope_id, request.agent_slot_id))
            if not cursor.fetchone():
                raise DeliveryRejected("target_slot_unavailable")
            # All delivery commands lock command/grant, Scope/Slot and endpoint
            # in that order. This avoids an endpoint/slot inversion with send.
            cursor.execute("SELECT revision FROM delivery_endpoints WHERE tenant_id=%s AND endpoint_id=%s FOR UPDATE",
                           (command.tenant_id, command.target_id))
            prior = cursor.fetchone()
            revision = prior[0] if prior else 0
            if revision != command.expected_revision:
                raise RevisionConflict(command.target_id, command.expected_revision, revision)
            if request.expires_at <= self._now(cursor):
                raise DeliveryRejected("binding_expired", "expired")
            # Locks and storage can outlive a short Grant. Recheck authority at
            # the actual write boundary using the database clock.
            self.authority._authorize(command, cursor, "delivery.manage", request.scope_id)
            cursor.execute(
                "INSERT INTO delivery_endpoints(tenant_id,endpoint_id,revision,scope_id,agent_slot_id,machine_id,node_id,"
                "boot_incarnation,supports_invoke,evidence_class,expires_at,command_id,operation_id) "
                "SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s WHERE clock_timestamp()<%s "
                "ON CONFLICT(tenant_id,endpoint_id) DO UPDATE SET revision=EXCLUDED.revision,scope_id=EXCLUDED.scope_id,"
                "agent_slot_id=EXCLUDED.agent_slot_id,machine_id=EXCLUDED.machine_id,node_id=EXCLUDED.node_id,"
                "boot_incarnation=EXCLUDED.boot_incarnation,supports_invoke=EXCLUDED.supports_invoke,evidence_class=EXCLUDED.evidence_class,"
                "expires_at=EXCLUDED.expires_at,status='active',command_id=EXCLUDED.command_id,operation_id=EXCLUDED.operation_id",
                (command.tenant_id, command.target_id, result.revision, request.scope_id, request.agent_slot_id,
                 description["machine_id"], description["node_id"], description["boot_incarnation"], description["supports_invoke"],
                 description["evidence_class"], request.expires_at, command.command_id, result.operation_id, command.deadline),
            )
            if cursor.rowcount != 1:
                raise DeliveryRejected("binding_authorization_expired", "expired")
            self._event(cursor, command, result, hashed, "message.endpoint_bound")
            self.authority._operation(cursor, command, result.operation_id)
            self.authority._outbox(cursor, command, result.operation_id, "message.endpoint_bound", {"endpoint_id": command.target_id})
        return result

    def _boundary(self, cursor, authority, command, packet, endpoint_id, revision, *, recovery=False):
        if min(command.deadline, packet.deadline) <= self._now(cursor):
            raise DeliveryRejected("deadline_expired", "expired")
        authority._authorize(command, cursor, "message.send", packet.target_scope_id)
        if packet.activation == "invoke":
            authority._authorize(command, cursor, "runtime.invoke", packet.target_scope_id)
        cursor.execute(
            "SELECT w.scope_id,w.revision,w.source_baseline,s.policy FROM work_items w "
            "JOIN scopes s ON s.scope_id=w.scope_id AND s.tenant_id=w.tenant_id "
            "WHERE w.tenant_id=%s AND w.work_item_id=%s AND s.status='active' FOR UPDATE OF w,s",
            (command.tenant_id, packet.work_item_id),
        )
        work = cursor.fetchone()
        if work is None or work[:3] != (packet.target_scope_id, command.expected_revision, packet.source_baseline):
            raise DeliveryRejected("work_item_precondition_changed")
        # Context ownership is independent of the receiving long-lived AgentSlot.
        # Cross-Scope delivery needs a separate explicit relationship policy;
        # this initial profile accepts only a target in the WorkItem's Scope.
        cursor.execute("SELECT 1 FROM agent_slots WHERE tenant_id=%s AND scope_id=%s AND agent_slot_id=%s "
                       "AND status='active' FOR UPDATE",
                       (command.tenant_id, packet.target_scope_id, packet.target_agent_slot_id))
        if cursor.fetchone() is None:
            raise DeliveryRejected("target_slot_unavailable")
        cursor.execute("SELECT to_jsonb(a) FROM accepted_state_revisions a WHERE tenant_id=%s AND work_item_id=%s "
                       "AND readiness_snapshot=FALSE ORDER BY revision DESC LIMIT 1 FOR UPDATE",
                       (command.tenant_id, packet.work_item_id))
        accepted = cursor.fetchone()
        accepted_state = accepted[0] if accepted else {
            "tenant_id": command.tenant_id,
            "work_item_id": packet.work_item_id,
            "revision": 0,
            "state": "genesis",
        }
        if accepted_state["revision"] != packet.accepted_revision:
            raise DeliveryRejected("accepted_revision_changed")
        cursor.execute("SELECT to_jsonb(e) FROM delivery_endpoints e WHERE tenant_id=%s AND endpoint_id=%s FOR UPDATE",
                       (command.tenant_id, endpoint_id))
        found = cursor.fetchone()
        if not found:
            raise DeliveryRejected("endpoint_binding_missing")
        binding = found[0]
        if ((binding["revision"] < revision if recovery else binding["revision"] != revision) or binding["status"] != "active"
                or binding["scope_id"] != packet.target_scope_id or binding["agent_slot_id"] != packet.target_agent_slot_id):
            raise DeliveryRejected("endpoint_binding_changed")
        if datetime.fromisoformat(binding["expires_at"]) <= self._now(cursor):
            raise DeliveryRejected("endpoint_binding_expired", "expired")
        if packet.activation == "invoke" and not binding["supports_invoke"] and not recovery:
            raise DeliveryRejected("invoke_endpoint_unavailable")
        authority._authorize(command, cursor, "message.send", packet.target_scope_id)
        if packet.activation == "invoke":
            authority._authorize(command, cursor, "runtime.invoke", packet.target_scope_id)
        return binding, digest(work[3]), digest(accepted_state)

    def send_message(self, command: CommandEnvelope, packet: DeliveryPacket, *, endpoint_id: str, binding_revision: int):
        if command.command_type != "message.send" or command.target_kind != "message":
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        packet = DeliveryPacket.model_validate_json(packet.model_dump_json(), strict=True)
        if packet.deadline > command.deadline or len(packet.model_dump_json().encode()) > 65536:
            raise DeliveryRejected("packet_bound_exceeded")
        if not endpoint_id or type(binding_revision) is not int or binding_revision < 1:
            raise DeliveryRejected("invalid_endpoint_selection")
        extra = {"packet": packet.model_dump(mode="json"), "endpoint_id": endpoint_id, "binding_revision": binding_revision}
        result = CommandResult(command_id=command.command_id, operation_id=f"op-{uuid.uuid4()}",
                               target_id=command.target_id, revision=command.expected_revision, state="message_queued")
        with self.authority._connect() as connection, connection.cursor() as cursor:
            self.authority._authorize(command, cursor, "message.send", packet.target_scope_id)
            if packet.activation == "invoke":
                self.authority._authorize(command, cursor, "runtime.invoke", packet.target_scope_id)
            duplicate, hashed = self.authority._dedup(cursor, command, result, extra)
            if duplicate:
                return duplicate
            binding, policy_hash, accepted_state_digest = self._boundary(
                cursor, self.authority, command, packet, endpoint_id, binding_revision,
            )
            envelope = DeliveryEnvelope(tenant_id=command.tenant_id, message_id=command.target_id,
                authority_id=command.authority_id, authority_incarnation=command.authority_incarnation,
                principal_ref=command.principal_ref, grant_ref=command.grant_ref,
                command_id=command.command_id, operation_id=result.operation_id, endpoint_id=endpoint_id,
                binding_revision=binding_revision, machine_id=binding["machine_id"], node_id=binding["node_id"],
                boot_incarnation=binding["boot_incarnation"], accepted_state_digest=accepted_state_digest,
                packet=packet)
            self.authority._operation(cursor, command, result.operation_id)
            cursor.execute("UPDATE operations SET provider_workflow_id=%s WHERE operation_id=%s",
                           (f"acs-delivery/{result.operation_id}", result.operation_id))
            cursor.execute(
                "INSERT INTO delivery_messages(tenant_id,message_id,command_id,operation_id,endpoint_id,binding_revision,"
                "packet_json,command_json,canonical_hash,envelope_json,envelope_hash,state,deadline,maximum_attempts,retry_delay_seconds,"
                "policy_hash,accepted_state_digest,receipt_high_water) "
                "SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'queued',%s,%s,%s,%s,%s,'accepted_by_authority' "
                "WHERE clock_timestamp()<%s",
                (command.tenant_id, command.target_id, command.command_id, result.operation_id, endpoint_id, binding_revision,
                 packet.model_dump_json(), command.model_dump_json(), hashed, envelope.model_dump_json(),
                 digest(envelope.model_dump(mode="json")), packet.deadline, packet.maximum_attempts, packet.retry_delay_seconds,
                 policy_hash, accepted_state_digest, packet.deadline),
            )
            if cursor.rowcount != 1:
                raise DeliveryRejected("deadline_expired", "expired")
            self._event(cursor, command, result, hashed, "message.queued", packet.work_item_id)
            cursor.execute("INSERT INTO outbox(tenant_id,message_id,operation_id,topic,payload) VALUES (%s,%s,%s,'message.delivery',%s)",
                           (command.tenant_id, command.target_id, result.operation_id,
                            json.dumps({"tenant_id": command.tenant_id, "message_id": command.target_id, "operation_id": result.operation_id})))
            receipt_id = f"delivery:{command.target_id}:accepted_by_authority"
            cursor.execute(
                "INSERT INTO delivery_receipts(tenant_id,message_id,receipt_id,layer,evidence_json) "
                "VALUES (%s,%s,%s,'accepted_by_authority',%s)",
                (command.tenant_id, command.target_id, receipt_id,
                 json.dumps({"receipt_id": receipt_id, "operation_id": result.operation_id,
                             "command_id": command.command_id, "canonical_hash": hashed,
                             "envelope_hash": digest(envelope.model_dump(mode="json")),
                             "accepted_revision": packet.accepted_revision,
                             "accepted_state_digest": accepted_state_digest})),
            )
        return result  # accepted_by_authority becomes visible only after this commit.

    def inspect(self, command, message_id):
        if command.command_type != "message.read" or command.target_kind != "message" or command.target_id != message_id:
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        with self.authority._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT to_jsonb(m) FROM delivery_messages m WHERE tenant_id=%s AND message_id=%s",
                           (command.tenant_id, message_id))
            row = cursor.fetchone()
            if row is None:
                raise DeliveryRejected("message_missing")
            self.authority._authorize(command, cursor, "message.read", row[0]["packet_json"]["target_scope_id"])
            cursor.execute("SELECT layer,evidence_json FROM delivery_receipts WHERE tenant_id=%s AND message_id=%s ORDER BY observed_at",
                           (command.tenant_id, message_id))
            return {"message": row[0], "receipts": cursor.fetchall()}


class DeliveryDispatcher:
    """Recover a committed operation; never invent a message, goal or turn.

    A session-level lock spans the durable attempt-start commit and local RPC.
    A dead Core releases that lock; the next Core preserves and closes its
    interrupted attempt before retrying the same logical identities.
    """

    def __init__(self, service: DeliveryService, *, worker_id="local-delivery-core"):
        self.service, self.worker_id = service, worker_id

    def after_claim(self, identity):
        """After durable dispatch preparation, before any Node call; fault seam.

        A pinned activation location means possibly dispatched after this point,
        never proof of an actual invoke. Recovery may retry only that location.
        """

    def _failure(self, cursor, row, error):
        if isinstance(error, DeliveryRejected):
            status, code = error.state, error.code
        elif isinstance(error, AuthorizationDenied):
            status, code = "blocked", "current_grant_denied"
        elif isinstance(error, InvocationPreCallRejected):
            status, code = "blocked", "native_pre_call_rejected"
        elif isinstance(error, (DeliveryBoundaryRejected, OperationIdentityConflict)):
            status, code = "blocked", "node_boundary_rejected"
        else:
            status = "budget_exhausted" if row["attempts"] >= row["maximum_attempts"] else "retry_wait"
            code = "transport_ack_unavailable"
        self._finish(cursor, row, status, code)
        return {"status": status, "message_id": row["message_id"], "attempts": row["attempts"],
                "retry_after_seconds": row["retry_delay_seconds"]}

    @staticmethod
    def _defer_prepared(cursor, row):
        cursor.execute(
            "UPDATE delivery_messages SET state='retry_wait',last_error='transport_ack_unavailable',"
            "next_attempt_at=clock_timestamp()+(retry_delay_seconds*interval '1 second') "
            "WHERE tenant_id=%s AND message_id=%s",
            (row["tenant_id"], row["message_id"]),
        )
        return {
            "status": "retry_wait",
            "message_id": row["message_id"],
            "attempts": row["attempts"],
            "retry_after_seconds": row["retry_delay_seconds"],
        }

    def pending(self, limit=16):
        if not 1 <= limit <= 64:
            raise ValueError("bounded scan required")
        with self.service.authority._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT m.tenant_id,m.message_id,m.operation_id FROM delivery_messages m "
                "JOIN outbox o ON o.tenant_id=m.tenant_id AND o.message_id=m.message_id AND o.operation_id=m.operation_id "
                "JOIN operations op ON op.operation_id=m.operation_id AND op.tenant_id=m.tenant_id "
                "WHERE o.topic='message.delivery' AND op.status='committed' "
                "AND m.state IN ('queued','delivering','retry_wait') AND m.next_attempt_at<=clock_timestamp() "
                "AND m.tenant_id=%s ORDER BY m.created_at LIMIT %s",
                (self.service.authority.tenant_id, limit),
            )
            return [dict(zip(("tenant_id", "message_id", "operation_id"), row, strict=True)) for row in cursor.fetchall()]

    def _load(self, cursor, identity):
        cursor.execute(
            "SELECT to_jsonb(m) FROM delivery_messages m WHERE m.tenant_id=%s "
            "AND m.message_id=%s AND m.operation_id=%s FOR UPDATE",
            (identity["tenant_id"], identity["message_id"], identity["operation_id"]),
        )
        row = cursor.fetchone()
        if row is None:
            raise DeliveryRejected("committed_outbox_missing")
        message = row[0]
        expected_identity = {
            "tenant_id": message["tenant_id"],
            "message_id": message["message_id"],
            "operation_id": message["operation_id"],
        }
        cursor.execute(
            "SELECT topic,payload FROM outbox WHERE tenant_id=%s AND message_id=%s AND operation_id=%s",
            tuple(expected_identity.values()),
        )
        outbox = cursor.fetchone()
        cursor.execute(
            "SELECT command_id,provider,provider_workflow_id,status FROM operations "
            "WHERE tenant_id=%s AND operation_id=%s",
            (message["tenant_id"], message["operation_id"]),
        )
        operation = cursor.fetchone()
        cursor.execute(
            "SELECT canonical_hash,result_json FROM command_dedup WHERE tenant_id=%s AND command_id=%s",
            (message["tenant_id"], message["command_id"]),
        )
        dedup = cursor.fetchone()
        cursor.execute(
            "SELECT target_kind,target_id,related_work_item_id,to_state,command_id,resulting_revision,canonical_hash "
            "FROM domain_events WHERE tenant_id=%s AND command_id=%s",
            (message["tenant_id"], message["command_id"]),
        )
        event_rows = cursor.fetchall()
        cursor.execute(
            "SELECT receipt_id,evidence_json FROM delivery_receipts WHERE tenant_id=%s AND message_id=%s "
            "AND layer='accepted_by_authority'",
            (message["tenant_id"], message["message_id"]),
        )
        accepted_receipt = cursor.fetchone()
        expected_workflow = f"acs-delivery/{message['operation_id']}"
        expected_event = (
            "message", message["message_id"], message["packet_json"]["work_item_id"],
            "message.queued", message["command_id"], message["command_json"]["expected_revision"],
            message["canonical_hash"],
        )
        expected_receipt_id = f"delivery:{message['message_id']}:accepted_by_authority"
        receipt_evidence = accepted_receipt[1] if accepted_receipt else None
        if (
            outbox is None or outbox[0] != "message.delivery" or outbox[1] != expected_identity
            or operation is None
            or operation != (message["command_id"], "temporal", expected_workflow, "committed")
            or dedup is None or dedup[0] != message["canonical_hash"]
            or dedup[1].get("operation_id") != message["operation_id"]
            or dedup[1].get("command_id") != message["command_id"]
            or dedup[1].get("target_id") != message["message_id"]
            or event_rows != [expected_event]
            or accepted_receipt is None or accepted_receipt[0] != expected_receipt_id
            or receipt_evidence.get("receipt_id") != expected_receipt_id
            or receipt_evidence.get("operation_id") != message["operation_id"]
            or receipt_evidence.get("command_id") != message["command_id"]
            or receipt_evidence.get("canonical_hash") != message["canonical_hash"]
            or receipt_evidence.get("accepted_state_digest") != message["accepted_state_digest"]
        ):
            raise DeliveryRejected("domain_ledger_conflict")
        return message

    def _authorize(self, cursor, row):
        command = CommandEnvelope.model_validate_json(json.dumps(row["command_json"]), strict=True)
        envelope = DeliveryEnvelope.model_validate_json(json.dumps(row["envelope_json"]), strict=True)
        if (digest(envelope.model_dump(mode="json")) != row["envelope_hash"] or envelope.packet.model_dump(mode="json") != row["packet_json"]
                or (envelope.tenant_id, envelope.message_id, envelope.operation_id, envelope.command_id)
                != (row["tenant_id"], row["message_id"], row["operation_id"], row["command_id"])):
            raise DeliveryRejected("durable_message_corrupt")
        extra = {"packet": row["packet_json"], "endpoint_id": row["endpoint_id"], "binding_revision": row["binding_revision"]}
        if command.canonical_hash(extra) != row["canonical_hash"]:
            raise DeliveryRejected("durable_command_corrupt")
        if any(getattr(envelope, key) != getattr(command, key) for key in (
            "authority_id", "authority_incarnation", "principal_ref", "grant_ref",
        )):
            raise DeliveryRejected("durable_authorization_reference_mismatch")
        ctx = AuthenticatedContext(command.tenant_id, command.authority_id, command.authority_incarnation,
                                   command.principal_ref, command.grant_ref)
        # Only the trusted committed ledger creates this recovery context.
        authority = type(self.service.authority)(self.service.authority._dsn, context=ctx)
        binding, policy_hash, accepted_state_digest = self.service._boundary(
            cursor, authority, command, envelope.packet,
            row["endpoint_id"], row["binding_revision"], recovery=True,
        )
        if policy_hash != row["policy_hash"]:
            raise DeliveryRejected("scope_policy_changed")
        if accepted_state_digest != row["accepted_state_digest"] or envelope.accepted_state_digest != accepted_state_digest:
            raise DeliveryRejected("accepted_state_digest_changed")
        if (envelope.packet.activation == "invoke" and row["activation_node_id"] is not None
                and (row["activation_node_id"], row["activation_machine_id"]) != (binding["node_id"], binding["machine_id"])):
            raise DeliveryRejected("activation_location_requires_reconciliation", "uncertain")
        return envelope.model_copy(update={"machine_id": binding["machine_id"], "node_id": binding["node_id"],
                                            "boot_incarnation": binding["boot_incarnation"], "binding_revision": binding["revision"]}), binding

    @staticmethod
    def _selection(row, binding):
        return {
            "endpoint_id": row["endpoint_id"],
            "revision": binding["revision"],
            "scope_id": binding["scope_id"],
            "agent_slot_id": binding["agent_slot_id"],
            "machine_id": binding["machine_id"],
            "node_id": binding["node_id"],
            "boot_incarnation": binding["boot_incarnation"],
            "supports_invoke": binding["supports_invoke"],
            "evidence_class": binding["evidence_class"],
            "expires_at": str(binding["expires_at"]),
        }

    @staticmethod
    def _endpoint_matches(endpoint, selection):
        descriptor = endpoint.descriptor()
        keys = (
            "scope_id", "agent_slot_id", "machine_id", "node_id", "boot_incarnation",
            "supports_invoke", "evidence_class",
        )
        return all(descriptor[key] == selection[key] for key in keys)

    def _load_attempt(self, cursor, row):
        cursor.execute(
            "SELECT to_jsonb(a) FROM delivery_attempts a WHERE tenant_id=%s AND message_id=%s "
            "AND ordinal=%s FOR UPDATE",
            (row["tenant_id"], row["message_id"], row["attempts"]),
        )
        found = cursor.fetchone()
        if found is None:
            raise DeliveryRejected("delivery_attempt_missing")
        return found[0]

    def _selected_endpoint(self, cursor, row, attempt):
        envelope, binding = self._authorize(cursor, row)
        selection = self._selection(row, binding)
        if selection != attempt["selection_json"] or digest(selection) != attempt["selection_digest"]:
            raise DeliveryRejected("attempt_selection_changed")
        endpoint = self.service.endpoints.get(selection["endpoint_id"])
        if endpoint is None:
            raise DeliveryTransportError("endpoint_unavailable")
        if not self._endpoint_matches(endpoint, selection):
            raise DeliveryRejected("configured_endpoint_changed")
        if envelope.packet.activation == "invoke":
            expected = invocation_for(envelope, attempt["attempt_id"])
            if attempt["invocation_json"] is None:
                raise DeliveryRejected("immutable_invocation_missing")
            invocation = InvocationRequest.model_validate_json(
                json.dumps(attempt["invocation_json"]), strict=True,
            )
            if invocation != expected or digest(invocation.model_dump(mode="json")) != attempt["invocation_digest"]:
                raise DeliveryRejected("immutable_invocation_changed")
        return envelope, endpoint

    @staticmethod
    def _record_receipt(cursor, row, receipt_id, layer, evidence, *, attempt_id=None, dispatch_id=None):
        if layer not in RECEIPT_LAYERS:
            raise DeliveryRejected("unknown_receipt_layer")
        cursor.execute(
            "SELECT receipt_id,evidence_json,attempt_id,dispatch_id FROM delivery_receipts "
            "WHERE tenant_id=%s AND message_id=%s AND layer=%s",
            (row["tenant_id"], row["message_id"], layer),
        )
        previous = cursor.fetchone()
        expected = (receipt_id, evidence, attempt_id, dispatch_id)
        if previous is not None and previous != expected:
            raise DeliveryRejected("receipt_projection_conflict")
        if previous is None:
            cursor.execute(
                "INSERT INTO delivery_receipts(tenant_id,message_id,receipt_id,layer,evidence_json,attempt_id,dispatch_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (row["tenant_id"], row["message_id"], receipt_id, layer,
                 json.dumps(evidence), attempt_id, dispatch_id),
            )
        cursor.execute(
            "SELECT receipt_high_water FROM delivery_messages WHERE tenant_id=%s AND message_id=%s FOR UPDATE",
            (row["tenant_id"], row["message_id"]),
        )
        high_water = cursor.fetchone()[0]
        if RECEIPT_LAYERS.index(layer) > RECEIPT_LAYERS.index(high_water):
            cursor.execute(
                "UPDATE delivery_messages SET receipt_high_water=%s WHERE tenant_id=%s AND message_id=%s",
                (layer, row["tenant_id"], row["message_id"]),
            )

    @staticmethod
    def _finish(cursor, row, state, code=None):
        cursor.execute("UPDATE delivery_messages SET state=%s,last_error=%s,next_attempt_at=clock_timestamp()+retry_delay_seconds*interval '1 second' "
                       "WHERE tenant_id=%s AND message_id=%s", (state, code, row["tenant_id"], row["message_id"]))
        cursor.execute("UPDATE delivery_attempts SET status=%s,error_code=%s,finished_at=clock_timestamp() "
                       "WHERE tenant_id=%s AND message_id=%s AND ordinal=%s AND finished_at IS NULL",
                       (state, code, row["tenant_id"], row["message_id"], row["attempts"]))

    @staticmethod
    def _project(cursor, row, observation):
        receipts = observation["receipts"]
        for receipt in receipts:
            if receipt["layer"] == "accepted_by_authority":
                continue  # The actual Domain commit receipt remains authoritative.
            DeliveryDispatcher._record_receipt(
                cursor, row, receipt["receipt_id"], receipt["layer"], receipt["evidence"],
                attempt_id=receipt["evidence"].get("attempt_id"),
                dispatch_id=receipt["evidence"].get("dispatch_id"),
            )
        inbox = next((item for item in receipts if item["layer"] == "target_inbox_committed"), None)
        if not inbox:
            raise DeliveryRejected("inbox_ack_missing")
        cursor.execute("SELECT target_agent_slot_id,payload FROM inbox_messages WHERE tenant_id=%s AND message_id=%s FOR UPDATE",
                       (row["tenant_id"], row["message_id"]))
        previous = cursor.fetchone()
        target = row["packet_json"]["target_agent_slot_id"]
        logical = logical_payload(DeliveryEnvelope.model_validate_json(json.dumps(row["envelope_json"]), strict=True))
        if previous and previous != (target, logical):
            raise DeliveryRejected("inbox_projection_conflict")
        cursor.execute("INSERT INTO inbox_messages(tenant_id,message_id,target_agent_slot_id,payload,receipt_json) "
                       "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                       (row["tenant_id"], row["message_id"], target, json.dumps(logical), json.dumps(inbox["evidence"])))
        cursor.execute("UPDATE outbox SET delivered_at=COALESCE(delivered_at,clock_timestamp()) WHERE tenant_id=%s AND message_id=%s AND operation_id=%s",
                       (row["tenant_id"], row["message_id"], row["operation_id"]))

    def dispatch(self, identity):
        if set(identity) != {"tenant_id", "message_id", "operation_id"} or identity["tenant_id"] != self.service.authority.tenant_id:
            raise DeliveryRejected("invalid_committed_operation_identity")
        key = int.from_bytes(hashlib.sha256(json.dumps(["delivery-dispatch", identity], sort_keys=True).encode()).digest()[:8], "big", signed=True)
        with psycopg.connect(self.service.authority._dsn, autocommit=True) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", (key,))
            if not cursor.fetchone()[0]:
                return {"status": "busy", "retry_after_seconds": 1}
            try:
                new_attempt = False
                with connection.transaction():
                    try:
                        row = self._load(cursor, identity)
                    except DeliveryRejected as error:
                        cursor.execute(
                            "SELECT to_jsonb(m) FROM delivery_messages m WHERE tenant_id=%s "
                            "AND message_id=%s AND operation_id=%s FOR UPDATE",
                            (identity["tenant_id"], identity["message_id"], identity["operation_id"]),
                        )
                        found = cursor.fetchone()
                        if found is None:
                            raise
                        row = found[0]
                        self._finish(cursor, row, error.state, error.code)
                        return {"status": error.state, "message_id": row["message_id"],
                                "attempts": row["attempts"]}
                    if row["state"] in TERMINAL_STATES:
                        return {"status": row["state"], "message_id": row["message_id"]}
                    if self.service._now(cursor) < datetime.fromisoformat(row["next_attempt_at"]):
                        return {"status": "retry_wait", "retry_after_seconds": row["retry_delay_seconds"]}
                    # A Core lost after the durable dispatch marker cannot create
                    # a new native-call attempt. Missing marker is known pre-call.
                    cursor.execute(
                        "SELECT status FROM delivery_attempts WHERE tenant_id=%s AND message_id=%s "
                        "AND finished_at IS NULL ORDER BY ordinal DESC LIMIT 1 FOR UPDATE",
                        (row["tenant_id"], row["message_id"]),
                    )
                    open_attempt = cursor.fetchone()
                    if open_attempt and open_attempt[0] == "runtime_dispatched":
                        self._finish(cursor, row, "uncertain", "core_interrupted_after_dispatch")
                        return {"status": "uncertain", "message_id": row["message_id"],
                                "attempts": row["attempts"]}
                    reuse_prepared = bool(open_attempt and open_attempt[0] == "prepared")
                    if not reuse_prepared:
                        if row["attempts"] >= row["maximum_attempts"]:
                            self._finish(
                                cursor,
                                row,
                                "budget_exhausted",
                                "attempt_budget_exhausted",
                            )
                            return {"status": "budget_exhausted"}
                        cursor.execute(
                            "UPDATE delivery_attempts SET status='interrupted',error_code='core_interrupted',"
                            "finished_at=clock_timestamp() WHERE tenant_id=%s AND message_id=%s AND finished_at IS NULL",
                            (row["tenant_id"], row["message_id"]),
                        )
                    try:
                        envelope, binding = self._authorize(cursor, row)
                        if reuse_prepared:
                            prepared_attempt = self._load_attempt(cursor, row)
                            try:
                                self._selected_endpoint(cursor, row, prepared_attempt)
                            except DeliveryTransportError:
                                return self._defer_prepared(cursor, row)
                        else:
                            selection = self._selection(row, binding)
                            row["attempts"] += 1
                            attempt_id = f"delivery-attempt-{uuid.uuid4()}"
                            endpoint = self.service.endpoints.get(row["endpoint_id"])
                            invocation = None
                            preparation_error = None
                            if endpoint is None:
                                preparation_error = DeliveryTransportError("endpoint_unavailable")
                            elif not self._endpoint_matches(endpoint, selection):
                                preparation_error = DeliveryRejected("configured_endpoint_changed")
                            elif envelope.packet.activation == "invoke":
                                invocation = invocation_for(envelope, attempt_id)
                            cursor.execute(
                                "UPDATE delivery_messages SET attempts=%s,state='delivering',last_error=NULL "
                                "WHERE tenant_id=%s AND message_id=%s",
                                (row["attempts"], row["tenant_id"], row["message_id"]),
                            )
                            cursor.execute(
                                "INSERT INTO delivery_attempts(tenant_id,message_id,ordinal,attempt_id,operation_id,"
                                "endpoint_id,selection_revision,connection_ref,deadline,status,selection_json,"
                                "selection_digest,invocation_json,invocation_digest,dispatch_id,"
                                "runtime_dispatched_receipt_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'prepared',"
                                "%s,%s,%s,%s,%s,%s)",
                                (row["tenant_id"], row["message_id"], row["attempts"], attempt_id,
                                 row["operation_id"], selection["endpoint_id"], selection["revision"],
                                 self.worker_id, row["deadline"], json.dumps(selection), digest(selection),
                                 json.dumps(invocation.model_dump(mode="json")) if invocation else None,
                                 digest(invocation.model_dump(mode="json")) if invocation else None,
                                 invocation.dispatch_id if invocation else None,
                                 invocation.runtime_dispatched_receipt_id if invocation else None),
                            )
                            new_attempt = True
                            if preparation_error is not None:
                                return self._failure(cursor, row, preparation_error)
                    except (DeliveryRejected, AuthorizationDenied, DeliveryBoundaryRejected,
                            OperationIdentityConflict, DeliveryTransportError) as error:
                        return self._failure(cursor, row, error)
                if new_attempt:
                    self.after_claim(identity)

                def authorize_selected():
                    with self.service.authority._connect() as auth_connection, auth_connection.cursor() as auth_cursor:
                        current = self._load(auth_cursor, identity)
                        current_attempt = self._load_attempt(auth_cursor, current)
                        return self._selected_endpoint(auth_cursor, current, current_attempt)[0]

                def mark_dispatched(invocation, evidence):
                    with self.service.authority._connect() as mark_connection, mark_connection.cursor() as mark_cursor:
                        current = self._load(mark_cursor, identity)
                        current_attempt = self._load_attempt(mark_cursor, current)
                        selected_envelope, _ = self._selected_endpoint(mark_cursor, current, current_attempt)
                        stored = InvocationRequest.model_validate_json(
                            json.dumps(current_attempt["invocation_json"]), strict=True,
                        )
                        if stored != invocation or selected_envelope != invocation.envelope:
                            raise DeliveryRejected("immutable_invocation_changed")
                        existing_location = (
                            current["activation_node_id"], current["activation_machine_id"],
                            current["activation_dispatch_id"], current["activation_receipt_id"],
                        )
                        selected_location = (
                            invocation.envelope.node_id, invocation.envelope.machine_id,
                            invocation.dispatch_id, invocation.runtime_dispatched_receipt_id,
                        )
                        if any(existing_location) and existing_location != selected_location:
                            raise DeliveryRejected("activation_location_requires_reconciliation", "uncertain")
                        self._record_receipt(
                            mark_cursor, current, invocation.runtime_dispatched_receipt_id,
                            "runtime_dispatched", evidence, attempt_id=invocation.attempt_id,
                            dispatch_id=invocation.dispatch_id,
                        )
                        mark_cursor.execute(
                            "UPDATE delivery_messages SET activation_node_id=%s,activation_machine_id=%s,"
                            "activation_dispatch_id=%s,activation_receipt_id=%s WHERE tenant_id=%s AND message_id=%s",
                            (*selected_location, current["tenant_id"], current["message_id"]),
                        )
                        mark_cursor.execute(
                            "UPDATE delivery_attempts SET status='runtime_dispatched' WHERE tenant_id=%s "
                            "AND message_id=%s AND ordinal=%s AND status='prepared'",
                            (current["tenant_id"], current["message_id"], current["attempts"]),
                        )
                        if mark_cursor.rowcount != 1:
                            raise DeliveryRejected("dispatch_marker_conflict", "uncertain")

                endpoint = None
                def read_dispatch_marker(invocation):
                    with self.service.authority._connect() as observed_connection, observed_connection.cursor() as observed_cursor:
                        self._load(observed_cursor, identity)
                        observed_cursor.execute(
                            "SELECT receipt_id,attempt_id,dispatch_id FROM delivery_receipts "
                            "WHERE tenant_id=%s AND message_id=%s AND layer='runtime_dispatched'",
                            (identity["tenant_id"], identity["message_id"]),
                        )
                        recorded = observed_cursor.fetchone()
                        if recorded is None:
                            return False
                        if recorded != (invocation.runtime_dispatched_receipt_id, invocation.attempt_id,
                                        invocation.dispatch_id):
                            raise DeliveryRejected("dispatch_marker_identity_changed", "uncertain")
                        return True

                try:
                    with self.service.authority._connect() as read_connection, read_connection.cursor() as read_cursor:
                        row = self._load(read_cursor, identity)
                        attempt = self._load_attempt(read_cursor, row)
                        envelope, endpoint = self._selected_endpoint(read_cursor, row, attempt)
                        invocation = (InvocationRequest.model_validate_json(
                            json.dumps(attempt["invocation_json"]), strict=True,
                        )
                                      if attempt["invocation_json"] is not None else None)
                    observation = endpoint.deliver(
                        envelope, authorize_selected, invocation=invocation,
                        mark_dispatched=mark_dispatched if invocation is not None else None,
                        read_dispatch_marker=read_dispatch_marker if invocation is not None else None,
                    )
                    with self.service.authority._connect() as final_connection, final_connection.cursor() as final_cursor:
                        row = self._load(final_cursor, identity)
                        self._project(final_cursor, row, observation)
                        status = observation["status"]
                        self._finish(
                            final_cursor, row, status,
                            "native_outcome_uncertain" if status == "uncertain" else None,
                        )
                except (DeliveryRejected, AuthorizationDenied, DeliveryBoundaryRejected,
                        OperationIdentityConflict, DeliveryTransportError) as error:
                    with self.service.authority._connect() as fail_connection, fail_connection.cursor() as fail_cursor:
                        row = self._load(fail_cursor, identity)
                        fail_cursor.execute(
                            "SELECT 1 FROM delivery_receipts WHERE tenant_id=%s AND message_id=%s "
                            "AND layer='runtime_dispatched'",
                            (row["tenant_id"], row["message_id"]),
                        )
                        if fail_cursor.fetchone() is not None:
                            if endpoint is not None:
                                readback = endpoint.inspect_delivery(row["operation_id"], "uncertain")
                                if any(receipt["layer"] in ("runtime_acknowledged", "response_received")
                                       for receipt in readback["receipts"]):
                                    return self._failure(fail_cursor, row, error)
                            self._finish(fail_cursor, row, "uncertain", "post_dispatch_result_uncertain")
                            return {"status": "uncertain", "message_id": row["message_id"],
                                    "attempts": row["attempts"]}
                        if isinstance(error, InvocationPreCallRejected) and endpoint is not None:
                            self._project(
                                fail_cursor, row,
                                endpoint.inspect_delivery(row["operation_id"], "blocked"),
                            )
                        return self._failure(fail_cursor, row, error)
                return {"status": status, "message_id": row["message_id"],
                        "attempts": row["attempts"], "retry_after_seconds": row["retry_delay_seconds"]}
            finally:
                cursor.execute("SELECT pg_advisory_unlock(%s)", (key,))
