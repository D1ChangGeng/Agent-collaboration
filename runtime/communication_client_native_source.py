"""Exact message provenance over Core receipts and one trusted source reader.

The public query accepts no provider, file, session or Host identity. Current
message ACL and original dispatch are checked before and after source I/O.
Only original ACS input/protocol references leave this boundary, never a Native
transcript or permission to contact/control a Host.
"""
from __future__ import annotations

import json

from runtime.delivery import DeliveryDispatcher, DeliveryRejected, DeliveryService, digest
from runtime.delivery_models import InvocationRequest
from runtime.delivery_node import invocation_for
from runtime.models import CommandEnvelope
from runtime.native_provider_registry import NativeProviderRegistry, NativeProviderRejected
from runtime.native_source_links import NativeSourceLinkPort
from runtime.native_view_models import NativeSelection
from runtime.project_common import parse_handle
from runtime.receiver_contract import ReceiverBinding


def _missing(reason):
    return {"available": False, "value": None, "reason_code": reason, "evidence_ref": None}


def _original_selection(invocation):
    e, p = invocation.envelope, invocation.envelope.packet
    return NativeSelection(tenant_id=e.tenant_id, project_id=p.project_id, scope_id=p.target_scope_id,
        agent_slot_id=p.target_agent_slot_id, node_id=e.node_id, boot_incarnation=e.boot_incarnation,
        binding=ReceiverBinding(receiver_id=e.endpoint_id, actor_address=p.recipient, binding_epoch=e.binding_revision,
            authority_id=e.authority_id, authority_incarnation=e.authority_incarnation,
            execution_host_ref=e.machine_id, native_session_ref=None, provider_generation=None))


class ClientNativeSourceService:
    def _native_source_original(self, project, reference):
        identifier = parse_handle(reference, "message", project)

        def selected(bound, cursor, _root, _command):
            original = self.project_service._communication_row(bound, cursor, {"project_id": project}, identifier)
            if original[3].get("activation") != "invoke":
                return None, "native_source_not_requested"
            try:
                # Reuse Core's real outbox/operation/dedup/event/acceptance ledger
                # verifier. Historical reads do not reauthorize the old sender
                # for a new execution or follow today's endpoint selection.
                loader = DeliveryDispatcher(DeliveryService(bound, {}))
                message = loader._load(cursor, {"tenant_id": bound.tenant_id, "message_id": identifier,
                    "operation_id": original[6]}, lock=False)
                command = CommandEnvelope.model_validate_json(json.dumps(message["command_json"]), strict=True)
                if command.canonical_hash({"packet": message["packet_json"], "endpoint_id": message["endpoint_id"],
                        "binding_revision": message["binding_revision"]}) != message["canonical_hash"]:
                    return None, "native_source_core_evidence_unavailable"
                # The immutable dispatched receipt identifies its original
                # attempt even after endpoint reassignment. Never use latest.
                cursor.execute("SELECT a.invocation_json,a.invocation_digest,a.attempt_id,a.selection_json,a.selection_digest,"
                    "r.receipt_id,r.dispatch_id FROM delivery_receipts r JOIN delivery_attempts a "
                    "ON a.tenant_id=r.tenant_id AND a.message_id=r.message_id AND a.attempt_id=r.attempt_id "
                    "WHERE r.tenant_id=%s AND r.message_id=%s AND r.layer='runtime_dispatched' LIMIT 2",
                    (bound.tenant_id, identifier))
                rows = cursor.fetchall()
                if len(rows) != 1 or rows[0][0] is None:
                    return None, "native_source_original_dispatch_unavailable"
                raw, hashed, attempt, selection, selection_hash, receipt, dispatch = rows[0]
                if len(json.dumps(raw).encode()) > 2 * 1024 * 1024:
                    return None, "native_source_core_evidence_unavailable"
                invocation = InvocationRequest.model_validate_json(json.dumps(raw), strict=True)
                e = invocation.envelope
                expected_selection = {"endpoint_id": e.endpoint_id, "revision": e.binding_revision,
                    "scope_id": e.packet.target_scope_id, "agent_slot_id": e.packet.target_agent_slot_id,
                    "machine_id": e.machine_id, "node_id": e.node_id, "boot_incarnation": e.boot_incarnation}
                if (digest(raw) != hashed or invocation != invocation_for(e, attempt)
                        or any(selection.get(name) != value for name, value in expected_selection.items())
                        or selection.get("supports_invoke") is not True or digest(selection) != selection_hash
                        or (receipt, dispatch) != (invocation.runtime_dispatched_receipt_id, invocation.dispatch_id)
                        or e.packet.model_dump(mode="json") != message["packet_json"]
                        or any(getattr(e, name) != message[name] for name in ("tenant_id", "message_id", "command_id", "operation_id"))
                        or any(getattr(e, name) != getattr(command, name) for name in
                            ("authority_id", "authority_incarnation", "principal_ref", "grant_ref"))
                        or e.accepted_state_digest != message["accepted_state_digest"]):
                    return None, "native_source_core_evidence_unavailable"
                return invocation, None
            except (DeliveryRejected, ValueError, TypeError, KeyError):
                return None, "native_source_core_evidence_unavailable"

        return self._transaction(project, "read_message", selected)

    def native_source(self, project, reference):
        value = self._native_source_lookup(project, reference)
        # Registry/SQLite waits may outlive the body read's authorization,
        # including an unavailable/ambiguous source. Recheck every outcome.
        self._transaction(project, "read_message", lambda bound, cursor, _root, _command:
            self.project_service._communication_row(bound, cursor, {"project_id": project},
                parse_handle(reference, "message", project)))
        return value

    def _native_source_lookup(self, project, reference):
        invocation, reason = self._native_source_original(project, reference)
        if invocation is None:
            return self._validate("NativeSourceLookup", _missing(reason))
        if not getattr(self.authority, "_communication_native_links_enabled", False):
            return self._validate("NativeSourceLookup", _missing("native_source_disabled"))
        registry = getattr(self.authority, "_native_provider_registry", None)
        if not isinstance(registry, NativeProviderRegistry):
            return self._validate("NativeSourceLookup", _missing("native_source_provider_unavailable"))
        try:
            admission, journal, fence = registry.original_source(_original_selection(invocation))
        except NativeProviderRejected as error:
            return self._validate("NativeSourceLookup", _missing(error.code))
        except (ValueError, TypeError):
            return self._validate("NativeSourceLookup", _missing("native_source_core_evidence_unavailable"))

        def authorize(actual):
            latest, _reason = self._native_source_original(project, reference)
            if latest != invocation or actual != invocation:
                raise NativeProviderRejected("native_source_original_dispatch_changed")
            if getattr(self.authority, "_native_provider_registry", None) is not registry:
                raise NativeProviderRejected("native_source_provider_changed")
            registry.assert_current(fence)

        from runtime.remote_native_source import RemoteNativeSourceReader

        if isinstance(journal, RemoteNativeSourceReader):
            authorize(invocation)
            try:
                return self._validate("NativeSourceLookup", journal.read(invocation, admission))
            except (OSError, ValueError, RuntimeError):
                return self._validate("NativeSourceLookup", _missing("native_source_remote_unavailable"))
            finally:
                authorize(invocation)

        port = NativeSourceLinkPort(read_original=lambda _message, _operation: invocation,
            original_provider=lambda _invocation: admission, journal_for=lambda _invocation: journal,
            authorize_original=authorize)
        try:
            result = port.read(reference, invocation.operation_id)
        except NativeProviderRejected as error:
            return self._validate("NativeSourceLookup", _missing(error.code))
        value = {"available": True, "value": result.value.as_client(), "reason_code": None,
                 "evidence_ref": result.evidence_ref} if result.available else _missing(result.reason_code)
        return self._validate("NativeSourceLookup", value)
