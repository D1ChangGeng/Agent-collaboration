"""Shared trusted Node identity and committed-message authorization for native receivers."""
from __future__ import annotations

import json
from copy import copy
from datetime import timedelta

from runtime.auth import AuthenticatedContext
from runtime.codex_driver import AuthorizedOperation, BindingIdentity
from runtime.communication_permissions import committed_delivery_context
from runtime.delivery_models import InvocationRequest
from runtime.delivery_node import InvocationPreCallRejected
from runtime.lifetimes import earliest
from runtime.models import CommandEnvelope


class NativeReceiverRejected(RuntimeError):
    pass


def bind_registered_receiver(authority, registration, deployment_policy_sha256, runtime_id, capacity_id):
    if registration.config_sha256 != deployment_policy_sha256 or registration.runtime_id != runtime_id:
        raise NativeReceiverRejected("receiver deployment binding changed")
    with authority._connect() as connection:
        actor = connection.execute(
            "SELECT observer_ref,observer_grant_ref FROM enrolled_nodes WHERE tenant_id=%s AND node_id=%s "
            "AND authority_id=%s AND authority_incarnation=%s AND status='active'",
            (registration.tenant_id, registration.node_id, registration.authority_id, registration.authority_incarnation),
        ).fetchone()
    if actor is None:
        raise NativeReceiverRejected("configured Node identity is unavailable")
    authority.context = AuthenticatedContext(registration.tenant_id, registration.authority_id,
        registration.authority_incarnation, actor[0], actor[1])
    if authority.access_mode == "owner":
        authority.owner_identity_ref = actor[1]
    return BindingIdentity(registration.node_id, registration.boot_incarnation, registration.runtime_id,
                           capacity_id, registration.agent_slot_id, registration.node_binding_revision)


class NativeReceiverAuthority:
    def _lifecycle_operation(self, action: str) -> AuthorizedOperation:
        prefix = "spawn" if action == "spawn" else "close"
        return AuthorizedOperation(
            self.settings[prefix + "_operation_id"],
            self.settings[prefix + "_command_id"],
            self.settings[prefix + "_message_id"],
            self.authority.context.grant_ref,
            None if getattr(self.config, "access_mode", "shared") == "owner" else earliest(self.config.binding.registration.expires_at,
                self.clock.now() + timedelta(minutes=5)),
        )

    def _domain_invocation(self, operation: AuthorizedOperation) -> InvocationRequest:
        prefix = "delivery-invocation:"
        if not operation.operation_id.startswith(prefix):
            raise NativeReceiverRejected("Native Driver operation is outside a Delivery Attempt")
        attempt_id = operation.operation_id.removeprefix(prefix)
        with self.authority._connect() as connection:
            row = connection.execute(
                "SELECT a.invocation_json,m.command_json,m.deadline FROM delivery_attempts a "
                "JOIN delivery_messages m ON m.tenant_id=a.tenant_id AND m.message_id=a.message_id "
                "WHERE a.tenant_id=%s AND a.attempt_id=%s",
                (self.authority.tenant_id, attempt_id),
            ).fetchone()
            if row is None or not isinstance(row[0], dict):
                raise NativeReceiverRejected("Native Driver Attempt is unavailable")
            invocation = InvocationRequest.model_validate_json(json.dumps(row[0]), strict=True)
            command = CommandEnvelope.model_validate_json(json.dumps(row[1], default=str), strict=True)
            if invocation.envelope.packet.schema_version == "acs-delivery/1":
                raise InvocationPreCallRejected("legacy_task_invocation_retired")
            self._authorize_domain_command(
                command, connection.cursor(), "runtime.invoke",
                invocation.envelope.packet.target_scope_id, invocation.envelope.packet,
            )
        if (
            (invocation.invocation_id, invocation.command_id, invocation.message_id)
            != (operation.operation_id, operation.command_id, operation.message_id)
            or operation.grant_ref != command.grant_ref
            or row[2] is not None and (operation.deadline is None or operation.deadline > row[2])
        ):
            raise NativeReceiverRejected("Native Driver operation lineage changed")
        return invocation

    def _authorize_domain_command(self, command, cursor, permission, scope_id, packet) -> None:
        actor = copy(self.authority)
        actor.context = committed_delivery_context(cursor, command, packet)
        actor._authorize(
            command,
            cursor,
            permission,
            scope_id,
            clock_skew_seconds=0 if getattr(self, "clock", None) is not None else self.config.clock_skew_seconds,
        )

    def _current(self, operation: AuthorizedOperation, observed: BindingIdentity) -> None:
        if observed != self.binding:
            raise NativeReceiverRejected("Native receiver Driver binding changed")
        with self.authority._connect() as connection, connection.cursor() as cursor:
            self.authority.enrollment._active_runtime(cursor, self.binding.runtime_id)
        if operation.operation_id in {
            self.settings["spawn_operation_id"], self.settings["close_operation_id"],
        }:
            if operation.grant_ref != self.authority.context.grant_ref:
                raise NativeReceiverRejected("Native receiver lifecycle identity changed")
            return
        self._domain_invocation(operation)

    def _authorize_invocation(self, invocation, observed) -> AuthorizedOperation:
        if observed != self.binding:
            raise NativeReceiverRejected("Native receiver invocation binding changed")
        operation = AuthorizedOperation(
            invocation.invocation_id, invocation.command_id, invocation.message_id,
            invocation.envelope.grant_ref, invocation.envelope.packet.deadline,
        )
        self._domain_invocation(operation)
        return operation

    def authorize_current(self, admission) -> bool:
        return self.authority.receiver_transport.current_authority(
            admission,
            clock_skew_seconds=0 if getattr(self, "clock", None) is not None else self.config.clock_skew_seconds,
        )

    def native_invoke(self, admission):
        invocation = self.bridge._invocation(admission)
        if invocation.envelope.packet.schema_version == "acs-delivery/1":
            raise InvocationPreCallRejected("legacy_task_invocation_retired")
        result = self.bridge(admission)
        return result

    def readiness(self, admission):
        return self.bridge.readiness(admission)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self.driver.owned is not None and self.driver.owned.process.poll() is None:
                self.driver.terminate(self._lifecycle_operation("close"))
        finally:
            try:
                self.driver.detach_transport()
            finally:
                self.supervisor.close()
