"""Owner-scoped durable Inbox projections; consumption is not business completion."""
from __future__ import annotations

from runtime.errors import AuthorizationDenied, NotFound
from runtime.project_common import canonical, handle, parse_handle


class InboxActions:
    def _inbox_consumed(self, cursor, project_id, kind, identifier, revision):
        cursor.execute("SELECT 1 FROM collaboration_inbox_consumptions WHERE tenant_id=%s AND project_id=%s "
                       "AND owner_ref=%s AND kind=%s AND item_id=%s AND revision=%s",
                       (self.context.tenant_id, project_id, self.context.principal_ref, kind, identifier, revision))
        return cursor.fetchone() is not None

    def _consume_inbox(self, cursor, project_id, kind, identifier, revision):
        cursor.execute("INSERT INTO collaboration_inbox_consumptions(tenant_id,project_id,owner_ref,kind,item_id,revision) "
                       "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                       (self.context.tenant_id, project_id, self.context.principal_ref, kind, identifier, revision))

    def _owns_inbox_slot(self, cursor, project_id, slot):
        cursor.execute("SELECT 1 FROM collaboration_memberships WHERE tenant_id=%s AND project_id=%s AND principal_ref=%s "
                       "AND profile=%s AND agent_slot_id=%s UNION ALL SELECT 1 FROM collaboration_route_grants "
                       "WHERE tenant_id=%s AND project_id=%s AND principal_ref=%s AND profile=%s AND agent_slot_id=%s",
                       (self.context.tenant_id, project_id, self.context.principal_ref, self.profile, slot,
                        self.context.tenant_id, project_id, self.context.principal_ref, self.profile, slot))
        return cursor.fetchone() is not None

    def _read_review_message(self, cursor, args):
        identifier = parse_handle(args["handle"], "review", args["project_id"])
        cursor.execute("SELECT reviewer_ref,revision,state,work_item_id,candidate_ref,source_baseline,definition,evidence_refs "
                       "FROM collaboration_review_requests WHERE tenant_id=%s AND project_id=%s AND request_id=%s FOR UPDATE",
                       (self.context.tenant_id, args["project_id"], identifier))
        row = cursor.fetchone()
        if row is None:
            raise NotFound("review", identifier)
        if row[0] != self.context.principal_ref:
            raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
        data = {"project_id": args["project_id"], "kind": "review", "review_handle": args["handle"],
            "revision": row[1], "state": row[2], "work_handle": handle("work", args["project_id"], row[3]),
            "candidate_ref": row[4], "source_baseline": row[5], "definition": row[6],
            "evidence_handles": [handle("evidence", args["project_id"], item) for item in row[7]],
            "consumed": args.get("consume", True) or self._inbox_consumed(cursor, args["project_id"], "review", identifier, row[1])}
        self._inbox_bound(data, args)
        if args.get("consume", True):
            self._consume_inbox(cursor, args["project_id"], "review", identifier, row[1])
        return "observed", data, []

    @staticmethod
    def _inbox_bound(value, args):
        maximum = args.get("max_inline_bytes", 16384)
        if type(maximum) is not int or not 1 <= maximum <= 65536 or len(canonical(value).encode()) > maximum:
            raise ValueError("Inbox content exceeds the requested inline bound")

    def _incoming_inbox(self, authority, cursor, project, command, args, credential):
        scopes = self._visible_scopes(authority, cursor, project)
        cursor.execute("SELECT i.message_id,m.state,m.receipt_high_water,m.packet_json->>'target_scope_id' "
                       "FROM inbox_messages i JOIN delivery_messages m USING(tenant_id,message_id) "
                       "JOIN collaboration_work_links l ON l.tenant_id=m.tenant_id AND l.work_item_id=m.packet_json->>'work_item_id' "
                       "WHERE i.tenant_id=%s AND l.project_id=%s "
                       "AND (%s::text[] IS NULL OR m.packet_json->>'target_scope_id'=ANY(%s)) "
                       "AND (EXISTS (SELECT 1 FROM collaboration_memberships p WHERE p.tenant_id=i.tenant_id "
                       "AND p.project_id=l.project_id AND p.principal_ref=%s AND p.profile=%s AND p.agent_slot_id=i.target_agent_slot_id) "
                       "OR EXISTS (SELECT 1 FROM collaboration_route_grants g WHERE g.tenant_id=i.tenant_id "
                       "AND g.project_id=l.project_id AND g.principal_ref=%s AND g.profile=%s AND g.agent_slot_id=i.target_agent_slot_id)) "
                       "AND NOT EXISTS (SELECT 1 FROM collaboration_inbox_consumptions c WHERE c.tenant_id=i.tenant_id "
                       "AND c.project_id=l.project_id AND c.owner_ref=%s AND c.kind='message' AND c.item_id=i.message_id AND c.revision=1) "
                       "AND ('message:' || l.project_id || ':' || i.message_id)>%s "
                       "AND (%s::text[]='{}' OR m.state=ANY(%s)) "
                       "ORDER BY i.message_id LIMIT 101", (self.context.tenant_id, args["project_id"], scopes, scopes,
                       self.context.principal_ref, self.profile, self.context.principal_ref, self.profile, self.context.principal_ref,
                       args.get("cursor") or "", args.get("states", []), args.get("states", [])))
        result = []
        for message_id, state, layer, _scope in cursor.fetchall():
            message_handle = handle("message", args["project_id"], message_id)
            try:
                self._authorize(authority, cursor, args["project_id"], "read_message", {
                    "project_id": args["project_id"], "handle": message_handle, "consume": False})
            except AuthorizationDenied:
                continue
            result.append({"kind": "message", "handle": message_handle, "message_handle": message_handle,
                "message_id": message_id, "state": state, "receipt_high_water": layer,
                "read": {"tool": "read_message", "arguments": {
                    "project_id": args["project_id"], "handle": message_handle}}})
        return result

    def _review_inbox(self, authority, cursor, project, _command, args, _credential):
        scopes = self._visible_scopes(authority, cursor, project)
        cursor.execute("SELECT r.request_id,r.revision,r.work_item_id,r.candidate_ref FROM collaboration_review_requests r "
                       "JOIN work_items w USING(tenant_id,work_item_id) WHERE r.tenant_id=%s AND r.project_id=%s "
                       "AND r.reviewer_ref=%s AND r.state='pending' AND (%s::text[] IS NULL OR w.scope_id=ANY(%s)) "
                       "AND NOT EXISTS (SELECT 1 FROM collaboration_inbox_consumptions c WHERE c.tenant_id=r.tenant_id "
                       "AND c.project_id=r.project_id AND c.owner_ref=r.reviewer_ref AND c.kind='review' "
                       "AND c.item_id=r.request_id AND c.revision=r.revision) "
                       "AND ('review:' || r.project_id || ':' || r.request_id)>%s ORDER BY r.request_id LIMIT 101",
                       (self.context.tenant_id, args["project_id"], self.context.principal_ref, scopes, scopes, args.get("cursor") or ""))
        result = []
        for identifier, revision, work_id, candidate in cursor.fetchall():
            review_handle = handle("review", args["project_id"], identifier)
            try:
                self._authorize(authority, cursor, args["project_id"], "read_message", {
                    "project_id": args["project_id"], "handle": review_handle, "consume": False})
            except AuthorizationDenied:
                continue
            result.append({"kind": "review", "handle": review_handle, "review_handle": review_handle,
                "revision": revision, "state": "pending", "work_handle": handle("work", args["project_id"], work_id),
                "candidate_ref": candidate, "read": {"tool": "read_message", "arguments": {
                    "project_id": args["project_id"], "handle": review_handle}}})
        return result
