"""Natural messages, explicit replies and observational waits on the delivery ledger.

The message packet is authoritative. These actions neither create work nor infer
an Agent's reply from native execution. All public reads recheck live authority.
"""
from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import datetime

import anyio

from runtime.delivery import DeliveryRejected, digest
from runtime.delivery_models import MessagePacket, NoticePacket
from runtime.errors import AuthorizationDenied, InvalidToolArgument, NotFound
from runtime.project_common import handle, parse_handle

CONTACTS = "(SELECT m.tenant_id,m.project_id,m.principal_ref,m.profile,m.grant_ref,m.agent_slot_id FROM collaboration_memberships m " \
    "WHERE NOT EXISTS(SELECT 1 FROM collaboration_team_members t WHERE t.tenant_id=m.tenant_id AND t.project_id=m.project_id AND t.agent_slot_id=m.agent_slot_id) " \
    "UNION SELECT tenant_id,project_id,principal_ref,profile,grant_ref,agent_slot_id FROM collaboration_team_members WHERE status='active')"


def communication_boundary(cursor, authority, command, packet, endpoint_id, revision, *, recovery=False):
    """Validate the actual caller, project and receiving endpoint without Work."""
    authority._authorize(command, cursor, "message.send", packet.target_scope_id)
    if command.payload.get("communication_project_id") != packet.project_id:
        raise DeliveryRejected("message_project_identity_changed")
    if packet.activation == "invoke" and packet.target_agent_slot_id is not None:
        authority._authorize(command, cursor, "runtime.invoke", packet.target_scope_id)
    if packet.deadline is not None and packet.deadline <= authority.canonical_now(cursor):
        raise DeliveryRejected("deadline_expired", "expired")
    cursor.execute("SELECT scope_id FROM collaboration_projects WHERE tenant_id=%s AND project_id=%s AND state='active'",
                   (command.tenant_id, packet.project_id))
    if cursor.fetchone() is None:
        raise DeliveryRejected("project_unavailable")
    if isinstance(packet, NoticePacket):
        from runtime.communication_faults import authorize_notice
        authorize_notice(cursor, command, packet)
    elif packet.sender.startswith("client:"):
        if not (authority.context.trusted_client or getattr(authority, "_communication_recovery", False)):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        cursor.execute("SELECT 1 FROM communication_clients WHERE tenant_id=%s AND project_id=%s AND address=%s AND principal_ref=%s",
                       (command.tenant_id, packet.project_id, packet.sender, command.principal_ref))
    else:
        slot = parse_handle(packet.sender, "collaborator", packet.project_id)
        if authority.context.agent_slot_id is not None and authority.context.agent_slot_id != slot:
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        cursor.execute("SELECT 1 FROM " + CONTACTS + " m JOIN agent_slots s USING(agent_slot_id) "
                       "WHERE m.tenant_id=%s AND m.project_id=%s AND m.principal_ref=%s "
                       "AND m.agent_slot_id=%s AND m.grant_ref=%s AND s.tenant_id=m.tenant_id AND s.status='active'",
                       (command.tenant_id, packet.project_id, command.principal_ref, slot,
                        command.grant_ref))
    if not isinstance(packet, NoticePacket) and cursor.fetchone() is None:
        raise AuthorizationDenied(command.principal_ref, command.grant_ref)
    if packet.recipient.startswith("client:"):
        cursor.execute("SELECT 1 FROM communication_clients WHERE tenant_id=%s AND project_id=%s AND address=%s",
                       (command.tenant_id, packet.project_id, packet.recipient))
        if cursor.fetchone() is None or packet.target_agent_slot_id is not None or endpoint_id is not None:
            raise DeliveryRejected("recipient_binding_mismatch")
        return {"machine_id": None, "node_id": None, "boot_incarnation": None}, digest({"authority_inbox": packet.project_id}), digest({
            "project_id": packet.project_id, "sender": packet.sender, "recipient": packet.recipient})
    target = parse_handle(packet.recipient, "collaborator", packet.project_id)
    if target != packet.target_agent_slot_id:
        raise DeliveryRejected("recipient_binding_mismatch")
    cursor.execute("SELECT 1 FROM agent_slots s WHERE s.tenant_id=%s AND s.agent_slot_id=%s "
                   "AND s.scope_id=%s AND s.status='active' AND EXISTS "
                   "(SELECT 1 FROM " + CONTACTS + " m JOIN grants g ON g.grant_ref=m.grant_ref "
                   "WHERE m.tenant_id=s.tenant_id AND m.project_id=%s AND m.agent_slot_id=s.agent_slot_id "
                   "AND g.tenant_id=m.tenant_id AND g.principal_ref=m.principal_ref "
                   "AND (%s OR (g.revoked_at IS NULL AND (g.expires_at IS NULL OR g.expires_at>clock_timestamp()) "
                   "AND g.authority_id=%s AND g.authority_incarnation=%s)))",
                   (command.tenant_id, target, packet.target_scope_id, packet.project_id, packet.activation == "message_only",
                    command.authority_id, command.authority_incarnation))
    if cursor.fetchone() is None:
        raise DeliveryRejected("target_slot_unavailable")
    cursor.execute("SELECT policy FROM scopes WHERE tenant_id=%s AND scope_id=%s AND status='active'",
                   (command.tenant_id, packet.target_scope_id))
    scope_policy = cursor.fetchone()
    if scope_policy is None:
        raise DeliveryRejected("scope_unavailable")
    if authority.access_mode != "owner":
        for policy in scope_policy[0].get("collaboration_team", {}).get("policies", []):
            rules = policy.get("rules", {})
            if (packet.activation not in rules.get("allowed_activations", ["invoke", "message_only"])
                    or packet.delivery_policy not in rules.get("allowed_delivery_policies", ["queue_until_idle"])):
                raise AuthorizationDenied(command.principal_ref, command.grant_ref)
    if packet.activation == "message_only" and endpoint_id is None:
        cursor.execute("SELECT policy FROM scopes WHERE tenant_id=%s AND scope_id=%s AND status='active'",
                       (command.tenant_id, packet.target_scope_id))
        policy = cursor.fetchone()
        if policy is None:
            raise DeliveryRejected("scope_unavailable")
        return {"machine_id": None, "node_id": None, "boot_incarnation": None}, digest(policy[0]), digest({
            "project_id": packet.project_id, "sender": packet.sender, "recipient": packet.recipient})
    cursor.execute("SELECT to_jsonb(e) FROM delivery_endpoints e WHERE tenant_id=%s AND endpoint_id=%s FOR UPDATE",
                   (command.tenant_id, endpoint_id))
    row = cursor.fetchone()
    if row is None:
        raise DeliveryRejected("endpoint_binding_missing")
    binding = row[0]
    if (binding["status"] != "active" or binding["scope_id"] != packet.target_scope_id
            or binding["agent_slot_id"] != target
            or (binding["revision"] < revision if recovery else binding["revision"] != revision)):
        raise DeliveryRejected("endpoint_binding_changed")
    if (authority.access_mode != "owner" and binding["expires_at"] is not None
            and datetime.fromisoformat(binding["expires_at"]) <= authority.canonical_now(cursor)):
        raise DeliveryRejected("endpoint_binding_expired")
    if packet.activation == "invoke" and not binding["supports_invoke"]:
        raise DeliveryRejected("invoke_endpoint_unavailable")
    cursor.execute("SELECT policy FROM scopes WHERE tenant_id=%s AND scope_id=%s AND status='active'",
                   (command.tenant_id, packet.target_scope_id))
    policy = cursor.fetchone()
    if policy is None:
        raise DeliveryRejected("scope_unavailable")
    return binding, digest(policy[0]), digest({"project_id": packet.project_id, "sender": packet.sender,
                                              "recipient": packet.recipient})


def _page_message_content(data, maximum, offset=0, *, reference=False):
    raw = data["content"].encode()
    if offset > len(raw):
        raise ValueError("content offset exceeds message")
    try:
        raw[:offset].decode()
    except UnicodeDecodeError as error:
        raise ValueError("content offset is not a UTF-8 boundary") from error
    part = raw[offset:offset + maximum].decode(errors="ignore")
    if not part and offset < len(raw) and not reference:
        raise ValueError("content byte budget cannot fit the next UTF-8 character")
    end = offset + len(part.encode())
    data["content"] = part
    data["next_offset"] = end if end < len(raw) else None
    if data["next_offset"] is None:
        return []
    # A reference can remain readable even when this response's budget cannot
    # fit its first code point. The next explicit read advertises enough space.
    next_maximum = max(maximum, len(raw[end:].decode()[0].encode()))
    return [{"rel": "next", "tool": "read_message", "arguments": {
        "project_id": data["project_id"], "handle": data["message_handle"],
        "max_inline_bytes": next_maximum, "offset": end}}]


class CommunicationActions:
    def bind_notification_session(self, project_id, session_ref, connection_ref, credential):
        """Bind an explicitly subscribed transport to its authenticated owner."""
        self.service.authenticate(credential)
        with (self.service.authority.transaction() as (authority, connection), connection.cursor() as cursor):
            self._authorize(authority, cursor, project_id, "check_inbox", {"project_id": project_id})
            cursor.execute("SELECT state,revision,connection_ref FROM collaboration_notification_sessions WHERE tenant_id=%s "
                           "AND project_id=%s AND owner_ref=%s AND session_ref=%s FOR UPDATE",
                           (self.context.tenant_id, project_id, self.context.principal_ref, session_ref))
            prior = cursor.fetchone()
            if prior and prior[0] == "retired":
                raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
            if prior and prior[2] == connection_ref:
                cursor.execute("UPDATE collaboration_notification_sessions SET expires_at="
                               "CASE WHEN %s THEN NULL ELSE clock_timestamp()+interval '300 seconds' END WHERE tenant_id=%s "
                               "AND project_id=%s AND owner_ref=%s AND session_ref=%s",
                               (authority.access_mode == "owner", self.context.tenant_id, project_id, self.context.principal_ref, session_ref))
                return prior[1]
            cursor.execute("SELECT COALESCE(MAX(revision),0) FROM collaboration_notification_sessions "
                           "WHERE tenant_id=%s AND project_id=%s AND owner_ref=%s",
                           (self.context.tenant_id, project_id, self.context.principal_ref))
            revision = cursor.fetchone()[0] + 1
            cursor.execute("UPDATE collaboration_notification_sessions SET state='retired' WHERE tenant_id=%s "
                           "AND project_id=%s AND owner_ref=%s AND session_ref<>%s AND state='active'",
                           (self.context.tenant_id, project_id, self.context.principal_ref, session_ref))
            cursor.execute("INSERT INTO collaboration_notification_sessions(tenant_id,project_id,owner_ref,"
                           "session_ref,connection_ref,revision,state,expires_at) "
                           "VALUES (%s,%s,%s,%s,%s,%s,'active',CASE WHEN %s THEN NULL ELSE clock_timestamp()+interval '300 seconds' END) "
                           "ON CONFLICT(tenant_id,project_id,owner_ref,session_ref) DO UPDATE "
                           "SET connection_ref=EXCLUDED.connection_ref,revision=EXCLUDED.revision,"
                           "expires_at=EXCLUDED.expires_at",
                           (self.context.tenant_id, project_id, self.context.principal_ref,
                            session_ref, connection_ref, revision, authority.access_mode == "owner"))
        return revision

    @staticmethod
    def _validate_send_observation(args):
        timeout = args.get("wait_timeout_seconds")
        if ((timeout is not None and (type(timeout) is not int or not 0 <= timeout <= 2**53-1))
                or args.get("response_mode", "async") not in {"async", "sync"}):
            raise InvalidToolArgument("wait_timeout_seconds", "Choose an optional nonnegative observation timeout and async or sync response_mode.")

    def _list_harnesses(self, authority, cursor, project, command, args, _credential):
        from runtime.codex_driver import AuthorizedOperation
        from runtime.native_delivery import NativeDeliveryAdapter
        scopes = self._visible_scopes(authority, cursor, project)
        scope = self._scope(cursor, self.context.tenant_id, args["project_id"], args["scope_handle"]) if args.get("scope_handle") else None
        cursor.execute("SELECT e.endpoint_id,e.agent_slot_id,e.scope_id,e.machine_id,e.node_id,e.revision,e.supports_invoke "
                       "FROM delivery_endpoints e WHERE e.tenant_id=%s AND e.status='active' "
                       "AND (%s OR e.expires_at>clock_timestamp()) AND (%s::text IS NULL OR e.scope_id=%s) "
                       "AND (%s::text[] IS NULL OR e.scope_id=ANY(%s)) AND (e.scope_id=%s OR EXISTS "
                       "(SELECT 1 FROM collaboration_routes r WHERE r.tenant_id=e.tenant_id AND r.project_id=%s AND r.scope_id=e.scope_id)) "
                       "ORDER BY e.endpoint_id", (self.context.tenant_id, authority.access_mode == "owner", scope, scope,
                            scopes, scopes, project[0], args["project_id"]))
        items = []
        for endpoint_id, slot, scope_id, machine, node, revision, invoke in cursor.fetchall():
            capabilities = ["message", "invoke"] if invoke else ["message"]
            if not set(args.get("required_capabilities", [])) <= set(capabilities):
                continue
            provider = authority._delivery_endpoints.get(endpoint_id)
            observed = {"state": "unknown", "harness": "unknown", "session_ref": None}
            try:
                if callable(getattr(provider, "inspect_runtime", None)):
                    observed.update(provider.inspect_runtime())
                elif isinstance(getattr(provider, "driver", None), NativeDeliveryAdapter):
                    adapter = provider.driver
                    adapter._check_binding()
                    driver = adapter.driver
                    operation = AuthorizedOperation(command.command_id, command.command_id, command.command_id,
                                                     authority.context.grant_ref, command.deadline)
                    view = driver.inspect(operation)
                    observed.update(state=view.get("thread", {}).get("status", view.get("status", {})).get("type", "unknown"),
                        harness="codex" if getattr(driver, "thread_id", None) else "opencode",
                        session_ref=getattr(driver, "thread_id", None) or getattr(driver, "session_id", None))
            except Exception:  # noqa: BLE001 - a failed observation never triggers preparation.
                observed.update(state="unknown", session_ref=None)
            if args.get("harness_kinds") and observed["harness"] not in args["harness_kinds"]:
                continue
            items.append({"endpoint_id": endpoint_id, "collaborator_handle": handle("collaborator", args["project_id"], slot),
                "agent_slot_id": slot, "scope_handle": handle("scope", args["project_id"], scope_id), "machine_id": machine,
                "node_id": node, "binding_revision": revision, "capabilities": capabilities, "runtime_state": observed["state"],
                "harness": observed["harness"], "session_ref": observed.get("session_ref"), "observation": "read_only_snapshot"})
        limit = args.get("limit", 20)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid Harness page size")
        items = [item for item in items if not args.get("cursor") or item["endpoint_id"] > args["cursor"]]
        return "observed", {"project_id": args["project_id"], "items": items[:limit],
                            "next_cursor": items[limit-1]["endpoint_id"] if len(items) > limit else None}, []

    def pending_wake_keys(self, project_id, session_ref, connection_ref, credential):
        self.service.authenticate(credential)
        with self.service.authority.transaction() as (authority, connection), connection.cursor() as cursor:
            self._authorize(authority, cursor, project_id, "check_inbox", {"project_id": project_id})
            address = self._communication_address(cursor, project_id)
            cursor.execute("SELECT 1 FROM collaboration_notification_sessions WHERE tenant_id=%s AND project_id=%s "
                           "AND owner_ref=%s AND session_ref=%s AND connection_ref=%s AND state='active' "
                           "AND (expires_at IS NULL OR expires_at>clock_timestamp())",
                           (self.context.tenant_id, project_id, self.context.principal_ref, session_ref, connection_ref))
            if cursor.fetchone() is None:
                return []
            cursor.execute("SELECT sequence FROM communication_messages WHERE tenant_id=%s AND project_id=%s "
                           "AND recipient=%s ORDER BY sequence DESC LIMIT 1", (self.context.tenant_id, project_id, address))
            latest = cursor.fetchone()
            keys = ["message:" + str(latest[0])] if latest else []
            cursor.execute("SELECT sequence FROM communication_notices WHERE tenant_id=%s AND project_id=%s "
                           "AND recipient=%s ORDER BY sequence DESC LIMIT 1", (self.context.tenant_id, project_id, address))
            notice = cursor.fetchone()
            return keys + (["notice:" + str(notice[0])] if notice else [])

    def _list_collaborators(self, authority, cursor, project, _command, args, _credential):
        scopes = self._visible_scopes(authority, cursor, project)
        if scopes is not None:
            scopes=list(dict.fromkeys([*scopes,project[0]]))
        scope = (self._scope(cursor, self.context.tenant_id, args["project_id"], args["scope_handle"])
                 if args.get("scope_handle") else None)
        cursor.execute("SELECT DISTINCT s.agent_slot_id,m.principal_ref,m.profile,s.scope_id,s.status,"
                       "g.revoked_at,g.expires_at,tm.role,t.definition,cs.manager_address,g.authority_id,g.authority_incarnation FROM " + CONTACTS + " m "
                       "JOIN agent_slots s USING(agent_slot_id) JOIN grants g ON g.grant_ref=m.grant_ref "
                       "LEFT JOIN collaboration_team_members tm ON tm.tenant_id=m.tenant_id AND tm.project_id=m.project_id "
                       "AND tm.agent_slot_id=m.agent_slot_id LEFT JOIN collaboration_teams t "
                       "ON t.tenant_id=tm.tenant_id AND t.project_id=tm.project_id AND t.scope_id=tm.scope_id "
                       "LEFT JOIN communication_supervisors cs ON cs.tenant_id=m.tenant_id AND cs.project_id=m.project_id "
                       "AND cs.agent_slot_id=m.agent_slot_id "
                       "WHERE m.tenant_id=%s AND s.tenant_id=m.tenant_id AND m.project_id=%s "
                       "AND (%s::text[] IS NULL OR s.scope_id=ANY(%s)) AND (%s::text IS NULL OR s.scope_id=%s) "
                       "ORDER BY s.agent_slot_id", (self.context.tenant_id, args["project_id"], scopes, scopes, scope, scope))
        items = []
        for slot, principal, profile, scope_id, state, revoked, expiry, role, definition, manager, issuer, incarnation in cursor.fetchall():
            declared = next((entry for entry in (definition or {}).get("members", []) if entry["agent_slot_id"] == slot), {})
            state = "active" if state == "active" and revoked is None and (issuer, incarnation) == (
                self.context.authority_id, self.context.authority_incarnation) and (authority.access_mode == "owner" or
                expiry is not None and expiry > authority.canonical_now(cursor)) else "inactive"
            name = declared.get("display_name") or slot
            if (args.get("roles") and role not in args["roles"] or args.get("states") and state not in args["states"]
                    or args.get("name") and args["name"].casefold() not in name.casefold()):
                continue
            items.append({"collaborator_handle": handle("collaborator", args["project_id"], slot),
                "display_name": name, "agent_slot_id": slot, "principal_ref": principal, "role": role,
                "profile": profile, "scope_handle": handle("scope", args["project_id"], scope_id), "state": state,
                "manager_handle": manager,
                "receiver": {"endpoint_id": declared.get("endpoint_id"), "selection": "configured" if declared.get("endpoint_id") else "automatic"},
                "is_self": principal == self.context.principal_ref and profile == self.profile})
        limit = args.get("limit", 50)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid contact page size")
        items = [item for item in items if not args.get("cursor") or item["agent_slot_id"] > args["cursor"]]
        return "observed", {"project_id": args["project_id"], "self": self._communication_address(cursor, args["project_id"]),
            "items": items[:limit], "next_cursor": items[limit-1]["agent_slot_id"] if len(items) > limit else None}, []

    def _communication_address(self, cursor, project_id):
        if self.context.trusted_client:
            if self.context.agent_slot_id is not None:
                raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
            return handle("client", project_id, digest([self.context.authority_id, self.context.principal_ref]))
        if self.context.agent_slot_id is not None:
            cursor.execute("SELECT 1 FROM collaboration_team_members m JOIN agent_slots s USING(agent_slot_id) "
                           "WHERE m.tenant_id=%s AND m.project_id=%s AND m.agent_slot_id=%s AND m.principal_ref=%s "
                           "AND m.grant_ref=%s AND m.profile=%s AND m.status='active' AND s.status='active' "
                           "UNION ALL SELECT 1 FROM collaboration_memberships m JOIN agent_slots s USING(agent_slot_id) "
                           "WHERE m.tenant_id=%s AND m.project_id=%s AND m.agent_slot_id=%s AND m.principal_ref=%s "
                           "AND m.grant_ref=%s AND m.profile=%s AND s.status='active'",
                           (self.context.tenant_id, project_id, self.context.agent_slot_id, self.context.principal_ref,
                            self.context.grant_ref, self.profile, self.context.tenant_id, project_id, self.context.agent_slot_id,
                            self.context.principal_ref, self.context.grant_ref, self.profile))
            if cursor.fetchone() is None:
                raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
            return handle("collaborator", project_id, self.context.agent_slot_id)
        cursor.execute("SELECT DISTINCT m.agent_slot_id FROM " + CONTACTS + " m "
                       "JOIN agent_slots s USING(agent_slot_id) WHERE m.tenant_id=%s AND m.project_id=%s "
                       "AND m.principal_ref=%s AND m.profile=%s AND m.grant_ref=%s AND s.tenant_id=m.tenant_id AND s.status='active'",
                       (self.context.tenant_id, project_id, self.context.principal_ref, self.profile, self.context.grant_ref))
        slots = cursor.fetchall()
        if len(slots) != 1:
            raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
        return handle("collaborator", project_id, slots[0][0])

    @staticmethod
    def _communication_lock(cursor, tenant_id, project_id):
        # Serialize allocation through commit. A lower sequence can never become
        # visible after a higher sequence from this project was paged past.
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                       ("communication-order:" + tenant_id + ":" + project_id,))

    def _communication_row(self, authority, cursor, args, message_id):
        cursor.execute("SELECT c.sender,c.recipient,c.sequence,m.packet_json,m.state,m.receipt_high_water,m.operation_id,m.last_error,m.attempts "
                       "FROM communication_messages c JOIN delivery_messages m USING(tenant_id,message_id) "
                       "WHERE c.tenant_id=%s AND c.project_id=%s AND c.message_id=%s",
                       (self.context.tenant_id, args["project_id"], message_id))
        row = cursor.fetchone()
        if row is None:
            raise NotFound("message", message_id)
        address = self._communication_address(cursor, args["project_id"])
        if address not in row[:2]:
            raise AuthorizationDenied(self.context.principal_ref, authority.context.grant_ref)
        return row

    @staticmethod
    def _communication_view(project_id, message_id, row):
        packet = row[3]
        return {"project_id": project_id, "message_id": message_id,
                "message_handle": handle("message", project_id, message_id),
                "response_handle": handle("response", project_id, message_id),
                "from": row[0], "to": row[1], "sequence": row[2], "content": packet["content"],
                "reply_to": packet["reply_to"], "response_mode_at_send": packet["response_mode"],
                "activation": packet["activation"], "state": row[4], "receipt_high_water": row[5],
                "operation_id": row[6], "consumed": False, "model_consumption": "unconfirmed",
                "delivery": {"state": row[4], "error_code": row[7], "attempts": row[8]}}

    def _send_message(self, authority, cursor, project, command, args, _credential):
        project_id = args["project_id"]
        sender = self._communication_address(cursor, project_id)
        client_target = args["to"].startswith("client:")
        target = None if client_target else parse_handle(args["to"], "collaborator", project_id)
        if client_target:
            parse_handle(args["to"], "client", project_id)
        content = args["content"]
        if not isinstance(content, str) or not content.strip() or len(content.encode()) > 32768:
            raise InvalidToolArgument("content", "Provide nonempty message text within the 32768-byte UTF-8 limit.")
        relations = args.get("reply_to", [])
        if (not isinstance(relations, list) or len(relations) > 32
                or len(set(relations)) != len(relations)):
            raise ValueError("invalid reply references")
        self._communication_lock(cursor, self.context.tenant_id, project_id)
        if self.context.trusted_client:
            cursor.execute("INSERT INTO communication_clients VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                           (self.context.tenant_id, project_id, sender, self.context.principal_ref))
        request_ids = []
        for reference in relations:
            request_id = parse_handle(reference, "message", project_id)
            original = self._communication_row(authority, cursor, args, request_id)
            if (original[1], original[0]) != (sender, args["to"]):
                raise AuthorizationDenied(self.context.principal_ref, authority.context.grant_ref, field="reply_to",
                    guidance="reply_to can only answer messages from this recipient addressed to your identity. "
                    "When delegating to a different collaborator, send a new message without reply_to; "
                    "describe relevant context in content instead.")
            request_ids.append(request_id)
        cursor.execute("SELECT s.scope_id FROM agent_slots s WHERE s.tenant_id=%s AND s.agent_slot_id=%s "
                       "AND s.status='active' AND EXISTS(SELECT 1 FROM " + CONTACTS + " m "
                       "WHERE m.tenant_id=s.tenant_id AND m.project_id=%s AND m.agent_slot_id=s.agent_slot_id)",
                       (self.context.tenant_id, target, project_id))
        selected = cursor.fetchone()
        if selected is None and not client_target:
            raise NotFound("collaborator", target)
        scope = selected[0] if selected else project[0]
        cursor.execute("SELECT endpoint_id,revision FROM delivery_endpoints WHERE tenant_id=%s "
                       "AND scope_id=%s AND agent_slot_id=%s AND status='active' "
                       "AND (%s OR expires_at>clock_timestamp()) ORDER BY endpoint_id",
                       (self.context.tenant_id, scope, target, authority.access_mode == "owner"))
        endpoints = cursor.fetchall()
        cursor.execute("SELECT t.definition FROM collaboration_teams t JOIN collaboration_team_members m "
                       "USING(tenant_id,project_id,scope_id) WHERE t.tenant_id=%s AND t.project_id=%s AND m.agent_slot_id=%s",
                       (self.context.tenant_id, project_id, target))
        configured = cursor.fetchone()
        declared = next((member for member in configured[0]["members"] if member["agent_slot_id"] == target), {}) if configured else {}
        if declared.get("endpoint_id"):
            endpoints = [item for item in endpoints if item[0] == declared["endpoint_id"]]
        direct_inbox = client_target or args.get("activation", "invoke") == "message_only"
        if len(endpoints) != 1 and not direct_inbox:
            raise DeliveryRejected("endpoint_binding_missing" if not endpoints else "endpoint_binding_ambiguous")
        if direct_inbox:
            endpoints = [(None, None)]
        packet = MessagePacket(project_id=project_id, sender=sender, recipient=args["to"], content=content,
            reply_to=tuple(relations), response_mode=args.get("response_mode", "async"),
            target_scope_id=scope, target_agent_slot_id=target, activation=args.get("activation", "invoke"),
            deadline=datetime.fromisoformat(args["deadline"]) if args.get("deadline") else None)
        message_id = "message-" + uuid.uuid4().hex
        send_command = command.model_copy(update={"command_type": "message.send", "target_kind": "message",
                                                  "target_id": message_id, "deadline": packet.deadline,
                                                  "payload": {"schema_version": "acs-message/1", "communication_project_id": project_id}})
        result = authority.send_message(send_command, packet, endpoint_id=endpoints[0][0], binding_revision=endpoints[0][1])
        cursor.execute("INSERT INTO communication_messages(tenant_id,project_id,message_id,sender,recipient) "
                       "VALUES (%s,%s,%s,%s,%s) RETURNING sequence",
                       (self.context.tenant_id, project_id, message_id, sender, args["to"]))
        sequence = cursor.fetchone()[0]
        for request_id in request_ids:
            cursor.execute("INSERT INTO communication_replies VALUES (%s,%s,%s,%s)",
                           (self.context.tenant_id, project_id, request_id, message_id))
        cursor.execute("SELECT 1 FROM communication_waits w WHERE w.tenant_id=%s AND w.project_id=%s "
                       "AND w.address=%s AND w.request_id=ANY(%s) AND w.expires_at>clock_timestamp() "
                       "AND NOT EXISTS(SELECT 1 FROM communication_replies r WHERE r.tenant_id=w.tenant_id "
                       "AND r.project_id=w.project_id AND r.request_id=w.request_id AND r.reply_id<>%s) LIMIT 1",
                       (self.context.tenant_id, project_id, args["to"], request_ids, message_id))
        through_wait = cursor.fetchone() is not None
        if through_wait and not direct_inbox:
            cursor.execute("UPDATE delivery_messages SET state='delivered',receipt_high_water='target_inbox_committed' "
                           "WHERE tenant_id=%s AND message_id=%s", (self.context.tenant_id, message_id))
            cursor.execute("INSERT INTO delivery_receipts(tenant_id,message_id,receipt_id,layer,evidence_json) "
                           "VALUES (%s,%s,%s,'target_inbox_committed',%s)",
                           (self.context.tenant_id, message_id, f"delivery:{message_id}:target_inbox_committed",
                            __import__('json').dumps({"source": "authority_inbox", "ingress": "active_wait",
                                "model_consumption": "unconfirmed"})))
        # Inbox is a view of the authoritative, committed message. Native
        # delivery to a remote node remains an independently recorded fact.
        message_handle = handle("message", project_id, message_id)
        response_handle = handle("response", project_id, message_id)
        cursor.execute("SELECT pg_notify('acs_domain_change',%s)", (project_id,))
        data = {**result.model_dump(mode="json"), "project_id": project_id, "message_id": message_id,
                "message_handle": message_handle, "response_handle": response_handle, "sequence": sequence,
                "from": sender, "to": args["to"], "activation": packet.activation,
                "native_status": "client_inbox" if client_target else "not_requested" if packet.activation == "message_only"
                    else "active_wait_ingress" if through_wait else "pending",
                "client_request_id": args.get("client_request_id"),
                "delivery_recovery": "active" if getattr(self.service.authority, "_communication_maintenance_running", False)
                    else "external_dispatcher_configured" if getattr(self.service.authority, "_communication_maintenance_mode", "auto") == "external"
                    else "pending_dispatcher"}
        return "accepted", data, [{"rel": "wait", "tool": "wait_for_response", "arguments": {
            "project_id": project_id, "handles": [message_handle]}}, {"rel": "read", "tool": "read_message",
            "arguments": {"project_id": project_id, "handle": message_handle}}]

    def _read_message(self, authority, cursor, project, command, args, credential):
        kind = args["handle"].split(":", 1)[0]
        if kind == "notification":
            notice_id = parse_handle(args["handle"], kind, args["project_id"])
            if notice_id.startswith("communication-"):
                address = self._communication_address(cursor, args["project_id"])
                cursor.execute("SELECT n.message_id,n.state,n.code,m.state,m.receipt_high_water,r.native_requested,COALESCE(r.last_error,m.last_error) "
                               "FROM communication_notices n LEFT JOIN communication_notice_routes r "
                               "USING(tenant_id,project_id,message_id,recipient) LEFT JOIN delivery_messages m "
                               "ON m.tenant_id=r.tenant_id AND m.message_id=r.delivery_message_id WHERE n.tenant_id=%s "
                               "AND n.project_id=%s AND n.sequence=%s AND n.recipient=%s", (self.context.tenant_id,
                                args["project_id"], int(notice_id.removeprefix("communication-")), address))
                notice = cursor.fetchone()
                if notice is None:
                    raise NotFound("notification", notice_id)
                return "observed", {"source": "acs", "message_handle": handle("message", args["project_id"], notice[0]),
                    "state": notice[1], "code": notice[2], "native_delivery": {
                        "state": notice[3] or ("pending_dispatcher" if notice[5] else "retained_in_inbox"),
                        "receipt_high_water": notice[4], "error_code": notice[6], "model_consumption": "unconfirmed"},
                    "meaning": "Communication obstacle; no Agent reply or work outcome inferred."}, []
        if kind not in {"message", "response"}:
            raise InvalidToolArgument("handle", "Use a message, response or current ACS communication notification handle.")
        message_id = parse_handle(args["handle"], kind, args["project_id"])
        cursor.execute("SELECT 1 FROM communication_messages WHERE tenant_id=%s AND project_id=%s AND message_id=%s",
                       (self.context.tenant_id, args["project_id"], message_id))
        if cursor.fetchone() is None:
            cursor.execute("SELECT packet_json->>'schema_version',packet_json->>'project_id' FROM delivery_messages "
                           "WHERE tenant_id=%s AND message_id=%s", (self.context.tenant_id, message_id))
            packet = cursor.fetchone()
            if packet is None or packet[0] == "acs-notice/1" or (packet[1] is not None and packet[1] != args["project_id"]):
                raise NotFound("message", message_id)
            if packet[0] != "acs-delivery/1":
                raise DeliveryRejected("message_history_unavailable")
            from runtime.project_archive import read_archived_message
            archived = read_archived_message(self, authority, cursor, project, command, args, credential)
            return archived[0], {**archived[1], "historical": True, "content_format": "legacy_delivery_packet",
                "reply_semantics": "native_output_is_not_an_explicit_reply"}, archived[2]
        row = self._communication_row(authority, cursor, args, message_id)
        data = self._communication_view(args["project_id"], message_id, row)
        cursor.execute("SELECT r.reply_id FROM communication_replies r JOIN communication_messages c "
                       "ON c.tenant_id=r.tenant_id AND c.project_id=r.project_id AND c.message_id=r.reply_id "
                       "WHERE r.tenant_id=%s AND r.project_id=%s AND r.request_id=%s ORDER BY c.sequence LIMIT 1",
                       (self.context.tenant_id, args["project_id"], message_id))
        reply = cursor.fetchone()
        data["reply"] = (self._communication_view(args["project_id"], reply[0],
                         self._communication_row(authority, cursor, args, reply[0])) if reply else None)
        maximum = args.get("max_inline_bytes", 16384)
        offset = args.get("offset", 0)
        if type(maximum) is not int or not 1 <= maximum <= 65536 or type(offset) is not int or offset < 0:
            raise ValueError("invalid message content bounds")
        actions = _page_message_content(data, maximum, offset)
        if data["reply"] is not None:
            actions.extend(_page_message_content(data["reply"], maximum, reference=True))
        return "observed", data, actions

    def _list_messages(self, authority, cursor, _project, _command, args, _credential):
        address = self._communication_address(cursor, args["project_id"])
        limit = args.get("limit", 50)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid message page size")
        cursor_value = args.get("cursor")
        direction = args.get("direction", "both")
        if direction not in {"both", "incoming", "outgoing"}:
            raise ValueError("invalid message direction")
        # Optional filters are often emitted as empty strings by Harness tool
        # adapters. Keep their meaning and cursor identity equal to omission.
        peer = args.get("with") or None
        if peer:
            try:
                parse_handle(peer, "client" if peer.startswith("client:") else "collaborator", args["project_id"])
            except ValueError:
                raise InvalidToolArgument("with", "with filters a collaborator_handle or Client address in this project. "
                    "Read a notification_handle with read_message(handle=notification_handle).") from None
        query = digest([self.context.tenant_id, args["project_id"], address, direction, peer])
        after, reset = 0, False
        if cursor_value:
            try:
                if not isinstance(cursor_value, str) or len(cursor_value) > 1024:
                    raise ValueError("invalid cursor")
                saved = json.loads(base64.urlsafe_b64decode(cursor_value + "=" * (-len(cursor_value) % 4)))
                if set(saved) != {"after", "query"} or type(saved["after"]) is not int or saved["after"] < 0:
                    raise ValueError("invalid cursor")
                after = saved["after"] if saved["query"] == query else 0
                reset = saved["query"] != query
            except (ValueError, TypeError, KeyError, UnicodeError) as error:
                raise ValueError("invalid message cursor") from error
        def continuation(sequence):
            return base64.urlsafe_b64encode(json.dumps({"after": sequence, "query": query}).encode()).decode().rstrip("=")
        cursor.execute("SELECT c.message_id,c.sender,c.recipient,c.sequence,m.packet_json,m.state,m.receipt_high_water "
                       "FROM communication_messages c JOIN delivery_messages m USING(tenant_id,message_id) "
                       "WHERE c.tenant_id=%s AND c.project_id=%s AND c.sequence>%s "
                       "AND ((%s IN ('both','outgoing') AND c.sender=%s) OR (%s IN ('both','incoming') AND c.recipient=%s)) "
                       "AND (%s::text IS NULL OR c.sender=%s OR c.recipient=%s) ORDER BY c.sequence LIMIT %s",
                       (self.context.tenant_id, args["project_id"], after, direction, address, direction, address,
                        peer, peer, peer, limit + 1))
        rows = cursor.fetchall()
        items = [{"kind": "message", "handle": handle("message", args["project_id"], row[0]),
                  "message_handle": handle("message", args["project_id"], row[0]), "from": row[1], "to": row[2],
                  "sequence": row[3], "reply_to": row[4]["reply_to"], "preview": row[4]["content"][:256],
                  "state": row[5], "receipt_high_water": row[6]} for row in rows[:limit]]
        return "observed", {"project_id": args["project_id"], "items": items,
                            "next_cursor": continuation(rows[limit-1][3]) if len(rows) > limit else None,
                            "resume_cursor": continuation(rows[min(limit, len(rows))-1][3]) if rows else continuation(after),
                            "cursor_reset": reset}, []

    def _check_inbox(self, authority, cursor, project, command, args, credential):
        result = self._list_messages(authority, cursor, project, command, dict(args, direction="incoming"), credential)
        address = self._communication_address(cursor, args["project_id"])
        notice_cursor = args.get("notification_cursor", "0") or "0"
        if not isinstance(notice_cursor, str) or not notice_cursor.isdecimal():
            raise ValueError("invalid notification cursor")
        cursor.execute("SELECT sequence,message_id,state,code FROM communication_notices WHERE tenant_id=%s "
                       "AND project_id=%s AND recipient=%s AND sequence>%s ORDER BY sequence LIMIT 101",
                       (self.context.tenant_id, args["project_id"], address, int(notice_cursor)))
        rows = cursor.fetchall()
        notices = [{"source": "acs", "notification_handle": handle("notification", args["project_id"], "communication-" + str(row[0])),
                    "message_handle": handle("message", args["project_id"], row[1]), "state": row[2], "code": row[3]} for row in rows[:100]]
        return result[0], {**result[1], "notifications": notices,
                          "next_notification_cursor": str(rows[99][0]) if len(rows) > 100 else None}, result[2]

    def _wait(self, args, credential):
        references = args["handles"]
        mode, until = args.get("mode", "all"), args.get("until", "response_received")
        timeout = args.get("timeout_seconds")
        if (mode not in {"any", "all"} or until not in {"response_received", "accepted_by_authority",
                "target_inbox_committed", "runtime_dispatched", "runtime_acknowledged"}
                or not 1 <= len(references) <= 32 or len(set(references)) != len(references)
                or (timeout is not None and (type(timeout) is not int or not 0 <= timeout <= 2**53-1))):
            raise ValueError("invalid wait options")
        end = None if timeout is None else time.monotonic() + timeout
        waiter_id = uuid.uuid4().hex
        try:
            return self._observe_messages(args, credential, references, mode, until, end, waiter_id)
        finally:
            with self.service.authority._connect() as connection:
                connection.execute("DELETE FROM communication_waits WHERE tenant_id=%s AND project_id=%s AND waiter_id=%s",
                                   (self.context.tenant_id, args["project_id"], waiter_id))

    def _observe_messages(self, args, credential, references, mode, until, end, waiter_id):
        while True:
            try:
                anyio.from_thread.check_cancelled()
            except RuntimeError:
                pass
            address = self._wait_address(args, credential)
            # Register before reading. The send transaction and this registration
            # share the project lock, closing the commit/subscribe race.
            with self.service.authority.transaction() as (authority, connection), connection.cursor() as cursor:
                bound, _project, command = self._authorize(authority, cursor, args["project_id"], "wait_for_response", args)
                self._communication_lock(cursor, self.context.tenant_id, args["project_id"])
                for reference in references:
                    kind = reference.split(":", 1)[0]
                    if kind not in {"message", "response"}:
                        raise ValueError("wait requires message or response references")
                    identifier = parse_handle(reference, kind, args["project_id"])
                    try:
                        original = self._communication_row(authority, cursor, args, identifier)
                    except NotFound:
                        cursor.execute("SELECT m.packet_json->>'target_scope_id' FROM communication_archives a "
                            "JOIN delivery_messages m USING(tenant_id,message_id) WHERE a.tenant_id=%s "
                            "AND a.project_id=%s AND a.message_id=%s AND a.source_hash=m.canonical_hash",
                            (self.context.tenant_id, args["project_id"], identifier))
                        archived = cursor.fetchone()
                        if archived is None:
                            raise
                        bound._authorize(command.model_copy(update={"command_type": "message.read", "target_kind": "message", "target_id": identifier}),
                                         cursor, "message.read", archived[0])
                        raise InvalidToolArgument("handles", "Historical packets and Native results are read-only records. Use read_message; reply waiting applies to current natural messages.") from None
                    if original[0] != address:
                        raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
                    if until == "response_received":
                        cursor.execute("INSERT INTO communication_waits VALUES (%s,%s,%s,%s,%s,clock_timestamp()+interval '5 seconds') "
                                       "ON CONFLICT(tenant_id,project_id,waiter_id,request_id) DO UPDATE SET expires_at=EXCLUDED.expires_at",
                                       (self.context.tenant_id, args["project_id"], waiter_id, address, identifier))
            pages = [self.execute("read_message", {"project_id": args["project_id"],
                     "handle": reference}, credential) for reference in references]
            observations = [page[1] for page in pages]
            satisfied = []
            for reference, item in zip(references, observations, strict=True):
                if item.get("historical"):
                    raise InvalidToolArgument("handles", "Historical packets and Native results are read-only records. Use read_message; reply waiting applies to current natural messages.")
                if item["from"] != address:
                    raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
                reached = item["reply"] is not None if until == "response_received" else self._has_receipt(item, until)
                if reached:
                    satisfied.append(reference)
            pending = [item for item in references if item not in satisfied]
            ready = not pending if mode == "all" else bool(satisfied)
            if ready or (end is not None and time.monotonic() >= end):
                if until == "response_received":
                    self._retain_wait_ingress(args, credential, observations)
                continuations = {digest(action["arguments"]): action for page in pages for action in page[2]}
                return "satisfied" if ready else "timeout", {"project_id": args["project_id"],
                    "satisfied": satisfied, "pending": pending, "observations": observations}, list(continuations.values())
            time.sleep(0.1 if end is None else min(0.1, max(0, end-time.monotonic())))

    def _retain_wait_ingress(self, args, credential, observations):
        """Keep a reply selected for this Tool Result from later starting Native.

        This closes the lease-expiry/read race. It records a chosen ingress,
        never a claim that a disconnected Host or model consumed the result.
        """
        with self.service.authority.transaction() as (authority, connection), connection.cursor() as cursor:
            self._authorize(authority, cursor, args["project_id"], "wait_for_response", args)
            self.service.authenticate(credential)
            for observation in observations:
                reply = observation.get("reply")
                if reply is None:
                    continue
                cursor.execute("SELECT state FROM delivery_messages WHERE tenant_id=%s AND message_id=%s FOR UPDATE",
                               (self.context.tenant_id, reply["message_id"]))
                cursor.fetchone()
                cursor.execute("SELECT 1 FROM delivery_receipts WHERE tenant_id=%s AND message_id=%s AND layer='runtime_dispatched'",
                               (self.context.tenant_id, reply["message_id"]))
                if cursor.fetchone():
                    continue  # Preserve an already possible Native effect and its evidence.
                cursor.execute("UPDATE delivery_messages SET state='delivered',receipt_high_water='target_inbox_committed' "
                               "WHERE tenant_id=%s AND message_id=%s", (self.context.tenant_id, reply["message_id"]))
                cursor.execute("INSERT INTO delivery_receipts(tenant_id,message_id,receipt_id,layer,evidence_json) "
                    "VALUES (%s,%s,%s,'target_inbox_committed',%s) ON CONFLICT DO NOTHING", (self.context.tenant_id,
                        reply["message_id"], f"delivery:{reply['message_id']}:target_inbox_committed",
                        json.dumps({"source": "authority_inbox", "ingress": "active_wait", "model_consumption": "unconfirmed"})))

    def _wait_address(self, args, credential):
        self.service.authenticate(credential)
        with self.service.authority.transaction() as (_authority, connection), connection.cursor() as cursor:
            return self._communication_address(cursor, args["project_id"])

    @staticmethod
    def _has_receipt(item, until):
        order = ("accepted_by_authority", "target_inbox_committed", "runtime_dispatched", "runtime_acknowledged")
        return item["receipt_high_water"] in order and order.index(item["receipt_high_water"]) >= order.index(until)
