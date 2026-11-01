"""Partial collaborator configuration on the existing project/grant authority."""
from __future__ import annotations

from datetime import datetime

from runtime.communication_permissions import expanded_permissions
from runtime.errors import AuthorizationDenied, RevisionConflict
from runtime.project_common import IDENTIFIER, canonical, digest, handle, parse_handle


class CommunicationManagement:
    def _receiving_binding(self, authority, cursor, project_id, scope, slot):
        cursor.execute("SELECT definition FROM collaboration_teams WHERE tenant_id=%s AND project_id=%s AND scope_id=%s",
                       (self.context.tenant_id, project_id, scope))
        saved = cursor.fetchone()
        member = next((value for value in saved[0]["members"] if value["agent_slot_id"] == slot), {}) if saved else {}
        preferred = member.get("endpoint_id")
        cursor.execute("SELECT endpoint_id,revision FROM delivery_endpoints WHERE tenant_id=%s AND scope_id=%s "
                       "AND agent_slot_id=%s AND status='active' AND (%s OR expires_at>clock_timestamp()) "
                       "AND (%s::text IS NULL OR endpoint_id=%s) ORDER BY endpoint_id",
                       (self.context.tenant_id, scope, slot, authority.access_mode == "owner", preferred, preferred))
        rows = cursor.fetchall()
        return {"endpoint_id": rows[0][0], "binding_revision": rows[0][1]} if len(rows) == 1 else {
            "endpoint_id": None, "binding_revision": None}

    def _prepare_communication_sessions(self, result, args, credential):
        """Prepare only explicit authorized configuration targets, after commit.

        Actual native Drivers supply their own IDs; an absent provider leaves a
        saved configuration, never a fabricated Session or a task-era Attempt.
        """
        sessions = []
        for committed in result[1]["native_sessions"]:
            reference = committed["collaborator_handle"]
            slot = reference.rsplit(":", 1)[1]
            item = {**committed, "session_ref": None, "state": "provider_unavailable"}
            expected = {name: committed.get(name) for name in ("endpoint_id", "binding_revision")}
            try:
                with self.service.authority.transaction() as (authority, connection), connection.cursor() as cursor:
                    bound, _project, command = self._authorize(authority, cursor, args["project_id"], "configure_team", args)
                    self.service.authenticate(credential)
                    scope = parse_handle(result[1]["scope_handle"], "scope", args["project_id"])
                    current = self._receiving_binding(bound, cursor, args["project_id"], scope, slot)
                    if current != expected:
                        item.update(state="configuration_changed", receiver_state="unknown")
                        sessions.append(item)
                        continue
                    provider = bound._delivery_endpoints.get(expected["endpoint_id"]) if expected["endpoint_id"] else None
                    if provider is not None and callable(getattr(provider, "prepare_runtime", None)):
                        bound._authorize(command, cursor, "runtime.invoke")
                        observed = provider.prepare_runtime()
                        if self._receiving_binding(bound, cursor, args["project_id"], scope, slot) != expected:
                            item.update(state="configuration_changed", receiver_state="unknown",
                                preparation_observation={"session_ref":observed.get("session_ref") if observed.get("observation")=="native_driver_readback" else None,
                                    "receiver_state":observed.get("state","unknown"),"observation":observed.get("observation","unknown")})
                            sessions.append(item)
                            continue
                        confirmed = observed.get("observation") == "native_driver_readback" and observed.get("session_ref")
                        item.update(session_ref=observed.get("session_ref"), state="native_observed" if confirmed else "receiver_unconfirmed",
                                    receiver_state=observed.get("state", "unknown"), observation=observed.get("observation", "unknown"),
                                    preparation=observed.get("preparation", "unknown"))
            except Exception as error:  # noqa: BLE001 - committed configuration remains reviewable.
                item.update(state="preparation_unavailable", error_type=type(error).__name__)
            sessions.append(item)
        return result[0], {**result[1], "native_sessions": sessions}, result[2]

    def _configure_team(self, authority, cursor, project, command, args, _credential):
        project_id = args["project_id"]
        cursor.execute("SELECT scope_id,permissions,expires_at FROM grants WHERE grant_ref=%s FOR UPDATE",
                       (authority.context.grant_ref,))
        caller_scope, caller_permissions, caller_expiry = cursor.fetchone()
        scope = (self._scope(cursor, self.context.tenant_id, project_id, args["scope_handle"])
                 if args.get("scope_handle") else caller_scope)
        if self.profile == "route_manager" and not self.context.trusted_client and scope != caller_scope:
            raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
        authority._authorize(command, cursor, "collaborators.manage", scope)
        authority._authorize(command, cursor, "grants.manage", scope)
        cursor.execute("SELECT revision,definition FROM collaboration_teams WHERE tenant_id=%s AND project_id=%s "
                       "AND scope_id=%s FOR UPDATE", (self.context.tenant_id, project_id, scope))
        prior = cursor.fetchone()
        revision, definition = prior if prior else (0, {"members": []})
        if args.get("expected_revision", revision) != revision:
            raise RevisionConflict(scope, args["expected_revision"], revision, "expected_revision",
                "expected_revision checks this Scope's team_revision, independently of Root and Route revisions. "
                "For a partial update you may omit it and protect observed member properties with if_unchanged; "
                "do not blindly replace a stale expected revision.")
        updates = args["members"]
        if not isinstance(updates, list) or not 1 <= len(updates) <= 32:
            raise ValueError("provide one to 32 collaborator updates")
        members = {item["agent_slot_id"]: item for item in definition["members"]}
        seen = set()
        manager_address = self._communication_address(cursor, project_id)
        if self.context.trusted_client:
            cursor.execute("INSERT INTO communication_clients VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                           (self.context.tenant_id, project_id, manager_address, self.context.principal_ref))
        for update in updates:
            if not isinstance(update, dict) or set(update) - {"agent_slot_id", "principal_ref", "profile", "role",
                    "display_name", "harness_requirements", "permissions", "expires_at", "endpoint_id", "if_unchanged"}:
                raise ValueError("unknown collaborator property")
            slot = update["agent_slot_id"]
            if not IDENTIFIER.fullmatch(slot) or slot in seen:
                raise ValueError("invalid or duplicate collaborator")
            seen.add(slot)
            old = members.get(slot, {})
            expected = update.get("if_unchanged", {})
            if not isinstance(expected, dict) or any(old.get(key) != value for key, value in expected.items()):
                raise RevisionConflict(slot, revision, revision, "members.if_unchanged",
                    "A member property changed. Read the current collaborator and reconsider the requested change; "
                    "do not replace its old-value condition automatically.")
            inferred_profile = {"root": "root_manager", "route": "route_manager", "reviewer": "reviewer"}.get(update.get("role"), "engineer")
            member = {"profile": inferred_profile, "role": "engineer", "harness_requirements": [], **old,
                      **{key: value for key, value in update.items() if key != "if_unchanged"}}
            if (not isinstance(member.get("principal_ref"), str) or not member["principal_ref"]
                    or member["profile"] not in self.catalog["profiles"]
                    or member["role"] not in {"root", "route", "engineer", "reviewer", "specialist", "finalizer"}
                    or member["harness_requirements"] not in ([], ["codex"], ["opencode"], ["codex", "opencode"], ["opencode", "codex"])
                    or ("display_name" in member and (not isinstance(member["display_name"], str)
                        or not 1 <= len(member["display_name"]) <= 256))):
                raise ValueError("invalid collaborator configuration")
            if self.profile == "route_manager" and not self.context.trusted_client and (
                    member["role"] in {"root", "route"} or member["profile"] in {"root_manager", "route_manager"}):
                raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
            if (not self.context.trusted_client and (member["role"] == "root" or member["profile"] == "root_manager")
                    and manager_address != handle("collaborator", project_id, slot)):
                raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
            if old and old["principal_ref"] != member["principal_ref"]:
                raise ValueError("a stable Slot cannot change author identity")
            if member.get("endpoint_id") is not None:
                if not isinstance(member["endpoint_id"], str):
                    raise ValueError("endpoint_id must be an admitted reference or null")
                cursor.execute("SELECT scope_id,agent_slot_id,status FROM delivery_endpoints WHERE tenant_id=%s AND endpoint_id=%s",
                               (self.context.tenant_id, member["endpoint_id"]))
                if cursor.fetchone() != (scope, slot, "active"):
                    raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
            cursor.execute("SELECT tenant_id,scope_id FROM agent_slots WHERE agent_slot_id=%s FOR UPDATE", (slot,))
            existing = cursor.fetchone()
            if existing and existing != (self.context.tenant_id, scope):
                raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
            cursor.execute("SELECT principal_ref,profile FROM collaboration_memberships WHERE tenant_id=%s "
                           "AND project_id=%s AND agent_slot_id=%s", (self.context.tenant_id, project_id, slot))
            owners = cursor.fetchall()
            if any(principal != member["principal_ref"] for principal, _profile in owners):
                raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
            cursor.execute("SELECT principal_ref,grant_ref,scope_id,role,profile FROM collaboration_team_members "
                           "WHERE tenant_id=%s AND project_id=%s AND agent_slot_id=%s",
                           (self.context.tenant_id, project_id, slot))
            configured = cursor.fetchone()
            if configured and (configured[0], configured[2]) != (member["principal_ref"], scope):
                raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
            existing_manager = (configured[3] in {"root", "route"} or configured[4] in {"root_manager", "route_manager"}) if configured else any(
                profile in {"root_manager", "route_manager"} for _principal, profile in owners)
            if self.profile == "route_manager" and not self.context.trusted_client and existing_manager:
                raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
            existing_root = (configured[3] == "root" or configured[4] == "root_manager") if configured else any(
                profile == "root_manager" for _principal, profile in owners)
            if (not self.context.trusted_client and existing_root
                    and manager_address != handle("collaborator", project_id, slot)):
                raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
            # Reuse an existing membership's real credential binding when adding
            # display metadata to an already configured contact.
            cursor.execute("SELECT grant_ref FROM collaboration_memberships WHERE tenant_id=%s AND project_id=%s "
                           "AND agent_slot_id=%s AND principal_ref=%s AND profile=%s",
                           (self.context.tenant_id, project_id, slot, member["principal_ref"], member["profile"]))
            binding = cursor.fetchone()
            grant = configured[1] if configured else binding[0] if binding else "actor:" + digest([self.context.tenant_id, project_id, slot])
            owner = authority.access_mode == "owner"
            if "permissions" in update and (not isinstance(update["permissions"], list)
                    or any(not isinstance(permission, str) for permission in update["permissions"])):
                raise ValueError("permissions must be a list of text entries")
            if owner and set(update).intersection({"permissions", "expires_at"}):
                raise ValueError("owner identities use explicit lifecycle changes, not shared Grant validity fields")
            permissions = member.get("permissions", [p for p in (
                "profile." + member["profile"], "message.send", "message.read", "runtime.invoke", "collaborators.read",
                "project.read", "projects.read", "runtime.read", *(["collaborators.manage", "grants.manage"]
                    if member["profile"] in {"route_manager", "root_manager"} else [])) if p in expanded_permissions(caller_permissions)])
            if not owner and not set(permissions) <= expanded_permissions(caller_permissions):
                raise AuthorizationDenied(member["principal_ref"], grant)
            expiry = datetime.fromisoformat(member["expires_at"]) if member.get("expires_at") else caller_expiry
            if not owner and (expiry is None or expiry > caller_expiry or expiry <= authority.canonical_now(cursor)):
                raise ValueError("collaborator grant exceeds caller validity")
            cursor.execute("INSERT INTO agent_slots VALUES (%s,%s,%s,'active') ON CONFLICT(agent_slot_id) DO NOTHING",
                           (slot, self.context.tenant_id, scope))
            if binding is None and configured is None:
                cursor.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,"
                               "scope_id,permissions,expires_at,identity_only) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                               (grant, self.context.tenant_id, member["principal_ref"], self.context.authority_id,
                                self.context.authority_incarnation, scope, canonical([] if owner else permissions), None if owner else expiry, owner))
                if not owner:
                    cursor.execute("SELECT policy FROM scopes WHERE scope_id=%s AND tenant_id=%s", (scope, self.context.tenant_id))
                    cursor.execute("INSERT INTO grant_delegations(grant_ref,parent_grant_ref,tenant_id,command_id,parent_policy_digest) "
                                   "VALUES (%s,%s,%s,%s,%s)",
                                   (grant, authority.context.grant_ref, self.context.tenant_id, command.command_id, digest(cursor.fetchone()[0])))
            elif not owner and (set(update).intersection({"permissions", "expires_at", "profile"})):
                if grant == authority.context.grant_ref:
                    raise ValueError("team updates cannot rewrite their managing Grant")
                cursor.execute("SELECT parent_grant_ref FROM grant_delegations WHERE grant_ref=%s", (grant,))
                parent = cursor.fetchone()
                if parent != (authority.context.grant_ref,):
                    raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
                cursor.execute("UPDATE grants SET permissions=%s,expires_at=%s WHERE grant_ref=%s",
                               (canonical(permissions), expiry, grant))
            member["grant_ref"] = grant
            members[slot] = member
            if manager_address != handle("collaborator", project_id, slot):
                from runtime.communication_faults import bind_supervisor
                bind_supervisor(cursor, self.context.tenant_id, project_id, slot, manager_address)
        if len(members) > 100:
            raise ValueError("team exceeds configured contact bound")
        definition = {**definition, "members": list(members.values()), "access_mode": authority.access_mode}
        cursor.execute("INSERT INTO collaboration_teams VALUES (%s,%s,%s,%s,%s) "
                       "ON CONFLICT(tenant_id,project_id,scope_id) DO UPDATE SET revision=EXCLUDED.revision,definition=EXCLUDED.definition",
                       (self.context.tenant_id, project_id, scope, revision + 1, canonical(definition)))
        for slot in seen:
            member = members[slot]
            cursor.execute("INSERT INTO collaboration_team_members VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'',%s,'active') "
                           "ON CONFLICT(tenant_id,project_id,agent_slot_id) DO UPDATE SET role=EXCLUDED.role,profile=EXCLUDED.profile,"
                           "harness_requirements=EXCLUDED.harness_requirements",
                           (self.context.tenant_id, project_id, scope, slot, member["principal_ref"], member["role"],
                            member["profile"], member["grant_ref"], canonical(member["harness_requirements"])))
            cursor.execute("INSERT INTO collaboration_memberships VALUES (%s,%s,%s,%s,%s,%s) "
                           "ON CONFLICT(tenant_id,project_id,principal_ref,profile) DO NOTHING",
                           (self.context.tenant_id, project_id, member["principal_ref"], member["grant_ref"], member["profile"], slot))
        result = self._management_record(authority, cursor, command, args, target_kind="team", target_id=scope,
                                         state="team.configured", revision=revision + 1)
        cursor.execute("SELECT agent_slot_id,manager_address FROM communication_supervisors WHERE tenant_id=%s "
                       "AND project_id=%s AND agent_slot_id=ANY(%s) ORDER BY agent_slot_id",
                       (self.context.tenant_id, project_id, sorted(seen)))
        managers = [{"collaborator_handle": handle("collaborator", project_id, slot), "manager_handle": manager}
                    for slot, manager in cursor.fetchall()]
        return "configured", {"project_id": project_id, "team_revision": revision + 1, "operation_id": result.operation_id,
            "configuration_state": "committed", "scope_handle": handle("scope", project_id, scope),
            "communication_managers": managers,
            "member_handles": [handle("collaborator", project_id, slot) for slot in sorted(seen)],
            "caller_bindings": [{"agent_slot_id": slot, "principal_ref": members[slot]["principal_ref"],
                "grant_ref": members[slot]["grant_ref"], "profile": members[slot]["profile"], "trusted_client": False}
                for slot in sorted(seen)],
            "native_sessions": [{"collaborator_handle": handle("collaborator", project_id, slot),
                **self._receiving_binding(authority, cursor, project_id, scope, slot),
                "session_ref": None, "state": "not_observed"} for slot in sorted(seen)]}, []
