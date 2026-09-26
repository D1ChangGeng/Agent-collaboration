"""Durable watch/notification intent; wake signals never replace Inbox state."""
from __future__ import annotations

import uuid

from runtime.errors import AuthorizationDenied, NotFound, RevisionConflict
from runtime.project_common import canonical, digest, handle, parse_handle


class ContinuationActions:
    def _watch_scope_visible(self, cursor, project_id, targets, *, tool="check_inbox"):
        if not targets:
            bound, project, _ = self._authorize(self.service.authority, cursor, project_id, tool,
                                               {"project_id": project_id})
            return self._visible_scopes(bound, cursor, project) is None
        for target in targets:
            value = target.get("handle") or handle(
                "work" if target["kind"] == "work_item" else target["kind"], project_id, target["id"])
            try:
                bound, project, _ = self._authorize(self.service.authority, cursor, project_id, tool,
                                                   {"project_id": project_id, "target_handle": value})
                if target["kind"] == "project" and self._visible_scopes(bound, cursor, project) is not None:
                    return False
            except (AuthorizationDenied, NotFound):
                return False
        return True

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
                return prior[1]
            cursor.execute("SELECT COALESCE(MAX(revision),0) FROM collaboration_notification_sessions "
                           "WHERE tenant_id=%s AND project_id=%s AND owner_ref=%s",
                           (self.context.tenant_id, project_id, self.context.principal_ref))
            revision = cursor.fetchone()[0] + 1
            cursor.execute("UPDATE collaboration_notification_sessions SET state='retired' WHERE tenant_id=%s "
                           "AND project_id=%s AND owner_ref=%s AND session_ref<>%s AND state='active'",
                           (self.context.tenant_id, project_id, self.context.principal_ref, session_ref))
            cursor.execute("INSERT INTO collaboration_notification_sessions VALUES (%s,%s,%s,%s,%s,%s,'active') "
                           "ON CONFLICT(tenant_id,project_id,owner_ref,session_ref) DO UPDATE "
                           "SET connection_ref=EXCLUDED.connection_ref,revision=EXCLUDED.revision",
                           (self.context.tenant_id, project_id, self.context.principal_ref,
                            session_ref, connection_ref, revision))
        return revision

    def pending_wake_keys(self, project_id, session_ref, connection_ref, credential):
        """Read current-owner wake keys; no liveness or Harness capability inference."""
        self.service.authenticate(credential)
        with (self.service.authority.transaction() as (authority, connection), connection.cursor() as cursor):
            bound, project, command = self._authorize(authority, cursor, project_id, "check_inbox", {"project_id": project_id})
            cursor.execute("SELECT 1 FROM collaboration_notification_sessions WHERE tenant_id=%s "
                           "AND project_id=%s AND owner_ref=%s AND session_ref=%s AND connection_ref=%s AND state='active'",
                           (self.context.tenant_id, project_id, self.context.principal_ref, session_ref, connection_ref))
            if cursor.fetchone() is None:
                return []
            inbox = self._check_inbox(bound, cursor, project, command, {"project_id": project_id}, credential)[1]
            cursor.execute("SELECT t.response_handle FROM collaboration_response_tracking t "
                           "JOIN collaboration_response_subscriptions s USING(tenant_id,project_id,message_id) "
                           "WHERE t.tenant_id=%s AND t.project_id=%s AND t.initiating_principal=%s "
                           "AND s.enabled AND s.consumed_at IS NULL AND EXISTS (SELECT 1 FROM delivery_receipts r "
                           "WHERE r.tenant_id=t.tenant_id AND r.message_id=t.message_id AND r.layer='response_received')",
                           (self.context.tenant_id, project_id, self.context.principal_ref))
            keys = [row[0] + ":completion:1" for row in cursor.fetchall()]
            visible_responses = {item["response_handle"] for item in inbox["items"] if item["kind"] == "response"}
            keys = [key for key in keys if key.removesuffix(":completion:1") in visible_responses]
            keys.extend(item["handle"] + ":content:" + str(item.get("revision", 1))
                        for item in inbox["items"] if item["kind"] in {"message", "review"})
            keys.extend(item["notification_handle"] for item in inbox["notifications"] if item["notification_enabled"])
            return sorted(keys)

    def _watch_changes(self, authority, cursor, project, command, args, _credential):
        targets = sorted(set(args["target_handles"]))
        if len(targets) != len(args["target_handles"]) or len(targets) > 32:
            raise ValueError("watch targets must be unique and bounded")
        if args["delivery_policy"] not in {"notify_current_session", "inbox_only"}:
            raise ValueError("unsupported watch delivery policy")
        normalized = []
        for target in targets:
            kind = target.split(":", 1)[0]
            identifier = parse_handle(target, kind, args["project_id"])
            if kind == "project":
                if identifier != project[1]:
                    raise NotFound(kind, identifier)
                normalized.append({"kind": "project", "id": args["project_id"]})
            elif kind == "work":
                self._project_work(cursor, args["project_id"], target)
                normalized.append({"kind": "work_item", "id": identifier})
            elif kind == "route":
                cursor.execute("SELECT 1 FROM collaboration_routes WHERE tenant_id=%s AND project_id=%s AND route_id=%s",
                               (self.context.tenant_id, args["project_id"], identifier))
                if not cursor.fetchone():
                    raise NotFound(kind, identifier)
                normalized.append({"kind": kind, "id": identifier})
            elif kind == "review":
                cursor.execute("SELECT work_item_id FROM collaboration_review_requests WHERE tenant_id=%s "
                               "AND project_id=%s AND request_id=%s", (self.context.tenant_id, args["project_id"], identifier))
                if cursor.fetchone() is None:
                    raise NotFound(kind, identifier)
                normalized.append({"kind": kind, "id": identifier, "handle": target})
            else:
                raise ValueError("unsupported watch target kind")
        target_digest = digest(targets)
        if not self._watch_scope_visible(cursor, args["project_id"], normalized, tool="watch_changes"):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        cursor.execute("SELECT watch_id,revision FROM collaboration_watches WHERE tenant_id=%s AND project_id=%s "
                       "AND owner_ref=%s AND targets_digest=%s FOR UPDATE",
                       (self.context.tenant_id, args["project_id"], self.context.principal_ref, target_digest))
        old = cursor.fetchone()
        revision = old[1] if old else 0
        if revision != args["expected_revision"]:
            raise RevisionConflict("watch", args["expected_revision"], revision)
        watch_id = old[0] if old else "watch-" + uuid.uuid4().hex
        cursor.execute("INSERT INTO collaboration_watches VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,pg_current_snapshot()) "
                       "ON CONFLICT(tenant_id,project_id,watch_id) DO UPDATE SET event_kinds=EXCLUDED.event_kinds,"
                       "delivery_policy=EXCLUDED.delivery_policy,revision=EXCLUDED.revision,enabled=TRUE",
                       (self.context.tenant_id, args["project_id"], watch_id, self.context.principal_ref,
                        target_digest, canonical(normalized), canonical(args["event_kinds"]),
                        args["delivery_policy"], revision+1))
        result = self._management_record(authority, cursor, command, args, target_kind="projection",
            target_id=watch_id, state="watch.configured", revision=revision+1)
        return "watching", {"project_id": args["project_id"],
            "subscription_handle": handle("subscription", args["project_id"], watch_id),
            "revision": revision+1, "operation_id": result.operation_id}, []

    def _set_notification(self, authority, cursor, _project, command, args, _credential):
        kind = args["target_handle"].split(":", 1)[0]
        if kind not in {"response", "subscription"}:
            raise ValueError("notification target requires a response or subscription")
        target = parse_handle(args["target_handle"], kind, args["project_id"])
        is_watch = kind == "subscription" and target.startswith("watch-")
        if is_watch:
            cursor.execute("SELECT owner_ref,revision FROM collaboration_watches WHERE tenant_id=%s "
                           "AND project_id=%s AND watch_id=%s FOR UPDATE",
                           (self.context.tenant_id, args["project_id"], target))
        else:
            cursor.execute("SELECT t.initiating_principal,s.revision FROM collaboration_response_tracking t "
                           "JOIN collaboration_response_subscriptions s USING(tenant_id,project_id,message_id) "
                           "WHERE t.tenant_id=%s AND t.project_id=%s AND t.message_id=%s FOR UPDATE OF s",
                           (self.context.tenant_id, args["project_id"], target))
        found = cursor.fetchone()
        if found is None:
            raise NotFound("subscription", target)
        if found[0] != self.context.principal_ref:
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        if found[1] != args["expected_revision"]:
            raise RevisionConflict(target, args["expected_revision"], found[1])
        if is_watch:
            cursor.execute("UPDATE collaboration_watches SET enabled=%s,revision=revision+1 "
                           "WHERE tenant_id=%s AND project_id=%s AND watch_id=%s",
                           (args["enabled"], self.context.tenant_id, args["project_id"], target))
        else:
            cursor.execute("UPDATE collaboration_response_subscriptions SET enabled=%s,revision=revision+1 "
                           "WHERE tenant_id=%s AND project_id=%s AND message_id=%s",
                           (args["enabled"], self.context.tenant_id, args["project_id"], target))
        result = self._management_record(authority, cursor, command, args, target_kind="projection",
            target_id=target, state="notification.configured", revision=found[1]+1)
        return "configured", {"project_id": args["project_id"], "target_handle": args["target_handle"],
            "revision": found[1]+1, "enabled": args["enabled"], "operation_id": result.operation_id}, []

    def _project_watch_events(self, cursor, project_id):
        cursor.execute("SELECT watch_id,targets,event_kinds,start_snapshot::text FROM collaboration_watches "
                       "WHERE tenant_id=%s AND project_id=%s AND owner_ref=%s FOR UPDATE",
                       (self.context.tenant_id, project_id, self.context.principal_ref))
        watches = cursor.fetchall()
        for watch_id, targets, kinds, snapshot in watches:
            if not self._watch_scope_visible(cursor, project_id, targets):
                continue
            # BIGSERIAL IDs are allocated before commit. A snapshot + anti-join
            # includes late lower-ID commits, while excluding pre-subscription
            # history. pg_current_xact_id records the top-level xid even inside
            # the Domain composition savepoint.
            cursor.execute(
                "SELECT e.event_id,e.target_kind,COALESCE(e.target_id,e.work_item_id),e.related_work_item_id,"
                "COALESCE(o.topic,e.to_state),e.command_id,e.initiated_by,e.resulting_revision,c.result_json,l.route_id "
                "FROM domain_events e LEFT JOIN operations op ON op.tenant_id=e.tenant_id AND op.command_id=e.command_id "
                "LEFT JOIN outbox o ON o.tenant_id=op.tenant_id AND o.operation_id=op.operation_id "
                "LEFT JOIN collaboration_commands c ON c.tenant_id=e.tenant_id AND c.project_id=%s AND c.command_id=e.command_id "
                "LEFT JOIN collaboration_work_links l ON l.tenant_id=e.tenant_id AND l.project_id=%s "
                "AND l.work_item_id=COALESCE(e.related_work_item_id,e.work_item_id,"
                "CASE WHEN e.target_kind='work_item' THEN e.target_id END) "
                "WHERE e.tenant_id=%s AND NOT pg_visible_in_snapshot(e.writer_xid,%s::pg_snapshot) "
                "AND ((e.target_kind='project' AND e.target_id=%s) OR c.command_id IS NOT NULL OR l.work_item_id IS NOT NULL) "
                "AND NOT EXISTS (SELECT 1 FROM collaboration_watch_observations n WHERE n.tenant_id=e.tenant_id "
                "AND n.project_id=%s AND n.watch_id=%s AND n.event_id=e.event_id) ORDER BY e.event_id LIMIT 1000",
                (project_id, project_id, self.context.tenant_id, snapshot, project_id, project_id, watch_id),
            )
            for event_id, target_kind, target_id, work_id, kind, command_id, actor, revision, result, route in cursor.fetchall():
                cursor.execute("INSERT INTO collaboration_watch_observations VALUES (%s,%s,%s,%s) "
                               "ON CONFLICT DO NOTHING RETURNING event_id",
                               (self.context.tenant_id, project_id, watch_id, event_id))
                if cursor.fetchone() is None:
                    continue
                public_kind = {"review.recorded": "review.submitted", "reviewer.assigned": "review.requested"}.get(kind, kind)
                if kinds and public_kind not in kinds:
                    continue
                matches = not targets or any(
                    target["kind"] == "project"
                    or (target["kind"] == target_kind and target["id"] == target_id)
                    or (target["kind"] == "work_item" and target["id"] == work_id)
                    or (target["kind"] == "route" and target["id"] == route)
                    or (target["kind"] == "review" and result and result[1].get("review_handle") == target["handle"])
                    for target in targets)
                if not matches:
                    continue
                notification = "notice-" + digest([watch_id, event_id])
                payload = {"event_id": event_id, "kind": public_kind, "command_id": command_id,
                           "actor": actor, "revision": revision, "target_kind": target_kind,
                           "target_id": target_id, "evidence_class": "authority_observation"}
                cursor.execute("INSERT INTO collaboration_inbox_notifications(tenant_id,project_id,notification_id,"
                               "owner_ref,watch_id,event_id,payload) VALUES (%s,%s,%s,%s,%s,%s,%s) "
                               "ON CONFLICT(tenant_id,project_id,watch_id,event_id) DO NOTHING",
                               (self.context.tenant_id, project_id, notification, self.context.principal_ref,
                                watch_id, event_id, canonical(payload)))

    def _notification_inbox(self, cursor, project_id):
        self._project_watch_events(cursor, project_id)
        cursor.execute("SELECT n.notification_id,n.payload,w.enabled,w.delivery_policy,w.targets FROM collaboration_inbox_notifications n "
                       "JOIN collaboration_watches w USING(tenant_id,project_id,watch_id) WHERE n.tenant_id=%s "
                       "AND n.project_id=%s AND n.owner_ref=%s AND n.consumed_at IS NULL ORDER BY n.event_id LIMIT 100",
                       (self.context.tenant_id, project_id, self.context.principal_ref))
        rows = cursor.fetchall()
        return [{"notification_handle": handle("notification", project_id, row[0]), "payload": row[1],
                 "notification_enabled": row[2] and row[3] == "notify_current_session"}
                for row in rows if self._watch_scope_visible(cursor, project_id, row[4])]

    def _read_notification(self, cursor, args):
        identifier = parse_handle(args["handle"], "notification", args["project_id"])
        cursor.execute("SELECT n.payload,n.consumed_at,w.targets FROM collaboration_inbox_notifications n "
                       "JOIN collaboration_watches w USING(tenant_id,project_id,watch_id) WHERE n.tenant_id=%s "
                       "AND n.project_id=%s AND n.notification_id=%s AND n.owner_ref=%s FOR UPDATE OF n",
                       (self.context.tenant_id, args["project_id"], identifier, self.context.principal_ref))
        row = cursor.fetchone()
        if row is None:
            raise NotFound("notification", identifier)
        if not self._watch_scope_visible(cursor, args["project_id"], row[2]):
            raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
        if args.get("consume", True):
            cursor.execute("UPDATE collaboration_inbox_notifications SET consumed_at=COALESCE(consumed_at,clock_timestamp()) "
                           "WHERE tenant_id=%s AND project_id=%s AND notification_id=%s",
                           (self.context.tenant_id, args["project_id"], identifier))
        return "observed", {"project_id": args["project_id"], "notification_handle": args["handle"],
                            "payload": row[0], "consumed": bool(row[1] or args.get("consume", True))}, []
