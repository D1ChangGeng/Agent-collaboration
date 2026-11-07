"""HTTP client read/send projections from the existing authenticated authority.

Immutable Message revision is 1; acceptance time is the timestamp recorded in
the committed Authority message row. Technical delivery is a separate view.
"""
from __future__ import annotations

import base64
import hashlib
import json
from copy import copy

from cryptography.fernet import Fernet

from runtime.client_contracts import ClientContracts
from runtime.communication_client_attachments import ClientAttachmentService
from runtime.communication_client_auth import ClientCursorAuthorization
from runtime.communication_client_events import ClientEventFeed
from runtime.communication_client_native_links import ClientNativeLinkService
from runtime.communication_client_native_source import ClientNativeSourceService
from runtime.communication_client_notices import NoticeQueryService
from runtime.communication_client_queries import conversation_view_id
from runtime.communication_client_receivers import ReceiverQueryService
from runtime.communication_client_recovery import ClientRecoveryService
from runtime.communication_client_search import ClientSearchService
from runtime.communication_client_snapshot import ClientSnapshotService, is_materialized_page
from runtime.communication_client_state import ClientStateService
from runtime.communication_client_views import (
    ClientConversationViews,
    client_page_state,
    client_snapshot_token,
)
from runtime.communication_http import CommunicationHttpError
from runtime.errors import AuthorizationDenied, InvalidToolArgument, NotFound
from runtime.project_common import digest, handle, parse_handle

_contracts = ClientContracts()


class CommunicationClientService(ClientConversationViews, ClientStateService, ClientCursorAuthorization, ClientSearchService, ReceiverQueryService, NoticeQueryService, ClientEventFeed, ClientSnapshotService, ClientAttachmentService, ClientNativeLinkService, ClientNativeSourceService, ClientRecoveryService):
    def __init__(self, projects, credential, *, message_bytes=262144):
        self.project_service, self.credential = projects, credential
        self.authority = projects.service.authority
        if type(message_bytes) is not int or not 1 <= message_bytes <= 1048576:
            raise ValueError("invalid client message limit")
        self.message_bytes = message_bytes

    def _execute(self, name, args):
        return self.project_service.execute(name, args, self.credential)

    def _validate(self, name, data):
        return _contracts.validate(name, data)

    def _transaction(self, project, name, callback):
        self.project_service.service.authenticate(self.credential)
        self.project_service._check_tool_policy(name)
        with self.authority.transaction() as (authority, connection), connection.cursor() as cursor:
            bound, root, command = self.project_service._authorize(authority, cursor, project, name, {"project_id": project})
            result = callback(bound, cursor, root, command)
            self.project_service.service.authenticate(self.credential)
            self.project_service._authorize(bound, cursor, project, name, {"project_id": project})
            return result

    def profile(self):
        _state, data, _actions = self._execute("read_profile", {})
        actor = data.get("actor")
        level = actor.get("organization", {}).get("level") if actor else None
        if level == "unknown" and actor.get("binding_source") == "trusted_collaborator_binding":
            slot, bindings = actor.get("agent_slot_id"), actor.get("bindings", [])
            if (slot is not None and bindings and all(binding.get("agent_slot_id") == slot
                    and binding.get("principal_ref") == self.project_service.context.principal_ref
                    and binding.get("organization", {}).get("level") in {"agent", "unknown"} for binding in bindings)):
                # An authenticated stable collaborator is an ordinary Actor even
                # when legacy management responsibilities were never declared.
                # Actual tools/Grants remain authoritative for every action.
                level = "agent"
        if not actor or level not in {"client", "root", "route", "agent"}:
            raise CommunicationHttpError("authorization_unavailable", "Current caller binding is unavailable", status_code=403)
        # Global identity is the actual authenticated subject. Project-scoped
        # routable addresses are returned by contacts.is_self in each namespace.
        return self._validate("Actor", {"address": self.project_service.context.principal_ref,
            "principal_ref": self.project_service.context.principal_ref, "level": level,
            "agent_slot_id": actor.get("agent_slot_id"), "auth_revision": digest(data),
            "allowed_actions": self.project_service.available_tools(self.credential)})

    def projects(self, *, limit=50, cursor=None, snapshot_id=None):
        if snapshot_id is not None:
            raise CommunicationHttpError("cursor_invalid", "Project snapshots require a new query", status_code=409)
        _state, data, _actions = self._execute("list_projects", {"limit": limit, "cursor": cursor})
        items = []
        for row in data["items"]:
            def selected(_bound, cur, _root, _cmd, row=row):
                cur.execute("SELECT name,revision FROM collaboration_projects WHERE tenant_id=%s AND project_id=%s",
                            (self.authority.tenant_id, row["project_id"]))
                value = cur.fetchone()
                if value is None:
                    raise NotFound("project", row["project_id"])
                return {"project_id": row["project_id"], "root_handle": row["root_handle"], "name": value[0],
                        "revision": value[1], "allowed_actions": self._allowed_actions(_bound, cur, row["project_id"])}
            items.append(self._transaction(row["project_id"], "load_project", selected))
        return self._validate("ProjectPage", {"items": items, "page": {"next_cursor": data.get("next_cursor"), "snapshot_id": None}})

    def _allowed_actions(self, bound, cursor, project):
        allowed = []
        for name in ("load_project", "list_routes", "list_collaborators", "list_messages", "read_message", "send_message", "configure_team", "create_route"):
            try:
                self.project_service._check_tool_policy(name)
                self.project_service._authorize(bound, cursor, project, name, {"project_id": project})
            except (PermissionError, AuthorizationDenied):
                continue
            allowed.append(name)
        return allowed

    def routes(self, project, *, limit=50, cursor=None, snapshot_id=None):
        if snapshot_id is not None:
            raise CommunicationHttpError("cursor_invalid", "Route snapshots require a new query", status_code=409)
        _state, data, _actions = self._execute("list_routes", {"project_id": project, "limit": limit, "cursor": cursor})
        items = [{"route_handle": row["route_handle"], "project_id": project,
            "scope_handle": handle("scope", project, row["scope_id"]), "display_name": row["definition"].get("display_name", ""),
            "goal": row["definition"].get("goal", ""), "state": row["state"], "revision": row["revision"]} for row in data["items"]]
        return self._validate("RoutePage", {"items": items, "page": {"next_cursor": data.get("next_cursor"), "snapshot_id": None}})

    def contacts(self, project, *, limit=50, cursor=None, snapshot_id=None, name=None, scope_handle=None):
        if is_materialized_page(snapshot_id, cursor):
            if name is not None or scope_handle is not None:
                raise CommunicationHttpError("snapshot_invalid", "Contact filters differ from the captured snapshot.", status_code=409)
            return self.snapshot_page(project, "contacts", limit=limit, cursor=cursor, snapshot_id=snapshot_id)
        if snapshot_id is not None:
            raise CommunicationHttpError("cursor_invalid", "Contact snapshots require a new query", status_code=409)
        args = {"project_id": project, "limit": limit, "cursor": cursor}
        args.update({key: value for key, value in {"name": name, "scope_handle": scope_handle}.items() if value is not None})
        def project_contacts(bound, cur, root, cmd):
            cur.execute("SELECT revision FROM communication_contact_versions WHERE tenant_id=%s AND project_id=%s FOR SHARE",
                        (bound.tenant_id, project))
            version = cur.fetchone()
            if version is None:
                raise LookupError("client contact projection requires explicit adoption")
            _state, data, _actions = self.project_service._list_collaborators(bound, cur, root, cmd, args, self.credential)
            items = []
            for row in data["items"]:
                address = row.get("collaborator_handle") or row.get("address")
                slot = row.get("agent_slot_id")
                cur.execute("SELECT e.endpoint_id FROM delivery_endpoints e WHERE e.tenant_id=%s AND e.agent_slot_id=%s AND e.status='active' ORDER BY e.endpoint_id",
                            (self.authority.tenant_id, slot))
                receivers = [value[0] for value in cur.fetchall()]
                scope = row.get("scope_handle")
                items.append({"address": address, "display_name": row.get("display_name", address), "agent_slot_id": slot,
                    "manager_handle": row.get("manager_handle"), "role": row.get("role"), "scope_handles": [scope] if scope else [],
                    "receiver_refs": receivers, "is_self": address == data["self"], "revision": version[0]})
            return {"items": items, "page": {"next_cursor": data.get("next_cursor"), "snapshot_id": None}}
        return self._validate("ContactPage", self._transaction(project, "list_collaborators", project_contacts))

    def _message(self, cursor, bound, project, reference, body, offset, *, high=None):
        identifier = parse_handle(reference, "message", project)
        row = self.project_service._communication_row(bound, cursor, {"project_id": project}, identifier)
        content = row[3]["content"].encode("utf-8")
        end = body.get("next_offset")
        if end is None:
            end = len(content)
        if content[offset:end].decode("utf-8") != body["content"]:
            raise ValueError("Core body slice differs from immutable message")
        cur_id = conversation_view_id(bound.tenant_id, project, row[0], row[1])
        cursor.execute("SELECT count(*) FROM communication_messages WHERE tenant_id=%s AND project_id=%s AND sequence<=%s "
            "AND ((sender=%s AND recipient=%s) OR (sender=%s AND recipient=%s))", (bound.tenant_id, project, row[2], row[0], row[1], row[1], row[0]))
        sequence = str(cursor.fetchone()[0])
        cursor.execute("SELECT created_at FROM delivery_messages WHERE tenant_id=%s AND message_id=%s", (bound.tenant_id, identifier))
        created = cursor.fetchone()[0].isoformat()
        cursor.execute("SELECT count(*),(array_agg(c.message_id ORDER BY c.sequence))[1] FROM communication_replies r JOIN communication_messages c "
            "ON c.tenant_id=r.tenant_id AND c.project_id=r.project_id AND c.message_id=r.reply_id "
            "WHERE r.tenant_id=%s AND r.project_id=%s AND r.request_id=%s AND (%s::bigint IS NULL OR c.sequence<=%s)",
            (bound.tenant_id, project, identifier, high, high))
        reply_count, first = cursor.fetchone()
        return {"message_handle": handle("message", project, identifier), "project_id": project, "conversation_id": cur_id,
            "sender": row[0], "to": row[1], "content": {"text": body["content"], "offset": offset,
                "next_offset": body.get("next_offset"), "total_bytes": len(content), "digest": hashlib.sha256(content).hexdigest()},
            "reply_to": row[3]["reply_to"], "attachment_refs": row[3].get("attachment_refs", []), "conversation_sequence": sequence,
            "committed_at": created, "revision": 1 + reply_count,
            "source": "acs_client" if row[0].startswith("client:") else "acs_agent",
            "first_reply_handle": handle("message", project, first) if first else None}

    def _lock_delivery_version(self, cursor, bound, project, identifier):
        # ACL precedes the lock. Every delivery/reply source writer ticks this
        # row in its own transaction, so a short shared lock freezes the view
        # while current authorization remains readable under READ COMMITTED.
        self.project_service._communication_row(bound, cursor, {"project_id": project}, identifier)
        cursor.execute("SELECT revision,updated_at FROM communication_delivery_versions "
                       "WHERE tenant_id=%s AND message_id=%s FOR SHARE", (bound.tenant_id, identifier))
        row = cursor.fetchone()
        if row is None:
            raise LookupError("client delivery projection requires explicit adoption")
        return row[0], row[1].isoformat()

    def read_message(self, project, reference, *, offset=0, max_inline_bytes=16384, _high=None, include_native_source=False):
        if type(include_native_source) is not bool:
            raise TypeError("Native provenance selection must be a boolean")
        try:
            kind = reference.split(":", 1)[0]
            identifier = parse_handle(reference, kind if kind in {"message", "response"} else "message", project)
        except (AttributeError, ValueError) as error:
            raise CommunicationHttpError("invalid_argument", "Use a message reference in this project") from error
        def selected(bound, cur, root, cmd):
            self._lock_delivery_version(cur, bound, project, identifier)
            try:
                _state, data, actions = self.project_service._read_message(bound, cur, root, cmd,
                    {"project_id": project, "handle": reference, "offset": offset, "max_inline_bytes": max_inline_bytes}, self.credential)
            except ValueError as error:
                raise InvalidToolArgument("content_range", "Use a UTF-8 boundary and a budget that fits the next character.") from error
            if data.get("historical") or not isinstance(data.get("content"), str):
                raise CommunicationHttpError("unsupported", "Historical structured packets are not natural messages", status_code=409)
            message = self._message(cur, bound, project, data["message_handle"], data, offset, high=_high)
            reply = data.get("reply") if message["first_reply_handle"] else None
            first_reply = self._message(cur, bound, project, reply["message_handle"], reply, 0, high=_high) if reply else None
            continuations = [{"message_handle": action["arguments"]["handle"], "offset": action["arguments"]["offset"],
                              "max_inline_bytes": action["arguments"]["max_inline_bytes"]}
                for action in actions if action.get("tool") == "read_message" and "offset" in action["arguments"]
                and action["arguments"]["handle"] in {message["message_handle"], message["first_reply_handle"]}]
            return {"message": message, "first_reply": first_reply, "continuations": continuations}
        result = self._transaction(project, "read_message", selected)
        if include_native_source:
            result["native_source"] = self.native_source(project, result["message"]["message_handle"])
        return self._validate("ReadMessageResponse", result)

    def messages(self, project, *, limit=50, cursor=None, snapshot_id=None, **filters):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid message page limit")
        peer = filters.get("with") or filters.get("peer")
        direction = filters.get("direction", "both")
        if direction not in {"both", "incoming", "outgoing"}:
            raise ValueError("invalid message direction")
        conversation = filters.get("conversation_id")
        reply_root = filters.get("reply_root")

        def selected(bound, cur, _root, _cmd):
            from runtime.communication_client_storage import cursor_secret

            address = self.project_service._communication_address(cur, project)
            query = digest({"tenant": bound.tenant_id, "project": project, "actor": address,
                            "authorization": self._cursor_binding(bound, cur, project), "peer": peer,
                            "direction": direction, "conversation": conversation, "reply_root": reply_root})
            codec = Fernet(base64.urlsafe_b64encode(cursor_secret(cur.connection)))
            token = cursor or snapshot_id
            if token:
                state = client_page_state(codec, token, query)
                if cursor and snapshot_id and client_page_state(codec, snapshot_id, query)["high"] != state["high"]:
                    raise CommunicationHttpError("cursor_invalid", "Cursor and snapshot differ", status_code=409)
            else:
                cur.execute("SELECT COALESCE(MAX(sequence),0) FROM communication_messages WHERE tenant_id=%s AND project_id=%s AND (sender=%s OR recipient=%s)",
                            (bound.tenant_id, project, address, address))
                state = {"query": query, "high": cur.fetchone()[0], "after": 0}
            snapshot = client_snapshot_token(codec, snapshot_id, query, state, position="after", initial=0)
            if conversation and not peer:
                # Resolve a conversation ref only among this actor's own pairs.
                cur.execute("SELECT DISTINCT CASE WHEN sender=%s THEN recipient ELSE sender END FROM communication_messages "
                    "WHERE tenant_id=%s AND project_id=%s AND (sender=%s OR recipient=%s)",
                    (address, bound.tenant_id, project, address, address))
                matches = [value[0] for value in cur.fetchall()
                           if conversation_view_id(bound.tenant_id, project, address, value[0]) == conversation]
                if len(matches) != 1:
                    raise NotFound("conversation", conversation)
                chosen_peer = matches[0]
            else:
                chosen_peer = peer
            if chosen_peer and conversation and conversation_view_id(bound.tenant_id, project, address, chosen_peer) != conversation:
                raise ValueError("peer and conversation filters differ")
            root_id = parse_handle(reply_root, "message", project) if reply_root else None
            if root_id:
                self.project_service._communication_row(bound, cur, {"project_id": project}, root_id)
            cur.execute("SELECT c.message_id,c.sequence FROM communication_messages c WHERE c.tenant_id=%s AND c.project_id=%s "
                "AND c.sequence>%s AND c.sequence<=%s AND ((%s='both' AND (c.sender=%s OR c.recipient=%s)) "
                "OR (%s='incoming' AND c.recipient=%s) OR (%s='outgoing' AND c.sender=%s)) "
                "AND (%s::text IS NULL OR c.sender=%s OR c.recipient=%s) AND (%s::text IS NULL OR c.message_id=%s OR EXISTS "
                "(SELECT 1 FROM communication_replies r WHERE r.tenant_id=c.tenant_id AND r.project_id=c.project_id AND r.reply_id=c.message_id AND r.request_id=%s)) "
                "ORDER BY c.sequence LIMIT %s", (bound.tenant_id, project, state["after"], state["high"], direction, address, address,
                    direction, address, direction, address, chosen_peer, chosen_peer, chosen_peer, root_id, root_id, root_id, limit + 1))
            rows = cur.fetchall()
            next_cursor = codec.encrypt(json.dumps(state | {"after": rows[limit - 1][1]}).encode()).decode() if len(rows) > limit else None
            return [handle("message", project, row[0]) for row in rows[:limit]], {"next_cursor": next_cursor, "snapshot_id": snapshot}, state["high"]

        references, page, high = self._transaction(project, "list_messages", selected)
        items = [self.read_message(project, reference, _high=high)["message"] for reference in references]
        return self._validate("MessagePage", {"items": items, "page": page})

    def delivery(self, project, reference):
        try:
            identifier = parse_handle(reference, "message", project)
        except ValueError as error:
            raise CommunicationHttpError("invalid_argument", "Use a message reference in this project") from error
        def selected(bound, cur, _root, _cmd):
            revision, _updated_at = self._lock_delivery_version(cur, bound, project, identifier)
            row = self.project_service._communication_row(bound, cur, {"project_id": project}, identifier)
            cur.execute("SELECT layer,receipt_id,evidence_json FROM delivery_receipts WHERE tenant_id=%s AND message_id=%s", (bound.tenant_id, identifier))
            receipts = {value[0]: (value[1], value[2]) for value in cur.fetchall()}
            ack = receipts.get("runtime_acknowledged")
            cur.execute("SELECT binding_revision FROM delivery_messages WHERE tenant_id=%s AND message_id=%s", (bound.tenant_id, identifier))
            epoch = cur.fetchone()[0]
            native = {"state": "not_requested" if row[3]["activation"] == "message_only" or row[1].startswith("client:") else
                "accepted" if ack else "unknown" if row[4] == "uncertain" else
                "unsupported" if row[7] == "native_attachment_delivery_unsupported" else "pending", "operation_ref": row[6],
                "binding_epoch": epoch, "provider_generation": None, "evidence_ref": ack[0] if ack else None,
                "native_input_ref": ack[1].get("native_input_ref") if ack else None, "reason_code": row[7]}
            cur.execute("SELECT c.message_id FROM communication_replies r JOIN communication_messages c "
                "ON c.tenant_id=r.tenant_id AND c.project_id=r.project_id AND c.message_id=r.reply_id "
                "WHERE r.tenant_id=%s AND r.project_id=%s AND r.request_id=%s ORDER BY c.sequence LIMIT 1",
                (bound.tenant_id, project, identifier))
            first = cur.fetchone()
            return {"message_handle": handle("message", project, identifier), "accepted_by_authority": True,
                "target_inbox_committed": "target_inbox_committed" in receipts, "native": native,
                "consumption": {"state": "unobservable", "semantics": "provider_input_consumed", "evidence_ref": None},
                "response": {"present": first is not None, "message_handle": handle("message", project, first[0]) if first else None},
                "revision": revision}
        return self._validate("DeliveryFacts", self._transaction(project, "read_message", selected))

    def wait(self, project, request):
        request = self._validate("WaitRequest", request)
        state, data, _actions = self._execute("wait_for_response", {"project_id": project, **request})
        references = [item["message_handle"] for item in data["observations"]]
        values = [self.read_message(project, reference) for reference in references]
        return self._validate("WaitResponse", {"wait": {"state": "satisfied" if state == "satisfied" else "timed_out",
            "satisfied_handles": data["satisfied"], "pending_handles": data["pending"]},
            "items": [self.delivery(project, reference) for reference in references],
            "continuations": [item for value in values for item in value["continuations"]]})

    def send(self, project, body, *, client_request_id):
        body = self._validate("SendRequest", body)
        if body.get("attachment_refs"):
            self._attachment_limits()
        args = {key: value for key, value in body.items() if key != "attachment_refs" or value}
        adapted = copy(self.project_service)
        adapted._client_content_limit = self.message_bytes
        try:
            state, data, _actions = adapted.execute("send_message", {"project_id": project, "client_request_id": client_request_id, **args}, self.credential)
        except Exception as error:
            from runtime.project_http import OAuthScopeDenied

            if isinstance(error, OAuthScopeDenied):
                # execute(send_message) raises this only before its transaction
                # commits. Post-commit wait/read failures are wrapped below as
                # observation_unavailable with the actual committed handle.
                raise CommunicationHttpError("authorization_denied", "This action is not authorized.",
                    status_code=403, effect_state="none") from error
            if not body.get("attachment_refs"):
                raise
            from runtime.communication_client_attachments import attachment_failure

            raise attachment_failure(error) from error
        reference, operation = data["message_handle"], data["operation_id"]
        try:
            observation = data.get("observation")
            waited = observation if isinstance(observation, dict) else None
            wait = {"state": "not_requested", "satisfied_handles": [], "pending_handles": []}
            if body.get("response_mode", "async") == "sync":
                wait = {"state": "satisfied" if waited and not waited.get("pending") else "interrupted" if state == "observation_unavailable" else "timed_out",
                    "satisfied_handles": waited.get("satisfied", []) if waited else [],
                    "pending_handles": waited.get("pending", [reference]) if waited else [reference]}
            return self._validate("SendResponse", {"message": self.read_message(project, reference)["message"],
                "delivery": self.delivery(project, reference), "operation_ref": operation, "duplicate": data.get("duplicate", False), "wait": wait})
        except Exception as error:
            raise CommunicationHttpError("observation_unavailable", "Message committed; resume the original operation",
                status_code=503, retryable=False, effect_state="committed", operation_ref=operation) from error

    def operation(self, operation_ref, *, project_id=None):
        if project_id is None:
            raise ValueError("operation query requires its project namespace")
        if operation_ref.startswith("receiver-recovery-"):
            from runtime.receiver_recovery_operations import ReceiverRecoveryOperations

            return self._validate("Operation", ReceiverRecoveryOperations(self.project_service).read(project_id, operation_ref, self.credential))
        def selected(bound, cur, _root, _cmd):
            cur.execute("SELECT m.message_id,m.state,m.attempts,m.created_at,m.endpoint_id,m.binding_revision,m.receipt_high_water,m.last_error "
                "FROM delivery_messages m JOIN communication_messages c USING(tenant_id,message_id) "
                "WHERE m.tenant_id=%s AND c.project_id=%s AND m.operation_id=%s", (bound.tenant_id, project_id, operation_ref))
            row = cur.fetchone()
            if row is None:
                raise NotFound("operation", operation_ref)
            revision, updated_at = self._lock_delivery_version(cur, bound, project_id, row[0])
            cur.execute("SELECT message_id,state,attempts,created_at,endpoint_id,binding_revision,receipt_high_water,last_error "
                "FROM delivery_messages WHERE tenant_id=%s AND message_id=%s", (bound.tenant_id, row[0]))
            row = cur.fetchone()
            cur.execute("SELECT receipt_id FROM delivery_receipts WHERE tenant_id=%s AND message_id=%s ORDER BY layer", (bound.tenant_id, row[0]))
            refs = [value[0] for value in cur.fetchall()]
            phase = {"queued": "queued", "retry_wait": "deferred", "delivering": "submitting", "delivered": "accepted", "uncertain": "unknown",
                     "blocked": "definitively_rejected", "expired": "definitively_rejected", "budget_exhausted": "definitively_rejected"}[row[1]]
            return {"operation_id": operation_ref, "kind": "delivery", "state": phase, "message_handle": handle("message", project_id, row[0]),
                "receiver_ref": row[4], "binding_epoch": row[5], "effect_state": "native_possible" if row[6] in {"runtime_dispatched", "runtime_acknowledged"} else "committed",
                "reason_code": row[7], "evidence_refs": refs, "revision": revision,
                "created_at": row[3].isoformat(), "updated_at": updated_at}
        return self._validate("Operation", self._transaction(project_id, "read_message", selected))
