"""Historical packet seeding and regression fixture, excluded from the wheel.

The old authenticated mutation path is retained only to construct old database
facts and check archive/recovery boundaries. Current tests use runtime.delivery.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from runtime.delivery import DeliveryRejected, digest
from runtime.delivery import DeliveryService as CommunicationDelivery
from runtime.delivery_models import (
    DeliveryEnvelope,
    DeliveryPacket,
    MessagePacket,
    NoticePacket,
)
from runtime.errors import AuthorizationDenied
from runtime.lifetimes import earliest, expired
from runtime.models import CommandEnvelope, CommandResult
from runtime_tests.fixtures.legacy_team_policy import enforce_team_delivery


class DeliveryService(CommunicationDelivery):
    def send_message(
        self,
        command: CommandEnvelope,
        packet: DeliveryPacket,
        *,
        endpoint_id: str,
        binding_revision: int,
        operation_id: str | None = None,
    ):
        if command.command_type != "message.send" or command.target_kind != "message":
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        from runtime.delivery_models import PACKET
        packet = PACKET.validate_json(packet.model_dump_json(), strict=True)
        if isinstance(packet, NoticePacket) and not getattr(self.authority, "_communication_notice", False):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        if ((packet.deadline is not None and command.deadline is not None
             and packet.deadline > command.deadline)
                or len(packet.model_dump_json().encode()) > 65536):
            raise DeliveryRejected("packet_bound_exceeded")
        direct_inbox = isinstance(packet, MessagePacket) and (packet.recipient.startswith("client:") or packet.activation == "message_only")
        if not direct_inbox and (not endpoint_id or type(binding_revision) is not int or binding_revision < 1):
            raise DeliveryRejected("invalid_endpoint_selection")
        extra = {"packet": packet.model_dump(mode="json"), "endpoint_id": endpoint_id, "binding_revision": binding_revision}
        result = CommandResult(command_id=command.command_id, operation_id=operation_id or f"op-{uuid.uuid4()}",
                               target_id=command.target_id, revision=command.expected_revision, state="message_queued")
        with self.authority._connect() as connection, connection.cursor() as cursor:
            self.authority._authorize(command, cursor, "message.send", packet.target_scope_id)
            if packet.activation == "invoke" and not direct_inbox:
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
                "WHERE (%s::timestamptz IS NULL OR clock_timestamp()<%s)",
                (command.tenant_id, command.target_id, command.command_id, result.operation_id, endpoint_id, binding_revision,
                 packet.model_dump_json(), command.model_dump_json(), hashed, envelope.model_dump_json(),
                 digest(envelope.model_dump(mode="json")), packet.deadline, packet.maximum_attempts, packet.retry_delay_seconds,
                 policy_hash, accepted_state_digest, packet.deadline, packet.deadline),
            )
            if cursor.rowcount != 1:
                raise DeliveryRejected("deadline_expired", "expired")
            self._event(cursor, command, result, hashed, "message.queued", getattr(packet, "work_item_id", None))
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
                             "accepted_revision": getattr(packet, "accepted_revision", None),
                             "accepted_state_digest": accepted_state_digest})),
            )
            if direct_inbox:
                cursor.execute("UPDATE delivery_messages SET state='delivered',receipt_high_water='target_inbox_committed' "
                               "WHERE tenant_id=%s AND message_id=%s", (command.tenant_id, command.target_id))
                cursor.execute("INSERT INTO delivery_receipts(tenant_id,message_id,receipt_id,layer,evidence_json) "
                               "VALUES (%s,%s,%s,'target_inbox_committed',%s)",
                               (command.tenant_id, command.target_id, f"delivery:{command.target_id}:target_inbox_committed",
                                json.dumps({"source": "authority_inbox", "model_consumption": "unconfirmed"})))
        return result  # accepted_by_authority becomes visible only after this commit.


    def _boundary(self, cursor, authority, command, packet, endpoint_id, revision, *, recovery=False):
        from runtime.communication import communication_boundary
        from runtime.delivery_models import MessagePacket
        if isinstance(packet, (MessagePacket, NoticePacket)):
            return communication_boundary(cursor, authority, command, packet, endpoint_id, revision,
                                          recovery=recovery)
        if expired(earliest(command.deadline, packet.deadline), self._now(cursor)):
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
        # A Root assignment is distinct from the receiving Agent's acceptance.
        # Only its own durable acknowledgement request may cross this boundary.
        cursor.execute("SELECT to_regclass('collaboration_handoffs')")
        if cursor.fetchone()[0] is not None:
            cursor.execute("SELECT state,message_id FROM collaboration_handoffs "
                           "WHERE tenant_id=%s AND work_item_id=%s "
                           "ORDER BY assigned_work_revision DESC LIMIT 1",
                           (command.tenant_id, packet.work_item_id))
            handoff = cursor.fetchone()
            if handoff and handoff[0] in {"pending", "rejected", "withdrawn"} and handoff[1] != command.target_id:
                raise DeliveryRejected("handoff_acknowledgement_required")
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
        if (authority.access_mode != "owner"
                and datetime.fromisoformat(binding["expires_at"]) <= self._now(cursor)):
            raise DeliveryRejected("endpoint_binding_expired", "expired")
        if packet.activation == "invoke" and not binding["supports_invoke"] and not recovery:
            raise DeliveryRejected("invoke_endpoint_unavailable")
        authority._authorize(command, cursor, "message.send", packet.target_scope_id)
        if packet.activation == "invoke":
            authority._authorize(command, cursor, "runtime.invoke", packet.target_scope_id)
        enforce_team_delivery(cursor, command, packet, work[3], recovery=recovery, access_mode=authority.access_mode)
        return binding, digest(work[3]), digest(accepted_state)
