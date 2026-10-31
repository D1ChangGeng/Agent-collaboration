"""Finite system notices through configured managers and the existing delivery ledger."""
from __future__ import annotations

import json
from dataclasses import replace

from runtime.delivery import DeliveryRejected, DeliveryService, digest
from runtime.delivery_models import NoticePacket
from runtime.errors import AuthorizationDenied
from runtime.models import CommandEnvelope
from runtime.project_common import handle, parse_handle

OBSTACLES = frozenset({"blocked", "uncertain", "budget_exhausted", "expired"})


def bind_supervisor(cursor, tenant, project, slot, manager):
    """Adopt the configuring manager once; partial edits preserve that relationship."""
    cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("communication-supervisors:" + tenant + ":" + project,))
    cursor.execute("SELECT manager_address FROM communication_supervisors WHERE tenant_id=%s "
                   "AND project_id=%s AND agent_slot_id=%s", (tenant, project, slot))
    if cursor.fetchone():
        return
    seen = {handle("collaborator", project, slot)}
    address = manager
    for _ in range(128):
        if address in seen:
            raise ValueError("communication manager relationship would form a cycle")
        seen.add(address)
        if address.startswith("client:"):
            break
        parent_slot = parse_handle(address, "collaborator", project)
        cursor.execute("SELECT manager_address FROM communication_supervisors WHERE tenant_id=%s "
                       "AND project_id=%s AND agent_slot_id=%s", (tenant, project, parent_slot))
        parent = cursor.fetchone()
        if not parent:
            break
        address = parent[0]
    else:
        raise ValueError("communication manager chain exceeds the configured team bound")
    cursor.execute("INSERT INTO communication_supervisors VALUES (%s,%s,%s,%s)",
                   (tenant, project, slot, manager))


def _forward(cursor, tenant, project, message_id, source_slot):
    cursor.execute("SELECT packet_json->>'sender' FROM delivery_messages WHERE tenant_id=%s AND message_id=%s",
                   (tenant, message_id))
    sender = cursor.fetchone()[0]
    cursor.execute("SELECT state,code FROM communication_notices WHERE tenant_id=%s AND project_id=%s "
                   "AND message_id=%s ORDER BY sequence LIMIT 1", (tenant, project, message_id))
    original = cursor.fetchone()
    cursor.execute("SELECT manager_address FROM communication_supervisors WHERE tenant_id=%s "
                   "AND project_id=%s AND agent_slot_id=%s", (tenant, project, source_slot))
    manager = cursor.fetchone()
    if manager:
        recipient = manager[0]
    else:
        cursor.execute("SELECT address FROM communication_clients WHERE tenant_id=%s AND project_id=%s LIMIT 2",
                       (tenant, project))
        clients = cursor.fetchall()
        recipient = clients[0][0] if len(clients) == 1 else sender
    return recipient, bool(manager and recipient.startswith("collaborator:")), original


def _insert(cursor, tenant, project, message_id, recipient, source_slot, native, state, code):
    cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("communication-notices:" + tenant + ":" + project,))
    cursor.execute("INSERT INTO communication_notices(tenant_id,project_id,message_id,recipient,state,code) "
                   "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING sequence",
                   (tenant, project, message_id, recipient, state, code or "delivery_unconfirmed"))
    if cursor.fetchone() is None:
        return  # Includes repeated failures and a malformed/cyclic old relationship.
    cursor.execute("INSERT INTO communication_notice_routes(tenant_id,project_id,message_id,recipient,source_slot_id,native_requested) "
                   "VALUES (%s,%s,%s,%s,%s,%s)", (tenant, project, message_id, recipient, source_slot, native))
    cursor.execute("SELECT pg_notify('acs_domain_change',%s)", (project,))


def _unreachable(cursor, tenant, project, message_id, recipient, code):
    cursor.execute("UPDATE communication_notice_routes SET native_requested=FALSE,last_error=%s "
                   "WHERE tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s",
                   (code, tenant, project, message_id, recipient))
    slot = parse_handle(recipient, "collaborator", project)
    next_recipient, native, original = _forward(cursor, tenant, project, message_id, slot)
    if original:
        _insert(cursor, tenant, project, message_id, next_recipient, slot, native, *original)


def record_obstacle(cursor, row, state, code):
    packet = row["packet_json"]
    if state not in OBSTACLES:
        return
    schema = packet.get("schema_version")
    if schema == "acs-message/1":
        project, slot = packet["project_id"], packet["target_agent_slot_id"]
        recipient, native, _original = _forward(cursor, row["tenant_id"], project, row["message_id"], slot)
        _insert(cursor, row["tenant_id"], project, row["message_id"], recipient, slot, native and state != "uncertain", state, code)
    elif schema == "acs-notice/1":
        # A possibly accepted manager invocation does not justify invoking its
        # parent. Silence/unknown outcome is neither unreachability nor failure.
        cursor.execute("SELECT 1 FROM delivery_receipts WHERE tenant_id=%s AND message_id=%s "
                       "AND layer IN ('runtime_dispatched','runtime_acknowledged') LIMIT 1",
                       (row["tenant_id"], row["message_id"]))
        dispatched = cursor.fetchone() is not None
        if state != "uncertain" and (not dispatched or code == "native_pre_call_rejected"):
            _unreachable(cursor, row["tenant_id"], packet["project_id"], packet["origin_message_id"], packet["recipient"], code)


def _content(project, message_id, target, state, code):
    return json.dumps({"message_handle": handle("message", project, message_id), "target": target,
                       "delivery_state": state, "code": code}, ensure_ascii=False, sort_keys=True)


def authorize_notice(cursor, command, packet):
    """Revalidate the exact persisted notice and current receiving manager identity."""
    from runtime.communication import CONTACTS
    cursor.execute("SELECT n.state,n.code,d.packet_json->>'recipient' FROM communication_notices n "
                   "JOIN communication_notice_routes r USING(tenant_id,project_id,message_id,recipient) "
                   "JOIN communication_supervisors s ON s.tenant_id=r.tenant_id AND s.project_id=r.project_id "
                   "AND s.agent_slot_id=r.source_slot_id AND s.manager_address=r.recipient "
                   "JOIN delivery_messages d ON d.tenant_id=n.tenant_id AND d.message_id=n.message_id "
                   "WHERE n.tenant_id=%s AND n.project_id=%s AND n.message_id=%s AND n.recipient=%s "
                   "AND n.sequence=%s AND r.delivery_message_id=%s AND r.native_requested",
                   (command.tenant_id, packet.project_id, packet.origin_message_id, packet.recipient,
                    packet.notification_sequence, command.target_id))
    row = cursor.fetchone()
    if row is None or packet.content != _content(packet.project_id, packet.origin_message_id, row[2], row[0], row[1]):
        raise DeliveryRejected("system_notice_binding_changed")
    cursor.execute("SELECT 1 FROM " + CONTACTS + " m WHERE m.tenant_id=%s AND m.project_id=%s "
                   "AND m.agent_slot_id=%s AND m.principal_ref=%s AND m.grant_ref=%s "
                   "AND m.profile IN ('root_manager','route_manager')",
                   (command.tenant_id, packet.project_id, packet.target_agent_slot_id, command.principal_ref, command.grant_ref))
    if cursor.fetchone() is None:
        raise AuthorizationDenied(command.principal_ref, command.grant_ref)


def queue_communication_notices(authority, *, limit=16):
    """Atomically queue a bounded set, before any possible external Native effect.

    The manager's current Grant authorizes receipt at its own endpoint. It is
    an authorization reference, never the notice's author or an Agent reply.
    """
    if type(limit) is not int or not 1 <= limit <= 64:
        raise ValueError("bounded notice scan required")
    from runtime.communication import CONTACTS
    with authority.transaction() as (bound, connection), connection.cursor() as cursor:
        cursor.execute("SELECT n.project_id,n.message_id,n.recipient,n.sequence,n.state,n.code,d.packet_json->>'recipient' "
            "FROM communication_notice_routes r JOIN communication_notices n USING(tenant_id,project_id,message_id,recipient) "
            "JOIN delivery_messages d ON d.tenant_id=n.tenant_id AND d.message_id=n.message_id "
            "WHERE r.tenant_id=%s AND r.native_requested AND r.delivery_message_id IS NULL "
            "ORDER BY n.sequence LIMIT %s FOR UPDATE OF r SKIP LOCKED", (authority.tenant_id, limit))
        pending = cursor.fetchall()
        for project, message_id, recipient, sequence, state, code, target in pending:
            slot = parse_handle(recipient, "collaborator", project)
            cursor.execute("SELECT DISTINCT m.principal_ref,m.grant_ref,s.scope_id FROM " + CONTACTS + " m "
                "JOIN agent_slots s USING(agent_slot_id) JOIN grants g ON g.grant_ref=m.grant_ref "
                "WHERE m.tenant_id=%s AND m.project_id=%s AND m.agent_slot_id=%s AND s.tenant_id=m.tenant_id "
                "AND s.status='active' AND m.profile IN ('root_manager','route_manager') "
                "AND g.principal_ref=m.principal_ref AND g.revoked_at IS NULL "
                "AND (g.expires_at IS NULL OR g.expires_at>clock_timestamp())", (authority.tenant_id, project, slot))
            managers = cursor.fetchall()
            cursor.execute("SELECT e.endpoint_id,e.revision FROM delivery_endpoints e "
                "LEFT JOIN collaboration_team_members m ON m.tenant_id=e.tenant_id AND m.project_id=%s AND m.agent_slot_id=e.agent_slot_id "
                "LEFT JOIN collaboration_teams t ON t.tenant_id=m.tenant_id AND t.project_id=m.project_id AND t.scope_id=m.scope_id "
                "WHERE e.tenant_id=%s AND e.agent_slot_id=%s AND e.status='active' AND e.supports_invoke "
                "AND (e.expires_at IS NULL OR e.expires_at>clock_timestamp()) "
                "AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(t.definition->'members') member "
                "WHERE member->>'agent_slot_id'=e.agent_slot_id AND member->>'endpoint_id' IS NOT NULL "
                "AND member->>'endpoint_id'<>e.endpoint_id)", (project, authority.tenant_id, slot))
            endpoints = cursor.fetchall()
            if len(managers) != 1 or len(endpoints) != 1:
                _unreachable(cursor, authority.tenant_id, project, message_id, recipient, "manager_receiver_unavailable")
                continue
            principal, grant, scope = managers[0]
            identifier = "notice-" + digest([authority.tenant_id, project, message_id, recipient])
            bound.context = replace(authority.context, principal_ref=principal, grant_ref=grant,
                                    agent_slot_id=slot, trusted_client=False)
            bound._communication_notice = True
            command = CommandEnvelope(command_id=identifier, command_type="message.send", idempotency_key=identifier,
                correlation_id=message_id, tenant_id=authority.tenant_id, authority_id=authority.context.authority_id,
                authority_incarnation=authority.context.authority_incarnation, principal_ref=principal, grant_ref=grant,
                target_kind="message", target_id=identifier, expected_revision=0, issued_at=authority.canonical_now(cursor),
                payload={"schema_version": "acs-notice/1", "communication_project_id": project})
            packet = NoticePacket(project_id=project, recipient=recipient, origin_message_id=message_id,
                notification_sequence=sequence, content=_content(project, message_id, target, state, code),
                target_scope_id=scope, target_agent_slot_id=slot)
            try:
                with connection.transaction():
                    cursor.execute("UPDATE communication_notice_routes SET delivery_message_id=%s "
                        "WHERE tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s",
                        (identifier, authority.tenant_id, project, message_id, recipient))
                    DeliveryService(bound, authority._delivery_endpoints).send_message(command, packet,
                        endpoint_id=endpoints[0][0], binding_revision=endpoints[0][1], operation_id="op-" + identifier)
            except (AuthorizationDenied, DeliveryRejected) as error:
                _unreachable(cursor, authority.tenant_id, project, message_id, recipient,
                             getattr(error, "code", "manager_authorization_unavailable"))
