"""Real PostgreSQL, Ed25519 and local-execution enrollment regressions.

Requires the schema-1.6 integration and ACS_P1_DSN. No Node, Runtime or Attempt
row is created by fixture SQL. Initial operator/actor Grants use the existing
explicit local-profile bootstrap. The process test is not Harness conformance.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg import sql
from psycopg.conninfo import make_conninfo

from runtime.artifacts import LocalArtifactStore
from runtime.domain import DomainAuthority
from runtime.effects import LocalFileEffectGateway
from runtime.enrollment import EnrollmentAuthority
from runtime.enrollment_models import (
    AttemptRegistration,
    NodeChallengeRequest,
    NodeCommandProof,
    NodeEnrollment,
    NodeRevocation,
    NodeRotation,
    RuntimeRegistration,
)
from runtime.errors import (
    AcceptanceGuardFailed,
    AuthorizationDenied,
    FencingRejected,
    IdempotencyConflict,
    LeaseRejected,
    RevisionConflict,
)
from runtime.models import (
    CommandEnvelope,
    EvidenceBundle,
    EvidenceRecord,
    ExecutionReceipt,
    LeaseRequest,
    TransitionRequest,
    WorkItemState,
)


def command(domain, name, target_kind, target_id, revision=0):
    now = datetime.now(UTC)
    identity = uuid.uuid4().hex
    return CommandEnvelope(
        command_id=f"enroll-cmd-{identity}", idempotency_key=f"enroll-key-{identity}", command_type=name,
        correlation_id="enrollment-test", tenant_id=domain.tenant_id, authority_id=domain.authority_id,
        authority_incarnation=domain.context.authority_incarnation, principal_ref=domain.context.principal_ref,
        grant_ref=domain.context.grant_ref, target_kind=target_kind, target_id=target_id,
        expected_revision=revision, issued_at=now, deadline=now + timedelta(minutes=5),
    )


def public_key(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def counts(f):
    tables = ("command_dedup", "domain_events", "operations", "outbox", "enrolled_nodes", "enrolled_node_bindings",
              "enrolled_runtimes", "attempts", "execution_receipts", "evidence", "enrolled_node_command_proofs")
    with psycopg.connect(f.dsn) as conn:
        return {table: conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()[0] for table in tables}


def source_identity(repo):
    """Bind an archive to runner-supplied IDs, never an enclosing repository."""
    supplied = (os.environ.get("ACS_TEST_SOURCE_COMMIT"), os.environ.get("ACS_TEST_SOURCE_TREE"))
    if any(value is not None for value in supplied):
        if not all(value and len(value.strip()) in (40, 64)
                   and all(char in "0123456789abcdef" for char in value.strip()) for value in supplied):
            raise RuntimeError("ACS_TEST_SOURCE_COMMIT and ACS_TEST_SOURCE_TREE must both be full verified Git object IDs")
        return tuple(value.strip() for value in supplied)
    repo = Path(repo).resolve()
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=repo,
                             capture_output=True, text=True, check=True).stdout.strip()
        if Path(top).resolve() != repo:
            raise RuntimeError("Git top-level is not the exact source root; archived runners must provide ACS_TEST_SOURCE_COMMIT/TREE")
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
        tree = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise RuntimeError("Source identity unavailable; archived runners must provide ACS_TEST_SOURCE_COMMIT/TREE") from None
    return commit, tree


@pytest.fixture
def env(tmp_path):
    dsn = os.environ.get("ACS_P1_DSN")
    if not dsn:
        pytest.skip("ACS_P1_DSN required; PostgreSQL enrollment not measured")
    if not sys.platform.startswith("linux"):
        pytest.skip("the integrated receipt fixture requires real Linux CAS")
    schema = f"enrollment_{uuid.uuid4().hex}"
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(dsn, options=f"-c search_path={schema} -c lock_timeout=5000")
    store = LocalArtifactStore(tmp_path / "cas")
    try:
        actor = DomainAuthority(isolated, artifact_store=store)
        actor.initialize()
        actor.bootstrap_local_grant()
        def role(name, permissions):
            context = replace(actor.context, principal_ref=f"enrollment:{name}", grant_ref=f"grant:enrollment:{name}")
            domain = DomainAuthority(isolated, context=context, artifact_store=store)
            domain.bootstrap_local_grant(permissions)
            return domain
        operator = role("operator", ("enrollment.manage", "work_item.read"))
        node = role("node", ("runtime.register", "attempt.register", "execution.record", "work_item.read"))
        reviewer = role("reviewer", ("review.record", "work_item.read"))
        finalizer = role("finalizer", ("review.assign", "work_item.transition", "acceptance.finalize", "work_item.read"))
        repo = Path(__file__).resolve().parents[1]
        commit, tree = source_identity(repo)
        baseline = f"git:{commit}"
        actor.create_work_item(command(actor, "work_item.create", "work_item", "work"), "local-scope", "local-slot", baseline)
        yield SimpleNamespace(dsn=isolated, actor=actor, operator=operator, node=node, reviewer=reviewer,
                              finalizer=finalizer, store=store, key=Ed25519PrivateKey.generate(), node_revision=1,
                              baseline=baseline, commit=commit, tree=tree)
    finally:
        store.close()
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def enroll(f, *, node_id="node-1", key=None, expires_at=None):
    request = NodeEnrollment(scope_id="local-scope", agent_slot_id="local-slot", observer_grant_ref=f.node.context.grant_ref,
                             machine_id="machine-1", boot_incarnation="boot-1", public_key=public_key(key or f.key),
                             expires_at=expires_at or datetime.now(UTC) + timedelta(minutes=30))
    cmd = command(f.operator, "node.enroll", "node", node_id)
    return f.operator.enroll_node(cmd, request), cmd, request


def proof(f, purpose_command, node_input, *, signer=None, node_id="node-1", revision=None, ttl=120):
    issued = f.node.challenge_node(command(f.node, "node.challenge", "node", node_id,
                                           f.node_revision if revision is None else revision), NodeChallengeRequest(
        purpose=purpose_command.command_type, purpose_command_id=purpose_command.command_id,
        purpose_hash=EnrollmentAuthority.signing_hash(purpose_command, node_input), ttl_seconds=ttl))
    signed = (signer or f.key).sign(bytes.fromhex(issued.message_hex))
    return NodeCommandProof(challenge_id=issued.challenge_id, signature=signed.hex())


def runtime(f):
    request = RuntimeRegistration(node_id="node-1", node_binding_revision=f.node_revision, provider="local-subprocess",
                                  producer_grant_ref=f.actor.context.grant_ref, expires_at=datetime.now(UTC) + timedelta(minutes=20))
    cmd = command(f.node, "runtime.register", "runtime", "runtime-1")
    signed = proof(f, cmd, {"request": request.model_dump(mode="json")})
    return f.node.register_runtime(cmd, request, signed), cmd, request, signed


def execute_and_register_attempt(f, *, proof_ttl=120):
    # Capture the real inline execution input as an artifact. Git IDs identify
    # the inspected source baseline; this manifest captures the extra test input.
    argv = [sys.executable, "-c", "print('authenticated enrollment execution')"]
    started = datetime.now(UTC)
    executed = subprocess.run(argv, capture_output=True, check=True)
    finished = datetime.now(UTC)
    output = f.store.put_bytes(executed.stdout, kind="output")
    manifest = f.store.put_bytes(json.dumps({"inline_argv": argv}).encode(), kind="manifest")
    readback = f.store.put_bytes(json.dumps({"sha256": hashlib.sha256(f.store.read(output)).hexdigest(),
                                           "size_bytes": len(executed.stdout)}).encode(), kind="readback")
    candidate = f"test-output:{output.sha256}"
    request = AttemptRegistration(runtime_id="runtime-1", work_item_id="work", expected_work_item_revision=0,
                                  source_baseline=f.baseline, source_commit=f.commit, source_tree=f.tree,
                                  candidate_ref=candidate, observed_started_at=started)
    cmd = command(f.node, "attempt.register", "attempt", "attempt-1")
    signed = proof(f, cmd, {"request": request.model_dump(mode="json")}, ttl=proof_ttl)
    registered = f.node.register_attempt(cmd, request, signed)
    f.last_attempt_request, f.last_attempt_proof = request, signed
    binding = registered.binding
    receipt = ExecutionReceipt(
        receipt_id="receipt-1", work_item_id="work", attempt_id="attempt-1", runtime_id="runtime-1",
        provider="local-subprocess", command_id=binding["execution_command_id"],
        operation_id=binding["execution_operation_id"], event_id=binding["execution_event_id"],
        source_baseline=f.baseline, candidate_ref=candidate, source_commit=f.commit, source_tree=f.tree,
        untracked_manifest=manifest, test_commands=(json.dumps(argv),), test_exit_codes=(executed.returncode,),
        test_exit_code=executed.returncode, os=sys.platform, toolchain=sys.version,
        artifact_refs=(output,), readback_refs=(readback,), source_sync="git-baseline-and-captured-inline-input",
        status="succeeded", observed_at=finished,
    )
    return receipt, registered, cmd


def record(f, receipt, *, proof_ttl=120):
    cmd = command(f.node, "execution.record", "work_item", "work")
    signed = proof(f, cmd, {"receipt": receipt.model_dump(mode="json")}, ttl=proof_ttl)
    return f.node.record_execution_receipt(cmd, receipt, node_proof=signed), cmd, signed


def ready(f, receipt):
    bundle = EvidenceBundle(evidence_id="evidence-1", work_item_id="work", source_baseline=f.baseline,
        candidate_ref=receipt.candidate_ref, producer_ref=f.actor.context.principal_ref, observer_ref=f.node.context.principal_ref,
        source_class="directly_verified", evidence_state="complete", execution_receipt=receipt,
        artifact_refs=receipt.artifact_refs, readback_refs=receipt.readback_refs, command_id=receipt.command_id,
        operation_id=receipt.operation_id, event_id=receipt.event_id, observed_at=datetime.now(UTC))
    evidence = EvidenceRecord(evidence_id="evidence-1", work_item_id="work", observer_ref=f.node.context.principal_ref,
        source_class="directly_verified", baseline_ref=f.baseline, artifact_sha256=receipt.artifact_refs[0].sha256,
        summary="Actual local subprocess, signed Node observation and real CAS bytes; no Harness conformance claim",
        bundle_ref="evidence-1", candidate_ref=receipt.candidate_ref, execution_receipt_ref=receipt.receipt_id,
        evidence_state="complete", producer_ref=f.actor.context.principal_ref, attempt_id="attempt-1", test_exit_code=0,
        artifact_refs=receipt.artifact_refs, readback_refs=receipt.readback_refs)
    f.actor.record_evidence(command(f.actor, "evidence.record", "work_item", "work"), evidence, bundle)
    f.finalizer.assign_reviewer(command(f.finalizer, "review.assign", "work_item", "work"),
                               "work", f.reviewer.context.principal_ref, f.reviewer.context.grant_ref)
    f.reviewer.record_review(command(f.reviewer, "review.record", "work_item", "work"),
                             "review-1", "work", "pass", "evidence-1", f.baseline)
    return f.finalizer.transition_work_item(command(f.finalizer, "work_item.transition", "work_item", "work"),
        TransitionRequest(to_state=WorkItemState.ACCEPTANCE_READY, evidence_refs=("evidence-1",), review_ref="review-1"))


def test_formal_enrollment_produces_signed_execution_receipt_and_evidence(env):
    f = env
    node, _, _ = enroll(f)
    runtime_reply, _, _, _ = runtime(f)
    receipt, attempt, attempt_command = execute_and_register_attempt(f)
    stored, receipt_command, _ = record(f, receipt)
    assert node.binding["event_id"] and runtime_reply.binding["event_id"]
    assert receipt.command_id == attempt_command.command_id
    assert receipt.operation_id == attempt.result.operation_id != stored.operation_id
    assert receipt.event_id == attempt.binding["execution_event_id"]
    assert ready(f, receipt).revision == 1
    with psycopg.connect(f.dsn) as conn:
        data = conn.execute("SELECT enrollment_recorded_at,registration_command_id,enrollment_proof_ref FROM execution_receipts").fetchone()
        assert data[0] is not None and data[1] == receipt_command.command_id and data[2]
        assert conn.execute("SELECT count(*) FROM domain_events WHERE target_kind IN ('node','runtime','attempt') AND work_item_id IS NOT NULL").fetchone()[0] == 0
        assert conn.execute("SELECT related_work_item_id FROM domain_events WHERE target_kind='attempt' AND command_id=%s",
                            (attempt_command.command_id,)).fetchone()[0] == "work"
        assert conn.execute("SELECT state,revision FROM work_items WHERE work_item_id='work'").fetchone() == ("acceptance_ready", 1)


def test_current_operator_authorization_and_revision_are_required(env):
    f = env
    _, cmd, request = enroll(f)
    before = counts(f)
    with pytest.raises(AuthorizationDenied):
        f.actor.enroll_node(command(f.actor, "node.enroll", "node", "unauthorized"), request)
    with pytest.raises(RevisionConflict):
        f.operator.enroll_node(command(f.operator, "node.enroll", "node", "different", 3), request)
    with pytest.raises(IdempotencyConflict):
        f.operator.enroll_node(cmd, request.model_copy(update={"machine_id": "changed"}))
    assert counts(f) == before


def test_exact_enrollment_and_runtime_replay_are_currently_authorized(env):
    f = env
    first, cmd, request = enroll(f)
    runtime_reply, runtime_cmd, runtime_request, signed = runtime(f)
    before = counts(f)
    duplicate = f.operator.enroll_node(cmd, request)
    assert duplicate.result.duplicate and duplicate.binding == first.binding
    duplicate_runtime = f.node.register_runtime(runtime_cmd, runtime_request, signed)
    assert duplicate_runtime.result.duplicate and duplicate_runtime.binding == runtime_reply.binding
    assert counts(f) == before
    with psycopg.connect(f.dsn) as conn:
        conn.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (f.node.context.grant_ref,))
    with pytest.raises(AuthorizationDenied):
        f.node.register_runtime(runtime_cmd, runtime_request, signed)
    assert counts(f) == before


def test_wrong_key_or_changed_signed_input_is_rejected(env):
    f = env
    enroll(f)
    request = RuntimeRegistration(node_id="node-1", node_binding_revision=1, provider="local-subprocess",
                                  producer_grant_ref=f.actor.context.grant_ref, expires_at=datetime.now(UTC) + timedelta(minutes=10))
    cmd = command(f.node, "runtime.register", "runtime", "runtime-1")
    wrong = proof(f, cmd, {"request": request.model_dump(mode="json")}, signer=Ed25519PrivateKey.generate())
    before = counts(f)
    with pytest.raises(AuthorizationDenied):
        f.node.register_runtime(cmd, request, wrong)
    assert counts(f) == before
    signed = proof(f, cmd, {"request": request.model_dump(mode="json")})
    before = counts(f)
    with pytest.raises(AuthorizationDenied):
        f.node.register_runtime(cmd, request.model_copy(update={"provider": "forged-provider"}), signed)
    assert counts(f) == before


def test_node_keys_are_not_shared_between_nodes(env):
    f = env
    enroll(f)
    before = counts(f)
    with pytest.raises(AcceptanceGuardFailed, match="key is shared"):
        enroll(f, node_id="node-2")
    assert counts(f) == before


def test_expired_challenge_and_expired_operator_grant_fail_closed(env):
    f = env
    enroll(f)
    req = RuntimeRegistration(node_id="node-1", node_binding_revision=1, provider="local-subprocess",
                              producer_grant_ref=f.actor.context.grant_ref, expires_at=datetime.now(UTC) + timedelta(minutes=10))
    cmd = command(f.node, "runtime.register", "runtime", "runtime-1")
    signed = proof(f, cmd, {"request": req.model_dump(mode="json")}, ttl=1)
    before = counts(f)
    time.sleep(1.1)
    with pytest.raises(AuthorizationDenied):
        f.node.register_runtime(cmd, req, signed)
    with psycopg.connect(f.dsn) as conn:
        conn.execute("UPDATE grants SET expires_at=clock_timestamp()-interval '1 second' WHERE grant_ref=%s", (f.operator.context.grant_ref,))
    with pytest.raises(AuthorizationDenied):
        f.operator.revoke_node(command(f.operator, "node.revoke", "node", "node-1", 1), NodeRevocation(reason="test expiry"))
    assert counts(f) == before


def test_cross_scope_observer_grant_and_slot_cannot_be_enrolled(env):
    f = env
    with psycopg.connect(f.dsn) as conn:
        conn.execute("INSERT INTO scopes(scope_id,tenant_id,policy,status) VALUES ('other-scope',%s,'{}','active')", (f.actor.tenant_id,))
        conn.execute("INSERT INTO agent_slots(agent_slot_id,tenant_id,scope_id,status) VALUES ('other-slot',%s,'other-scope','active')", (f.actor.tenant_id,))
    request = NodeEnrollment(scope_id="local-scope", agent_slot_id="other-slot", observer_grant_ref=f.node.context.grant_ref,
        machine_id="m", boot_incarnation="b", public_key=public_key(f.key), expires_at=datetime.now(UTC) + timedelta(minutes=10))
    before = counts(f)
    with pytest.raises(AcceptanceGuardFailed, match="Scope/AgentSlot"):
        f.operator.enroll_node(command(f.operator, "node.enroll", "node", "node-1"), request)
    with pytest.raises(AuthorizationDenied):
        f.operator.enroll_node(command(f.operator, "node.enroll", "node", "node-1"),
                               request.model_copy(update={"scope_id": "other-scope"}))
    assert counts(f) == before


def rotate(f):
    new_key = Ed25519PrivateKey.generate()
    reply = f.operator.rotate_node(command(f.operator, "node.rotate", "node", "node-1", 1), NodeRotation(
        machine_id="replacement-machine", boot_incarnation="boot-2", public_key=public_key(new_key),
        expires_at=datetime.now(UTC) + timedelta(minutes=30)))
    f.node_revision, f.key = reply.result.revision, new_key
    return reply


@pytest.mark.parametrize("lifecycle", ["rotate", "revoke"])
def test_retirement_blocks_new_writes_but_preserves_recorded_ready_evidence(env, lifecycle):
    f = env
    enroll(f)
    runtime(f)
    receipt, _, _ = execute_and_register_attempt(f)
    record(f, receipt)
    ready(f, receipt)
    lease_request = LeaseRequest(resource_id="resource", owner_attempt_id="attempt-1",
        owner_runtime_id="runtime-1", work_item_id="work", scope_id="local-scope", grant_ref=f.actor.context.grant_ref,
        authority_incarnation=f.actor.context.authority_incarnation, ttl_seconds=60)
    live_lease = f.actor.leases.acquire_lease(command(f.actor, "lease.acquire", "lease", "resource", 1), lease_request)
    fence = {"lease_id": live_lease["lease_id"], "resource_id": "resource", "generation": live_lease["generation"],
             "fencing_token": live_lease["fencing_token"], "caller": f.actor.context, "attempt_id": "attempt-1",
             "runtime_id": "runtime-1", "scope_id": "local-scope", "grant_ref": f.actor.context.grant_ref,
             "authority_incarnation": f.actor.context.authority_incarnation}
    f.actor.leases.verify_fence(**fence)
    if lifecycle == "rotate":
        replacement = rotate(f)
        assert replacement.binding["machine_id"] == "replacement-machine"
    else:
        f.operator.revoke_node(command(f.operator, "node.revoke", "node", "node-1", 1), NodeRevocation(reason="block future activity"))
    lease_cmd = command(f.actor, "lease.acquire", "lease", "resource", 1)
    before = counts(f)
    with pytest.raises(FencingRejected):
        f.actor.leases.verify_fence(**fence)
    with pytest.raises(LeaseRejected):
        f.actor.leases.acquire_lease(lease_cmd, lease_request)
    assert counts(f) == before
    accepted = f.finalizer.transition_work_item(command(f.finalizer, "work_item.transition", "work_item", "work", 1),
        TransitionRequest(to_state=WorkItemState.ACCEPTED, evidence_refs=("evidence-1",), review_ref="review-1"))
    assert accepted.revision == 2
    with psycopg.connect(f.dsn) as conn:
        assert conn.execute("SELECT scope_id,agent_slot_id FROM enrolled_nodes").fetchone() == ("local-scope", "local-slot")
        assert conn.execute("SELECT count(*) FROM execution_receipts").fetchone()[0] == 1
        snapshot = conn.execute("SELECT to_jsonb(a) FROM accepted_state_revisions a ORDER BY revision").fetchall()
    if lifecycle == "rotate":
        f.operator.revoke_node(command(f.operator, "node.revoke", "node", "node-1", 2), NodeRevocation(reason="later shutdown"))
        with psycopg.connect(f.dsn) as conn:
            assert conn.execute("SELECT to_jsonb(a) FROM accepted_state_revisions a ORDER BY revision").fetchall() == snapshot


def test_backdated_unrecorded_receipt_cannot_enter_after_boot_retirement(env):
    f = env
    enroll(f)
    runtime(f)
    receipt, _, _ = execute_and_register_attempt(f)
    cmd = command(f.node, "execution.record", "work_item", "work")
    rotate(f)
    # Even fresh authentication by the replacement Node cannot admit a new
    # backdated receipt for the retired execution binding.
    signed = proof(f, cmd, {"receipt": receipt.model_dump(mode="json")})
    before = counts(f)
    with pytest.raises(AcceptanceGuardFailed, match="Runtime enrollment is missing, expired or retired"):
        f.node.record_execution_receipt(cmd, receipt, node_proof=signed)
    assert counts(f) == before
    assert before["execution_receipts"] == 0


def test_old_boot_cannot_be_reactivated_or_sign_current_requests(env):
    f = env
    _, _, original = enroll(f)
    rotate(f)
    before = counts(f)
    with pytest.raises(AcceptanceGuardFailed, match="boot cannot be reactivated"):
        f.operator.rotate_node(command(f.operator, "node.rotate", "node", "node-1", 2), NodeRotation(
            machine_id="machine-1", boot_incarnation="boot-1", public_key=original.public_key,
            expires_at=datetime.now(UTC) + timedelta(minutes=30)))
    request = RuntimeRegistration(node_id="node-1", node_binding_revision=1, provider="local-subprocess",
        producer_grant_ref=f.actor.context.grant_ref, expires_at=datetime.now(UTC) + timedelta(minutes=10))
    cmd = command(f.node, "runtime.register", "runtime", "old-binding-runtime")
    signed = proof(f, cmd, {"request": request.model_dump(mode="json")})
    before = counts(f)
    with pytest.raises(AcceptanceGuardFailed, match="binding is not current"):
        f.node.register_runtime(cmd, request, signed)
    assert counts(f) == before


def test_signature_receipt_tampering_is_not_repaired_from_caller_body(env):
    f = env
    enroll(f)
    runtime(f)
    receipt, _, _ = execute_and_register_attempt(f)
    record(f, receipt)
    with psycopg.connect(f.dsn) as conn:
        conn.execute("UPDATE enrolled_node_command_proofs SET signature=%s WHERE purpose='execution.record'", ("00" * 64,))
    before = counts(f)
    with pytest.raises(AcceptanceGuardFailed, match="recorded execution signature is invalid"):
        ready(f, receipt)
    assert counts(f) == before


def test_retirement_waiting_before_receipt_seal_uses_actual_database_write_time(env, monkeypatch):
    f = env
    enroll(f)
    runtime(f)
    receipt, _, _ = execute_and_register_attempt(f)
    receipt_command = command(f.node, "execution.record", "work_item", "work")
    receipt_proof = proof(f, receipt_command, {"receipt": receipt.model_dump(mode="json")})
    seal_reached = threading.Event()
    allow_seal = threading.Event()
    retirement_started = threading.Event()
    retiring_transactions = []
    original_seal = EnrollmentAuthority.seal_execution_receipt
    original_connect = f.operator._connect

    def held_seal(self, cursor, cmd, observed, enrolled):
        seal_reached.set()
        assert allow_seal.wait(10)
        return original_seal(self, cursor, cmd, observed, enrolled)

    def retire_connection():
        conn = original_connect()
        # This earlier transaction-start timestamp must never be used as the
        # later, lock-protected retirement time of a key, Runtime or Node boot.
        begun = conn.execute("SELECT now()").fetchone()[0]
        retiring_transactions.append((conn.info.backend_pid, begun))
        retirement_started.set()
        return conn

    monkeypatch.setattr(EnrollmentAuthority, "seal_execution_receipt", held_seal)
    monkeypatch.setattr(f.operator, "_connect", retire_connection)
    with ThreadPoolExecutor(max_workers=2) as pool:
        recording = pool.submit(f.node.record_execution_receipt, receipt_command, receipt, node_proof=receipt_proof)
        assert seal_reached.wait(10)
        retiring = pool.submit(rotate, f)
        try:
            assert retirement_started.wait(10)
            pid = retiring_transactions[0][0]
            deadline = time.monotonic() + 3
            with psycopg.connect(f.dsn, autocommit=True) as monitor:
                while time.monotonic() < deadline:
                    state = monitor.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s", (pid,)).fetchone()
                    if state and state[0] == "Lock":
                        break
                    if retiring.done():
                        pytest.fail("retirement did not serialize after the receipt transaction")
                    time.sleep(0.01)
                else:
                    pytest.fail("retirement did not reach its authorization/binding lock")
        finally:
            allow_seal.set()
        assert recording.result(timeout=10).state == "execution_receipt"
        assert retiring.result(timeout=10).result.state == "node_rotated"
    with psycopg.connect(f.dsn) as conn:
        recorded_at = conn.execute("SELECT enrollment_recorded_at FROM execution_receipts").fetchone()[0]
        retired_times = conn.execute(
            "SELECT b.retired_at,k.retired_at,r.retired_at FROM enrolled_node_bindings b "
            "JOIN enrolled_node_keys k ON k.key_id=b.key_id JOIN enrolled_runtimes r "
            "ON r.node_id=b.node_id AND r.node_binding_revision=b.binding_revision "
            "WHERE b.binding_revision=1").fetchone()
    assert retiring_transactions[0][1] < recorded_at
    assert all(retired_at > recorded_at for retired_at in retired_times)
    assert ready(f, receipt).revision == 1
    accepted = f.finalizer.transition_work_item(command(f.finalizer, "work_item.transition", "work_item", "work", 1),
        TransitionRequest(to_state=WorkItemState.ACCEPTED, evidence_refs=("evidence-1",), review_ref="review-1"))
    assert accepted.state == "accepted"


@pytest.mark.parametrize("key_hex", ["01" + "00" * 31, "95" + "99" * 31])
def test_enroll_and_rotate_reject_small_or_mixed_order_public_keys(env, key_hex):
    f = env
    request = NodeEnrollment(scope_id="local-scope", agent_slot_id="local-slot", observer_grant_ref=f.node.context.grant_ref,
        machine_id="weak-key-machine", boot_incarnation="weak-boot", public_key=key_hex,
        expires_at=datetime.now(UTC) + timedelta(minutes=10))
    before = counts(f)
    with pytest.raises(AcceptanceGuardFailed, match="strict Ed25519 point validation"):
        f.operator.enroll_node(command(f.operator, "node.enroll", "node", "weak-node"), request)
    assert counts(f) == before
    enroll(f)
    before = counts(f)
    with pytest.raises(AcceptanceGuardFailed, match="strict Ed25519 point validation"):
        f.operator.rotate_node(command(f.operator, "node.rotate", "node", "node-1", 1), NodeRotation(
            machine_id="weak-key-machine", boot_incarnation="weak-boot", public_key=key_hex,
            expires_at=datetime.now(UTC) + timedelta(minutes=10)))
    assert counts(f) == before


@pytest.mark.parametrize("mode", ["current", "historical"])
def test_injected_legacy_weak_key_cannot_authenticate_or_validate_history(env, mode):
    f = env
    enroll(f)
    if mode == "historical":
        runtime(f)
        receipt, _, _ = execute_and_register_attempt(f)
        record(f, receipt)
    else:
        request = RuntimeRegistration(node_id="node-1", node_binding_revision=1, provider="local-subprocess",
            producer_grant_ref=f.actor.context.grant_ref, expires_at=datetime.now(UTC) + timedelta(minutes=10))
        cmd = command(f.node, "runtime.register", "runtime", "runtime-1")
        signed = proof(f, cmd, {"request": request.model_dump(mode="json")})
    identity = bytes.fromhex("01" + "00" * 31)
    forged = (identity + bytes(32)).hex()
    # Explicit legacy/corruption injection, never an enrollment bypass in the API.
    with psycopg.connect(f.dsn) as conn:
        conn.execute("UPDATE enrolled_node_keys SET public_key=%s,fingerprint=%s WHERE status='active'",
                     (identity.hex(), hashlib.sha256(identity).hexdigest()))
        if mode == "historical":
            conn.execute("UPDATE enrolled_node_command_proofs SET signature=%s WHERE purpose='execution.record'", (forged,))
    before = counts(f)
    with pytest.raises(AcceptanceGuardFailed, match="strict Ed25519 point validation"):
        if mode == "historical":
            ready(f, receipt)
        else:
            f.node.register_runtime(cmd, request, signed.model_copy(update={"signature": forged}))
    assert counts(f) == before


def replay_case(f, kind, *, ttl=2):
    enroll(f)
    if kind == "runtime":
        request = RuntimeRegistration(node_id="node-1", node_binding_revision=1, provider="local-subprocess",
            producer_grant_ref=f.actor.context.grant_ref, expires_at=datetime.now(UTC) + timedelta(minutes=20))
        cmd = command(f.node, "runtime.register", "runtime", "runtime-1")
        node_input = {"request": request.model_dump(mode="json")}
        signed = proof(f, cmd, node_input, ttl=ttl)
        result = f.node.register_runtime(cmd, request, signed)
    else:
        runtime(f)
        receipt, attempt, attempt_cmd = execute_and_register_attempt(f, proof_ttl=ttl if kind == "attempt" else 120)
        if kind == "attempt":
            request, cmd, signed, result = f.last_attempt_request, attempt_cmd, f.last_attempt_proof, attempt
            node_input = {"request": request.model_dump(mode="json")}
        else:
            result, cmd, signed = record(f, receipt, proof_ttl=ttl)
            request, node_input = receipt, {"receipt": receipt.model_dump(mode="json")}
    def call(value, auth):
        if kind == "runtime":
            return f.node.register_runtime(cmd, value, auth)
        if kind == "attempt":
            return f.node.register_attempt(cmd, value, auth)
        return f.node.record_execution_receipt(cmd, value, node_proof=auth)
    return request, cmd, node_input, signed, result, call


@pytest.mark.parametrize("kind", ["runtime", "attempt", "receipt"])
def test_expired_challenge_can_refresh_auth_without_replaying_business_writes(env, kind):
    f = env
    request, cmd, node_input, original_proof, original, call = replay_case(f, kind)
    with psycopg.connect(f.dsn) as conn:
        immutable_proof = conn.execute("SELECT to_jsonb(p) FROM enrolled_node_command_proofs p WHERE challenge_id=%s",
                                       (original_proof.challenge_id,)).fetchone()[0]
        original_receipt = conn.execute("SELECT to_jsonb(x) FROM execution_receipts x").fetchall()
    time.sleep(2.1)
    before = counts(f)
    with pytest.raises(AuthorizationDenied):
        call(request, original_proof)
    assert counts(f) == before
    refreshed = proof(f, cmd, node_input)
    before = counts(f)  # Challenge issuance has its own unique command audit.
    replay = call(request, refreshed)
    result = replay if kind == "receipt" else replay.result
    expected = original if kind == "receipt" else original.result
    assert result.duplicate and result.operation_id == expected.operation_id
    after = counts(f)
    assert after.pop("enrolled_node_command_proofs") == before.pop("enrolled_node_command_proofs") + 1
    assert after == before
    before = counts(f)
    assert (call(request, refreshed) if kind == "receipt" else call(request, refreshed).result).duplicate
    assert counts(f) == before
    with psycopg.connect(f.dsn) as conn:
        assert conn.execute("SELECT to_jsonb(p) FROM enrolled_node_command_proofs p WHERE challenge_id=%s",
                            (original_proof.challenge_id,)).fetchone()[0] == immutable_proof
        assert conn.execute("SELECT to_jsonb(x) FROM execution_receipts x").fetchall() == original_receipt
        assert conn.execute("SELECT count(*) FROM enrolled_node_command_proofs WHERE command_id=%s", (cmd.command_id,)).fetchone()[0] == 2
        if kind == "attempt":
            assert conn.execute("SELECT enrollment_proof_ref FROM attempts WHERE attempt_id='attempt-1'").fetchone()[0] == original_proof.challenge_id
    if kind == "receipt":
        # Expired original auth remains valid historical evidence at record time.
        assert ready(f, request).revision == 1


@pytest.mark.parametrize("kind", ["runtime", "attempt", "receipt"])
def test_fresh_authentication_cannot_replace_same_command_business_input(env, kind):
    f = env
    request, cmd, _, _, _, call = replay_case(f, kind, ttl=120)
    change = {"provider": "different-provider"} if kind == "runtime" else (
        {"candidate_ref": "different-candidate"} if kind == "attempt" else {"usage": {"changed": True}})
    altered = request.model_copy(update=change)
    node_input = {"receipt" if kind == "receipt" else "request": altered.model_dump(mode="json")}
    signed = proof(f, cmd, node_input)
    before = counts(f)
    with pytest.raises(IdempotencyConflict):
        call(altered, signed)
    assert counts(f) == before


def test_fresh_auth_after_rotation_never_reactivates_old_key_or_changes_original_proof(env):
    f = env
    request, cmd, node_input, original_proof, original, call = replay_case(f, "runtime", ttl=120)
    old_key = f.key
    rotate(f)
    forged_current = proof(f, cmd, node_input, signer=old_key)
    before = counts(f)
    with pytest.raises(AuthorizationDenied):
        call(request, forged_current)
    assert counts(f) == before
    current_proof = proof(f, cmd, node_input)
    before = counts(f)
    replay = call(request, current_proof)
    assert replay.result.duplicate and replay.binding == original.binding
    after = counts(f)
    assert after.pop("enrolled_node_command_proofs") == before.pop("enrolled_node_command_proofs") + 1
    assert after == before
    with psycopg.connect(f.dsn) as conn:
        assert conn.execute("SELECT node_binding_revision FROM enrolled_node_command_proofs WHERE challenge_id=%s",
                            (original_proof.challenge_id,)).fetchone()[0] == 1
        assert conn.execute("SELECT status FROM enrolled_runtimes WHERE runtime_id='runtime-1'").fetchone()[0] == "retired"


@pytest.mark.parametrize("role", ["reviewer", "publisher"])
def test_runtime_identity_does_not_require_evidence_capability(env, tmp_path, role):
    f = env
    enroll(f)
    if role == "reviewer":
        producer = f.reviewer  # Exactly review.record + work_item.read.
    else:
        producer = DomainAuthority(f.dsn, context=replace(f.actor.context,
            principal_ref="publisher:permission-split", grant_ref="grant:publisher:permission-split"), artifact_store=f.store)
        producer.bootstrap_local_grant(("lease.acquire", "lease.release", "effect.write", "effect.read"))
    request = RuntimeRegistration(node_id="node-1", node_binding_revision=1, provider="local-subprocess",
        producer_grant_ref=producer.context.grant_ref, expires_at=datetime.now(UTC) + timedelta(minutes=20))
    runtime_command = command(f.node, "runtime.register", "runtime", "runtime-1")
    signed = proof(f, runtime_command, {"request": request.model_dump(mode="json")})
    enrolled = f.node.register_runtime(runtime_command, request, signed)
    receipt, attempt, _ = execute_and_register_attempt(f)
    assert enrolled.binding["producer_ref"] == producer.context.principal_ref
    assert attempt.binding["producer_ref"] == producer.context.principal_ref
    if role == "publisher":
        lease = producer.leases.acquire_lease(command(producer, "lease.acquire", "lease", "publisher-resource"),
            LeaseRequest(resource_id="publisher-resource", owner_attempt_id="attempt-1", owner_runtime_id="runtime-1",
                work_item_id="work", scope_id="local-scope", grant_ref=producer.context.grant_ref,
                authority_incarnation=producer.context.authority_incarnation, ttl_seconds=60))
        root = tmp_path / "publisher-resource"
        with LocalFileEffectGateway(producer.leases, root, scope_id="local-scope",
                                    resource_paths={"publisher-resource": "output.txt"}) as gateway:
            result = gateway.write(lease_id=lease["lease_id"], resource_id="publisher-resource", generation=lease["generation"],
                fencing_token=lease["fencing_token"], caller=producer.context, attempt_id="attempt-1", runtime_id="runtime-1",
                scope_id="local-scope", grant_ref=producer.context.grant_ref,
                authority_incarnation=producer.context.authority_incarnation, relative_path="output.txt",
                payload=b"publisher capability is independent of evidence", operation_id="publisher-capability-write")
            assert result["sha256"] == hashlib.sha256((root / "output.txt").read_bytes()).hexdigest()
    evidence = EvidenceRecord(evidence_id="unauthorized-evidence", work_item_id="work",
        observer_ref=producer.context.principal_ref, source_class="endpoint_reported", baseline_ref=f.baseline,
        artifact_sha256=receipt.artifact_refs[0].sha256, summary="This actor has no evidence.record capability")
    before = counts(f)
    with pytest.raises(AuthorizationDenied):
        producer.record_evidence(command(producer, "evidence.record", "work_item", "work"), evidence)
    assert counts(f) == before
    # Even a valid Node signature cannot bypass the existing evidence-action
    # producer permission check in Domain._execution_binding.
    receipt_command = command(f.node, "execution.record", "work_item", "work")
    receipt_proof = proof(f, receipt_command, {"receipt": receipt.model_dump(mode="json")})
    before = counts(f)
    with pytest.raises(AcceptanceGuardFailed, match="trusted execution attempt binding is missing or unauthorized"):
        f.node.record_execution_receipt(receipt_command, receipt, node_proof=receipt_proof)
    assert counts(f) == before


def test_source_identity_uses_explicit_archive_ids_without_querying_parent_git(tmp_path, monkeypatch):
    monkeypatch.setenv("ACS_TEST_SOURCE_COMMIT", "a" * 40)
    monkeypatch.setenv("ACS_TEST_SOURCE_TREE", "b" * 40)
    def forbidden(*args, **kwargs):
        pytest.fail("explicit archive identity must not be replaced by a Git lookup")
    monkeypatch.setattr(subprocess, "run", forbidden)
    assert source_identity(tmp_path) == ("a" * 40, "b" * 40)


def test_source_identity_rejects_implicitly_inherited_parent_repository(tmp_path, monkeypatch):
    monkeypatch.delenv("ACS_TEST_SOURCE_COMMIT", raising=False)
    monkeypatch.delenv("ACS_TEST_SOURCE_TREE", raising=False)
    parent = tmp_path / "parent-repository"
    subprocess.run(["git", "init", "-q", str(parent)], check=True)
    snapshot = parent / "archive-source"
    snapshot.mkdir()
    with pytest.raises(RuntimeError, match="not the exact source root"):
        source_identity(snapshot)


def test_source_identity_requires_both_verified_archive_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("ACS_TEST_SOURCE_COMMIT", "a" * 40)
    monkeypatch.delenv("ACS_TEST_SOURCE_TREE", raising=False)
    with pytest.raises(RuntimeError, match="must both be full verified"):
        source_identity(tmp_path)
