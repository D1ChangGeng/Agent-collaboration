"""Current project/source reads and participant-scoped communication activity."""
from __future__ import annotations

import base64

from runtime.artifacts import ArtifactError
from runtime.errors import InvalidToolArgument, NotFound, RevisionConflict
from runtime.models import ArtifactRef
from runtime.project_common import canonical, handle, parse_handle
from runtime.project_source import read_artifact_reference
from runtime.source import SourceError


class ResourceActions:
    def _list_activity(self, authority, cursor, project, _command, args, _credential):
        project_id = args["project_id"]
        address = self._communication_address(cursor, project_id)
        scopes = self._visible_scopes(authority, cursor, project)
        after = int(args.get("cursor") or 0)
        limit = args.get("limit", 50)
        if type(limit) is not int or not 1 <= limit <= 100 or after < 0:
            raise InvalidToolArgument("cursor", "Use the returned activity cursor and a limit from 1 to 100.")
        kind = target = None
        if args.get("target_handle"):
            kind = args["target_handle"].split(":", 1)[0]
            target = parse_handle(args["target_handle"], kind, project_id)
            if kind == "project":
                if target != project[1]:
                    raise NotFound("project", target)
                target = project_id
            elif kind == "scope":
                kind = "team"
            elif kind == "response":
                kind = "message"
            elif kind == "notification":
                if not target.startswith("communication-") or not target.removeprefix("communication-").isdecimal():
                    raise InvalidToolArgument("target_handle", "Use a current ACS communication notification_handle.")
                cursor.execute("SELECT r.delivery_message_id FROM communication_notices n "
                    "LEFT JOIN communication_notice_routes r USING(tenant_id,project_id,message_id,recipient) "
                    "WHERE n.tenant_id=%s AND n.project_id=%s AND n.sequence=%s AND n.recipient=%s",
                    (self.context.tenant_id, project_id, int(target.removeprefix("communication-")), address))
                row = cursor.fetchone()
                if row is None:
                    raise NotFound("notification", target)
                if row[0] is None:
                    return "observed", {"project_id": project_id, "items": [], "next_cursor": None}, []
                kind, target = "message", row[0]
            elif kind not in {"route", "message"}:
                raise InvalidToolArgument("target_handle", "Select a Project, Route, Scope, message or communication notification handle.")
        cursor.execute("SELECT e.event_id,e.command_id,e.to_state,e.initiated_by,e.resulting_revision,e.target_kind,e.target_id,e.created_at "
            "FROM domain_events e WHERE e.tenant_id=%s AND e.event_id>%s "
            "AND (%s::text IS NULL OR (e.target_kind=%s AND e.target_id=%s)) "
            "AND (%s::text[]='{}' OR e.to_state=ANY(%s)) AND ("
            "(e.target_kind='message' AND (EXISTS(SELECT 1 FROM communication_messages c "
            "JOIN delivery_messages m USING(tenant_id,message_id) WHERE c.tenant_id=e.tenant_id AND c.project_id=%s "
            "AND m.command_id=e.command_id AND (c.sender=%s OR c.recipient=%s)) OR EXISTS("
            "SELECT 1 FROM communication_notice_routes r JOIN delivery_messages m ON m.tenant_id=r.tenant_id "
            "AND m.message_id=r.delivery_message_id WHERE r.tenant_id=e.tenant_id AND r.project_id=%s "
            "AND r.recipient=%s AND m.command_id=e.command_id))) "
            "OR (e.target_kind='project' AND e.target_id=%s) "
            "OR (e.target_kind='route' AND EXISTS(SELECT 1 FROM collaboration_routes r WHERE r.tenant_id=e.tenant_id "
            "AND r.project_id=%s AND r.route_id=e.target_id AND (%s::text[] IS NULL OR r.scope_id=ANY(%s)))) "
            "OR (e.target_kind='team' AND EXISTS(SELECT 1 FROM collaboration_commands c WHERE c.tenant_id=e.tenant_id "
            "AND c.project_id=%s AND c.command_id=e.command_id) AND (%s::text[] IS NULL OR e.target_id=ANY(%s)))) "
            "ORDER BY e.event_id LIMIT %s", (self.context.tenant_id, after, kind, kind, target,
                args.get("event_kinds", []), args.get("event_kinds", []), project_id, address, address,
                project_id, address, project_id, project_id, scopes, scopes, project_id, scopes, scopes, limit+1))
        rows = [{"event_id": row[0], "command_id": row[1], "kind": row[2], "actor": row[3],
                 "revision": row[4], "target_kind": row[5], "target_id": row[6],
                 "observed_at": row[7].isoformat(), "evidence_class": "authority_observation"}
                for row in cursor.fetchall()]
        return "observed", {"project_id": project_id, "items": rows[:limit],
                            "next_cursor": str(rows[limit-1]["event_id"]) if len(rows) > limit else None}, []

    def _read_resource(self, authority, cursor, project, command, args, credential):
        project_id = args["project_id"]
        kind = args["handle"].split(":", 1)[0]
        identifier = parse_handle(args["handle"], kind, project_id)
        if args.get("view", "summary") not in {"summary", "detail", "content"} or args.get("include"):
            raise InvalidToolArgument("view", "Use summary, detail or content for current Project, Route and source records.")
        if kind in {"message", "response", "notification"}:
            if args.get("at_revision") is not None:
                raise InvalidToolArgument("at_revision", "Message records use stable handles. Use read_message for communication content.")
            bound, message_project, message_command = self._authorize(authority, cursor, project_id, "read_message", args)
            state, data, follow = self._read_message(bound, cursor, message_project, message_command, args, credential)
            return state, dict(data, handle=args["handle"]), follow
        if kind == "project":
            if identifier != project[1]:
                raise NotFound("project", identifier)
            data = {"root_id": project[1], "revision": project[2], "scope_handle": handle("scope", project_id, project[0])}
        elif kind == "route":
            cursor.execute("SELECT revision,state,scope_id,definition FROM collaboration_routes "
                           "WHERE tenant_id=%s AND project_id=%s AND route_id=%s",
                           (self.context.tenant_id, project_id, identifier))
            row = cursor.fetchone()
            if row is None:
                raise NotFound("route", identifier)
            data = {"revision": row[0], "state": row[1], "scope_handle": handle("scope", project_id, row[2]), "definition": row[3]}
        elif kind == "artifact":
            data = self._source_artifact(authority, cursor, command, project_id, identifier, args)
        else:
            raise InvalidToolArgument("handle", "Use a current Project, Route, source Artifact or communication handle. Business task records are outside ACS.")
        if args.get("at_revision") is not None and args["at_revision"] != data["revision"]:
            raise RevisionConflict(identifier, args["at_revision"], data["revision"])
        result = dict(data, project_id=project_id, handle=args["handle"])
        maximum = args.get("max_inline_bytes", 16384)
        if type(maximum) is not int or not 1 <= maximum <= 65536:
            raise InvalidToolArgument("max_inline_bytes", "Choose an inline byte limit from 1 to 65536.")
        if kind == "artifact" and result.get("content_state") == "inline" and len(canonical(result).encode()) > maximum:
            result.pop("content", None)
            result.pop("content_base64", None)
            result["content_state"] = "verified_reference"
        if len(canonical(result).encode()) > maximum:
            raise InvalidToolArgument("max_inline_bytes", "The resource exceeds this bound; request a smaller view or a larger allowed byte limit.")
        return "observed", result, []

    def _source_artifact(self, authority, cursor, command, project_id, identifier, args):
        if len(identifier) < 66 or identifier[-65] != ".":
            raise InvalidToolArgument("handle", "Use an Artifact handle returned by the source reader.")
        scope_id, sha256 = identifier[:-65], identifier[-64:]
        authority._authorize(command, cursor, "artifact.read", scope_id)
        cursor.execute("SELECT f.value->'artifact_ref' FROM collaboration_source_snapshots p "
            "JOIN collaboration_sources s USING(tenant_id,project_id,source_id) "
            "CROSS JOIN LATERAL jsonb_array_elements(p.snapshot_json->'files') f "
            "WHERE p.tenant_id=%s AND p.project_id=%s AND p.snapshot_json->>'scope_id'=%s "
            "AND f.value->'artifact_ref'->>'sha256'=%s UNION ALL "
            "SELECT p.snapshot_json->'manifest_ref' FROM collaboration_source_snapshots p "
            "WHERE p.tenant_id=%s AND p.project_id=%s AND p.snapshot_json->>'scope_id'=%s "
            "AND p.snapshot_json->'manifest_ref'->>'sha256'=%s",
            (self.context.tenant_id, project_id, scope_id, sha256, self.context.tenant_id, project_id, scope_id, sha256))
        references = {canonical(row[0]): row[0] for row in cursor.fetchall()}
        store = self.sources.store if self.sources is not None else self.artifacts
        if not references and store is not None:
            cursor.execute("SELECT 1 FROM communication_archives a JOIN delivery_messages m USING(tenant_id,message_id) "
                "JOIN delivery_receipts r USING(tenant_id,message_id) WHERE a.tenant_id=%s AND a.project_id=%s "
                "AND a.source_hash=m.canonical_hash AND m.packet_json->>'target_scope_id'=%s "
                "AND r.layer='response_received' AND r.evidence_json->>'response_digest'=%s "
                "AND r.evidence_json->>'response_artifact_ref'=%s LIMIT 1",
                (self.context.tenant_id, project_id, scope_id, sha256, "artifact:"+sha256))
            if cursor.fetchone():
                provider = store.for_scope(scope_id) if hasattr(store, "for_scope") else store
                try:
                    reference = provider.reference_for_digest(sha256, kind="readback", media_type="application/json")
                except ArtifactError as error:
                    raise SourceError("historical Artifact reference is unavailable") from error
                references[canonical(reference.model_dump(mode="json"))] = reference.model_dump(mode="json")
        if len(references) != 1 or store is None:
            raise NotFound("artifact", identifier)
        reference = ArtifactRef.model_validate(next(iter(references.values())), strict=True)
        if reference.scope_id != scope_id or reference.sha256 != sha256:
            raise SourceError("Artifact handle differs from stored identity")
        reference, payload = read_artifact_reference(store, reference, args.get("max_inline_bytes", 16384), authority, command)
        data = {"revision": 1, "artifact_ref": reference.model_dump(mode="json"), "content_state": "verified_reference"}
        if args.get("content_mode", "reference") not in {"inline", "reference"}:
            raise InvalidToolArgument("content_mode", "Choose inline or reference.")
        if args.get("content_mode", "reference") == "inline" and payload is not None:
            if reference.media_type.startswith("text/") or reference.media_type == "application/json":
                try:
                    data["content"] = payload.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise SourceError("text Artifact is not UTF-8") from error
            else:
                data["content_base64"] = base64.b64encode(payload).decode("ascii")
            data["content_state"] = "inline"
        return data
