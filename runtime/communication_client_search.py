"""Participant-authorized literal search of existing natural ACS messages.

The hosting client service supplies its current authorization/cursor binding,
transaction boundary and owning message reader. Search creates no identity,
conversation, transcript, index, read marker or Native input.
"""
from __future__ import annotations

import base64
import json

from cryptography.fernet import Fernet

from runtime.communication_client_storage import cursor_secret
from runtime.communication_client_views import client_page_state
from runtime.communication_http import CommunicationHttpError
from runtime.errors import InvalidToolArgument
from runtime.project_common import digest, handle, parse_handle

SNIPPET_BYTES = 512
CONTEXT_CHARACTERS = 64


def _search_state(codec, token, query):
    state = client_page_state(codec, token, query)
    if (any(type(state.get(key)) is not int or not 0 <= state[key] <= 2**63 - 1 for key in ("high", "after"))
            or state["after"] > state["high"]):
        raise CommunicationHttpError("cursor_invalid", "Restart the authorized search page", status_code=409)
    return state


class ClientSearchService:
    """Literal, case-sensitive substring hits with bounded UTF-8 body excerpts."""

    def search(self, project, *, q, limit=50, cursor=None, snapshot_id=None, conversation_id=None, peer=None, **filters):
        if not isinstance(q, str) or not 1 <= len(q) <= 1000 or "\x00" in q:
            raise InvalidToolArgument("q", "Use between 1 and 1000 valid text characters.")
        try:
            q.encode("utf-8")
        except UnicodeError as error:
            raise InvalidToolArgument("q", "Use valid UTF-8 search text.") from error
        if type(limit) is not int or not 1 <= limit <= 100:
            raise InvalidToolArgument("limit", "Use a page limit between 1 and 100.")
        if set(filters) - {"with"}:
            raise InvalidToolArgument("filters", "Use only the supported search filters.")
        named_peer = filters.get("with")
        if peer is not None and named_peer is not None and peer != named_peer:
            raise InvalidToolArgument("with", "Peer filters must select the same participant.")
        peer = named_peer if named_peer is not None else peer
        for field, value, maximum in (("cursor", cursor, 2048), ("snapshot_id", snapshot_id, 512),
                                       ("with", peer, 512), ("conversation_id", conversation_id, 512)):
            if value is not None and (not isinstance(value, str) or not 1 <= len(value) <= maximum):
                raise InvalidToolArgument(field, "Use a bounded nonempty search reference.")

        def selected(bound, cur, _root, _command):
            address = self.project_service._communication_address(cur, project)
            chosen_peer = peer
            if chosen_peer is not None:
                try:
                    parse_handle(chosen_peer, "client" if chosen_peer.startswith("client:") else "collaborator", project)
                except ValueError as error:
                    raise InvalidToolArgument("with", "Use a participant address in this project.") from error
                if chosen_peer == address:
                    raise InvalidToolArgument("with", "Choose another participant for a direct pair filter.")
            if conversation_id is not None:
                own, actual_peer = self._conversation_peer(bound, cur, project, conversation_id)
                if own != address or chosen_peer is not None and chosen_peer != actual_peer:
                    raise InvalidToolArgument("conversation_id", "Conversation and peer filters must select the same pair.")
                chosen_peer = actual_peer
            binding = self._cursor_binding(bound, cur, project)
            query = digest({"kind": "search", "tenant": bound.tenant_id, "project": project,
                            "binding": binding, "actor": address, "q": q,
                            "peer": peer, "conversation_id": conversation_id})
            codec = Fernet(base64.urlsafe_b64encode(cursor_secret(cur.connection)))
            if cursor or snapshot_id:
                state = _search_state(codec, cursor or snapshot_id, query)
                if cursor and snapshot_id and _search_state(codec, snapshot_id, query)["high"] != state["high"]:
                    raise CommunicationHttpError("cursor_invalid", "Cursor and snapshot differ", status_code=409)
            else:
                cur.execute("SELECT COALESCE(MAX(c.sequence),0) FROM communication_messages c JOIN delivery_messages m "
                    "USING(tenant_id,message_id) WHERE c.tenant_id=%s AND c.project_id=%s AND (c.sender=%s OR c.recipient=%s) "
                    "AND m.packet_json->>'schema_version'='acs-message/1'",
                    (bound.tenant_id, project, address, address))
                state = {"query": query, "high": cur.fetchone()[0], "after": 0}
            # strpos has no wildcard/escape syntax. SQL never returns a foreign
            # body, an aggregate hit count, or an entire matching message body.
            cur.execute("WITH authorized AS (SELECT c.message_id,c.sequence,m.packet_json->>'content' content "
                "FROM communication_messages c JOIN delivery_messages m USING(tenant_id,message_id) "
                "WHERE c.tenant_id=%s AND c.project_id=%s AND (c.sender=%s OR c.recipient=%s) "
                "AND c.sequence>%s AND c.sequence<=%s AND m.packet_json->>'schema_version'='acs-message/1' "
                "AND (%s::text IS NULL OR c.sender=%s OR c.recipient=%s)), "
                "matches AS (SELECT message_id,sequence,content,strpos(content,%s) match_at FROM authorized) "
                "SELECT message_id,sequence,octet_length(left(content,GREATEST(match_at-%s,0))) "
                "FROM matches WHERE match_at>0 ORDER BY sequence LIMIT %s",
                (bound.tenant_id, project, address, address, state["after"], state["high"],
                 chosen_peer, chosen_peer, chosen_peer, q, CONTEXT_CHARACTERS + 1, limit + 1))
            rows = cur.fetchall()
            next_cursor = codec.encrypt(json.dumps(state | {"after": rows[limit - 1][1]}).encode()).decode() if len(rows) > limit else None
            snapshot = codec.encrypt(json.dumps(state | {"after": 0}).encode()).decode()
            references = [(handle("message", project, identifier), offset) for identifier, _sequence, offset in rows[:limit]]
            return references, {"next_cursor": next_cursor, "snapshot_id": snapshot}, state["high"], binding

        references, page, high, binding = self._transaction(project, "list_messages", selected)
        items = []
        for reference, offset in references:
            message = self.read_message(project, reference, offset=offset, max_inline_bytes=SNIPPET_BYTES, _high=high)["message"]
            body = message["content"]
            items.append({"message_handle": message["message_handle"], "conversation_id": message["conversation_id"],
                "snippet": body["text"], "matched_fields": ["content"],
                "content_truncated": body["offset"] > 0 or body["next_offset"] is not None,
                "committed_at": message["committed_at"]})

        def authorize_response(bound, cur, _root, _command):
            if self._cursor_binding(bound, cur, project) != binding:
                raise CommunicationHttpError("cursor_invalid", "Authorization changed; restart the search page", status_code=409)
            return {"items": items, "page": page}

        return self._validate("SearchHitPage", self._transaction(project, "list_messages", authorize_response))
