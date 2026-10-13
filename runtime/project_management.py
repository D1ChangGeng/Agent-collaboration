"""Typed management actions on current Domain Grants, identities and ledgers."""
from __future__ import annotations

from copy import copy
from dataclasses import replace
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from runtime.agent_organization import organization_projection
from runtime.errors import AuthorizationDenied, NotFound, RevisionConflict
from runtime.models import CommandResult
from runtime.project_common import IDENTIFIER, canonical, digest, handle, parse_handle


class ClosedInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TeamMember(ClosedInput):
    agent_slot_id: str = Field(min_length=1, max_length=128)
    principal_ref: str = Field(min_length=1, max_length=256)
    role: Literal["root", "route", "engineer", "reviewer", "finalizer", "specialist"]
    profile: Literal["root_manager", "route_manager", "engineer", "reviewer", "operator"] = "engineer"
    grant_ref: str | None = Field(default=None, min_length=1, max_length=256)
    permissions: list[str] = Field(default_factory=list, max_length=128)
    expires_at: datetime | None = None
    budget_ref: str | None = Field(default=None, min_length=1, max_length=256)
    harness_requirements: list[Literal["codex", "opencode"]] = Field(max_length=2)
    organization_level: Literal["root", "route", "task"] | None = None
    responsibilities: list[Literal["project_coordination", "route_coordination", "engineer",
                                    "reviewer", "specialist", "finalizer"]] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def role_declaration(self):
        if len(set(self.responsibilities)) != len(self.responsibilities):
            raise ValueError("responsibilities must be unique")
        primary = {"root": "project_coordination", "route": "route_coordination"}.get(self.role, self.role)
        if self.responsibilities and primary not in self.responsibilities:
            raise ValueError("responsibilities must include the primary role")
        return self

    @field_validator("expires_at")
    @classmethod
    def aware(cls, value):
        if value is None:
            return value
        if value.tzinfo is None:
            raise ValueError("Grant expiry requires a timezone")
        return value


class TeamBudget(ClosedInput):
    budget_ref: str = Field(min_length=1, max_length=256)
    max_messages: int = Field(ge=1, le=10000)
    max_pending_messages: int = Field(ge=1, le=1000)
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def aware(cls, value):
        return TeamMember.aware(value)


class TeamRules(ClosedInput):
    allowed_activations: list[Literal["message_only", "invoke"]] = Field(min_length=1, max_length=2)
    allowed_delivery_policies: list[Literal["queue_until_idle", "steer_active_turn"]] = Field(min_length=1, max_length=2)
    max_deadline_seconds: int = Field(ge=1, le=86400)


class TeamPolicy(ClosedInput):
    policy_ref: str = Field(min_length=1, max_length=256)
    rules: TeamRules


class ManagementActions:
    def _management_record(self, authority, cursor, command, args, *, target_kind,
                           target_id, state, revision):
        command = command.model_copy(update={"target_kind": target_kind, "target_id": target_id})
        result = CommandResult(command_id=command.command_id,
            operation_id="op-" + digest([command.command_id, state]), target_id=target_id,
            revision=revision, state=state)
        duplicate, hashed = authority._dedup(cursor, command, result, args)
        if duplicate:
            raise ValueError("management command has an inconsistent projection")
        authority._operation(cursor, command, result.operation_id)
        authority._outbox(cursor, command, result.operation_id, state, {"project_id": args["project_id"]})
        cursor.execute("INSERT INTO domain_events(tenant_id,work_item_id,target_kind,target_id,to_state,initiated_by,"
                       "lineage_mode,command_id,resulting_revision,evidence_refs,command_hash_version,"
                       "canonical_hash) VALUES (%s,%s,%s,%s,%s,%s,'external_command',%s,%s,'[]','v2',%s)",
                       (self.context.tenant_id, target_id if target_kind == "work_item" else None,
                        target_kind, target_id, state, command.principal_ref,
                        command.command_id, revision, hashed))
        return result

    @staticmethod
    def _scope(cursor, tenant, project_id, scope_handle):
        scope_id = parse_handle(scope_handle, "scope", project_id)
        cursor.execute("SELECT scope_id FROM collaboration_projects WHERE tenant_id=%s "
                       "AND project_id=%s AND scope_id=%s UNION SELECT scope_id FROM collaboration_routes "
                       "WHERE tenant_id=%s AND project_id=%s AND scope_id=%s",
                       (tenant, project_id, scope_id, tenant, project_id, scope_id))
        if not cursor.fetchone():
            raise NotFound("scope", scope_id)
        return scope_id

    def _configure_team(self, authority, cursor, project, command, args, _credential):
        if authority.access_mode == "owner":
            return self._configure_owner_team(authority, cursor, project, command, args)
        scope = self._scope(cursor, self.context.tenant_id, args["project_id"], args["scope_handle"])
        authority._authorize(command, cursor, "grants.manage", scope)
        members = [TeamMember.model_validate_json(canonical(item), strict=True) for item in args["members"]]
        budgets = [TeamBudget.model_validate_json(canonical(item), strict=True) for item in args["budgets"]]
        policies = [TeamPolicy.model_validate_json(canonical(item), strict=True) for item in args["policies"]]
        if not 1 <= len(members) <= 32 or not 1 <= len(budgets) <= 32 or not 1 <= len(policies) <= 16:
            raise ValueError("team definition is outside bounds")
        for identities in ([m.agent_slot_id for m in members], [m.grant_ref for m in members],
                           [m.principal_ref for m in members], [b.budget_ref for b in budgets],
                           [p.policy_ref for p in policies]):
            if len(identities) != len(set(identities)):
                raise ValueError("duplicate team identity")
        cursor.execute("SELECT revision FROM collaboration_teams WHERE tenant_id=%s AND project_id=%s "
                       "AND scope_id=%s FOR UPDATE", (self.context.tenant_id, args["project_id"], scope))
        prior = cursor.fetchone()
        revision = prior[0] if prior else 0
        if revision != args["expected_revision"]:
            raise RevisionConflict(args["scope_handle"], args["expected_revision"], revision)
        cursor.execute("SELECT permissions,expires_at FROM grants WHERE grant_ref=%s FOR UPDATE",
                       (authority.context.grant_ref,))
        permissions, expiry = cursor.fetchone()
        now = authority.canonical_now(cursor)
        by_budget = {budget.budget_ref: budget for budget in budgets}
        for member in members:
            is_manager = (member.principal_ref == authority.context.principal_ref
                          and member.grant_ref == authority.context.grant_ref
                          and member.agent_slot_id == project[5] and member.profile == self.profile)
            if (not IDENTIFIER.fullmatch(member.agent_slot_id)
                    or ((member.grant_ref == authority.context.grant_ref
                         or member.principal_ref == authority.context.principal_ref) and not is_manager)
                    or member.profile not in self.catalog["profiles"]
                    or "profile." + member.profile not in member.permissions
                    or not set(member.permissions) <= set(permissions)
                    or not now < member.expires_at <= expiry
                    or member.budget_ref not in by_budget):
                raise AuthorizationDenied(member.principal_ref, member.grant_ref)
            if is_manager and (set(member.permissions) != set(permissions) or member.expires_at != expiry):
                raise ValueError("team membership cannot rewrite the managing Grant")
            budget = by_budget[member.budget_ref]
            if not now < budget.expires_at <= expiry or (not is_manager and member.expires_at > budget.expires_at):
                raise ValueError("member expiry exceeds its bounded budget")
            cursor.execute("SELECT principal_ref,grant_ref,scope_id FROM collaboration_team_members "
                           "WHERE tenant_id=%s AND project_id=%s AND agent_slot_id=%s FOR UPDATE",
                           (self.context.tenant_id, args["project_id"], member.agent_slot_id))
            old = cursor.fetchone()
            if old and old != (member.principal_ref, member.grant_ref, scope):
                raise ValueError("AgentSlot ownership cannot be replaced by team reconfiguration")
            if old and not is_manager:
                cursor.execute("SELECT parent_grant_ref FROM grant_delegations WHERE grant_ref=%s",
                               (member.grant_ref,))
                parent = cursor.fetchone()
                if parent != (authority.context.grant_ref,):
                    raise ValueError("team cannot replace another delegator's Grant")
            if not old and not is_manager:
                cursor.execute("SELECT 1 FROM agent_slots WHERE agent_slot_id=%s UNION ALL "
                               "SELECT 1 FROM grants WHERE grant_ref=%s", (member.agent_slot_id, member.grant_ref))
                if cursor.fetchone():
                    raise ValueError("team cannot claim a pre-existing Slot or Grant")
        cursor.execute("SELECT policy FROM scopes WHERE tenant_id=%s AND scope_id=%s FOR UPDATE",
                       (self.context.tenant_id, scope))
        scope_policy = cursor.fetchone()[0]
        definition = {"policies": [p.model_dump(mode="json") for p in policies],
                      "budgets": [b.model_dump(mode="json") for b in budgets],
                      "members": [m.model_dump(mode="json") for m in members]}
        scope_policy = dict(scope_policy, collaboration_team={"project_id": args["project_id"],
            "revision": revision+1, "policies": definition["policies"]})
        cursor.execute("UPDATE scopes SET policy=%s WHERE tenant_id=%s AND scope_id=%s",
                       (canonical(scope_policy), self.context.tenant_id, scope))
        cursor.execute("INSERT INTO collaboration_teams VALUES (%s,%s,%s,%s,%s) "
                       "ON CONFLICT(tenant_id,project_id,scope_id) DO UPDATE "
                       "SET revision=EXCLUDED.revision,definition=EXCLUDED.definition",
                       (self.context.tenant_id, args["project_id"], scope, revision+1, canonical(definition)))
        for budget in budgets:
            cursor.execute("SELECT messages_used,scope_id FROM collaboration_team_budgets WHERE "
                           "tenant_id=%s AND project_id=%s AND budget_ref=%s FOR UPDATE",
                           (self.context.tenant_id, args["project_id"], budget.budget_ref))
            old = cursor.fetchone()
            if old and (old[0] > budget.max_messages or old[1] != scope):
                raise ValueError("budget cannot discard usage or change Scope")
            cursor.execute("INSERT INTO collaboration_team_budgets VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0) "
                           "ON CONFLICT(tenant_id,project_id,budget_ref) DO UPDATE SET revision=EXCLUDED.revision,"
                           "max_messages=EXCLUDED.max_messages,max_pending_messages=EXCLUDED.max_pending_messages,"
                           "expires_at=EXCLUDED.expires_at",
                           (self.context.tenant_id, args["project_id"], scope, budget.budget_ref, revision+1,
                            budget.max_messages, budget.max_pending_messages, budget.expires_at))
        cursor.execute("SELECT agent_slot_id,grant_ref FROM collaboration_team_members WHERE tenant_id=%s "
                       "AND project_id=%s AND scope_id=%s AND status='active' FOR UPDATE",
                       (self.context.tenant_id, args["project_id"], scope))
        retained = {member.agent_slot_id for member in members}
        for slot, grant in cursor.fetchall():
            if slot not in retained and grant != authority.context.grant_ref:
                cursor.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (grant,))
                cursor.execute("UPDATE agent_slots SET status='revoked' WHERE agent_slot_id=%s", (slot,))
        cursor.execute("UPDATE collaboration_team_members SET status='retired' WHERE tenant_id=%s "
                       "AND project_id=%s AND scope_id=%s", (self.context.tenant_id, args["project_id"], scope))
        for member in members:
            is_manager = member.grant_ref == authority.context.grant_ref
            cursor.execute("INSERT INTO agent_slots VALUES (%s,%s,%s,'active') "
                           "ON CONFLICT(agent_slot_id) DO UPDATE SET status='active'",
                           (member.agent_slot_id, self.context.tenant_id, scope))
            if not is_manager:
                self._write_delegated_member_grant(authority, cursor, command, scope,
                                                   scope_policy, member)
            cursor.execute("INSERT INTO collaboration_team_members VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active') "
                           "ON CONFLICT(tenant_id,project_id,agent_slot_id) DO UPDATE SET role=EXCLUDED.role,"
                           "profile=EXCLUDED.profile,budget_ref=EXCLUDED.budget_ref,"
                           "harness_requirements=EXCLUDED.harness_requirements,status='active'",
                           (self.context.tenant_id, args["project_id"], scope, member.agent_slot_id,
                            member.principal_ref, member.role, member.profile, member.grant_ref,
                            member.budget_ref, canonical(member.harness_requirements)))
            if not is_manager:
                cursor.execute("DELETE FROM collaboration_memberships WHERE tenant_id=%s AND project_id=%s "
                               "AND principal_ref=%s", (self.context.tenant_id, args["project_id"], member.principal_ref))
                cursor.execute("INSERT INTO collaboration_memberships VALUES (%s,%s,%s,%s,%s,%s)",
                               (self.context.tenant_id, args["project_id"], member.principal_ref,
                                member.grant_ref, member.profile, member.agent_slot_id))
        authority._authorize(command, cursor, "grants.manage", scope)
        now = authority.canonical_now(cursor)
        if any(member.expires_at <= now for member in members):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        if any(budget.expires_at <= now for budget in budgets):
            raise ValueError("team budget expired during configuration")
        result = self._management_record(authority, cursor, command, args, target_kind="team",
            target_id=scope, state="team.configured", revision=revision+1)
        return "configured", {"project_id": args["project_id"], "operation_id": result.operation_id,
            "team_handle": handle("team", args["project_id"], scope), "team_revision": revision+1,
            "scope_handle": args["scope_handle"], "member_handles": [
                handle("collaborator", args["project_id"], member.agent_slot_id) for member in members]}, []

    def _write_delegated_member_grant(self, authority, cursor, command, scope, scope_policy, member):
        cursor.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,"
                           "scope_id,permissions,expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                           "ON CONFLICT(grant_ref) DO UPDATE SET permissions=EXCLUDED.permissions,"
                           "expires_at=EXCLUDED.expires_at,revoked_at=NULL",
                           (member.grant_ref, self.context.tenant_id, member.principal_ref,
                            command.authority_id, command.authority_incarnation, scope,
                            canonical(member.permissions), member.expires_at))
        cursor.execute("INSERT INTO grant_delegations(grant_ref,parent_grant_ref,tenant_id,command_id,"
                           "parent_policy_digest) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(grant_ref) DO UPDATE "
                           "SET command_id=EXCLUDED.command_id,parent_policy_digest=EXCLUDED.parent_policy_digest",
                           (member.grant_ref, authority.context.grant_ref, self.context.tenant_id,
                            command.command_id, digest(scope_policy)))

    def _configure_owner_team(self, authority, cursor, project, command, args):
        scope = self._scope(cursor, self.context.tenant_id, args["project_id"], args["scope_handle"])
        authority._authorize(command, cursor, scope_id=scope)
        members = [TeamMember.model_validate_json(canonical(item), strict=True) for item in args["members"]]
        if not 1 <= len(members) <= 32 or len({item.agent_slot_id for item in members}) != len(members):
            raise ValueError("team needs distinct bounded members")
        cursor.execute("SELECT revision FROM collaboration_teams WHERE tenant_id=%s AND project_id=%s "
            "AND scope_id=%s FOR UPDATE", (self.context.tenant_id, args["project_id"], scope))
        prior = cursor.fetchone()
        revision = prior[0] if prior else 0
        if revision != args["expected_revision"]:
            raise RevisionConflict(args["scope_handle"], args["expected_revision"], revision)
        definition_members = [member.model_dump(mode="json", exclude={"permissions", "expires_at", "budget_ref", "grant_ref"})
                              for member in members]
        definition = {"members": definition_members, "policies": [], "budgets": [], "access_mode": "owner"}
        cursor.execute("INSERT INTO collaboration_teams VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT(tenant_id,project_id,scope_id) DO UPDATE SET revision=EXCLUDED.revision,definition=EXCLUDED.definition",
            (self.context.tenant_id, args["project_id"], scope, revision+1, canonical(definition)))
        for member in members:
            if not IDENTIFIER.fullmatch(member.agent_slot_id):
                raise ValueError("invalid collaborator identity")
            cursor.execute("SELECT principal_ref,grant_ref,scope_id FROM collaboration_team_members "
                "WHERE tenant_id=%s AND project_id=%s AND agent_slot_id=%s FOR UPDATE",
                (self.context.tenant_id, args["project_id"], member.agent_slot_id))
            old = cursor.fetchone()
            if old and (old[0], old[2]) != (member.principal_ref, scope):
                raise ValueError("AgentSlot identity cannot be replaced")
            cursor.execute("SELECT tenant_id,scope_id FROM agent_slots WHERE agent_slot_id=%s FOR UPDATE",
                (member.agent_slot_id,))
            existing = cursor.fetchone()
            if existing and existing != (self.context.tenant_id, scope):
                raise ValueError("AgentSlot belongs to another collaboration context")
            # Existing foreign keys retain an identity reference. This row has no
            # permissions, no expiry, and no delegation; it is never an owner permission gate.
            reference = old[1] if old else "actor:" + digest([self.context.tenant_id, scope, member.agent_slot_id])
            cursor.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,"
                "scope_id,permissions,expires_at,identity_only) VALUES (%s,%s,%s,%s,%s,%s,'[]',NULL,TRUE) "
                "ON CONFLICT(grant_ref) DO NOTHING", (reference, self.context.tenant_id, member.principal_ref,
                self.context.authority_id, self.context.authority_incarnation, scope))
            cursor.execute("INSERT INTO agent_slots VALUES (%s,%s,%s,'active') "
                "ON CONFLICT(agent_slot_id) DO UPDATE SET status='active'",
                (member.agent_slot_id, self.context.tenant_id, scope))
            cursor.execute("INSERT INTO collaboration_team_members VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active') "
                "ON CONFLICT(tenant_id,project_id,agent_slot_id) DO UPDATE SET role=EXCLUDED.role,profile=EXCLUDED.profile,"
                "harness_requirements=EXCLUDED.harness_requirements,status='active'",
                (self.context.tenant_id, args["project_id"], scope, member.agent_slot_id, member.principal_ref,
                member.role, member.profile, reference, "", canonical(member.harness_requirements)))
            cursor.execute("INSERT INTO collaboration_memberships VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(tenant_id,project_id,principal_ref,profile) DO UPDATE SET "
                "grant_ref=EXCLUDED.grant_ref,agent_slot_id=EXCLUDED.agent_slot_id",
                (self.context.tenant_id, args["project_id"], member.principal_ref, reference, member.profile, member.agent_slot_id))
        retained = [member.agent_slot_id for member in members]
        cursor.execute("UPDATE collaboration_team_members SET status='retired' WHERE tenant_id=%s "
            "AND project_id=%s AND scope_id=%s AND NOT(agent_slot_id=ANY(%s))",
            (self.context.tenant_id, args["project_id"], scope, retained))
        result = self._management_record(authority, cursor, command, args, target_kind="team",
            target_id=scope, state="team.configured", revision=revision+1)
        return "configured", {"project_id": args["project_id"], "operation_id": result.operation_id,
            "team_handle": handle("team", args["project_id"], scope), "team_revision": revision+1,
            "scope_handle": args["scope_handle"], "member_handles": [
                handle("collaborator", args["project_id"], member.agent_slot_id) for member in members]}, []

    def _list_collaborators(self, authority, cursor, project, command, args, _credential):
        scope = self._scope(cursor, self.context.tenant_id, args["project_id"], args["scope_handle"]) if args.get("scope_handle") else None
        scopes = self._visible_scopes(authority, cursor, project)
        cursor.execute("SELECT m.agent_slot_id,m.principal_ref,m.role,m.profile,m.scope_id,m.status,"
                       "m.harness_requirements,g.expires_at,g.revoked_at,m.grant_ref,g.permissions,t.definition FROM collaboration_team_members m "
                       "JOIN grants g USING(grant_ref) JOIN collaboration_teams t ON t.tenant_id=m.tenant_id AND t.project_id=m.project_id AND t.scope_id=m.scope_id WHERE m.tenant_id=%s AND m.project_id=%s "
                       "AND (%s::text IS NULL OR m.scope_id=%s) "
                       "AND (%s::text[] IS NULL OR m.scope_id=ANY(%s)) ORDER BY m.agent_slot_id",
                       (self.context.tenant_id, args["project_id"], scope, scope, scopes, scopes))
        items = []
        for slot, principal, role, profile, scope_id, state, harnesses, expires, revoked, grant, permissions, definition in cursor.fetchall():
            declared = next((item for item in definition["members"] if item["agent_slot_id"] == slot), {})
            state = state if revoked is None and (authority.access_mode == "owner" or expires > authority.canonical_now(cursor)) else "inactive"
            if state == "active":
                child = copy(authority)
                child.context = replace(authority.context, principal_ref=principal, grant_ref=grant)
                child_command = command.model_copy(update={"principal_ref": principal, "grant_ref": grant})
                try:
                    child._authorize(child_command, cursor, "profile." + profile, scope_id)
                except AuthorizationDenied:
                    state = "inactive"
            organization = organization_projection(role, level=declared.get("organization_level"),
                                                   responsibilities=declared.get("responsibilities"))
            if (args.get("roles") and not set(args["roles"]).intersection({role, *organization["responsibilities"]})
                    or args.get("states") and state not in args["states"]):
                continue
            items.append({"collaborator_handle": handle("collaborator", args["project_id"], slot),
                "agent_slot_id": slot, "principal_ref": principal, "role": role, "profile": profile,
                "scope_handle": handle("scope", args["project_id"], scope_id), "state": state,
                "harness_requirements": harnesses, "expires_at": expires.isoformat() if expires and authority.access_mode != "owner" else None,
                "organization": organization,
                "authorization": ({"identity_ref":principal, "binding_state":state,
                                   "operation_checks":"identity and object state"} if authority.access_mode == "owner" else
                                  {"grant_ref":grant, "declared_permissions":permissions,
                                   "binding_state":state, "operation_checks":"live Grant and Policy checks"}),
                "work_query": {"tool": "list_work", "arguments": {"project_id": args["project_id"],
                               "assigned_to": handle("collaborator", args["project_id"], slot)}},
                "session_query": {"tool": "list_harnesses", "arguments": {
                                  "project_id": args["project_id"],
                                  "scope_handle": handle("scope", args["project_id"], scope_id),
                                  "required_capabilities": []}},
                "review_query": {"tool": "list_reviews", "arguments": {"project_id": args["project_id"]},
                                 "match_observations": {"reviewer_ref": principal}},
                "evidence_class": "authority_observation"})
        limit = args.get("limit", 50)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid collaborator page size")
        items = [item for item in items if not args.get("cursor") or item["agent_slot_id"] > args["cursor"]]
        return "observed", {"project_id": args["project_id"], "items": items[:limit],
            "next_cursor": items[limit-1]["agent_slot_id"] if len(items)>limit else None}, []

    def _list_harnesses(self, authority, cursor, _project, _command, args, _credential):
        scope = self._scope(cursor, self.context.tenant_id, args["project_id"], args["scope_handle"])
        now = authority.canonical_now(cursor)
        until = datetime.fromisoformat(args["require_current_until"]) if args.get("require_current_until") else now
        if until.tzinfo is None:
            raise ValueError("capability horizon requires a timezone")
        until = max(until, now)
        owner = authority.access_mode == "owner"
        cursor.execute("SELECT e.endpoint_id,e.agent_slot_id,e.machine_id,e.node_id,e.revision,e.supports_invoke,"
                       "e.evidence_class,e.expires_at,h.driver_kind,h.installed_version,h.native_session_ref,"
                       "h.attempt_context,e.boot_incarnation,m.role "
                       "FROM delivery_endpoints e JOIN agent_slots s ON s.agent_slot_id=e.agent_slot_id "
                       "AND s.tenant_id=e.tenant_id AND s.scope_id=e.scope_id AND s.status='active' "
                       "LEFT JOIN collaboration_team_members m ON m.tenant_id=e.tenant_id "
                       "AND m.project_id=%s AND m.agent_slot_id=e.agent_slot_id AND m.status='active' "
                       "LEFT JOIN harness_session_bindings h "
                       "ON h.tenant_id=e.tenant_id AND h.scope_id=e.scope_id AND h.agent_slot_id=e.agent_slot_id "
                       "AND h.status='active' WHERE e.tenant_id=%s AND e.scope_id=%s AND e.status='active' "
                       "AND (%s OR e.expires_at>%s) ORDER BY e.endpoint_id,h.native_session_ref",
                       (args["project_id"], self.context.tenant_id, scope, owner, until))
        items = []
        for (endpoint, slot, machine, node, revision, invoke, evidence, expires, harness,
             version, session, attempt, boot, role) in cursor.fetchall():
            capabilities = ["message", "invoke"] if invoke else ["message"]
            if not set(args["required_capabilities"]) <= set(capabilities):
                continue
            if not owner and args.get("harness_kinds") and harness not in args["harness_kinds"]:
                continue
            if args.get("role") and role != args["role"]:
                continue
            eligible = isinstance(attempt, dict) and all(attempt.get(key) == value for key, value in {
                "machine_id": machine, "node_id": node, "node_boot_incarnation": boot,
                "endpoint_id": endpoint, "endpoint_binding_revision": revision,
                "scope_id": scope, "agent_slot_id": slot}.items())
            if eligible:
                cursor.execute("SELECT 1 FROM enrolled_nodes n JOIN enrolled_node_bindings b "
                               "ON b.tenant_id=n.tenant_id AND b.node_id=n.node_id WHERE n.tenant_id=%s "
                               "AND n.node_id=%s AND b.binding_revision=%s AND b.boot_incarnation=%s "
                               "AND n.status='active' AND b.status='active' AND (%s OR b.expires_at>%s)",
                               (self.context.tenant_id, node, attempt.get("node_binding_revision"), boot, owner, until))
                eligible = cursor.fetchone() is not None
            runtime_state = "not_observed"
            if owner:
                configured = authority._delivery_endpoints.get(endpoint)
                inspector = getattr(configured, "inspect_runtime", None)
                if callable(inspector):
                    live = inspector()
                    runtime_state = live.get("state", "unknown")
                    harness = live.get("harness", harness)
                    version = live.get("version", version)
                    eligible = invoke and runtime_state in {"idle", "busy", "online"}
                else:
                    eligible = False
            if args.get("harness_kinds") and harness not in args["harness_kinds"]:
                continue
            items.append({"endpoint_id": endpoint, "agent_slot_id": slot, "machine_id": machine,
                "node_id": node, "binding_revision": revision, "capabilities": capabilities,
                "harness": harness or "unknown", "version": version or "unknown",
                "session_ref": session, "expires_at": None if owner else expires.isoformat(),
                "binding_lifetime": "continuous" if owner else "bounded",
                "capacity_ref": endpoint + "|" + (session or "unknown"),
                "eligible": eligible, "runtime_state": runtime_state, "evidence_class": evidence})
        limit = args.get("limit", 20)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid capacity page size")
        items = [item for item in items if not args.get("cursor") or item["capacity_ref"] > args["cursor"]]
        return "observed", {"project_id": args["project_id"], "items": items[:limit],
            "next_cursor": items[limit-1]["capacity_ref"] if len(items)>limit else None}, []
