from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from runtime.models import CommandEnvelope, EvidenceRecord, TransitionRequest, WorkItemState


def command(**overrides: object) -> dict[str, object]:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "command_id": "cmd-1",
        "command_type": "work_item.create",
        "idempotency_key": "idem-1",
        "correlation_id": "corr-1",
        "tenant_id": "tenant-1",
        "authority_id": "authority-1",
        "authority_incarnation": "inc-1",
        "principal_ref": "agent-1",
        "grant_ref": "grant-1",
        "target_kind": "work_item",
        "target_id": "work-1",
        "expected_revision": 0,
        "issued_at": now,
        "deadline": now + timedelta(minutes=1),
    }
    payload.update(overrides)
    return payload


def test_command_boundary_rejects_deadline_before_issue() -> None:
    now = datetime.now(UTC)

    with pytest.raises(ValidationError):
        CommandEnvelope.model_validate(command(issued_at=now, deadline=now - timedelta(seconds=1)))


def test_transition_boundary_requires_external_acceptance_fields() -> None:
    transition = TransitionRequest(
        to_state=WorkItemState.ACCEPTANCE_READY,
        evidence_refs=("evidence-1",),
        review_ref="review-1",
        effect_refs=("effect-1",),
        readback_refs=("readback-1",),
    )

    assert transition.to_state is WorkItemState.ACCEPTANCE_READY
    assert transition.review_ref == "review-1"


def test_evidence_boundary_rejects_non_sha256_artifact() -> None:
    with pytest.raises(ValidationError):
        EvidenceRecord(
            evidence_id="evidence-1",
            work_item_id="work-1",
            observer_ref="reviewer-1",
            source_class="directly_verified",
            baseline_ref="baseline-1",
            artifact_sha256="not-a-digest",
            summary="verified",
        )
