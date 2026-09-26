"""Real Domain registration, PostgreSQL LeaseAuthority and Linux Gateway tests.

The production Domain initialization adopts the registration schema. This suite reuses only the initial trusted evidence fixture; all
Effect rows are created by authenticated Domain.register_effect calls.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import psycopg
import pytest
from psycopg import sql

from runtime.effects import LocalFileEffectGateway
from runtime.errors import (
    AcceptanceGuardFailed,
    AuthorizationDenied,
    EffectUnavailable,
    IdempotencyConflict,
    RevisionConflict,
)
from runtime.models import EffectReadback, LeaseRequest, WorkItemState
from runtime_tests import test_domain_evidence as suite

runtime = suite.runtime


def lease_command(domain, operation):
    return suite.command(domain, f"lease.{operation}", 1).model_copy(
        update={"target_kind": "lease", "target_id": "publication-resource"})


def owner_args(domain, lease):
    return {"lease_id": lease["lease_id"], "resource_id": lease["resource_id"],
                "generation": lease["generation"], "fencing_token": lease["fencing_token"],
                "caller": domain.context, "attempt_id": "attempt-1", "runtime_id": "runtime-1",
                "scope_id": "local-scope", "grant_ref": domain.context.grant_ref,
                "authority_incarnation": domain.context.authority_incarnation}


@pytest.fixture
def publication(runtime, tmp_path):
    f = runtime
    with psycopg.connect(f.dsn) as conn:
        engineer_permissions = conn.execute(
            "SELECT permissions FROM grants WHERE grant_ref=%s", (f.engineer.context.grant_ref,)).fetchone()[0]
        finalizer_permissions = conn.execute(
            "SELECT permissions FROM grants WHERE grant_ref=%s", (f.finalizer.context.grant_ref,)).fetchone()[0]
    f.engineer.bootstrap_local_grant(tuple(set(engineer_permissions) | {"effect.register", "effect.read"}))
    f.finalizer.bootstrap_local_grant(tuple(set(finalizer_permissions) | {"effect.read", "effect.register"}))
    suite.register(f)
    suite.review(f)
    suite.transition(f, WorkItemState.ACCEPTANCE_READY, 0)
    lease = f.engineer.leases.acquire_lease(lease_command(f.engineer, "acquire"), LeaseRequest(
        resource_id="publication-resource", owner_attempt_id="attempt-1", owner_runtime_id="runtime-1",
        scope_id="local-scope", work_item_id="work", grant_ref=f.engineer.context.grant_ref,
        authority_incarnation=f.engineer.context.authority_incarnation, ttl_seconds=300))
    root = tmp_path / "publication"
    with (
        LocalFileEffectGateway(f.engineer.leases, root, scope_id="local-scope",
                               resource_paths={"publication-resource": "output.txt"}) as writer,
        LocalFileEffectGateway(f.finalizer.leases, root, scope_id="local-scope",
                               resource_paths={"publication-resource": "output.txt"}) as observer,
    ):
        f.engineer._effect_registration_gateway = writer
        f.finalizer._effect_registration_gateway = observer
        observed_proofs = []
        transaction_ids = []
        def verifier(cursor, context, effect):
            cursor.execute("SET LOCAL lock_timeout='1s'")
            transaction_ids.append(cursor.execute("SELECT txid_current()").fetchone()[0])
            observed = observer.historical_readback_in_transaction(
                cursor, lease_id=effect["lease_id"], resource_id=effect["resource_id"],
                generation=effect["generation"], fencing_token=effect["fencing_token"],
                readback_ref=effect["readback_ref"], caller=context, scope_id=effect["scope_id"],
                grant_ref=context.grant_ref, authority_incarnation=context.authority_incarnation,
                expected_operation_id=effect["operation_id"])
            proof = {key: observed[key] for key in EffectReadback.model_fields
                     if key not in ("effect_id", "work_item_id")}
            proof.update(effect_id=effect["effect_id"], work_item_id=effect["work_item_id"])
            observed_proofs.append(proof)
            return proof
        f.finalizer._effect_readback_verifier = verifier
        yield SimpleNamespace(f=f, lease=lease, root=root, writer=writer, observer=observer,
                              proofs=observed_proofs, transactions=transaction_ids,
                              input={"effect_id": "publication-1", "lease_id": lease["lease_id"],
                                         "resource_id": "publication-resource", "readback_ref": "output.txt",
                                         "operation_id": "real-publication-operation"})


def write(p, payload=None):
    return p.writer.write(**owner_args(p.f.engineer, p.lease), relative_path="output.txt",
                          payload=p.f.store.read(p.f.output) if payload is None else payload,
                          operation_id=p.input["operation_id"])


def register(p, cmd=None, **changes):
    return p.f.engineer.register_effect(cmd or suite.command(p.f.engineer, "effect.register", 1),
                                       **(p.input | changes))


def release(p):
    return p.f.engineer.leases.release_lease(
        command=lease_command(p.f.engineer, "release"), lease_id=p.lease["lease_id"],
        resource_id=p.lease["resource_id"], generation=p.lease["generation"],
        fencing_token=p.lease["fencing_token"])


def effect_row(p):
    with psycopg.connect(p.f.dsn) as conn:
        return conn.execute(
            "SELECT status,candidate_ref,operation_id,expected_sha256,expected_size_bytes,intent_sha256,"
            "completion_sha256,completion_state,registered_readback,registered_by,registration_command_id,"
            "registration_operation_id,registration_event_id FROM effects WHERE effect_id='publication-1'").fetchone()


def test_authenticated_registration_replaces_fixture_enrollment_and_accepts(publication):
    p = publication
    write(p)
    cmd = suite.command(p.f.engineer, "effect.register", 1)
    result = register(p, cmd)
    row = effect_row(p)
    assert row[0:5] == ("verified", p.f.receipt.candidate_ref, p.input["operation_id"],
                        p.f.output.sha256, p.f.output.size_bytes)
    assert row[6] and row[7] == "completed"
    assert row[8]["intent_sha256"] == row[5] and row[8]["completion_sha256"] == row[6]
    assert row[9:12] == (p.f.engineer.context.principal_ref, cmd.command_id, result.operation_id)
    assert row[12] and result.operation_id != p.input["operation_id"]
    assert release(p)["status"] == "released"
    accepted = suite.transition(p.f, WorkItemState.ACCEPTED, 1,
                                effects=("publication-1",), readbacks=("output.txt",))
    assert accepted.revision == 2
    with psycopg.connect(p.f.dsn) as conn:
        ready_digest = conn.execute("SELECT readback_digest FROM accepted_state_revisions WHERE readiness_snapshot").fetchone()[0]
        final = conn.execute("SELECT readback_digest,xmin::text::bigint FROM accepted_state_revisions WHERE NOT readiness_snapshot").fetchone()
        assert conn.execute("SELECT count(*) FROM effects").fetchone()[0] == 1
    expected = hashlib.sha256(json.dumps({"source_readback_digest": ready_digest, "effects": p.proofs},
                                        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert final == (expected, p.transactions[0] % (2 ** 32))
    assert p.proofs[0]["completion_sha256"] == row[6]


def test_actual_prepared_readback_registers_uncertain_and_cannot_accept(publication, monkeypatch):
    p = publication
    original = p.writer._record
    def crash(parent, name, body, check, **kwargs):
        if name.endswith(".completed"):
            raise OSError("injected completion publication crash")
        return original(parent, name, body, check, **kwargs)
    with monkeypatch.context() as failure:
        failure.setattr(p.writer, "_record", crash)
        with pytest.raises(EffectUnavailable, match="injected completion"):
            write(p)
    assert (p.root / "output.txt").read_bytes() == p.f.store.read(p.f.output)
    cmd = suite.command(p.f.engineer, "effect.register", 1)
    registered = register(p, cmd)
    row = effect_row(p)
    assert row[0] == "uncertain" and row[6] is None and row[7] == "prepared"
    before = suite.counts(p.f)
    repeated = register(p, cmd)
    assert repeated.duplicate and repeated.operation_id == registered.operation_id
    with pytest.raises(AcceptanceGuardFailed, match="every protected effect must be verified"):
        suite.transition(p.f, WorkItemState.ACCEPTED, 1,
                         effects=("publication-1",), readbacks=("output.txt",))
    assert suite.counts(p.f) == before


@pytest.mark.parametrize("field,value,reason", [
    ("lease_id", "forged-lease", "publication lease owner binding is missing or unauthorized"),
    ("resource_id", "forged-resource", "publication lease owner binding is missing or unauthorized"),
    ("operation_id", "forged-operation", "publication Gateway readback failed"),
    ("readback_ref", "forged-output.txt", "publication Gateway readback failed"),
])
def test_caller_cannot_substitute_execution_identity(publication, field, value, reason):
    p = publication
    write(p)
    before = suite.counts(p.f)
    with pytest.raises(AcceptanceGuardFailed, match=reason):
        register(p, **{field: value})
    assert effect_row(p) is None and suite.counts(p.f) == before


def test_request_has_no_digest_or_completion_override(publication):
    p = publication
    write(p)
    before = suite.counts(p.f)
    with pytest.raises(TypeError, match="sha256"):
        register(p, sha256="a" * 64)
    assert effect_row(p) is None and suite.counts(p.f) == before


def test_actual_wrong_output_is_not_the_ready_candidate(publication):
    p = publication
    write(p, payload=b"different actual protected bytes")
    before = suite.counts(p.f)
    with pytest.raises(AcceptanceGuardFailed, match="publication bytes do not match the ready candidate"):
        register(p)
    assert effect_row(p) is None and suite.counts(p.f) == before


def test_valid_registration_permission_does_not_impersonate_lease_owner(publication):
    p = publication
    write(p)
    before = suite.counts(p.f)
    with pytest.raises(AcceptanceGuardFailed, match="publication lease owner binding is missing or unauthorized"):
        p.f.finalizer.register_effect(suite.command(p.f.finalizer, "effect.register", 1), **p.input)
    assert effect_row(p) is None and suite.counts(p.f) == before


@pytest.mark.parametrize("permission", ["effect.register", "effect.read"])
def test_both_current_permissions_are_required(publication, permission):
    p = publication
    write(p)
    with psycopg.connect(p.f.dsn) as conn:
        conn.execute("UPDATE grants SET permissions=permissions-%s WHERE grant_ref=%s",
                     (permission, p.f.engineer.context.grant_ref))
    before = suite.counts(p.f)
    with pytest.raises(AuthorizationDenied):
        register(p)
    assert effect_row(p) is None and suite.counts(p.f) == before


def test_replay_conflict_revocation_and_accepted_freeze(publication):
    p = publication
    write(p)
    cmd = suite.command(p.f.engineer, "effect.register", 1)
    original = register(p, cmd)
    before = suite.counts(p.f)
    assert register(p, cmd).duplicate
    with pytest.raises(IdempotencyConflict):
        register(p, cmd, operation_id="different-operation")
    with pytest.raises(AcceptanceGuardFailed, match="publication effect identity is already registered"):
        register(p)
    assert suite.counts(p.f) == before
    release(p)
    suite.transition(p.f, WorkItemState.ACCEPTED, 1, effects=("publication-1",), readbacks=("output.txt",))
    before = suite.counts(p.f)
    replay = register(p, cmd)
    assert replay.duplicate and replay.operation_id == original.operation_id
    with pytest.raises(AcceptanceGuardFailed, match="effect registration requires an acceptance-ready work item"):
        register(p, suite.command(p.f.engineer, "effect.register", 2), effect_id="new-effect")
    assert suite.counts(p.f) == before
    with psycopg.connect(p.f.dsn) as conn:
        conn.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                     (p.f.engineer.context.grant_ref,))
    with pytest.raises(AuthorizationDenied):
        register(p, cmd)
    assert suite.counts(p.f) == before


@pytest.mark.parametrize("change", [{"command_type": "effect.write"}, {"target_kind": "effect"}])
def test_registration_command_type_and_target_are_explicit(publication, change):
    p = publication
    before = suite.counts(p.f)
    cmd = suite.command(p.f.engineer, "effect.register", 1).model_copy(update=change)
    with pytest.raises(AuthorizationDenied):
        register(p, cmd)
    assert suite.counts(p.f) == before


def test_registration_expected_revision_is_enforced(publication):
    p = publication
    before = suite.counts(p.f)
    with pytest.raises(RevisionConflict):
        register(p, suite.command(p.f.engineer, "effect.register", 0))
    assert suite.counts(p.f) == before


def prepare_actual_effect(p, monkeypatch):
    record = p.writer._record
    def crash(parent, name, body, check, **kwargs):
        if name.endswith(".completed"):
            raise OSError("injected completion publication crash")
        return record(parent, name, body, check, **kwargs)
    with monkeypatch.context() as failure:
        failure.setattr(p.writer, "_record", crash)
        with pytest.raises(EffectUnavailable, match="injected completion"):
            write(p)
    original_command = suite.command(p.f.engineer, "effect.register", 1)
    original_result = register(p, original_command)
    assert effect_row(p)[0] == "uncertain"
    return original_command, original_result


def reconcile(p, cmd=None, effect_id="publication-1"):
    return p.f.engineer.reconcile_effect(
        cmd or suite.command(p.f.engineer, "effect.reconcile", 1), effect_id=effect_id)


def test_real_resume_explicit_reconciliation_and_acceptance(publication, monkeypatch):
    p = publication
    register_command, register_result = prepare_actual_effect(p, monkeypatch)
    initial = effect_row(p)
    prepared_command = suite.command(p.f.engineer, "effect.reconcile", 1)
    reconcile(p, prepared_command)
    assert effect_row(p)[0] == "uncertain"
    assert effect_row(p)[8] == initial[8]
    resumed = p.writer.resume(**owner_args(p.f.engineer, p.lease), relative_path="output.txt",
                              operation_id=p.input["operation_id"])
    assert resumed["sha256"] == p.f.output.sha256
    completed_command = suite.command(p.f.engineer, "effect.reconcile", 1)
    completed_result = reconcile(p, completed_command)
    completed = effect_row(p)
    assert completed[0] == "verified" and completed[7] == "completed" and completed[6]
    assert completed[1:6] == initial[1:6]
    assert completed[8:] == initial[8:]  # Original registration proof/lineage is preserved.
    with psycopg.connect(p.f.dsn) as conn:
        audit = conn.execute(
            "SELECT reconciled_readback,reconciliation_command_id,reconciliation_operation_id,"
            "reconciliation_event_id FROM effects WHERE effect_id='publication-1'").fetchone()
        attempts = conn.execute("SELECT count(*) FROM attempts").fetchone()[0]
    assert audit[0]["completion_sha256"] == completed[6]
    assert audit[1:3] == (completed_command.command_id, completed_result.operation_id)
    assert audit[3] and completed_result.operation_id != register_result.operation_id
    assert attempts == 1  # Reconciliation did not create an execution Attempt.
    before = suite.counts(p.f)
    assert reconcile(p, prepared_command).duplicate
    assert reconcile(p, completed_command).duplicate
    assert suite.counts(p.f) == before
    release(p)
    suite.transition(p.f, WorkItemState.ACCEPTED, 1, effects=("publication-1",), readbacks=("output.txt",))
    before = suite.counts(p.f)
    assert register(p, register_command).duplicate
    assert reconcile(p, completed_command).duplicate
    with pytest.raises(AcceptanceGuardFailed, match="effect reconciliation requires an acceptance-ready work item"):
        reconcile(p, suite.command(p.f.engineer, "effect.reconcile", 2))
    with pytest.raises(IdempotencyConflict):
        reconcile(p, completed_command, effect_id="different-effect")
    assert suite.counts(p.f) == before


def test_reconciliation_requires_current_authorization_even_for_replay(publication, monkeypatch):
    p = publication
    prepare_actual_effect(p, monkeypatch)
    cmd = suite.command(p.f.engineer, "effect.reconcile", 1)
    reconcile(p, cmd)
    with psycopg.connect(p.f.dsn) as conn:
        conn.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                     (p.f.engineer.context.grant_ref,))
    before = suite.counts(p.f)
    with pytest.raises(AuthorizationDenied):
        reconcile(p, cmd)
    assert suite.counts(p.f) == before


@pytest.mark.parametrize("field,value", [
    ("candidate_ref", "changed-candidate"),
    ("intent_sha256", "d" * 64),
    ("expected_sha256", "e" * 64),
    ("operation_id", "forged-operation"),
    ("readback_ref", "moved-output.txt"),
])
def test_registered_identity_and_intent_are_immutable(publication, monkeypatch, field, value):
    p = publication
    prepare_actual_effect(p, monkeypatch)
    # Corruption probe: the command API offers no identity/digest override fields.
    before = suite.counts(p.f)
    with psycopg.connect(p.f.dsn) as conn:
        original = conn.execute("SELECT to_jsonb(e) FROM effects e WHERE effect_id='publication-1'").fetchone()[0]
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="registered effect identity and original proof are immutable"),
        psycopg.connect(p.f.dsn) as conn,
    ):
        conn.execute(sql.SQL("UPDATE effects SET {}=%s WHERE effect_id='publication-1'").format(
            sql.Identifier(field)), (value,))
    with psycopg.connect(p.f.dsn) as conn:
        assert conn.execute("SELECT to_jsonb(e) FROM effects e WHERE effect_id='publication-1'").fetchone()[0] == original
    assert suite.counts(p.f) == before


def test_reconciliation_command_identity_revision_and_uncertain_precondition(publication):
    p = publication
    write(p)
    register(p)
    before = suite.counts(p.f)
    with pytest.raises(AcceptanceGuardFailed, match="effect reconciliation requires an uncertain registered effect"):
        reconcile(p)
    with pytest.raises(RevisionConflict):
        reconcile(p, suite.command(p.f.engineer, "effect.reconcile", 0))
    with pytest.raises(AuthorizationDenied):
        reconcile(p, suite.command(p.f.engineer, "effect.register", 1))
    with pytest.raises(AuthorizationDenied):
        reconcile(p, suite.command(p.f.engineer, "effect.reconcile", 1).model_copy(update={"target_kind": "effect"}))
    with pytest.raises(TypeError, match="operation_id"):
        p.f.engineer.reconcile_effect(suite.command(p.f.engineer, "effect.reconcile", 1),
                                     effect_id="publication-1", operation_id="forged")
    assert suite.counts(p.f) == before


def test_revoked_publication_owner_new_lease_resume_reconcile_and_accept(runtime, tmp_path, monkeypatch):
    f = runtime
    with psycopg.connect(f.dsn) as conn:
        permissions = conn.execute("SELECT permissions FROM grants WHERE grant_ref=%s",
                                   (f.finalizer.context.grant_ref,)).fetchone()[0]
    f.finalizer.bootstrap_local_grant(tuple(set(permissions) | {"effect.read"}))
    suite.register(f)
    suite.review(f)
    suite.transition(f, WorkItemState.ACCEPTANCE_READY, 0)

    def publisher(name):
        context = replace(f.engineer.context, principal_ref=f"publisher:{name}", grant_ref=f"grant:publisher:{name}")
        domain = type(f.engineer)(f.dsn, context=context, artifact_store=f.store)
        domain.bootstrap_local_grant(("lease.acquire", "lease.release", "effect.write", "effect.register", "effect.read"))
        # Explicit endpoint provisioning for two publication producers, separate
        # from the preexisting candidate evidence producer and its trusted Grant.
        with psycopg.connect(f.dsn) as conn:
            conn.execute(
                "INSERT INTO attempts(attempt_id,tenant_id,work_item_id,agent_slot_id,status,producer_ref,"
                "runtime_id,scope_id,grant_ref,authority_id,authority_incarnation) VALUES "
                "(%s,%s,'work','local-slot','running',%s,%s,'local-scope',%s,%s,%s)",
                (f"publication-attempt-{name}", domain.tenant_id, context.principal_ref,
                 f"publication-runtime-{name}", context.grant_ref, context.authority_id, context.authority_incarnation))
        return domain

    old, new = publisher("old"), publisher("new")
    resource = "handoff-resource"
    operation = "handoff-publication-operation"

    def lease_cmd(domain, action):
        return suite.command(domain, f"lease.{action}", 1).model_copy(
            update={"target_kind": "lease", "target_id": resource})

    def acquire(domain, name):
        return domain.leases.acquire_lease(lease_cmd(domain, "acquire"), LeaseRequest(
            resource_id=resource, owner_attempt_id=f"publication-attempt-{name}",
            owner_runtime_id=f"publication-runtime-{name}", scope_id="local-scope", work_item_id="work",
            grant_ref=domain.context.grant_ref, authority_incarnation=domain.context.authority_incarnation,
            ttl_seconds=300))

    def owned(domain, lease, name):
        return {"lease_id": lease["lease_id"], "resource_id": resource, "generation": lease["generation"],
                    "fencing_token": lease["fencing_token"], "caller": domain.context,
                    "attempt_id": f"publication-attempt-{name}", "runtime_id": f"publication-runtime-{name}",
                    "scope_id": "local-scope", "grant_ref": domain.context.grant_ref,
                    "authority_incarnation": domain.context.authority_incarnation}

    original_lease = acquire(old, "old")
    root = tmp_path / "owner-handoff"
    with (
        LocalFileEffectGateway(old.leases, root, scope_id="local-scope", resource_paths={resource: "output.txt"}) as writer,
        LocalFileEffectGateway(new.leases, root, scope_id="local-scope", resource_paths={resource: "output.txt"}) as recovery,
        LocalFileEffectGateway(f.finalizer.leases, root, scope_id="local-scope", resource_paths={resource: "output.txt"}) as observer,
    ):
        old._effect_registration_gateway = writer
        new._effect_registration_gateway = recovery
        record = writer._record
        def crash(parent, name, body, check, **kwargs):
            if name.endswith(".completed"):
                raise OSError("injected original publisher completion crash")
            return record(parent, name, body, check, **kwargs)
        with monkeypatch.context() as failure:
            failure.setattr(writer, "_record", crash)
            with pytest.raises(EffectUnavailable, match="injected original publisher"):
                writer.write(**owned(old, original_lease, "old"), relative_path="output.txt",
                             payload=f.store.read(f.output), operation_id=operation)
        registration_command = suite.command(old, "effect.register", 1)
        old.register_effect(registration_command, effect_id="handoff-effect", lease_id=original_lease["lease_id"],
                            resource_id=resource, readback_ref="output.txt", operation_id=operation)
        old.leases.release_lease(command=lease_cmd(old, "release"), lease_id=original_lease["lease_id"],
                                 resource_id=resource, generation=original_lease["generation"],
                                 fencing_token=original_lease["fencing_token"])
        with psycopg.connect(f.dsn) as conn:
            conn.execute("UPDATE grants SET revoked_at=clock_timestamp(),expires_at=clock_timestamp()-interval '1 minute' "
                         "WHERE grant_ref=%s", (old.context.grant_ref,))
            assert conn.execute("SELECT revoked_at FROM grants WHERE grant_ref=%s",
                                (f.engineer.context.grant_ref,)).fetchone()[0] is None
        replacement = acquire(new, "new")
        assert replacement["generation"] == original_lease["generation"] + 1
        recovery.resume(**owned(new, replacement, "new"), relative_path="output.txt", operation_id=operation)
        reconciliation_command = suite.command(new, "effect.reconcile", 1)
        reconciled = new.reconcile_effect(reconciliation_command, effect_id="handoff-effect")
        with psycopg.connect(f.dsn) as conn:
            effect = conn.execute(
                "SELECT status,lease_id,grant_ref,operation_id,registered_by,registration_command_id,"
                "reconciliation_command_id FROM effects WHERE effect_id='handoff-effect'").fetchone()
            assert effect == ("verified", original_lease["lease_id"], old.context.grant_ref, operation,
                              old.context.principal_ref, registration_command.command_id, reconciliation_command.command_id)
            assert conn.execute("SELECT initiated_by FROM domain_events WHERE command_id=%s",
                                (reconciliation_command.command_id,)).fetchone()[0] == new.context.principal_ref
        key = hashlib.sha256(operation.encode()).hexdigest()
        records = root / writer.MARKER_DIR / "operations"
        intent = json.loads((records / (key + ".intent")).read_bytes())["body"]
        completed = json.loads((records / (key + ".completed")).read_bytes())["body"]
        assert intent["lease_id"] == original_lease["lease_id"]
        assert intent["owner"]["grant_ref"] == old.context.grant_ref
        assert completed["completed_by"]["lease_id"] == replacement["lease_id"]
        assert completed["completed_by"]["owner"]["grant_ref"] == new.context.grant_ref

        def verifier(cursor, context, effect):
            cursor.execute("SET LOCAL lock_timeout='1s'")
            observed = observer.historical_readback_in_transaction(
                cursor, lease_id=effect["lease_id"], resource_id=effect["resource_id"],
                generation=effect["generation"], fencing_token=effect["fencing_token"],
                readback_ref=effect["readback_ref"], caller=context, scope_id=effect["scope_id"],
                grant_ref=context.grant_ref, authority_incarnation=context.authority_incarnation,
                expected_operation_id=effect["operation_id"])
            return {**{key: observed[key] for key in EffectReadback.model_fields
                       if key not in ("effect_id", "work_item_id")},
                    "effect_id": effect["effect_id"], "work_item_id": effect["work_item_id"]}
        f.finalizer._effect_readback_verifier = verifier
        accepted = suite.transition(f, WorkItemState.ACCEPTED, 1,
                                    effects=("handoff-effect",), readbacks=("output.txt",))
        assert accepted.state == "accepted"
        assert new.reconcile_effect(reconciliation_command, effect_id="handoff-effect").operation_id == reconciled.operation_id
