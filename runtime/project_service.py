"""Project-scoped typed actions composed with the PostgreSQL Domain service."""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from copy import copy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

from runtime.delivery_models import DeliveryPacket
from runtime.errors import AuthorizationDenied, IdempotencyConflict, NotFound, RevisionConflict
from runtime.models import CommandEnvelope, CommandResult
from runtime.project_common import IDENTIFIER, canonical, digest, handle, parse_handle
from runtime.project_continuation import ContinuationActions
from runtime.project_inbox import InboxActions
from runtime.project_management import ManagementActions
from runtime.project_routes import RouteActions
from runtime.project_work import WorkActions
from runtime.source import SourceChangedDuringSnapshot
from runtime.surfaces import SharedService, SurfaceCommand

RECEIPTS = (
    "accepted_by_authority", "target_inbox_committed", "runtime_dispatched",
    "runtime_acknowledged", "response_received",
)


class ProjectService(ContinuationActions, WorkActions, ManagementActions, RouteActions, InboxActions):
    """Authenticated project adapter; never owns an alternate execution state."""

    IMPLEMENTED = frozenset({
        "read_profile", "list_projects", "list_connections", "load_project", "list_routes", "list_work",
        "create_work", "send_message", "read_message", "check_inbox", "wait_for_response",
        "list_sources", "list_files", "search_files", "read_file", "read_source", "read_diff",
        "configure_team", "list_collaborators", "list_harnesses",
        "revise_work", "handoff_work", "request_review", "submit_review",
        "read_resource", "list_evidence", "list_reviews", "list_activity",
        "accept_work",
        "watch_changes", "set_notification",
        "create_route", "update_route",
    })
    DOMAIN_PERMISSIONS: ClassVar[dict[str, tuple[str, ...]]] = {
        "create_work": ("work_item.create",),
        "send_message": ("message.send",),
        "read_message": ("message.read",),
        "check_inbox": ("message.read",),
        "wait_for_response": ("message.read",),
        "list_files": ("artifact.read",),
        "search_files": ("artifact.read",),
        "read_file": ("artifact.read",),
        "read_source": ("artifact.read",),
        "read_diff": ("artifact.read",),
        "request_review": ("review.assign",),
        "submit_review": ("review.record",),
        "accept_work": ("work_item.transition", "acceptance.finalize"),
        "create_route": ("grants.manage",),
    }

    def __init__(self, service: SharedService, catalog: dict[str, Any], *, profile: str, sources=None):
        if profile not in catalog["profiles"]:
            raise ValueError("unknown Profile")
        self.service, self.catalog, self.profile = service, catalog, profile
        self.sources = sources

    @property
    def context(self):
        return self.service.authority.context

    def initialize(self) -> None:
        """Explicit operator schema adoption; not invoked by a tool request."""
        schema = Path(__file__).with_name("project_schema.sql").read_bytes()
        checksum = hashlib.sha256(schema).hexdigest()
        with self.service.authority._connect() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                               ("acs-project-runtime-schema",))
            old = connection.execute(
                "SELECT schema_version,schema_checksum FROM runtime_schema_metadata "
                "WHERE schema_name='acs-project-runtime' FOR UPDATE",
            ).fetchone()
            if old and old != ("1", checksum):
                raise ValueError("project schema requires explicit migration")
            connection.execute(schema)
            connection.execute(
                "INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) "
                "VALUES ('acs-project-runtime','1',%s) ON CONFLICT(schema_name) DO NOTHING",
                (checksum,),
            )

    def admit_project(self, command: CommandEnvelope, *, project_id: str, root_id: str,
                      scope_id: str, agent_slot_id: str, name: str,
                      context_manifest: dict[str, Any], credential: str) -> dict[str, Any]:
        """Admit installer-verified identities under an existing Scope and Grant.

        The installer remains responsible for the AGENTS/manifest write and
        preservation checks. This operation cannot create or enlarge a Grant.
        """
        self.service.authenticate(credential)
        if (command.command_type != "project.adopt" or command.target_kind != "project"
                or command.target_id != project_id):
            raise ValueError("invalid project admission command")
        handle("project", project_id, root_id)
        authority = self.service.authority
        with authority._connect() as connection, connection.cursor() as cursor:
            authority._authorize(command, cursor, "project.adopt", scope_id)
            authority._authorize(command, cursor, "profile." + self.profile, scope_id)
            result = CommandResult(command_id=command.command_id, operation_id="op-" + uuid.uuid4().hex,
                                   target_id=project_id, revision=1, state="project_adopted")
            replay, hashed = authority._dedup(cursor, command, result, {
                "project_id": project_id, "root_id": root_id, "scope_id": scope_id,
                "agent_slot_id": agent_slot_id, "name": name,
                "context_manifest": context_manifest, "profile": self.profile,
            })
            if replay:
                return replay.model_dump(mode="json")
            if command.expected_revision != 0:
                raise RevisionConflict(project_id, command.expected_revision, 0)
            cursor.execute("SELECT 1 FROM agent_slots WHERE tenant_id=%s AND scope_id=%s "
                           "AND agent_slot_id=%s AND status='active' FOR UPDATE",
                           (command.tenant_id, scope_id, agent_slot_id))
            if not cursor.fetchone():
                raise AuthorizationDenied(command.principal_ref, command.grant_ref)
            cursor.execute(
                "INSERT INTO collaboration_projects(tenant_id,project_id,root_id,scope_id,"
                "name,context_manifest) VALUES (%s,%s,%s,%s,%s,%s)",
                (command.tenant_id, project_id, root_id, scope_id, name, canonical(context_manifest)),
            )
            cursor.execute(
                "INSERT INTO collaboration_memberships VALUES (%s,%s,%s,%s,%s,%s)",
                (command.tenant_id, project_id, command.principal_ref, command.grant_ref,
                 self.profile, agent_slot_id),
            )
            for route in context_manifest.get("routes", []):
                handle("route", project_id, route["route_id"])
                if route["scope_id"] != scope_id:
                    raise ValueError("route Scope must be explicitly admitted to this project")
                cursor.execute("INSERT INTO collaboration_routes(tenant_id,project_id,route_id,"
                               "scope_id,definition) VALUES (%s,%s,%s,%s,%s)",
                               (command.tenant_id, project_id, route["route_id"], scope_id,
                                canonical(route)))
            authority._operation(cursor, command, result.operation_id)
            authority._outbox(cursor, command, result.operation_id, "project.adopted",
                              {"project_id": project_id})
            cursor.execute(
                "INSERT INTO domain_events(tenant_id,target_kind,target_id,to_state,initiated_by,"
                "lineage_mode,command_id,resulting_revision,evidence_refs,command_hash_version,"
                "canonical_hash) VALUES (%s,'project',%s,'project.adopted',%s,'external_command',"
                "%s,1,'[]','v2',%s)",
                (command.tenant_id, project_id, command.principal_ref, command.command_id, hashed),
            )
            authority._authorize(command, cursor, "project.adopt", scope_id)
        return result.model_dump(mode="json")

    def admit_source(self, command, *, project_id, source_id, request,
                     repository_identity, credential):
        """Register an immutable clean Source snapshot through live Domain Grants."""
        self.service.authenticate(credential)
        if (self.sources is None or command.command_type != "source.bind"
                or command.target_kind != "project" or command.target_id != project_id):
            raise ValueError("Source admission is unavailable")
        handle("source", project_id, source_id)
        with (self.service.authority.transaction() as (authority, connection),
              connection.cursor() as cursor):
            authority._authorize(command, cursor, "source.manage")
            bound, project, _ = self._authorize(authority, cursor, project_id, "list_sources",
                {"project_id": project_id, "scope_handle": handle("scope", project_id, request.scope_id),
                 "deadline": command.deadline.isoformat()})
            command = command.model_copy(update={"grant_ref": bound.context.grant_ref})
            bound._authorize(command, cursor, "source.manage", request.scope_id)
            if (request.tenant_id, request.scope_id, request.root_id) != (
                    self.context.tenant_id, self._scope(cursor, self.context.tenant_id, project_id,
                        handle("scope", project_id, request.scope_id)), project[1]):
                raise ValueError("Source admission identity differs from project")
            if request.route_id is None:
                if request.scope_id != project[0]:
                    raise ValueError("Root Source requires the actual project Root Scope")
            else:
                cursor.execute("SELECT 1 FROM collaboration_routes WHERE tenant_id=%s AND project_id=%s "
                               "AND route_id=%s AND scope_id=%s",
                               (self.context.tenant_id, project_id, request.route_id, request.scope_id))
                if not cursor.fetchone():
                    raise NotFound("route", request.route_id)
            result = CommandResult(command_id=command.command_id, operation_id="op-" + uuid.uuid4().hex,
                target_id=project_id, revision=command.expected_revision + 1, state="source_bound")
            replay, hashed = bound._dedup(cursor, command, result, {
                "source_id": source_id, "root": str(request.root),
                "commit": request.expected_commit, "tree": request.expected_tree,
                "scope_id": request.scope_id, "root_id": request.root_id, "route_id": request.route_id,
                "max_bytes": request.max_bytes, "secret_patterns": request.secret_patterns,
                "repository_identity": repository_identity,
            })
            if replay:
                return replay.model_dump(mode="json")
            cursor.execute("SELECT revision,repository_identity FROM collaboration_sources WHERE "
                           "tenant_id=%s AND project_id=%s AND source_id=%s FOR UPDATE",
                           (self.context.tenant_id, project_id, source_id))
            old = cursor.fetchone()
            revision = old[0] if old else 0
            if revision != command.expected_revision:
                raise RevisionConflict(source_id, command.expected_revision, revision)
            if old and old[1] != repository_identity:
                raise ValueError("Source repository identity cannot be replaced")
            if old:
                cursor.execute("SELECT p.snapshot_json FROM collaboration_source_snapshots p "
                               "JOIN collaboration_sources s USING(tenant_id,project_id,source_id) "
                               "WHERE p.tenant_id=%s AND p.project_id=%s AND p.source_id=%s AND p.source_commit=s.current_commit",
                               (self.context.tenant_id, project_id, source_id))
                previous_identity = cursor.fetchone()[0]
                if any(previous_identity[key] != getattr(request, key) for key in ("scope_id", "root_id", "route_id")):
                    raise ValueError("Source Scope, Root and Route identity cannot be replaced")
            snapshot = self.sources.capture(request, bound, command)
            cursor.execute("INSERT INTO collaboration_sources VALUES (%s,%s,%s,%s,%s,%s) "
                           "ON CONFLICT(tenant_id,project_id,source_id) DO UPDATE "
                           "SET revision=EXCLUDED.revision,current_commit=EXCLUDED.current_commit",
                           (self.context.tenant_id, project_id, source_id, revision + 1,
                            snapshot.source_commit, canonical(repository_identity)))
            cursor.execute("SELECT snapshot_json FROM collaboration_source_snapshots WHERE tenant_id=%s "
                           "AND project_id=%s AND source_id=%s AND source_commit=%s",
                           (self.context.tenant_id, project_id, source_id, snapshot.source_commit))
            previous = cursor.fetchone()
            if previous:
                retained = self.sources.snapshot(previous[0])
                if (retained.source_tree != snapshot.source_tree
                        or retained.repository_root != snapshot.repository_root
                        or retained.files != snapshot.files):
                    raise ValueError("immutable Source revision has different content or location")
            else:
                cursor.execute("INSERT INTO collaboration_source_snapshots(tenant_id,project_id,source_id,"
                               "source_commit,snapshot_digest,snapshot_json,command_id) "
                               "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                               (self.context.tenant_id, project_id, source_id, snapshot.source_commit,
                                snapshot.snapshot_sha256, canonical(snapshot.manifest_dict()), command.command_id))
            bound._operation(cursor, command, result.operation_id)
            bound._outbox(cursor, command, result.operation_id, "source.bound",
                          {"project_id": project_id, "source_id": source_id, "commit": snapshot.source_commit})
            cursor.execute("INSERT INTO domain_events(tenant_id,target_kind,target_id,to_state,initiated_by,"
                           "lineage_mode,command_id,resulting_revision,evidence_refs,command_hash_version,"
                           "canonical_hash) VALUES (%s,'project',%s,'source.bound',%s,'external_command',"
                           "%s,%s,'[]','v2',%s)", (self.context.tenant_id, project_id,
                           command.principal_ref, command.command_id, revision + 1, hashed))
            bound._authorize(command, cursor, "source.manage", request.scope_id)
        return result.model_dump(mode="json")

    def _command(self, authority, name, args, *, target_kind="project", target_id=None,
                 expected_revision=0, payload=None):
        context = authority.context
        request_id = args.get("client_request_id") or uuid.uuid4().hex
        identity = "mcp-" + digest([context.tenant_id, context.principal_ref,
                                     args.get("project_id"), request_id])
        now = datetime.now(UTC)
        for field in ("expected_revision", "expected_work_revision", "expected_route_revision", "expected_root_revision"):
            if field in args:
                expected_revision = args[field]
                break
        return CommandEnvelope(
            command_id=identity, command_type=name, idempotency_key=identity,
            correlation_id=identity, tenant_id=context.tenant_id,
            authority_id=context.authority_id, authority_incarnation=context.authority_incarnation,
            principal_ref=context.principal_ref, grant_ref=context.grant_ref,
            target_kind=target_kind, target_id=target_id or args["project_id"],
            expected_revision=expected_revision, issued_at=now,
            deadline=datetime.fromisoformat(args["deadline"]) if "deadline" in args
            else now + timedelta(seconds=30), payload=payload or {},
        )

    def _authorize(self, authority, cursor, project_id, name, args):
        cursor.execute(
            "SELECT p.scope_id,p.root_id,p.revision,p.context_manifest,m.grant_ref,m.agent_slot_id "
            "FROM collaboration_projects p JOIN collaboration_memberships m "
            "USING(tenant_id,project_id) WHERE p.tenant_id=%s AND p.project_id=%s "
            "AND p.state='active' AND m.principal_ref=%s AND m.profile=%s FOR UPDATE OF p,m",
            (self.context.tenant_id, project_id, self.context.principal_ref, self.profile),
        )
        row = cursor.fetchone()
        if row is None:
            raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
        # Membership selects a scoped descendant of the authenticated Grant;
        # it cannot upgrade a stale credential to a replacement Grant merely
        # because both credentials name the same principal.
        anchor_authority = copy(authority)
        anchor_authority.context = self.context
        anchor = self._command(anchor_authority, "project." + name, args)
        anchor_permissions = ["profile." + self.profile,
                              *self.catalog["tools"][name]["security_scopes"],
                              *self.DOMAIN_PERMISSIONS.get(name, ())]
        for permission in anchor_permissions:
            anchor_authority._authorize(anchor, cursor, permission)
        if row[4] != self.context.grant_ref:
            cursor.execute("WITH RECURSIVE ancestry AS (SELECT %s::text AS ref,0 AS depth "
                           "UNION ALL SELECT d.parent_grant_ref,a.depth+1 FROM ancestry a "
                           "JOIN grant_delegations d ON d.grant_ref=a.ref WHERE a.depth<8) "
                           "SELECT 1 FROM ancestry WHERE ref=%s",
                           (row[4], self.context.grant_ref))
            if cursor.fetchone() is None:
                raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
        bound = copy(anchor_authority)
        bound.context = replace(self.context, grant_ref=row[4])
        command = self._command(bound, "project." + name, args)
        permissions = ["profile." + self.profile,
                       *self.catalog["tools"][name]["security_scopes"],
                       *self.DOMAIN_PERMISSIONS.get(name, ())]
        for permission in permissions:
            bound._authorize(command, cursor, permission)
        requested_scope = self._requested_scope(cursor, project_id, args)
        return self._route_authority(bound, cursor, project_id, row, requested_scope,
                                     permissions, dict(args, _tool_name=name))

    def _accessible(self, credential, name="list_projects"):
        self.service.authenticate(credential)
        with self.service.authority.transaction() as (authority, connection):
            rows = connection.execute(
                "SELECT project_id FROM collaboration_memberships WHERE tenant_id=%s "
                "AND principal_ref=%s AND profile=%s ORDER BY project_id",
                (self.context.tenant_id, self.context.principal_ref, self.profile),
            ).fetchall()
            result = []
            for (project_id,) in rows:
                with connection.cursor() as cursor:
                    try:
                        _, row, _ = self._authorize(authority, cursor, project_id, name,
                                                    {"project_id": project_id})
                    except AuthorizationDenied:
                        continue
                    result.append({"project_id": project_id,
                                   "root_handle": handle("project", project_id, row[1]),
                                   "project_revision": row[2]})
        return result

    def available_tools(self, credential: str) -> list[str]:
        self.service.authenticate(credential)
        available = []
        for name in self.catalog["profiles"][self.profile]:
            if name not in self.IMPLEMENTED:
                continue
            if self.sources is None and name in {"list_files", "search_files", "read_file", "read_source", "read_diff"}:
                continue
            if name == "read_profile" or self._accessible(credential, name):
                available.append(name)
        return available

    def execute(self, name: str, args: dict[str, Any], credential: str):
        self.service.authenticate(credential)
        if name not in self.catalog["profiles"][self.profile] or name not in self.IMPLEMENTED:
            raise ValueError("tool is unavailable in the authenticated Profile")
        if name == "read_profile":
            return self._profile_snapshot()
        if name == "list_connections":
            return self._connections(args, credential)
        if name == "list_projects":
            limit = args.get("limit", 50)
            if type(limit) is not int or not 1 <= limit <= 100:
                raise ValueError("invalid page limit")
            rows = self._accessible(credential)
            cursor = args.get("cursor")
            rows = [item for item in rows if not cursor or item["project_id"] > cursor]
            return "observed", {"items": rows[:limit],
                                "next_cursor": rows[limit - 1]["project_id"]
                                if len(rows) > limit else None}, []
        if name == "wait_for_response":
            return self._wait(args, credential)
        project_id = args["project_id"]
        if not IDENTIFIER.fullmatch(project_id):
            raise ValueError("invalid project_id")
        with (self.service.authority.transaction() as (authority, connection),
              connection.cursor() as cursor):
            bound, project, command = self._authorize(authority, cursor, project_id, name, args)
            request_id = args.get("client_request_id")
            input_digest = digest([name, args])
            prior = None
            if request_id:
                if project[3].get("management"):
                    # Management identity is checked with the primary project
                    # membership; a selected Route Grant governs the action.
                    cursor.execute("SELECT grant_ref FROM collaboration_memberships WHERE tenant_id=%s AND project_id=%s "
                                   "AND principal_ref=%s AND profile=%s", (self.context.tenant_id, project_id,
                                   self.context.principal_ref, self.profile))
                    identity_authority = copy(bound)
                    identity_authority.context = replace(self.context, grant_ref=cursor.fetchone()[0])
                    identity_command = command.model_copy(update={"grant_ref": identity_authority.context.grant_ref})
                    identity_project = project
                    narrow = self._visible_scopes(identity_authority, cursor, project)
                    if narrow is not None:
                        cursor.execute("SELECT definition->'context_manifest' FROM collaboration_routes "
                                       "WHERE tenant_id=%s AND project_id=%s AND scope_id=%s",
                                       (self.context.tenant_id, project_id, narrow[0]))
                        route_context = cursor.fetchone()
                        if route_context is None or not route_context[0]:
                            raise ValueError("Route management Source context is unavailable")
                        identity_project = (*project[:3], route_context[0], *project[4:])
                    self._verify_management_identity(identity_authority, cursor, identity_project, identity_command,
                                                     args["project_id"], require_current=True)
                bound._lock_command_identity(cursor, command)
                cursor.execute(
                    "SELECT input_digest,result_json FROM collaboration_commands "
                    "WHERE tenant_id=%s AND project_id=%s AND principal_ref=%s "
                    "AND client_request_id=%s FOR UPDATE",
                    (self.context.tenant_id, project_id, self.context.principal_ref, request_id),
                )
                prior = cursor.fetchone()
                if prior and prior[0] != input_digest:
                    raise IdempotencyConflict(request_id)
            result = (tuple(prior[1]) if prior else
                      getattr(self, "_" + name)(bound, cursor, project, command, args, credential))
            # Recheck after potentially expensive reads/commands, before commit.
            self._authorize(bound, cursor, project_id, name, args)
            if request_id and prior is None:
                cursor.execute(
                    "INSERT INTO collaboration_commands(tenant_id,project_id,principal_ref,"
                    "client_request_id,tool_name,input_digest,command_id,result_json) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (self.context.tenant_id, project_id, self.context.principal_ref,
                     request_id, name, input_digest, command.command_id, canonical(result)),
                )
        if name == "send_message" and args.get("response_mode", "async") == "sync":
            observation = self._wait({"project_id": project_id,
                "handles": [result[1]["response_handle"]], "mode": "all",
                "until": args.get("wait_until", "response_received"),
                "timeout_seconds": args.get("wait_timeout_seconds", 30)}, credential)
            result = (observation[0], dict(result[1], observation=observation[1]), result[2])
        return result

    def _profile_snapshot(self):
        with self.service.authority._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT scope_id,permissions,expires_at,revoked_at FROM grants WHERE tenant_id=%s "
                           "AND principal_ref=%s AND grant_ref=%s AND authority_id=%s AND authority_incarnation=%s",
                           (self.context.tenant_id, self.context.principal_ref, self.context.grant_ref,
                            self.context.authority_id, self.context.authority_incarnation))
            grant = cursor.fetchone()
            active = False
            if grant:
                try:
                    self.service.authority._authorize_delegation(cursor, self.context, "profile." + self.profile)
                    cursor.execute("SELECT 1 FROM authority_instances WHERE authority_id=%s "
                                   "AND authority_incarnation=%s AND status='active'",
                                   (self.context.authority_id, self.context.authority_incarnation))
                    active = cursor.fetchone() is not None
                except AuthorizationDenied:
                    active = False
        return "observed", {"subject": self.context.principal_ref, "tenant_id": self.context.tenant_id,
            "profile": self.profile, "granted_profiles": [self.profile] if active else [],
            "authority_id": self.context.authority_id, "authority_incarnation": self.context.authority_incarnation,
            "domain_schema_version": self.service.authority.SCHEMA_VERSION,
            "connection_state": "authorized" if active else "authorization_unavailable",
            "grant": {"ref": self.context.grant_ref, "scope_id": grant[0] if grant else None,
                "permissions": grant[1] if active else [], "expires_at": grant[2].isoformat() if grant else None}}, []

    def _connections(self, args, credential):
        visible = self._accessible(credential, "list_connections")
        if args.get("project_id"):
            visible = [item for item in visible if item["project_id"] == args["project_id"]]
        rows = []
        with self.service.authority.transaction() as (authority, connection), connection.cursor() as cursor:
            for project in visible:
                project_id = project["project_id"]
                bound, selected, _ = self._authorize(authority, cursor, project_id, "list_connections", {"project_id": project_id})
                scopes = self._visible_scopes(bound, cursor, selected)
                cursor.execute("SELECT DISTINCT c.connection_ref,c.revision,c.route_class,c.status,c.expires_at,"
                               "e.endpoint_id,e.endpoint_revision,e.machine_id,e.node_id,e.expires_at "
                               "FROM deployment_connection_refs c JOIN delivery_endpoint_registrations e "
                               "USING(tenant_id,connection_ref) WHERE c.tenant_id=%s AND e.scope_id IN ("
                               "SELECT scope_id FROM collaboration_projects WHERE tenant_id=%s AND project_id=%s "
                               "UNION SELECT scope_id FROM collaboration_routes WHERE tenant_id=%s AND project_id=%s) "
                               "AND e.status='active' AND e.authority_id=%s AND e.authority_incarnation=%s "
                               "AND (%s::text[] IS NULL OR e.scope_id=ANY(%s))",
                               (self.context.tenant_id, self.context.tenant_id, project_id, self.context.tenant_id,
                                project_id, self.context.authority_id, self.context.authority_incarnation, scopes, scopes))
                for ref, revision, kind, state, expiry, endpoint, endpoint_revision, machine, node, endpoint_expiry in cursor.fetchall():
                    expires = min(expiry, endpoint_expiry)
                    rows.append({"connection_key": project_id + ":" + ref + ":" + endpoint,
                        "project_id": project_id, "connection_ref": ref, "revision": revision,
                        "kind": kind, "state": state if expires > datetime.now(UTC) else "expired",
                        "endpoint_id": endpoint, "endpoint_revision": endpoint_revision,
                        "machine_id": machine, "node_id": node, "expires_at": expires.isoformat(),
                        "evidence_class": "authority_observation"})
                cursor.execute("SELECT source_id,revision,current_commit,repository_identity FROM collaboration_sources s "
                               "WHERE tenant_id=%s AND project_id=%s AND (%s::text[] IS NULL OR EXISTS "
                               "(SELECT 1 FROM collaboration_routes r WHERE r.tenant_id=s.tenant_id AND r.project_id=s.project_id "
                               "AND r.scope_id=ANY(%s) AND COALESCE(r.definition->'source_binding_ids','[]') ? s.source_id) "
                               "OR EXISTS (SELECT 1 FROM collaboration_source_snapshots p WHERE p.tenant_id=s.tenant_id "
                               "AND p.project_id=s.project_id AND p.source_id=s.source_id AND p.source_commit=s.current_commit "
                               "AND p.snapshot_json->>'scope_id'=ANY(%s)))",
                               (self.context.tenant_id, project_id, scopes, scopes, scopes))
                rows.extend({"connection_key": project_id + ":source:" + row[0], "project_id": project_id,
                    "source_id": row[0], "revision": row[1], "commit": row[2], "repository": row[3],
                    "kind": "source", "state": "registered", "evidence_class": "authority_observation"}
                    for row in cursor.fetchall())
        rows = [row for row in rows if (not args.get("kinds") or row["kind"] in args["kinds"])
                and (not args.get("states") or row["state"] in args["states"])]
        return self._page_result(args.get("project_id"), rows, args, "connection_key")

    def _load_project(self, authority, cursor, project, command, args, credential):
        if args.get("at_revision") not in (None, project[2]):
            raise RevisionConflict(args["project_id"], args["at_revision"], project[2])
        data = {
            "schema_version": "acs-project-context-pack/1", "project_id": args["project_id"],
            "root_handle": handle("project", args["project_id"], project[1]),
            "project_revision": project[2], "manifest": project[3],
            "routes": self._list_routes(authority, cursor, project, command, args, credential)[1]["items"],
            "active_work": self._list_work(authority, cursor, project, command, args, credential)[1]["items"],
            "context_completeness": "partial", "missing_context": [],
        }
        data["missing_context"].extend("route_metadata_sync:" + item["route_handle"] for item in data["routes"]
            if item["definition"].get("management_source_state") == "source_sync_required")
        scopes = self._visible_scopes(authority, cursor, project)
        if scopes is not None:
            cursor.execute("SELECT definition->'context_manifest' FROM collaboration_routes "
                           "WHERE tenant_id=%s AND project_id=%s AND scope_id=%s",
                           (self.context.tenant_id, args["project_id"], scopes[0]))
            route_context = cursor.fetchone()
            data["manifest"] = route_context[0] if route_context and route_context[0] else {}
            data["context_scope_id"] = scopes[0]
            if not data["manifest"]:
                data["missing_context"] = ["route_scoped_source_hydration"]
                return "partial", data, []
            project = (*project[:3], data["manifest"], *project[4:])
        return self._hydrate_context(authority, cursor, project, command, args, data)

    def _snapshot(self, cursor, args):
        if self.sources is None:
            raise ValueError("Source provider is unavailable")
        cursor.execute("SELECT s.revision,s.current_commit,s.repository_identity,p.snapshot_json "
                       "FROM collaboration_sources s JOIN collaboration_source_snapshots p "
                       "ON (p.tenant_id,p.project_id,p.source_id)=(s.tenant_id,s.project_id,s.source_id) "
                       "AND p.source_commit=COALESCE(%s,s.current_commit) WHERE s.tenant_id=%s "
                       "AND s.project_id=%s AND s.source_id=%s",
                       (args.get("revision"), self.context.tenant_id, args["project_id"], args["source_id"]))
        row = cursor.fetchone()
        if row is None:
            raise NotFound("source_revision", args["source_id"])
        return row, self.sources.snapshot(row[3])

    def _list_sources(self, authority, cursor, project, _command, args, _credential):
        scopes = self._visible_scopes(authority, cursor, project)
        cursor.execute("SELECT source_id,revision,current_commit,repository_identity "
                       "FROM collaboration_sources s WHERE tenant_id=%s AND project_id=%s "
                       "AND (%s::text[] IS NULL OR EXISTS (SELECT 1 FROM collaboration_routes r "
                       "WHERE r.tenant_id=s.tenant_id AND r.project_id=s.project_id AND r.scope_id=ANY(%s) "
                       "AND COALESCE(r.definition->'source_binding_ids','[]') ? s.source_id) OR EXISTS "
                       "(SELECT 1 FROM collaboration_source_snapshots p WHERE p.tenant_id=s.tenant_id "
                       "AND p.project_id=s.project_id AND p.source_id=s.source_id AND p.source_commit=s.current_commit "
                       "AND p.snapshot_json->>'scope_id'=ANY(%s))) ORDER BY source_id",
                       (self.context.tenant_id, args["project_id"], scopes, scopes, scopes))
        return "observed", {"project_id": args["project_id"], "items": [
            {"source_id": row[0], "revision": row[1], "commit": row[2],
             "repository": row[3], "capabilities": ["read"], "provider": "local-node",
             "read": {"tool": "read_source", "arguments": {
                 "project_id": args["project_id"], "source_id": row[0]}}}
            for row in cursor.fetchall()]}, []

    def _source_read(self, name, authority, cursor, command, args):
        _row, snapshot = self._snapshot(cursor, args)
        method = getattr(self.sources, name)
        data = method(snapshot, args, authority, command)
        data.update(project_id=args["project_id"], source_id=args["source_id"])
        follow = []
        if data.get("next_start_line"):
            follow.append({"rel": "next", "tool": "read_file", "arguments":
                dict(args, start_line=data["next_start_line"])})
        if data.get("next_cursor"):
            follow.append({"rel": "next", "tool": name, "arguments":
                dict(args, cursor=data["next_cursor"])})
        return "observed", data, follow

    def _read_file(self, authority, cursor, _project, command, args, _credential):
        return self._source_read("read_file", authority, cursor, command, args)

    def _list_files(self, authority, cursor, _project, command, args, _credential):
        return self._source_read("list_files", authority, cursor, command, args)

    def _search_files(self, authority, cursor, _project, command, args, _credential):
        return self._source_read("search_files", authority, cursor, command, args)

    def _read_source(self, authority, cursor, _project, command, args, _credential):
        row, snapshot = self._snapshot(cursor, args)
        self.sources.verify(snapshot, authority, command)
        observed = self.sources.observe(snapshot, authority, command)
        current = (observed["commit"], observed["tree"], observed["working_tree"]) == (
            snapshot.source_commit, snapshot.source_tree, "clean")
        return "current" if current else "stale", dict(observed, project_id=args["project_id"],
            source_id=args["source_id"], binding_revision=row[0], repository=row[2],
            admitted_commit=snapshot.source_commit, admitted_tree=snapshot.source_tree,
            snapshot_digest=snapshot.snapshot_sha256), []

    def _read_diff(self, authority, cursor, _project, command, args, _credential):
        _, base = self._snapshot(cursor, dict(args, revision=args["base_revision"]))
        _, target = self._snapshot(cursor, dict(args, revision=args["target_revision"]))
        data = self.sources.read_diff(base, target, args, authority, command)
        return "observed", dict(data, project_id=args["project_id"], source_id=args["source_id"]), []

    def _hydrate_context(self, authority, cursor, project, command, args, data):
        manifest = project[3]
        management = manifest.get("management")
        follow = []
        if not management or self.sources is None:
            data["missing_context"] = ["source_hydration"]
            return "partial", data, follow
        maximum = self.sources.bound(args.get("max_inline_bytes", 65536), minimum=4096)
        include = set(args.get("include", ["root", "routes", "instructions", "knowledge_indexes",
                                           "source_bindings", "active_work", "policies"]))
        if include - {"root", "routes", "instructions", "knowledge_indexes", "source_bindings",
                      "active_work", "policies"}:
            raise ValueError("invalid project context include")
        if args.get("context_view", "root_management") not in {
                "root_management", "route_management", "reviewer", "finalizer"}:
            raise ValueError("invalid project context view")
        source_args = {"project_id": args["project_id"], "source_id": management["source_id"]}
        _, snapshot = self._snapshot(cursor, source_args)
        try:
            authority._authorize(command, cursor, "source.read", snapshot.scope_id)
            authority._authorize(command, cursor, "artifact.read", snapshot.scope_id)
        except AuthorizationDenied:
            data["missing_context"] = ["source_read_authorization"]
            return "partial", data, follow
        observed = self.sources.observe(snapshot, authority, command)
        stale = observed["commit"] != snapshot.source_commit or observed["tree"] != snapshot.source_tree or observed["working_tree"] != "clean"
        data["source_observation"] = observed
        data["management_root"] = dict(management, revision=snapshot.source_commit)
        data["source_bindings"] = self._list_sources(authority, cursor, project, command, args, None)[1]["items"]
        for label, key in (("instructions", "instruction_paths"), ("knowledge_indexes", "knowledge_index_paths")):
            if label not in include:
                continue
            data[label] = []
            for path in manifest.get(key, []):
                payload, item = self.sources.file_bytes(snapshot, path, authority, command)
                entry = {"path": path, "source_id": management["source_id"],
                         "revision": snapshot.source_commit, "sha256": item.sha256}
                text = payload.decode("utf-8")
                # Reserve metadata space and return an exact read when a full
                # instruction body does not fit. Never truncate instructions.
                if len(canonical(data).encode()) + len(payload) + 2048 < maximum:
                    entry["content"] = text
                else:
                    read = {"rel": "read_" + label, "tool": "read_file", "arguments": {
                        **source_args, "path": path, "revision": snapshot.source_commit,
                        "max_inline_bytes": min(maximum, 32768)}}
                    follow.append(read)
                    entry["read"] = read
                    data["missing_context"].append(path)
                data[label].append(entry)
        self._verify_management_identity(authority, cursor, project, command,
                                         args["project_id"], require_current=False)
        try:
            current_paths = [*manifest.get("instruction_paths", []),
                             *manifest.get("knowledge_index_paths", [])]
            if current_paths:
                self.sources.verify_current_paths(snapshot, current_paths, authority, command)
        except SourceChangedDuringSnapshot:
            stale = True
        data["skills"] = []
        skill_catalog = manifest.get("skill_catalog")
        if skill_catalog:
            _, skill_snapshot = self._snapshot(cursor, {**source_args,
                "source_id": skill_catalog["source_id"]})
            raw, _ = self.sources.file_bytes(skill_snapshot, skill_catalog["path"], authority, command)
            catalog = json.loads(raw)
            for name, skill in catalog["skills"].items():
                data["skills"].append({"name": name, "description": skill["description"]})
            primary = "acs-project-context"
            if primary in catalog["skills"]:
                spec = self.sources.skill_spec(skill_catalog["path"], catalog["skills"][primary]["spec"])
                follow.append({"rel": "read_skill", "skill": primary, "tool": "read_file", "arguments": {
                    "project_id": args["project_id"], "source_id": skill_catalog["source_id"],
                    "path": spec, "revision": skill_snapshot.source_commit}})
                data["knowledge_hint"] = [{"skill": primary, "topic": "Project identity and context",
                    "reason": "Project context loaded", "reference": "references/model.md"}]
        if "policies" in include:
            cursor.execute("SELECT s.policy,g.permissions,g.expires_at FROM scopes s JOIN grants g "
                           "ON g.scope_id=s.scope_id AND g.tenant_id=s.tenant_id "
                           "WHERE g.grant_ref=%s AND g.tenant_id=%s",
                           (authority.context.grant_ref, self.context.tenant_id))
            policy, permissions, expires = cursor.fetchone()
            data["policy"] = policy
            data["grant_summary"] = {"permissions": permissions, "expires_at": expires.isoformat(),
                                     "profile": self.profile}
        data["context_completeness"] = "stale" if stale else "partial" if data["missing_context"] else "current"
        if len(canonical(data).encode()) > maximum:
            raise ValueError("project metadata exceeds requested context bound")
        return data["context_completeness"], data, follow

    def _verify_management_identity(self, authority, cursor, project, command,
                                    project_id, *, require_current):
        management = project[3]["management"]
        if self.sources is None:
            raise ValueError("Management Source is unavailable")
        _, snapshot = self._snapshot(cursor, {"project_id": project_id,
                                             "source_id": management["source_id"]})
        prefix = self.sources.path(management["path"], root=True)
        prefix = prefix + "/" if prefix else ""
        identity_path, agents_path = prefix + ".agents/manifest.json", prefix + "AGENTS.md"
        identity = json.loads(self.sources.file_bytes(snapshot, identity_path, authority, command)[0])
        agents = self.sources.file_bytes(snapshot, agents_path, authority, command)[0].decode("utf-8")
        blocks = re.findall(r"<!-- ACS-PROJECT:BEGIN -->(.*?)<!-- ACS-PROJECT:END -->", agents, re.DOTALL)
        if (identity.get("project_id") != project_id or identity.get("root_id") != project[1]
                or len(blocks) != 1
                or re.findall(r"^project_id: ([A-Za-z0-9._-]+)\r?$", blocks[0], re.MULTILINE) != [project_id]):
            raise ValueError("Management Project/Root identity differs")
        if require_current:
            # Ordinary engineering edits do not revoke project management.
            # Source-dependent commands check their own baseline separately;
            # this invariant binds only the stable Management identity bytes.
            self.sources.verify_current_paths(snapshot, [identity_path, agents_path], authority, command)

    def _list_routes(self, authority, cursor, project, _command, args, _credential):
        scopes = self._visible_scopes(authority, cursor, project)
        limit, after, since = self._list_bounds(args, "route")
        states = args.get("states", [])
        cursor.execute("SELECT route_id,scope_id,revision,state,definition FROM collaboration_routes "
                       "WHERE tenant_id=%s AND project_id=%s AND (%s::text[] IS NULL OR scope_id=ANY(%s)) "
                       "AND route_id>%s AND (%s::timestamptz IS NULL OR updated_at>%s) "
                       "AND (%s::text[]='{}'::text[] OR state=ANY(%s)) ORDER BY route_id LIMIT %s",
                       (self.context.tenant_id, args["project_id"], scopes, scopes, after, since, since, states, states, limit+1))
        rows = [{"route_handle": handle("route", args["project_id"], row[0]),
            "scope_id": row[1], "revision": row[2], "state": row[3], "definition": row[4]}
            for row in cursor.fetchall()]
        return self._page_result(args["project_id"], rows, args, "route_handle")

    def _list_work(self, authority, cursor, project, _command, args, _credential):
        scopes = self._visible_scopes(authority, cursor, project)
        limit, after, since = self._list_bounds(args, "work")
        route_id = parse_handle(args["route_handle"], "route", args["project_id"]) if args.get("route_handle") else None
        assigned = args.get("assigned_to")
        if assigned and assigned.startswith("collaborator:"):
            assigned = parse_handle(assigned, "collaborator", args["project_id"])
        states, blocked = args.get("states", []), args.get("blocked")
        cursor.execute(
            "SELECT w.work_item_id,w.revision,w.state,w.execution_status,w.source_baseline,w.agent_slot_id,l.route_id "
            "FROM collaboration_work_links l JOIN work_items w USING(tenant_id,work_item_id) "
            "WHERE l.tenant_id=%s AND l.project_id=%s AND (%s::text[] IS NULL OR w.scope_id=ANY(%s)) "
            "AND (%s::text IS NULL OR l.route_id=%s) AND (%s::text IS NULL OR w.agent_slot_id=%s) "
            "AND w.work_item_id>%s AND (%s::timestamptz IS NULL OR w.updated_at>%s) "
            "AND (%s::text[]='{}'::text[] OR w.state=ANY(%s)) "
            "AND (%s::boolean IS NULL OR (w.execution_status='blocked')=%s) ORDER BY w.work_item_id LIMIT %s",
            (self.context.tenant_id, args["project_id"], scopes, scopes, route_id, route_id, assigned, assigned,
             after, since, since, states, states, blocked, blocked, limit+1),
        )
        rows = [{"work_handle": handle("work", args["project_id"], row[0]),
            "revision": row[1], "state": row[2], "execution_status": row[3],
            "source_baseline": row[4], "assigned_to": row[5],
            "route_handle": handle("route", args["project_id"], row[6])} for row in cursor.fetchall()]
        return self._page_result(args["project_id"], rows, args, "work_handle")

    def _create_work(self, authority, cursor, project, command, args, _credential):
        route_id = parse_handle(args["route_handle"], "route", args["project_id"])
        cursor.execute("SELECT revision,scope_id FROM collaboration_routes WHERE tenant_id=%s "
                       "AND project_id=%s AND route_id=%s AND state='active' FOR UPDATE",
                       (self.context.tenant_id, args["project_id"], route_id))
        route = cursor.fetchone()
        if route is None:
            raise NotFound("route", route_id)
        if route[0] != args["expected_route_revision"]:
            raise RevisionConflict(route_id, args["expected_route_revision"], route[0])
        work_handle = handle("work", args["project_id"], args["work_item_id"])
        if args["accepted_state"] != {"revision": 0}:
            raise ValueError("new WorkItem requires genesis accepted revision")
        domain_command = command.model_copy(update={"command_type": "work_item.create",
            "target_kind": "work_item", "target_id": args["work_item_id"],
            "expected_revision": 0})
        result = authority.create_work_item(domain_command, route[1], project[5], args["source_baseline"])
        cursor.execute("INSERT INTO collaboration_work_links VALUES (%s,%s,%s,%s,%s)",
                       (self.context.tenant_id, args["project_id"], args["work_item_id"],
                        route_id, canonical(args)))
        return "created", dict(result.model_dump(mode="json"), project_id=args["project_id"],
                               work_handle=work_handle), []

    def _send_message(self, authority, cursor, project, command, args, _credential):
        # Validate bounded observation options before the durable command. A
        # malformed sync request must never commit and then report rejection.
        wait_timeout = args.get("wait_timeout_seconds", 30)
        if (type(wait_timeout) is not int or not 0 <= wait_timeout <= 30
                or args.get("wait_until", "response_received") not in (*RECEIPTS, "terminal")):
            raise ValueError("invalid synchronous observation bound")
        work_id = parse_handle(args["work_handle"], "work", args["project_id"])
        cursor.execute(
            "SELECT w.scope_id,w.source_baseline FROM collaboration_work_links l "
            "JOIN work_items w USING(tenant_id,work_item_id) WHERE l.tenant_id=%s "
            "AND l.project_id=%s AND l.work_item_id=%s FOR UPDATE OF w",
            (self.context.tenant_id, args["project_id"], work_id),
        )
        work = cursor.fetchone()
        if work is None:
            raise NotFound("work_item", work_id)
        target = args["target"]
        if (set(target) != {"scope_id", "agent_slot_id"} or target["scope_id"] != work[0]):
            raise ValueError("target Scope does not belong to the WorkItem")
        cursor.execute(
            "SELECT endpoint_id,revision FROM delivery_endpoints WHERE tenant_id=%s "
            "AND scope_id=%s AND agent_slot_id=%s AND status='active' "
            "AND expires_at>clock_timestamp() ORDER BY endpoint_id FOR UPDATE",
            (self.context.tenant_id, work[0], target["agent_slot_id"]),
        )
        endpoints = cursor.fetchall()
        if len(endpoints) != 1:
            raise ValueError("delivery needs one current admitted endpoint")
        if args.get("delivery_policy", "queue_until_idle") != "queue_until_idle":
            raise ValueError("active-turn steering is unavailable in this delivery adapter")
        cursor.execute("SELECT policy FROM scopes WHERE tenant_id=%s AND scope_id=%s",
                       (self.context.tenant_id, work[0]))
        configured_team = cursor.fetchone()[0].get("collaboration_team")
        if configured_team and any(args.get("delivery_policy", "queue_until_idle") not in
                item["rules"]["allowed_delivery_policies"] for item in configured_team["policies"]):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        if args.get("response_mode", "async") not in {"async", "sync"}:
            raise ValueError("invalid response mode")
        message_id = "message-" + uuid.uuid4().hex
        response_handle = handle("response", args["project_id"], message_id)
        packet = {"work_item_id": work_id, "target_scope_id": work[0],
                  "target_agent_slot_id": target["agent_slot_id"],
                  "accepted_revision": args["accepted_revision"], "goal": args["goal"],
                  "accepted_state_summary": "Read authoritative accepted revision " + str(args["accepted_revision"]),
                  "request": args["request"], "constraints": args["constraints"],
                  "source_baseline": work[1], "expected_response": "Structured response with required evidence",
                  "required_evidence": args["required_evidence"],
                  "activation": args.get("activation", "invoke"), "delivery_policy": "queue_until_idle",
                  "deadline": args["deadline"]}
        request = SurfaceCommand(
            command_type="message.send", target_kind="message", target_id=message_id,
            expected_revision=args["expected_work_revision"], command_id=command.command_id,
            idempotency_key=command.idempotency_key, correlation_id=command.correlation_id,
            issued_at=command.issued_at, deadline=command.deadline,
            payload={"packet": packet, "endpoint_id": endpoints[0][0],
                     "binding_revision": endpoints[0][1]},
        )
        # Reuse the Domain handler called by CLI and versioned HTTP. Transport
        # authentication precedes resolution of the stored project Grant.
        result = authority.send_message(request.to_domain(authority.context),
            DeliveryPacket.model_validate(packet),
            endpoint_id=endpoints[0][0], binding_revision=endpoints[0][1])
        cursor.execute(
            "INSERT INTO collaboration_response_tracking(tenant_id,project_id,message_id,"
            "initiating_principal,initiating_slot,response_handle,delivery_policy,expect_response) "
            "VALUES (%s,%s,%s,%s,%s,%s,'queue_until_idle',%s)",
            (self.context.tenant_id, args["project_id"], message_id, self.context.principal_ref,
             project[5], response_handle, args.get("expect_response", True)),
        )
        cursor.execute("INSERT INTO collaboration_response_subscriptions(tenant_id,project_id,message_id) "
                       "VALUES (%s,%s,%s)", (self.context.tenant_id, args["project_id"], message_id))
        return "accepted", dict(result.model_dump(mode="json"), project_id=args["project_id"],
            message_id=message_id, message_handle=handle("message", args["project_id"], message_id),
            response_handle=response_handle,
            notification_handle=handle("subscription", args["project_id"], message_id)), [
                {"rel": "read_response", "tool": "read_message", "arguments": {
                    "project_id": args["project_id"], "handle": response_handle, "consume": True}},
                {"rel": "wait", "tool": "wait_for_response", "arguments": {
                    "project_id": args["project_id"], "handles": [response_handle],
                    "mode": "all", "until": "response_received", "timeout_seconds": 30}},
            ]

    def _read_message(self, authority, cursor, _project, command, args, _credential):
        kind = args["handle"].split(":", 1)[0]
        if kind == "notification":
            return self._read_notification(cursor, args)
        if kind == "review":
            return self._read_review_message(cursor, args)
        if kind not in {"message", "response"}:
            raise ValueError("message or response handle required")
        message_id = parse_handle(args["handle"], kind, args["project_id"])
        cursor.execute("SELECT t.initiating_principal,m.command_json->>'principal_ref',i.target_agent_slot_id "
                       "FROM delivery_messages m JOIN collaboration_work_links l "
                       "ON l.tenant_id=m.tenant_id AND l.work_item_id=m.packet_json->>'work_item_id' "
                       "LEFT JOIN collaboration_response_tracking t ON t.tenant_id=m.tenant_id AND t.message_id=m.message_id AND t.project_id=l.project_id "
                       "LEFT JOIN inbox_messages i ON i.tenant_id=m.tenant_id AND i.message_id=m.message_id "
                       "WHERE m.tenant_id=%s AND l.project_id=%s AND m.message_id=%s",
                       (self.context.tenant_id, args["project_id"], message_id))
        row = cursor.fetchone()
        if row is None or (kind == "response" and row[0] is None):
            raise NotFound("message", message_id)
        observed = authority.read_message(command.model_copy(update={
            "command_type": "message.read", "target_kind": "message", "target_id": message_id,
        }), message_id)
        message = observed["message"]
        if kind == "response" and args.get("consume", True) and message["receipt_high_water"] == "response_received":
            if row[0] != self.context.principal_ref:
                raise AuthorizationDenied(self.context.principal_ref, authority.context.grant_ref)
            cursor.execute("UPDATE collaboration_response_subscriptions SET consumed_at=clock_timestamp() "
                           "WHERE tenant_id=%s AND project_id=%s AND message_id=%s "
                           "AND consumed_at IS NULL",
                           (self.context.tenant_id, args["project_id"], message_id))
        # Raw delivery commands contain private authorization references and are
        # not an MCP response. Expose only explicitly selected observation fields.
        consumed = self._inbox_consumed(cursor, args["project_id"], "message", message_id, 1) if kind == "message" else False
        if kind == "message" and row[2] and args.get("consume", True):
            if self._owns_inbox_slot(cursor, args["project_id"], row[2]):
                self._consume_inbox(cursor, args["project_id"], "message", message_id, 1)
                consumed = True
            elif row[1] != self.context.principal_ref:
                raise AuthorizationDenied(self.context.principal_ref, authority.context.grant_ref)
        data = {"project_id": args["project_id"], "message_id": message_id,
            "response_handle": handle("response", args["project_id"], message_id),
            "state": message["state"], "receipt_high_water": message["receipt_high_water"],
            "operation_id": message["operation_id"], "receipts": observed["receipts"]}
        if kind == "message":
            if row[0] is None:
                data.pop("response_handle")
            data.update(kind="message", message_handle=handle("message", args["project_id"], message_id), consumed=consumed, content={key: message["packet_json"][key]
                for key in ("goal", "request", "constraints", "source_baseline", "required_evidence", "expected_response")})
            self._inbox_bound(data, args)
        return "observed", data, []

    def _check_inbox(self, authority, cursor, project, command, args, credential):
        scopes = self._visible_scopes(authority, cursor, project)
        cursor.execute(
            "SELECT t.response_handle FROM collaboration_response_tracking t "
            "JOIN collaboration_response_subscriptions s USING(tenant_id,project_id,message_id) "
            "JOIN delivery_messages m USING(tenant_id,message_id) "
            "WHERE t.tenant_id=%s AND t.project_id=%s AND t.initiating_principal=%s "
            "AND s.consumed_at IS NULL AND t.response_handle>%s AND (%s::text[]='{}' OR m.state=ANY(%s)) "
            "AND (%s::text[] IS NULL OR m.packet_json->>'target_scope_id'=ANY(%s)) "
            "ORDER BY t.response_handle LIMIT 101",
            (self.context.tenant_id, args["project_id"], self.context.principal_ref, args.get("cursor") or "",
             args.get("states", []), args.get("states", []), scopes, scopes),
        )
        handles = [row[0] for row in cursor.fetchall()]
        items = []
        for item in handles:
            read_args = {"project_id": args["project_id"], "handle": item, "consume": False}
            try:
                scoped, selected, read_command = self._authorize(authority, cursor, args["project_id"], "read_message", read_args)
            except AuthorizationDenied:
                continue
            value = self._read_message(scoped, cursor, selected, read_command, read_args, credential)[1]
            items.append({key: value[key] for key in ("message_id", "response_handle", "state", "receipt_high_water", "operation_id")}
                         | {"kind": "response", "handle": item, "read": {"tool": "read_message", "arguments": dict(read_args, consume=True)}})
        items.extend(self._incoming_inbox(authority, cursor, project, command, args, credential))
        items.extend(self._review_inbox(authority, cursor, project, command, args, credential))
        kinds, states = args.get("kinds", []), args.get("states", [])
        if set(kinds) - {"message", "response", "review", "notification"}:
            raise ValueError("unknown Inbox kind")
        items = [item for item in items if (not kinds or item["kind"] in kinds) and (not states or item["state"] in states)]
        _, page, _ = self._page_result(args["project_id"], items, args, "handle")
        notifications = self._notification_inbox(cursor, args["project_id"]) if not kinds or "notification" in kinds else []
        return "observed", {**page,
                            "notifications": notifications}, []

    def _wait(self, args, credential):
        timeout = args["timeout_seconds"]
        if (type(timeout) is not int or not 0 <= timeout <= 30 or args["mode"] not in {"any", "all"}
                or args["until"] not in (*RECEIPTS, "terminal") or not 1 <= len(args["handles"]) <= 32
                or len(set(args["handles"])) != len(args["handles"])):
            raise ValueError("invalid bounded wait")
        for value in args["handles"]:
            parse_handle(value, "response", args["project_id"])
        end = time.monotonic() + timeout
        while True:
            observations = [self.execute("read_message", {"project_id": args["project_id"],
                "handle": item, "consume": False}, credential)[1] for item in args["handles"]]
            terminal = [item["response_handle"] for item in observations
                        if item["state"] in {"blocked", "expired", "budget_exhausted", "uncertain"}
                        or "response_received" in {receipt[0] for receipt in item["receipts"]}]
            satisfied = [item["response_handle"] for item in observations
                         if (item["response_handle"] in terminal if args["until"] == "terminal"
                             else args["until"] in {receipt[0] for receipt in item["receipts"]})]
            ready = len(satisfied) == len(observations) if args["mode"] == "all" else bool(satisfied)
            pending = [item for item in args["handles"] if item not in satisfied and item not in terminal]
            if ready or not pending or time.monotonic() >= end:
                return "satisfied" if ready else "terminal" if not pending else "timeout", {"project_id": args["project_id"],
                    "satisfied": satisfied,
                    "pending": pending, "terminal": terminal,
                    "observations": observations}, []
            time.sleep(min(0.1, max(0, end - time.monotonic())))
