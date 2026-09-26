from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable
from pathlib import Path

import psycopg
from psycopg.sql import SQL

from runtime.errors import (
    AcceptanceGuardFailed,
    AuthorizationDenied,
    IdempotencyConflict,
    InvalidTransition,
    NotFound,
    RevisionConflict,
)
from runtime.models import (
    AuthenticatedContext,
    CommandEnvelope,
    CommandResult,
    EvidenceRecord,
    TransitionRequest,
    WorkItemState,
)


class DomainAuthority:
    def __init__(self, dsn: str, context: AuthenticatedContext | None = None) -> None:
        self._dsn = dsn
        self.context = context or AuthenticatedContext("local-tenant", "acs-p1-authority", "local-1", "agent:engineer", "grant:p1")

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._dsn)

    def initialize(self) -> None:
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(SQL(schema))
            cursor.execute("INSERT INTO authority_instances(authority_id,authority_incarnation,status) VALUES (%s,%s,'active') ON CONFLICT DO NOTHING", (self.context.authority_id, self.context.authority_incarnation))
            cursor.execute("INSERT INTO scopes(scope_id,tenant_id,policy,status) VALUES ('local-scope',%s,'{}','active') ON CONFLICT DO NOTHING", (self.context.tenant_id,))
            cursor.execute("INSERT INTO agent_slots(agent_slot_id,tenant_id,scope_id,status) VALUES ('local-slot',%s,'local-scope','active') ON CONFLICT DO NOTHING", (self.context.tenant_id,))
            cursor.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,scope_id,permissions,expires_at) VALUES (%s,%s,%s,%s,%s,'local-scope',%s,now()+interval '365 days') ON CONFLICT DO NOTHING", (self.context.grant_ref, self.context.tenant_id, self.context.principal_ref, self.context.authority_id, self.context.authority_incarnation, json.dumps(["work_item.create", "work_item.transition", "evidence.record", "review.record", "lease.acquire"])))

    def _authorize(self, command: CommandEnvelope, cursor: psycopg.Cursor, permission: str) -> None:
        expected = self.context
        if (command.tenant_id, command.authority_id, command.authority_incarnation, command.principal_ref, command.grant_ref) != (expected.tenant_id, expected.authority_id, expected.authority_incarnation, expected.principal_ref, expected.grant_ref):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        cursor.execute("SELECT permissions FROM grants g JOIN authority_instances a USING(authority_id,authority_incarnation) JOIN scopes s ON s.scope_id=g.scope_id WHERE g.grant_ref=%s AND g.tenant_id=%s AND g.principal_ref=%s AND a.status='active' AND s.status='active' AND g.revoked_at IS NULL AND g.expires_at>now()", (expected.grant_ref, expected.tenant_id, expected.principal_ref))
        row = cursor.fetchone()
        if row is None or permission not in list(row[0]):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)

    @staticmethod
    def _hash(command: CommandEnvelope, extra: dict[str, object]) -> str:
        value = json.dumps({"command_type": command.command_type, "target_kind": command.target_kind, "target_id": command.target_id, "expected_revision": command.expected_revision, "payload": command.payload, "extra": extra}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(value.encode()).hexdigest()

    def _dedup(self, cursor: psycopg.Cursor, command: CommandEnvelope, result: CommandResult, extra: dict[str, object]) -> CommandResult | None:
        digest = self._hash(command, extra)
        cursor.execute("INSERT INTO command_dedup(tenant_id,idempotency_key,payload_hash,result_json) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING", (self.context.tenant_id, command.idempotency_key, digest, result.model_dump_json()))
        if cursor.rowcount == 1:
            return None
        cursor.execute("SELECT payload_hash,result_json FROM command_dedup WHERE tenant_id=%s AND idempotency_key=%s FOR UPDATE", (self.context.tenant_id, command.idempotency_key))
        row = cursor.fetchone()
        if row is None or row[0] != digest:
            raise IdempotencyConflict(command.idempotency_key)
        return CommandResult.model_validate(row[1]).model_copy(update={"duplicate": True})

    @staticmethod
    def _op() -> str:
        return f"op-{uuid.uuid4()}"

    def create_work_item(self, command: CommandEnvelope, scope_id: str, agent_slot_id: str, source_baseline: str) -> CommandResult:
        result = CommandResult(command_id=command.command_id, operation_id=self._op(), target_id=command.target_id, revision=0, state=WorkItemState.CANDIDATE)
        with self._connect() as connection, connection.cursor() as cursor:
            self._authorize(command, cursor, "work_item.create")
            duplicate = self._dedup(cursor, command, result, {"scope_id": scope_id, "agent_slot_id": agent_slot_id, "source_baseline": source_baseline})
            if duplicate is not None:
                return duplicate
            cursor.execute("SELECT 1 FROM scopes s JOIN agent_slots a ON a.scope_id=s.scope_id WHERE s.scope_id=%s AND a.agent_slot_id=%s AND s.tenant_id=%s AND s.status='active' AND a.status='active'", (scope_id, agent_slot_id, self.context.tenant_id))
            if cursor.fetchone() is None:
                raise AuthorizationDenied(command.principal_ref, command.grant_ref)
            cursor.execute("INSERT INTO work_items(work_item_id,tenant_id,scope_id,agent_slot_id,state,execution_status,source_baseline,created_by) VALUES (%s,%s,%s,%s,'candidate','ready',%s,%s)", (command.target_id, self.context.tenant_id, scope_id, agent_slot_id, source_baseline, self.context.principal_ref))
            self._record(cursor, command, None, WorkItemState.CANDIDATE, 0, ())
            self._operation(cursor, command, result.operation_id)
            self._outbox(cursor, command, result.operation_id, "work_item.created", {"state": "candidate"})
        return result

    def transition_work_item(self, command: CommandEnvelope, transition: TransitionRequest) -> CommandResult:
        with self._connect() as connection, connection.cursor() as cursor:
            self._authorize(command, cursor, "work_item.transition")
            result = CommandResult(command_id=command.command_id, operation_id=self._op(), target_id=command.target_id, revision=command.expected_revision + 1, state=transition.to_state)
            duplicate = self._dedup(cursor, command, result, {"transition": transition.model_dump(mode="json")})
            if duplicate is not None:
                return duplicate
            cursor.execute("SELECT state,revision,source_baseline FROM work_items WHERE tenant_id=%s AND work_item_id=%s FOR UPDATE", (self.context.tenant_id, command.target_id))
            row = cursor.fetchone()
            if row is None:
                raise NotFound("work_item", command.target_id)
            current = WorkItemState(row[0])
            revision = int(row[1])
            if revision != command.expected_revision:
                raise RevisionConflict(command.target_id, command.expected_revision, revision)
            self._guard(cursor, command.target_id, current, transition, row[2])
            next_revision = revision + 1
            cursor.execute("UPDATE work_items SET state=%s,revision=%s,updated_at=now() WHERE tenant_id=%s AND work_item_id=%s", (transition.to_state, next_revision, self.context.tenant_id, command.target_id))
            self._record(cursor, command, current, transition.to_state, next_revision, transition.evidence_refs)
            if transition.to_state is WorkItemState.ACCEPTED:
                cursor.execute("INSERT INTO accepted_state_revisions(tenant_id,work_item_id,revision,baseline_ref,evidence_refs,review_ref,effect_refs,readback_refs) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (self.context.tenant_id, command.target_id, next_revision, row[2], json.dumps(transition.evidence_refs), transition.review_ref, json.dumps(transition.effect_refs), json.dumps(transition.readback_refs)))
            self._operation(cursor, command, result.operation_id)
            self._outbox(cursor, command, result.operation_id, f"work_item.{transition.to_state}", {"state": transition.to_state})
            return result.model_copy(update={"revision": next_revision})

    @staticmethod
    def _guard(cursor: psycopg.Cursor, work_item_id: str, current: WorkItemState, transition: TransitionRequest, baseline: str) -> None:
        if current is WorkItemState.CANDIDATE and transition.to_state is WorkItemState.ACCEPTANCE_READY:
            if not transition.evidence_refs or transition.review_ref is None:
                raise AcceptanceGuardFailed("evidence and review are required")
            cursor.execute("SELECT count(*) AS n FROM evidence WHERE work_item_id=%s AND baseline_ref=%s AND evidence_id=ANY(%s)", (work_item_id, baseline, list(transition.evidence_refs)))
            count_row = cursor.fetchone()
            if count_row is None or int(count_row[0]) != len(transition.evidence_refs):
                raise AcceptanceGuardFailed("baseline-bound evidence is missing")
            cursor.execute("SELECT 1 FROM reviews r JOIN grants g ON g.grant_ref=r.reviewer_grant_ref WHERE r.work_item_id=%s AND r.review_id=%s AND r.verdict='pass' AND r.baseline_ref=%s AND g.revoked_at IS NULL AND g.expires_at>now()", (work_item_id, transition.review_ref, baseline))
            if cursor.fetchone() is None:
                raise AcceptanceGuardFailed("independent review is missing")
            return
        if current is WorkItemState.ACCEPTANCE_READY and transition.to_state is WorkItemState.ACCEPTED:
            cursor.execute("SELECT count(*) AS n FROM effects WHERE work_item_id=%s AND effect_id=ANY(%s) AND status='verified' AND readback_ref=ANY(%s)", (work_item_id, list(transition.effect_refs), list(transition.readback_refs)))
            effect_count = cursor.fetchone()
            if not transition.effect_refs or not transition.readback_refs or effect_count is None or int(effect_count[0]) != len(transition.effect_refs):
                raise AcceptanceGuardFailed("verified effect readback is missing")
            return
        raise InvalidTransition(current, transition.to_state)

    def record_evidence(self, command: CommandEnvelope, evidence: EvidenceRecord) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            self._authorize(command, cursor, "evidence.record")
            cursor.execute("SELECT 1 FROM work_items WHERE tenant_id=%s AND work_item_id=%s FOR UPDATE", (self.context.tenant_id, evidence.work_item_id))
            if cursor.fetchone() is None:
                raise NotFound("work_item", evidence.work_item_id)
            result = CommandResult(command_id=command.command_id, operation_id=self._op(), target_id=evidence.work_item_id, revision=0, state="evidence")
            if self._dedup(cursor, command, result, {"evidence": evidence.model_dump(mode="json")}) is not None:
                return
            cursor.execute("INSERT INTO evidence(evidence_id,tenant_id,work_item_id,observer_ref,source_class,baseline_ref,artifact_sha256,summary) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", (evidence.evidence_id, self.context.tenant_id, evidence.work_item_id, evidence.observer_ref, evidence.source_class, evidence.baseline_ref, evidence.artifact_sha256, evidence.summary))
            if cursor.rowcount != 1:
                raise IdempotencyConflict(evidence.evidence_id)

    def record_review(self, command: CommandEnvelope, review_id: str, work_item_id: str, verdict: str, evidence_ref: str, baseline_ref: str) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            self._authorize(command, cursor, "review.record")
            result = CommandResult(command_id=command.command_id, operation_id=self._op(), target_id=work_item_id, revision=0, state="review")
            if self._dedup(cursor, command, result, {"review_id": review_id, "work_item_id": work_item_id, "verdict": verdict, "evidence_ref": evidence_ref, "baseline_ref": baseline_ref}) is not None:
                return
            cursor.execute("INSERT INTO reviews(review_id,tenant_id,work_item_id,reviewer_ref,reviewer_grant_ref,verdict,evidence_ref,baseline_ref) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", (review_id, self.context.tenant_id, work_item_id, self.context.principal_ref, self.context.grant_ref, verdict, evidence_ref, baseline_ref))
            if cursor.rowcount != 1:
                raise IdempotencyConflict(review_id)

    def get_work_item(self, work_item_id: str) -> dict[str, str | int] | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT work_item_id,state,execution_status,revision,source_baseline FROM work_items WHERE tenant_id=%s AND work_item_id=%s", (self.context.tenant_id, work_item_id))
            row = cursor.fetchone()
            return None if row is None else {"work_item_id": row[0], "state": row[1], "execution_status": row[2], "revision": row[3], "source_baseline": row[4]}

    @staticmethod
    def _record(cursor: psycopg.Cursor, command: CommandEnvelope, before: WorkItemState | None, after: WorkItemState, revision: int, refs: Iterable[str]) -> None:
        cursor.execute("INSERT INTO domain_events(tenant_id,work_item_id,from_state,to_state,initiated_by,lineage_mode,command_id,resulting_revision,evidence_refs) VALUES (%s,%s,%s,%s,%s,'external_command',%s,%s,%s)", (command.tenant_id, command.target_id, before, after, command.principal_ref, command.command_id, revision, json.dumps(list(refs))))

    @staticmethod
    def _operation(cursor: psycopg.Cursor, command: CommandEnvelope, operation_id: str) -> None:
        cursor.execute("INSERT INTO operations(operation_id,tenant_id,command_id,provider,provider_workflow_id,status) VALUES (%s,%s,%s,'temporal',%s,'committed')", (operation_id, command.tenant_id, command.command_id, f"acs-p1/{command.command_id}"))

    @staticmethod
    def _outbox(cursor: psycopg.Cursor, command: CommandEnvelope, operation_id: str, topic: str, payload: dict[str, str]) -> None:
        cursor.execute("INSERT INTO outbox(tenant_id,message_id,operation_id,topic,payload) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", (command.tenant_id, f"msg-{command.command_id}", operation_id, topic, json.dumps(payload)))
