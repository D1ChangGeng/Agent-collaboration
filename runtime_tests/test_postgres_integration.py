from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from runtime.domain import DomainAuthority
from runtime.errors import AcceptanceGuardFailed, AuthorizationDenied, FencingRejected
from runtime.models import (
    AuthenticatedContext,
    CommandEnvelope,
    EvidenceRecord,
    LeaseRequest,
    TransitionRequest,
    WorkItemState,
)

DSN = os.getenv("ACS_P1_DSN", "")


def make_command(authority: DomainAuthority, command_type: str, target_id: str, idempotency_key: str, expected_revision: int = 0) -> CommandEnvelope:
    now = datetime.now(UTC)
    return CommandEnvelope(
        command_id=f"cmd-{idempotency_key}",
        command_type=command_type,
        idempotency_key=idempotency_key,
        correlation_id=f"corr-{idempotency_key}",
        tenant_id=authority.context.tenant_id,
        authority_id=authority.context.authority_id,
        authority_incarnation=authority.context.authority_incarnation,
        principal_ref=authority.context.principal_ref,
        grant_ref=authority.context.grant_ref,
        target_kind="work_item",
        target_id=target_id,
        expected_revision=expected_revision,
        issued_at=now,
        deadline=now + timedelta(minutes=5),
    )


@pytest.mark.skipif(not DSN, reason="NOT_RUN: ACS_P1_DSN is not set")
def test_real_postgres_authority_retry_revocation_and_acceptance_guards() -> None:
    authority = DomainAuthority(DSN)
    authority.initialize()
    authority.bootstrap_local_grant()
    work_item_id = f"work-{uuid.uuid4()}"
    create = make_command(authority, "work_item.create", work_item_id, f"create-{work_item_id}")

    first = authority.create_work_item(create, "local-scope", "local-slot", "baseline-real")
    retry = authority.create_work_item(create, "local-scope", "local-slot", "baseline-real")
    assert retry.duplicate is True
    assert retry.operation_id == first.operation_id

    evidence = EvidenceRecord(
        evidence_id=f"evidence-{work_item_id}",
        work_item_id=work_item_id,
        observer_ref=authority.context.principal_ref,
        source_class="directly_verified",
        baseline_ref="baseline-real",
        artifact_sha256="a" * 64,
        summary="real PostgreSQL authority evidence",
    )
    authority.record_evidence(make_command(authority, "evidence.record", work_item_id, f"evidence-command-{work_item_id}"), evidence)
    with pytest.raises(AuthorizationDenied):
        authority.record_review(make_command(authority, "review.record", work_item_id, f"review-command-{work_item_id}"), f"review-{work_item_id}", work_item_id, "pass", evidence.evidence_id, "baseline-real")

    with psycopg.connect(DSN) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM domain_events WHERE tenant_id=%s AND command_id IN (%s,%s)", (authority.context.tenant_id, f"cmd-evidence-command-{work_item_id}", f"cmd-review-command-{work_item_id}"))
        event_count = cursor.fetchone()
        assert event_count is not None and event_count[0] == 1
        cursor.execute("SELECT count(*) FROM outbox WHERE tenant_id=%s AND operation_id IN (SELECT operation_id FROM operations WHERE command_id IN (%s,%s))", (authority.context.tenant_id, f"cmd-evidence-command-{work_item_id}", f"cmd-review-command-{work_item_id}"))
        outbox_count = cursor.fetchone()
        assert outbox_count is not None and outbox_count[0] == 1

    with psycopg.connect(DSN) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE grants SET revoked_at=now() WHERE grant_ref=%s", (authority.context.grant_ref,))
    with pytest.raises(AuthorizationDenied):
        authority.transition_work_item(make_command(authority, "work_item.transition", work_item_id, f"blocked-{work_item_id}"), TransitionRequest(to_state=WorkItemState.ACCEPTANCE_READY, evidence_refs=(evidence.evidence_id,), review_ref=f"review-{work_item_id}"))
    with psycopg.connect(DSN) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE grants SET revoked_at=NULL WHERE grant_ref=%s", (authority.context.grant_ref,))

    with pytest.raises(AcceptanceGuardFailed):
        authority.transition_work_item(make_command(authority, "work_item.transition", work_item_id, f"ready-{work_item_id}"), TransitionRequest(to_state=WorkItemState.ACCEPTANCE_READY, evidence_refs=(evidence.evidence_id,), review_ref=f"review-{work_item_id}"))

    forged = evidence.model_copy(update={"observer_ref": "different-observer"})
    with pytest.raises(AuthorizationDenied):
        authority.record_evidence(make_command(authority, "evidence.record", work_item_id, f"forged-evidence-{work_item_id}"), forged)


@pytest.mark.skipif(not DSN, reason="NOT_RUN: ACS_P1_DSN is not set")
def test_real_postgres_assigned_reviewer_can_make_readiness_eligible() -> None:
    engineer = DomainAuthority(DSN)
    engineer.initialize()
    engineer.bootstrap_local_grant()
    work_item_id = f"assigned-review-{uuid.uuid4()}"
    baseline = "baseline-assigned-review"
    engineer.create_work_item(make_command(engineer, "work_item.create", work_item_id, f"create-{work_item_id}"), "local-scope", "local-slot", baseline)
    reviewer_context = AuthenticatedContext("local-tenant", "acs-p1-authority", "local-1", f"agent:reviewer-{work_item_id}", f"grant:reviewer-{work_item_id}")
    with psycopg.connect(DSN) as connection, connection.cursor() as cursor:
        cursor.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,scope_id,permissions,expires_at) VALUES (%s,%s,%s,%s,%s,'local-scope',%s,now()+interval '1 day')", (reviewer_context.grant_ref, reviewer_context.tenant_id, reviewer_context.principal_ref, reviewer_context.authority_id, reviewer_context.authority_incarnation, '[\"review.record\",\"work_item.read\"]'))
    engineer.assign_reviewer(make_command(engineer, "reviewer.assign", work_item_id, f"assign-{work_item_id}"), work_item_id, reviewer_context.principal_ref, reviewer_context.grant_ref)
    evidence = EvidenceRecord(evidence_id=f"evidence-{work_item_id}", work_item_id=work_item_id, observer_ref=engineer.context.principal_ref, source_class="directly_verified", baseline_ref=baseline, artifact_sha256="b" * 64, summary="assigned reviewer fixture")
    engineer.record_evidence(make_command(engineer, "evidence.record", work_item_id, f"evidence-{work_item_id}"), evidence)
    reviewer = DomainAuthority(DSN, reviewer_context)
    reviewer.record_review(make_command(reviewer, "review.record", work_item_id, f"review-{work_item_id}"), f"review-{work_item_id}", work_item_id, "pass", evidence.evidence_id, baseline)
    ready = engineer.transition_work_item(make_command(engineer, "work_item.transition", work_item_id, f"ready-{work_item_id}"), TransitionRequest(to_state=WorkItemState.ACCEPTANCE_READY, evidence_refs=(evidence.evidence_id,), review_ref=f"review-{work_item_id}"))
    assert ready.state == WorkItemState.ACCEPTANCE_READY


@pytest.mark.skipif(not DSN, reason="NOT_RUN: ACS_P1_DSN is not set")
def test_real_postgres_rejects_cross_paired_effect_readback_and_forged_observer() -> None:
    authority = DomainAuthority(DSN)
    authority.initialize()
    authority.bootstrap_local_grant()
    work_item_id = f"effect-pair-{uuid.uuid4()}"
    authority.create_work_item(make_command(authority, "work_item.create", work_item_id, f"create-{work_item_id}"), "local-scope", "local-slot", "baseline-effect")
    evidence = EvidenceRecord(evidence_id=f"evidence-{work_item_id}", work_item_id=work_item_id, observer_ref=authority.context.principal_ref, source_class="directly_verified", baseline_ref="baseline-effect", artifact_sha256="c" * 64, summary="effect fixture")
    authority.record_evidence(make_command(authority, "evidence.record", work_item_id, f"evidence-{work_item_id}"), evidence)
    forged = evidence.model_copy(update={"observer_ref": "forged-observer"})
    with pytest.raises(AuthorizationDenied):
        authority.record_evidence(make_command(authority, "evidence.record", work_item_id, f"forged-{work_item_id}"), forged)

    other_authority = DomainAuthority(DSN, AuthenticatedContext(authority.context.tenant_id, "other-authority", "other-incarnation", authority.context.principal_ref, "other-grant"))
    lease = authority.leases.acquire_lease(make_command(authority, "lease.acquire", work_item_id, f"lease-{work_item_id}"), LeaseRequest(resource_id=f"resource-{work_item_id}", owner_attempt_id=f"attempt-{work_item_id}", owner_runtime_id=f"runtime-{work_item_id}", grant_ref=authority.context.grant_ref, authority_incarnation=authority.context.authority_incarnation, ttl_seconds=30))
    lease_id = lease["lease_id"]
    resource_id = lease["resource_id"]
    generation = lease["generation"]
    fencing_token = lease["fencing_token"]
    assert isinstance(lease_id, str) and isinstance(resource_id, str)
    assert isinstance(generation, int) and isinstance(fencing_token, str)
    with pytest.raises(FencingRejected):
        other_authority.leases.verify_fence(lease_id, resource_id, generation, fencing_token)
