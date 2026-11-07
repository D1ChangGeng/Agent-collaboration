"""Stable page/stream authorization identity from actual admitted bindings.

Call only inside an already authorized ProjectService transaction. This digest
does not authorize a read and contains no bearer or credential hash. Every page
still performs the normal current authentication and participant/scope checks.
"""
from __future__ import annotations

from runtime.communication import CONTACTS
from runtime.errors import AuthorizationDenied, InvalidToolArgument
from runtime.project_common import digest


class ClientCursorAuthorization:
    def _viewer_actor_ref(self, project, address):
        context = self.project_service.context
        # Logical viewer state survives credential/Grant/incarnation renewal.
        # Same-principal Slots and a trusted Client are distinct actual viewers.
        return "viewer-" + digest([context.tenant_id, project, context.principal_ref, address])

    def _private_actor_ref(self, cursor, project):
        return self._viewer_actor_ref(project, self.project_service._communication_address(cursor, project))

    def _private_request_key(self, project, address, kind, key):
        if type(key) is not str or not 1 <= len(key) <= 200 or any(ord(char) < 32 or ord(char) == 127 for char in key):
            raise InvalidToolArgument("Idempotency-Key", "Use one stable bounded request key.")
        context = self.project_service.context
        return "request-" + digest([context.authority_id, context.authority_incarnation, context.tenant_id,
                                   project, context.principal_ref, address, kind, key])

    def _cursor_binding(self, bound, cursor, project):
        context = self.project_service.context
        cursor.execute("WITH RECURSIVE chain(ref,path,depth) AS ("
            "SELECT ref,ARRAY[ref],0 FROM unnest(%s::text[]) ref UNION ALL "
            "SELECT d.parent_grant_ref,c.path||d.parent_grant_ref,c.depth+1 FROM chain c "
            "JOIN grant_delegations d ON d.grant_ref=c.ref "
            "WHERE c.depth<8 AND NOT d.parent_grant_ref=ANY(c.path)) "
            "SELECT to_jsonb(g),to_jsonb(d),to_jsonb(s) FROM grants g LEFT JOIN grant_delegations d USING(grant_ref) "
            "LEFT JOIN scopes s ON s.scope_id=g.scope_id "
            "WHERE g.tenant_id=%s AND g.grant_ref IN (SELECT ref FROM chain) ORDER BY g.grant_ref",
            ([context.grant_ref, bound.context.grant_ref], context.tenant_id))
        grants = cursor.fetchall()
        if not grants:
            raise AuthorizationDenied(context.principal_ref, context.grant_ref)
        cursor.execute("SELECT to_jsonb(m),to_jsonb(s) FROM " + CONTACTS + " m "
            "LEFT JOIN agent_slots s ON s.tenant_id=m.tenant_id AND s.agent_slot_id=m.agent_slot_id "
            "WHERE m.tenant_id=%s AND m.project_id=%s AND m.principal_ref=%s AND m.profile=%s "
            "ORDER BY m.agent_slot_id,m.grant_ref",
            (context.tenant_id, project, context.principal_ref, self.project_service.profile))
        bindings = cursor.fetchall()
        cursor.execute("SELECT 'member',to_jsonb(m) FROM collaboration_team_members m "
            "WHERE tenant_id=%s AND project_id=%s AND principal_ref=%s "
            "UNION ALL SELECT 'route',to_jsonb(r) FROM collaboration_route_grants r "
            "WHERE tenant_id=%s AND project_id=%s AND grant_ref=ANY(%s) ORDER BY 1,2",
            (context.tenant_id, project, context.principal_ref, context.tenant_id, project,
             [context.grant_ref, bound.context.grant_ref]))
        roles = cursor.fetchall()
        cursor.execute("SELECT scope_id,root_id,state FROM collaboration_projects WHERE tenant_id=%s AND project_id=%s",
                       (context.tenant_id, project))
        namespace = cursor.fetchone()
        profile = self.project_service.profile
        tools = self.project_service.catalog["profiles"][profile]
        token = getattr(self.project_service, "token_authorization", None)
        access = getattr(token, "access", None)
        oauth = None if access is None else {
            "subject": access.subject, "client_id": access.client_id, "scopes": sorted(access.scopes)}
        return digest({"tenant": context.tenant_id, "authority": [context.authority_id, context.authority_incarnation],
            "principal": context.principal_ref, "grant": context.grant_ref, "selected_grant": bound.context.grant_ref,
            "slot": context.agent_slot_id, "trusted_client": context.trusted_client,
            "profile": profile, "tool_scopes": {name: self.project_service.catalog["tools"][name]["security_scopes"] for name in sorted(tools)},
            "address": self.project_service._communication_address(cursor, project),
            "namespace": namespace, "grant_chain": grants, "bindings": bindings, "roles": roles, "oauth": oauth})
