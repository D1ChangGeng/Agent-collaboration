"""Participant-authorized, pure observation of the original delivery operation.

This is the query/projection component for recovery and client services. It is
not an operator action and never dispatches, prepares, resumes or replaces input.
"""
from __future__ import annotations

import json

from runtime.delivery import DeliveryDispatcher, DeliveryRejected
from runtime.delivery_models import InvocationRequest
from runtime.errors import NotFound, RevisionConflict


class CommunicationDeliveryObserver:
    def __init__(self, projects):
        self.projects = projects
        self.authority = projects.service.authority

    def _load(self, cursor, authority, project_id, operation_ref, expected_revision):
        args = {"project_id": project_id}
        bound, _project, _command = self.projects._authorize(authority, cursor, project_id, "read_message", args)
        cursor.execute("SELECT to_jsonb(m) FROM delivery_messages m JOIN communication_messages c "
            "USING(tenant_id,message_id) WHERE m.tenant_id=%s AND c.project_id=%s AND m.operation_id=%s",
            (bound.tenant_id, project_id, operation_ref))
        row = cursor.fetchone()
        if row is None:
            raise NotFound("operation", operation_ref)
        message = row[0]
        self.projects._communication_row(bound, cursor, args, message["message_id"])
        cursor.execute("SELECT to_jsonb(e) FROM delivery_endpoints e WHERE tenant_id=%s AND endpoint_id=%s",
                       (bound.tenant_id, message["endpoint_id"]))
        endpoint = cursor.fetchone()
        endpoint = endpoint[0] if endpoint else None
        if expected_revision is not None and (endpoint is None or endpoint["revision"] != expected_revision):
            raise RevisionConflict(message["endpoint_id"] or "receiver", expected_revision,
                                   endpoint["revision"] if endpoint else 0)
        cursor.execute("SELECT to_jsonb(a) FROM delivery_attempts a WHERE tenant_id=%s AND message_id=%s "
                       "ORDER BY ordinal DESC LIMIT 1", (bound.tenant_id, message["message_id"]))
        attempt = cursor.fetchone()
        return message, endpoint, attempt[0] if attempt else None

    @staticmethod
    def _facts(cursor, message, project_id, *, reason=None):
        cursor.execute("SELECT layer FROM delivery_receipts WHERE tenant_id=%s AND message_id=%s",
                       (message["tenant_id"], message["message_id"]))
        layers = {row[0] for row in cursor.fetchall()}
        return {"operation_id": message["operation_id"], "message_handle": f"message:{project_id}:{message['message_id']}",
            "delivery_state": message["state"], "attempts": message["attempts"],
            "binding_revision": message["binding_revision"], "native_acknowledged": "runtime_acknowledged" in layers,
            "native_state": "accepted" if "runtime_acknowledged" in layers else "not_requested"
                if message["packet_json"].get("activation") == "message_only" or message["packet_json"].get("target_agent_slot_id") is None else "unknown",
            "model_consumption": "unconfirmed", "reason_code": reason,
            "receipt_layers": sorted(layers)}

    @staticmethod
    def _selection(message, endpoint, invocation):
        if endpoint is None or endpoint["status"] != "active":
            return False
        envelope = invocation.envelope
        return ((endpoint["endpoint_id"], endpoint["revision"], endpoint["machine_id"],
                 endpoint["node_id"], endpoint["boot_incarnation"], endpoint["scope_id"], endpoint["agent_slot_id"]) ==
                (message["endpoint_id"], envelope.binding_revision, envelope.machine_id,
                 envelope.node_id, envelope.boot_incarnation, envelope.packet.target_scope_id, envelope.packet.target_agent_slot_id))

    def observe(self, project_id, operation_ref, credential, *, reconcile=False, expected_revision=None):
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
            raise ValueError("expected receiver revision must be a nonnegative integer")
        self.projects.service.authenticate(credential)
        with self.authority.transaction() as (authority, connection), connection.cursor() as cursor:
            message, endpoint, attempt = self._load(cursor, authority, project_id, operation_ref, expected_revision)
            initial = self._facts(cursor, message, project_id)
        if not reconcile or initial["native_acknowledged"] or attempt is None or attempt["invocation_json"] is None:
            return initial
        invocation = InvocationRequest.model_validate_json(json.dumps(attempt["invocation_json"]), strict=True)
        if not self._selection(message, endpoint, invocation):
            return initial | {"reason_code": "original_receiver_binding_unavailable"}
        provider = self.authority._delivery_endpoints.get(message["endpoint_id"])
        if provider is None:
            return initial | {"reason_code": "original_receiver_provider_unavailable"}
        reason = "native_outcome_unconfirmed"
        observation = {"receipts": []}
        try:
            description = provider.descriptor()
            if any(description.get(key) != endpoint[key] for key in ("machine_id", "node_id", "boot_incarnation", "scope_id", "agent_slot_id")):
                reason = "original_receiver_binding_changed"
            else:
                query = getattr(provider, "reconcile_delivery", None)
                if callable(query):
                    observation = query(invocation)
                else:
                    query = getattr(provider, "inspect_delivery", None)
                    if callable(query):
                        observation = query(message["operation_id"], "uncertain")
                    else:
                        reason = "pure_delivery_observation_unsupported"
        except (OSError, RuntimeError, ValueError):
            reason = "original_receiver_provider_unavailable"
        with self.authority.transaction() as (authority, connection), connection.cursor() as cursor:
            # The selected Native may have changed while its read API was in
            # flight. Reauthorize the actual reader, then freeze this projection.
            self.projects.service.authenticate(credential)
            # Match the dispatcher's message -> Grant lock order. No private
            # result is exposed until the current reader is authorized below.
            cursor.execute("SELECT state FROM delivery_messages WHERE tenant_id=%s AND message_id=%s FOR UPDATE",
                           (message["tenant_id"], message["message_id"]))
            cursor.fetchone()
            current, current_endpoint, current_attempt = self._load(cursor, authority, project_id, operation_ref, expected_revision)
            if (current_attempt is None or current_attempt["attempt_id"] != attempt["attempt_id"]
                    or current_attempt["invocation_digest"] != attempt["invocation_digest"]
                    or not self._selection(current, current_endpoint, invocation)):
                return self._facts(cursor, current, project_id, reason="delivery_selection_changed_during_observation")
            receipts = observation.get("receipts", [])
            accepted = [item for item in receipts if item.get("layer") == "runtime_acknowledged"]
            if accepted:
                for item in accepted:
                    evidence = item.get("evidence", {})
                    if (evidence.get("dispatch_id") != invocation.dispatch_id
                            or evidence.get("attempt_id", invocation.attempt_id) != invocation.attempt_id
                            or evidence.get("invocation_id", invocation.invocation_id) != invocation.invocation_id):
                        raise DeliveryRejected("observed_native_receipt_lineage_changed")
                    signed = evidence.get("signed_receipt")
                    if signed is not None:
                        receipt = signed.get("receipt", {})
                        expected = {"message_id": invocation.message_id, "command_id": invocation.command_id,
                            "operation_id": invocation.operation_id, "attempt_id": invocation.attempt_id,
                            "dispatch_id": invocation.dispatch_id, "invocation_digest": attempt["invocation_digest"],
                            "envelope_digest": invocation.envelope_digest, "selection_digest": invocation.selection_digest}
                        if any(receipt.get(key) != value for key, value in expected.items()):
                            raise DeliveryRejected("observed_native_signed_receipt_lineage_changed")
                # _project validates the actual Inbox, receipt identities and
                # packet/attempt lineage; do not trust a provider's status text.
                DeliveryDispatcher._project(cursor, current, observation)
                cursor.execute("UPDATE delivery_messages SET state='delivered',last_error=NULL "
                    "WHERE tenant_id=%s AND message_id=%s", (current["tenant_id"], current["message_id"]))
                cursor.execute("UPDATE delivery_attempts SET status='delivered',error_code=NULL,finished_at=clock_timestamp() "
                    "WHERE tenant_id=%s AND message_id=%s AND attempt_id=%s",
                    (current["tenant_id"], current["message_id"], invocation.attempt_id))
                current["state"] = "delivered"
            return self._facts(cursor, current, project_id, reason=None if accepted else reason)
