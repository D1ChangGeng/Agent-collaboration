"""Shared trusted Node identity and committed-message authorization for native receivers."""
from __future__ import annotations

import json
from copy import copy
from datetime import timedelta

from runtime.auth import AuthenticatedContext
from runtime.codex_driver import AuthorizedObservation, AuthorizedOperation, BindingIdentity
from runtime.communication_permissions import committed_delivery_context
from runtime.delivery_models import InvocationRequest
from runtime.delivery_node import InvocationPreCallRejected
from runtime.errors import RuntimeErrorBase
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
    def _observation_current(self, operation):
        prefix = "native-observation:delivery-invocation:"
        if (not isinstance(operation, AuthorizedObservation) or not operation.operation_id.startswith(prefix)
                or operation.grant_ref != self.authority.context.grant_ref):
            raise NativeReceiverRejected("Native observation capability differs")
        attempt = operation.operation_id.removeprefix(prefix)
        with self.authority._connect() as connection, connection.cursor() as cursor:
            runtime, _node, _binding, _key, valid_until = self.authority.enrollment._active_runtime(cursor, self.binding.runtime_id)
            if (runtime["observer_ref"] != self.authority.context.principal_ref
                    or runtime["observer_grant_ref"] != operation.grant_ref):
                raise NativeReceiverRejected("Native observer is not the enrolled Runtime observer")
            cursor.execute("SELECT invocation_json FROM delivery_attempts WHERE tenant_id=%s AND attempt_id=%s",
                           (self.authority.tenant_id, attempt))
            row = cursor.fetchone()
        if row is None:
            raise NativeReceiverRejected("original Native invocation is unavailable")
        invocation = InvocationRequest.model_validate_json(json.dumps(row[0]), strict=True)
        packet = invocation.envelope.packet
        if ((invocation.invocation_id, invocation.command_id, invocation.message_id,
             packet.target_scope_id, packet.target_agent_slot_id) !=
                (operation.operation_id.removeprefix("native-observation:"), operation.command_id,
                 operation.message_id, runtime["scope_id"], self.binding.agent_slot_id)
                or packet.schema_version not in {"acs-message/1", "acs-notice/1"}):
            raise NativeReceiverRejected("Native observation belongs to another receiving Slot")
        if valid_until is not None:
            self.clock.require_before(valid_until)
        return invocation

    def _authorize_observation(self, invocation, observed):
        if observed != self.binding:
            raise NativeReceiverRejected("Native observation binding changed")
        operation = AuthorizedObservation("native-observation:" + invocation.invocation_id,
            invocation.command_id, invocation.message_id, self.authority.context.grant_ref, None)
        if self._observation_current(operation) != invocation:
            raise NativeReceiverRejected("Native observation differs from the original invocation")
        return operation

    def _lifecycle_operation(self, action: str) -> AuthorizedOperation:
        if action not in ("spawn", "close"):
            raise NativeReceiverRejected("Native bootstrap lifecycle action is unsupported")
        prefix = action
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
        if isinstance(operation, AuthorizedObservation):
            self._observation_current(operation)
            return
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

    def read_native_source(self, admission, provider):
        return self.bridge.read_native_source(admission, provider)

    def authorize_native_source_read(self, admission):
        """Technical reader owns this receiving Slot, not the old sender Grant.

        The Core's signed request delegates an already checked message ACL.
        Current enrolled-Node/runtime/endpoint trust is still checked locally
        before and after the refs-only journal read.
        """
        try:
            invocation = self.bridge._invocation(admission)
            self._authorize_observation(invocation, self.binding)
            registration = self.config.binding.registration
            with self.authority._connect() as connection:
                row = connection.execute("SELECT registration_json,status FROM delivery_endpoint_registrations "
                    "WHERE tenant_id=%s AND endpoint_id=%s", (registration.tenant_id, registration.endpoint_id)).fetchone()
            return row is not None and row[1] == "active" and row[0] == registration.model_dump(mode="json")
        except (NativeReceiverRejected, ValueError, RuntimeError, RuntimeErrorBase):
            return False

    def close(self):
        if self._closed:
            return
        self._closed = True
        controller = getattr(self, "lifecycle_node", None)
        if controller is not None:
            controller.close()
        try:
            if self.driver.owned is not None and self.driver.owned.process.poll() is None:
                self.driver.terminate(self._lifecycle_operation("close"))
        finally:
            try:
                # Cleanup authority comes from proven process ownership even
                # when the lifecycle Grant/deadline has expired. Stop that
                # capacity before releasing its journal/kernel claim.
                self.supervisor.close()
            finally:
                self.driver.detach_transport()
