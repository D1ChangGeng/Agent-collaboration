"""Work intent, handoff and independent Review adapters for the shared Domain."""
from __future__ import annotations

import base64
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from runtime.artifacts import ArtifactError
from runtime.delivery_models import DeliveryPacket
from runtime.errors import AcceptanceGuardFailed, AuthorizationDenied, NotFound, RevisionConflict
from runtime.models import (
    ArtifactRef,
    AuthenticatedContext,
    EvidenceRecord,
    TransitionRequest,
    WorkItemState,
)
from runtime.project_common import canonical, digest, handle, parse_handle
from runtime.project_source import read_artifact_reference
from runtime.source import SourceError


class EvidenceDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    evidence_handle: str
    disposition: Literal["out_of_scope", "superseded", "resolved"]
    reason: str = Field(min_length=1, max_length=2048)
    replacement_handles: list[str] = Field(default_factory=list, max_length=32)


class WorkActions:
    def _candidate_inventory(self, cursor, work_id, candidate, baseline):
        cursor.execute("SELECT evidence_id,source_class,evidence_state,test_exit_code,artifact_sha256,"
                       "observer_ref,producer_ref,bundle_ref,summary FROM evidence WHERE tenant_id=%s "
                       "AND work_item_id=%s AND candidate_ref=%s AND baseline_ref=%s ORDER BY evidence_id FOR UPDATE",
                       (self.context.tenant_id, work_id, candidate, baseline))
        return [dict(zip(("evidence_id", "source_class", "evidence_state", "test_exit_code", "artifact_sha256",
                          "observer_ref", "producer_ref", "bundle_ref", "summary"), row, strict=True))
                for row in cursor.fetchall()]

    @staticmethod
    def _page_result(project_id, rows, args, identity):
        limit = args.get("limit", 50)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid page size")
        rows = sorted(rows, key=lambda row: row[identity])
        rows = [row for row in rows if not args.get("cursor") or row[identity] > args["cursor"]]
        return "observed", {"project_id": project_id, "items": rows[:limit],
                            "next_cursor": rows[limit-1][identity] if len(rows)>limit else None}, []

    def _list_evidence(self, _authority, cursor, _project, _command, args, _credential):
        work_id, _ = self._project_work(cursor, args["project_id"], args["target_handle"])
        cursor.execute("SELECT e.evidence_id,e.source_class,e.evidence_state,e.candidate_ref,"
                       "e.baseline_ref,e.bundle_ref,b.bundle_json FROM evidence e "
                       "LEFT JOIN evidence_bundles b ON b.tenant_id=e.tenant_id "
                       "AND b.evidence_id=e.evidence_id WHERE e.tenant_id=%s "
                       "AND e.work_item_id=%s ORDER BY e.evidence_id",
                       (self.context.tenant_id, work_id))
        rows = []
        for row in cursor.fetchall():
            if ((args.get("evidence_classes") and row[1] not in args["evidence_classes"])
                    or (args.get("kinds") and ("bundle" if row[5] else "summary") not in args["kinds"])):
                continue
            references = [] if row[6] is None else [
                *row[6].get("artifact_refs", []), *row[6].get("readback_refs", []),
            ]
            rows.append({"evidence_handle": handle("evidence", args["project_id"], row[0]),
                "evidence_class": row[1], "state": row[2], "candidate_ref": row[3],
                "source_baseline": row[4],
                "bundle_handle": handle("bundle", args["project_id"], row[5]) if row[5] else None,
                "artifact_handles": sorted({handle("artifact", args["project_id"],
                    reference["scope_id"] + "." + reference["sha256"])
                    for reference in references})})
        return self._page_result(args["project_id"], rows, args, "evidence_handle")

    def _list_reviews(self, authority, cursor, project, _command, args, _credential):
        scopes = self._visible_scopes(authority, cursor, project)
        work_id = None
        if args.get("target_handle"):
            work_id, _ = self._project_work(cursor, args["project_id"], args["target_handle"])
        cursor.execute("SELECT request_id,work_item_id,revision,state,candidate_ref,reviewer_ref,definition "
                       "FROM collaboration_review_requests r WHERE tenant_id=%s AND project_id=%s "
                       "AND (%s::text IS NULL OR work_item_id=%s) "
                       "AND (%s::text[] IS NULL OR EXISTS (SELECT 1 FROM work_items w WHERE w.tenant_id=r.tenant_id "
                       "AND w.work_item_id=r.work_item_id AND w.scope_id=ANY(%s)))",
                       (self.context.tenant_id, args["project_id"], work_id, work_id, scopes, scopes))
        rows = [{"review_handle": handle("review", args["project_id"], row[0]),
                 "work_handle": handle("work", args["project_id"], row[1]), "revision": row[2],
                 "state": row[3], "candidate_ref": row[4], "reviewer_ref": row[5],
                 "review_type": row[6]["review_type"]} for row in cursor.fetchall()
                if (not args.get("states") or row[3] in args["states"])
                and (not args.get("review_types") or row[6]["review_type"] in args["review_types"])]
        return self._page_result(args["project_id"], rows, args, "review_handle")

    def _list_activity(self, authority, cursor, project, _command, args, _credential):
        scopes = self._visible_scopes(authority, cursor, project)
        target = None
        if args.get("target_handle"):
            kind = args["target_handle"].split(":", 1)[0]
            target = parse_handle(args["target_handle"], kind, args["project_id"])
        after = int(args.get("cursor") or args.get("after_revision", 0))
        limit = args.get("limit", 50)
        if type(limit) is not int or not 1 <= limit <= 100 or after < 0:
            raise ValueError("invalid activity page")
        cursor.execute("SELECT event_id,command_id,to_state,initiated_by,resulting_revision,target_kind,"
                       "COALESCE(target_id,work_item_id),created_at FROM domain_events e "
                       "WHERE e.tenant_id=%s AND e.event_id>%s AND ("
                       "(e.target_kind='project' AND e.target_id=%s) OR EXISTS (SELECT 1 FROM collaboration_commands c "
                       "WHERE c.tenant_id=e.tenant_id AND c.project_id=%s AND c.command_id=e.command_id) "
                       "OR EXISTS (SELECT 1 FROM collaboration_work_links l "
                       "WHERE l.tenant_id=e.tenant_id AND l.project_id=%s AND l.work_item_id="
                       "COALESCE(e.related_work_item_id,e.work_item_id,CASE WHEN e.target_kind='work_item' THEN e.target_id END))) "
                       "AND (%s::text IS NULL OR COALESCE(target_id,work_item_id)=%s) "
                       "AND (%s::jsonb='[]'::jsonb OR to_state IN (SELECT jsonb_array_elements_text(%s::jsonb))) "
                       "AND (%s::text[] IS NULL OR EXISTS (SELECT 1 FROM work_items w WHERE w.tenant_id=e.tenant_id "
                       "AND w.work_item_id=COALESCE(e.related_work_item_id,e.work_item_id,"
                       "CASE WHEN e.target_kind='work_item' THEN e.target_id END) AND w.scope_id=ANY(%s)) "
                       "OR EXISTS (SELECT 1 FROM collaboration_routes r WHERE r.tenant_id=e.tenant_id AND r.project_id=%s "
                       "AND e.target_kind='route' AND r.route_id=e.target_id AND r.scope_id=ANY(%s))) "
                       "ORDER BY event_id LIMIT %s", (self.context.tenant_id, after, args["project_id"],
                       args["project_id"], args["project_id"], target, target, canonical(args.get("event_kinds", [])),
                       canonical(args.get("event_kinds", [])), scopes, scopes, args["project_id"], scopes, limit+1))
        rows = [{"event_id": row[0], "command_id": row[1], "kind": row[2], "actor": row[3],
                 "revision": row[4], "target_kind": row[5], "target_id": row[6],
                 "observed_at": row[7].isoformat(), "evidence_class": "authority_observation"}
                for row in cursor.fetchall()]
        return "observed", {"project_id": args["project_id"], "items": rows[:limit],
                            "next_cursor": str(rows[limit-1]["event_id"]) if len(rows)>limit else None}, []

    def _read_resource(self, authority, cursor, project, command, args, credential):
        project_id = args["project_id"]
        kind = args["handle"].split(":", 1)[0]
        identifier = parse_handle(args["handle"], kind, project_id)
        view = args.get("view", "summary")
        if view not in {"summary", "detail", "content", "history", "evidence"}:
            raise ValueError("invalid resource view")
        if args.get("include"):
            raise ValueError("this resource view has no additional include fields")
        if kind == "project":
            if identifier != project[1]:
                raise NotFound("project", identifier)
            data = {"root_id": project[1], "revision": project[2], "scope_handle": handle("scope", project_id, project[0])}
        elif kind == "work":
            _, work = self._project_work(cursor, project_id, args["handle"])
            data = {"revision": work[1], "state": work[2], "execution_status": work[3],
                    "source_baseline": work[4], "agent_slot_id": work[5]}
            cursor.execute("SELECT handoff_id,state FROM collaboration_handoffs WHERE tenant_id=%s "
                           "AND project_id=%s AND work_item_id=%s "
                           "ORDER BY assigned_work_revision DESC LIMIT 1",
                           (self.context.tenant_id, project_id, identifier))
            latest_handoff = cursor.fetchone()
            data["handoff_handle"] = (handle("handoff", project_id, latest_handoff[0])
                                      if latest_handoff else None)
            data["acknowledgement"] = latest_handoff[1] if latest_handoff else "not_required"
            if view in {"detail", "content"}:
                data["definition"] = work[6]
            elif view == "history":
                cursor.execute("SELECT revision,definition,source_baseline,agent_slot_id,reason "
                               "FROM work_item_revisions WHERE tenant_id=%s "
                               "AND work_item_id=%s ORDER BY revision", (self.context.tenant_id, identifier))
                data["history"] = [{"revision": row[0], "definition": row[1], "source_baseline": row[2],
                                    "agent_slot_id": row[3], "reason": row[4]} for row in cursor.fetchall()]
            elif view == "evidence":
                return self._list_evidence(authority, cursor, project, command,
                    {"project_id": project_id, "target_handle": args["handle"], "limit": args.get("limit", 50)}, credential)
        elif kind == "handoff":
            cursor.execute("SELECT work_item_id,assigned_work_revision,revision,from_agent_slot,"
                           "to_agent_slot,to_principal_ref,initiated_by,source_state,source_digest,"
                           "context_handles,evidence_handles,unresolved_items,message_id,state,"
                           "decision_reason,decided_by,decided_grant_ref,decided_at,created_at "
                           "FROM collaboration_handoffs WHERE tenant_id=%s AND project_id=%s "
                           "AND handoff_id=%s", (self.context.tenant_id, project_id, identifier))
            row = cursor.fetchone()
            if row is None:
                raise NotFound("handoff", identifier)
            if command.principal_ref not in {row[5], row[6]}:
                raise AuthorizationDenied(command.principal_ref, command.grant_ref)
            data = {"work_handle": handle("work", project_id, row[0]),
                "assigned_work_revision": row[1], "revision": row[2],
                "from_agent_slot": row[3], "to_agent_slot": row[4],
                "source_digest": row[8], "state": row[13],
                "message_handle": handle("message", project_id, row[12]) if row[12] else None,
                "decision_reason": row[14], "decided_by": row[15],
                "decided_grant_ref": row[16],
                "decided_at": row[17].isoformat() if row[17] else None,
                "created_at": row[18].isoformat()}
            if view in {"detail", "content"}:
                data.update(source_state=row[7], context_handles=row[9],
                            evidence_handles=row[10], unresolved_items=row[11])
        elif kind == "route":
            cursor.execute("SELECT revision,state,scope_id,definition FROM collaboration_routes "
                           "WHERE tenant_id=%s AND project_id=%s AND route_id=%s",
                           (self.context.tenant_id, project_id, identifier))
            row = cursor.fetchone()
            if row is None:
                raise NotFound(kind, identifier)
            data = {"revision": row[0], "state": row[1], "scope_handle": handle("scope", project_id, row[2]),
                    "definition": row[3]}
        elif kind == "review":
            cursor.execute("SELECT revision,state,candidate_ref,source_baseline,reviewer_ref,definition,"
                           "evidence_refs,submission FROM collaboration_review_requests "
                           "WHERE tenant_id=%s AND project_id=%s AND request_id=%s",
                           (self.context.tenant_id, project_id, identifier))
            row = cursor.fetchone()
            if row is None:
                raise NotFound(kind, identifier)
            data = {"revision": row[0], "state": row[1], "candidate_ref": row[2], "source_baseline": row[3],
                    "reviewer_ref": row[4], "definition": row[5], "evidence_handles": [
                        handle("evidence", project_id, item) for item in row[6]], "submission": row[7]}
        elif kind == "evidence":
            record, bundle = self._evidence(cursor, project_id, args["handle"])
            data = {"revision": 1, "record": record, "bundle": bundle if view in {"detail", "evidence"} else None}
        elif kind == "accepted":
            try:
                work_id, revision_text = identifier.rsplit(".", 1)
                revision = int(revision_text)
            except (ValueError, TypeError):
                raise ValueError("AcceptedState handle is invalid") from None
            cursor.execute("SELECT to_jsonb(a) FROM accepted_state_revisions a "
                           "JOIN collaboration_work_links l USING(tenant_id,work_item_id) "
                           "WHERE a.tenant_id=%s AND l.project_id=%s AND a.work_item_id=%s "
                           "AND a.revision=%s", (self.context.tenant_id, project_id,
                           work_id, revision))
            row = cursor.fetchone()
            if row is None:
                raise NotFound("accepted_state", identifier)
            data = {"revision": revision, "accepted_state": row[0],
                    "work_handle": handle("work", project_id, work_id)}
        elif kind == "artifact":
            if len(identifier) < 66 or identifier[-65] != ".":
                raise ValueError("Artifact handle is invalid")
            scope_id, sha256 = identifier[:-65], identifier[-64:]
            authority._authorize(command, cursor, "artifact.read", scope_id)
            references = []
            cursor.execute("SELECT f.value->'artifact_ref' FROM collaboration_source_snapshots p "
                           "JOIN collaboration_sources s USING(tenant_id,project_id,source_id) "
                           "CROSS JOIN LATERAL jsonb_array_elements(p.snapshot_json->'files') f "
                           "WHERE p.tenant_id=%s AND p.project_id=%s "
                           "AND p.snapshot_json->>'scope_id'=%s "
                           "AND f.value->'artifact_ref'->>'sha256'=%s",
                           (self.context.tenant_id, project_id, scope_id, sha256))
            references.extend(row[0] for row in cursor.fetchall())
            cursor.execute("SELECT p.snapshot_json->'manifest_ref' FROM collaboration_source_snapshots p "
                           "WHERE p.tenant_id=%s AND p.project_id=%s "
                           "AND p.snapshot_json->>'scope_id'=%s "
                           "AND p.snapshot_json->'manifest_ref'->>'sha256'=%s",
                           (self.context.tenant_id, project_id, scope_id, sha256))
            references.extend(row[0] for row in cursor.fetchall())
            cursor.execute("SELECT r.value FROM evidence_bundles b "
                           "JOIN collaboration_work_links l USING(tenant_id,work_item_id) "
                           "CROSS JOIN LATERAL jsonb_array_elements("
                           "COALESCE(b.bundle_json->'artifact_refs','[]'::jsonb) || "
                           "COALESCE(b.bundle_json->'readback_refs','[]'::jsonb)) r "
                           "WHERE b.tenant_id=%s AND l.project_id=%s "
                           "AND r.value->>'scope_id'=%s AND r.value->>'sha256'=%s",
                           (self.context.tenant_id, project_id, scope_id, sha256))
            references.extend(row[0] for row in cursor.fetchall())
            unique = {canonical(reference): reference for reference in references}
            store = self.sources.store if self.sources is not None else self.artifacts
            if not unique:
                cursor.execute("SELECT 1 FROM delivery_receipts r JOIN delivery_messages m "
                               "USING(tenant_id,message_id) JOIN collaboration_work_links l "
                               "ON l.tenant_id=m.tenant_id "
                               "AND l.work_item_id=m.packet_json->>'work_item_id' "
                               "WHERE r.tenant_id=%s AND l.project_id=%s "
                               "AND m.packet_json->>'target_scope_id'=%s "
                               "AND r.layer='response_received' "
                               "AND r.evidence_json->>'response_digest'=%s",
                               (self.context.tenant_id, project_id, scope_id, sha256))
                if cursor.fetchone() and store is not None:
                    provider = store.for_scope(scope_id) if hasattr(store, "for_scope") else store
                    try:
                        reference = provider.reference_for_digest(
                            sha256, kind="readback", media_type="application/json",
                        )
                    except ArtifactError as error:
                        raise SourceError("Artifact reference is unavailable") from error
                    unique[canonical(reference.model_dump(mode="json"))] = reference.model_dump(mode="json")
            if len(unique) != 1 or store is None:
                raise NotFound("artifact", identifier)
            reference = ArtifactRef.model_validate(next(iter(unique.values())), strict=True)
            if reference.scope_id != scope_id or reference.sha256 != sha256:
                raise SourceError("Artifact handle differs from stored identity")
            reference, payload = read_artifact_reference(store, reference,
                args.get("max_inline_bytes", 16384), authority, command)
            data = {"revision": 1, "artifact_ref": reference.model_dump(mode="json"),
                    "content_state": "verified_reference"}
            if args.get("content_mode", "reference") not in {"inline", "reference"}:
                raise ValueError("invalid Artifact content mode")
            if args.get("content_mode", "reference") == "inline" and payload is not None:
                if reference.media_type.startswith("text/") or reference.media_type == "application/json":
                    try:
                        data["content"] = payload.decode("utf-8")
                    except UnicodeDecodeError as error:
                        raise SourceError("text Artifact is not UTF-8") from error
                else:
                    data["content_base64"] = base64.b64encode(payload).decode("ascii")
                if len(canonical(data).encode()) <= args.get("max_inline_bytes", 16384):
                    data["content_state"] = "inline"
                else:
                    data.pop("content", None)
                    data.pop("content_base64", None)
        else:
            raise ValueError("unsupported resource kind")
        if args.get("at_revision") is not None and args["at_revision"] != data["revision"]:
            raise RevisionConflict(identifier, args["at_revision"], data["revision"])
        maximum = args.get("max_inline_bytes", 16384)
        if type(maximum) is not int or not 1 <= maximum <= 65536:
            raise ValueError("resource output bound is invalid")
        result = dict(data, project_id=project_id, handle=args["handle"])
        if (kind == "artifact" and result.get("content_state") == "inline"
                and len(canonical(result).encode()) > maximum):
            result.pop("content", None)
            result.pop("content_base64", None)
            result["content_state"] = "verified_reference"
        if len(canonical(result).encode()) > maximum:
            raise ValueError("resource exceeds requested inline bound")
        return "observed", result, []

    def _project_work(self, cursor, project_id, work_handle):
        work_id = parse_handle(work_handle, "work", project_id)
        cursor.execute("SELECT w.scope_id,w.revision,w.state,w.execution_status,w.source_baseline,"
                       "w.agent_slot_id,l.definition FROM collaboration_work_links l JOIN work_items w "
                       "USING(tenant_id,work_item_id) WHERE l.tenant_id=%s AND l.project_id=%s "
                       "AND l.work_item_id=%s FOR UPDATE OF w,l",
                       (self.context.tenant_id, project_id, work_id))
        row = cursor.fetchone()
        if row is None:
            raise NotFound("work_item", work_id)
        return work_id, row

    @staticmethod
    def _require_quiescent(cursor, tenant, work_id, work):
        if work[2] != "candidate" or work[3] in {"running", "failed", "cancelled"}:
            raise AcceptanceGuardFailed("work intent cannot change while running or sealed for acceptance")
        cursor.execute("SELECT 1 FROM collaboration_handoffs WHERE tenant_id=%s AND work_item_id=%s "
                       "AND state='pending' LIMIT 1", (tenant, work_id))
        if cursor.fetchone():
            raise AcceptanceGuardFailed("work has a pending handoff acknowledgement")
        cursor.execute("SELECT 1 FROM delivery_messages WHERE tenant_id=%s "
                       "AND packet_json->>'work_item_id'=%s "
                       "AND state IN ('queued','delivering','retry_wait','uncertain') "
                       "AND NOT EXISTS (SELECT 1 FROM collaboration_handoffs h "
                       "WHERE h.tenant_id=delivery_messages.tenant_id "
                       "AND h.message_id=delivery_messages.message_id "
                       "AND h.state IN ('accepted','rejected','withdrawn','cancelled')) LIMIT 1",
                       (tenant, work_id))
        if cursor.fetchone():
            raise AcceptanceGuardFailed("work has unresolved delivery")
        cursor.execute("SELECT 1 FROM attempts a WHERE a.tenant_id=%s AND a.work_item_id=%s "
                       "AND a.status='running' AND NOT EXISTS ("
                       "SELECT 1 FROM execution_receipts r WHERE r.tenant_id=a.tenant_id "
                       "AND r.work_item_id=a.work_item_id AND r.attempt_id=a.attempt_id "
                       "AND r.source_class='directly_verified' AND r.finished_at IS NOT NULL "
                       "AND r.receipt_json->>'status'='succeeded') LIMIT 1", (tenant, work_id))
        if cursor.fetchone():
            raise AcceptanceGuardFailed("work has a running Attempt without a verified completion")
        cursor.execute("SELECT 1 FROM leases l JOIN attempts a ON a.attempt_id=l.owner_attempt_id "
                       "AND a.tenant_id=l.tenant_id WHERE a.tenant_id=%s AND a.work_item_id=%s "
                       "AND l.status='granted' AND l.expires_at>clock_timestamp() LIMIT 1", (tenant, work_id))
        if cursor.fetchone():
            raise AcceptanceGuardFailed("work has an active protected resource owner")
        cursor.execute("SELECT 1 FROM effects WHERE tenant_id=%s AND work_item_id=%s "
                       "AND status IN ('prepared','uncertain') LIMIT 1", (tenant, work_id))
        if cursor.fetchone():
            raise AcceptanceGuardFailed("work has an unresolved protected effect")

    @staticmethod
    def _require_confirmed_handoff(cursor, tenant, work_id):
        cursor.execute("SELECT state FROM collaboration_handoffs WHERE tenant_id=%s "
                       "AND work_item_id=%s ORDER BY assigned_work_revision DESC LIMIT 1",
                       (tenant, work_id))
        latest = cursor.fetchone()
        if latest and latest[0] in {"pending", "rejected", "withdrawn"}:
            raise AcceptanceGuardFailed("handoff acknowledgement is required")

    def _save_work_revision(self, cursor, command, args, work_id, work):
        cursor.execute("INSERT INTO work_item_revisions VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                       (self.context.tenant_id, work_id, work[1], canonical(work[6]),
                        work[4], work[5], command.command_id, args.get("reason", "handoff")))

    def _revise_work(self, authority, cursor, _project, command, args, _credential):
        work_id, work = self._project_work(cursor, args["project_id"], args["work_handle"])
        authority._authorize(command, cursor, "work.manage", work[0])
        if work[1] != args["expected_revision"]:
            raise RevisionConflict(work_id, args["expected_revision"], work[1])
        self._require_quiescent(cursor, self.context.tenant_id, work_id, work)
        changes = args["changes"]
        allowed = {"goal", "constraints", "source_baseline", "required_evidence", "budget"}
        if not changes or set(changes) - allowed:
            raise ValueError("invalid work intent changes")
        for key, value in changes.items():
            expected = dict if key == "budget" else list if key in {"constraints", "required_evidence"} else str
            if type(value) is not expected or (expected is str and not value):
                raise ValueError("work intent change type differs")
            if expected is list and (len(value) > 32 or any(not isinstance(item, str) for item in value)):
                raise ValueError("work intent list is invalid")
        definition = dict(work[6], **changes)
        self._save_work_revision(cursor, command, args, work_id, work)
        cursor.execute("UPDATE work_items SET source_baseline=%s,revision=revision+1,updated_at=clock_timestamp() "
                       "WHERE tenant_id=%s AND work_item_id=%s", (definition["source_baseline"], self.context.tenant_id, work_id))
        cursor.execute("UPDATE collaboration_work_links SET definition=%s WHERE tenant_id=%s "
                       "AND project_id=%s AND work_item_id=%s", (canonical(definition), self.context.tenant_id,
                       args["project_id"], work_id))
        result = self._management_record(authority, cursor, command, args, target_kind="work_item",
            target_id=work_id, state="work.revised", revision=work[1]+1)
        return "revised", {"project_id": args["project_id"], "work_handle": args["work_handle"],
                           "revision": work[1]+1, "operation_id": result.operation_id}, []

    def _cancel_work(self, authority, cursor, _project, command, args, _credential):
        """End the durable objective without pretending to stop a native process."""
        work_id, work = self._project_work(cursor, args["project_id"], args["work_handle"])
        authority._authorize(command, cursor, "work.manage", work[0])
        if work[1] != args["expected_revision"]:
            raise RevisionConflict(work_id, args["expected_revision"], work[1])
        if work[2] != "candidate" or work[3] == "cancelled":
            raise AcceptanceGuardFailed("sealed or already cancelled Work cannot be cancelled")
        reason = args["reason"]
        if not isinstance(reason, str) or not 1 <= len(reason) <= 2048:
            raise ValueError("cancellation reason is outside bounds")
        cursor.execute("SELECT attempt_id,status,runtime_id,enrollment_node_id,enrollment_revision "
                       "FROM attempts WHERE tenant_id=%s AND work_item_id=%s ORDER BY attempt_id FOR UPDATE",
                       (self.context.tenant_id, work_id))
        attempts = [{"attempt_handle": handle("attempt", args["project_id"], row[0]),
            "revision": 1 if row[1] == "running" else max(row[4] or 1, 2),
            "state": row[1], "runtime_id": row[2], "node_id": row[3],
            "control_required": row[1] == "running"} for row in cursor.fetchall()]
        cursor.execute("SELECT effect_id,status,readback_ref FROM effects WHERE tenant_id=%s "
                       "AND work_item_id=%s AND status IN ('prepared','uncertain') ORDER BY effect_id",
                       (self.context.tenant_id, work_id))
        unresolved_effects = [{"effect_handle": handle("effect", args["project_id"], row[0]),
            "state": row[1], "readback_ref": row[2]} for row in cursor.fetchall()]
        self._save_work_revision(cursor, command, args, work_id, work)
        cursor.execute("UPDATE collaboration_handoffs SET state='cancelled',revision=revision+1 "
                       "WHERE tenant_id=%s AND work_item_id=%s AND state='pending'",
                       (self.context.tenant_id, work_id))
        definition = dict(work[6], cancellation={"reason": reason,
            "requested_by": command.principal_ref, "command_id": command.command_id})
        cursor.execute("UPDATE work_items SET execution_status='cancelled',revision=revision+1,"
                       "updated_at=clock_timestamp() WHERE tenant_id=%s AND work_item_id=%s",
                       (self.context.tenant_id, work_id))
        cursor.execute("UPDATE collaboration_work_links SET definition=%s WHERE tenant_id=%s "
                       "AND project_id=%s AND work_item_id=%s", (canonical(definition),
                       self.context.tenant_id, args["project_id"], work_id))
        result = self._management_record(authority, cursor, command, args,
            target_kind="work_item", target_id=work_id, state="work.cancelled",
            revision=work[1] + 1)
        follow = [{"rel": "stop_running_attempt", "tool": "stop_attempt", "arguments": {
            "client_request_id": args["client_request_id"] + ":stop:" +
                parse_handle(item["attempt_handle"], "attempt", args["project_id"]),
            "project_id": args["project_id"], "attempt_handle": item["attempt_handle"],
            "expected_revision": item["revision"], "reason": reason,
            "deadline": args["deadline"],
        }} for item in attempts if item["control_required"]]
        return "cancelled", {"project_id": args["project_id"],
            "work_handle": args["work_handle"], "revision": work[1] + 1,
            "work_state": work[2], "execution_status": "cancelled",
            "operation_id": result.operation_id, "accepted_state_changed": False,
            "attempts": attempts, "unresolved_effects": unresolved_effects}, follow

    def _handoff_work(self, authority, cursor, project, command, args, _credential):
        if self.profile != "root_manager":
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        work_id, work = self._project_work(cursor, args["project_id"], args["work_handle"])
        authority._authorize(command, cursor, "work.manage", work[0])
        if work[1] != args["expected_revision"]:
            raise RevisionConflict(work_id, args["expected_revision"], work[1])
        self._require_quiescent(cursor, self.context.tenant_id, work_id, work)
        cursor.execute("SELECT state,previous_execution_status,assigned_work_revision "
                       "FROM collaboration_handoffs WHERE tenant_id=%s AND work_item_id=%s "
                       "ORDER BY assigned_work_revision DESC LIMIT 1",
                       (self.context.tenant_id, work_id))
        prior_handoff = cursor.fetchone()
        previous_status = (prior_handoff[1] if prior_handoff and prior_handoff[0] in {"rejected", "withdrawn"}
                           and work[3] == "blocked" else work[3])
        if args["from_agent_slot"] != work[5]:
            raise ValueError("handoff origin differs from current owner")
        if args["to_agent_slot"] == work[5]:
            raise ValueError("handoff target is already the current owner")
        cursor.execute("SELECT m.principal_ref,m.grant_ref,m.profile FROM collaboration_team_members m "
                       "JOIN agent_slots s ON s.agent_slot_id=m.agent_slot_id AND s.tenant_id=m.tenant_id "
                       "WHERE m.tenant_id=%s AND m.project_id=%s AND m.scope_id=%s AND m.agent_slot_id=%s "
                       "AND m.status='active' AND s.status='active'", (self.context.tenant_id,
                       args["project_id"], work[0], args["to_agent_slot"]))
        target = cursor.fetchone()
        if target is None:
            raise NotFound("collaborator", args["to_agent_slot"])
        target_command = command.model_copy(update={
            "principal_ref": target[0], "grant_ref": target[1]})
        authority._authorize_delegation(cursor, target_command, "profile." + target[2])
        if args["require_ack"]:
            cursor.execute("SELECT 1 FROM grants WHERE grant_ref=%s AND scope_id=%s",
                           (target[1], work[0]))
            if cursor.fetchone() is None:
                raise AuthorizationDenied(target[0], target[1])
            for permission in ("handoff.ack", "resources.read", "messages.read", "message.read"):
                authority._authorize_delegation(cursor, target_command, permission)
        source = args["source_state"]
        required = {"branch", "commit", "tree", "working_tree", "push", "receiver_sync"}
        if not required <= set(source) or source["commit"] != work[4]:
            raise ValueError("handoff requires exact source and explicit sync observations")
        if any(not isinstance(source[key], str) or not source[key] for key in required):
            raise ValueError("invalid handoff source observation")
        for value in args["context_handles"]:
            kind = value.split(":", 1)[0]
            if kind not in {"project", "route", "work"}:
                raise ValueError("handoff context kind is not supported")
            identifier = parse_handle(value, kind, args["project_id"])
            if kind == "project":
                if identifier != project[1]:
                    raise NotFound("project", identifier)
            elif kind == "route":
                cursor.execute("SELECT 1 FROM collaboration_routes WHERE tenant_id=%s "
                               "AND project_id=%s AND route_id=%s AND scope_id=%s AND state='active'",
                               (self.context.tenant_id, args["project_id"], identifier, work[0]))
                if cursor.fetchone() is None:
                    raise NotFound("route", identifier)
            else:
                cursor.execute("SELECT 1 FROM collaboration_work_links l JOIN work_items w "
                               "USING(tenant_id,work_item_id) WHERE l.tenant_id=%s "
                               "AND l.project_id=%s AND l.work_item_id=%s AND w.scope_id=%s",
                               (self.context.tenant_id, args["project_id"], identifier, work[0]))
                if cursor.fetchone() is None:
                    raise NotFound("work_item", identifier)
        for value in args["evidence_handles"]:
            self._evidence(cursor, args["project_id"], value, work_id)
        message_id = None
        handoff_id = "handoff-" + uuid.uuid4().hex
        endpoint = None
        if args["require_ack"]:
            cursor.execute("SELECT session_ref FROM collaboration_notification_sessions "
                           "WHERE tenant_id=%s AND project_id=%s AND owner_ref=%s AND state='active' "
                           "AND expires_at>clock_timestamp()",
                           (self.context.tenant_id, args["project_id"], target[0]))
            if cursor.fetchone() is None:
                raise AcceptanceGuardFailed("receiving collaborator has no current Session")
            cursor.execute("SELECT endpoint_id,revision FROM delivery_endpoints WHERE tenant_id=%s "
                           "AND scope_id=%s AND agent_slot_id=%s AND status='active' "
                           "AND expires_at>clock_timestamp() ORDER BY endpoint_id FOR UPDATE",
                           (self.context.tenant_id, work[0], args["to_agent_slot"]))
            endpoints = cursor.fetchall()
            if len(endpoints) != 1:
                raise AcceptanceGuardFailed("receiving collaborator needs one current Endpoint")
            endpoint = endpoints[0]
            authority._authorize(command, cursor, "message.send", work[0])
            message_id = "handoff-message-" + uuid.uuid4().hex
        self._save_work_revision(cursor, command, args, work_id, work)
        handoff_definition = {key: args[key] for key in (
            "from_agent_slot", "to_agent_slot", "source_state", "context_handles", "evidence_handles",
            "unresolved_items", "require_ack")}
        handoff_definition["handoff_handle"] = handle("handoff", args["project_id"], handoff_id)
        definition = dict(work[6], handoff=handoff_definition)
        cursor.execute("UPDATE work_items SET agent_slot_id=%s,revision=revision+1,execution_status=%s,"
                       "updated_at=clock_timestamp() "
                       "WHERE tenant_id=%s AND work_item_id=%s",
                       (args["to_agent_slot"], "blocked" if args["require_ack"] else previous_status,
                        self.context.tenant_id, work_id))
        cursor.execute("UPDATE collaboration_work_links SET definition=%s WHERE tenant_id=%s "
                       "AND project_id=%s AND work_item_id=%s",
                       (canonical(definition), self.context.tenant_id, args["project_id"], work_id))
        message_result = None
        source_digest = digest(source)
        cursor.execute("INSERT INTO collaboration_handoffs(tenant_id,project_id,handoff_id,work_item_id,"
                           "assigned_work_revision,from_agent_slot,to_agent_slot,to_principal_ref,to_grant_ref,"
                           "initiated_by,source_state,source_digest,context_handles,evidence_handles,"
                           "unresolved_items,message_id,previous_execution_status,state) "
                           "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                           (self.context.tenant_id, args["project_id"], handoff_id, work_id,
                            work[1]+1, work[5], args["to_agent_slot"], target[0], target[1],
                            command.principal_ref, canonical(source), source_digest,
                            canonical(args["context_handles"]), canonical(args["evidence_handles"]),
                            canonical(args["unresolved_items"]), message_id, previous_status,
                            "pending" if args["require_ack"] else "not_required"))
        if message_id and endpoint:
            message_command = command.model_copy(update={
                "command_id": command.command_id + ":handoff-message",
                "idempotency_key": command.idempotency_key + ":handoff-message",
                "command_type": "message.send", "target_kind": "message", "target_id": message_id,
                "expected_revision": work[1]+1,
            })
            packet = DeliveryPacket(
                work_item_id=work_id, target_scope_id=work[0],
                target_agent_slot_id=args["to_agent_slot"], accepted_revision=0,
                goal="Review and acknowledge the assigned WorkItem",
                accepted_state_summary="Read the current accepted revision from ACS",
                request=canonical({"handoff_handle": handle("handoff", args["project_id"], handoff_id),
                    "work_handle": args["work_handle"], "work_revision": work[1]+1,
                    "source_digest": source_digest}),
                source_baseline=work[4], context_digests=(source_digest,),
                expected_response="Use acknowledge_handoff with the exact revision and source digest",
                activation="message_only", delivery_policy="queue_until_idle",
                deadline=command.deadline,
            )
            message_result = authority.send_message(message_command, packet,
                endpoint_id=endpoint[0], binding_revision=endpoint[1])
        result = self._management_record(authority, cursor, command, args, target_kind="work_item",
            target_id=work_id, state="work.handed_off", revision=work[1]+1)
        data = {"project_id": args["project_id"], "work_handle": args["work_handle"],
            "revision": work[1]+1, "operation_id": result.operation_id, "source_state": source,
            "assigned_to": args["to_agent_slot"], "acknowledgement": "pending" if args["require_ack"] else "not_required",
            "source_observation_class": "sender_reported"}
        follow_ups = []
        data.update(handoff_handle=handle("handoff", args["project_id"], handoff_id),
                    handoff_revision=1, source_digest=source_digest)
        follow_ups.append({"rel": "read_acknowledgement", "tool": "read_resource",
            "arguments": {"project_id": args["project_id"], "handle": data["handoff_handle"],
                          "view": "detail"}})
        if message_id and message_result:
            data.update(
                message_handle=handle("message", args["project_id"], message_id),
                message_operation_id=message_result.operation_id)
            follow_ups.append({"rel": "read_delivery", "tool": "read_message",
                "arguments": {"project_id": args["project_id"], "handle": data["message_handle"],
                              "consume": False}})
        return "pending" if args["require_ack"] else "handed_off", data, follow_ups

    def _acknowledge_handoff(self, authority, cursor, project, command, args, _credential):
        handoff_id = parse_handle(args["handoff_handle"], "handoff", args["project_id"])
        # Match Root cancellation's lock order: Work first, then handoff.
        cursor.execute("SELECT work_item_id FROM collaboration_handoffs WHERE tenant_id=%s "
                       "AND project_id=%s AND handoff_id=%s",
                       (self.context.tenant_id, args["project_id"], handoff_id))
        identity = cursor.fetchone()
        if identity is None:
            raise NotFound("handoff", handoff_id)
        work_handle = handle("work", args["project_id"], identity[0])
        work_id, work = self._project_work(cursor, args["project_id"], work_handle)
        cursor.execute("SELECT work_item_id,assigned_work_revision,revision,to_agent_slot,"
                       "to_principal_ref,to_grant_ref,source_digest,previous_execution_status,state,message_id "
                       "FROM collaboration_handoffs WHERE tenant_id=%s AND project_id=%s AND handoff_id=%s "
                       "FOR UPDATE", (self.context.tenant_id, args["project_id"], handoff_id))
        handoff = cursor.fetchone()
        if handoff is None or handoff[0] != work_id:
            raise NotFound("handoff", handoff_id)
        if handoff[4] != command.principal_ref or project[5] != handoff[3]:
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        cursor.execute("SELECT 1 FROM collaboration_team_members m JOIN agent_slots s "
                       "ON s.tenant_id=m.tenant_id AND s.agent_slot_id=m.agent_slot_id "
                       "WHERE m.tenant_id=%s AND m.project_id=%s AND m.agent_slot_id=%s "
                       "AND m.principal_ref=%s AND m.grant_ref=%s AND m.status='active' "
                       "AND s.status='active' FOR UPDATE OF m,s",
                       (self.context.tenant_id, args["project_id"], handoff[3],
                        command.principal_ref, authority.context.grant_ref))
        if cursor.fetchone() is None:
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        cursor.execute("SELECT 1 FROM collaboration_notification_sessions WHERE tenant_id=%s "
                       "AND project_id=%s AND owner_ref=%s AND state='active' "
                       "AND expires_at>clock_timestamp()",
                       (self.context.tenant_id, args["project_id"], command.principal_ref))
        if cursor.fetchone() is None:
            raise AcceptanceGuardFailed("receiving collaborator has no current Session")
        if handoff[2] != args["expected_handoff_revision"]:
            raise RevisionConflict(handoff_id, args["expected_handoff_revision"], handoff[2])
        if handoff[8] != "pending":
            raise AcceptanceGuardFailed("handoff is no longer pending")
        cursor.execute("SELECT 1 FROM delivery_receipts WHERE tenant_id=%s AND message_id=%s "
                       "AND layer='target_inbox_committed'",
                       (self.context.tenant_id, handoff[9]))
        if cursor.fetchone() is None:
            raise AcceptanceGuardFailed("handoff Message has not reached the receiving Inbox")
        if handoff[6] != args["source_digest"]:
            raise AcceptanceGuardFailed("handoff Source state differs")
        if work[1] != args["expected_work_revision"] or work[1] != handoff[1]:
            raise RevisionConflict(work_id, args["expected_work_revision"], work[1])
        if work[5] != handoff[3] or work[3] != "blocked":
            raise AcceptanceGuardFailed("handoff assignment changed")
        decision = args["decision"]
        if decision not in {"accepted", "rejected"}:
            raise ValueError("handoff decision is invalid")
        if not 1 <= len(args["reason"]) <= 2048:
            raise ValueError("handoff reason is outside bounds")
        self._save_work_revision(cursor, command, args, work_id, work)
        acknowledgement = {"decision": decision, "reason": args["reason"],
                           "by": command.principal_ref, "grant_ref": authority.context.grant_ref}
        definition = dict(work[6], handoff=dict(work[6]["handoff"], acknowledgement=acknowledgement))
        cursor.execute("UPDATE work_items SET execution_status=%s,revision=revision+1,"
                       "updated_at=clock_timestamp() WHERE tenant_id=%s AND work_item_id=%s",
                       (handoff[7] if decision == "accepted" else "blocked", self.context.tenant_id, work_id))
        cursor.execute("UPDATE collaboration_work_links SET definition=%s WHERE tenant_id=%s "
                       "AND project_id=%s AND work_item_id=%s",
                       (canonical(definition), self.context.tenant_id, args["project_id"], work_id))
        cursor.execute("UPDATE collaboration_handoffs SET state=%s,revision=revision+1,"
                       "decision_reason=%s,decided_by=%s,decided_grant_ref=%s,decided_at=clock_timestamp() "
                       "WHERE tenant_id=%s AND project_id=%s AND handoff_id=%s",
                       (decision, args["reason"], command.principal_ref, authority.context.grant_ref,
                        self.context.tenant_id, args["project_id"], handoff_id))
        result = self._management_record(authority, cursor, command, args, target_kind="work_item",
            target_id=work_id, state="handoff." + decision, revision=work[1]+1)
        return decision, {"project_id": args["project_id"], "handoff_handle": args["handoff_handle"],
            "handoff_revision": handoff[2]+1, "work_handle": work_handle,
            "work_revision": work[1]+1, "assigned_to": handoff[3],
            "acknowledgement": decision, "operation_id": result.operation_id}, []

    def _withdraw_handoff(self, authority, cursor, _project, command, args, _credential):
        if self.profile != "root_manager":
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        handoff_id = parse_handle(args["handoff_handle"], "handoff", args["project_id"])
        cursor.execute("SELECT work_item_id FROM collaboration_handoffs WHERE tenant_id=%s "
                       "AND project_id=%s AND handoff_id=%s",
                       (self.context.tenant_id, args["project_id"], handoff_id))
        identity = cursor.fetchone()
        if identity is None:
            raise NotFound("handoff", handoff_id)
        work_handle = handle("work", args["project_id"], identity[0])
        work_id, work = self._project_work(cursor, args["project_id"], work_handle)
        authority._authorize(command, cursor, "work.manage", work[0])
        cursor.execute("SELECT revision,assigned_work_revision,to_agent_slot,state "
                       "FROM collaboration_handoffs WHERE tenant_id=%s AND project_id=%s "
                       "AND handoff_id=%s FOR UPDATE",
                       (self.context.tenant_id, args["project_id"], handoff_id))
        handoff = cursor.fetchone()
        if handoff is None:
            raise NotFound("handoff", handoff_id)
        if handoff[0] != args["expected_handoff_revision"]:
            raise RevisionConflict(handoff_id, args["expected_handoff_revision"], handoff[0])
        if work[1] != args["expected_work_revision"] or work[1] != handoff[1]:
            raise RevisionConflict(work_id, args["expected_work_revision"], work[1])
        if handoff[3] != "pending" or work[5] != handoff[2] or work[3] != "blocked":
            raise AcceptanceGuardFailed("handoff is no longer pending on this WorkItem")
        if not 1 <= len(args["reason"]) <= 2048:
            raise ValueError("withdrawal reason is outside bounds")
        self._save_work_revision(cursor, command, args, work_id, work)
        definition = dict(work[6], handoff=dict(work[6]["handoff"],
            withdrawal={"reason": args["reason"], "by": command.principal_ref}))
        cursor.execute("UPDATE work_items SET revision=revision+1,updated_at=clock_timestamp() "
                       "WHERE tenant_id=%s AND work_item_id=%s",
                       (self.context.tenant_id, work_id))
        cursor.execute("UPDATE collaboration_work_links SET definition=%s WHERE tenant_id=%s "
                       "AND project_id=%s AND work_item_id=%s",
                       (canonical(definition), self.context.tenant_id, args["project_id"], work_id))
        cursor.execute("UPDATE collaboration_handoffs SET state='withdrawn',revision=revision+1,"
                       "decision_reason=%s,decided_by=%s,decided_grant_ref=%s,decided_at=clock_timestamp() "
                       "WHERE tenant_id=%s AND project_id=%s AND handoff_id=%s",
                       (args["reason"], command.principal_ref, authority.context.grant_ref,
                        self.context.tenant_id, args["project_id"], handoff_id))
        result = self._management_record(authority, cursor, command, args, target_kind="work_item",
            target_id=work_id, state="handoff.withdrawn", revision=work[1]+1)
        return "withdrawn", {"project_id": args["project_id"],
            "handoff_handle": args["handoff_handle"], "handoff_revision": handoff[0]+1,
            "work_handle": work_handle, "work_revision": work[1]+1,
            "assigned_to": handoff[2], "acknowledgement": "withdrawn",
            "operation_id": result.operation_id}, []

    def _evidence(self, cursor, project_id, evidence_handle, work_id=None):
        evidence_id = parse_handle(evidence_handle, "evidence", project_id)
        cursor.execute("SELECT to_jsonb(e),b.bundle_json FROM evidence e JOIN collaboration_work_links l "
                       "USING(tenant_id,work_item_id) LEFT JOIN evidence_bundles b "
                       "ON b.tenant_id=e.tenant_id AND b.evidence_id=e.evidence_id "
                       "WHERE l.tenant_id=%s AND l.project_id=%s AND e.evidence_id=%s "
                       "AND (%s::text IS NULL OR e.work_item_id=%s) FOR UPDATE OF e",
                       (self.context.tenant_id, project_id, evidence_id, work_id, work_id))
        row = cursor.fetchone()
        if row is None:
            raise NotFound("evidence", evidence_id)
        return row

    def _request_review(self, authority, cursor, _project, command, args, _credential):
        work_id, work = self._project_work(cursor, args["project_id"], args["work_handle"])
        self._require_confirmed_handoff(cursor, self.context.tenant_id, work_id)
        if work[1] != args["expected_work_revision"]:
            raise RevisionConflict(work_id, args["expected_work_revision"], work[1])
        if args["source_baseline"] != work[4]:
            raise ValueError("review baseline differs from WorkItem")
        # Reviewer selection is an external Agent decision. This field carries
        # its explicit collaborator handle; Core never chooses a reviewer.
        if len(args["reviewer_requirements"]) != 1:
            raise ValueError("select one explicit Reviewer collaborator per Review request")
        slot = parse_handle(args["reviewer_requirements"][0], "collaborator", args["project_id"])
        cursor.execute("SELECT principal_ref,grant_ref FROM collaboration_team_members WHERE tenant_id=%s "
                       "AND project_id=%s AND scope_id=%s AND agent_slot_id=%s AND role='reviewer' "
                       "AND status='active'", (self.context.tenant_id, args["project_id"], work[0], slot))
        reviewer = cursor.fetchone()
        if reviewer is None:
            raise NotFound("reviewer", slot)
        inventory = self._candidate_inventory(cursor, work_id, args["candidate_ref"], work[4])
        if len(inventory) > 256:
            raise ValueError("candidate evidence inventory exceeds the review bound")
        available = {row["evidence_id"] for row in inventory}
        evidence_refs = ([parse_handle(value, "evidence", args["project_id"]) for value in args["evidence_handles"]]
                         if "evidence_handles" in args else sorted(available))
        if len(set(evidence_refs)) != len(evidence_refs) or not set(evidence_refs) <= available:
            raise ValueError("selected evidence does not belong to this candidate")
        evidence_refs = sorted(evidence_refs)
        if not 1 <= len(evidence_refs) <= 32:
            raise AcceptanceGuardFailed("review requires a bounded recorded candidate evidence set")
        excluded = [row for row in inventory if row["evidence_id"] not in evidence_refs]
        definition = dict(args, evidence_inventory=inventory, evidence_inventory_digest=digest(inventory),
                          excluded_evidence=excluded)
        assigned = authority.assign_reviewer(command.model_copy(update={"command_type": "review.assign",
            "target_kind": "work_item", "target_id": work_id, "expected_revision": work[1]}),
            work_id, reviewer[0], reviewer[1])
        authority._authorize_delegation(cursor, command.model_copy(update={
            "principal_ref": reviewer[0], "grant_ref": reviewer[1]}), "review.record")
        cursor.execute("SELECT assignment_revision FROM reviewer_assignments WHERE tenant_id=%s "
                       "AND work_item_id=%s AND reviewer_ref=%s",
                       (self.context.tenant_id, work_id, reviewer[0]))
        assignment = cursor.fetchone()[0]
        request_id = "review-" + uuid.uuid4().hex
        cursor.execute("INSERT INTO collaboration_review_requests(tenant_id,project_id,request_id,work_item_id,"
                       "work_revision,revision,candidate_ref,source_baseline,reviewer_ref,reviewer_grant_ref,"
                       "assignment_revision,state,definition,evidence_refs) "
                       "VALUES (%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s,'pending',%s,%s)",
                       (self.context.tenant_id, args["project_id"], request_id, work_id, work[1], args["candidate_ref"],
                        work[4], reviewer[0], reviewer[1], assignment, canonical(definition), canonical(evidence_refs)))
        review_handle = handle("review", args["project_id"], request_id)
        return "requested", {"project_id": args["project_id"], "review_handle": review_handle,
            "revision": 1, "operation_id": assigned.operation_id, "reviewer_ref": reviewer[0],
            "excluded_evidence": [{"evidence_handle": handle("evidence", args["project_id"], row["evidence_id"]),
                "source_class": row["source_class"], "state": row["evidence_state"]} for row in excluded],
            "evidence_handles": [handle("evidence", args["project_id"], item) for item in evidence_refs]}, [
                {"rel": "read_review", "tool": "read_resource", "arguments": {
                    "project_id": args["project_id"], "handle": review_handle, "view": "detail"}}]

    def _submit_review(self, authority, cursor, _project, command, args, _credential):
        request_id = parse_handle(args["review_handle"], "review", args["project_id"])
        cursor.execute("SELECT work_item_id,work_revision,revision,candidate_ref,source_baseline,reviewer_ref,"
                       "reviewer_grant_ref,assignment_revision,state,evidence_refs,definition "
                       "FROM collaboration_review_requests WHERE tenant_id=%s AND project_id=%s AND request_id=%s FOR UPDATE",
                       (self.context.tenant_id, args["project_id"], request_id))
        review = cursor.fetchone()
        if review is None:
            raise NotFound("review", request_id)
        if review[2] != args["expected_revision"]:
            raise RevisionConflict(request_id, args["expected_revision"], review[2])
        if (review[5], review[6], review[8]) != (authority.context.principal_ref, authority.context.grant_ref, "pending"):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        if args["decision"] not in {"pass", "fail"}:
            raise ValueError("Review decision must be pass or fail")
        evidence_refs = [parse_handle(value, "evidence", args["project_id"]) for value in args["evidence_handles"]]
        if len(set(evidence_refs)) != len(evidence_refs) or set(evidence_refs) != set(review[9]):
            raise ValueError("Review evidence set differs from the sealed request")
        work_id, work = self._project_work(cursor, args["project_id"], handle("work", args["project_id"], review[0]))
        if work[1] != review[1] or work[4] != review[4]:
            raise RevisionConflict(work_id, review[1], work[1])
        inventory = self._candidate_inventory(cursor, work_id, review[3], work[4])
        if digest(inventory) != review[10]["evidence_inventory_digest"]:
            raise AcceptanceGuardFailed("candidate evidence inventory changed after Review was sealed")
        cursor.execute("SELECT assignment_revision FROM reviewer_assignments WHERE tenant_id=%s "
                       "AND work_item_id=%s AND reviewer_ref=%s AND status='active'",
                       (self.context.tenant_id, work_id, review[5]))
        if cursor.fetchone() != (review[7],):
            raise AcceptanceGuardFailed("Reviewer assignment changed since request")
        if args["decision"] == "pass":
            if args["unresolved_items"] or args["findings"]:
                raise AcceptanceGuardFailed("passing Review requires resolved findings")
            dispositions = [EvidenceDisposition.model_validate_json(canonical(item), strict=True)
                            for item in args.get("evidence_dispositions", [])]
            excluded = {row["evidence_id"]: row for row in review[10]["excluded_evidence"]}
            handled = set()
            for disposition in dispositions:
                evidence_id = parse_handle(disposition.evidence_handle, "evidence", args["project_id"])
                if evidence_id not in excluded or evidence_id in handled:
                    raise ValueError("evidence disposition must name one excluded record exactly once")
                handled.add(evidence_id)
                row = excluded[evidence_id]
                replacements = {parse_handle(value, "evidence", args["project_id"])
                                for value in disposition.replacement_handles}
                if disposition.disposition == "out_of_scope":
                    if (row["source_class"] == "directly_verified"
                            or row["evidence_state"] not in {"incomplete", "not_run"}
                            or row["test_exit_code"] not in (None, 0) or replacements):
                        raise AcceptanceGuardFailed("adverse or direct evidence requires a supported resolution")
                elif not replacements or not replacements <= set(evidence_refs):
                    raise AcceptanceGuardFailed("evidence resolution requires selected verified replacements")
            if handled != set(excluded):
                raise AcceptanceGuardFailed("Reviewer must explicitly disposition all excluded evidence")
            source = args["source_readback"]
            if not {"source_id", "commit", "tree"} <= set(source):
                raise ValueError("passing Review requires direct SourceBinding readback")
            _, source_snapshot = self._snapshot(cursor, {"project_id": args["project_id"],
                "source_id": source["source_id"], "revision": source["commit"]})
            self.sources.verify(source_snapshot, authority, command)
            current = self.sources.observe(source_snapshot, authority, command)
            if (current["commit"], current["tree"], current["working_tree"]) != (source["commit"], source["tree"], "clean"):
                raise AcceptanceGuardFailed("Review Source readback is stale")
            for value in args["evidence_handles"]:
                stored, bundle = self._evidence(cursor, args["project_id"], value, work_id)
                if bundle is None:
                    raise AcceptanceGuardFailed("passing Review requires complete evidence bundles")
                record = EvidenceRecord.model_validate({key: value for key, value in stored.items()
                                                        if key in EvidenceRecord.model_fields})
                _, receipt, _ = authority._validate_bundle(cursor, record, bundle, work_id, work[4], work[0])
                if (receipt.candidate_ref, receipt.source_commit, receipt.source_tree) != (review[3], source["commit"], source["tree"]):
                    raise AcceptanceGuardFailed("Review evidence Source differs from direct readback")
        ordered_refs = sorted(evidence_refs)
        recorded = authority.record_review(command.model_copy(update={"command_type": "review.record",
            "target_kind": "work_item", "target_id": work_id, "expected_revision": work[1]}),
            request_id, work_id, args["decision"], ordered_refs[0], work[4], tuple(ordered_refs[1:]))
        cursor.execute("UPDATE collaboration_review_requests SET revision=revision+1,state='submitted',"
                       "submission=%s,review_id=%s WHERE tenant_id=%s AND project_id=%s AND request_id=%s",
                       (canonical(args), request_id, self.context.tenant_id, args["project_id"], request_id))
        return "submitted", {"project_id": args["project_id"], "review_handle": args["review_handle"],
            "revision": review[2]+1, "decision": args["decision"], "operation_id": recorded.operation_id,
            "accepted_state_changed": False}, []

    def _accept_work(self, authority, cursor, _project, command, args, _credential):
        """Apply an explicitly authorized Finalizer decision through all Core guards."""
        work_id, work = self._project_work(cursor, args["project_id"], args["work_handle"])
        self._require_confirmed_handoff(cursor, self.context.tenant_id, work_id)
        if work[1] != args["expected_revision"]:
            raise RevisionConflict(work_id, args["expected_revision"], work[1])
        if args["decision"] not in {"acceptance_ready", "accepted"}:
            raise ValueError("invalid Finalizer decision")
        bundle_handles = args["evidence_bundle_handles"]
        review_handles = args["review_handles"]
        if (not 1 <= len(bundle_handles) <= 32 or len(set(bundle_handles)) != len(bundle_handles)
                or not 1 <= len(review_handles) <= 8 or len(set(review_handles)) != len(review_handles)):
            raise ValueError("acceptance requires bounded unique Evidence and Review sets")
        source = args["source_readback"]
        if not {"source_id", "commit", "tree"} <= set(source):
            raise ValueError("Finalizer requires explicit Source readback")
        _, snapshot = self._snapshot(cursor, {"project_id": args["project_id"],
            "source_id": source["source_id"], "revision": source["commit"]})
        self.sources.verify(snapshot, authority, command)
        current = self.sources.observe(snapshot, authority, command)
        if (current["commit"], current["tree"], current["working_tree"]) != (source["commit"], source["tree"], "clean"):
            raise AcceptanceGuardFailed("Finalizer Source readback is stale")
        evidence_refs = []
        for value in bundle_handles:
            bundle_id = parse_handle(value, "bundle", args["project_id"])
            cursor.execute("SELECT e.evidence_id,e.candidate_ref,b.bundle_json FROM evidence_bundles b "
                           "JOIN evidence e ON e.tenant_id=b.tenant_id AND e.evidence_id=b.evidence_id "
                           "WHERE b.tenant_id=%s AND b.work_item_id=%s AND b.bundle_id=%s FOR UPDATE OF e,b",
                           (self.context.tenant_id, work_id, bundle_id))
            row = cursor.fetchone()
            if (row is None or row[1] != args["candidate_ref"]
                    or row[2]["execution_receipt"]["source_commit"] != source["commit"]
                    or row[2]["execution_receipt"]["source_tree"] != source["tree"]):
                raise AcceptanceGuardFailed("Finalizer Evidence set differs from the candidate Source")
            evidence_refs.append(row[0])
        review_ids = []
        for value in review_handles:
            request_id = parse_handle(value, "review", args["project_id"])
            cursor.execute("SELECT q.review_id,q.evidence_refs,q.candidate_ref,r.verdict,r.reviewer_ref,"
                           "r.reviewer_grant_ref,r.assignment_revision,a.assignment_revision,q.definition "
                           "FROM collaboration_review_requests q JOIN reviews r ON r.review_id=q.review_id "
                           "AND r.tenant_id=q.tenant_id JOIN reviewer_assignments a ON a.tenant_id=r.tenant_id "
                           "AND a.work_item_id=r.work_item_id AND a.reviewer_ref=r.reviewer_ref "
                           "AND a.reviewer_grant_ref=r.reviewer_grant_ref AND a.status='active' "
                           "WHERE q.tenant_id=%s AND q.project_id=%s AND q.work_item_id=%s AND q.request_id=%s "
                           "AND q.state='submitted' FOR UPDATE OF q,r,a",
                           (self.context.tenant_id, args["project_id"], work_id, request_id))
            review = cursor.fetchone()
            if (review is None or set(review[1]) != set(evidence_refs) or review[2] != args["candidate_ref"]
                    or review[3] != "pass" or review[6] != review[7]):
                raise AcceptanceGuardFailed("Finalizer Review set is incomplete or stale")
            inventory = self._candidate_inventory(cursor, work_id, args["candidate_ref"], work[4])
            if digest(inventory) != review[8]["evidence_inventory_digest"]:
                raise AcceptanceGuardFailed("candidate evidence inventory changed after Review")
            authority._authorize_delegation(cursor, AuthenticatedContext(self.context.tenant_id,
                self.context.authority_id, self.context.authority_incarnation, review[4], review[5]), "review.record")
            review_ids.append(review[0])
        effects = args["effect_readback"]
        if set(effects) != {"effect_refs", "readback_refs"} or any(
                not isinstance(effects[key], list) or any(not isinstance(item, str) for item in effects[key])
                for key in effects):
            raise ValueError("Finalizer Effect readback requires explicit effect and readback references")
        result = authority.transition_work_item(command.model_copy(update={
            "command_type": "work_item.transition", "target_kind": "work_item", "target_id": work_id,
            "expected_revision": work[1]}), TransitionRequest(to_state=WorkItemState(args["decision"]),
            evidence_refs=tuple(sorted(evidence_refs)), review_ref=min(review_ids),
            effect_refs=tuple(effects["effect_refs"]), readback_refs=tuple(effects["readback_refs"])))
        return result.state, {"project_id": args["project_id"], "work_handle": args["work_handle"],
            "accepted_state_handle": handle("accepted", args["project_id"],
                                            work_id + "." + str(result.revision)),
            "revision": result.revision, "operation_id": result.operation_id,
            "accepted_by": authority.context.principal_ref if result.state == "accepted" else None}, []
