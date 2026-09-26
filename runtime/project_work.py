"""Work intent, handoff and independent Review adapters for the shared Domain."""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from runtime.errors import AcceptanceGuardFailed, AuthorizationDenied, NotFound, RevisionConflict
from runtime.models import AuthenticatedContext, EvidenceRecord, TransitionRequest, WorkItemState
from runtime.project_common import canonical, digest, handle, parse_handle


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
        cursor.execute("SELECT evidence_id,source_class,evidence_state,candidate_ref,baseline_ref,bundle_ref "
                       "FROM evidence WHERE tenant_id=%s AND work_item_id=%s ORDER BY evidence_id",
                       (self.context.tenant_id, work_id))
        rows = [{"evidence_handle": handle("evidence", args["project_id"], row[0]),
                 "evidence_class": row[1], "state": row[2], "candidate_ref": row[3],
                 "source_baseline": row[4], "bundle_handle": handle("bundle", args["project_id"], row[5]) if row[5] else None}
                for row in cursor.fetchall() if (not args.get("evidence_classes") or row[1] in args["evidence_classes"])
                and (not args.get("kinds") or ("bundle" if row[5] else "summary") in args["kinds"])]
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
        else:
            raise ValueError("unsupported resource kind")
        if args.get("at_revision") is not None and args["at_revision"] != data["revision"]:
            raise RevisionConflict(identifier, args["at_revision"], data["revision"])
        maximum = args.get("max_inline_bytes", 16384)
        if type(maximum) is not int or not 1 <= maximum <= 65536 or len(canonical(data).encode()) > maximum:
            raise ValueError("resource exceeds requested inline bound")
        return "observed", dict(data, project_id=project_id, handle=args["handle"]), []

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
        if work[2] != "candidate" or work[3] == "running":
            raise AcceptanceGuardFailed("work intent cannot change while running or sealed for acceptance")
        cursor.execute("SELECT 1 FROM delivery_messages WHERE tenant_id=%s "
                       "AND packet_json->>'work_item_id'=%s "
                       "AND state IN ('queued','delivering','retry_wait','uncertain') LIMIT 1",
                       (tenant, work_id))
        if cursor.fetchone():
            raise AcceptanceGuardFailed("work has unresolved delivery")
        cursor.execute("SELECT 1 FROM leases l JOIN attempts a ON a.attempt_id=l.owner_attempt_id "
                       "AND a.tenant_id=l.tenant_id WHERE a.tenant_id=%s AND a.work_item_id=%s "
                       "AND l.status='granted' AND l.expires_at>clock_timestamp() LIMIT 1", (tenant, work_id))
        if cursor.fetchone():
            raise AcceptanceGuardFailed("work has an active protected resource owner")
        cursor.execute("SELECT 1 FROM effects WHERE tenant_id=%s AND work_item_id=%s "
                       "AND status IN ('prepared','uncertain') LIMIT 1", (tenant, work_id))
        if cursor.fetchone():
            raise AcceptanceGuardFailed("work has an unresolved protected effect")

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

    def _handoff_work(self, authority, cursor, _project, command, args, _credential):
        work_id, work = self._project_work(cursor, args["project_id"], args["work_handle"])
        authority._authorize(command, cursor, "work.manage", work[0])
        if work[1] != args["expected_revision"]:
            raise RevisionConflict(work_id, args["expected_revision"], work[1])
        self._require_quiescent(cursor, self.context.tenant_id, work_id, work)
        if args["from_agent_slot"] != work[5]:
            raise ValueError("handoff origin differs from current owner")
        cursor.execute("SELECT m.principal_ref,m.grant_ref,m.profile FROM collaboration_team_members m "
                       "JOIN agent_slots s ON s.agent_slot_id=m.agent_slot_id AND s.tenant_id=m.tenant_id "
                       "WHERE m.tenant_id=%s AND m.project_id=%s AND m.scope_id=%s AND m.agent_slot_id=%s "
                       "AND m.status='active' AND s.status='active'", (self.context.tenant_id,
                       args["project_id"], work[0], args["to_agent_slot"]))
        target = cursor.fetchone()
        if target is None:
            raise NotFound("collaborator", args["to_agent_slot"])
        authority._authorize_delegation(cursor, command.model_copy(update={
            "principal_ref": target[0], "grant_ref": target[1]}), "profile." + target[2])
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
            parse_handle(value, kind, args["project_id"])
        for value in args["evidence_handles"]:
            self._evidence(cursor, args["project_id"], value, work_id)
        self._save_work_revision(cursor, command, args, work_id, work)
        definition = dict(work[6], handoff={key: args[key] for key in (
            "from_agent_slot", "to_agent_slot", "source_state", "context_handles", "evidence_handles",
            "unresolved_items", "require_ack")})
        cursor.execute("UPDATE work_items SET agent_slot_id=%s,revision=revision+1,updated_at=clock_timestamp() "
                       "WHERE tenant_id=%s AND work_item_id=%s",
                       (args["to_agent_slot"], self.context.tenant_id, work_id))
        cursor.execute("UPDATE collaboration_work_links SET definition=%s WHERE tenant_id=%s "
                       "AND project_id=%s AND work_item_id=%s",
                       (canonical(definition), self.context.tenant_id, args["project_id"], work_id))
        result = self._management_record(authority, cursor, command, args, target_kind="work_item",
            target_id=work_id, state="work.handed_off", revision=work[1]+1)
        return "handed_off", {"project_id": args["project_id"], "work_handle": args["work_handle"],
            "revision": work[1]+1, "operation_id": result.operation_id, "source_state": source,
            "assigned_to": args["to_agent_slot"], "acknowledgement": "pending" if args["require_ack"] else "not_required",
            "source_observation_class": "sender_reported"}, []

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
            "revision": result.revision, "operation_id": result.operation_id,
            "accepted_by": authority.context.principal_ref if result.state == "accepted" else None}, []
