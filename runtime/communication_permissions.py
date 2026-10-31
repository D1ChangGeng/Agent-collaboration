"""Profile inheritance expands role eligibility, never an operational Grant."""
from __future__ import annotations

from runtime.errors import AuthorizationDenied
from runtime.models import AuthenticatedContext


def committed_delivery_context(cursor, command, packet):
    """Recover identity only after the caller verifies the committed envelope.

    A registered Client origin is durable authority evidence. The packet body
    and an arbitrary principal string cannot grant the Client capability.
    """
    client = packet.schema_version == "acs-message/1" and packet.sender.startswith("client:")
    if client:
        cursor.execute("SELECT 1 FROM communication_clients WHERE tenant_id=%s AND project_id=%s "
                       "AND address=%s AND principal_ref=%s", (command.tenant_id, packet.project_id,
                            packet.sender, command.principal_ref))
        if cursor.fetchone() is None:
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
    return AuthenticatedContext(command.tenant_id, command.authority_id, command.authority_incarnation,
                                command.principal_ref, command.grant_ref, trusted_client=client)


def expanded_permissions(permissions):
    result = set(permissions or ())
    if "profile.root_manager" in result:
        result.update({"profile.route_manager", "profile.engineer", "profile.reviewer"})
    if "profile.route_manager" in result:
        result.update({"profile.engineer", "profile.reviewer"})
    return result


def permits_project_message_scope(cursor, context, command, sender_scope, target_scope):
    """Permit a project's Root↔Route channel without widening management Grants."""
    project_id=command.payload.get("communication_project_id")
    if not isinstance(project_id,str):
        return False
    cursor.execute("SELECT scope_id FROM collaboration_projects WHERE tenant_id=%s AND project_id=%s AND state='active'",
                   (context.tenant_id,project_id))
    project=cursor.fetchone()
    if project is None:
        return False
    root_scope=project[0]
    if sender_scope!=root_scope and target_scope!=root_scope:
        return False
    cursor.execute("SELECT 1 FROM collaboration_routes WHERE tenant_id=%s AND project_id=%s AND scope_id=%s "
                   "UNION ALL SELECT 1 FROM collaboration_projects WHERE tenant_id=%s AND project_id=%s AND scope_id=%s",
                   (context.tenant_id,project_id,target_scope,context.tenant_id,project_id,target_scope))
    if cursor.fetchone() is None:
        return False
    if context.trusted_client and sender_scope==root_scope:
        return True
    from runtime.communication import CONTACTS
    cursor.execute("SELECT 1 FROM "+CONTACTS+" c JOIN agent_slots s USING(agent_slot_id) WHERE c.tenant_id=%s "
                   "AND c.project_id=%s AND c.principal_ref=%s AND c.grant_ref=%s AND s.scope_id=%s AND s.status='active'",
                   (context.tenant_id,project_id,context.principal_ref,context.grant_ref,sender_scope))
    return cursor.fetchone() is not None
