"""Enforce explicitly configured team policy at the Domain delivery boundary."""
from __future__ import annotations

from runtime.errors import AuthorizationDenied


def enforce_team_delivery(cursor, command, packet, policy, *, recovery):
    team = policy.get("collaboration_team")
    if team is None:
        return
    cursor.execute("SELECT clock_timestamp()")
    now = cursor.fetchone()[0]
    for item in team["policies"]:
        rules = item["rules"]
        if (packet.activation not in rules["allowed_activations"]
                or packet.delivery_policy not in rules["allowed_delivery_policies"]
                or (packet.deadline - command.issued_at).total_seconds() > rules["max_deadline_seconds"]):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
    cursor.execute(
        "SELECT b.project_id,b.budget_ref,b.max_messages,b.max_pending_messages,b.expires_at,"
        "b.messages_used,m.status,g.revoked_at,g.expires_at "
        "FROM collaboration_team_members m JOIN collaboration_team_budgets b "
        "USING(tenant_id,project_id,scope_id,budget_ref) JOIN grants g ON g.grant_ref=m.grant_ref "
        "WHERE m.tenant_id=%s AND m.project_id=%s AND m.scope_id=%s AND m.agent_slot_id=%s "
        "FOR UPDATE OF b,m,g",
        (command.tenant_id, team["project_id"], packet.target_scope_id, packet.target_agent_slot_id),
    )
    budget = cursor.fetchone()
    if (budget is None or budget[6] != "active" or budget[7] is not None
            or min(budget[4], budget[8]) <= now or packet.deadline > min(budget[4], budget[8])):
        raise AuthorizationDenied(command.principal_ref, command.grant_ref)
    cursor.execute("SELECT project_id,budget_ref FROM collaboration_budget_reservations "
                   "WHERE tenant_id=%s AND message_id=%s FOR UPDATE",
                   (command.tenant_id, command.target_id))
    reservation = cursor.fetchone()
    if reservation is not None:
        if reservation != budget[:2]:
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        return
    if recovery or budget[5] >= budget[2]:
        raise AuthorizationDenied(command.principal_ref, command.grant_ref)
    cursor.execute("SELECT count(*) FROM collaboration_budget_reservations r JOIN delivery_messages m "
                   "USING(tenant_id,message_id) WHERE r.tenant_id=%s AND r.project_id=%s "
                   "AND r.budget_ref=%s AND m.state IN ('queued','delivering','retry_wait','uncertain')",
                   (command.tenant_id, budget[0], budget[1]))
    if cursor.fetchone()[0] >= budget[3]:
        raise AuthorizationDenied(command.principal_ref, command.grant_ref)
    cursor.execute("UPDATE collaboration_team_budgets SET messages_used=messages_used+1 "
                   "WHERE tenant_id=%s AND project_id=%s AND budget_ref=%s",
                   (command.tenant_id, budget[0], budget[1]))
    cursor.execute("INSERT INTO collaboration_budget_reservations(tenant_id,project_id,budget_ref,message_id) "
                   "VALUES (%s,%s,%s,%s)", (command.tenant_id, budget[0], budget[1], command.target_id))
