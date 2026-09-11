"""PostgreSQL + real Linux CAS regressions for trusted evidence admission.

ACS_P1_DSN enables isolated-schema integration tests. These fixtures explicitly
seed Node admission bindings; they are not evidence of actual Node execution.
ACS_DOMAIN_EVIDENCE_FILE optionally selects the independent candidate module.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from runtime.artifacts import LocalArtifactStore
from runtime.domain import DomainAuthority as DefaultAuthority
from runtime.errors import (
    AcceptanceGuardFailed,
    AuthorizationDenied,
    IdempotencyConflict,
    RevisionConflict,
)
from runtime.models import (
    AuthenticatedContext,
    CommandEnvelope,
    EffectReadback,
    EvidenceBundle,
    EvidenceRecord,
    ExecutionReceipt,
    TransitionRequest,
    WorkItemState,
)


def authority_class():
    source = os.environ.get("ACS_DOMAIN_EVIDENCE_FILE")
    if not source:
        return DefaultAuthority
    spec = importlib.util.spec_from_file_location("evidence_candidate_domain", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DomainAuthority


def command(domain, kind, revision=0):
    now = datetime.now(UTC)
    identity = uuid.uuid4().hex
    return CommandEnvelope(
        command_id=f"cmd-{identity}", command_type=kind, idempotency_key=f"idem-{identity}",
        correlation_id="trusted-fixture", tenant_id=domain.tenant_id,
        authority_id=domain.authority_id, authority_incarnation=domain.context.authority_incarnation,
        principal_ref=domain.context.principal_ref, grant_ref=domain.context.grant_ref,
        target_kind="work_item", target_id="work", expected_revision=revision,
        issued_at=now, deadline=now + timedelta(minutes=10),
    )


def counts(fixture):
    tables = ("execution_receipts", "evidence", "evidence_bundles", "command_dedup",
              "domain_events", "operations", "outbox", "accepted_state_revisions")
    with psycopg.connect(fixture.dsn) as conn:
        return {table: conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]
                for table in tables}


@pytest.fixture
def runtime(tmp_path):
    base = os.environ.get("ACS_P1_DSN")
    if not base:
        pytest.skip("ACS_P1_DSN is required for real PostgreSQL evidence tests")
    if not sys.platform.startswith("linux"):
        pytest.skip("real LocalArtifactStore verification requires Linux")
    schema = f"evidence_{uuid.uuid4().hex}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(base, options=f"-c search_path={schema}")
    store = LocalArtifactStore(tmp_path / "cas")
    cls = authority_class()
    try:
        # Load fresh schema directly so the standalone candidate can be tested
        # without copying the schema next to its source or invoking bootstrap.
        schema_source = Path(sys.modules[DefaultAuthority.__module__].__file__).with_name("schema.sql")
        with psycopg.connect(dsn) as conn:
            conn.execute(schema_source.read_text(encoding="utf-8"))
            conn.execute(Path(__file__).with_name("evidence-schema.sql").read_text(encoding="utf-8"))
            conn.execute("INSERT INTO authority_instances VALUES ('acs-p1-authority','local-1','active',now())")
            conn.execute("INSERT INTO scopes(scope_id,tenant_id,policy,status) VALUES ('local-scope','local-tenant','{}','active')")
            conn.execute("INSERT INTO agent_slots(agent_slot_id,tenant_id,scope_id,status) VALUES ('local-slot','local-tenant','local-scope','active')")
        def domain(name):
            return cls(dsn, context=AuthenticatedContext("local-tenant", "acs-p1-authority", "local-1",
                                                       f"agent:{name}", f"grant:{name}"), artifact_store=store)
        engineer, node, reviewer, finalizer = map(domain, ("engineer", "node", "reviewer", "finalizer"))
        engineer.bootstrap_local_grant()
        node.bootstrap_local_grant(("execution.record", "work_item.read"))
        reviewer.bootstrap_local_grant(("review.record", "work_item.read"))
        finalizer.bootstrap_local_grant(("work_item.transition", "acceptance.finalize", "review.assign", "work_item.read"))
        engineer.create_work_item(command(engineer, "work_item.create"), "local-scope", "local-slot", "baseline-1")
        output = store.put_bytes(b"candidate output", kind="output")
        candidate_ref = "source-candidate:fixture-commit:output"
        readback = store.put_bytes(b"independent artifact readback", kind="readback")
        now = datetime.now(UTC)
        receipt = ExecutionReceipt(
            receipt_id="receipt-1", work_item_id="work", attempt_id="attempt-1", runtime_id="runtime-1",
            provider="fixture-node", command_id="execution-command-1", operation_id="execution-operation-1",
            event_id="execution-event-1", source_baseline="baseline-1", candidate_ref=candidate_ref,
            source_commit="fixture-commit", source_tree="fixture-tree", test_commands=("pytest tests",),
            test_exit_codes=(0,), test_exit_code=0, os="linux", toolchain="python-test-fixture",
            artifact_refs=(output,), readback_refs=(readback,), source_sync="fixture-seeded",
            status="succeeded", observed_at=now,
        )
        with psycopg.connect(dsn) as conn:
            conn.execute(
                "INSERT INTO attempts(attempt_id,tenant_id,work_item_id,agent_slot_id,status,producer_ref,"
                "runtime_id,scope_id,grant_ref,authority_id,authority_incarnation,observer_ref,observer_grant_ref,"
                "execution_command_id,execution_operation_id,execution_event_id,provider,source_baseline,"
                "source_commit,source_tree,candidate_ref,execution_started_at) VALUES ("
                "'attempt-1','local-tenant','work','local-slot','running','agent:engineer','runtime-1',"
                "'local-scope','grant:engineer','acs-p1-authority','local-1','agent:node','grant:node',"
                "'execution-command-1','execution-operation-1','execution-event-1','fixture-node','baseline-1',"
                "'fixture-commit','fixture-tree',%s,%s)", (candidate_ref, now - timedelta(seconds=1)),
            )
        bundle = EvidenceBundle(
            evidence_id="evidence-1", work_item_id="work", source_baseline="baseline-1",
            candidate_ref=candidate_ref, producer_ref="agent:engineer", observer_ref="agent:node",
            source_class="directly_verified", evidence_state="complete", execution_receipt=receipt,
            artifact_refs=(output,), readback_refs=(readback,), command_id=receipt.command_id,
            operation_id=receipt.operation_id, event_id=receipt.event_id, observed_at=now,
        )
        evidence = EvidenceRecord(
            evidence_id="evidence-1", work_item_id="work", observer_ref="agent:node",
            source_class="directly_verified", baseline_ref="baseline-1", artifact_sha256=output.sha256,
            summary="Explicitly seeded trusted execution fixture", bundle_ref="evidence-1", candidate_ref=candidate_ref,
            execution_receipt_ref="receipt-1", evidence_state="complete", producer_ref="agent:engineer",
            attempt_id="attempt-1", test_exit_code=0, artifact_refs=(output,), readback_refs=(readback,),
        )
        yield SimpleNamespace(dsn=dsn, engineer=engineer, node=node, reviewer=reviewer,
                              finalizer=finalizer, store=store, receipt=receipt, evidence=evidence,
                              bundle=bundle, output=output, readback=readback)
    finally:
        store.close()
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def register(f):
    return f.node.record_execution_receipt(command(f.node, "execution.record"), f.receipt)


def review(f):
    f.engineer.record_evidence(command(f.engineer, "evidence.record"), f.evidence, f.bundle)
    f.finalizer.assign_reviewer(command(f.finalizer, "review.assign"), "work", "agent:reviewer", "grant:reviewer")
    f.reviewer.record_review(command(f.reviewer, "review.record"), "review-1", "work", "pass", "evidence-1", "baseline-1")


def transition(f, state, revision, *, effects=(), readbacks=()):
    return f.finalizer.transition_work_item(command(f.finalizer, "work_item.transition", revision),
        TransitionRequest(to_state=state, evidence_refs=("evidence-1",), review_ref="review-1",
                          effect_refs=effects, readback_refs=readbacks))


def test_trusted_execution_and_evidence_submission_have_distinct_lineage(runtime):
    f = runtime
    registration = register(f)
    evidence_command = command(f.engineer, "evidence.record")
    result = f.engineer.record_evidence(evidence_command, f.evidence, f.bundle)
    assert result.operation_id != registration.operation_id != f.receipt.operation_id
    assert f.engineer.record_evidence(evidence_command, f.evidence, f.bundle).duplicate
    with psycopg.connect(f.dsn) as conn:
        row = conn.execute("SELECT e.command_id,e.operation_id,e.event_id,x.receipt_json FROM evidence e JOIN execution_receipts x ON x.receipt_id=e.execution_receipt_ref").fetchone()
    assert row[:2] == (evidence_command.command_id, result.operation_id)
    assert row[2] and row[3]["operation_id"] == f.receipt.operation_id


def test_trusted_receipt_review_ready_accepted(runtime):
    f = runtime
    register(f)
    review(f)
    assert transition(f, WorkItemState.ACCEPTANCE_READY, 0).revision == 1
    assert transition(f, WorkItemState.ACCEPTED, 1).revision == 2
    assert f.finalizer.get_work_item("work")["state"] == "accepted"


def test_engineer_cannot_mint_trusted_receipt(runtime):
    f = runtime
    before = counts(f)
    with pytest.raises(AuthorizationDenied):
        f.engineer.record_execution_receipt(command(f.engineer, "execution.record"), f.receipt)
    assert counts(f) == before


@pytest.mark.parametrize("changed", ["runtime_id", "command_id", "operation_id", "event_id", "source_commit", "candidate_ref"])
def test_node_cannot_replace_registered_attempt_identity(runtime, changed):
    f = runtime
    before = counts(f)
    altered = f.receipt.model_copy(update={changed: "forged"})
    with pytest.raises(AcceptanceGuardFailed, match="receipt does not match trusted execution attempt"):
        f.node.record_execution_receipt(command(f.node, "execution.record"), altered)
    assert counts(f) == before


@pytest.mark.parametrize("case,reason", [
    ("receipt_absent", "trusted execution receipt is not registered"),
    ("attempt_absent", "trusted execution attempt binding is missing or unauthorized"),
    ("producer", "bundle producer/observer differs from trusted execution"),
    ("receipt_json", "receipt differs from registered execution receipt"),
    ("receipt_event", "receipt does not match trusted execution attempt"),
])
def test_forged_evidence_rolls_back_all_writes(runtime, case, reason):
    f = runtime
    if case != "receipt_absent":
        register(f)
    evidence, bundle = f.evidence, f.bundle
    if case == "attempt_absent":
        receipt = f.receipt.model_copy(update={"attempt_id": "unregistered"})
        bundle = bundle.model_copy(update={"execution_receipt": receipt})
        evidence = evidence.model_copy(update={"attempt_id": "unregistered"})
    elif case == "producer":
        bundle = bundle.model_copy(update={"producer_ref": "agent:other"})
        evidence = evidence.model_copy(update={"producer_ref": "agent:other"})
    elif case == "receipt_json":
        bundle = bundle.model_copy(update={"execution_receipt": f.receipt.model_copy(update={"usage": {"forged": True}})})
    elif case == "receipt_event":
        bundle = bundle.model_copy(update={"event_id": "forged", "execution_receipt": f.receipt.model_copy(update={"event_id": "forged"})})
    before = counts(f)
    with pytest.raises(AcceptanceGuardFailed, match=reason):
        f.engineer.record_evidence(command(f.engineer, "evidence.record"), evidence, bundle)
    assert counts(f) == before


@pytest.mark.parametrize("mutation,reason", [
    ("revoke", "independent assigned authorized review is missing"),
    ("assignment", "reviewer independence or evidence binding failed"),
    ("cas", "receipt artifact bytes are not verified"),
    ("policy", "readiness snapshot bindings changed"),
])
def test_ready_does_not_freeze_authorization_or_cas_verification(runtime, mutation, reason):
    f = runtime
    register(f)
    review(f)
    transition(f, WorkItemState.ACCEPTANCE_READY, 0)
    if mutation == "cas":
        target = f.store.root / f.output.path
        target.chmod(0o600)
        target.write_bytes(b"corrupted candidate bytes")
    else:
        with psycopg.connect(f.dsn) as conn:
            if mutation == "revoke":
                conn.execute("UPDATE grants SET revoked_at=now() WHERE grant_ref='grant:reviewer'")
            elif mutation == "assignment":
                conn.execute("UPDATE reviewer_assignments SET assignment_revision=assignment_revision+1")
            else:
                conn.execute("UPDATE scopes SET policy='{\"changed\":true}'")
    before = counts(f)
    with pytest.raises(AcceptanceGuardFailed, match=reason):
        transition(f, WorkItemState.ACCEPTED, 1)
    assert counts(f) == before
    assert f.finalizer.get_work_item("work")["state"] == "acceptance_ready"


def seed_effect(f, status="verified", *, candidate_ref=None):
    with psycopg.connect(f.dsn) as conn:
        conn.execute(
            "INSERT INTO effects(effect_id,tenant_id,work_item_id,resource_id,baseline_ref,lease_id,"
            "fencing_token,generation,status,readback_ref,grant_ref,candidate_ref,operation_id,"
            "expected_sha256,expected_size_bytes,intent_sha256) VALUES ('effect-1','local-tenant',"
            "'work','resource-1','baseline-1','lease-1','token-1',1,%s,'effect-readback-1','grant:engineer',%s,"
            "'fixture-effect-op',%s,%s,%s)",
            (status, candidate_ref if candidate_ref is not None else f.receipt.candidate_ref,
             f.output.sha256, f.output.size_bytes, hashlib.sha256(b"explicit-fixture-intent").hexdigest()))
        conn.execute(
            "INSERT INTO leases(lease_id,tenant_id,resource_id,owner_attempt_id,owner_runtime_id,"
            "authority_id,authority_incarnation,generation,fencing_token,grant_ref,scope_id,expires_at,status) "
            "VALUES ('lease-1','local-tenant','resource-1','attempt-1','runtime-1','acs-p1-authority',"
            "'local-1',1,'token-1','grant:engineer','local-scope',now()-interval '1 hour','released')")


def test_effect_universe_is_enumerated_and_uncertain_effects_rejected(runtime):
    f = runtime
    register(f)
    review(f)
    seed_effect(f, "uncertain")
    before = counts(f)
    with pytest.raises(AcceptanceGuardFailed, match="all protected effects must be included"):
        transition(f, WorkItemState.ACCEPTANCE_READY, 0)
    with pytest.raises(AcceptanceGuardFailed, match="every protected effect must be verified"):
        transition(f, WorkItemState.ACCEPTANCE_READY, 0, effects=("effect-1",), readbacks=("effect-readback-1",))
    assert counts(f) == before


def test_completed_effect_requires_live_callback_but_not_live_writer_lease(runtime):
    f = runtime
    register(f)
    review(f)
    seed_effect(f)
    before = counts(f)
    with pytest.raises(AcceptanceGuardFailed, match="live effect readback verifier is unavailable"):
        transition(f, WorkItemState.ACCEPTANCE_READY, 0, effects=("effect-1",), readbacks=("effect-readback-1",))
    assert counts(f) == before
    calls = []
    def explicit_fixture_verifier(cursor, context, effect):
        # Deliberately injected fixture: this is contract testing, not a live gateway measurement.
        calls.append((context.principal_ref, effect["effect_id"]))
        return fixture_effect_proof(f, effect)
    f.finalizer._effect_readback_verifier = explicit_fixture_verifier
    transition(f, WorkItemState.ACCEPTANCE_READY, 0, effects=("effect-1",), readbacks=("effect-readback-1",))
    transition(f, WorkItemState.ACCEPTED, 1, effects=("effect-1",), readbacks=("effect-readback-1",))
    assert len(calls) == 2


def test_successful_evidence_replay_precedes_revision_check_and_seals_bundle(runtime):
    f = runtime
    receipt_command = command(f.node, "execution.record")
    receipt_result = f.node.record_execution_receipt(receipt_command, f.receipt)
    evidence_command = command(f.engineer, "evidence.record")
    original = f.engineer.record_evidence(evidence_command, f.evidence, f.bundle)
    with psycopg.connect(f.dsn) as conn:
        conn.execute("UPDATE work_items SET revision=9 WHERE work_item_id='work'")
    before = counts(f)
    replay = f.engineer.record_evidence(evidence_command, f.evidence, f.bundle)
    assert replay.duplicate and replay.operation_id == original.operation_id
    receipt_replay = f.node.record_execution_receipt(receipt_command, f.receipt)
    assert receipt_replay.duplicate and receipt_replay.operation_id == receipt_result.operation_id
    with pytest.raises(IdempotencyConflict):
        f.engineer.record_evidence(evidence_command, f.evidence, f.bundle.model_copy(update={"expires_at": datetime.now(UTC) + timedelta(days=1)}))
    with pytest.raises(RevisionConflict):
        f.engineer.record_evidence(command(f.engineer, "evidence.record"), f.evidence, f.bundle)
    assert counts(f) == before


def test_summary_cannot_assert_direct_verification(runtime):
    f = runtime
    before = counts(f)
    with pytest.raises(AcceptanceGuardFailed, match="untrusted summary must remain an incomplete candidate"):
        f.engineer.record_evidence(command(f.engineer, "evidence.record"), f.evidence)
    assert counts(f) == before
    summary = EvidenceRecord(evidence_id="summary-1", work_item_id="work", observer_ref="agent:engineer",
                             source_class="endpoint_reported", baseline_ref="baseline-1",
                             artifact_sha256=f.output.sha256, summary="Unverified endpoint summary")
    f.engineer.record_evidence(command(f.engineer, "evidence.record"), summary)
    with psycopg.connect(f.dsn) as conn:
        assert conn.execute("SELECT source_class,evidence_state,bundle_ref FROM evidence WHERE evidence_id='summary-1'").fetchone() == ("endpoint_reported", "incomplete", None)


def publish_fixture_after_ready(f):
    """Explicit authorized fixture publication, with real filesystem readback.

    Node/Gateway admission is still fixture-seeded. The verifier independently
    opens the published resource; it never derives success from DB status.
    """
    target = f.store.root.parent / "published-output"
    target.write_bytes(f.store.read(f.output))
    seed_effect(f)
    calls = []
    def verify(cursor, context, effect):
        payload = target.read_bytes()
        if hashlib.sha256(payload).hexdigest() != f.output.sha256:
            raise ValueError('published bytes do not match candidate digest')
        assert effect["candidate_ref"] == f.receipt.candidate_ref
        calls.append(effect["effect_id"])
        return fixture_effect_proof(f, effect)
    f.finalizer._effect_readback_verifier = verify
    return target, calls


def fixture_effect_proof(f, effect):
    # Intentionally explicit fixture lineage, not a claim of real Gateway
    # execution. publish_fixture_after_ready separately reads the actual bytes.
    return EffectReadback(
        effect_id=effect["effect_id"], work_item_id=effect["work_item_id"],
        resource_id=effect["resource_id"], status="verified", readback_ref=effect["readback_ref"],
        sha256=f.output.sha256, size_bytes=f.output.size_bytes,
        operation_id="fixture-effect-op", intent_sha256=hashlib.sha256(b"explicit-fixture-intent").hexdigest(),
        completion_sha256=hashlib.sha256(b"explicit-fixture-completion").hexdigest(),
        completion_state="completed",
    )


def test_ready_authorizes_later_publication_and_acceptance_reads_actual_output(runtime):
    f = runtime
    register(f)
    review(f)
    transition(f, WorkItemState.ACCEPTANCE_READY, 0)
    with psycopg.connect(f.dsn) as conn:
        ready = conn.execute("SELECT effect_refs,readback_refs,readback_digest FROM accepted_state_revisions WHERE readiness_snapshot").fetchone()
    assert ready[0:2] == ([], [])
    _, calls = publish_fixture_after_ready(f)
    accepted = transition(f, WorkItemState.ACCEPTED, 1, effects=("effect-1",), readbacks=("effect-readback-1",))
    assert accepted.revision == 2 and calls == ["effect-1"]
    with psycopg.connect(f.dsn) as conn:
        final = conn.execute("SELECT effect_refs,readback_refs,readback_digest FROM accepted_state_revisions WHERE NOT readiness_snapshot").fetchone()
    assert final[0:2] == (["effect-1"], ["effect-readback-1"])
    assert final[2] != ready[2]  # Final digest includes the newly verified Effect.


@pytest.mark.parametrize("case,reason", [
    ("uncertain", "every protected effect must be verified"),
    ("wrong_candidate", "effect candidate differs from readiness candidate"),
    ("omitted", "all protected effects must be included"),
    ("corrupt_publication", "live effect readback verification failed"),
])
def test_post_readiness_effects_still_require_complete_candidate_bound_verification(runtime, case, reason):
    f = runtime
    register(f)
    review(f)
    transition(f, WorkItemState.ACCEPTANCE_READY, 0)
    if case in ("omitted", "corrupt_publication"):
        target, _ = publish_fixture_after_ready(f)
        if case == "corrupt_publication":
            target.write_bytes(b"wrong published bytes")
    else:
        seed_effect(f, "uncertain" if case == "uncertain" else "verified",
                    candidate_ref="another-candidate" if case == "wrong_candidate" else None)
    before = counts(f)
    with pytest.raises(AcceptanceGuardFailed, match=reason):
        transition(f, WorkItemState.ACCEPTED, 1,
                   effects=() if case == "omitted" else ("effect-1",),
                   readbacks=() if case == "omitted" else ("effect-readback-1",))
    assert counts(f) == before
    assert f.finalizer.get_work_item("work")["state"] == "acceptance_ready"


def test_concurrent_effect_insert_cannot_escape_acceptance_enumeration(runtime):
    f = runtime
    register(f)
    review(f)
    transition(f, WorkItemState.ACCEPTANCE_READY, 0)
    validating = threading.Event()
    allow_commit = threading.Event()
    original = f.finalizer._validate_acceptance_effects
    def paused_validation(*args):
        # transition_work_item already holds the WorkItem row lock. Pause just
        # before enumeration so the concurrent INSERT attempts its trigger lock.
        validating.set()
        assert allow_commit.wait(10), "test did not release acceptance transaction"
        return original(*args)
    f.finalizer._validate_acceptance_effects = paused_validation
    with ThreadPoolExecutor(max_workers=2) as pool, psycopg.connect(f.dsn) as writer:
        accepted = pool.submit(transition, f, WorkItemState.ACCEPTED, 1)
        assert validating.wait(10), "acceptance did not reach locked enumeration"
        writer_pid = writer.info.backend_pid
        def insert_after_barrier():
            writer.execute(
                "INSERT INTO effects(effect_id,tenant_id,work_item_id,resource_id,baseline_ref,lease_id,"
                "fencing_token,generation,status,readback_ref,grant_ref,candidate_ref) VALUES "
                "('late-effect','local-tenant','work','late-resource','baseline-1','fixture-lease',"
                "'fixture-token',1,'verified','late-readback','grant:engineer',%s)",
                (f.receipt.candidate_ref,))
            writer.commit()
        inserted = pool.submit(insert_after_barrier)
        try:
            deadline = time.monotonic() + 10
            with psycopg.connect(f.dsn, autocommit=True) as monitor:
                while time.monotonic() < deadline:
                    state = monitor.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s", (writer_pid,)).fetchone()
                    if state and state[0] == "Lock":
                        break
                    if inserted.done():
                        pytest.fail("Effect insertion escaped the WorkItem serialization barrier")
                    time.sleep(0.01)
                else:
                    pytest.fail("concurrent insertion never reached the WorkItem lock")
        finally:
            allow_commit.set()
        assert accepted.result(timeout=10).state == "accepted"
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="accepted work item rejects effect mutation"):
            inserted.result(timeout=10)
        writer.rollback()
    with psycopg.connect(f.dsn) as conn:
        assert conn.execute("SELECT count(*) FROM effects").fetchone()[0] == 0


@pytest.mark.parametrize("phase", ["registration", "after_ready"])
def test_revoked_execution_slot_blocks_receipt_registration_and_final_acceptance(runtime, phase):
    f = runtime
    if phase == "after_ready":
        register(f)
        review(f)
        transition(f, WorkItemState.ACCEPTANCE_READY, 0)
    with psycopg.connect(f.dsn) as conn:
        conn.execute("UPDATE agent_slots SET status='revoked' WHERE agent_slot_id='local-slot'")
    before = counts(f)
    with pytest.raises(AcceptanceGuardFailed, match="trusted execution attempt binding is missing or unauthorized"):
        if phase == "registration":
            register(f)
        else:
            transition(f, WorkItemState.ACCEPTED, 1)
    assert counts(f) == before


def test_registered_effect_history_cannot_be_deleted_to_shrink_readiness_set(runtime):
    f = runtime
    register(f)
    review(f)
    publish_fixture_after_ready(f)
    transition(f, WorkItemState.ACCEPTANCE_READY, 0,
               effects=("effect-1",), readbacks=("effect-readback-1",))
    before = counts(f)
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="registered effect history cannot be deleted"),
        psycopg.connect(f.dsn) as conn,
    ):
        conn.execute("DELETE FROM effects WHERE effect_id='effect-1'")
    with psycopg.connect(f.dsn) as conn:
        assert conn.execute("SELECT effect_id FROM effects").fetchall() == [("effect-1",)]
    with pytest.raises(AcceptanceGuardFailed, match="all protected effects must be included"):
        transition(f, WorkItemState.ACCEPTED, 1)
    assert counts(f) == before


def sleep_past_database_deadline(cursor, deadline):
    seconds = cursor.execute(
        "SELECT GREATEST(0,EXTRACT(EPOCH FROM (%s::timestamptz-clock_timestamp())))", (deadline,)
    ).fetchone()[0]
    time.sleep(float(seconds) + 0.05)


@pytest.mark.parametrize("expires", ["command", "finalizer", "reviewer", "producer", "node", "bundle"])
def test_actual_readback_crossing_any_authorization_expiry_rolls_back_acceptance(runtime, expires):
    f = runtime
    if expires == "bundle":
        deadline = datetime.now(UTC) + timedelta(seconds=5)
        # Seal the expiry in the same immutable Bundle used at readiness.
        f.bundle = f.bundle.model_copy(update={"expires_at": deadline})
    register(f)
    review(f)
    transition(f, WorkItemState.ACCEPTANCE_READY, 0)
    _, calls = publish_fixture_after_ready(f)
    if expires != "bundle":
        with psycopg.connect(f.dsn) as conn:
            deadline = conn.execute("SELECT clock_timestamp()+interval '2 seconds'").fetchone()[0]
            grants = {"finalizer": "grant:finalizer", "reviewer": "grant:reviewer",
                      "producer": "grant:engineer", "node": "grant:node"}
            if expires in grants:
                conn.execute("UPDATE grants SET expires_at=%s WHERE grant_ref=%s", (deadline, grants[expires]))
    cmd = command(f.finalizer, "work_item.transition", 1)
    if expires == "command":
        cmd = cmd.model_copy(update={"deadline": deadline})
    actual_readback = f.finalizer._effect_readback_verifier
    def slow_actual_readback(cursor, context, effect):
        observed = actual_readback(cursor, context, effect)
        sleep_past_database_deadline(cursor, deadline)
        return observed
    f.finalizer._effect_readback_verifier = slow_actual_readback
    before = counts(f)
    with pytest.raises(AcceptanceGuardFailed, match="acceptance authorization expired during verification"):
        f.finalizer.transition_work_item(cmd, TransitionRequest(
            to_state=WorkItemState.ACCEPTED, evidence_refs=("evidence-1",), review_ref="review-1",
            effect_refs=("effect-1",), readback_refs=("effect-readback-1",)))
    assert calls == ["effect-1"]  # Actual resource readback occurred exactly once.
    assert counts(f) == before
    with psycopg.connect(f.dsn) as conn:
        assert conn.execute("SELECT state,revision FROM work_items WHERE work_item_id='work'").fetchone() == ("acceptance_ready", 1)


def test_slow_real_cas_verification_cannot_commit_after_command_deadline(runtime):
    f = runtime
    register(f)
    review(f)
    transition(f, WorkItemState.ACCEPTANCE_READY, 0)
    cmd = command(f.finalizer, "work_item.transition", 1)
    with psycopg.connect(f.dsn) as conn:
        deadline = conn.execute("SELECT clock_timestamp()+interval '2 seconds'").fetchone()[0]
    cmd = cmd.model_copy(update={"deadline": deadline})
    verify = f.store.verify
    calls = []
    def slow_cas(ref):
        actual = verify(ref)
        if ref == f.output:
            calls.append(ref.path)
            with psycopg.connect(f.dsn) as timer:
                sleep_past_database_deadline(timer.cursor(), deadline)
        return actual
    f.store.verify = slow_cas
    before = counts(f)
    with pytest.raises(AcceptanceGuardFailed, match="acceptance authorization expired during verification"):
        f.finalizer.transition_work_item(cmd, TransitionRequest(
            to_state=WorkItemState.ACCEPTED, evidence_refs=("evidence-1",), review_ref="review-1"))
    assert calls == [f.output.path]
    assert counts(f) == before


@pytest.mark.parametrize("field,value,reason", [
    ("sha256", "f" * 64, "live effect readback binding differs"),
    ("size_bytes", 9999, "live effect readback binding differs"),
    ("operation_id", "another-operation", "live effect readback binding differs"),
    ("intent_sha256", "e" * 64, "live effect readback binding differs"),
    ("completion_sha256", None, "live effect readback is invalid"),
    ("completion_state", "prepared", "live effect readback is invalid"),
])
def test_final_acceptance_requires_complete_matching_effect_readback_proof(runtime, field, value, reason):
    f = runtime
    register(f)
    review(f)
    transition(f, WorkItemState.ACCEPTANCE_READY, 0)
    publish_fixture_after_ready(f)
    verified = f.finalizer._effect_readback_verifier
    def altered(cursor, context, effect):
        proof = verified(cursor, context, effect)
        changes = {field: value}
        if field == "completion_state":
            changes["completion_sha256"] = None
        return proof.model_copy(update=changes)
    f.finalizer._effect_readback_verifier = altered
    before = counts(f)
    with pytest.raises(AcceptanceGuardFailed, match=reason):
        transition(f, WorkItemState.ACCEPTED, 1, effects=("effect-1",), readbacks=("effect-readback-1",))
    assert counts(f) == before


def test_legacy_effect_without_expected_proof_binding_fails_closed(runtime):
    f = runtime
    register(f)
    review(f)
    transition(f, WorkItemState.ACCEPTANCE_READY, 0)
    publish_fixture_after_ready(f)
    with psycopg.connect(f.dsn) as conn:
        conn.execute("UPDATE effects SET intent_sha256=NULL WHERE effect_id='effect-1'")
    before = counts(f)
    with pytest.raises(AcceptanceGuardFailed, match="effect execution proof binding is missing"):
        transition(f, WorkItemState.ACCEPTED, 1, effects=("effect-1",), readbacks=("effect-readback-1",))
    assert counts(f) == before
