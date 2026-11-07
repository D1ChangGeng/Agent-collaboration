"""Current read authority over an immutable original lifecycle permit.

This is an internal Core hook. A network endpoint must first authenticate a
fresh readback-purpose request; possession of an expired mutation permit is not
caller authentication. Current endpoint selection is deliberately not consulted.
"""
from __future__ import annotations

import json
from copy import copy

from runtime.auth import LocalCredentialAuthenticator
from runtime.errors import AuthorizationDenied
from runtime.models import AuthenticatedContext, CommandEnvelope
from runtime.project_common import handle
from runtime.receiver_crypto import sha256
from runtime.receiver_lifecycle_contract import (
    SignedLifecyclePermit,
    lifecycle_plan_digest,
)
from runtime.receiver_recovery_operations import RecoveryRequest


def require_original_lifecycle_read(recovery, cursor, signed_permit):
    from runtime.project_service import ProjectService
    from runtime.surfaces import SharedService

    signed = SignedLifecyclePermit.model_validate_json(signed_permit.model_dump_json(), strict=True)
    permit, source, target = signed.permit, signed.permit.plan.source, signed.permit.plan.target
    payload = recovery._row(cursor, source.project_id, source.operation_ref, lock=True)
    data = payload.get("lifecycle", {})
    command = CommandEnvelope.model_validate_json(json.dumps(payload["command"]), strict=True)
    message_wake = payload.get("schema_version") == "acs-message-wake/1"
    request = payload["request"] if message_wake else RecoveryRequest.model_validate(payload["request"]).model_dump(mode="json")
    operation = payload["operation"]
    if (data.get("permit") != signed.model_dump(mode="json") or data.get("permit_digest") != sha256(permit)
            or data.get("first_plan_digest") != lifecycle_plan_digest(permit.plan)
            or operation.get("operation_id") != source.operation_ref or operation.get("receiver_ref") != target.registration.endpoint_id
            or operation.get("binding_epoch") != target.binding_epoch or source.project_id != payload["project_id"]
            or source.actor_address != payload["actor"] or source.profile != payload["profile"]
            or source.command_id != command.command_id or source.command_digest != sha256(command)
            or source.principal_ref != command.principal_ref or source.grant_ref != command.grant_ref
            or source.issuer_context_digest != sha256(payload["issuer_context"])
            or source.request_digest != sha256(request)):
        raise AuthorizationDenied(recovery.authority.context.principal_ref, recovery.authority.context.grant_ref)
    if message_wake:
        from runtime.communication_message_wake import MessageWakeStore

        if type(recovery) is not MessageWakeStore:
            raise AuthorizationDenied(source.principal_ref, source.grant_ref)
        return recovery.original_read(cursor, source)
    context = AuthenticatedContext(**payload["issuer_context"])
    if (context.tenant_id, context.authority_id, context.authority_incarnation) != (
            source.tenant_id, source.authority_id, source.authority_incarnation):
        raise AuthorizationDenied(context.principal_ref, context.grant_ref)
    original = copy(recovery.authority)
    original.context = context
    projects = ProjectService(SharedService(original, LocalCredentialAuthenticator(context)),
                              recovery.projects.catalog, profile=payload["profile"])
    args = {"project_id": source.project_id,
            "scope_handle": handle("scope", source.project_id, target.registration.scope_id)}

    def current():
        projects._check_tool_policy("list_harnesses")
        bound, root, _command = projects._authorize(original, cursor, source.project_id, "list_harnesses", args)
        scopes = projects._visible_scopes(bound, cursor, root)
        if (scopes is not None and target.registration.scope_id not in {*scopes, root[0]}
                or projects._communication_address(cursor, source.project_id) != source.actor_address):
            raise AuthorizationDenied(context.principal_ref, context.grant_ref)

    current()
    # Physical origin is still the accepted operation and its exact outbox,
    # independently of today's endpoint/Session/generation assignment.
    cursor.execute("SELECT command_id,provider,provider_workflow_id FROM operations WHERE tenant_id=%s "
        "AND operation_id=%s FOR SHARE", (source.tenant_id, source.operation_ref))
    row = cursor.fetchone()
    if row != (source.command_id, "communication-recovery", source.operation_ref):
        raise AuthorizationDenied(context.principal_ref, context.grant_ref)
    current()  # A prior role/Grant observation cannot survive a later row wait.
    return source


def resolve_original_lifecycle_read(recovery, signed_permit):
    """Close Core SQL before a Node reads its original private Driver journal."""
    with recovery.authority.transaction() as (_authority, connection), connection.cursor() as cursor:
        from runtime.communication_message_wake import lifecycle_store

        store = lifecycle_store(recovery, cursor, signed_permit.permit.plan.source)
        return require_original_lifecycle_read(store, cursor, signed_permit)
