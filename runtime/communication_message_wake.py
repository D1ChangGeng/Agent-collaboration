"""Conditional Receiver preparation owned by the real accepted Message.

The only durable state added is technical lifecycle metadata in its original
delivery Outbox. No recovery command, Message or Core operation is synthesized.
Normal delivery still owns input admission and all delivery/Agent-reply facts.
"""
from __future__ import annotations

import json
from copy import copy, deepcopy
from types import SimpleNamespace

from runtime.auth import LocalCredentialAuthenticator
from runtime.delivery import DeliveryDispatcher, DeliveryService
from runtime.errors import AcceptanceGuardFailed, AuthorizationDenied, NotFound
from runtime.models import AuthenticatedContext, CommandEnvelope
from runtime.project_service import ProjectService
from runtime.receiver_crypto import sha256
from runtime.receiver_lifecycle_contract import LifecycleSource
from runtime.surfaces import SharedService

SCHEMA = "acs-message-wake/1"


class MessageWakeUnavailable(ValueError):
    pass


def enabled(authority, endpoint_id):
    policy = getattr(authority, "_receiver_message_wake_policy", None)
    return callable(policy) and policy(endpoint_id) is True


class MessageWakeStore:
    """An internal lifecycle frame over one actual message.delivery Outbox.

    ``operation`` below is that operation's technical wake substate, not a
    public Recovery DTO or another entry in operations. The delivery identity,
    packet, command, Message state and attempts are never replaced by this store.
    """
    def __init__(self, projects):
        self.projects, self.authority = projects, projects.service.authority

    def _load(self, cursor, project, operation_ref, *, lock):
        cursor.execute("SELECT tenant_id,message_id,operation_id FROM delivery_messages WHERE tenant_id=%s AND operation_id=%s",
            (self.authority.tenant_id, operation_ref))
        rows = cursor.fetchall()
        if len(rows) != 1:
            raise NotFound("message operation", operation_ref)
        identity = dict(zip(("tenant_id", "message_id", "operation_id"), rows[0], strict=True))
        dispatcher = DeliveryDispatcher(DeliveryService(self.authority, self.authority._delivery_endpoints))
        row = dispatcher._load(cursor, identity, lock=lock)
        packet, command = row["packet_json"], row["command_json"]
        metadata = command.get("payload", {}).get("lifecycle_source")
        if (packet.get("schema_version") != "acs-message/1" or packet.get("project_id") != project
                or packet.get("activation") != "invoke" or row["endpoint_id"] is None
                or type(metadata) is not dict or metadata.get("schema_version") != "acs-message-lifecycle-source/1"
                or set(metadata) != {"schema_version", "profile", "issuer_context"}):
            raise MessageWakeUnavailable("message_has_no_eligible_original_wake_source")
        return dispatcher, row, metadata

    def _row(self, cursor, project, operation_ref, *, lock=False):
        _dispatcher, row, metadata = self._load(cursor, project, operation_ref, lock=lock)
        cursor.execute("SELECT payload FROM outbox WHERE tenant_id=%s AND operation_id=%s AND topic='message.delivery'" +
            (" FOR UPDATE" if lock else ""), (self.authority.tenant_id, operation_ref))
        saved = cursor.fetchone()[0].get("receiver_wake")
        if saved is None:
            now = self.authority.canonical_now(cursor).isoformat()
            saved = {"schema_version": SCHEMA, "operation": {"operation_id": operation_ref, "kind": "message_wake",
                "state": "queued", "receiver_ref": row["endpoint_id"], "binding_epoch": row["binding_revision"],
                "effect_state": "committed", "reason_code": None, "evidence_refs": [], "revision": 1,
                "created_at": now, "updated_at": now}}
        if (saved.get("schema_version") != SCHEMA or saved.get("operation", {}).get("operation_id") != operation_ref
                or saved["operation"].get("receiver_ref") != row["endpoint_id"]
                or saved["operation"].get("binding_epoch") != row["binding_revision"]):
            raise MessageWakeUnavailable("original_message_wake_identity_changed")
        return {**deepcopy(saved), "project_id": project, "message_id": row["message_id"], "receiver_id": row["endpoint_id"],
            "actor": row["packet_json"]["sender"], "issuer_context": metadata["issuer_context"], "profile": metadata["profile"],
            "command": row["command_json"], "request": row["packet_json"]}

    def _save(self, cursor, payload, operation, *, done=False):
        original = self._row(cursor, payload["project_id"], operation["operation_id"], lock=True)
        if (operation["operation_id"] != original["operation"]["operation_id"]
                or any(payload.get(key) != original.get(key) for key in
                    ("project_id", "message_id", "receiver_id", "actor", "issuer_context", "profile", "command", "request"))):
            raise MessageWakeUnavailable("original_message_wake_source_changed")
        previous_lifecycle = original.get("lifecycle", {})
        next_lifecycle = payload.get("lifecycle", {})
        previous_history = previous_lifecycle.get("history", [])
        if (next_lifecycle.get("history", [])[:len(previous_history)] != previous_history
                or previous_lifecycle.get("original_capacity_digest") is not None and
                next_lifecycle.get("original_capacity_digest") != previous_lifecycle["original_capacity_digest"]):
            raise MessageWakeUnavailable("original_message_restore_history_changed")
        if (previous_lifecycle.get("first_plan_digest") is not None
                and next_lifecycle.get("first_plan_digest") != previous_lifecycle["first_plan_digest"]):
            archived = deepcopy(previous_lifecycle)
            archived.pop("history", None)
            if (original["operation"]["state"] != "completed" or operation["state"] != "preparing"
                    or next_lifecycle.get("history", []) != [*previous_history, archived]):
                raise MessageWakeUnavailable("original_message_lifecycle_plan_cannot_be_replaced")
        technical = {"schema_version": SCHEMA, "operation": operation}
        if "lifecycle" in payload:
            technical["lifecycle"] = payload["lifecycle"]
        cursor.execute("UPDATE outbox SET payload=jsonb_set(payload,'{receiver_wake}',%s::jsonb) "
            "WHERE tenant_id=%s AND operation_id=%s AND topic='message.delivery'",
            (json.dumps(technical), self.authority.tenant_id, operation["operation_id"]))

    def _reader(self, metadata):
        authority = copy(self.authority)
        authority.context = AuthenticatedContext(**metadata["issuer_context"])
        projects = ProjectService(SharedService(authority, LocalCredentialAuthenticator(authority.context)),
            self.projects.catalog, profile=metadata["profile"])
        return authority, projects

    def original_source(self, cursor, payload):
        dispatcher, row, metadata = self._load(cursor, payload["project_id"], payload["operation"]["operation_id"], lock=True)
        original, projects = self._reader(metadata)
        command = CommandEnvelope.model_validate_json(json.dumps(row["command_json"]), strict=True)
        ctx = original.context
        if any(getattr(ctx, key) != getattr(command, key) for key in
                ("tenant_id", "authority_id", "authority_incarnation", "principal_ref", "grant_ref")):
            raise AuthorizationDenied(ctx.principal_ref, ctx.grant_ref)
        if not enabled(self.authority, row["endpoint_id"]):
            raise MessageWakeUnavailable("message_wake_disabled")
        projects._check_tool_policy("send_message")
        # The established delivery boundary independently recovers trusted
        # Client/Slot identity, current message.send/runtime.invoke and scope.
        envelope, binding = dispatcher._authorize(cursor, row)
        if (binding["revision"] != row["binding_revision"] or envelope.binding_revision != row["binding_revision"]
                or row["state"] not in {"queued", "retry_wait", "delivering"}
                or row["activation_dispatch_id"] is not None):
            raise MessageWakeUnavailable("original_message_no_longer_pre_effect")
        # An active reply wait owns the message until its original durable
        # ingress has resolved; a queued wake cannot race a ToolResult delivery.
        if (getattr(self.authority, "_wait_ingress_storage_available", False)
                or getattr(self.authority, "_wait_ingress_recovery_enabled", False)):
            from runtime.communication_wait_ingress import gate

            if gate(cursor, row["tenant_id"], row["packet_json"]["project_id"], row["message_id"]):
                raise MessageWakeUnavailable("message_owned_by_active_reply_wait")
        cursor.execute("SELECT 1 FROM delivery_messages m JOIN outbox o USING(tenant_id,message_id,operation_id) "
            "WHERE m.tenant_id=%s AND m.endpoint_id=%s AND m.binding_revision=%s AND m.message_id<>%s AND "
            "((m.activation_dispatch_id IS NOT NULL AND m.state<>'delivered') OR "
            "(o.payload->'receiver_wake'->'lifecycle'->>'phase'='executing')) LIMIT 1",
            (row["tenant_id"], row["endpoint_id"], row["binding_revision"], row["message_id"]))
        if cursor.fetchone() is not None:
            raise MessageWakeUnavailable("original_receiver_has_unresolved_native_effect")
        cursor.execute("SELECT 1 FROM outbox WHERE tenant_id=%s AND topic='communication.receiver.recovery' "
            "AND payload->'lifecycle'->>'phase'='executing' "
            "AND payload->'lifecycle'->'target'->'registration'->>'endpoint_id'=%s "
            "AND payload->'lifecycle'->'target'->>'binding_epoch'=%s LIMIT 1",
            (row["tenant_id"], row["endpoint_id"], str(row["binding_revision"])))
        if cursor.fetchone() is not None:
            raise MessageWakeUnavailable("original_receiver_has_unresolved_lifecycle_effect")
        # Profile eligibility is checked in the issuer's own Scope, while the
        # existing delivery boundary owns Root/Route messaging scope rules.
        original._authorize(command, cursor, "profile." + metadata["profile"])
        checked = SimpleNamespace(authority=original, stored_command=command, admission_command=command,
            endpoint=binding, actor_address=envelope.packet.sender)
        current = self._row(cursor, payload["project_id"], row["operation_id"], lock=True)
        if any(current.get(key) != payload.get(key) for key in
                ("schema_version", "project_id", "message_id", "receiver_id", "actor", "issuer_context", "profile", "command", "request")):
            raise MessageWakeUnavailable("original_message_wake_source_changed")
        source = LifecycleSource(operation_ref=row["operation_id"], command_id=command.command_id, tenant_id=command.tenant_id,
            authority_id=command.authority_id, authority_incarnation=command.authority_incarnation,
            project_id=envelope.packet.project_id, actor_address=envelope.packet.sender, principal_ref=command.principal_ref,
            grant_ref=command.grant_ref, profile=metadata["profile"], command_digest=sha256(command),
            issuer_context_digest=sha256(metadata["issuer_context"]), request_digest=sha256(row["packet_json"]),
            business_deadline=envelope.packet.deadline)
        return checked, source

    def original_read(self, cursor, source):
        _dispatcher, row, metadata = self._load(cursor, source.project_id, source.operation_ref, lock=True)
        authority, projects = self._reader(metadata)
        projects._check_tool_policy("read_message")
        args = {"project_id": source.project_id}
        bound, _root, _command = projects._authorize(authority, cursor, source.project_id, "read_message", args)
        projects._communication_row(bound, cursor, args, row["message_id"])
        command = CommandEnvelope.model_validate_json(json.dumps(row["command_json"]), strict=True)
        if (source.command_digest != sha256(command) or source.command_id != command.command_id
                or source.issuer_context_digest != sha256(metadata["issuer_context"])
                or source.request_digest != sha256(row["packet_json"]) or source.actor_address != row["packet_json"]["sender"]
                or source.principal_ref != command.principal_ref or source.grant_ref != command.grant_ref
                or source.profile != metadata["profile"]):
            raise AcceptanceGuardFailed("original message lifecycle read subject changed")
        return source


def lifecycle_store(recovery, cursor, source):
    """Resolve through real Outbox ownership, never a caller-selected backend."""
    cursor.execute("SELECT topic FROM outbox WHERE tenant_id=%s AND operation_id=%s",
        (recovery.authority.tenant_id, source.operation_ref))
    rows = cursor.fetchall()
    if rows == [("message.delivery",)]:
        return MessageWakeStore(recovery.projects)
    return recovery


def advance_message_wake(service, identity):
    """Called under DeliveryDispatcher's original message and Slot locks.

    Returns None for the unchanged delivery path, or its technical wake state.
    The caller must defer input unless that state is completed. Existing
    possible effects remain readback-only even after message wake is disabled.
    """
    from runtime.receiver_lifecycle_contract import SignedLifecyclePermit
    from runtime.receiver_lifecycle_domain import original_lifecycle_source
    from runtime.receiver_lifecycle_executor import (
        LifecycleExecutorRejected,
        ReceiverLifecycleExecutor,
    )
    from runtime.receiver_lifecycle_issuance import _possible, _state
    from runtime.receiver_lifecycle_readback import require_original_lifecycle_read

    authority = service.authority
    catalog = getattr(authority, "_receiver_lifecycle_catalog", None)
    if catalog is None:
        raise MessageWakeUnavailable("message_wake_project_catalog_unavailable")
    projects = ProjectService(SharedService(authority, LocalCredentialAuthenticator(authority.context)), catalog, profile="engineer")
    store = MessageWakeStore(projects)
    with authority.transaction() as (_bound, connection), connection.cursor() as cursor:
        cursor.execute("SELECT packet_json->>'project_id',endpoint_id FROM delivery_messages "
            "WHERE tenant_id=%s AND message_id=%s AND operation_id=%s",
            (authority.tenant_id, identity["message_id"], identity["operation_id"]))
        found = cursor.fetchone()
        if found is None:
            raise MessageWakeUnavailable("original_message_missing")
        project, endpoint_id = found
        cursor.execute("SELECT payload->'receiver_wake' FROM outbox WHERE tenant_id=%s AND operation_id=%s AND topic='message.delivery'",
            (authority.tenant_id, identity["operation_id"]))
        retained = cursor.fetchone()[0]
        if retained is None and not enabled(authority, endpoint_id):
            return None
        try:
            frame = store._row(cursor, project, identity["operation_id"], lock=True)
        except MessageWakeUnavailable:
            if retained is None:
                return None  # Legacy/message_only/wait semantics remain with delivery.
            raise
        completed = frame["operation"]["state"] == "completed"
        if (frame["operation"]["state"] == "definitively_rejected"
                and frame.get("lifecycle", {}).get("receipt", {}).get("receipt", {}).get("outcome") == "definitively_not_started"):
            # Keep that negative startup fact. An independently prepared,
            # currently ready receiver may still accept the original Message
            # through ordinary final admission; this path does not prepare it.
            return None
        if (not enabled(authority, endpoint_id) and not _possible(frame, _state(frame))):
            return None  # Disabling automatic preparation does not disable ordinary delivery.
    transport = getattr(authority, "_receiver_lifecycle_transports", {}).get(endpoint_id)
    if transport is None:
        if completed:
            return frame["operation"]  # Ordinary final admission still checks the actual receiver.
        raise MessageWakeUnavailable("message_wake_fenced_transport_unavailable")
    if completed:
        from runtime.communication_message_restore import continue_stopped_message

        if not continue_stopped_message(store, transport, project, identity["operation_id"]):
            return frame["operation"]

    class MessageWakeExecutor(ReceiverLifecycleExecutor):
        def _caller(self, cursor, authority, project, operation_ref, _credential):
            payload = self.recovery._row(cursor, project, operation_ref, lock=True)
            if payload["receiver_id"] != self.config.binding.registration.endpoint_id:
                raise LifecycleExecutorRejected("original Message receiver differs from installed transport")
            data = _state(payload)
            self._history_only = _possible(payload, data)
            if self._history_only:
                if data is None or data.get("permit") is None:
                    raise LifecycleExecutorRejected("original Message wake read artifacts are unavailable")
                signed = SignedLifecyclePermit.model_validate_json(json.dumps(data["permit"]), strict=True)
                require_original_lifecycle_read(self.recovery, cursor, signed)
            else:
                original_lifecycle_source(self.recovery, cursor, payload)
            return payload

        def _host_boundary(self):
            super()._host_boundary()
            if not self._history_only and not enabled(self.authority, endpoint_id):
                raise MessageWakeUnavailable("message_wake_disabled")

        def _operation(self, project, operation_ref, _credential):
            with self.authority.transaction() as (_bound, connection), connection.cursor() as cursor:
                return self.recovery._row(cursor, project, operation_ref)["operation"]

    return MessageWakeExecutor(store, transport).advance(project, identity["operation_id"], None)
