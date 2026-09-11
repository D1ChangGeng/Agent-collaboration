from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from runtime.effects import LocalFileEffectGateway
from runtime.errors import (
    AcceptanceGuardFailed,
    AuthorizationDenied,
    RevisionConflict,
    RuntimeErrorBase,
)
from runtime.models import CommandEnvelope, CommandResult, EvidenceRecord, WorkItemState


class _RegistrationInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    effect_id: str = Field(min_length=1, max_length=256)
    lease_id: str = Field(min_length=1, max_length=256)
    resource_id: str = Field(min_length=1, max_length=256)
    readback_ref: str = Field(min_length=1, max_length=256)
    operation_id: str = Field(min_length=1, max_length=256)


class _GatewayObservation(BaseModel):
    """Internal shared-cursor Gateway result, never accepted from a request body."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    status: Literal["verified"]
    operation_id: str = Field(min_length=1, max_length=256)
    resource_id: str = Field(min_length=1, max_length=256)
    readback_ref: str = Field(min_length=1, max_length=256)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bytes: int = Field(ge=0)
    size_bytes: int = Field(ge=0)
    intent_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    completion_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    completion_state: Literal["prepared", "completed"]
    observation: Literal["current_resource"]

    @model_validator(mode="after")
    def coherent_completion(self):
        if self.bytes != self.size_bytes:
            raise ValueError("Gateway byte lengths differ")
        if (self.completion_state == "completed") != (self.completion_sha256 is not None):
            raise ValueError("Gateway completion state and proof differ")
        return self


class EffectDomain:
    """Authenticated publication registration delegated by DomainAuthority.

    The injected Gateway is trusted service configuration. Both effect.register
    and effect.read are required. effect.write remains the separate permission
    checked by the Gateway while performing protected writes.
    """

    def __init__(self, authority: Any, gateway: LocalFileEffectGateway | None) -> None:
        self._authority = authority
        self._gateway = gateway

    def _ready_output_bindings(self, cursor, command, work_item):
        authority = self._authority
        cursor.execute(
            "SELECT baseline_ref,scope_id,candidate_ref,evidence_refs,evidence_bundle_refs,review_ref,readback_digest "
            "FROM accepted_state_revisions WHERE tenant_id=%s AND work_item_id=%s "
            "AND revision=%s AND readiness_snapshot=TRUE FOR UPDATE",
            (command.tenant_id, command.target_id, int(work_item[2])),
        )
        snapshot = cursor.fetchone()
        if (snapshot is None or snapshot[0] != work_item[3] or snapshot[1] != work_item[0]
                or not snapshot[2] or len(snapshot[3]) != 1 or len(snapshot[4]) != 1):
            raise AcceptanceGuardFailed("current ready candidate snapshot is missing")
        cursor.execute(
            "SELECT to_jsonb(e),to_jsonb(b) FROM evidence e JOIN evidence_bundles b "
            "ON b.tenant_id=e.tenant_id AND b.work_item_id=e.work_item_id AND b.evidence_id=e.evidence_id "
            "WHERE e.tenant_id=%s AND e.work_item_id=%s AND e.evidence_id=ANY(%s) FOR UPDATE OF e,b",
            (command.tenant_id, command.target_id, list(snapshot[3])),
        )
        rows = cursor.fetchall()
        if len(rows) != 1:
            raise AcceptanceGuardFailed("ready candidate evidence is missing")
        stored, stored_bundle = rows[0]
        evidence = authority._typed_evidence(
            EvidenceRecord, {key: value for key, value in stored.items() if key in EvidenceRecord.model_fields},
            "ready candidate evidence is invalid",
        )
        bundle, receipt, bound = authority._validate_bundle(
            cursor, evidence, stored_bundle["bundle_json"], command.target_id, str(work_item[3]), str(work_item[0]),
        )
        if (bundle.candidate_ref != snapshot[2] or bundle.evidence_id not in snapshot[4]
                or stored_bundle["bundle_id"] != bundle.evidence_id
                or stored_bundle["receipt_id"] != receipt.receipt_id):
            raise AcceptanceGuardFailed("ready candidate evidence binding differs")
        cursor.execute(
            "SELECT reviewer_ref,authority_incarnation,assignment_revision,candidate_ref,evidence_set_hash "
            "FROM reviews WHERE tenant_id=%s AND work_item_id=%s AND review_id=%s FOR UPDATE",
            (command.tenant_id, command.target_id, snapshot[5]),
        )
        review = cursor.fetchone()
        if review is None:
            raise AcceptanceGuardFailed("ready review source seal is missing")
        source_seal = {
            "baseline_ref": snapshot[0], "candidate_ref": snapshot[2],
            "bundle_digests": [authority._evidence_digest(bundle.model_dump(mode="json"))],
            "review": {"review_ref": snapshot[5], "reviewer_ref": review[0],
                       "authority_incarnation": review[1], "assignment_revision": review[2],
                       "candidate_ref": review[3], "evidence_set_hash": review[4]},
            "artifacts": sorted([ref.model_dump(mode="json") for ref in receipt.readback_refs],
                                key=authority._evidence_digest),
        }
        if authority._evidence_digest(source_seal) != snapshot[6]:
            raise AcceptanceGuardFailed("ready source or review seal changed")
        outputs = {(ref.sha256, ref.size_bytes) for ref in receipt.artifact_refs if ref.kind == "output"}
        deadlines = [bound["producer_expires_at"], bound["observer_expires_at"]]
        if bundle.expires_at is not None:
            deadlines.append(bundle.expires_at)
        return str(snapshot[2]), outputs, deadlines

    def _lease_binding(self, cursor, command, work_item, request):
        cursor.execute(
            "SELECT l.generation,l.fencing_token,g.expires_at "
            "FROM leases l JOIN attempts a ON a.tenant_id=l.tenant_id AND a.attempt_id=l.owner_attempt_id "
            "AND a.runtime_id=l.owner_runtime_id AND a.scope_id=l.scope_id AND a.grant_ref=l.grant_ref "
            "AND a.authority_id=l.authority_id AND a.authority_incarnation=l.authority_incarnation "
            "JOIN work_items w ON w.tenant_id=a.tenant_id AND w.work_item_id=a.work_item_id "
            "AND w.scope_id=a.scope_id AND w.agent_slot_id=a.agent_slot_id "
            "JOIN agent_slots s ON s.tenant_id=a.tenant_id AND s.agent_slot_id=a.agent_slot_id "
            "AND s.scope_id=a.scope_id AND s.status='active' "
            "JOIN grants g ON g.tenant_id=a.tenant_id AND g.grant_ref=a.grant_ref "
            "AND g.principal_ref=a.producer_ref AND g.scope_id=a.scope_id "
            "AND g.authority_id=a.authority_id AND g.authority_incarnation=a.authority_incarnation "
            "WHERE l.tenant_id=%s AND l.lease_id=%s AND l.resource_id=%s "
            "AND a.work_item_id=%s AND l.scope_id=%s AND g.grant_ref=%s AND g.principal_ref=%s "
            "AND l.authority_id=%s AND l.authority_incarnation=%s "
            "AND g.revoked_at IS NULL AND g.expires_at>clock_timestamp() FOR UPDATE OF l,a,w,s,g",
            (command.tenant_id, request.lease_id, request.resource_id, command.target_id, str(work_item[0]),
             command.grant_ref, command.principal_ref, command.authority_id, command.authority_incarnation),
        )
        binding = cursor.fetchone()
        if binding is None:
            raise AcceptanceGuardFailed("publication lease owner binding is missing or unauthorized")
        return binding

    def _observe(self, cursor, command, work_item, request, generation, fencing_token):
        if self._gateway is None:
            raise AcceptanceGuardFailed("publication registration Gateway is unavailable")
        try:
            observed = _GatewayObservation.model_validate(
                self._gateway.historical_readback_in_transaction(
                    cursor, lease_id=request.lease_id, resource_id=request.resource_id,
                    generation=generation, fencing_token=fencing_token, readback_ref=request.readback_ref,
                    caller=self._authority.context, scope_id=str(work_item[0]), grant_ref=command.grant_ref,
                    authority_incarnation=command.authority_incarnation,
                    expected_operation_id=request.operation_id,
                ), strict=True,
            )
        except (RuntimeErrorBase, ValueError, TypeError, OSError):
            raise AcceptanceGuardFailed("publication Gateway readback failed") from None
        if (observed.operation_id != request.operation_id or observed.resource_id != request.resource_id
                or observed.readback_ref != request.readback_ref):
            raise AcceptanceGuardFailed("publication Gateway identity differs")
        return observed

    def _historical_lease_binding(self, cursor, command, work_item, request):
        """Bind original execution provenance independently of the reader Grant.

        The original writer may be revoked or expired after a recovery handoff.
        Current effect.register/effect.read authorization belongs to the new
        reconciler; historical identity remains tied to its original Lease.
        """
        cursor.execute(
            "SELECT l.generation,l.fencing_token,l.grant_ref,cg.expires_at "
            "FROM leases l JOIN attempts a ON a.tenant_id=l.tenant_id AND a.attempt_id=l.owner_attempt_id "
            "AND a.runtime_id=l.owner_runtime_id AND a.scope_id=l.scope_id AND a.grant_ref=l.grant_ref "
            "AND a.authority_id=l.authority_id AND a.authority_incarnation=l.authority_incarnation "
            "JOIN work_items w ON w.tenant_id=a.tenant_id AND w.work_item_id=a.work_item_id "
            "AND w.scope_id=a.scope_id "
            "JOIN grants pg ON pg.tenant_id=a.tenant_id AND pg.grant_ref=a.grant_ref "
            "AND pg.principal_ref=a.producer_ref AND pg.scope_id=a.scope_id "
            "AND pg.authority_id=a.authority_id AND pg.authority_incarnation=a.authority_incarnation "
            "JOIN authority_instances ai ON ai.authority_id=l.authority_id "
            "AND ai.authority_incarnation=l.authority_incarnation AND ai.status IN ('active','revoked') "
            "JOIN grants cg ON cg.tenant_id=w.tenant_id AND cg.scope_id=w.scope_id "
            "WHERE l.tenant_id=%s AND l.lease_id=%s AND l.resource_id=%s AND a.work_item_id=%s "
            "AND l.scope_id=%s AND l.authority_id=%s "
            "AND cg.grant_ref=%s AND cg.principal_ref=%s "
            "AND cg.authority_id=%s AND cg.authority_incarnation=%s AND cg.revoked_at IS NULL "
            "FOR UPDATE OF l,a,w,pg,ai,cg",
            (command.tenant_id, request.lease_id, request.resource_id, command.target_id, str(work_item[0]),
             command.authority_id, command.grant_ref, command.principal_ref,
             command.authority_id, command.authority_incarnation),
        )
        binding = cursor.fetchone()
        if binding is None:
            raise AcceptanceGuardFailed("historical publication lease provenance is missing or mismatched")
        return binding

    def register_effect(
        self, command: CommandEnvelope, *, effect_id: str, lease_id: str,
        resource_id: str, readback_ref: str, operation_id: str,
    ) -> CommandResult:
        authority = self._authority
        if command.command_type != "effect.register" or command.target_kind != "work_item":
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        try:
            request = _RegistrationInput(
                effect_id=effect_id, lease_id=lease_id, resource_id=resource_id,
                readback_ref=readback_ref, operation_id=operation_id,
            )
        except (TypeError, ValueError):
            raise AcceptanceGuardFailed("invalid publication registration input") from None
        extra = {"effect_registration": request.model_dump(mode="json")}
        with authority._connect() as connection, connection.cursor() as cursor:
            work_item = authority._lock_work_item(
                cursor, command, command.target_id, permission="effect.register",
            )
            authority._authorize(command, cursor, "effect.read", str(work_item[0]))
            result = CommandResult(
                command_id=command.command_id, operation_id=f"op-{uuid.uuid4()}",
                target_id=command.target_id, revision=int(work_item[2]), state="effect_registered",
            )
            duplicate, digest = authority._dedup(cursor, command, result, extra)
            if duplicate is not None:
                return duplicate
            if command.expected_revision != int(work_item[2]):
                raise RevisionConflict(command.target_id, command.expected_revision, int(work_item[2]))
            if work_item[1] != WorkItemState.ACCEPTANCE_READY:
                raise AcceptanceGuardFailed("effect registration requires an acceptance-ready work item")
            if self._gateway is None:
                raise AcceptanceGuardFailed("publication registration Gateway is unavailable")
            cursor.execute(
                "SELECT effect_id FROM effects WHERE effect_id=%s OR "
                "(tenant_id=%s AND work_item_id=%s AND resource_id=%s AND operation_id=%s) FOR UPDATE",
                (request.effect_id, command.tenant_id, command.target_id, request.resource_id, request.operation_id),
            )
            if cursor.fetchone() is not None:
                raise AcceptanceGuardFailed("publication effect identity is already registered")
            candidate, outputs, deadlines = self._ready_output_bindings(cursor, command, work_item)
            generation, fencing_token, owner_expires = self._lease_binding(cursor, command, work_item, request)
            deadlines.extend((command.deadline, owner_expires))
            # WorkItem -> authorization/Lease rows -> filesystem is the shared
            # acceptance order. This path never opens a separate readback DB
            # transaction and never acquires the writer resource advisory lock.
            observed = self._observe(cursor, command, work_item, request, generation, fencing_token)
            if (observed.sha256, observed.size_bytes) not in outputs:
                raise AcceptanceGuardFailed("publication bytes do not match the ready candidate")
            status = "verified" if observed.completion_state == "completed" else "uncertain"
            valid_until: datetime = min(deadlines)
            cursor.execute(
                "INSERT INTO effects(effect_id,tenant_id,work_item_id,resource_id,baseline_ref,lease_id,"
                "fencing_token,generation,status,readback_ref,grant_ref,candidate_ref,operation_id,"
                "expected_sha256,expected_size_bytes,intent_sha256,completion_sha256,completion_state,"
                "registered_readback,registered_by,registration_command_id,registration_operation_id) "
                "SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s "
                "WHERE clock_timestamp()<%s",
                (request.effect_id, command.tenant_id, command.target_id, request.resource_id, str(work_item[3]),
                 request.lease_id, fencing_token, generation, status, observed.readback_ref, command.grant_ref,
                 candidate, observed.operation_id, observed.sha256, observed.size_bytes, observed.intent_sha256,
                 observed.completion_sha256, observed.completion_state, observed.model_dump_json(),
                 command.principal_ref, command.command_id, result.operation_id, valid_until),
            )
            if cursor.rowcount != 1:
                raise AcceptanceGuardFailed("publication registration authorization expired during verification")
            authority._record(cursor, command, WorkItemState(work_item[1]), WorkItemState(work_item[1]),
                              int(work_item[2]), (request.effect_id,), digest)
            cursor.execute(
                "UPDATE effects SET registration_event_id=(SELECT event_id::text FROM domain_events "
                "WHERE tenant_id=%s AND work_item_id=%s AND command_id=%s ORDER BY event_id DESC LIMIT 1) "
                "WHERE tenant_id=%s AND effect_id=%s",
                (command.tenant_id, command.target_id, command.command_id, command.tenant_id, request.effect_id),
            )
            authority._operation(cursor, command, result.operation_id)
            authority._outbox(cursor, command, result.operation_id, "effect.registered",
                              {"effect_id": request.effect_id, "status": status,
                               "execution_operation_id": observed.operation_id,
                               "readback": observed.model_dump_json()})
            return result

    def reconcile_effect(self, command: CommandEnvelope, *, effect_id: str) -> CommandResult:
        """Reobserve an existing uncertain Effect; never apply or resume writes."""
        authority = self._authority
        if command.command_type != "effect.reconcile" or command.target_kind != "work_item":
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        if not isinstance(effect_id, str) or not 1 <= len(effect_id) <= 256:
            raise AcceptanceGuardFailed("invalid publication reconciliation input")
        with authority._connect() as connection, connection.cursor() as cursor:
            work_item = authority._lock_work_item(cursor, command, command.target_id, permission="effect.register")
            authority._authorize(command, cursor, "effect.read", str(work_item[0]))
            result = CommandResult(command_id=command.command_id, operation_id=f"op-{uuid.uuid4()}",
                                   target_id=command.target_id, revision=int(work_item[2]), state="effect_reconciled")
            duplicate, digest = authority._dedup(
                cursor, command, result, {"effect_reconciliation": {"effect_id": effect_id}})
            if duplicate is not None:
                return duplicate
            if command.expected_revision != int(work_item[2]):
                raise RevisionConflict(command.target_id, command.expected_revision, int(work_item[2]))
            if work_item[1] != WorkItemState.ACCEPTANCE_READY:
                raise AcceptanceGuardFailed("effect reconciliation requires an acceptance-ready work item")
            cursor.execute(
                "SELECT lease_id,resource_id,readback_ref,operation_id,candidate_ref,baseline_ref,status,"
                "generation,fencing_token,grant_ref,expected_sha256,expected_size_bytes,intent_sha256,"
                "registration_command_id,registration_operation_id,registration_event_id "
                "FROM effects WHERE tenant_id=%s AND work_item_id=%s AND effect_id=%s FOR UPDATE",
                (command.tenant_id, command.target_id, effect_id),
            )
            row = cursor.fetchone()
            if row is None or row[6] != "uncertain":
                raise AcceptanceGuardFailed("effect reconciliation requires an uncertain registered effect")
            if any(row[index] is None for index in range(len(row))):
                raise AcceptanceGuardFailed("uncertain effect identity or registration lineage is incomplete")
            request = _RegistrationInput(effect_id=effect_id, lease_id=row[0], resource_id=row[1],
                                         readback_ref=row[2], operation_id=row[3])
            candidate, outputs, deadlines = self._ready_output_bindings(cursor, command, work_item)
            generation, fencing_token, original_grant, reconciler_expires = self._historical_lease_binding(
                cursor, command, work_item, request)
            if (row[4] != candidate or row[5] != work_item[3] or row[7] != generation
                    or row[8] != fencing_token or row[9] != original_grant):
                raise AcceptanceGuardFailed("uncertain effect immutable identity differs")
            observed = self._observe(cursor, command, work_item, request, generation, fencing_token)
            if (observed.sha256 != row[10] or observed.size_bytes != row[11]
                    or observed.intent_sha256 != row[12]
                    or (observed.sha256, observed.size_bytes) not in outputs):
                raise AcceptanceGuardFailed("reconciliation differs from original intent or payload")
            status = "verified" if observed.completion_state == "completed" else "uncertain"
            valid_until = min([command.deadline, reconciler_expires, *deadlines])
            cursor.execute(
                "UPDATE effects SET status=%s,completion_sha256=%s,completion_state=%s,reconciled_readback=%s,"
                "reconciliation_command_id=%s,reconciliation_operation_id=%s "
                "WHERE tenant_id=%s AND work_item_id=%s AND effect_id=%s AND status='uncertain' "
                "AND clock_timestamp()<%s",
                (status, observed.completion_sha256, observed.completion_state, observed.model_dump_json(),
                 command.command_id, result.operation_id, command.tenant_id, command.target_id, effect_id, valid_until),
            )
            if cursor.rowcount != 1:
                raise AcceptanceGuardFailed("publication reconciliation authorization expired during verification")
            authority._record(cursor, command, WorkItemState(work_item[1]), WorkItemState(work_item[1]),
                              int(work_item[2]), (effect_id,), digest)
            cursor.execute(
                "UPDATE effects SET reconciliation_event_id=(SELECT event_id::text FROM domain_events "
                "WHERE tenant_id=%s AND work_item_id=%s AND command_id=%s ORDER BY event_id DESC LIMIT 1) "
                "WHERE tenant_id=%s AND effect_id=%s",
                (command.tenant_id, command.target_id, command.command_id, command.tenant_id, effect_id),
            )
            authority._operation(cursor, command, result.operation_id)
            authority._outbox(cursor, command, result.operation_id, "effect.reconciled",
                              {"effect_id": effect_id, "status": status,
                               "execution_operation_id": observed.operation_id,
                               "readback": observed.model_dump_json()})
            return result
