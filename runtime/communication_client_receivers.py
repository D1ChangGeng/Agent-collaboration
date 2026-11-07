"""Authorized receiver evidence, without lifecycle actions or message access.

Endpoint selection follows list_harnesses. Native facts use its existing strict
receiver projection, outside the authorization transaction, then live authority,
selection and freshness are checked again before a DTO is returned.
"""
from __future__ import annotations

import base64
import json

from cryptography.fernet import Fernet

from runtime.communication_client_storage import cursor_secret
from runtime.communication_client_views import client_page_state, client_snapshot_token
from runtime.communication_http import CommunicationHttpError
from runtime.communication_receiver_observation_storage import current_receiver_observation
from runtime.errors import NotFound
from runtime.project_common import digest, handle
from runtime.receiver_contract import ReceiverBinding
from runtime.receiver_evidence import project_receiver, unknown_receiver

ENDPOINT_FIELDS = ("endpoint_id", "agent_slot_id", "scope_id", "machine_id", "node_id",
                   "revision", "supports_invoke", "boot_incarnation", "expires_at")
SELECTION_FIELDS = ("machine_id", "node_id", "boot_incarnation", "scope_id", "agent_slot_id")


class ReceiverQueryService:
    """Mixin using CommunicationClientService's authenticated transaction API."""

    def _receiver_records(self, bound, cursor, root, project, reference=None):
        scopes = self.project_service._visible_scopes(bound, cursor, root)
        cursor.execute("SELECT e.endpoint_id,e.agent_slot_id,e.scope_id,e.machine_id,e.node_id,e.revision,"
            "e.supports_invoke,e.boot_incarnation,e.expires_at FROM delivery_endpoints e "
            "WHERE e.tenant_id=%s AND e.status='active' AND (%s OR e.expires_at>clock_timestamp()) "
            "AND (%s::text IS NULL OR e.endpoint_id=%s) AND (%s::text[] IS NULL OR e.scope_id=ANY(%s)) "
            "AND (e.scope_id=%s OR EXISTS (SELECT 1 FROM collaboration_routes r "
            "WHERE r.tenant_id=e.tenant_id AND r.project_id=%s AND r.scope_id=e.scope_id)) ORDER BY e.endpoint_id",
            (bound.tenant_id, bound.access_mode == "owner", reference, reference, scopes, scopes, root[0], project))
        return [dict(zip(ENDPOINT_FIELDS, (*row[:-1], row[-1].isoformat() if row[-1] else None), strict=True))
                for row in cursor.fetchall()]

    def _receiver_binding(self, project, record):
        context = self.project_service.context
        return ReceiverBinding(receiver_id=record["endpoint_id"],
            actor_address=handle("collaborator", project, record["agent_slot_id"]), binding_epoch=record["revision"],
            provider_generation=None, native_session_ref=None, authority_id=context.authority_id,
            authority_incarnation=context.authority_incarnation, execution_host_ref=record["machine_id"])

    def _observe_receiver(self, project, record):
        binding = self._receiver_binding(project, record)
        if not getattr(self.authority, "_receiver_evidence_enabled", False):
            return unknown_receiver(binding, reason="receiver_evidence_disabled")
        provider = getattr(self.authority, "_delivery_endpoints", {}).get(record["endpoint_id"])
        return project_receiver(provider, binding, self.authority.canonical_now,
            expected_node={field: record[field] for field in SELECTION_FIELDS})

    def _persist_receiver_observation(self, bound, cursor, project, record, snapshot):
        if (getattr(self.authority, "_communication_receiver_observation_available", False)
                or getattr(self.authority, "_communication_events_enabled", False)):
            from runtime.communication_receiver_observation_storage import (
                record_receiver_observation,
            )

            return record_receiver_observation(cursor, bound.tenant_id, project, record, snapshot)
        return snapshot

    def _persist_receiver_batch(self, project, records, observations):
        def selected(bound, cursor, root, _command):
            visible = {row["endpoint_id"]: row for row in self._receiver_records(bound, cursor, root, project)}
            result = {}
            for record in records:
                if visible.get(record["endpoint_id"]) != record:
                    raise CommunicationHttpError("snapshot_invalid", "Receiver binding changed before the snapshot cut.", status_code=409)
                result[record["endpoint_id"]] = self._persist_receiver_observation(bound, cursor, project, record, observations[record["endpoint_id"]])
            return result
        return self._transaction(project, "list_harnesses", selected)

    def receivers(self, project, *, limit=50, cursor=None, snapshot_id=None):
        from runtime.communication_client_snapshot import is_materialized_page

        if is_materialized_page(snapshot_id, cursor):
            return self.snapshot_page(project, "receivers", limit=limit, cursor=cursor, snapshot_id=snapshot_id)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise CommunicationHttpError("invalid_argument", "Invalid receiver page limit")
        for token in (cursor, snapshot_id):
            if token is not None and (type(token) is not str or not 1 <= len(token) <= 512):
                raise CommunicationHttpError("cursor_invalid", "Invalid receiver page token", status_code=409)

        def select(bound, cur, root, _command):
            records = self._receiver_records(bound, cur, root, project)
            address = self.project_service._communication_address(cur, project)
            context = self.project_service.context
            authorization = self._cursor_binding(bound, cur, project)
            query = digest({"kind": "receivers", "tenant": bound.tenant_id, "project": project, "actor": address,
                "principal": context.principal_ref, "grant": context.grant_ref, "profile": self.project_service.profile,
                "trusted_client": context.trusted_client, "authorization": authorization,
                "receiver_evidence": bool(getattr(self.authority, "_receiver_evidence_enabled", False))})
            version = digest(records)
            codec = Fernet(base64.urlsafe_b64encode(cursor_secret(cur.connection)))
            state = client_page_state(codec, cursor or snapshot_id, query) if cursor or snapshot_id else {
                "query": query, "version": version, "after": 0}
            if (state.get("version") != version or type(state.get("after")) is not int
                    or not 0 <= state["after"] <= len(records)):
                raise CommunicationHttpError("cursor_invalid", "Receiver metadata changed; restart the page", status_code=409)
            if cursor and snapshot_id:
                original = client_page_state(codec, snapshot_id, query)
                if original.get("version") != version or original.get("after") != 0:
                    raise CommunicationHttpError("cursor_invalid", "Receiver cursor and snapshot differ", status_code=409)

            def token(after):
                return codec.encrypt(json.dumps({"query": query, "version": version, "after": after},
                                                separators=(",", ":")).encode()).decode()

            end = state["after"] + limit
            return records[state["after"]:end], version, authorization, {
                "next_cursor": token(end) if end < len(records) else None,
                "snapshot_id": client_snapshot_token(codec, snapshot_id, query, state, position="after", initial=0)}

        records, version, authorization, page = self._transaction(project, "list_harnesses", select)
        # No DB transaction or writer lock is held during any provider readback.
        observations = [self._observe_receiver(project, record) for record in records]

        def finish(bound, cur, root, _command):
            if (digest(self._receiver_records(bound, cur, root, project)) != version
                    or self._cursor_binding(bound, cur, project) != authorization):
                raise CommunicationHttpError("cursor_invalid", "Receiver metadata changed during this page", status_code=409)
            now = bound.canonical_now(cur)
            items = []
            for record, observed in zip(records, observations, strict=True):
                current = observed.current(now, scope=observed.capability_scope)
                if not getattr(self.authority, "_receiver_evidence_enabled", False):
                    current = unknown_receiver(self._receiver_binding(project, record), reason="receiver_evidence_disabled")
                current = self._persist_receiver_observation(bound, cur, project, record, current)
                items.append(current)
            return items

        items = self._transaction(project, "list_harnesses", finish)
        # A later receiver can wait while an earlier receiver's proof expires.
        # This is a live response; frozen snapshot pages returned above retain
        # their original cut facts and do not pass through this normalization.
        now = self.authority.canonical_now()
        items = [current_receiver_observation(item, now).model_copy(update={"allowed_actions": ("inspect",)}).model_dump(mode="json")
                 for item in items]
        return self._validate("ReceiverPage", {"items": items, "page": page})

    def receiver(self, project, receiver_ref):
        if (type(receiver_ref) is not str or not receiver_ref.strip() or len(receiver_ref) > 512
                or any(ord(character) < 32 or ord(character) == 127 for character in receiver_ref)):
            raise CommunicationHttpError("invalid_argument", "Invalid receiver reference")

        def select(bound, cur, root, _command):
            records = self._receiver_records(bound, cur, root, project, receiver_ref)
            if not records:
                raise NotFound("receiver", receiver_ref)
            return records[0]

        record = self._transaction(project, "list_harnesses", select)
        observed = self._observe_receiver(project, record)

        def finish(bound, cur, root, command):
            current = select(bound, cur, root, command)
            if current != record:
                result = unknown_receiver(self._receiver_binding(project, current), reason="receiver_binding_changed")
            elif not getattr(self.authority, "_receiver_evidence_enabled", False):
                result = unknown_receiver(self._receiver_binding(project, current), reason="receiver_evidence_disabled")
            else:
                result = observed.current(bound.canonical_now(cur), scope=observed.capability_scope)
            return self._persist_receiver_observation(bound, cur, project, current, result)

        result = self._transaction(project, "list_harnesses", finish)
        result = current_receiver_observation(result, self.authority.canonical_now())
        return self._validate("Receiver", result.model_copy(update={"allowed_actions": ("inspect",)}).model_dump(mode="json"))
