"""Coherent current trust and original-issuer facts for recovery lifecycle.

All queries borrow one caller-owned transaction. This module creates no message,
operation, ledger, grant or Native effect. Its snapshots are not a permission:
the original recovery command must also pass current ProjectService authority.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from psycopg.pq import TransactionStatus

from runtime.errors import AcceptanceGuardFailed, RevisionConflict
from runtime.project_common import digest
from runtime.receiver_crypto import key_fingerprint, sha256, verify
from runtime.receiver_models import EndpointBinding, EndpointRegistration


def _reject():
    raise AcceptanceGuardFailed("current lifecycle recovery authority is unavailable")


def _time(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _reject()
    return value.astimezone(UTC)


def _transaction(cursor):
    connection = cursor.connection
    if connection.autocommit and connection.info.transaction_status != TransactionStatus.INTRANS:
        raise AcceptanceGuardFailed("lifecycle trust snapshot requires a caller-owned transaction")


@dataclass(frozen=True)
class LifecycleAuthorityKey:
    key_id: str
    revision: int
    public_key: str
    fingerprint: str


@dataclass(frozen=True)
class LifecycleEndpointSnapshot:
    binding: EndpointBinding
    binding_epoch: int
    connection_revision: int
    connection_policy_digest: str
    authority_key: LifecycleAuthorityKey
    journal_generation: int
    checked_at: datetime
    valid_until: datetime | None

    def target(self):
        from runtime.receiver_lifecycle_contract import LifecycleTarget

        return LifecycleTarget(registration=self.binding.registration, binding_epoch=self.binding_epoch,
            connection_revision=self.connection_revision, node_key_id=self.binding.node_key_id,
            journal_generation=self.journal_generation)

    @property
    def selection_digest(self):
        return sha256({"binding": self.binding.model_dump(mode="json"), "binding_epoch": self.binding_epoch,
            "connection_revision": self.connection_revision, "connection_policy_digest": self.connection_policy_digest,
            "authority_key": {"key_id": self.authority_key.key_id, "revision": self.authority_key.revision,
                "public_key": self.authority_key.public_key, "fingerprint": self.authority_key.fingerprint},
            "journal_generation": self.journal_generation})


def current_lifecycle_endpoint(authority, cursor, endpoint_id, binding_epoch, *, journal_generation):
    """Read and lock actual selection, registration, enrollment and signing key.

    ``binding_epoch`` is delivery_endpoints.revision, independently versioned
    from EndpointRegistration.endpoint_revision. ``journal_generation`` comes
    from the trusted enrolled transport configuration, never a request body.
    """
    _transaction(cursor)
    if (type(binding_epoch) is not int or binding_epoch < 1 or type(journal_generation) is not int
            or journal_generation < 1 or not isinstance(endpoint_id, str) or not 1 <= len(endpoint_id) <= 256):
        _reject()
    cursor.execute("SELECT to_jsonb(e) FROM delivery_endpoints e WHERE tenant_id=%s AND endpoint_id=%s FOR SHARE NOWAIT",
                   (authority.tenant_id, endpoint_id))
    row = cursor.fetchone()
    if row is None:
        _reject()
    selected = row[0]
    if selected.get("revision") != binding_epoch:
        raise RevisionConflict(endpoint_id, binding_epoch, selected.get("revision"))
    if selected.get("status") != "active" or selected.get("supports_invoke") is not True:
        _reject()
    cursor.execute("SELECT to_jsonb(e),to_jsonb(c),to_jsonb(k) FROM delivery_endpoint_registrations e "
        "JOIN deployment_connection_refs c ON c.tenant_id=e.tenant_id AND c.connection_ref=e.connection_ref "
        "JOIN enrolled_node_keys k ON k.tenant_id=e.tenant_id AND k.key_id=e.node_key_id "
        "WHERE e.tenant_id=%s AND e.endpoint_id=%s AND e.status='active' AND c.status='active' "
        "AND k.status='active' FOR SHARE OF e,c,k NOWAIT", (authority.tenant_id, endpoint_id))
    rows = cursor.fetchall()
    if len(rows) != 1:
        _reject()
    registration_row, connection, registered_key = rows[0]
    registration = EndpointRegistration.model_validate_json(
        json.dumps(registration_row["registration_json"], default=str), strict=True)
    context = authority.context
    if ((registration.tenant_id, registration.authority_id, registration.authority_incarnation, registration.endpoint_id) !=
            (authority.tenant_id, context.authority_id, context.authority_incarnation, endpoint_id)
            or registration_row.get("registration_sha256") != sha256(registration)):
        _reject()
    for name, expected in registration.model_dump(exclude={"schema_version", "purpose", "expires_at"}).items():
        if registration_row.get(name) != expected:
            _reject()
    if any(selected.get(name) != getattr(registration, name)
           for name in ("scope_id", "agent_slot_id", "machine_id", "node_id", "boot_incarnation")):
        _reject()
    runtime, node, node_binding, key, enrollment_expiry = authority.enrollment.current_runtime_snapshot(cursor, registration.runtime_id)
    if (any(runtime.get(name) != expected for name, expected in {
            "tenant_id": registration.tenant_id, "runtime_id": registration.runtime_id,
            "revision": registration.runtime_revision, "node_id": registration.node_id,
            "node_binding_revision": registration.node_binding_revision,
            "node_boot_incarnation": registration.boot_incarnation,
            "scope_id": registration.scope_id, "agent_slot_id": registration.agent_slot_id}.items())
            or any(node.get(name) != expected for name, expected in {
                "tenant_id": registration.tenant_id, "node_id": registration.node_id,
                "authority_id": registration.authority_id, "authority_incarnation": registration.authority_incarnation,
                "current_binding_revision": registration.node_binding_revision,
                "scope_id": registration.scope_id, "agent_slot_id": registration.agent_slot_id}.items())
            or any(node_binding.get(name) != expected for name, expected in {
                "tenant_id": registration.tenant_id, "node_id": registration.node_id,
                "binding_revision": registration.node_binding_revision, "machine_id": registration.machine_id,
                "boot_incarnation": registration.boot_incarnation, "key_id": registered_key.get("key_id")}.items())
            or any(key.get(name) != registered_key.get(name) for name in ("key_id", "tenant_id", "node_id", "public_key", "fingerprint"))
            or (registered_key.get("tenant_id"), registered_key.get("node_id")) != (registration.tenant_id, registration.node_id)
            or registered_key.get("key_id") != registration_row.get("node_key_id")
            or registered_key.get("fingerprint") != key_fingerprint(registered_key["public_key"])):
        _reject()
    if (connection.get("tenant_id") != authority.tenant_id or connection.get("connection_ref") != registration.connection_ref
            or type(connection.get("revision")) is not int or connection["revision"] < 1):
        _reject()
    binding = EndpointBinding(registration=registration, locator_host=connection["locator_host"],
        locator_port=connection["locator_port"], route_class=connection["route_class"],
        node_key_id=key["key_id"], node_public_key=key["public_key"],
        registration_signature=registration_row["registration_signature"])
    verify(binding.node_public_key, binding.registration_signature, registration)
    cursor.execute("SELECT to_jsonb(k) FROM authority_transport_keys k WHERE tenant_id=%s AND authority_id=%s "
        "AND authority_incarnation=%s AND status='active' FOR SHARE NOWAIT", (authority.tenant_id,
            context.authority_id, context.authority_incarnation))
    keys = cursor.fetchall()
    if len(keys) != 1:
        _reject()
    authority_key = keys[0][0]
    if (authority_key.get("tenant_id") != authority.tenant_id or authority_key.get("authority_id") != context.authority_id
            or authority_key.get("authority_incarnation") != context.authority_incarnation
            or authority_key.get("fingerprint") != key_fingerprint(authority_key["public_key"])
            or type(authority_key.get("revision")) is not int or authority_key["revision"] < 1):
        _reject()
    now = _time(authority.canonical_now(cursor))  # All row waits precede the final expiry fence.
    valid_until = None
    if authority.access_mode != "owner":
        expiries = [selected.get("expires_at"), registration_row.get("expires_at"), registration.expires_at,
                    connection.get("expires_at"), authority_key.get("expires_at"), enrollment_expiry]
        valid_until = min(_time(value) for value in expiries)
        if valid_until <= now:
            _reject()
    return LifecycleEndpointSnapshot(binding, binding_epoch, connection["revision"], connection["policy_digest"],
        LifecycleAuthorityKey(authority_key["key_id"], authority_key["revision"], authority_key["public_key"], authority_key["fingerprint"]),
        journal_generation, now, valid_until)


def original_lifecycle_source(recovery, cursor, payload):
    """Recheck the real operation/outbox/dedup lineage and original issuer."""
    from runtime.receiver_lifecycle_contract import LifecycleSource
    from runtime.receiver_recovery_operations import TOPIC, RecoveryRequest

    _transaction(cursor)
    if payload.get("schema_version") == "acs-message-wake/1":
        from runtime.communication_message_wake import MessageWakeStore

        if type(recovery) is not MessageWakeStore:
            _reject()
        return recovery.original_source(cursor, payload)
    request = RecoveryRequest.model_validate(payload["request"])
    if request.action not in {"prepare_receiver", "resume_receiver", "rebind_receiver"}:
        _reject()
    operation = payload["operation"]
    # The writer takes outbox before operations. Take those exact locks in the
    # same order, before source policy or target-row locks, rather than relying
    # on a joined LockRows plan's acquisition order.
    cursor.execute("SELECT message_id,payload FROM outbox WHERE tenant_id=%s AND operation_id=%s AND topic=%s FOR SHARE",
                   (recovery.authority.tenant_id, operation["operation_id"], TOPIC))
    outboxes = cursor.fetchall()
    if len(outboxes) != 1:
        _reject()
    message_id, saved = outboxes[0]
    cursor.execute("SELECT command_id,provider,provider_workflow_id FROM operations WHERE tenant_id=%s AND operation_id=%s FOR SHARE",
                   (recovery.authority.tenant_id, operation["operation_id"]))
    operations = cursor.fetchall()
    if len(operations) != 1:
        _reject()
    command_id, provider, workflow = operations[0]
    checked = recovery._original_authority(cursor, payload, request, lock_endpoint=False)
    stored, context = checked.stored_command, checked.authority.context
    if (stored.command_type != "receiver.recovery" or stored.target_kind != "endpoint"
            or stored.target_id != payload["receiver_id"] or stored.expected_revision != request.expected_revision
            or operation.get("kind") != "recovery" or operation.get("receiver_ref") != payload["receiver_id"]
            or operation.get("binding_epoch") != request.expected_revision):
        _reject()
    immutable = ("schema_version", "project_id", "receiver_id", "actor", "issuer_context", "profile", "request", "command",
                 "rebind_selection")
    if ((command_id, provider, workflow, message_id) != (stored.command_id, "communication-recovery",
            operation["operation_id"], "msg-" + stored.command_id)
            or any(saved.get(name) != payload.get(name) for name in immutable)
            or saved.get("operation", {}).get("operation_id") != operation["operation_id"]):
        _reject()
    owner = "recovery-actor:" + digest([context.authority_incarnation, checked.actor_address])
    cursor.execute("SELECT input_digest,result_json FROM collaboration_commands WHERE tenant_id=%s AND project_id=%s "
        "AND principal_ref=%s AND command_id=%s AND tool_name='receiver.recovery' FOR SHARE",
        (checked.authority.tenant_id, payload["project_id"], owner, stored.command_id))
    receipts = cursor.fetchall()
    if (len(receipts) != 1 or receipts[0][0] != digest([payload["receiver_id"], request.model_dump(mode="json")])
            or receipts[0][1].get("operation_id") != operation["operation_id"]):
        _reject()
    # Recheck after all physical lineage row waits, without renewing the stored command.
    checked = recovery._original_authority(cursor, payload, request, lock_endpoint=False)
    source = LifecycleSource(tenant_id=context.tenant_id, authority_id=context.authority_id,
        authority_incarnation=context.authority_incarnation, operation_ref=operation["operation_id"],
        command_id=stored.command_id, project_id=payload["project_id"], actor_address=checked.actor_address,
        principal_ref=stored.principal_ref, grant_ref=stored.grant_ref, profile=payload["profile"],
        command_digest=sha256(stored), issuer_context_digest=sha256(payload["issuer_context"]),
        request_digest=sha256(request.model_dump(mode="json")), business_deadline=None)
    return checked, source


def checked_lifecycle_authority(recovery, cursor, payload, *, journal_generation,
                                expected_source=None, expected_target=None):
    """Current original-issuer and target facts from one borrowed transaction.

    A signer or Node effect checker calls this with the original outbox payload.
    No network or process callback is accepted here. Expiry and source authority
    are checked again after all target and physical-lineage row waits.
    """
    checked, source = original_lifecycle_source(recovery, cursor, payload)
    from runtime.receiver_rebind import lifecycle_receiver, require_rebind_selection

    if payload["request"].get("action") == "rebind_receiver":
        require_rebind_selection(recovery, cursor, payload, checked)
    endpoint_id, epoch = lifecycle_receiver(payload)
    snapshot = current_lifecycle_endpoint(checked.authority, cursor, endpoint_id, epoch, journal_generation=journal_generation)
    checked, after = original_lifecycle_source(recovery, cursor, payload)
    now = _time(checked.authority.canonical_now(cursor))
    if source != after or expected_source is not None and source != expected_source:
        _reject()
    if snapshot.valid_until is not None and snapshot.valid_until <= now:
        _reject()
    if expected_target is not None and snapshot.target() != expected_target:
        _reject()
    return checked, source, replace(snapshot, checked_at=now)


def resolve_lifecycle_authority(recovery, source, *, journal_generation):
    """Resolve a signed source through actual Core rows for a Node callback.

    Only metadata and current original-issuer authority are returned. An effect
    must additionally verify the persisted execution phase/plan/permit. The
    borrowed transaction is closed before the Node performs any Host read/I/O.
    """
    from runtime.receiver_lifecycle_contract import LifecycleSource

    source = LifecycleSource.model_validate_json(source.model_dump_json(), strict=True)
    authority = recovery.authority
    context = authority.context
    if (source.tenant_id, source.authority_id, source.authority_incarnation) != (
            authority.tenant_id, context.authority_id, context.authority_incarnation):
        _reject()
    with authority.transaction() as (_bound, connection), connection.cursor() as cursor:
        from runtime.communication_message_wake import lifecycle_store

        store = lifecycle_store(recovery, cursor, source)
        payload = store._row(cursor, source.project_id, source.operation_ref, lock=True)
        _checked, current, snapshot = checked_lifecycle_authority(store, cursor, payload,
            journal_generation=journal_generation, expected_source=source)
        return current, snapshot
