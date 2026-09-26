"""Real PostgreSQL ledger tests, each using its own disposable random schema."""
from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg import sql
from psycopg.conninfo import make_conninfo

from runtime.domain import DomainAuthority
from runtime.errors import (
    AuthorizationDenied,
    IdempotencyConflict,
    RevisionConflict,
    SchemaAdoptionError,
)
from runtime.migrations import FOUNDATION_HASH_VERSION, HARDENED_HASH_VERSION, legacy_command_hash
from runtime.models import CommandEnvelope, CommandResult, TransitionRequest, WorkItemState


@pytest.fixture
def isolated_dsn():
    base = os.environ.get("ACS_P1_DSN")
    if not base:
        pytest.skip("ACS_P1_DSN is not configured; real PostgreSQL not measured")
    schema = "ledger_test_" + uuid.uuid4().hex
    with psycopg.connect(base, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        yield make_conninfo(base, options=f"-csearch_path={schema} -cstatement_timeout=15000 -clock_timeout=10000")
    finally:
        with psycopg.connect(base, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def authority(isolated_dsn):
    domain = DomainAuthority(isolated_dsn)
    domain.initialize()
    domain.bootstrap_local_grant()
    return domain


def command(domain, *, target="work-1", kind="work_item.create", revision=0, **overrides):
    now = datetime.now(UTC)
    value = {"command_id": "cmd-" + uuid.uuid4().hex, "idempotency_key": "key-" + uuid.uuid4().hex,
                 "correlation_id": "ledger-test", "command_type": kind, "tenant_id": domain.tenant_id,
                 "authority_id": domain.context.authority_id,
                 "authority_incarnation": domain.context.authority_incarnation,
                 "principal_ref": domain.context.principal_ref, "grant_ref": domain.context.grant_ref,
                 "target_kind": "work_item", "target_id": target, "expected_revision": revision,
                 "issued_at": now - timedelta(seconds=1), "deadline": now + timedelta(minutes=5)}
    value.update(overrides)
    return CommandEnvelope(**value)


def create(domain, cmd):
    return domain.create_work_item(cmd, "local-scope", "local-slot", "baseline-1")


CREATE_EXTRA = {"scope_id": "local-scope", "agent_slot_id": "local-slot", "source_baseline": "baseline-1"}


def query(domain, statement, params=()):
    with domain._connect() as connection:
        cursor = connection.execute(statement, params)
        return cursor.fetchall() if cursor.description else []


def counts(domain):
    return tuple(query(domain, f"SELECT count(*) FROM {table}")[0][0]
                 for table in ("command_dedup", "domain_events", "outbox", "operations"))


def add_reviewer(domain):
    reviewer = DomainAuthority(domain._dsn, replace(domain.context, principal_ref="agent:reviewer", grant_ref="grant:reviewer"))
    reviewer.bootstrap_local_grant()
    return reviewer


def seed_evidence(domain):
    query(domain, "INSERT INTO evidence(evidence_id,tenant_id,work_item_id,observer_ref,source_class,"
          "baseline_ref,artifact_sha256,summary,producer_ref,candidate_ref) "
          "VALUES ('e-1',%s,'work-1','agent:engineer','directly_verified','baseline-1',%s,'fixture',"
          "'agent:engineer','candidate-1')", (domain.tenant_id, "a" * 64))


def test_current_hash_and_atomic_exact_replay(authority):
    cmd = command(authority)
    result = create(authority, cmd)
    replay = create(authority, cmd)
    assert replay.duplicate and replay.operation_id == result.operation_id
    assert counts(authority) == (1, 1, 1, 1)
    digest = cmd.canonical_hash(CREATE_EXTRA)
    assert query(authority, "SELECT payload_hash,canonical_hash,hash_version,migration_state,replay_policy FROM command_dedup") == [
        (digest, digest, "v2", "current", "replay_safe")]
    assert query(authority, "SELECT canonical_hash FROM domain_events") == [(digest,)]


@pytest.mark.parametrize("field,value", [("causation_id", "different-cause"), ("correlation_id", "different-correlation"),
                                        ("payload", {"meaning": "changed"})])
def test_changed_canonical_input_conflicts_without_side_effects(authority, field, value):
    cmd = command(authority)
    create(authority, cmd)
    with pytest.raises(IdempotencyConflict) as caught:
        create(authority, cmd.model_copy(update={field: value}))
    assert caught.value.idempotency_key == cmd.idempotency_key
    assert counts(authority) == (1, 1, 1, 1)


def test_changed_create_semantic_parameter_conflicts(authority):
    cmd = command(authority)
    create(authority, cmd)
    with pytest.raises(IdempotencyConflict):
        authority.create_work_item(cmd, "local-scope", "local-slot", "changed-baseline")
    assert counts(authority) == (1, 1, 1, 1)


def test_replay_precedes_stale_revision_and_slot_preconditions(authority):
    cmd = command(authority)
    create(authority, cmd)
    query(authority, "UPDATE work_items SET revision=7")
    query(authority, "UPDATE agent_slots SET status='revoked'")
    assert create(authority, cmd).duplicate
    with pytest.raises(RevisionConflict) as caught:
        create(authority, command(authority, target="work-2", revision=7))
    assert (caught.value.expected, caught.value.actual) == (7, 0)
    assert counts(authority) == (1, 1, 1, 1)


@pytest.mark.parametrize("change", ["grant_revoked", "grant_expired", "scope_revoked", "authority_revoked", "deadline"])
def test_exact_replay_still_checks_current_authority(authority, change):
    cmd = command(authority)
    create(authority, cmd)
    if change == "grant_revoked":
        query(authority, "UPDATE grants SET revoked_at=now()")
    elif change == "grant_expired":
        query(authority, "UPDATE grants SET expires_at=now()-interval '1 second'")
    elif change == "scope_revoked":
        query(authority, "UPDATE scopes SET status='revoked'")
    elif change == "authority_revoked":
        query(authority, "UPDATE authority_instances SET status='revoked'")
    else:
        cmd = cmd.model_copy(update={"deadline": datetime.now(UTC)-timedelta(seconds=1)})
    with pytest.raises(AuthorizationDenied) as caught:
        create(authority, cmd)
    assert caught.value.principal_ref == cmd.principal_ref
    assert counts(authority) == (1, 1, 1, 1)


def test_command_body_cannot_impersonate_authenticated_context(authority):
    reviewer = add_reviewer(authority)
    with pytest.raises(AuthorizationDenied):
        create(authority, command(reviewer))
    assert counts(authority) == (0, 0, 0, 0)


def test_initialize_never_creates_context_incarnation(authority):
    other = DomainAuthority(authority._dsn, replace(authority.context, authority_incarnation="invented"))
    other.initialize()
    other.bootstrap_local_grant()
    assert query(authority, "SELECT authority_id,authority_incarnation,status FROM authority_instances") == [
        ("acs-p1-authority", "local-1", "active")]
    with pytest.raises(AuthorizationDenied):
        create(other, command(other))
    assert counts(authority) == (0, 0, 0, 0)


def test_explicit_deployment_authority_binding(isolated_dsn):
    initial = DomainAuthority(isolated_dsn)
    context = replace(initial.context, authority_id="deployment-a", authority_incarnation="generation-4")
    configured = DomainAuthority(isolated_dsn, context, authority_binding=("deployment-a", "generation-4"))
    configured.initialize()
    configured.bootstrap_local_grant()
    assert not create(configured, command(configured)).duplicate
    assert query(configured, "SELECT authority_id,authority_incarnation FROM authority_instances") == [
        ("deployment-a", "generation-4")]


def test_assignment_replay_precedes_recipient_and_revision_checks(authority):
    create(authority, command(authority))
    reviewer = add_reviewer(authority)
    cmd = command(authority, kind="review.assign")
    result = authority.assign_reviewer(cmd, "work-1", reviewer.context.principal_ref, reviewer.context.grant_ref)
    query(authority, "UPDATE work_items SET revision=3")
    query(authority, "UPDATE grants SET revoked_at=now() WHERE grant_ref=%s", (reviewer.context.grant_ref,))
    replay = authority.assign_reviewer(cmd, "work-1", reviewer.context.principal_ref, reviewer.context.grant_ref)
    assert replay.duplicate and replay.operation_id == result.operation_id
    with pytest.raises(IdempotencyConflict):
        authority.assign_reviewer(cmd, "work-1", "agent:changed", reviewer.context.grant_ref)
    with pytest.raises(RevisionConflict) as caught:
        authority.assign_reviewer(command(authority, kind="review.assign"), "work-1",
                                  reviewer.context.principal_ref, reviewer.context.grant_ref)
    assert caught.value.actual == 3
    assert counts(authority) == (2, 2, 2, 2)


def test_review_replay_precedes_business_checks_but_new_review_checks_revision(authority):
    create(authority, command(authority))
    reviewer = add_reviewer(authority)
    authority.assign_reviewer(command(authority, kind="review.assign"), "work-1",
                              reviewer.context.principal_ref, reviewer.context.grant_ref)
    seed_evidence(authority)
    cmd = command(reviewer, kind="review.record")
    result = reviewer.record_review(cmd, "review-1", "work-1", "pass", "e-1", "baseline-1")
    query(authority, "UPDATE work_items SET revision=5")
    query(authority, "UPDATE reviewer_assignments SET status='revoked'")
    query(authority, "DELETE FROM evidence")
    replay = reviewer.record_review(cmd, "review-1", "work-1", "pass", "e-1", "baseline-1")
    assert replay.duplicate and replay.operation_id == result.operation_id
    with pytest.raises(IdempotencyConflict):
        reviewer.record_review(cmd, "review-1", "work-1", "fail", "e-1", "baseline-1")
    with pytest.raises(RevisionConflict) as caught:
        reviewer.record_review(command(reviewer, kind="review.record"), "review-2", "work-1", "pass", "e-1", "baseline-1")
    assert (caught.value.expected, caught.value.actual) == (0, 5)
    assert counts(authority) == (3, 3, 3, 3)
    digest = cmd.canonical_hash({"review_id": "review-1", "work_item_id": "work-1", "verdict": "pass",
                                    "evidence_ref": "e-1", "baseline_ref": "baseline-1"})
    assert query(authority, "SELECT canonical_hash FROM command_dedup WHERE command_id=%s", (cmd.command_id,)) == [(digest,)]
    assert query(authority, "SELECT canonical_hash FROM domain_events WHERE command_id=%s", (cmd.command_id,)) == [(digest,)]


def test_new_transition_stale_revision_rolls_back_ledger(authority):
    create(authority, command(authority))
    cmd = command(authority, kind="work_item.transition", revision=4)
    with pytest.raises(RevisionConflict) as caught:
        authority.transition_work_item(cmd, TransitionRequest(to_state=WorkItemState.ACCEPTANCE_READY))
    assert (caught.value.expected, caught.value.actual) == (4, 0)
    assert counts(authority) == (1, 1, 1, 1)


def install_old_ledger(dsn, cmd, version, *, contradictory_id=None):
    result = CommandResult(command_id=cmd.command_id, operation_id="historical-op", target_id=cmd.target_id,
                           revision=0, state="candidate")
    digest = legacy_command_hash(cmd, CREATE_EXTRA, hash_version=version)
    with psycopg.connect(dsn) as connection:
        connection.execute("CREATE TABLE runtime_schema_metadata(schema_name TEXT PRIMARY KEY, schema_version TEXT NOT NULL,"
                           "schema_checksum TEXT NOT NULL, adopted_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        connection.execute("INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) VALUES (%s,'1.3',%s)",
                           (DomainAuthority.SCHEMA_NAME, "0e3600dc7ed3b7fac727670f5c8fec0b00c6e100063e63a3f149661631dccea4"))
        # The pre-v2 journal intentionally lacks every migration/canonical column.
        connection.execute("CREATE TABLE command_dedup(tenant_id TEXT NOT NULL,idempotency_key TEXT NOT NULL,command_id TEXT,"
                           "payload_hash TEXT NOT NULL,result_json JSONB NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
                           "PRIMARY KEY(tenant_id,idempotency_key))")
        connection.execute("INSERT INTO command_dedup(tenant_id,idempotency_key,command_id,payload_hash,result_json) VALUES (%s,%s,%s,%s,%s)",
                           (cmd.tenant_id, cmd.idempotency_key, contradictory_id or (cmd.command_id if version == HARDENED_HASH_VERSION else None),
                            digest, result.model_dump_json()))
    return result, digest


@pytest.mark.parametrize("version", [FOUNDATION_HASH_VERSION, HARDENED_HASH_VERSION])
def test_old_schema_adoption_and_verified_replay(isolated_dsn, version):
    domain = DomainAuthority(isolated_dsn)
    cmd = command(domain, hash_version="v1")
    expected, digest = install_old_ledger(isolated_dsn, cmd, version)
    domain.initialize()
    domain.bootstrap_local_grant()
    query(domain, "INSERT INTO domain_events(tenant_id,work_item_id,to_state,initiated_by,lineage_mode,command_id,resulting_revision) "
          "VALUES (%s,%s,'candidate',%s,'external_command',%s,0)",
          (cmd.tenant_id, cmd.target_id, cmd.principal_ref, cmd.command_id))
    before = query(domain, "SELECT legacy_record FROM command_dedup")[0][0]
    assert before["payload_hash"] == digest
    assert before["result_json"]["command_id"] == cmd.command_id
    assert query(domain, "SELECT schema_version FROM runtime_schema_metadata") == [("1.9",)]
    result = create(domain, cmd)
    assert result.duplicate and result.operation_id == expected.operation_id
    assert counts(domain) == (1, 1, 0, 0)
    assert query(domain, "SELECT migration_state,replay_policy,legacy_record,payload_hash FROM command_dedup") == [
        ("migrated", "verify_legacy_hash", before, digest)]
    domain.initialize()
    assert query(domain, "SELECT legacy_record FROM command_dedup") == [(before,)]


@pytest.mark.parametrize("provenance", ["missing", "wrong", "ambiguous"])
def test_foundation_replay_requires_trusted_historical_principal(isolated_dsn, provenance):
    domain = DomainAuthority(isolated_dsn)
    cmd = command(domain, hash_version="v1")
    install_old_ledger(isolated_dsn, cmd, FOUNDATION_HASH_VERSION)
    domain.initialize()
    domain.bootstrap_local_grant()
    for principal in ([] if provenance == "missing" else ["agent:someone-else"] if provenance == "wrong"
                      else [cmd.principal_ref, "agent:someone-else"]):
        query(domain, "INSERT INTO domain_events(tenant_id,work_item_id,to_state,initiated_by,lineage_mode,command_id,resulting_revision) "
              "VALUES (%s,%s,'candidate',%s,'external_command',%s,0)",
              (cmd.tenant_id, cmd.target_id, principal, cmd.command_id))
    before = counts(domain)
    with pytest.raises(IdempotencyConflict):
        create(domain, cmd)
    assert counts(domain) == before


def test_quarantine_keeps_both_contradictory_historical_ids_occupied(isolated_dsn):
    domain = DomainAuthority(isolated_dsn)
    cmd = command(domain, command_id="history-result-id", hash_version="v1")
    install_old_ledger(isolated_dsn, cmd, HARDENED_HASH_VERSION, contradictory_id="history-column-id")
    domain.initialize()
    domain.bootstrap_local_grant()
    row = query(domain, "SELECT command_id,migration_state,legacy_command_id,legacy_record FROM command_dedup")[0]
    assert row[:3] == (None, "quarantined", "history-column-id")
    assert row[3]["result_json"]["command_id"] == "history-result-id"
    for reserved in ("history-result-id", "history-column-id"):
        with pytest.raises(IdempotencyConflict):
            create(domain, command(domain, command_id=reserved))
    assert counts(domain) == (1, 0, 0, 0)


@pytest.mark.parametrize("claim", ["legacy_command_id", "snapshot_column", "snapshot_result"])
def test_each_retained_quarantine_claim_blocks_fresh_key(authority, claim):
    legacy = {"command_id": "unused-column", "result_json": {"command_id": "unused-result"}}
    retained = "unused-retained"
    if claim == "legacy_command_id":
        retained = "occupied"
    elif claim == "snapshot_column":
        legacy["command_id"] = "occupied"
    else:
        legacy["result_json"]["command_id"] = "occupied"
    query(authority, "INSERT INTO command_dedup(tenant_id,idempotency_key,payload_hash,migration_state,replay_policy,"
          "legacy_command_id,legacy_record,result_json) VALUES (%s,'legacy-key',%s,'quarantined','quarantine',%s,%s,'{}')",
          (authority.tenant_id, "a"*64, retained, json.dumps(legacy)))
    with pytest.raises(IdempotencyConflict):
        create(authority, command(authority, command_id="occupied"))
    assert counts(authority) == (1, 0, 0, 0)


def test_same_command_id_with_different_keys_is_transactionally_serialized(authority):
    barrier = Barrier(2)
    commands = [command(authority, command_id="shared-command", target=f"target-{i}") for i in range(2)]
    def submit(cmd):
        barrier.wait(timeout=5)
        try:
            return create(authority, cmd)
        except IdempotencyConflict as error:
            return error
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, commands))
    assert sum(isinstance(result, CommandResult) for result in results) == 1
    assert sum(isinstance(result, IdempotencyConflict) for result in results) == 1
    assert counts(authority) == (1, 1, 1, 1)
    assert query(authority, "SELECT count(*) FROM work_items") == [(1,)]


def test_current_row_collision_does_not_hide_second_historical_claim(authority):
    cmd = command(authority)
    create(authority, cmd)
    query(authority, "INSERT INTO command_dedup(tenant_id,idempotency_key,payload_hash,migration_state,replay_policy,"
          "legacy_command_id,result_json) VALUES (%s,'conflicting-retained-key',%s,'quarantined','quarantine',%s,'{}')",
          (authority.tenant_id, "a" * 64, cmd.command_id))
    with pytest.raises(IdempotencyConflict):
        create(authority, cmd)
    assert counts(authority) == (2, 1, 1, 1)


def test_ambiguous_active_authority_is_denied_even_with_matching_grant(authority):
    # Simulate a pre-hardening deployment whose active-incarnation index is absent.
    query(authority, "DROP INDEX IF EXISTS authority_instances_one_active")
    query(authority, "INSERT INTO authority_instances(authority_id,authority_incarnation,status) "
          "VALUES ('acs-p1-authority','competing-incarnation','active')")
    with pytest.raises(AuthorizationDenied):
        create(authority, command(authority))
    assert counts(authority) == (0, 0, 0, 0)


def test_unknown_old_schema_checksum_is_not_adopted(authority):
    query(authority, "UPDATE runtime_schema_metadata SET schema_version='1.3',schema_checksum=%s", ("f" * 64,))
    with pytest.raises(SchemaAdoptionError) as caught:
        authority.initialize()
    assert caught.value.actual_checksum == "f" * 64
    assert query(authority, "SELECT schema_version,schema_checksum FROM runtime_schema_metadata") == [("1.3", "f" * 64)]
    assert counts(authority) == (0, 0, 0, 0)


def test_foundation_hash_verification_cannot_be_replaced_by_identity_only(isolated_dsn):
    domain = DomainAuthority(isolated_dsn)
    cmd = command(domain, hash_version="v1")
    install_old_ledger(isolated_dsn, cmd, FOUNDATION_HASH_VERSION)
    domain.initialize()
    domain.bootstrap_local_grant()
    query(domain, "INSERT INTO domain_events(tenant_id,work_item_id,to_state,initiated_by,lineage_mode,command_id,resulting_revision) "
          "VALUES (%s,%s,'candidate',%s,'external_command',%s,0)",
          (cmd.tenant_id, cmd.target_id, cmd.principal_ref, cmd.command_id))
    with pytest.raises(IdempotencyConflict):
        domain.create_work_item(cmd, "local-scope", "local-slot", "different-baseline")
    assert counts(domain) == (1, 1, 0, 0)


def test_hardened_legacy_hash_binds_principal_without_event_provenance(isolated_dsn):
    domain = DomainAuthority(isolated_dsn)
    original = command(domain, hash_version="v1")
    install_old_ledger(isolated_dsn, original, HARDENED_HASH_VERSION)
    domain.initialize()
    domain.bootstrap_local_grant()
    assert create(domain, original).duplicate
    reviewer = add_reviewer(domain)
    spoof = original.model_copy(update={"principal_ref": reviewer.context.principal_ref, "grant_ref": reviewer.context.grant_ref})
    with pytest.raises(IdempotencyConflict):
        create(reviewer, spoof)
    assert counts(domain) == (1, 0, 0, 0)


def test_legacy_replay_still_rejects_revoked_grant(isolated_dsn):
    domain = DomainAuthority(isolated_dsn)
    cmd = command(domain, hash_version="v1")
    install_old_ledger(isolated_dsn, cmd, HARDENED_HASH_VERSION)
    domain.initialize()
    domain.bootstrap_local_grant()
    query(domain, "UPDATE grants SET revoked_at=now()")
    with pytest.raises(AuthorizationDenied):
        create(domain, cmd)
    assert counts(domain) == (1, 0, 0, 0)


def test_new_v1_command_cannot_create_mislabeled_v2_journal_row(authority):
    with pytest.raises(IdempotencyConflict):
        create(authority, command(authority, hash_version="v1"))
    assert counts(authority) == (0, 0, 0, 0)


def test_acceptance_replay_requires_current_finalize_permission(authority):
    create(authority, command(authority))
    cmd = command(authority, kind="work_item.transition")
    transition = TransitionRequest(to_state=WorkItemState.ACCEPTED)
    result = CommandResult(command_id=cmd.command_id, operation_id="prior-acceptance", target_id=cmd.target_id,
                           revision=1, state="accepted")
    # Seed a previously committed acceptance result to isolate the replay path.
    with authority._connect() as connection, connection.cursor() as cursor:
        authority._dedup(cursor, cmd, result, {"transition": transition.model_dump(mode="json")})
    query(authority, "UPDATE grants SET permissions='[\"work_item.transition\"]'::jsonb")
    with pytest.raises(AuthorizationDenied):
        authority.transition_work_item(cmd, transition)
    assert counts(authority) == (2, 1, 1, 1)

@pytest.mark.parametrize("method", ("create", "transition", "review", "assignment"))
@pytest.mark.parametrize("invalid", ({"command_type": "wrong.method"}, {"target_kind": "effect"}))
def test_method_semantics_reject_before_ledger_writes(authority, method, invalid):
    types = {"create": "work_item.create", "transition": "work_item.transition",
             "review": "review.record", "assignment": "review.assign"}
    cmd = command(authority, kind=types[method]).model_copy(update=invalid)
    before = counts(authority)
    with pytest.raises(ValueError, match="command_type/target_kind"):
        if method == "create":
            create(authority, cmd)
        elif method == "transition":
            authority.transition_work_item(cmd, TransitionRequest(
                to_state=WorkItemState.ACCEPTANCE_READY, evidence_refs=("missing",), review_ref="missing"))
        elif method == "review":
            authority.record_review(cmd, "review", "work-1", "pass", "e-1", "baseline-1")
        else:
            authority.assign_reviewer(cmd, "work-1", "reviewer", "grant-reviewer")
    assert counts(authority) == before
