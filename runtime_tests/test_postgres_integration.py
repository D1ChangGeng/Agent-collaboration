from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from runtime.domain import DomainAuthority
from runtime.errors import AcceptanceGuardFailed, AuthorizationDenied
from runtime.models import (
    CommandEnvelope,
    EvidenceRecord,
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
    work_item_id = f"work-{uuid.uuid4()}"
    create = make_command(authority, "work_item.create", work_item_id, f"create-{work_item_id}")

    first = authority.create_work_item(create, "local-scope", "local-slot", "baseline-real")
    retry = authority.create_work_item(create, "local-scope", "local-slot", "baseline-real")
    assert retry.duplicate is True
    assert retry.operation_id == first.operation_id

    evidence = EvidenceRecord(
        evidence_id=f"evidence-{work_item_id}",
        work_item_id=work_item_id,
        observer_ref="engineer-runtime-1302",
        source_class="directly_verified",
        baseline_ref="baseline-real",
        artifact_sha256="a" * 64,
        summary="real PostgreSQL authority evidence",
    )
    authority.record_evidence(make_command(authority, "evidence.record", work_item_id, f"evidence-command-{work_item_id}"), evidence)
    authority.record_review(make_command(authority, "review.record", work_item_id, f"review-command-{work_item_id}"), f"review-{work_item_id}", work_item_id, "pass", evidence.evidence_id, "baseline-real")

    with psycopg.connect(DSN) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE grants SET revoked_at=now() WHERE grant_ref=%s", (authority.context.grant_ref,))
    with pytest.raises(AuthorizationDenied):
        authority.transition_work_item(make_command(authority, "work_item.transition", work_item_id, f"blocked-{work_item_id}"), TransitionRequest(to_state=WorkItemState.ACCEPTANCE_READY, evidence_refs=(evidence.evidence_id,), review_ref=f"review-{work_item_id}"))
    with psycopg.connect(DSN) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE grants SET revoked_at=NULL WHERE grant_ref=%s", (authority.context.grant_ref,))

    ready = authority.transition_work_item(make_command(authority, "work_item.transition", work_item_id, f"ready-{work_item_id}"), TransitionRequest(to_state=WorkItemState.ACCEPTANCE_READY, evidence_refs=(evidence.evidence_id,), review_ref=f"review-{work_item_id}"))
    assert ready.state == WorkItemState.ACCEPTANCE_READY
    with pytest.raises(AcceptanceGuardFailed):
        authority.transition_work_item(make_command(authority, "work_item.transition", work_item_id, f"accept-{work_item_id}", ready.revision), TransitionRequest(to_state=WorkItemState.ACCEPTED, effect_refs=(f"effect-{work_item_id}",), readback_refs=(f"readback-{work_item_id}",)))
