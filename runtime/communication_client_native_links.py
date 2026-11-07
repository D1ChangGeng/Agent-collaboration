"""Current Core-authorized Native linkage metadata; Host proof runs outside SQL.

A recorded link grants no transcript/action permission and metadata reads never
contact a provider or follow a replacement session. Existing successful request
receipts precede fresh epoch, proof and CAS checks, after current Core admission.
"""
from __future__ import annotations

import base64
import json
import re

from cryptography.fernet import Fernet

from runtime.communication_client_storage import cursor_secret
from runtime.communication_client_views import client_page_state
from runtime.communication_http import CommunicationHttpError
from runtime.communication_native_link_storage import (
    NativeLinkCorrupt,
    NativeLinkIdentity,
    NativeLinkProofRejected,
    NativeLinkQuotaExceeded,
    NativeLinkWrite,
    native_link_request,
    read_native_link,
    require_native_link_storage,
    write_native_link,
)
from runtime.errors import AuthorizationDenied, NotFound, RevisionConflict
from runtime.native_provider_registry import NativeProviderRegistry, NativeProviderRejected
from runtime.native_view_models import NativeSelection
from runtime.project_common import digest, handle

_POSITION = re.compile(r"[a-f0-9]{64}\Z")
_CODE = re.compile(r"[a-z][a-z0-9_]{0,95}\Z")
_SELECTION = ("endpoint_id", "scope_id", "agent_slot_id", "machine_id", "node_id", "boot_incarnation", "revision")


def _reference(value, label, *, maximum=512):
    if (type(value) is not str or not value.strip() or len(value) > maximum
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise CommunicationHttpError("invalid_argument", "Invalid Native link " + label)
    return value


def _provider_error(reason):
    code = reason if type(reason) is str and _CODE.fullmatch(reason) else "native_provider_unavailable"
    return CommunicationHttpError(code, "The admitted Native source could not prove the requested binding.", status_code=409)


class ClientNativeLinkService:
    """Mixin consuming the normal authenticated ClientService transaction API."""

    def _native_link_limits(self):
        if not getattr(self.authority, "_communication_native_links_enabled", False):
            raise CommunicationHttpError("capability_unsupported", "Native links are not enabled.", status_code=409)
        settings = getattr(self.authority, "_communication_native_link_settings", None)
        if settings is None:
            raise CommunicationHttpError("capability_unsupported", "Native link settings are unavailable.", status_code=409)
        return settings.to_limits()

    def _native_link_identity(self, bound, cursor, project, scope):
        actor = self.project_service._communication_address(cursor, project)
        return NativeLinkIdentity(bound.tenant_id, project, scope, self._viewer_actor_ref(project, actor),
            bound.context.authority_id, bound.context.authority_incarnation, bound.access_mode)

    def _native_link_transport_permissions(self, permissions):
        from runtime.project_http import OAuthScopeDenied

        authorization = getattr(self.project_service, "token_authorization", None)
        if authorization is not None:
            try:
                authorization.authorize_permissions(permissions)
            except OAuthScopeDenied as error:
                raise AuthorizationDenied(self.project_service.context.principal_ref, self.project_service.context.grant_ref) from error

    def _native_link_scopes(self, bound, cursor, root, project, _command):
        visible = self.project_service._visible_scopes(bound, cursor, root)
        cursor.execute("SELECT s.scope_id FROM scopes s WHERE s.tenant_id=%s AND s.status='active' "
            "AND (%s::text[] IS NULL OR s.scope_id=ANY(%s)) AND (s.scope_id=%s OR EXISTS("
            "SELECT 1 FROM collaboration_routes r WHERE r.tenant_id=s.tenant_id AND r.project_id=%s "
            "AND r.scope_id=s.scope_id AND r.state='active')) ORDER BY s.scope_id",
            (bound.tenant_id, visible, visible, root[0], project))
        # list_harnesses already admits runtime.read. Its normal visibility
        # policy lets a Root Grant read project metadata across Route Scopes;
        # adding a target-Scope Domain grant here would invent a stricter rule.
        return [scope for (scope,) in cursor.fetchall()]

    def native_links(self, project, *, limit=50, cursor=None, snapshot_id=None, address=None):
        self._native_link_limits()
        _reference(project, "project")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise CommunicationHttpError("invalid_argument", "Invalid Native link page limit")
        for token in (cursor, snapshot_id):
            if token is not None:
                _reference(token, "page token")
        if address is not None:
            _reference(address, "address")

        def select(bound, cur, root, command):
            require_native_link_storage(cur)
            scopes = self._native_link_scopes(bound, cur, root, project, command)
            authorization = self._cursor_binding(bound, cur, project)
            query = digest({"kind": "native_links", "project": project, "tenant": bound.tenant_id,
                "authorization": authorization, "address": address, "scopes": scopes})
            codec = Fernet(base64.urlsafe_b64encode(cursor_secret(cur.connection)))
            state = client_page_state(codec, cursor or snapshot_id, query) if cursor or snapshot_id else None
            after = state.get("after") if state is not None else None
            if after is not None and (type(after) is not str or _POSITION.fullmatch(after) is None):
                raise CommunicationHttpError("cursor_invalid", "Invalid Native link page position", status_code=409)
            # One MVCC statement captures source version and selected row revisions.
            # Hash the exact set: active Slot changes can substitute visible rows
            # with equal counts/revision sums even though link rows are permanent.
            # Scope/count values never enter a public token or DTO.
            cur.execute("WITH visible AS MATERIALIZED (SELECT n.link_id,n.link_key,n.scope_id,n.revision "
                "FROM communication_native_links n JOIN agent_slots a ON a.tenant_id=n.tenant_id "
                "AND a.scope_id=n.scope_id AND n.address=('collaborator:'||n.project_id||':'||a.agent_slot_id) "
                "AND a.status='active' WHERE n.tenant_key=acs_native_link_key(%s) "
                "AND n.project_key=acs_native_link_key(%s) AND n.scope_id=ANY(%s::text[]) "
                "AND (%s::text IS NULL OR n.address=%s)), stats AS (SELECT encode(acs_native_link_key("
                "COALESCE(string_agg(encode(link_key,'hex')||':'||revision::text,',' ORDER BY link_key),'')),"
                "'hex') AS version FROM visible), selected AS ("
                "SELECT * FROM visible WHERE (%s::bytea IS NULL OR link_key>%s) "
                "ORDER BY link_key,link_id COLLATE \"C\" LIMIT %s) SELECT stats.version,"
                "COALESCE(jsonb_agg(jsonb_build_object('link_id',selected.link_id,'scope_id',selected.scope_id,"
                "'revision',selected.revision,'position',encode(selected.link_key,'hex')) ORDER BY selected.link_key) "
                "FILTER(WHERE selected.link_id IS NOT NULL),'[]'::jsonb) FROM stats LEFT JOIN selected ON TRUE "
                "GROUP BY stats.version", (bound.tenant_id, project, scopes, address, address,
                bytes.fromhex(after) if after else None, bytes.fromhex(after) if after else None, limit + 1))
            version, selected = cur.fetchone()
            if state is not None and state.get("version") != version:
                raise CommunicationHttpError("cursor_invalid", "Native link metadata changed; restart the page", status_code=409)
            if snapshot_id:
                initial = client_page_state(codec, snapshot_id, query)
                if initial.get("version") != version or initial.get("after") is not None:
                    raise CommunicationHttpError("cursor_invalid", "Native link cursor and snapshot differ", status_code=409)
            items = []
            for row in selected[:limit]:
                identity = self._native_link_identity(bound, cur, project, row["scope_id"])
                item = read_native_link(cur, identity, row["link_id"])
                if item["revision"] != row["revision"]:
                    raise CommunicationHttpError("cursor_invalid", "Native link metadata changed during the page", status_code=409)
                items.append(item)
            if self._cursor_binding(bound, cur, project) != authorization:
                raise CommunicationHttpError("cursor_invalid", "Native link authorization changed during the page", status_code=409)

            def token(position):
                return codec.encrypt(json.dumps({"query": query, "version": version, "after": position},
                                                separators=(",", ":")).encode()).decode()

            return {"items": items, "page": {"next_cursor": token(selected[limit - 1]["position"])
                if len(selected) > limit else None, "snapshot_id": snapshot_id or token(None)}}

        return self._validate("NativeLinkPage", self._transaction(project, "list_harnesses", select))

    def _native_link_event_visible(self, bound, cur, _root, project, _command, link_id, scope_id):
        """Current metadata visibility for a source event; no Host observation."""
        if not getattr(self.authority, "_communication_native_links_enabled", False):
            return False
        try:
            self.project_service._check_tool_policy("list_harnesses")
            reader, root, command = self.project_service._authorize(bound, cur, project, "list_harnesses",
                                                                   {"project_id": project})
        except (PermissionError, AuthorizationDenied):
            return False
        if scope_id not in self._native_link_scopes(reader, cur, root, project, command):
            return False
        cur.execute("SELECT n.scope_id FROM communication_native_links n JOIN agent_slots a "
            "ON a.tenant_id=n.tenant_id AND a.scope_id=n.scope_id AND a.status='active' "
            "AND n.address=('collaborator:'||n.project_id||':'||a.agent_slot_id) "
            "WHERE n.tenant_key=acs_native_link_key(%s) AND n.project_key=acs_native_link_key(%s) "
            "AND n.link_key=acs_native_link_key(%s) AND n.link_id=%s AND n.scope_id=%s",
            (reader.tenant_id, project, link_id, link_id, scope_id))
        if cur.fetchone() is None:
            return False
        identity = self._native_link_identity(reader, cur, project, scope_id)
        read_native_link(cur, identity, link_id)
        return True

    def _native_link_authorize_target(self, bound, cur, root, command, project, scope, address):
        """Admit the actual caller to a logical Slot/Scope, independent of an endpoint ID."""
        scopes = self._native_link_scopes(bound, cur, root, project, command)
        if scope not in scopes:
            raise AuthorizationDenied(self.project_service.context.principal_ref, self.project_service.context.grant_ref)
        cur.execute("SELECT 1 FROM agent_slots WHERE tenant_id=%s AND scope_id=%s AND status='active' "
                    "AND ('collaborator:'||%s||':'||agent_slot_id)=%s", (bound.tenant_id, scope, project, address))
        if cur.fetchone() is None:
            raise NotFound("Native link target", address)
        actor = self.project_service._communication_address(cur, project)
        if (not self.project_service.context.trusted_client and actor == address
                and actor.startswith("collaborator:")):
            self._native_link_transport_permissions(("runtime.invoke",))
            bound._authorize(command, cur, "runtime.invoke", scope)
        else:
            self.project_service._check_tool_policy("configure_team")
            manager, _project, management = self.project_service._authorize(bound, cur, project, "configure_team",
                {"project_id": project, "scope_handle": handle("scope", project, scope)})
            self._native_link_transport_permissions(("delivery.manage",))
            for permission in ("collaborators.manage", "grants.manage", "delivery.manage"):
                manager._authorize(management, cur, permission, scope)
        return self._native_link_identity(bound, cur, project, scope), actor

    def _native_link_original_outcome(self, bound, cur, root, command, project, link_id, body, request_id):
        # An endpoint ID may now name another Slot. The immutable recorded target
        # still chooses replay authorization; a fresh endpoint matters only on a
        # receipt miss. This lookup never grants Host access or mutates a binding.
        require_native_link_storage(cur)
        cur.execute("SELECT tenant_id,project_id,link_id,scope_id,address FROM communication_native_links "
            "WHERE tenant_key=acs_native_link_key(%s) AND project_key=acs_native_link_key(%s) "
            "AND link_key=acs_native_link_key(%s)", (bound.tenant_id, project, link_id))
        recorded = cur.fetchone()
        if recorded is None:
            return False, None
        if recorded[:3] != (bound.tenant_id, project, link_id):
            raise NativeLinkCorrupt("Native link physical resource identity differs")
        identity, actor = self._native_link_authorize_target(bound, cur, root, command, project, recorded[3], recorded[4])
        read_native_link(cur, identity, link_id)
        namespace = self._private_request_key(project, actor, "native_link.write", request_id)
        return True, native_link_request(cur, identity, link_id, body, namespace)

    def _native_link_authorize_write(self, bound, cur, root, command, project, body):
        cur.execute("SELECT to_jsonb(e) FROM delivery_endpoints e WHERE tenant_id=%s AND endpoint_id=%s",
                    (bound.tenant_id, body.receiver_ref))
        found = cur.fetchone()
        if found is None:
            raise NotFound("receiver", body.receiver_ref)
        record = found[0]
        actual = self._receiver_binding(project, record)
        if actual.actor_address != body.address:
            raise AuthorizationDenied(self.project_service.context.principal_ref, self.project_service.context.grant_ref)
        identity, actor = self._native_link_authorize_target(bound, cur, root, command, project, record["scope_id"], body.address)
        # Preserve Grant -> Scope -> endpoint lock order and freeze the selection
        # only after current read/write permission checks have admitted it.
        cur.execute("SELECT to_jsonb(e) FROM delivery_endpoints e WHERE tenant_id=%s AND endpoint_id=%s FOR SHARE",
                    (bound.tenant_id, body.receiver_ref))
        current = cur.fetchone()
        if current is None:
            raise NotFound("receiver", body.receiver_ref)
        if any(current[0][key] != record[key] for key in _SELECTION):
            raise RevisionConflict(body.receiver_ref, record["revision"], current[0]["revision"])
        return current[0], identity, actor

    def _native_link_selection(self, bound, cur, root, project, record):
        visible = self._receiver_records(bound, cur, root, project, record["endpoint_id"])
        if not visible or any(visible[0][key] != record[key] for key in _SELECTION):
            raise NotFound("receiver", record["endpoint_id"])
        return NativeSelection(tenant_id=bound.tenant_id, project_id=project, scope_id=record["scope_id"],
            agent_slot_id=record["agent_slot_id"], binding=self._receiver_binding(project, record),
            node_id=record["node_id"], boot_incarnation=record["boot_incarnation"])

    def write_native_link(self, project, link_id, body, client_request_id):
        self._native_link_limits()
        _reference(project, "project")
        _reference(link_id, "identifier")
        request = NativeLinkWrite.model_validate_json(json.dumps(self._validate("NativeLinkWrite", body)))

        def select(bound, cur, root, command):
            recorded, prior = self._native_link_original_outcome(bound, cur, root, command, project, link_id,
                                                                request, client_request_id)
            if prior is not None:
                return prior, None, None, None, None
            record, identity, actor = self._native_link_authorize_write(bound, cur, root, command, project, request)
            namespace = self._private_request_key(project, actor, "native_link.write", client_request_id)
            prior = None if recorded else native_link_request(cur, identity, link_id, request, namespace)
            if prior is not None:
                return prior, None, None, None, None
            if request.expected_binding_epoch != record["revision"]:
                raise RevisionConflict(request.receiver_ref, request.expected_binding_epoch, record["revision"])
            if request.expected_host_ref != record["machine_id"]:
                raise _provider_error("native_source_selection_changed")
            registry = getattr(self.authority, "_native_provider_registry", None)
            if not isinstance(registry, NativeProviderRegistry):
                raise _provider_error("native_provider_not_registered")
            try:
                admission, fence = registry.resolve_fenced(request.provider_ref, request.native_authority,
                    self._native_link_selection(bound, cur, root, project, record))
            except NativeProviderRejected as error:
                raise _provider_error(error.code) from error
            return None, record, registry, admission, fence

        prior, record, registry, admission, fence = self._transaction(project, "list_harnesses", select)
        if prior is not None:
            return self._validate("NativeLink", prior)
        # No SQL connection or locks survive this point. This observation never
        # requests Host transcript permission, preparation, input or a new session.
        proof = registry.prove(request.provider_ref, request.native_authority, admission.selection)
        if proof.state != "verified":
            raise _provider_error(proof.reason_code)
        if (proof.provider_ref, proof.native_authority, proof.host_ref, proof.native_session_ref, proof.provider_generation) != (
                request.provider_ref, request.native_authority, request.expected_host_ref,
                request.native_session_ref, request.expected_provider_generation):
            raise _provider_error("native_source_selection_changed")

        def finish(bound, cur, root, command):
            current_limits = self._native_link_limits()
            recorded, prior = self._native_link_original_outcome(bound, cur, root, command, project, link_id,
                                                                request, client_request_id)
            if prior is not None:
                return prior
            current, identity, actor = self._native_link_authorize_write(bound, cur, root, command, project, request)
            namespace = self._private_request_key(project, actor, "native_link.write", client_request_id)
            # A concurrent exact request may have committed while Host I/O ran.
            # It still returns its original outcome before fresh binding checks.
            prior = None if recorded else native_link_request(cur, identity, link_id, request, namespace)
            if prior is not None:
                return prior
            if any(current[key] != record[key] for key in _SELECTION):
                raise RevisionConflict(request.receiver_ref, request.expected_binding_epoch, current["revision"])
            if getattr(self.authority, "_native_provider_registry", None) is not registry:
                raise _provider_error("native_provider_registration_changed")
            try:
                resolved = registry.resolve(request.provider_ref, request.native_authority,
                    self._native_link_selection(bound, cur, root, project, current))
            except NativeProviderRejected as error:
                raise _provider_error(error.code) from error
            if resolved != admission:
                raise _provider_error("native_provider_selection_changed")
            registry.assert_current(fence)
            result = write_native_link(cur, identity, link_id, request, proof, namespace, limits=current_limits)
            registry.assert_current(fence)
            # A public DTO contract failure must still roll back this write.
            return self._validate("NativeLink", result)

        try:
            result = self._transaction(project, "list_harnesses", finish)
        except NativeLinkProofRejected as error:
            raise _provider_error("native_link_proof_rejected") from error
        except NativeLinkQuotaExceeded as error:
            raise CommunicationHttpError("native_link_quota_exceeded", "Native link metadata quota reached.",
                                         status_code=429) from error
        except NativeProviderRejected as error:
            raise _provider_error(error.code) from error
        return self._validate("NativeLink", result)
