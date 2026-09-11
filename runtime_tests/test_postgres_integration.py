from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from runtime.domain import DomainAuthority
from runtime.errors import AcceptanceGuardFailed, AuthorizationDenied, LeaseRejected
from runtime.models import (
    AuthenticatedContext,
    CommandEnvelope,
    EvidenceRecord,
    LeaseRequest,
    TransitionRequest,
    WorkItemState,
)

DSN = os.getenv("ACS_P1_DSN", "")


@pytest.fixture
def postgres_dsn():
    """Keep the original integration checks independent of other Grant fixtures."""
    if not DSN:
        pytest.skip("NOT_RUN: ACS_P1_DSN is not set")
    name = f"legacy_integration_{uuid.uuid4().hex}"
    with psycopg.connect(DSN, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
    try:
        yield make_conninfo(DSN, options=f"-csearch_path={name} -cstatement_timeout=15000 -clock_timeout=10000")
    finally:
        with psycopg.connect(DSN, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))


def make_command(authority: DomainAuthority, command_type: str, target_id: str,
                 idempotency_key: str, expected_revision: int = 0) -> CommandEnvelope:
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
        target_kind="lease" if command_type.startswith("lease.") else "work_item",
        target_id=target_id,
        expected_revision=expected_revision,
        issued_at=now,
        deadline=now + timedelta(minutes=5),
    )


def journal_counts(dsn: str) -> tuple[int, ...]:
    with psycopg.connect(dsn) as connection:
        return tuple(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                     for table in ("command_dedup", "domain_events", "operations", "outbox"))


def test_real_postgres_retry_revocation_and_incomplete_evidence_guards(postgres_dsn: str) -> None:
    authority = DomainAuthority(postgres_dsn)
    authority.initialize()
    authority.bootstrap_local_grant()
    work_item_id = f"work-{uuid.uuid4()}"
    create = make_command(authority, "work_item.create", work_item_id, f"create-{work_item_id}")
    first = authority.create_work_item(create, "local-scope", "local-slot", "baseline-real")
    retry = authority.create_work_item(create, "local-scope", "local-slot", "baseline-real")
    assert retry.duplicate is True
    assert retry.operation_id == first.operation_id
    assert journal_counts(postgres_dsn) == (1, 1, 1, 1)

    digest_only_claim = EvidenceRecord(
        evidence_id=f"evidence-{work_item_id}", work_item_id=work_item_id,
        observer_ref=authority.context.principal_ref, source_class="directly_verified",
        baseline_ref="baseline-real", artifact_sha256="a" * 64,
        summary="PostgreSQL test summary without a registered execution receipt",
    )
    with pytest.raises(AcceptanceGuardFailed) as rejected_claim:
        authority.record_evidence(
            make_command(authority, "evidence.record", work_item_id, f"claimed-verified-{work_item_id}"),
            digest_only_claim,
        )
    assert rejected_claim.value.reason == "untrusted summary must remain an incomplete candidate"
    assert journal_counts(postgres_dsn) == (1, 1, 1, 1)

    evidence = digest_only_claim.model_copy(update={"source_class": "endpoint_reported"})
    authority.record_evidence(
        make_command(authority, "evidence.record", work_item_id, f"evidence-command-{work_item_id}"), evidence)
    with pytest.raises(AuthorizationDenied) as self_review:
        authority.record_review(
            make_command(authority, "review.record", work_item_id, f"review-command-{work_item_id}"),
            f"review-{work_item_id}", work_item_id, "pass", evidence.evidence_id, "baseline-real")
    assert self_review.value.principal_ref == authority.context.principal_ref
    assert journal_counts(postgres_dsn) == (2, 2, 2, 2)

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("UPDATE grants SET revoked_at=now() WHERE grant_ref=%s", (authority.context.grant_ref,))
    with pytest.raises(AuthorizationDenied) as revoked_retry:
        authority.create_work_item(create, "local-scope", "local-slot", "baseline-real")
    assert revoked_retry.value.grant_ref == authority.context.grant_ref
    with pytest.raises(AuthorizationDenied) as revoked_transition:
        authority.transition_work_item(
            make_command(authority, "work_item.transition", work_item_id, f"blocked-{work_item_id}"),
            TransitionRequest(to_state=WorkItemState.ACCEPTANCE_READY, evidence_refs=(evidence.evidence_id,),
                              review_ref=f"review-{work_item_id}"))
    assert revoked_transition.value.grant_ref == authority.context.grant_ref
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("UPDATE grants SET revoked_at=NULL WHERE grant_ref=%s", (authority.context.grant_ref,))

    with pytest.raises(AcceptanceGuardFailed) as incomplete:
        authority.transition_work_item(
            make_command(authority, "work_item.transition", work_item_id, f"ready-{work_item_id}"),
            TransitionRequest(to_state=WorkItemState.ACCEPTANCE_READY, evidence_refs=(evidence.evidence_id,),
                              review_ref=f"review-{work_item_id}"))
    assert incomplete.value.reason == "complete evidence bundle set is missing"

    forged = evidence.model_copy(update={"observer_ref": "different-observer"})
    with pytest.raises(AcceptanceGuardFailed) as forged_observer:
        authority.record_evidence(
            make_command(authority, "evidence.record", work_item_id, f"forged-evidence-{work_item_id}"), forged)
    assert forged_observer.value.reason == "untrusted summary must remain an incomplete candidate"
    assert journal_counts(postgres_dsn) == (2, 2, 2, 2)
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT state,revision FROM work_items WHERE work_item_id=%s",
                                  (work_item_id,)).fetchone() == ("candidate", 0)
        assert connection.execute("SELECT count(*) FROM accepted_state_revisions").fetchone() == (0,)


def test_real_postgres_assigned_review_cannot_promote_incomplete_summary(postgres_dsn: str) -> None:
    engineer = DomainAuthority(postgres_dsn)
    engineer.initialize()
    engineer.bootstrap_local_grant()
    work_item_id = f"assigned-review-{uuid.uuid4()}"
    baseline = "baseline-assigned-review"
    engineer.create_work_item(
        make_command(engineer, "work_item.create", work_item_id, f"create-{work_item_id}"),
        "local-scope", "local-slot", baseline)
    reviewer_context = AuthenticatedContext(
        "local-tenant", "acs-p1-authority", "local-1",
        f"agent:reviewer-{work_item_id}", f"grant:reviewer-{work_item_id}")
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,"
            "scope_id,permissions,expires_at) VALUES (%s,%s,%s,%s,%s,'local-scope',%s,now()+interval '1 day')",
            (reviewer_context.grant_ref, reviewer_context.tenant_id, reviewer_context.principal_ref,
             reviewer_context.authority_id, reviewer_context.authority_incarnation,
             '["review.record","work_item.read"]'))
    engineer.assign_reviewer(
        make_command(engineer, "review.assign", work_item_id, f"assign-{work_item_id}"),
        work_item_id, reviewer_context.principal_ref, reviewer_context.grant_ref)
    evidence = EvidenceRecord(
        evidence_id=f"evidence-{work_item_id}", work_item_id=work_item_id,
        observer_ref=engineer.context.principal_ref, source_class="endpoint_reported",
        baseline_ref=baseline, artifact_sha256="b" * 64, summary="incomplete assigned-review summary")
    engineer.record_evidence(
        make_command(engineer, "evidence.record", work_item_id, f"evidence-{work_item_id}"), evidence)
    reviewer = DomainAuthority(postgres_dsn, reviewer_context)
    review = reviewer.record_review(
        make_command(reviewer, "review.record", work_item_id, f"review-{work_item_id}"),
        f"review-{work_item_id}", work_item_id, "pass", evidence.evidence_id, baseline)
    assert review.state == "review"
    with pytest.raises(AcceptanceGuardFailed) as incomplete:
        engineer.transition_work_item(
            make_command(engineer, "work_item.transition", work_item_id, f"ready-{work_item_id}"),
            TransitionRequest(to_state=WorkItemState.ACCEPTANCE_READY, evidence_refs=(evidence.evidence_id,),
                              review_ref=f"review-{work_item_id}"))
    assert incomplete.value.reason == "complete evidence bundle set is missing"
    assert journal_counts(postgres_dsn) == (4, 4, 4, 4)
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT state,revision FROM work_items WHERE work_item_id=%s",
                                  (work_item_id,)).fetchone() == ("candidate", 0)
        assert connection.execute("SELECT count(*) FROM accepted_state_revisions").fetchone() == (0,)


def test_real_postgres_rejects_forged_observer_unregistered_lease_owner_and_wrong_scope(postgres_dsn: str) -> None:
    authority = DomainAuthority(postgres_dsn)
    authority.initialize()
    authority.bootstrap_local_grant()
    work_item_id = f"lease-owner-{uuid.uuid4()}"
    authority.create_work_item(
        make_command(authority, "work_item.create", work_item_id, f"create-{work_item_id}"),
        "local-scope", "local-slot", "baseline-effect")
    evidence = EvidenceRecord(
        evidence_id=f"evidence-{work_item_id}", work_item_id=work_item_id,
        observer_ref=authority.context.principal_ref, source_class="endpoint_reported",
        baseline_ref="baseline-effect", artifact_sha256="c" * 64, summary="incomplete observer summary")
    authority.record_evidence(
        make_command(authority, "evidence.record", work_item_id, f"evidence-{work_item_id}"), evidence)
    with pytest.raises(AcceptanceGuardFailed) as forged:
        authority.record_evidence(
            make_command(authority, "evidence.record", work_item_id, f"forged-{work_item_id}"),
            evidence.model_copy(update={"observer_ref": "forged-observer"}))
    assert forged.value.reason == "untrusted summary must remain an incomplete candidate"

    resource_id = f"resource-{work_item_id}"
    lease_command = make_command(authority, "lease.acquire", resource_id, f"lease-{work_item_id}")
    lease_request = LeaseRequest(
        resource_id=resource_id, owner_attempt_id=f"attempt-{work_item_id}",
        owner_runtime_id=f"runtime-{work_item_id}", grant_ref=authority.context.grant_ref,
        authority_incarnation=authority.context.authority_incarnation,
        scope_id="local-scope", work_item_id=work_item_id, ttl_seconds=30)
    with pytest.raises(LeaseRejected) as unregistered:
        authority.leases.acquire_lease(lease_command, lease_request)
    assert unregistered.value.reason == "owner registration is incomplete, inactive or mismatched"
    with pytest.raises(LeaseRejected) as wrong_envelope:
        authority.leases.acquire_lease(lease_command.model_copy(update={"target_kind": "work_item"}), lease_request)
    assert wrong_envelope.value.reason == "command type or target does not match lease operation"

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("INSERT INTO scopes(scope_id,tenant_id,policy,status) VALUES ('other-scope',%s,'{}','active')",
                           (authority.context.tenant_id,))
    with pytest.raises(AuthorizationDenied) as wrong_scope:
        authority.leases.acquire_lease(
            make_command(authority, "lease.acquire", resource_id, f"wrong-scope-{work_item_id}"),
            lease_request.model_copy(update={"scope_id": "other-scope"}))
    assert wrong_scope.value.grant_ref == authority.context.grant_ref

    other_authority = DomainAuthority(
        postgres_dsn, AuthenticatedContext(authority.context.tenant_id, "other-authority", "other-incarnation",
                                          authority.context.principal_ref, "other-grant"))
    with pytest.raises(AuthorizationDenied) as wrong_authority:
        other_authority.leases.acquire_lease(
            make_command(other_authority, "lease.acquire", resource_id, f"wrong-authority-{work_item_id}"),
            lease_request.model_copy(update={"grant_ref": "other-grant", "authority_incarnation": "other-incarnation"}))
    assert wrong_authority.value.grant_ref == "other-grant"
    assert journal_counts(postgres_dsn) == (2, 2, 2, 2)
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM leases").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM attempts").fetchone() == (0,)
