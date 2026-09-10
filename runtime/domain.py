from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar

import psycopg

from runtime.errors import (
    AcceptanceGuardFailed,
    AuthorizationDenied,
    IdempotencyConflict,
    InvalidTransition,
    NotFound,
    RevisionConflict,
    SchemaAdoptionError,
)
from runtime.lease_authority import LeaseAuthority
from runtime.models import (
    AuthenticatedContext,
    CommandEnvelope,
    CommandResult,
    EvidenceRecord,
    TransitionRequest,
    WorkItemState,
)


class DomainAuthority:
    SCHEMA_NAME = "acs-p1-runtime"
    SCHEMA_VERSION = "1.3"
    _KNOWN_SCHEMA_MIGRATIONS: ClassVar[set[tuple[str, str]]] = {
        ("1.0", "415c76f2778e1b1b33aa2533f14140511cb7c00bd0ebbd47ff8fb3a007578a87"),
        ("1.1", "ea0097e39fb023c5130cb924d0faf34429f2f6968056b00a72042af1d78cdd92"),
        ("1.2", "95e952142fc3d55d4eda3211852dee823e48aad6d793890716dc2365d2cbdd84"),
        ("1.2", "312465f388be994fd1a2b308bd7f1c6e7c8354be5dfd54792fcb2be20ef13339"),
    }
    def __init__(self, dsn: str, context: AuthenticatedContext | None = None) -> None:
        self._dsn = dsn
        self.context = context or AuthenticatedContext("local-tenant", "acs-p1-authority", "local-1", "agent:engineer", "grant:p1")

    @property
    def leases(self) -> LeaseAuthority:
        return LeaseAuthority(self)

    @property
    def tenant_id(self) -> str:
        return self.context.tenant_id

    @property
    def authority_id(self) -> str:
        return self.context.authority_id

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._dsn)

    def initialize(self) -> None:
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        checksum = hashlib.sha256(schema.encode("utf-8")).hexdigest()
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(schema.encode("utf-8"))
            cursor.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s FOR UPDATE", (self.SCHEMA_NAME,))
            metadata = cursor.fetchone()
            if metadata is None:
                cursor.execute("INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) VALUES (%s,%s,%s)", (self.SCHEMA_NAME, self.SCHEMA_VERSION, checksum))
            elif metadata[0] == self.SCHEMA_VERSION and metadata[1] == checksum:
                pass
            elif (str(metadata[0]), str(metadata[1])) in self._KNOWN_SCHEMA_MIGRATIONS:
                cursor.execute("UPDATE runtime_schema_metadata SET schema_version=%s,schema_checksum=%s,adopted_at=now() WHERE schema_name=%s", (self.SCHEMA_VERSION, checksum, self.SCHEMA_NAME))
            else:
                mismatch = SchemaAdoptionError(self.SCHEMA_NAME, checksum, str(metadata[1]))
                connection.rollback()
                raise mismatch
            cursor.execute("INSERT INTO authority_instances(authority_id,authority_incarnation,status) VALUES (%s,%s,'active') ON CONFLICT DO NOTHING", (self.context.authority_id, self.context.authority_incarnation))
            cursor.execute("INSERT INTO scopes(scope_id,tenant_id,policy,status) VALUES ('local-scope',%s,'{}','active') ON CONFLICT DO NOTHING", (self.context.tenant_id,))
            cursor.execute("INSERT INTO agent_slots(agent_slot_id,tenant_id,scope_id,status) VALUES ('local-slot',%s,'local-scope','active') ON CONFLICT DO NOTHING", (self.context.tenant_id,))

    def bootstrap_local_grant(self, permissions: tuple[str, ...] = ("work_item.create", "work_item.transition", "evidence.record", "review.record", "lease.acquire", "work_item.read")) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,scope_id,permissions,expires_at,revoked_at) "
                "VALUES (%s,%s,%s,%s,%s,'local-scope',%s,now()+interval '365 days',NULL) "
                "ON CONFLICT (grant_ref) DO UPDATE SET tenant_id=EXCLUDED.tenant_id, "
                "principal_ref=EXCLUDED.principal_ref, authority_id=EXCLUDED.authority_id, "
                "authority_incarnation=EXCLUDED.authority_incarnation, scope_id=EXCLUDED.scope_id, "
                "permissions=EXCLUDED.permissions, expires_at=EXCLUDED.expires_at, revoked_at=NULL",
                (self.context.grant_ref, self.context.tenant_id, self.context.principal_ref,
                 self.context.authority_id, self.context.authority_incarnation, json.dumps(permissions)),
            )

    def _authorize(self, command: CommandEnvelope, cursor: psycopg.Cursor | None = None, permission: str = "work_item.read", scope_id: str | None = None) -> None:
        if cursor is None:
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        now = datetime.now(UTC)
        c = self.context
        if command.issued_at.tzinfo is None or command.deadline.tzinfo is None or command.deadline <= now or command.issued_at > now:
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        if (command.tenant_id, command.authority_id, command.authority_incarnation, command.principal_ref, command.grant_ref) != (c.tenant_id, c.authority_id, c.authority_incarnation, c.principal_ref, c.grant_ref):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        cursor.execute("SELECT g.scope_id,g.permissions FROM grants g JOIN authority_instances a ON a.authority_id=g.authority_id AND a.authority_incarnation=g.authority_incarnation JOIN scopes s ON s.scope_id=g.scope_id WHERE g.grant_ref=%s AND g.tenant_id=%s AND g.principal_ref=%s AND g.authority_id=%s AND g.authority_incarnation=%s AND a.status='active' AND s.tenant_id=%s AND s.status='active' AND g.revoked_at IS NULL AND g.expires_at>%s FOR UPDATE", (c.grant_ref, c.tenant_id, c.principal_ref, c.authority_id, c.authority_incarnation, c.tenant_id, now))
        row = cursor.fetchone()
        if row is None or permission not in tuple(row[1]) or (scope_id is not None and row[0] != scope_id):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)

    @staticmethod
    def _hash(command: CommandEnvelope, extra: dict[str, object]) -> str:
        value = {"command_id": command.command_id, "command_type": command.command_type, "idempotency_key": command.idempotency_key, "correlation_id": command.correlation_id, "tenant_id": command.tenant_id, "authority_id": command.authority_id, "authority_incarnation": command.authority_incarnation, "principal_ref": command.principal_ref, "grant_ref": command.grant_ref, "target_kind": command.target_kind, "target_id": command.target_id, "expected_revision": command.expected_revision, "issued_at": command.issued_at.isoformat(), "deadline": command.deadline.isoformat(), "payload": command.payload, "extra": extra}
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _dedup(self, cursor: psycopg.Cursor, command: CommandEnvelope, result: CommandResult, extra: dict[str, object]) -> CommandResult | None:
        digest = self._hash(command, extra)
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"acs-p1-command:{command.tenant_id}:{command.idempotency_key}",))
        cursor.execute("SELECT payload_hash,result_json FROM command_dedup WHERE tenant_id=%s AND idempotency_key=%s FOR UPDATE", (command.tenant_id, command.idempotency_key)); row = cursor.fetchone()
        if row is None:
            cursor.execute("SELECT payload_hash,result_json FROM command_dedup WHERE tenant_id=%s AND command_id=%s FOR UPDATE", (command.tenant_id, command.command_id)); row = cursor.fetchone()
        if row is not None:
            if row[0] != digest: raise IdempotencyConflict(command.idempotency_key)
            return CommandResult.model_validate(row[1]).model_copy(update={"duplicate": True})
        cursor.execute("INSERT INTO command_dedup(tenant_id,idempotency_key,command_id,payload_hash,result_json) VALUES (%s,%s,%s,%s,%s)", (command.tenant_id, command.idempotency_key, command.command_id, digest, result.model_dump_json()))
        return None

    def create_work_item(self, command: CommandEnvelope, scope_id: str, agent_slot_id: str, source_baseline: str) -> CommandResult:
        result = CommandResult(command_id=command.command_id, operation_id=f"op-{uuid.uuid4()}", target_id=command.target_id, revision=0, state=WorkItemState.CANDIDATE)
        with self._connect() as connection, connection.cursor() as cursor:
            self._authorize(command, cursor, "work_item.create", scope_id)
            duplicate = self._dedup(cursor, command, result, {"scope_id": scope_id, "agent_slot_id": agent_slot_id, "source_baseline": source_baseline})
            if duplicate is not None: return duplicate
            cursor.execute("SELECT 1 FROM scopes s JOIN agent_slots a ON a.scope_id=s.scope_id WHERE s.scope_id=%s AND a.agent_slot_id=%s AND s.tenant_id=%s AND a.tenant_id=%s AND s.status='active' AND a.status='active'", (scope_id, agent_slot_id, self.context.tenant_id, self.context.tenant_id))
            if cursor.fetchone() is None: raise AuthorizationDenied(command.principal_ref, command.grant_ref)
            cursor.execute("INSERT INTO work_items(work_item_id,tenant_id,scope_id,agent_slot_id,state,execution_status,source_baseline,created_by) VALUES (%s,%s,%s,%s,'candidate','ready',%s,%s)", (command.target_id, self.context.tenant_id, scope_id, agent_slot_id, source_baseline, self.context.principal_ref)); self._record(cursor, command, None, WorkItemState.CANDIDATE, 0, ()); self._operation(cursor, command, result.operation_id); self._outbox(cursor, command, result.operation_id, "work_item.created", {"state": "candidate"})
        return result

    def transition_work_item(self, command: CommandEnvelope, transition: TransitionRequest) -> CommandResult:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT scope_id FROM work_items WHERE tenant_id=%s AND work_item_id=%s", (command.tenant_id, command.target_id)); scope = cursor.fetchone()
            if scope is None: raise NotFound("work_item", command.target_id)
            self._authorize(command, cursor, "work_item.transition", str(scope[0]))
            result = CommandResult(command_id=command.command_id, operation_id=f"op-{uuid.uuid4()}", target_id=command.target_id, revision=command.expected_revision + 1, state=transition.to_state)
            duplicate = self._dedup(cursor, command, result, {"transition": transition.model_dump(mode="json")})
            if duplicate is not None: return duplicate
            cursor.execute("SELECT state,revision,source_baseline,scope_id FROM work_items WHERE tenant_id=%s AND work_item_id=%s FOR UPDATE", (self.context.tenant_id, command.target_id)); row = cursor.fetchone()
            if row is None: raise NotFound("work_item", command.target_id)
            current, revision = WorkItemState(row[0]), int(row[1])
            if revision != command.expected_revision: raise RevisionConflict(command.target_id, command.expected_revision, revision)
            self._guard(cursor, command, current, transition, str(row[2]), str(row[3])); next_revision = revision + 1
            cursor.execute("UPDATE work_items SET state=%s,revision=%s,updated_at=now() WHERE tenant_id=%s AND work_item_id=%s", (transition.to_state, next_revision, self.context.tenant_id, command.target_id)); self._record(cursor, command, current, transition.to_state, next_revision, transition.evidence_refs)
            if transition.to_state is WorkItemState.ACCEPTED:
                cursor.execute("INSERT INTO accepted_state_revisions(tenant_id,work_item_id,revision,baseline_ref,evidence_refs,review_ref,effect_refs,readback_refs,accepted_by,policy_version,parent_revision,scope_id,valid_from) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())", (self.context.tenant_id, command.target_id, next_revision, row[2], json.dumps(transition.evidence_refs), transition.review_ref, json.dumps(transition.effect_refs), json.dumps(transition.readback_refs), self.context.principal_ref, "1", revision, row[3]))
            elif transition.to_state is WorkItemState.ACCEPTANCE_READY:
                cursor.execute("INSERT INTO accepted_state_revisions(tenant_id,work_item_id,revision,baseline_ref,evidence_refs,review_ref,effect_refs,readback_refs,accepted_by,policy_version,parent_revision,scope_id,valid_from) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s,%s,%s,now())", (self.context.tenant_id, command.target_id, next_revision, row[2], json.dumps(transition.evidence_refs), transition.review_ref, json.dumps(()), json.dumps(()), "1", revision, row[3]))
            self._operation(cursor, command, result.operation_id); self._outbox(cursor, command, result.operation_id, f"work_item.{transition.to_state}", {"state": str(transition.to_state)}); return result.model_copy(update={"revision": next_revision})

    def _guard(self, cursor: psycopg.Cursor, command: CommandEnvelope, current: WorkItemState, transition: TransitionRequest, baseline: str, scope_id: str) -> None:
        if current is WorkItemState.CANDIDATE and transition.to_state is WorkItemState.ACCEPTANCE_READY:
            if not transition.evidence_refs or transition.review_ref is None: raise AcceptanceGuardFailed("evidence and review are required")
            if len(transition.evidence_refs) != 1: raise AcceptanceGuardFailed("current review API binds exactly one evidence reference")
            cursor.execute("SELECT source_class FROM evidence WHERE tenant_id=%s AND work_item_id=%s AND baseline_ref=%s AND evidence_id=ANY(%s)", (self.context.tenant_id, command.target_id, baseline, list(transition.evidence_refs))); evidence = cursor.fetchall()
            if len(evidence) != len(transition.evidence_refs) or any(r[0] in ("not_run", "mocked") for r in evidence): raise AcceptanceGuardFailed("admissible evidence is missing")
            cursor.execute("SELECT r.reviewer_ref,w.created_by,g.permissions FROM reviews r JOIN work_items w ON w.tenant_id=r.tenant_id AND w.work_item_id=r.work_item_id JOIN reviewer_assignments a ON a.tenant_id=r.tenant_id AND a.work_item_id=r.work_item_id AND a.reviewer_ref=r.reviewer_ref AND a.reviewer_grant_ref=r.reviewer_grant_ref AND a.status='active' JOIN grants g ON g.grant_ref=r.reviewer_grant_ref AND g.tenant_id=r.tenant_id AND g.principal_ref=r.reviewer_ref AND g.scope_id=a.scope_id WHERE r.tenant_id=%s AND r.work_item_id=%s AND r.review_id=%s AND r.verdict='pass' AND r.baseline_ref=%s AND r.evidence_ref=ANY(%s) AND g.revoked_at IS NULL AND g.expires_at>now()", (self.context.tenant_id, command.target_id, transition.review_ref, baseline, list(transition.evidence_refs))); review = cursor.fetchone()
            if review is None or review[0] == review[1] or "review.record" not in tuple(review[2]): raise AcceptanceGuardFailed("independent assigned authorized review is missing")
            return
        if current is WorkItemState.ACCEPTANCE_READY and transition.to_state is WorkItemState.ACCEPTED:
            self._authorize(command, cursor, "acceptance.finalize", scope_id)
            if not transition.review_ref or not transition.evidence_refs or not transition.effect_refs or not transition.readback_refs: raise AcceptanceGuardFailed("sealed readiness references are required")
            if len(transition.effect_refs) != len(transition.readback_refs): raise AcceptanceGuardFailed("effect and readback references must pair one-to-one")
            cursor.execute("SELECT baseline_ref,evidence_refs,review_ref,scope_id FROM accepted_state_revisions WHERE tenant_id=%s AND work_item_id=%s ORDER BY revision DESC LIMIT 1", (self.context.tenant_id, command.target_id)); snap = cursor.fetchone()
            if snap is None or snap[0] != baseline or snap[2] != transition.review_ref: raise AcceptanceGuardFailed("readiness snapshot mismatch")
            if str(snap[3]) != scope_id or tuple(snap[1] or ()) != tuple(transition.evidence_refs): raise AcceptanceGuardFailed("readiness evidence snapshot mismatch")
            cursor.execute("SELECT r.reviewer_ref,w.created_by,g.permissions FROM reviews r JOIN work_items w ON w.tenant_id=r.tenant_id AND w.work_item_id=r.work_item_id JOIN reviewer_assignments a ON a.tenant_id=r.tenant_id AND a.work_item_id=r.work_item_id AND a.reviewer_ref=r.reviewer_ref AND a.reviewer_grant_ref=r.reviewer_grant_ref AND a.status='active' JOIN grants g ON g.grant_ref=r.reviewer_grant_ref AND g.tenant_id=r.tenant_id AND g.principal_ref=r.reviewer_ref AND g.scope_id=a.scope_id WHERE r.tenant_id=%s AND r.work_item_id=%s AND r.review_id=%s AND r.verdict='pass' AND r.baseline_ref=%s AND r.evidence_ref=ANY(%s) AND g.revoked_at IS NULL AND g.expires_at>now()", (self.context.tenant_id, command.target_id, transition.review_ref, baseline, list(transition.evidence_refs))); review = cursor.fetchone()
            if review is None or review[0] == review[1] or "review.record" not in tuple(review[2]): raise AcceptanceGuardFailed("sealed independent assigned review is no longer valid")
            for effect_id, readback_ref in zip(transition.effect_refs, transition.readback_refs, strict=True):
                cursor.execute("SELECT e.effect_id,e.readback_ref,e.baseline_ref,e.grant_ref,e.generation,l.authority_incarnation,l.status,l.expires_at,g.revoked_at,g.expires_at,a.status FROM effects e JOIN leases l ON l.lease_id=e.lease_id AND l.tenant_id=e.tenant_id AND l.resource_id=e.resource_id AND l.fencing_token=e.fencing_token AND l.generation=e.generation AND l.grant_ref=e.grant_ref JOIN grants g ON g.grant_ref=e.grant_ref AND g.tenant_id=e.tenant_id AND g.authority_id=l.authority_id AND g.authority_incarnation=l.authority_incarnation JOIN authority_instances a ON a.authority_id=l.authority_id AND a.authority_incarnation=l.authority_incarnation WHERE e.tenant_id=%s AND e.work_item_id=%s AND e.effect_id=%s AND e.readback_ref=%s AND e.baseline_ref=%s AND e.status='verified' AND l.authority_id=%s", (self.context.tenant_id, command.target_id, effect_id, readback_ref, baseline, self.context.authority_id)); effect = cursor.fetchone()
                if effect is None or effect[1] != readback_ref or effect[2] != baseline or effect[3] != self.context.grant_ref or effect[5] != self.context.authority_incarnation or effect[6] != "granted" or effect[7] <= datetime.now(UTC) or effect[8] is not None or effect[9] <= datetime.now(UTC) or effect[10] != "active": raise AcceptanceGuardFailed("verified effect readback is missing or no longer authorized")
            return
        raise InvalidTransition(current, transition.to_state)

    def record_evidence(self, command: CommandEnvelope, evidence: EvidenceRecord) -> CommandResult:
        with self._connect() as connection, connection.cursor() as cursor:
            if command.target_id != evidence.work_item_id:
                raise AuthorizationDenied(command.principal_ref, command.grant_ref)
            if evidence.observer_ref != self.context.principal_ref:
                raise AuthorizationDenied(command.principal_ref, command.grant_ref)
            cursor.execute("SELECT scope_id,state FROM work_items WHERE tenant_id=%s AND work_item_id=%s FOR UPDATE", (self.context.tenant_id, evidence.work_item_id)); row = cursor.fetchone()
            if row is None: raise NotFound("work_item", evidence.work_item_id)
            self._authorize(command, cursor, "evidence.record", str(row[0])); result = CommandResult(command_id=command.command_id, operation_id=f"op-{uuid.uuid4()}", target_id=evidence.work_item_id, revision=0, state="evidence")
            duplicate = self._dedup(cursor, command, result, {"evidence": evidence.model_dump(mode="json")})
            if duplicate is not None: return duplicate
            cursor.execute("INSERT INTO evidence(evidence_id,tenant_id,work_item_id,observer_ref,source_class,baseline_ref,artifact_sha256,summary) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (evidence.evidence_id, self.context.tenant_id, evidence.work_item_id, evidence.observer_ref, evidence.source_class, evidence.baseline_ref, evidence.artifact_sha256, evidence.summary))
            self._record(cursor, command, WorkItemState(row[1]), WorkItemState(row[1]), 0, (evidence.evidence_id,))
            self._operation(cursor, command, result.operation_id)
            self._outbox(cursor, command, result.operation_id, "evidence.recorded", {"evidence_id": evidence.evidence_id})
            return result

    def record_review(self, command: CommandEnvelope, review_id: str, work_item_id: str, verdict: str, evidence_ref: str, baseline_ref: str) -> CommandResult:
        with self._connect() as connection, connection.cursor() as cursor:
            if command.target_id != work_item_id:
                raise AuthorizationDenied(command.principal_ref, command.grant_ref)
            cursor.execute("SELECT scope_id,state FROM work_items WHERE tenant_id=%s AND work_item_id=%s FOR UPDATE", (self.context.tenant_id, work_item_id)); row = cursor.fetchone()
            if row is None: raise NotFound("work_item", work_item_id)
            self._authorize(command, cursor, "review.record", str(row[0])); cursor.execute("SELECT baseline_ref FROM evidence WHERE tenant_id=%s AND work_item_id=%s AND evidence_id=%s", (self.context.tenant_id, work_item_id, evidence_ref)); evidence = cursor.fetchone()
            if evidence is None or evidence[0] != baseline_ref: raise AcceptanceGuardFailed("review evidence is not bound")
            cursor.execute("SELECT 1 FROM reviewer_assignments a JOIN grants g ON g.grant_ref=a.reviewer_grant_ref AND g.tenant_id=a.tenant_id AND g.principal_ref=a.reviewer_ref AND g.scope_id=a.scope_id AND g.authority_id=%s AND g.authority_incarnation=%s WHERE a.tenant_id=%s AND a.work_item_id=%s AND a.reviewer_ref=%s AND a.reviewer_grant_ref=%s AND a.status='active' AND g.revoked_at IS NULL AND g.expires_at>now()", (self.context.authority_id, self.context.authority_incarnation, self.context.tenant_id, work_item_id, self.context.principal_ref, self.context.grant_ref))
            if cursor.fetchone() is None: raise AuthorizationDenied(self.context.principal_ref, self.context.grant_ref)
            result = CommandResult(command_id=command.command_id, operation_id=f"op-{uuid.uuid4()}", target_id=work_item_id, revision=0, state="review")
            duplicate = self._dedup(cursor, command, result, {"review_id": review_id, "work_item_id": work_item_id, "verdict": verdict, "evidence_ref": evidence_ref, "baseline_ref": baseline_ref})
            if duplicate is not None: return duplicate
            cursor.execute("INSERT INTO reviews(review_id,tenant_id,work_item_id,reviewer_ref,reviewer_grant_ref,verdict,evidence_ref,baseline_ref) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (review_id, self.context.tenant_id, work_item_id, self.context.principal_ref, self.context.grant_ref, verdict, evidence_ref, baseline_ref))
            self._record(cursor, command, WorkItemState(row[1]), WorkItemState(row[1]), 0, (review_id, evidence_ref))
            self._operation(cursor, command, result.operation_id)
            self._outbox(cursor, command, result.operation_id, "review.recorded", {"review_id": review_id, "evidence_id": evidence_ref})
            return result

    def assign_reviewer(self, command: CommandEnvelope, work_item_id: str, reviewer_ref: str, reviewer_grant_ref: str) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT scope_id,created_by FROM work_items WHERE tenant_id=%s AND work_item_id=%s FOR UPDATE", (self.context.tenant_id, work_item_id))
            row = cursor.fetchone()
            if row is None:
                raise NotFound("work_item", work_item_id)
            if command.target_id != work_item_id or reviewer_ref == row[1]:
                raise AuthorizationDenied(command.principal_ref, command.grant_ref)
            self._authorize(command, cursor, "review.record", str(row[0]))
            cursor.execute("SELECT 1 FROM grants g JOIN authority_instances a ON a.authority_id=g.authority_id AND a.authority_incarnation=g.authority_incarnation WHERE g.grant_ref=%s AND g.tenant_id=%s AND g.principal_ref=%s AND g.scope_id=%s AND g.authority_id=%s AND g.authority_incarnation=%s AND a.status='active' AND g.revoked_at IS NULL AND g.expires_at>now()", (reviewer_grant_ref, self.context.tenant_id, reviewer_ref, row[0], self.context.authority_id, self.context.authority_incarnation))
            if cursor.fetchone() is None:
                raise AuthorizationDenied(reviewer_ref, reviewer_grant_ref)
            cursor.execute("INSERT INTO reviewer_assignments(tenant_id,work_item_id,reviewer_ref,reviewer_grant_ref,assigned_by,scope_id,status) VALUES (%s,%s,%s,%s,%s,%s,'active') ON CONFLICT (tenant_id,work_item_id,reviewer_ref) DO UPDATE SET reviewer_grant_ref=EXCLUDED.reviewer_grant_ref,assigned_by=EXCLUDED.assigned_by,scope_id=EXCLUDED.scope_id,status='active'", (self.context.tenant_id, work_item_id, reviewer_ref, reviewer_grant_ref, self.context.principal_ref, row[0]))

    def get_work_item(self, work_item_id: str) -> dict[str, str | int] | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT scope_id,work_item_id,state,execution_status,revision,source_baseline FROM work_items WHERE tenant_id=%s AND work_item_id=%s", (self.context.tenant_id, work_item_id)); row = cursor.fetchone()
            if row is None: return None
            now = datetime.now(UTC); read = CommandEnvelope(command_id=f"read-{uuid.uuid4()}", command_type="work_item.read", idempotency_key=f"read-{uuid.uuid4()}", correlation_id="read", tenant_id=self.context.tenant_id, authority_id=self.context.authority_id, authority_incarnation=self.context.authority_incarnation, principal_ref=self.context.principal_ref, grant_ref=self.context.grant_ref, target_kind="work_item", target_id=work_item_id, expected_revision=0, issued_at=now, deadline=now + timedelta(minutes=1)); self._authorize(read, cursor, "work_item.read", str(row[0])); return {"work_item_id": row[1], "state": row[2], "execution_status": row[3], "revision": row[4], "source_baseline": row[5]}

    @staticmethod
    def _record(cursor: psycopg.Cursor, command: CommandEnvelope, before: WorkItemState | None, after: WorkItemState, revision: int, refs: Iterable[str]) -> None:
        cursor.execute("INSERT INTO domain_events(tenant_id,work_item_id,from_state,to_state,initiated_by,lineage_mode,command_id,resulting_revision,evidence_refs) VALUES (%s,%s,%s,%s,%s,'external_command',%s,%s,%s)", (command.tenant_id, command.target_id, before, after, command.principal_ref, command.command_id, revision, json.dumps(list(refs))))

    @staticmethod
    def _operation(cursor: psycopg.Cursor, command: CommandEnvelope, operation_id: str) -> None:
        cursor.execute("INSERT INTO operations(operation_id,tenant_id,command_id,provider,provider_workflow_id,status) VALUES (%s,%s,%s,'temporal',%s,'committed')", (operation_id, command.tenant_id, command.command_id, f"acs-p1/{command.command_id}"))

    @staticmethod
    def _outbox(cursor: psycopg.Cursor, command: CommandEnvelope, operation_id: str, topic: str, payload: dict[str, str]) -> None:
        cursor.execute("INSERT INTO outbox(tenant_id,message_id,operation_id,topic,payload) VALUES (%s,%s,%s,%s,%s)", (command.tenant_id, f"msg-{command.command_id}", operation_id, topic, json.dumps(payload)))
