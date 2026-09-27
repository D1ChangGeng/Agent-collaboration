"""Authenticated local Delivery operations, separate from original sender authority."""
from __future__ import annotations

import json
import uuid

from runtime.delivery import DeliveryDispatcher, DeliveryRejected, DeliveryService
from runtime.errors import RevisionConflict
from runtime.models import CommandResult


class DeliveryOperations:
    def __init__(self, authority):
        self.authority = authority
        self.dispatcher = DeliveryDispatcher(DeliveryService(authority, authority._delivery_endpoints))

    def after_authorize(self, command, result, identity):
        """Fault seam after committed operator audit, before dispatcher entry."""

    def after_dispatch(self, command, result, identity):
        """Fault seam after dispatcher completion, before operator readback commit."""

    @staticmethod
    def _status(cursor, identity):
        cursor.execute("SELECT state,attempts,receipt_high_water FROM delivery_messages "
                       "WHERE tenant_id=%s AND message_id=%s AND operation_id=%s",
                       (identity["tenant_id"], identity["message_id"], identity["operation_id"]))
        row = cursor.fetchone()
        if row is None:
            raise DeliveryRejected("message_missing")
        return {**identity, "state": row[0], "attempts": row[1], "receipt_high_water": row[2]}

    @staticmethod
    def _audit_outbox(cursor, command, result, identity):
        cursor.execute("SELECT payload,delivered_at FROM outbox WHERE tenant_id=%s AND operation_id=%s "
                       "AND topic='delivery.dispatch.authorized' FOR UPDATE", (command.tenant_id, result.operation_id))
        row = cursor.fetchone()
        if row is None or row[0].get("delivery_identity") != identity:
            raise DeliveryRejected("operator_audit_outbox_conflict")
        return row

    @staticmethod
    def _expect(command, name):
        if command.command_type != name or command.target_kind != "message":
            raise ValueError("delivery operation command type/target differs")

    def scan(self, command, *, scope_id, limit):
        """Read the Scope's due message collection; no business ledger mutation."""
        self._expect(command, "delivery.scan")
        if command.target_id != "pending" or command.expected_revision != 0:
            raise ValueError("scan targets the pending message collection at revision zero")
        with self.authority._connect() as connection, connection.cursor() as cursor:
            self.authority._authorize(command, cursor, "delivery.scan", scope_id)
            cursor.execute(
                "SELECT m.tenant_id,m.message_id,m.operation_id FROM delivery_messages m "
                "JOIN outbox o ON o.tenant_id=m.tenant_id AND o.message_id=m.message_id "
                "AND o.operation_id=m.operation_id JOIN operations op "
                "ON op.tenant_id=m.tenant_id AND op.operation_id=m.operation_id "
                "WHERE m.tenant_id=%s AND m.packet_json->>'target_scope_id'=%s "
                "AND o.topic='message.delivery' AND op.status='committed' "
                "AND m.state IN ('queued','delivering','retry_wait') "
                "AND m.next_attempt_at<=clock_timestamp() ORDER BY m.created_at,m.message_id LIMIT %s",
                (command.tenant_id, scope_id, limit),
            )
            pending = [dict(zip(("tenant_id", "message_id", "operation_id"), row, strict=True))
                       for row in cursor.fetchall()]
            self.authority._authorize(command, cursor, "delivery.scan", scope_id)
        return {"scope_id": scope_id, "pending": pending}

    def dispatch(self, command, *, operation_id):
        """Commit the operator's audit, then recover the original Delivery once.

        A pending operator Outbox permits explicit same-command recovery. The
        original Delivery identity owns dedup and native dispatch certainty.
        """
        self._expect(command, "delivery.dispatch")
        identity = {"tenant_id": command.tenant_id, "message_id": command.target_id,
                    "operation_id": operation_id}
        result = CommandResult(command_id=command.command_id, operation_id=f"op-{uuid.uuid4()}",
                               target_id=command.target_id, revision=command.expected_revision,
                               state="delivery_dispatch_authorized")
        # This preliminary authorization commits before acquiring a message lock.
        # Actual audit locking follows the dispatcher's message -> Grant order.
        with self.authority._connect() as connection, connection.cursor() as cursor:
            self.authority._authorize(command, cursor, "delivery.dispatch")
        with self.authority._connect() as connection, connection.cursor() as cursor:
            # Existing operator audits use Outbox -> message -> Grant order;
            # completion uses Outbox -> Grant and reads message without a lock.
            cursor.execute("SELECT o.operation_id FROM outbox o JOIN operations p "
                           "ON p.operation_id=o.operation_id AND p.tenant_id=o.tenant_id "
                           "WHERE p.tenant_id=%s AND p.command_id=%s "
                           "AND o.topic='delivery.dispatch.authorized' FOR UPDATE OF o",
                           (command.tenant_id, command.command_id))
            cursor.fetchall()
            cursor.execute("SELECT to_jsonb(m) FROM delivery_messages m WHERE tenant_id=%s AND message_id=%s FOR UPDATE",
                           (command.tenant_id, command.target_id))
            found = cursor.fetchone()
            if found is None:
                raise DeliveryRejected("message_missing")
            row = found[0]
            scope = row["packet_json"]["target_scope_id"]
            self.authority._authorize(command, cursor, "delivery.dispatch", scope)
            duplicate, hashed = self.authority._dedup(cursor, command, result, {"delivery_identity": identity})
            if duplicate is not None:
                result = duplicate
                _payload, completed_at = self._audit_outbox(cursor, command, result, identity)
                if completed_at is not None:
                    return {"operator_audit": result.model_dump(mode="json"),
                            "delivery": self._status(cursor, identity), "operator_pending": False}
            else:
                self.dispatcher._load(cursor, identity)
                if row["attempts"] != command.expected_revision:
                    raise RevisionConflict(command.target_id, command.expected_revision, row["attempts"])
                self.authority._authorize(command, cursor, "delivery.dispatch", scope)
                cursor.execute(
                    "INSERT INTO domain_events(tenant_id,work_item_id,target_kind,target_id,related_work_item_id,"
                    "to_state,initiated_by,lineage_mode,command_id,resulting_revision,evidence_refs,"
                    "command_hash_version,canonical_hash) "
                    "VALUES (%s,NULL,'message',%s,%s,'delivery.dispatch.authorized',%s,'external_command',%s,%s,'[]','v2',%s)",
                    (command.tenant_id, command.target_id, row["packet_json"]["work_item_id"],
                     command.principal_ref, command.command_id, command.expected_revision, hashed),
                )
                self.authority._operation(cursor, command, result.operation_id)
                self.authority._outbox(cursor, command, result.operation_id, "delivery.dispatch.authorized",
                                       {"delivery_identity": identity})
            self.authority._authorize(command, cursor, "delivery.dispatch", scope)
        # Recovery independently revalidates the original message.send/invoke
        # Grant, accepted state, selection and deadline. Audit is not delegation.
        self.after_authorize(command, result, identity)
        try:
            dispatched = self.dispatcher.dispatch(identity)
        except Exception:  # noqa: BLE001 -- committed operator request remains recoverable; never expose backend text
            dispatched = {"status": "unknown"}
        self.after_dispatch(command, dispatched, identity)
        with self.authority._connect() as connection, connection.cursor() as cursor:
            payload, completed_at = self._audit_outbox(cursor, command, result, identity)
            self.authority._authorize(command, cursor, "delivery.dispatch", scope)
            observed = self._status(cursor, identity)
            completed = completed_at is not None or dispatched["status"] in {
                "delivered", "blocked", "expired", "budget_exhausted",
            }
            # Another identical request may already have completed this audit.
            # Preserve its completion when this caller merely observed busy.
            cursor.execute("UPDATE outbox SET payload=%s,delivered_at=CASE WHEN %s THEN "
                           "COALESCE(delivered_at,clock_timestamp()) ELSE delivered_at END "
                           "WHERE tenant_id=%s AND operation_id=%s AND topic='delivery.dispatch.authorized'",
                           (json.dumps(payload | {"delivery_readback": observed}), completed,
                            command.tenant_id, result.operation_id))
            self.authority._authorize(command, cursor, "delivery.dispatch", scope)
        return {"operator_audit": result.model_dump(mode="json"), "delivery": observed,
                "operator_pending": not completed}
