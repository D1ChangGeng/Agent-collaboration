"""Owner enrollment and durable historical execution use real PostgreSQL and CAS."""
import psycopg
import pytest

from runtime.enrollment_models import NodeRevocation, RuntimeRegistration
from runtime.errors import AcceptanceGuardFailed, IdempotencyConflict
from runtime_tests import test_enrollment as reference


@pytest.fixture
def enrollment_env(tmp_path):
    yield from reference.env.__wrapped__(tmp_path)


@pytest.fixture
def owner(enrollment_env, monkeypatch):
    env = enrollment_env
    for actor in (env.actor, env.operator, env.node, env.reviewer, env.finalizer):
        actor.access_mode = "owner"
        actor.owner_identity_ref = env.actor.context.grant_ref
    # These owner operations deliberately supply no additional challenge. Native
    # execution observation and CAS readback still come from the actual subprocess.
    monkeypatch.setattr(reference, "proof", lambda *args, **kwargs: None)
    with psycopg.connect(env.dsn) as conn:
        conn.execute("UPDATE grants SET expires_at=clock_timestamp()-interval '1 day',permissions='[]'")
    return env


def test_owner_enrollment_runtime_and_execution_survive_legacy_expiry(owner):
    f = owner
    enrolled, command, request = reference.enroll(f)
    assert enrolled.binding["expires_at"] is None
    replay = f.operator.enroll_node(command, request)
    assert replay.result.duplicate
    with pytest.raises(IdempotencyConflict):
        f.operator.enroll_node(command, request.model_copy(update={"machine_id": "other-machine"}))
    registered, _, _, _ = reference.runtime(f)
    assert registered.binding["expires_at"] is None
    with psycopg.connect(f.dsn) as conn:
        conn.execute("UPDATE enrolled_node_bindings SET expires_at=clock_timestamp()-interval '1 day'")
        conn.execute("UPDATE enrolled_runtimes SET expires_at=clock_timestamp()-interval '1 day'")
    receipt, attempt, _ = reference.execute_and_register_attempt(f)
    assert attempt.binding["enrollment_proof_ref"] is None
    stored, command, _ = reference.record(f, receipt)
    assert f.node.record_execution_receipt(command, receipt).duplicate
    assert stored.state == "execution_receipt"
    assert reference.ready(f, receipt).revision == 1
    with psycopg.connect(f.dsn) as conn:
        assert conn.execute("SELECT count(*) FROM enrolled_node_challenges").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM owner_node_commands").fetchone()[0] == 3


def test_owner_explicit_node_revoke_stops_new_registration(owner):
    f = owner
    reference.enroll(f)
    f.operator.revoke_node(reference.command(f.operator, "node.revoke", "node", "node-1", 1),
                           NodeRevocation(reason="owner removed this machine"))
    request = RuntimeRegistration(node_id="node-1", node_binding_revision=1,
                                  provider="native", producer_grant_ref=f.actor.context.grant_ref)
    with pytest.raises(AcceptanceGuardFailed, match="Node"):
        f.node.register_runtime(reference.command(f.node, "runtime.register", "runtime", "new-runtime"), request)


def test_owner_attempt_history_remains_verifiable_after_node_retirement(owner):
    f = owner
    reference.enroll(f)
    reference.runtime(f)
    receipt, _, _ = reference.execute_and_register_attempt(f)
    reference.record(f, receipt)
    f.operator.revoke_node(reference.command(f.operator, "node.revoke", "node", "node-1", 1),
                           NodeRevocation(reason="machine replaced after completion"))
    with f.actor._connect() as conn, conn.cursor() as cursor:
        f.actor.enrollment.verify_receipt_provenance(cursor, receipt)


def test_owner_review_and_acceptance_follow_work_scope_not_identity_storage_scope(owner):
    f = owner
    reference.enroll(f)
    reference.runtime(f)
    receipt, _, _ = reference.execute_and_register_attempt(f)
    reference.record(f, receipt)
    with psycopg.connect(f.dsn) as conn:
        conn.execute("INSERT INTO scopes(scope_id,tenant_id,policy,status) VALUES ('identity-storage',%s,'{}','active')",
                     (f.actor.tenant_id,))
        conn.execute("UPDATE grants SET scope_id='identity-storage'")
    assert reference.ready(f, receipt).state == "acceptance_ready"
