"""Authorized direct-pair views; no Domain conversation or Native Session creation."""
from __future__ import annotations

import base64
import json

from cryptography.fernet import Fernet, InvalidToken

from runtime.communication_client_queries import conversation_view_id
from runtime.communication_client_storage import (
    ClientStateIdentity,
    cursor_secret,
    read_preferences,
)
from runtime.communication_http import CommunicationHttpError
from runtime.errors import AuthorizationDenied, NotFound
from runtime.project_common import handle


def client_page_state(codec, token, query):
    try:
        state = json.loads(codec.decrypt(token.encode(), ttl=86400))
        if not isinstance(state, dict) or state.get("query") != query:
            raise ValueError("cursor namespace differs")
        return state
    except (InvalidToken, ValueError, TypeError) as error:
        raise CommunicationHttpError("cursor_invalid", "Restart the authorized query page", status_code=409) from error


def client_snapshot_token(codec, snapshot_id, query, state, *, position, initial):
    """Keep the validated caller's anchor byte-for-byte across page results."""
    expected = state | {position: initial}
    if snapshot_id is not None:
        if client_page_state(codec, snapshot_id, query) != expected:
            raise CommunicationHttpError("cursor_invalid", "Cursor and snapshot differ", status_code=409)
        return snapshot_id
    return codec.encrypt(json.dumps(expected, separators=(",", ":")).encode()).decode()


class ClientConversationViews:
    def _personal_page_version(self, cursor, bound, project):
        cursor.execute("SELECT (SELECT COALESCE(sum(revision),0)::text FROM communication_client_read_state "
            "WHERE tenant_id=%s AND project_id=%s AND actor_ref=%s),"
            "(SELECT COALESCE(sum(revision),0)::text FROM communication_client_preferences "
            "WHERE tenant_id=%s AND project_id=%s AND actor_ref=%s)",
            (bound.tenant_id, project, self._private_actor_ref(cursor, project)) * 2)
        return list(cursor.fetchone())

    def conversations(self, project, *, limit=50, cursor=None, snapshot_id=None, include_archived=False):
        from runtime.communication_client_snapshot import is_materialized_page

        if is_materialized_page(snapshot_id, cursor):
            if include_archived:
                raise CommunicationHttpError("snapshot_invalid", "Conversation filters differ from the captured snapshot.", status_code=409)
            return self.snapshot_page(project, "conversations", limit=limit, cursor=cursor, snapshot_id=snapshot_id)
        if type(limit) is not int or not 1 <= limit <= 100 or type(include_archived) is not bool:
            raise ValueError("invalid conversation page arguments")

        def selected(bound, cur, _root, _command):
            address = self.project_service._communication_address(cur, project)
            from runtime.project_common import digest

            query = digest({"kind": "conversations", "tenant": bound.tenant_id, "project": project,
                            "actor": address, "authorization": self._cursor_binding(bound, cur, project),
                            "include_archived": include_archived})
            personal_version = self._personal_page_version(cur, bound, project)
            codec = Fernet(base64.urlsafe_b64encode(cursor_secret(cur.connection)))
            if cursor or snapshot_id:
                state = client_page_state(codec, cursor or snapshot_id, query)
                if state.get("personal") != personal_version:
                    raise CommunicationHttpError("cursor_invalid", "Personal state changed; restart the conversation page", status_code=409)
                if cursor and snapshot_id:
                    original = client_page_state(codec, snapshot_id, query)
                    if (original["high"], original.get("personal")) != (state["high"], personal_version):
                        raise CommunicationHttpError("cursor_invalid", "Cursor and snapshot differ", status_code=409)
            else:
                cur.execute("SELECT COALESCE(MAX(sequence),0) FROM communication_messages "
                    "WHERE tenant_id=%s AND project_id=%s AND (sender=%s OR recipient=%s)",
                    (bound.tenant_id, project, address, address))
                state = {"query": query, "high": cur.fetchone()[0], "before": None, "personal": personal_version}
            snapshot = client_snapshot_token(codec, snapshot_id, query, state, position="before", initial=None)
            selected, before = [], state["before"]
            while len(selected) <= limit:
                cur.execute("SELECT peer,last_sequence FROM (SELECT CASE WHEN sender=%s THEN recipient ELSE sender END peer,"
                    "MAX(sequence) last_sequence FROM communication_messages WHERE tenant_id=%s AND project_id=%s "
                    "AND (sender=%s OR recipient=%s) AND sequence<=%s GROUP BY 1) pairs "
                    "WHERE (%s::bigint IS NULL OR last_sequence<%s) ORDER BY last_sequence DESC LIMIT 101",
                    (address, bound.tenant_id, project, address, address, state["high"], before, before))
                rows = cur.fetchall()
                for peer, sequence in rows:
                    before = sequence
                    view = self._conversation_view(bound, cur, project, address, peer, high=state["high"])
                    if include_archived or not view["archived"]:
                        selected.append((view, sequence))
                        if len(selected) > limit:
                            break
                if len(rows) < 101:
                    break
            next_cursor = codec.encrypt(json.dumps(state | {"before": selected[limit - 1][1]}).encode()).decode() if len(selected) > limit else None
            if self._personal_page_version(cur, bound, project) != personal_version:
                raise CommunicationHttpError("cursor_invalid", "Personal state changed during this page", status_code=409)
            return {"items": [item[0] for item in selected[:limit]], "page": {"next_cursor": next_cursor, "snapshot_id": snapshot}}
        return self._validate("ConversationPage", self._transaction(project, "list_messages", selected))

    def _conversation_peer(self, bound, cursor, project, conversation_id):
        address = self.project_service._communication_address(cursor, project)
        cursor.execute("SELECT DISTINCT CASE WHEN sender=%s THEN recipient ELSE sender END "
            "FROM communication_messages WHERE tenant_id=%s AND project_id=%s AND (sender=%s OR recipient=%s)",
            (address, bound.tenant_id, project, address, address))
        for (peer,) in cursor.fetchall():
            if conversation_view_id(bound.tenant_id, project, address, peer) == conversation_id:
                return address, peer
        # Empty views are derived from actual authorized contacts. This also
        # works after restart, without persisting a create-conversation entity.
        try:
            contact_bound, contact_project, contact_command = self.project_service._authorize(
                bound, cursor, project, "list_collaborators", {"project_id": project})
        except (AuthorizationDenied, PermissionError):
            raise NotFound("conversation", conversation_id) from None
        page_cursor = None
        while True:
            _state, page, _actions = self.project_service._list_collaborators(contact_bound, cursor, contact_project, contact_command,
                {"project_id": project, "limit": 100, "cursor": page_cursor}, self.credential)
            for item in page["items"]:
                peer = item["collaborator_handle"]
                if peer != address and conversation_view_id(bound.tenant_id, project, address, peer) == conversation_id:
                    return address, peer
            page_cursor = page["next_cursor"]
            if page_cursor is None:
                raise NotFound("conversation", conversation_id)

    def _conversation_view(self, bound, cursor, project, address, peer, *, high=None):
        personal_version = self._personal_page_version(cursor, bound, project)
        conversation = conversation_view_id(bound.tenant_id, project, address, peer)
        identity = ClientStateIdentity(bound.tenant_id, project, self._viewer_actor_ref(project, address), conversation)
        from runtime.communication_client_viewer_storage import require_personal_owner

        require_personal_owner(cursor, identity, self.project_service.context.principal_ref)
        actual_revision = None
        if (getattr(self.authority, "_communication_conversation_storage_available", False)
                or getattr(self.authority, "_communication_events_enabled", False)):
            from runtime.communication_conversation_storage import sync_conversation_view

            actual_revision = sync_conversation_view(cursor, identity, address, peer)
        if high is None:
            # The counter fence precedes all current source reads. A writer
            # cannot commit private fields while waiting to advance this view.
            cursor.execute("SELECT COALESCE(MAX(sequence),0) FROM communication_messages WHERE tenant_id=%s AND project_id=%s "
                "AND ((sender=%s AND recipient=%s) OR (sender=%s AND recipient=%s))",
                (bound.tenant_id, project, address, peer, peer, address))
            high = cursor.fetchone()[0]
        preferences = read_preferences(cursor, identity)
        cursor.execute("SELECT through_sequence,unread_override,revision FROM communication_client_read_state "
            "WHERE tenant_id=%s AND project_id=%s AND actor_ref=%s AND conversation_id=%s", identity.values())
        through, unread_override, read_revision = cursor.fetchone() or (0, False, 0)
        cursor.execute("SELECT c.message_id,m.created_at FROM communication_messages c JOIN delivery_messages m "
            "USING(tenant_id,message_id) WHERE c.tenant_id=%s AND c.project_id=%s "
            "AND ((c.sender=%s AND c.recipient=%s) OR (c.sender=%s AND c.recipient=%s)) "
            "AND (%s::bigint IS NULL OR c.sequence<=%s) ORDER BY c.sequence DESC LIMIT 1",
            (bound.tenant_id, project, address, peer, peer, address, high, high))
        last = cursor.fetchone()
        cursor.execute("SELECT count(*),count(*) FILTER(WHERE recipient=%s AND pair_sequence>%s) FROM "
            "(SELECT recipient,row_number() OVER(ORDER BY sequence) pair_sequence FROM communication_messages "
            "WHERE tenant_id=%s AND project_id=%s AND ((sender=%s AND recipient=%s) OR (sender=%s AND recipient=%s)) "
            "AND (%s::bigint IS NULL OR sequence<=%s)) pair_messages",
            (address, through, bound.tenant_id, project, address, peer, peer, address, high, high))
        count, unread = cursor.fetchone()
        if actual_revision is not None:
            # Legacy high-water pages can reconstruct their earlier public
            # component while private revisions remain bound by their token.
            cursor.execute("SELECT message_count FROM communication_conversation_versions WHERE tenant_id=%s AND project_id=%s "
                "AND conversation_id=%s AND viewer_address=%s AND peer_address=%s",
                (bound.tenant_id, project, conversation, address, peer))
            actual_revision -= max(0, cursor.fetchone()[0] - count)
        if self._personal_page_version(cursor, bound, project) != personal_version:
            raise CommunicationHttpError("cursor_invalid", "Personal state changed during this view", status_code=409)
        return {"conversation_id": conversation, "project_id": project, "participants": sorted((address, peer)),
            "last_message_handle": handle("message", project, last[0]) if last else None,
            "last_activity_at": last[1].isoformat() if last else None,
            "unread_count": max(unread, 1 if unread_override else 0),
            "revision": actual_revision if actual_revision is not None else count + read_revision + preferences["revision"],
            "archived": preferences["archived"], "muted": preferences["muted"]}

    def resolve_conversation(self, project, *, peer):
        def selected(bound, cursor, _root, _command):
            address = self.project_service._communication_address(cursor, project)
            if address == peer:
                raise CommunicationHttpError("unsupported", "Direct pair views require two distinct participants", status_code=409)
            try:
                conversation = conversation_view_id(bound.tenant_id, project, address, peer)
            except ValueError as error:
                raise CommunicationHttpError("invalid_argument", "Peer must be an address in this project") from error
            own, actual_peer = self._conversation_peer(bound, cursor, project, conversation)
            return self._conversation_view(bound, cursor, project, own, actual_peer)
        return self._validate("Conversation", self._transaction(project, "list_messages", selected))

    def conversation(self, project, conversation_id):
        def selected(bound, cursor, _root, _command):
            own, peer = self._conversation_peer(bound, cursor, project, conversation_id)
            return self._conversation_view(bound, cursor, project, own, peer)
        return self._validate("Conversation", self._transaction(project, "list_messages", selected))
