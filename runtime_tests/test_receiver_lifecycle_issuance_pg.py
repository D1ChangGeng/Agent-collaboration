"""Actual isolated PostgreSQL lifecycle issuance; capacity facts are controlled.

Enrollment, challenge proofs, Runtime/endpoint/key registration and recovery
submission use actual APIs. No delivery Message/Attempt, Host transport, Native,
external service or process is created. This is E2 Core metadata/locking evidence,
not installed Native qualification. Run only under the coordinated sole PG lease.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import timedelta
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from nacl.signing import SigningKey
from psycopg.pq import TransactionStatus

from runtime.codex_driver import BindingIdentity
from runtime.delivery_models import EndpointBindingRequest
from runtime.domain import DomainAuthority
from runtime.enrollment import EnrollmentAuthority
from runtime.enrollment_models import (
    NodeChallengeRequest,
    NodeCommandProof,
    NodeEnrollment,
    NodeRotation,
    RuntimeRegistration,
)
from runtime.errors import AcceptanceGuardFailed, AuthorizationDenied, RevisionConflict
from runtime.models import CommandEnvelope
from runtime.receiver_contract import native_generation
from runtime.receiver_crypto import public_key, sha256, sign, verify
from runtime.receiver_domain import (
    AuthorityTransportKeyRegistration,
    ConnectionReferenceRegistration,
    EndpointRegistrationCommand,
)
from runtime.receiver_lifecycle_contract import (
    CapacityObservation,
    LifecycleCapacityFact,
    LifecycleContractRejected,
    OwnedProcessEvidence,
    sign_observation,
)
from runtime.receiver_lifecycle_domain import current_lifecycle_endpoint
from runtime.receiver_lifecycle_issuance import (
    LifecycleIssuance,
    LifecycleIssuanceRejected,
    require_current_execution,
)
from runtime.receiver_models import EndpointRegistration
from runtime.receiver_recovery_operations import TOPIC, ReceiverRecoveryOperations
from runtime_tests.test_communication import comm as comm_fixture

comm = comm_fixture
PROJECT, RECEIVER, RUNTIME, CONNECTION = "project-alpha", "endpoint-b", "lifecycle-runtime", "lifecycle-connection"


def command(authority, kind, target_kind, target_id, revision=0):
    now, identity = authority.canonical_now(), uuid4().hex
    return CommandEnvelope(command_id="lifecycle-fixture-" + identity, idempotency_key="lifecycle-fixture-key-" + identity,
        correlation_id="actual-lifecycle-enrollment", command_type=kind, tenant_id=authority.tenant_id,
        authority_id=authority.context.authority_id, authority_incarnation=authority.context.authority_incarnation,
        principal_ref=authority.context.principal_ref, grant_ref=authority.context.grant_ref, target_kind=target_kind,
        target_id=target_id, expected_revision=revision, issued_at=now, deadline=now + timedelta(minutes=3))


def proof(f, cmd, node_input):
    issued = f.node.challenge_node(command(f.node, "node.challenge", "node", f.node_id, 1),
        NodeChallengeRequest(purpose=cmd.command_type, purpose_command_id=cmd.command_id,
            purpose_hash=EnrollmentAuthority.signing_hash(cmd, node_input), ttl_seconds=120))
    return NodeCommandProof(challenge_id=issued.challenge_id,
        signature=f.node_key.sign(bytes.fromhex(issued.message_hex)).signature.hex())


def setup_graph(comm, *, mode="shared", locator_port=18765, tls_certificate_sha256="b" * 64):
    authority = comm.authority
    for client in comm.clients.values():
        client.service.service.authority.access_mode = mode
    authority.access_mode = mode
    endpoint = authority._delivery_endpoints[RECEIVER]
    identity = endpoint.identity
    actors = {}
    for name, permissions in (("operator", ("enrollment.manage", "receiver.manage")),
            ("observer", ("runtime.register", "endpoint.register")), ("producer", ("runtime.invoke",))):
        context = replace(authority.context, principal_ref="fixture:lifecycle-" + name,
                          grant_ref="grant:lifecycle-" + name, agent_slot_id=None, trusted_client=False)
        actor = DomainAuthority(comm.dsn, context=context, access_mode=mode)
        actor.bootstrap_local_grant(permissions)
        actors[name] = actor
    f = SimpleNamespace(comm=comm, authority=authority, dsn=comm.dsn, mode=mode, endpoint=endpoint,
        operator=actors["operator"], node=actors["observer"], producer=actors["producer"],
        node_key=SigningKey.generate(), authority_key=SigningKey.generate(), node_id=identity.node_id,
        tls_certificate_sha256=tls_certificate_sha256)
    now = authority.canonical_now()
    f.operator.enroll_node(command(f.operator, "node.enroll", "node", f.node_id), NodeEnrollment(
        scope_id="local-scope", agent_slot_id="slot-b", observer_grant_ref=f.node.context.grant_ref,
        machine_id=identity.machine_id, boot_incarnation=identity.boot_incarnation, public_key=public_key(f.node_key),
        expires_at=now + timedelta(minutes=10)))
    request = RuntimeRegistration(node_id=f.node_id, node_binding_revision=1, provider="controlled-capacity-profile",
        producer_grant_ref=f.producer.context.grant_ref, expires_at=now + timedelta(minutes=8))
    cmd = command(f.node, "runtime.register", "runtime", RUNTIME)
    f.node.register_runtime(cmd, request, proof(f, cmd, {"request": request.model_dump(mode="json")}))
    f.operator.register_authority_transport_key(command(f.operator, "receiver.key.register", "authority_transport_key", "lifecycle-authority-key"),
        AuthorityTransportKeyRegistration(key_id="lifecycle-authority-key", revision=1, public_key=public_key(f.authority_key),
                                         expires_at=now + timedelta(minutes=7)))
    f.operator.register_receiver_connection(command(f.operator, "receiver.connection.register", "connection", CONNECTION),
        ConnectionReferenceRegistration(connection_ref=CONNECTION, revision=1, locator_host="127.0.0.1", locator_port=locator_port,
            route_class="loopback", policy_digest="a" * 64, expires_at=now + timedelta(minutes=7)))
    f.registration = None
    # Real API revisions1→3 establish transport revision independent of Core1.
    for revision in (1, 2, 3):
        register_endpoint(f, revision, expires=now + timedelta(minutes=6))
    with authority._connect() as connection:
        f.node_key_id = connection.execute("SELECT key_id FROM enrolled_node_bindings WHERE tenant_id=%s AND node_id=%s AND binding_revision=1",
                                          (authority.tenant_id, f.node_id)).fetchone()[0]
    f.recovery = ReceiverRecoveryOperations(comm.clients["a"].service)
    f.issuer = LifecycleIssuance(f.recovery, f.authority_key, journal_generation=1)
    f.secret = comm.clients["a"].credential_provider()
    return f


def register_endpoint(f, revision, *, expires=None):
    identity, context = f.endpoint.identity, f.authority.context
    registration = EndpointRegistration(registration_id="lifecycle-registration-" + str(revision), endpoint_id=RECEIVER,
        endpoint_revision=revision, connection_ref=CONNECTION, tenant_id=f.authority.tenant_id,
        authority_id=context.authority_id, authority_incarnation=context.authority_incarnation,
        node_id=f.node_id, node_binding_revision=1, runtime_id=RUNTIME, runtime_revision=1,
        machine_id=identity.machine_id, boot_incarnation=identity.boot_incarnation, scope_id="local-scope", agent_slot_id="slot-b",
        tls_certificate_sha256=f.tls_certificate_sha256, config_sha256="c" * 64,
        expires_at=expires or f.authority.canonical_now() + timedelta(minutes=5))
    signature = sign(f.node_key, registration)
    cmd = command(f.node, "endpoint.register", "endpoint", RECEIVER, revision - 1)
    signed_proof = proof(f, cmd, {"registration": registration.model_dump(mode="json"), "registration_signature": signature})
    f.node.register_receiver_endpoint(cmd, EndpointRegistrationCommand(registration=registration,
        registration_signature=signature, proof=signed_proof))
    f.registration = registration


@pytest.fixture
def registered(comm):
    return setup_graph(comm)


@pytest.fixture
def owner_graph(comm):
    return setup_graph(comm, mode="owner")


def submit(f, action="prepare_receiver"):
    with f.authority._connect() as connection:
        revision = connection.execute("SELECT revision FROM delivery_endpoints WHERE tenant_id=%s AND endpoint_id=%s",
                                      (f.authority.tenant_id, RECEIVER)).fetchone()[0]
    return f.recovery.submit(PROJECT, RECEIVER, {"action": action, "expected_revision": revision,
        "reason": "Explicit isolated lifecycle acceptance"}, "lifecycle-pg-" + uuid4().hex, f.secret)


def payload(f, operation):
    with f.authority._connect() as connection:
        return connection.execute("SELECT payload FROM outbox WHERE tenant_id=%s AND operation_id=%s AND topic=%s",
            (f.authority.tenant_id, operation["operation_id"], TOPIC)).fetchone()[0]


def fact(f, *, state="fresh", profile="d" * 64, seconds=30):
    now = f.authority.canonical_now()
    binding = BindingIdentity(f.node_id, f.endpoint.identity.boot_incarnation, RUNTIME,
                              "configured-controlled-capacity", "slot-b", 1)
    existing = state == "existing"
    session = "controlled-existing-native-session" if existing else None
    return LifecycleCapacityFact(state=state, driver_binding_id="controlled-installed-driver-binding", binding=binding,
        profile_fingerprint=profile, profile_evidence_ref="controlled:captured-profile",
        ownership="exclusive_owned" if existing else "exclusive_reserved", journal_state="clear",
        kernel_claim_ref="controlled:kernel-claim", journal_evidence_ref="controlled:journal-snapshot",
        absence_evidence_ref=None if existing else "controlled:positive-absence",
        process=OwnedProcessEvidence(pid=4321, birth_ref="controlled-owned-birth", containment_id="controlled-owned-tree",
                                    evidence_ref="controlled:owned-process") if existing else None,
        native_session_ref=session, provider_generation=native_generation("controlled-installed-driver-binding", asdict(binding), session) if session else None,
        input_state="ready" if existing else "not_started", blocker="none", observed_at=now, valid_until=now + timedelta(seconds=seconds),
        reason_code=None, evidence_refs=("controlled:captured-profile", "controlled:kernel-claim", "controlled:journal-snapshot",
                                      "controlled:owned-process" if existing else "controlled:positive-absence"))


def observe(f, issued, *, state="fresh", signer=None, profile="d" * 64):
    challenge = issued.challenge.challenge
    observed = CapacityObservation(challenge_digest=sha256(challenge), request_id=challenge.request_id, nonce=challenge.nonce,
        source_digest=sha256(challenge.source), target=challenge.target, node_key_id=challenge.target.node_key_id,
        capacity=fact(f, state=state, profile=profile))
    return sign_observation(observed, signer or f.node_key)


def issue(f, operation):
    with f.authority._connect() as connection:
        return f.issuer.issue_challenge(connection.cursor(), PROJECT, operation["operation_id"])


def plan(f, operation, *, state="fresh", issued=None, profile="d" * 64):
    issued = issued or issue(f, operation)
    signed = observe(f, issued, state=state, profile=profile)
    with f.authority._connect() as connection:
        result = f.issuer.record_observation(connection.cursor(), PROJECT, operation["operation_id"], signed)
    return issued, signed, result


def allow(f, operation):
    with f.authority._connect() as connection:
        return f.issuer.issue_permit(connection.cursor(), PROJECT, operation["operation_id"])


def snapshot(f, connection):
    return current_lifecycle_endpoint(f.authority, connection.cursor(), RECEIVER, 1, journal_generation=1)


def no_message_or_input(f):
    with f.authority._connect() as connection:
        assert tuple(connection.execute("SELECT count(*) FROM " + table).fetchone()[0] for table in
                     ("communication_messages", "delivery_messages", "delivery_attempts")) == (0, 0, 0)
    assert not any(driver.calls for driver in f.comm.drivers.values())


@pytest.mark.parametrize("action,state,native_action", [("prepare_receiver", "fresh", "spawn"), ("resume_receiver", "existing", "resume")])
def test_actual_accepted_source_to_signed_plan_and_possible_marker_visible_before_host(registered, action, state, native_action):
    f = registered
    operation = submit(f, action)
    issued, signed_observation, planned = plan(f, operation, state=state)
    assert planned.kind == "planned"
    assert issued.challenge.challenge.target.binding_epoch == 1
    assert issued.challenge.challenge.target.registration.endpoint_revision == 3
    result = allow(f, operation)
    durable = payload(f, operation)  # Independent connection after caller commit.
    assert result.kind == "permit" and result.permit.permit.plan.action == native_action
    assert durable["operation"]["state"] == "submitting" and durable["operation"]["effect_state"] == "native_possible"
    assert durable["lifecycle"]["permit_digest"] == sha256(result.permit.permit)
    assert result.permit.permit.observation_digest == sha256(signed_observation.observation)
    verify(public_key(f.authority_key), result.permit.signature, result.permit.permit)
    with f.authority._connect() as connection:
        assert require_current_execution(f.recovery, connection.cursor(), PROJECT, operation["operation_id"], result.permit,
                                         journal_generation=1) is None
    no_message_or_input(f)


def test_permit_helper_does_not_commit_parent_and_all_rows_rollback_together(registered):
    f = registered
    operation = submit(f)
    plan(f, operation)
    before = payload(f, operation)
    connection = psycopg.connect(f.dsn)
    try:
        result = f.issuer.issue_permit(connection.cursor(), PROJECT, operation["operation_id"])
        assert result.kind == "permit" and connection.info.transaction_status == TransactionStatus.INTRANS
        assert payload(f, operation) == before
        connection.rollback()
    finally:
        connection.close()
    assert payload(f, operation) == before
    no_message_or_input(f)


def test_invalid_observation_savepoint_leaves_parent_usable_and_original_challenge_intact(registered):
    f = registered
    operation = submit(f)
    issued = issue(f, operation)
    before = payload(f, operation)
    wrong = observe(f, issued, signer=SigningKey.generate())
    with f.authority._connect() as connection:
        with pytest.raises(LifecycleContractRejected, match="signature_rejected"):
            f.issuer.record_observation(connection.cursor(), PROJECT, operation["operation_id"], wrong)
        assert connection.execute("SELECT 1").fetchone() == (1,)
    assert payload(f, operation) == before


def test_real_original_grant_revocation_prevents_new_challenge(registered):
    f = registered
    operation = submit(f)
    before = payload(f, operation)
    with f.authority._connect() as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (f.authority.context.grant_ref,))
    with pytest.raises(AuthorizationDenied):
        issue(f, operation)
    assert payload(f, operation) == before


def test_actual_membership_role_change_cannot_reuse_original_manager_context(registered):
    f = registered
    operation = submit(f)
    before = payload(f, operation)
    with f.authority._connect() as connection:
        changed = connection.execute("UPDATE collaboration_memberships SET profile='engineer' WHERE tenant_id=%s "
            "AND project_id=%s AND principal_ref=%s AND profile='root_manager'",
            (f.authority.tenant_id, PROJECT, f.authority.context.principal_ref)).rowcount
    assert changed == 1, "fixture must change the actual original manager binding"
    with pytest.raises(AuthorizationDenied):
        issue(f, operation)
    assert payload(f, operation) == before


def test_real_core_binding_cas_is_independent_from_transport_registration_revision(registered):
    f = registered
    operation = submit(f)
    issue(f, operation)
    before = payload(f, operation)
    f.authority.bind_message_endpoint(command(f.authority, "message.bind", "message", RECEIVER, 1),
        EndpointBindingRequest(scope_id="local-scope", agent_slot_id="slot-b", expires_at=f.authority.canonical_now() + timedelta(minutes=5)))
    with pytest.raises(RevisionConflict):
        issue(f, operation)
    with f.authority._connect() as connection:
        assert connection.execute("SELECT endpoint_revision FROM delivery_endpoint_registrations WHERE tenant_id=%s "
            "AND endpoint_id=%s AND status='active'", (f.authority.tenant_id, RECEIVER)).fetchone() == (3,)
    assert payload(f, operation) == before


def test_actual_transport_reregistration_cannot_replace_challenge_target(registered):
    f = registered
    operation = submit(f)
    issued = issue(f, operation)
    signed = observe(f, issued)
    before = payload(f, operation)
    register_endpoint(f, 4)
    with f.authority._connect() as connection, pytest.raises(AcceptanceGuardFailed):
        f.issuer.record_observation(connection.cursor(), PROJECT, operation["operation_id"], signed)
    assert payload(f, operation) == before


@pytest.mark.parametrize("sql", [
    "UPDATE enrolled_runtimes SET revision=revision+1 WHERE runtime_id='lifecycle-runtime'",
    "UPDATE enrolled_runtimes SET status='retired' WHERE runtime_id='lifecycle-runtime'",
    "UPDATE delivery_endpoint_registrations SET config_sha256=repeat('f',64) WHERE endpoint_id='endpoint-b' AND status='active'",
    "UPDATE delivery_endpoint_registrations SET registration_signature=repeat('0',128) WHERE endpoint_id='endpoint-b' AND status='active'",
])
def test_real_pki_runtime_or_config_damage_never_issues_challenge(registered, sql):
    f = registered
    operation = submit(f)
    before = payload(f, operation)
    with f.authority._connect() as connection:
        assert connection.execute(sql).rowcount == 1
    with pytest.raises((AcceptanceGuardFailed, ValueError)):
        issue(f, operation)
    assert payload(f, operation) == before


def test_actual_node_key_rotation_invalidates_old_registered_binding(registered):
    f = registered
    operation = submit(f)
    before = payload(f, operation)
    f.operator.rotate_node(command(f.operator, "node.rotate", "node", f.node_id, 1), NodeRotation(
        machine_id=f.endpoint.identity.machine_id, boot_incarnation="rotated-current-boot",
        public_key=public_key(SigningKey.generate()), expires_at=f.authority.canonical_now() + timedelta(minutes=5)))
    with pytest.raises(AcceptanceGuardFailed):
        issue(f, operation)
    assert payload(f, operation) == before


def test_first_plan_digest_survives_expired_transport_and_rejects_new_semantics(registered):
    f = registered
    operation = submit(f)
    first, _signed, _planned = plan(f, operation)
    original = payload(f, operation)
    # Expire the transport by waiting real Authority time, never edit signed bytes.
    while f.authority.canonical_now() <= first.challenge.challenge.deadline:
        sleep(0.05)
    renewed = issue(f, operation)
    assert renewed.challenge.challenge.nonce != first.challenge.challenge.nonce
    assert payload(f, operation)["lifecycle"]["first_plan_digest"] == original["lifecycle"]["first_plan_digest"]
    changed = observe(f, renewed, profile="e" * 64)
    before = payload(f, operation)
    with f.authority._connect() as connection, pytest.raises(LifecycleIssuanceRejected, match="stable_plan_changed"):
        f.issuer.record_observation(connection.cursor(), PROJECT, operation["operation_id"], changed)
    assert payload(f, operation) == before


def test_after_possible_marker_no_new_permit_or_challenge_is_issued(registered):
    f = registered
    operation = submit(f)
    plan(f, operation)
    allowed = allow(f, operation)
    before = payload(f, operation)
    for method in (f.issuer.issue_challenge, f.issuer.issue_permit):
        with f.authority._connect() as connection:
            result = method(connection.cursor(), PROJECT, operation["operation_id"])
        assert result.kind == "readback_only" and result.challenge is result.permit is None
    assert payload(f, operation) == before and before["lifecycle"]["permit_digest"] == sha256(allowed.permit.permit)
    no_message_or_input(f)


def test_prepare_existing_ready_settles_without_a_possible_marker(registered):
    f = registered
    operation = submit(f)
    _issued, _signed, result = plan(f, operation, state="existing")
    assert result.kind == "settled" and result.operation["state"] == "completed"
    durable = payload(f, operation)
    assert durable["operation"]["effect_state"] == "committed" and durable["lifecycle"]["permit"] is None
    no_message_or_input(f)


def test_snapshot_readers_share_locks_and_writer_gets_bounded_conflict(registered):
    f = registered
    first = psycopg.connect(f.dsn)
    second = psycopg.connect(f.dsn)
    try:
        a, b = snapshot(f, first), snapshot(f, second)
        assert a.target() == b.target() and a.binding_epoch == 1 and a.binding.registration.endpoint_revision == 3
        with f.authority._connect() as writer, pytest.raises(psycopg.errors.LockNotAvailable):
            writer.execute("SELECT 1 FROM enrolled_runtimes WHERE tenant_id=%s AND runtime_id=%s FOR UPDATE NOWAIT",
                           (f.authority.tenant_id, RUNTIME))
        first.rollback()
        second.rollback()
        with f.authority._connect() as writer:
            assert writer.execute("SELECT 1 FROM enrolled_runtimes WHERE tenant_id=%s AND runtime_id=%s FOR UPDATE NOWAIT",
                                  (f.authority.tenant_id, RUNTIME)).fetchone() == (1,)
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()


@pytest.mark.parametrize("table,where,values", [
    ("delivery_endpoints", "endpoint_id=%s", (RECEIVER,)),
    ("enrolled_runtimes", "runtime_id=%s", (RUNTIME,)),
    ("authority_transport_keys", "key_id=%s", ("lifecycle-authority-key",)),
])
def test_snapshot_writer_lock_is_nowait_conflict_not_deadlock_or_unlocked_fallback(registered, table, where, values):
    f = registered
    holder = psycopg.connect(f.dsn)
    reader = psycopg.connect(f.dsn)
    try:
        holder.execute("SELECT 1 FROM " + table + " WHERE tenant_id=%s AND " + where + " FOR UPDATE", (f.authority.tenant_id, *values))
        started = monotonic()
        with pytest.raises(psycopg.errors.LockNotAvailable):
            snapshot(f, reader)
        assert monotonic() - started < 2
        reader.rollback()
        holder.rollback()
        assert snapshot(f, reader).binding_epoch == 1
    finally:
        reader.rollback()
        holder.rollback()
        reader.close()
        holder.close()


@pytest.mark.parametrize("role", ["observer", "producer"])
def test_owner_snapshot_holds_identity_grants_across_later_clock_wait(owner_graph, role, monkeypatch):
    f = owner_graph
    grant = f.node.context.grant_ref if role == "observer" else f.producer.context.grant_ref
    ready, release = Event(), Event()
    real_time = f.authority.canonical_now
    executor = ThreadPoolExecutor(max_workers=1)

    class ObservedCursor(psycopg.Cursor):
        authority_key_read = False

        def execute(self, query, params=None, **options):
            result = super().execute(query, params, **options)
            if type(query) is str and "FROM authority_transport_keys" in query and "FOR SHARE" in query:
                self.authority_key_read = True
            return result

    def final_clock(cursor=None):
        # All actual Node/observer/producer SHARE reads precede this exact outer
        # authority-key query. Pause while the reader transaction is healthy,
        # then obtain the original real SQL time; no auth or data is replaced.
        if isinstance(cursor, ObservedCursor) and cursor.authority_key_read:
            ready.set()
            assert release.wait(4), "test must release the final real clock read"
        return real_time(cursor)

    monkeypatch.setattr(f.authority, "canonical_now", final_clock)

    def reader():
        with psycopg.connect(f.dsn) as connection, ObservedCursor(connection) as cursor:
            return current_lifecycle_endpoint(f.authority, cursor, RECEIVER, 1, journal_generation=1)

    try:
        future = executor.submit(reader)
        assert ready.wait(3), "reader must reach its healthy post-Grant clock barrier"
        with f.authority._connect() as writer, pytest.raises(psycopg.errors.LockNotAvailable):
            writer.execute("SELECT 1 FROM grants WHERE tenant_id=%s AND grant_ref=%s FOR UPDATE NOWAIT", (f.authority.tenant_id, grant))
        release.set()
        assert future.result(timeout=4).binding_epoch == 1
        with f.authority._connect() as writer:
            assert writer.execute("SELECT 1 FROM grants WHERE tenant_id=%s AND grant_ref=%s FOR UPDATE NOWAIT",
                                  (f.authority.tenant_id, grant)).fetchone() == (1,)
    finally:
        release.set()
        executor.shutdown(wait=True)


@pytest.mark.parametrize("role", ["observer", "producer"])
def test_owner_snapshot_still_refuses_revoked_identity_grant(owner_graph, role):
    f = owner_graph
    grant = f.node.context.grant_ref if role == "observer" else f.producer.context.grant_ref
    with f.authority._connect() as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE tenant_id=%s AND grant_ref=%s", (f.authority.tenant_id, grant))
    with f.authority._connect() as connection, pytest.raises(AuthorizationDenied):
        snapshot(f, connection)


def test_authority_key_expiring_while_waiting_for_original_outbox_lock_is_rejected(registered):
    f = registered
    operation = submit(f)
    # Actual key-registration API installs a short lease; no signed row is edited.
    expires = f.authority.canonical_now() + timedelta(seconds=2)
    f.operator.register_authority_transport_key(command(f.operator, "receiver.key.register", "authority_transport_key", "short-lived-key", 1),
        AuthorityTransportKeyRegistration(key_id="short-lived-key", revision=2, public_key=public_key(f.authority_key), expires_at=expires))
    before = payload(f, operation)
    holder = psycopg.connect(f.dsn)
    executor = ThreadPoolExecutor(max_workers=1)
    ready, pid = Event(), []
    try:
        holder.execute("SELECT 1 FROM outbox WHERE tenant_id=%s AND operation_id=%s AND topic=%s FOR UPDATE",
                       (f.authority.tenant_id, operation["operation_id"], TOPIC))

        def worker():
            with f.authority._connect() as connection:
                pid.append(connection.execute("SELECT pg_backend_pid()").fetchone()[0])
                ready.set()
                return f.issuer.issue_challenge(connection.cursor(), PROJECT, operation["operation_id"])

        future = executor.submit(worker)
        assert ready.wait(2)
        deadline, blocked = monotonic() + 2, False
        while monotonic() < deadline:
            with f.authority._connect() as observer:
                blocked = observer.execute("SELECT wait_event_type='Lock' AND cardinality(pg_blocking_pids(pid))>0 "
                    "FROM pg_stat_activity WHERE pid=%s", (pid[0],)).fetchone()[0]
            if blocked:
                break
            sleep(0.01)
        assert blocked, "writer must reach the actual outbox row lock before expiry"
        while f.authority.canonical_now() <= expires:
            sleep(0.01)
        holder.rollback()
        with pytest.raises(AcceptanceGuardFailed):
            future.result(timeout=4)
    finally:
        holder.rollback()
        holder.close()
        executor.shutdown(wait=True)
    assert payload(f, operation) == before
    no_message_or_input(f)
