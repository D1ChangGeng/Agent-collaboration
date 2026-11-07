"""Authorized, opaque event replay over committed projection facts.

Each batch and each eventual emit authenticate again. No event read performs
Native input, marks state read, creates a reply or advances a business operation.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken

from runtime.communication_client_storage import cursor_secret
from runtime.communication_event_storage import KINDS, EventCursorExpired, read_event_records
from runtime.communication_http import CommunicationHttpError
from runtime.errors import AuthorizationDenied, InvalidToolArgument, NotFound
from runtime.project_common import digest, parse_handle

EVENT_CURSOR_TTL = 7 * 86400


@dataclass(frozen=True)
class EventBatch:
    events: tuple[dict, ...]
    after_cursor: str
    auth_revision: str
    has_more: bool


def encode_event_cursor(cursor, tenant, project, auth_revision, position, *, kinds=None, anchor=False):
    if type(position) is not int or not 0 <= position <= 2**63 - 1:
        raise ValueError("invalid event cursor position")
    value = {"v": 1, "n": digest([tenant, project]), "a": auth_revision, "s": position,
             "k": None if anchor else digest(list(kinds) if kinds is not None else None), "b": anchor}
    codec = Fernet(base64.urlsafe_b64encode(cursor_secret(cursor.connection)))
    return codec.encrypt(json.dumps(value, separators=(",", ":")).encode()).decode()


class ClientEventFeed:
    def _event_authorize(self, authority, cursor, project):
        last, first, revisions = None, None, {}
        bindings = {}
        for name in ("list_messages", "read_message", "list_harnesses", "check_inbox", "list_collaborators"):
            try:
                self.project_service._check_tool_policy(name)
                selected = self.project_service._authorize(authority, cursor, project, name, {"project_id": project})
                if first is None:
                    first = selected
                bound = selected[0]
                token = getattr(self.project_service, "token_authorization", None)
                access = getattr(token, "access", None)
                context = bound.context
                key = (context.tenant_id, context.authority_id, context.authority_incarnation,
                    context.principal_ref, context.grant_ref, context.agent_slot_id, context.trusted_client,
                    bound.access_mode, self.project_service.profile,
                    None if access is None else (access.subject, access.client_id, tuple(sorted(access.scopes))))
                if key not in bindings:
                    bindings[key] = self._cursor_binding(bound, cursor, project)
                revisions[name] = bindings[key]
            except (AuthorizationDenied, PermissionError) as error:
                last = error
        if first is None:
            raise last or AuthorizationDenied(self.project_service.context.principal_ref, self.project_service.context.grant_ref)
        return (*first, digest(revisions))

    def _event_transaction(self, project, callback):
        self.project_service.service.authenticate(self.credential)
        with self.authority.transaction() as (authority, connection), connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout='5s'")
            cursor.execute("SET LOCAL lock_timeout='1s'")
            bound, root, command, revision = self._event_authorize(authority, cursor, project)
            result = callback(bound, cursor, root, command, revision)
            self.project_service.service.authenticate(self.credential)
            _current, _root, _command, current_revision = self._event_authorize(authority, cursor, project)
            if current_revision != revision:
                raise CommunicationHttpError("permission_changed", "Authorization changed; take a new snapshot", status_code=409)
            return result

    def event_current(self, project, *, expected_auth_revision=None, event_id=None):
        def selected(bound, cursor, _root, _command, revision):
            if expected_auth_revision is not None and revision != expected_auth_revision:
                raise CommunicationHttpError("permission_changed", "Authorization changed; take a new snapshot", status_code=409)
            if event_id is not None:
                cursor.execute("SELECT event_id,kind,resource_ref,resource_revision,audience_kind,sender,recipient,actor_ref,scope_id,payload_json "
                    "FROM communication_event_intents WHERE tenant_id=%s AND project_id=%s AND event_id=%s AND published_sequence IS NOT NULL",
                    (bound.tenant_id, project, event_id))
                row = cursor.fetchone()
                fields = ("event_id", "kind", "resource_ref", "resource_revision", "audience_kind", "sender", "recipient", "actor_ref", "scope_id", "payload_json")
                if row is None or not self._event_visible(bound, cursor, project, dict(zip(fields, row, strict=True))):
                    raise CommunicationHttpError("permission_changed", "Event visibility changed; take a new snapshot", status_code=409)
            address = self.project_service._communication_address(cursor, project)
            return {"auth_revision": revision, "viewer_key": self._viewer_actor_ref(project, address), "address": address}
        return self._event_transaction(project, selected)

    def _event_kinds(self, kinds):
        if kinds is None:
            return None
        if not isinstance(kinds, (list, tuple)) or len(kinds) > len(KINDS) or any(type(kind) is not str or kind not in KINDS for kind in kinds):
            raise InvalidToolArgument("kinds", "Use supported event kinds.")
        if len(set(kinds)) != len(kinds) or not kinds:
            raise InvalidToolArgument("kinds", "Use distinct supported event kinds.")
        return tuple(sorted(kinds))

    def _decode_event_cursor(self, cursor, project, token, revision, kinds):
        if type(token) is not str or not 1 <= len(token) <= 2048:
            raise CommunicationHttpError("cursor_invalid", "Use a snapshot or saved event cursor", status_code=409)
        codec = Fernet(base64.urlsafe_b64encode(cursor_secret(cursor.connection)))
        try:
            value = json.loads(codec.decrypt(token.encode(), ttl=EVENT_CURSOR_TTL))
        except InvalidToken as error:
            raise CommunicationHttpError("cursor_expired", "Event cursor expired or unavailable; take a new snapshot", status_code=410) from error
        except (ValueError, TypeError, UnicodeError) as error:
            raise CommunicationHttpError("cursor_invalid", "Restart from an authorized snapshot", status_code=409) from error
        if (type(value) is not dict or value.get("v") != 1 or value.get("n") != digest([self.authority.tenant_id, project])
                or value.get("a") != revision or type(value.get("s")) is not int
                or not 0 <= value["s"] <= 2**63 - 1 or type(value.get("b")) is not bool):
            raise CommunicationHttpError("cursor_invalid", "Event cursor identity or authorization changed", status_code=409)
        selected = digest(list(kinds) if kinds is not None else None)
        if (value["b"] and value.get("k") is not None) or (not value["b"] and value.get("k") != selected):
            raise CommunicationHttpError("cursor_invalid", "Event cursor filter changed; take a new snapshot", status_code=409)
        return value["s"]

    def _event_visible(self, bound, cursor, project, record):
        address = self.project_service._communication_address(cursor, project)
        audience = record["audience_kind"]
        try:
            if audience == "message":
                self.project_service._check_tool_policy("read_message")
                current, _root, _command = self.project_service._authorize(bound, cursor, project, "read_message", {"project_id": project})
                identifier = parse_handle(record["resource_ref"], "message", project)
                cursor.execute("SELECT sender,recipient FROM communication_messages WHERE tenant_id=%s AND project_id=%s AND message_id=%s",
                               (bound.tenant_id, project, identifier))
                row = cursor.fetchone()
                if row is None:
                    return False
                self.project_service._communication_participant(current, cursor, project, *row)
                return row == (record["sender"], record["recipient"])
            if audience == "private":
                if record["actor_ref"] != self._viewer_actor_ref(project, address) or record["recipient"] not in {None, address}:
                    return False
                self.project_service._check_tool_policy("read_message")
                current, root, _command = self.project_service._authorize(bound, cursor, project, "read_message", {"project_id": project})
                if record["kind"] == "attachment.ready":
                    from runtime.communication_attachment_storage import get_attachment

                    if (not getattr(self.authority, "_communication_attachments_enabled", False)
                            or getattr(self.authority, "_communication_attachment_settings", None) is None):
                        return False
                    get_attachment(cursor, self._attachment_owner(current, cursor, root, project), record["resource_ref"])
                    return True
                self._conversation_peer(current, cursor, project, record["payload_json"].get("conversation_id", record["resource_ref"]))
                return True
            if audience == "conversation":
                if record["recipient"] != address or record["actor_ref"] not in {None, self._viewer_actor_ref(project, address)}:
                    return False
                self.project_service._check_tool_policy("read_message")
                current, _root, _command = self.project_service._authorize(bound, cursor, project, "read_message", {"project_id": project})
                own, peer = self._conversation_peer(current, cursor, project, record["resource_ref"])
                return own == address and (record["sender"] is None or peer == record["sender"])
            if audience == "notice":
                if record["recipient"] != address or record["actor_ref"] not in {None, self.project_service.context.principal_ref}:
                    return False
                self.project_service._check_tool_policy("check_inbox")
                self.project_service._authorize(bound, cursor, project, "check_inbox", {"project_id": project})
                self._notice_row(bound, cursor, project, record["resource_ref"], address)
                return True
            if audience == "receiver":
                self.project_service._check_tool_policy("list_harnesses")
                current, root, command = self.project_service._authorize(bound, cursor, project, "list_harnesses", {"project_id": project})
                if record["kind"] == "native_link.changed":
                    return self._native_link_event_visible(current, cursor, root, project, command,
                                                           record["resource_ref"], record["scope_id"])
                return any(row["scope_id"] == record["scope_id"] for row in self._receiver_records(current, cursor, root, project, record["resource_ref"]))
            if audience == "control":
                return (record["resource_ref"] is None and record["resource_revision"] == 0
                    and record["actor_ref"] in {None, self.project_service.context.principal_ref, self._viewer_actor_ref(project, address)}
                    and set(record["payload_json"]) <= {"reason_code", "reset_required"})
        except (AuthorizationDenied, PermissionError, NotFound, InvalidToolArgument, ValueError):
            return False
        return False

    def event_batch(self, project, *, after_cursor, kinds=None, limit=100):
        kinds = self._event_kinds(kinds)
        if type(limit) is not int or not 1 <= limit <= 256:
            raise InvalidToolArgument("limit", "Use an event batch limit between 1 and 256.")

        def selected(bound, cursor, _root, _command, revision):
            after = self._decode_event_cursor(cursor, project, after_cursor, revision, kinds)
            try:
                records = read_event_records(cursor, bound.tenant_id, project, after=after, limit=limit)
            except EventCursorExpired as error:
                raise CommunicationHttpError("cursor_expired", "Event history expired; take a new snapshot", status_code=410) from error
            except ValueError as error:
                raise CommunicationHttpError("cursor_invalid", "Event cursor does not belong to this replay boundary", status_code=409) from error
            events = []
            for record in records:
                after = record["sequence"]
                if kinds is not None and record["kind"] not in kinds or not self._event_visible(bound, cursor, project, record):
                    continue
                token = encode_event_cursor(cursor, bound.tenant_id, project, revision, after, kinds=kinds)
                events.append(self._validate("Event", {"schema_version": "acs-event/1", "event_id": record["event_id"],
                    "cursor": token, "project_id": project, "kind": record["kind"], "resource_ref": record["resource_ref"],
                    "resource_revision": record["resource_revision"], "committed_at": record["committed_at"].isoformat(),
                    "auth_revision": revision, "payload": record["payload_json"]}))
            token = encode_event_cursor(cursor, bound.tenant_id, project, revision, after, kinds=kinds)
            return EventBatch(tuple(events), token, revision, len(records) == limit)
        return self._event_transaction(project, selected)
