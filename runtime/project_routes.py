"""Durable Route identity and explicitly delegated, distinct Domain Scopes."""
from __future__ import annotations

import json
from copy import copy
from dataclasses import replace
from datetime import datetime
from pathlib import PurePosixPath

from runtime.errors import AuthorizationDenied, NotFound, RevisionConflict
from runtime.project_common import IDENTIFIER, canonical, digest, handle, parse_handle


class RouteActions:
    @staticmethod
    def _list_bounds(args, kind):
        limit = args.get("limit", 50)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid page size")
        after = parse_handle(args["cursor"], kind, args["project_id"]) if args.get("cursor") else ""
        since = datetime.fromisoformat(args["updated_since"]) if args.get("updated_since") else None
        if since is not None and since.tzinfo is None:
            raise ValueError("updated_since requires a timezone")
        return limit, after, since

    def _route_sources(self, cursor, project_id, source_ids):
        if len(source_ids) != len(set(source_ids)) or len(source_ids) > 32:
            raise ValueError("Route SourceBindings must be unique and bounded")
        for source_id in source_ids:
            cursor.execute("SELECT 1 FROM collaboration_sources WHERE tenant_id=%s AND project_id=%s AND source_id=%s",
                           (self.context.tenant_id, project_id, source_id))
            if cursor.fetchone() is None:
                raise NotFound("source_binding", source_id)

    def _create_route(self, authority, cursor, project, command, args, _credential):
        root = parse_handle(args["root_handle"], "project", args["project_id"])
        if root != project[1]:
            raise NotFound("root", root)
        authority._authorize(command, cursor, "routes.manage", project[0])
        authority._authorize(command, cursor, "grants.manage", project[0])
        if project[2] != args["expected_root_revision"]:
            raise RevisionConflict(root, args["expected_root_revision"], project[2])
        route_id = args["route_id"]
        if (not IDENTIFIER.fullmatch(route_id) or not 1 <= len(args["display_name"]) <= 256
                or not 1 <= len(args["goal"]) <= 8192):
            raise ValueError("invalid Route metadata")
        self._route_sources(cursor, args["project_id"], args["source_binding_ids"])
        cursor.execute("SELECT 1 FROM collaboration_routes WHERE tenant_id=%s AND project_id=%s AND route_id=%s",
                       (self.context.tenant_id, args["project_id"], route_id))
        if cursor.fetchone():
            raise ValueError("Route already exists")
        identity = digest([self.context.tenant_id, args["project_id"], route_id])
        scope, slot, grant = "scope-" + identity, "slot-" + identity, "grant:route:" + identity
        cursor.execute("SELECT g.permissions,g.expires_at,s.policy FROM grants g JOIN scopes s USING(scope_id) "
                       "WHERE g.grant_ref=%s FOR UPDATE OF g,s", (authority.context.grant_ref,))
        permissions, expiry, parent_policy = cursor.fetchone()
        # Copy the non-team policy boundary. The Route's team and execution
        # capacity are configured separately; no parent Slot or budget is reused.
        scope_policy = {key: value for key, value in parent_policy.items() if key != "collaboration_team"}
        cursor.execute("INSERT INTO scopes VALUES (%s,%s,%s,'active')",
                       (scope, self.context.tenant_id, canonical(scope_policy)))
        cursor.execute("INSERT INTO agent_slots VALUES (%s,%s,%s,'active')", (slot, self.context.tenant_id, scope))
        cursor.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,"
                       "scope_id,permissions,expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                       (grant, self.context.tenant_id, command.principal_ref, command.authority_id,
                        command.authority_incarnation, scope, canonical(permissions), expiry))
        cursor.execute("INSERT INTO grant_delegations(grant_ref,parent_grant_ref,tenant_id,command_id,parent_policy_digest) "
                       "VALUES (%s,%s,%s,%s,%s)",
                       (grant, authority.context.grant_ref, self.context.tenant_id, command.command_id, digest(parent_policy)))
        definition = {"display_name": args["display_name"], "goal": args["goal"],
                      "source_binding_ids": args["source_binding_ids"], "root_id": root,
                      "management_source_state": "not_materialized"}
        cursor.execute("INSERT INTO collaboration_routes(tenant_id,project_id,route_id,scope_id,definition) "
                       "VALUES (%s,%s,%s,%s,%s)",
                       (self.context.tenant_id, args["project_id"], route_id, scope, canonical(definition)))
        cursor.execute("INSERT INTO collaboration_route_grants VALUES (%s,%s,%s,%s,%s,%s,%s)",
                       (self.context.tenant_id, args["project_id"], route_id, command.principal_ref,
                        self.profile, grant, slot))
        cursor.execute("UPDATE collaboration_projects SET revision=revision+1 WHERE tenant_id=%s AND project_id=%s",
                       (self.context.tenant_id, args["project_id"]))
        result = self._management_record(authority, cursor, command, args, target_kind="route",
            target_id=route_id, state="route.created", revision=1)
        return "created", {"project_id": args["project_id"], "route_handle": handle("route", args["project_id"], route_id),
            "scope_handle": handle("scope", args["project_id"], scope), "revision": 1,
            "root_revision": project[2]+1, "operation_id": result.operation_id,
            "management_source_state": "not_materialized"}, []

    def _update_route(self, authority, cursor, project, command, args, _credential):
        route_id = parse_handle(args["route_handle"], "route", args["project_id"])
        cursor.execute("SELECT scope_id,revision,state,definition FROM collaboration_routes "
                       "WHERE tenant_id=%s AND project_id=%s AND route_id=%s FOR UPDATE",
                       (self.context.tenant_id, args["project_id"], route_id))
        row = cursor.fetchone()
        if row is None:
            raise NotFound("route", route_id)
        authority._authorize(command, cursor, "routes.manage", row[0])
        if args["expected_revision"] != row[1]:
            raise RevisionConflict(route_id, args["expected_revision"], row[1])
        changes = args["changes"]
        if not changes or set(changes) - {"display_name", "goal", "state", "source_binding_ids", "context_manifest"}:
            raise ValueError("Route identity and Scope are immutable")
        state = changes.get("state", row[2])
        if state not in {"discovered", "active", "paused", "completed", "archived"}:
            raise ValueError("unknown Route lifecycle state")
        for key, maximum in (("display_name", 256), ("goal", 8192)):
            if key in changes and (not isinstance(changes[key], str) or not 1 <= len(changes[key]) <= maximum):
                raise ValueError("invalid Route text")
        if "source_binding_ids" in changes:
            values = changes["source_binding_ids"]
            if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
                raise ValueError("invalid Route SourceBindings")
            self._route_sources(cursor, args["project_id"], values)
        if "context_manifest" in changes:
            manifest = changes["context_manifest"]
            if (not isinstance(manifest, dict) or set(manifest) - {
                    "management", "instruction_paths", "knowledge_index_paths", "skill_catalog", "route_path"}
                    or not {"management", "instruction_paths"} <= set(manifest)
                    or not isinstance(manifest["management"], dict)
                    or set(manifest["management"]) != {"source_id", "path"}):
                raise ValueError("invalid Route context manifest")
            _, snapshot = self._snapshot(cursor, {"project_id": args["project_id"],
                                                  "source_id": manifest["management"]["source_id"]})
            if (snapshot.scope_id, snapshot.route_id) != (row[0], route_id):
                raise ValueError("Route context needs its own admitted Source Scope")
            available = {item.path for item in snapshot.files}
            for key in ("instruction_paths", "knowledge_index_paths"):
                paths = manifest.get(key, [])
                if (not isinstance(paths, list) or len(paths) > 32 or any(not isinstance(path, str) for path in paths)
                        or len(paths) != len(set(paths)) or any(path not in available for path in paths)):
                    raise ValueError("Route context paths must be admitted and bounded")
            if not manifest["instruction_paths"]:
                raise ValueError("Route context requires its instructions")
            if "skill_catalog" in manifest:
                catalog = manifest["skill_catalog"]
                if (not isinstance(catalog, dict) or set(catalog) != {"source_id", "path"}
                        or catalog["source_id"] != manifest["management"]["source_id"]
                        or catalog["path"] not in available):
                    raise ValueError("Skill catalog must share the admitted Route context Source")
            self._verify_management_identity(authority, cursor,
                (*project[:3], manifest, *project[4:]), command, args["project_id"], require_current=True)
        definition = {**row[3], **{key: value for key, value in changes.items() if key != "state"}}
        if (definition.get("management_source_readback") and "context_manifest" not in changes
                and (state != row[2] or definition.get("display_name") != row[3].get("display_name"))):
            # Git registry ownership is not silently transferred to a PG-only
            # metadata update. Retain the last imported revision and surface the
            # reconciliation requirement until direct Source readback matches.
            definition["management_source_state"] = "source_sync_required"
        if "context_manifest" in changes:
            definition["management_source_state"] = "not_materialized"
            definition.pop("management_source_readback", None)
            manifest = changes["context_manifest"]
            if manifest.get("route_path"):
                route_path = self.sources.path(manifest["route_path"])
                management = self.sources.path(manifest["management"]["path"], root=True)
                relative = PurePosixPath(route_path).relative_to(PurePosixPath(management)).as_posix()
                registry_path = (management + "/" if management else "") + ".agents/coordination/routes.yaml"
                metadata_path = route_path + "/.agents/route.yaml"
                raw_registry, registry_file = self.sources.file_bytes(snapshot, registry_path, authority, command)
                raw_metadata, metadata_file = self.sources.file_bytes(snapshot, metadata_path, authority, command)
                registry, metadata = json.loads(raw_registry), json.loads(raw_metadata)
                entries = [entry for entry in registry["routes"] if entry["id"] == route_id]
                if (registry.get("root_id") != project[1] or len(entries) != 1
                        or (entries[0]["path"], entries[0]["display_name"], entries[0]["status"]) != (
                            relative, definition["display_name"], state)
                        or (metadata.get("root_id"), metadata.get("route_id"), metadata.get("path")) != (
                            project[1], route_id, relative)
                        or route_path + "/AGENTS.md" not in manifest["instruction_paths"]):
                    raise ValueError("Route registry and metadata Source identity differs")
                self.sources.verify_current_paths(snapshot, [registry_path, metadata_path, route_path + "/AGENTS.md"], authority, command)
                definition["management_source_state"] = "adopted"
                definition["management_source_readback"] = {"source_id": manifest["management"]["source_id"],
                    "source_commit": snapshot.source_commit, "source_tree": snapshot.source_tree,
                    "route_path": route_path, "registry_sha256": registry_file.sha256,
                    "metadata_sha256": metadata_file.sha256}
        cursor.execute("UPDATE collaboration_routes SET state=%s,definition=%s,revision=revision+1,updated_at=clock_timestamp() "
                       "WHERE tenant_id=%s AND project_id=%s AND route_id=%s",
                       (state, canonical(definition), self.context.tenant_id, args["project_id"], route_id))
        result = self._management_record(authority, cursor, command, args, target_kind="route",
            target_id=route_id, state="route.updated", revision=row[1]+1)
        return "updated", {"project_id": args["project_id"], "route_handle": args["route_handle"],
            "scope_handle": handle("scope", args["project_id"], row[0]), "revision": row[1]+1,
            "state": state, "operation_id": result.operation_id}, []

    def _requested_scope(self, cursor, project_id, args):
        """Resolve a typed resource's project-bound Scope, never a body claim."""
        if args.get("source_id"):
            cursor.execute("SELECT p.snapshot_json->>'scope_id' FROM collaboration_source_snapshots p "
                           "JOIN collaboration_sources s USING(tenant_id,project_id,source_id) "
                           "WHERE p.tenant_id=%s AND p.project_id=%s AND p.source_id=%s "
                           "AND p.source_commit=COALESCE(%s,s.current_commit)",
                           (self.context.tenant_id, project_id, args["source_id"], args.get("revision")))
            row = cursor.fetchone()
            if row is None:
                raise NotFound("source", args["source_id"])
            return row[0]
        for field in ("work_handle", "route_handle", "scope_handle", "attempt_handle", "review_handle", "target_handle", "handle"):
            value = args.get(field)
            if not value:
                continue
            kind = value.split(":", 1)[0]
            identifier = parse_handle(value, kind, project_id)
            parameters = (self.context.tenant_id, project_id, identifier)
            if kind == "scope":
                return self._scope(cursor, *parameters[:2], value)
            if kind == "route":
                cursor.execute("SELECT scope_id FROM collaboration_routes WHERE tenant_id=%s AND project_id=%s AND route_id=%s", parameters)
            elif kind == "work":
                cursor.execute("SELECT w.scope_id FROM collaboration_work_links l JOIN work_items w USING(tenant_id,work_item_id) "
                               "WHERE l.tenant_id=%s AND l.project_id=%s AND l.work_item_id=%s", parameters)
            elif kind in {"message", "response"}:
                cursor.execute("SELECT m.packet_json->>'target_scope_id' FROM delivery_messages m "
                               "JOIN collaboration_work_links l ON l.tenant_id=m.tenant_id AND l.work_item_id=m.packet_json->>'work_item_id' "
                               "WHERE l.tenant_id=%s AND l.project_id=%s AND m.message_id=%s", parameters)
            elif kind in {"review", "evidence"}:
                table = "collaboration_review_requests" if kind == "review" else "evidence"
                identity = "request_id" if kind == "review" else "evidence_id"
                cursor.execute(f"SELECT w.scope_id FROM {table} e JOIN collaboration_work_links l USING(tenant_id,work_item_id) "
                               "JOIN work_items w USING(tenant_id,work_item_id) "
                               f"WHERE l.tenant_id=%s AND l.project_id=%s AND e.{identity}=%s", parameters)
            else:
                continue
            row = cursor.fetchone()
            if row is None:
                raise NotFound(kind, identifier)
            return row[0]
        return None

    def _route_authority(self, authority, cursor, project_id, project, scope, permissions, args):
        cursor.execute("SELECT scope_id FROM grants WHERE grant_ref=%s", (project[4],))
        member_scope = cursor.fetchone()[0]
        self._scope(cursor, self.context.tenant_id, project_id, handle("scope", project_id, member_scope))
        scope = scope or member_scope
        grant, slot = project[4], project[5]
        if scope != member_scope:
            cursor.execute("SELECT g.grant_ref,g.agent_slot_id FROM collaboration_route_grants g "
                           "JOIN collaboration_routes r USING(tenant_id,project_id,route_id) "
                           "WHERE g.tenant_id=%s AND g.project_id=%s AND g.principal_ref=%s AND g.profile=%s AND r.scope_id=%s",
                           (self.context.tenant_id, project_id, self.context.principal_ref, self.profile, scope))
            mapped = cursor.fetchone()
            if mapped is None:
                raise AuthorizationDenied(self.context.principal_ref, authority.context.grant_ref)
            grant, slot = mapped
            cursor.execute("WITH RECURSIVE ancestry AS (SELECT %s::text AS ref,0 AS depth UNION ALL "
                           "SELECT d.parent_grant_ref,a.depth+1 FROM ancestry a JOIN grant_delegations d "
                           "ON d.grant_ref=a.ref WHERE a.depth<8) SELECT 1 FROM ancestry WHERE ref=%s",
                           (grant, project[4]))
            if cursor.fetchone() is None:
                raise AuthorizationDenied(self.context.principal_ref, authority.context.grant_ref)
        bound = copy(authority)
        bound.context = replace(authority.context, grant_ref=grant)
        command = self._command(bound, "project." + args["_tool_name"], {key: value for key, value in args.items() if key != "_tool_name"})
        for permission in permissions:
            bound._authorize(command, cursor, permission, scope)
        return bound, (*project[:4], grant, slot), command

    @staticmethod
    def _visible_scopes(authority, cursor, project):
        cursor.execute("SELECT scope_id FROM grants WHERE grant_ref=%s", (authority.context.grant_ref,))
        scope = cursor.fetchone()[0]
        # A project Root Grant admits project-level metadata. A Route Grant
        # admits only its own Scope; direct resource reads resolve it separately.
        return None if scope == project[0] else [scope]
