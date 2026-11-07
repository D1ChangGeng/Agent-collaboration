"""Recipient-only system notices and explicit private seen state.

System notice ownership is distinct from participation in its original private
message. This projection never reads that message's body or reply relationship.
Any Native receipt belongs to the separately queued notice delivery itself.
"""
from __future__ import annotations

import base64
import json
import re
from datetime import UTC, datetime

from cryptography.fernet import Fernet

from runtime.communication_client_storage import cursor_secret
from runtime.communication_client_views import client_page_state, client_snapshot_token
from runtime.communication_http import CommunicationHttpError
from runtime.errors import InvalidToolArgument, NotFound
from runtime.project_common import digest, handle, parse_handle

_SUMMARIES = {
    "blocked": "An ACS communication delivery was blocked.",
    "uncertain": "The Native delivery outcome could not be confirmed.",
    "expired": "An ACS communication delivery deadline expired.",
    "budget_exhausted": "An ACS communication delivery exhausted its attempt budget.",
}
_REASON_CODES = frozenset({
    "delivery_unconfirmed", "native_pre_call_rejected", "native_outcome_uncertain",
    "post_dispatch_result_uncertain", "receiver_unavailable", "manager_receiver_unavailable",
    "manager_authorization_unavailable", "deadline_expired", "delivery_deadline_expired",
    "attempt_budget_exhausted", "budget_exhausted", "grant_revoked", "authorization_denied",
    "binding_changed", "endpoint_binding_missing", "endpoint_binding_ambiguous", "endpoint_unavailable",
    "native_ack_unconfirmed", "manager_delivery_unconfirmed", "native_result_uncertain",
    "native_unavailable", "driver_unavailable", "remote_readback_unavailable",
    "notice_delivery_binding_unconfirmed",
})


def _reason(value):
    return value if value in _REASON_CODES else "delivery_unconfirmed"


def _created_at(value):
    if value is None or isinstance(value, str):
        return value
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("notice creation time must be an aware source timestamp")
    return value.astimezone(UTC).isoformat()


def _notice_sequence(project, reference):
    try:
        identifier = parse_handle(reference, "notification", project)
        sequence = identifier.removeprefix("communication-")
        if (identifier == sequence or not sequence.isascii() or not sequence.isdecimal()
                or sequence.startswith("0") or not 1 <= int(sequence) <= 2**63 - 1):
            raise ValueError("invalid system notice sequence")
        return int(sequence)
    except (AttributeError, ValueError) as error:
        raise InvalidToolArgument("notice_handle", "Use a current ACS system notice handle in this project.") from error


class NoticeQueryService:
    """Mixin using the host's current authentication and ProjectService ACL."""

    def _notice_row(self, bound, cursor, project, reference, address):
        try:
            identifier = parse_handle(reference, "notification", project)
        except (AttributeError, ValueError) as error:
            raise InvalidToolArgument("notice_handle", "Use an authorized system notice reference in this project.") from error
        opaque = re.fullmatch(r"notice-[a-f0-9]{32}", identifier) is not None
        sequence = None if opaque else _notice_sequence(project, reference)
        cursor.execute("SELECT n.message_id,n.sequence,n.state,n.code,r.native_requested,r.delivery_message_id,r.last_error "
            "FROM communication_notices n LEFT JOIN communication_notice_routes r "
            "USING(tenant_id,project_id,message_id,recipient) "
            "LEFT JOIN communication_client_notice_versions v USING(tenant_id,project_id,message_id,recipient) "
            "WHERE n.tenant_id=%s AND n.project_id=%s AND n.recipient=%s "
            "AND ((%s AND v.notice_ref=%s) OR (NOT %s AND n.sequence=%s))",
            (bound.tenant_id, project, address, opaque, identifier, opaque, sequence))
        row = cursor.fetchone()
        if row is None:
            raise NotFound("notification", reference)
        return row

    def _notice_identity(self, bound, project, row, address):
        from runtime.communication_client_notice_storage import NoticeStateIdentity

        return NoticeStateIdentity(bound.tenant_id, project, self.project_service.context.principal_ref,
                                   row[0], address)

    def _notice_own_delivery(self, bound, cursor, project, row, address):
        requested, delivery_id, route_error = row[4:7]
        if requested is None:
            return None  # A legacy/missing route supplies no Native fact.
        empty = {"operation_ref": None, "binding_epoch": None, "provider_generation": None,
                 "evidence_ref": None, "native_input_ref": None, "reason_code": None}
        if delivery_id is None:
            return empty | {"state": "pending" if requested else "not_requested",
                            "reason_code": _reason(route_error) if route_error else None}
        cursor.execute("SELECT operation_id,state,binding_revision,last_error,receipt_high_water,"
            "packet_json->>'schema_version',packet_json->>'project_id',packet_json->>'origin_message_id',"
            "packet_json->>'recipient' FROM delivery_messages WHERE tenant_id=%s AND message_id=%s",
            (bound.tenant_id, delivery_id))
        delivery = cursor.fetchone()
        if delivery is None or delivery[5:] != ("acs-notice/1", project, row[0], address):
            return empty | {"state": "unknown", "reason_code": "notice_delivery_binding_unconfirmed"}
        operation, state, epoch, error, high = delivery[:5]
        cursor.execute("SELECT receipt_id FROM delivery_receipts WHERE tenant_id=%s AND message_id=%s "
                       "AND layer='runtime_acknowledged'", (bound.tenant_id, delivery_id))
        ack = cursor.fetchone()
        phase = ("accepted" if ack else {"queued": "pending", "retry_wait": "deferred", "delivering": "submitting",
                 "blocked": "rejected", "expired": "rejected", "budget_exhausted": "rejected"}.get(state, "unknown"))
        if not ack and high in {"runtime_dispatched", "runtime_acknowledged"} and error != "native_pre_call_rejected":
            phase = "unknown"
        return empty | {"state": phase, "operation_ref": operation, "binding_epoch": epoch,
            "evidence_ref": ack[0] if ack else None,
            "reason_code": None if ack else _reason(error) if error else "native_ack_unconfirmed" if state == "delivered" else None}

    def _notice_dto(self, bound, cursor, project, row, address, seen, seen_revision, source_revision, created_at):
        from runtime.communication_client_notice_storage import notice_public_ref

        public = notice_public_ref(cursor, self._notice_identity(bound, project, row, address))
        revision = source_revision + seen_revision
        if (getattr(self.authority, "_communication_notice_projection_available", False)
                or getattr(self.authority, "_communication_events_enabled", False)):
            from runtime.communication_notice_projection_storage import notice_projection_revision

            revision = notice_projection_revision(cursor, self._notice_identity(bound, project, row, address))
        return self._validate("Notice", {
            "notice_handle": handle("notification", project, public),
            "source": "acs_system", "kind": "communication_obstacle",
            "message_ref": handle("message", project, row[0]),
            # The old notice source stores a Slot, not an immutable failed
            # endpoint epoch. Current original/notice endpoints cannot fill it.
            "receiver_ref": None, "reason_code": _reason(row[3]),
            "summary": _SUMMARIES.get(row[2], "An ACS communication delivery requires attention."),
            "own_delivery": self._notice_own_delivery(bound, cursor, project, row, address),
            "seen": seen, "revision": revision, "created_at": _created_at(created_at)})

    def _notice(self, bound, cursor, project, reference, address):
        from runtime.communication_client_notice_storage import (
            read_notice_metadata,
            read_notice_seen,
        )

        row = self._notice_row(bound, cursor, project, reference, address)
        identity = self._notice_identity(bound, project, row, address)
        source_revision, created_at = read_notice_metadata(cursor, identity)
        if (getattr(self.authority, "_communication_notice_projection_available", False)
                or getattr(self.authority, "_communication_events_enabled", False)):
            from runtime.communication_notice_projection_storage import sync_notice_projection

            sync_notice_projection(cursor, identity)
        # Source/technical versions are now frozen; reread the owning route.
        row = self._notice_row(bound, cursor, project, reference, address)
        seen, seen_revision = read_notice_seen(cursor, identity)
        return self._notice_dto(bound, cursor, project, row, address, seen, seen_revision, source_revision, created_at)

    def notice(self, project, notice_ref):
        def selected(bound, cursor, _root, _command):
            address = self.project_service._communication_address(cursor, project)
            return self._notice(bound, cursor, project, notice_ref, address)
        return self._transaction(project, "check_inbox", selected)

    def notices(self, project, *, limit=50, cursor=None, snapshot_id=None, seen=None):
        if type(limit) is not int or not 1 <= limit <= 100 or seen is not None and type(seen) is not bool:
            raise InvalidToolArgument("limit", "Use a bounded notice page and an optional boolean seen filter.")

        def selected(bound, cur, _root, _command):
            from runtime.communication_client_notice_storage import notice_page_version

            address = self.project_service._communication_address(cur, project)
            actor = self.project_service.context.principal_ref
            query = digest({"kind": "notices", "project": project, "seen": seen,
                            "authorization": self._cursor_binding(bound, cur, project)})
            version = notice_page_version(cur, bound.tenant_id, project, address, actor)
            codec = Fernet(base64.urlsafe_b64encode(cursor_secret(cur.connection)))
            if cursor or snapshot_id:
                state = client_page_state(codec, cursor or snapshot_id, query)
                if state.get("version") != version:
                    raise CommunicationHttpError("cursor_invalid", "Notice state changed; restart the notice page", status_code=409)
                if cursor and snapshot_id:
                    original = client_page_state(codec, snapshot_id, query)
                    if (original["high"], original.get("version")) != (state["high"], version):
                        raise CommunicationHttpError("cursor_invalid", "Cursor and notice snapshot differ", status_code=409)
            else:
                cur.execute("SELECT COALESCE(MAX(sequence),0) FROM communication_notices "
                    "WHERE tenant_id=%s AND project_id=%s AND recipient=%s", (bound.tenant_id, project, address))
                state = {"query": query, "high": cur.fetchone()[0], "after": 0, "version": version}
            snapshot = client_snapshot_token(codec, snapshot_id, query, state, position="after", initial=0)
            items, after, more, last_included = [], state["after"], False, None
            while not more:
                cur.execute("SELECT sequence FROM communication_notices WHERE tenant_id=%s AND project_id=%s "
                    "AND recipient=%s AND sequence>%s AND sequence<=%s ORDER BY sequence LIMIT 101",
                    (bound.tenant_id, project, address, after, state["high"]))
                rows = cur.fetchall()
                for (sequence,) in rows:
                    item = self._notice(bound, cur, project, handle("notification", project, "communication-" + str(sequence)), address)
                    after = sequence
                    if seen is None or item["seen"] is seen:
                        if len(items) == limit:
                            more = True
                            break
                        items.append(item)
                        last_included = sequence
                if len(rows) < 101:
                    break
            next_cursor = codec.encrypt(json.dumps(state | {"after": last_included}).encode()).decode() if more else None
            if notice_page_version(cur, bound.tenant_id, project, address, actor) != version:
                raise CommunicationHttpError("cursor_invalid", "Notice state changed during this page", status_code=409)
            return self._validate("NoticePage", {"items": items, "page": {"next_cursor": next_cursor, "snapshot_id": snapshot}})
        return self._transaction(project, "check_inbox", selected)

    def mark_notice_seen(self, project, notice_ref, body, *, expected_revision, client_request_id):
        body = self._validate("SeenWrite", body)

        def selected(bound, cursor, _root, _command):
            from runtime.communication_client_notice_storage import write_notice_seen

            address = self.project_service._communication_address(cursor, project)
            row = self._notice_row(bound, cursor, project, notice_ref, address)
            identity = self._notice_identity(bound, project, row, address)

            def projected(seen, seen_revision, source_revision, created_at):
                current = self._notice_row(bound, cursor, project, notice_ref, address)
                return self._notice_dto(bound, cursor, project, current, address, seen, seen_revision, source_revision, created_at)

            revision_reader = None
            if (getattr(self.authority, "_communication_notice_projection_available", False)
                    or getattr(self.authority, "_communication_events_enabled", False)):
                from runtime.communication_notice_projection_storage import notice_cas_revision

                revision_reader = notice_cas_revision
            return write_notice_seen(cursor, identity, body["seen"], expected_revision=expected_revision,
                client_request_id=self._private_request_key(project, address, "notice.seen", client_request_id),
                project_result=projected, revision_reader=revision_reader)
        return self._transaction(project, "check_inbox", selected)
