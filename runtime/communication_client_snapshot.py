"""Short RR metadata cut, frozen pages and fresh post-cut authorization."""
from __future__ import annotations

import base64
import json
from copy import copy

from cryptography.fernet import Fernet, InvalidToken
from psycopg.errors import DeadlockDetected, SerializationFailure

from runtime.communication_client_events import encode_event_cursor
from runtime.communication_client_storage import cursor_secret
from runtime.communication_event_storage import stream_high_water
from runtime.communication_http import CommunicationHttpError
from runtime.communication_snapshot_storage import (
    SnapshotCorrupt,
    SnapshotExpired,
    SnapshotIdentity,
    SnapshotLimits,
    SnapshotMismatch,
    SnapshotQuotaExceeded,
    read_snapshot_page,
    save_snapshot,
    snapshot_filter_digest,
)
from runtime.errors import AuthorizationDenied, InvalidToolArgument
from runtime.receiver_evidence import unknown_receiver

FAMILY_TOOLS = {"contacts": "list_collaborators", "conversations": "list_messages", "receivers": "list_harnesses"}
FILTERS = {"include_archived": False}
PAGE_PREFIX = "snapshot-page."


def is_materialized_page(snapshot_id, cursor):
    return (isinstance(snapshot_id, str) and snapshot_id.startswith("snapshot-")) or (isinstance(cursor, str) and cursor.startswith(PAGE_PREFIX))


class ClientSnapshotService:
    def _snapshot_enabled(self):
        if not getattr(self.authority, "_communication_events_enabled", False):
            raise CommunicationHttpError("capability_unsupported", "Consistent snapshots are not enabled.", status_code=409)

    def _snapshot_facade(self, bound):
        shared = copy(self.project_service.service)
        shared.authority = bound
        projects = copy(self.project_service)
        projects.service = shared
        facade = copy(self)
        facade.authority, facade.project_service = bound, projects
        return facade

    def _snapshot_families(self, authority, cursor, project):
        allowed = {}
        for family, name in FAMILY_TOOLS.items():
            try:
                self.project_service._check_tool_policy(name)
                allowed[family] = self.project_service._authorize(authority, cursor, project, name, {"project_id": project})
            except (AuthorizationDenied, PermissionError):
                continue
        return allowed

    def _snapshot_identity(self, bound, cursor, project, revision):
        address = self.project_service._communication_address(cursor, project)
        return SnapshotIdentity(bound.tenant_id, project, self._viewer_actor_ref(project, address), revision, snapshot_filter_digest(FILTERS))

    def _snapshot_token(self, cursor, identity, ref, family, offset):
        codec = Fernet(base64.urlsafe_b64encode(cursor_secret(cursor.connection)))
        value = {"r": ref, "f": family, "o": offset, "a": identity.auth_revision, "q": identity.filter_digest}
        return PAGE_PREFIX + codec.encrypt(json.dumps(value, separators=(",", ":")).encode()).decode()

    def _snapshot_failure(self, error):
        if isinstance(error, SnapshotExpired):
            return CommunicationHttpError("snapshot_expired", "Snapshot expired or unavailable; capture a new view.", status_code=410)
        if isinstance(error, SnapshotMismatch):
            return CommunicationHttpError("snapshot_invalid", "Snapshot authorization or filters changed.", status_code=409)
        if isinstance(error, SnapshotQuotaExceeded):
            return CommunicationHttpError("snapshot_quota_exceeded", "Snapshot cache budget exceeded.", status_code=429, retryable=True, retry_after=5)
        return CommunicationHttpError("snapshot_unavailable", "Snapshot integrity is unavailable; capture a new view.", status_code=503)

    def snapshot(self, project, *, limit=50):
        self._snapshot_enabled()
        if type(limit) is not int or not 1 <= limit <= 100:
            raise InvalidToolArgument("limit", "Use a snapshot page limit between 1 and 100.")
        budgets = getattr(self.authority, "_communication_snapshot_limits", None) or SnapshotLimits()

        def probe(bound, cursor, root, _command, revision):
            families = self._snapshot_families(bound, cursor, project)
            receiver_context = families.get("receivers")
            records = []
            if receiver_context:
                records = self._receiver_records(receiver_context[0], cursor, receiver_context[1], project)
            if len(records) > budgets.max_items:
                raise SnapshotQuotaExceeded("snapshot receiver budget exceeded")
            return revision, records

        try:
            for attempt in range(3):
                revision, selected_receivers = self._event_transaction(project, probe)
                # The observation budget is one response page. Remaining rows
                # are explicitly unmeasured, never guessed as ready/connected.
                observations = {row["endpoint_id"]: self._observe_receiver(project, row) for row in selected_receivers[:limit]}
                if observations:
                    observations = self._persist_receiver_batch(project, selected_receivers[:limit], observations)
                try:
                    with self.authority.transaction() as (authority, connection), connection.cursor() as cursor:
                        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                        cursor.execute("SET LOCAL statement_timeout='10s'")
                        cursor.execute("SET LOCAL lock_timeout='1s'")
                        facade = self._snapshot_facade(authority)
                        _bound, _root, _command, cut_revision = facade._event_authorize(authority, cursor, project)
                        if cut_revision != revision:
                            raise SnapshotMismatch("snapshot authorization changed before cut")
                        families = facade._snapshot_families(authority, cursor, project)
                        receiver_context = families.get("receivers")
                        current_receivers = facade._receiver_records(receiver_context[0], cursor, receiver_context[1], project) if receiver_context else []
                        if current_receivers != selected_receivers:
                            raise SnapshotMismatch("snapshot receiver selection changed before cut")
                        pages = {family: [] for family in FAMILY_TOOLS}
                        for family in ("contacts", "conversations"):
                            if family not in families:
                                continue
                            next_cursor = None
                            while True:
                                value = getattr(facade, family)(project, limit=100, cursor=next_cursor)
                                pages[family].extend(value["items"])
                                if sum(map(len, pages.values())) + len(current_receivers) > budgets.max_items:
                                    raise SnapshotQuotaExceeded("snapshot item budget exceeded")
                                next_cursor = value["page"]["next_cursor"]
                                if next_cursor is None:
                                    break
                        now = authority.canonical_now(cursor)
                        for row in current_receivers:
                            observed = observations.get(row["endpoint_id"])
                            if (getattr(authority, "_communication_receiver_observation_available", False)
                                    or getattr(authority, "_communication_events_enabled", False)):
                                from runtime.communication_receiver_observation_storage import (
                                    read_receiver_observation,
                                )

                                observed = read_receiver_observation(cursor, authority.tenant_id, project, row, now)
                            value = (observed.current(now, scope=observed.capability_scope) if observed is not None else
                                unknown_receiver(facade._receiver_binding(project, row), reason="snapshot_observation_not_requested"))
                            if not getattr(authority, "_receiver_evidence_enabled", False):
                                value = unknown_receiver(facade._receiver_binding(project, row), reason="receiver_evidence_disabled").model_copy(update={"revision": value.revision})
                            pages["receivers"].append(value.model_copy(update={"allowed_actions": ("inspect",)}).model_dump(mode="json"))
                        actor = facade.profile()
                        actor["auth_revision"] = cut_revision
                        address = facade.project_service._communication_address(cursor, project)
                        principal = facade.project_service.context.principal_ref
                        try:
                            facade.project_service._check_tool_policy("check_inbox")
                            facade.project_service._authorize(authority, cursor, project, "check_inbox", {"project_id": project})
                            cursor.execute("SELECT count(*) FROM communication_notices n LEFT JOIN communication_client_notice_seen s "
                                "ON (s.tenant_id,s.project_id,s.message_id,s.recipient)=(n.tenant_id,n.project_id,n.message_id,n.recipient) "
                                "AND s.actor_ref=%s WHERE n.tenant_id=%s AND n.project_id=%s AND n.recipient=%s AND NOT COALESCE(s.seen,FALSE)",
                                (principal, authority.tenant_id, project, address))
                            notice_count = cursor.fetchone()[0]
                        except (AuthorizationDenied, PermissionError):
                            notice_count = 0
                        high = stream_high_water(cursor, authority.tenant_id, project)
                        identity = facade._snapshot_identity(authority, cursor, project, cut_revision)
                        meta = save_snapshot(cursor, identity, {"actor": actor, "notice_count": notice_count}, pages,
                                             high_water=high, limits=budgets)
                        first_pages = {family: read_snapshot_page(cursor, identity, meta["snapshot_ref"], family, limit=limit)
                                       for family in FAMILY_TOOLS}
                        result = {"snapshot_id": meta["snapshot_ref"], "snapshot_expires_at": meta["expires_at"],
                            "after_cursor": encode_event_cursor(cursor, authority.tenant_id, project, cut_revision, high, anchor=True),
                            "auth_revision": cut_revision, "actor": actor, "notice_count": notice_count,
                            **{family: page["items"] for family, page in first_pages.items()},
                            "pages": {family + "_cursor": facade._snapshot_token(cursor, identity, meta["snapshot_ref"], family, page["next_offset"])
                                      if page["next_offset"] is not None else None for family, page in first_pages.items()}}
                    # RR cannot see a later revocation. No cached payload is
                    # returned until current authority has been checked anew.
                    self.event_current(project, expected_auth_revision=cut_revision)
                    for family in families:
                        checked = self.snapshot_page(project, family, limit=limit, snapshot_id=meta["snapshot_ref"])
                        result[family] = checked["items"]
                        result["pages"][family + "_cursor"] = checked["page"]["next_cursor"]
                    return self._validate("Snapshot", result)
                except (SerializationFailure, DeadlockDetected):
                    if attempt == 2:
                        raise CommunicationHttpError("snapshot_busy", "Snapshot admission raced; retry a fresh view.", status_code=503, retryable=True) from None
        except (SnapshotExpired, SnapshotMismatch, SnapshotQuotaExceeded, SnapshotCorrupt) as error:
            raise self._snapshot_failure(error) from error

    def snapshot_page(self, project, family, *, limit=50, cursor=None, snapshot_id=None):
        self._snapshot_enabled()
        if family not in FAMILY_TOOLS:
            raise InvalidToolArgument("family", "Use a supported snapshot family.")

        def selected(bound, cur, _root, _command, revision):
            identity = self._snapshot_identity(bound, cur, project, revision)
            offset, ref = 0, snapshot_id
            if cursor is not None:
                try:
                    if not cursor.startswith(PAGE_PREFIX):
                        raise ValueError("wrong page token")
                    codec = Fernet(base64.urlsafe_b64encode(cursor_secret(cur.connection)))
                    state = json.loads(codec.decrypt(cursor[len(PAGE_PREFIX):].encode(), ttl=300))
                    if state["f"] != family or state["a"] != revision or state["q"] != identity.filter_digest:
                        raise SnapshotMismatch("page binding changed")
                    if ref is not None and ref != state["r"]:
                        raise SnapshotMismatch("page and snapshot differ")
                    ref, offset = state["r"], state["o"]
                except InvalidToken as error:
                    raise SnapshotExpired("snapshot page expired") from error
                except (ValueError, TypeError, KeyError, AttributeError) as error:
                    raise SnapshotMismatch("invalid snapshot page") from error
            self.project_service._check_tool_policy(FAMILY_TOOLS[family])
            current, root, command = self.project_service._authorize(bound, cur, project, FAMILY_TOOLS[family], {"project_id": project})
            page = read_snapshot_page(cur, identity, ref, family, offset=offset, limit=limit)
            if family == "receivers":
                visible = {row["endpoint_id"]: row for row in self._receiver_records(current, cur, root, project)}
                for item in page["items"]:
                    row = visible.get(item["receiver_id"])
                    if row is None or row["revision"] != item["binding_epoch"]:
                        raise SnapshotMismatch("cached receiver is no longer in the authorized binding")
            elif family == "contacts":
                visible, next_cursor = set(), None
                while True:
                    _state, contacts, _actions = self.project_service._list_collaborators(current, cur, root, command,
                        {"project_id": project, "limit": 100, "cursor": next_cursor}, self.credential)
                    visible.update(row["collaborator_handle"] for row in contacts["items"])
                    next_cursor = contacts["next_cursor"]
                    if next_cursor is None:
                        break
                if any(item["address"] not in visible for item in page["items"]):
                    raise SnapshotMismatch("cached contact is no longer visible")
            else:
                for item in page["items"]:
                    self._conversation_peer(current, cur, project, item["conversation_id"])
            return {"items": page["items"], "page": {"snapshot_id": ref,
                "next_cursor": self._snapshot_token(cur, identity, ref, family, page["next_offset"]) if page["next_offset"] is not None else None}}
        try:
            result = self._event_transaction(project, selected)
            return self._validate({"contacts": "ContactPage", "conversations": "ConversationPage", "receivers": "ReceiverPage"}[family], result)
        except (SnapshotExpired, SnapshotMismatch, SnapshotQuotaExceeded, SnapshotCorrupt) as error:
            raise self._snapshot_failure(error) from error
