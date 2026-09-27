"""Real PostgreSQL Domain + LeaseAuthority + Linux Gateway acceptance boundary.

Run with the assembled runtime and runtime_tests.test_domain_evidence available,
and ACS_P1_DSN set. The imported fixture owns an isolated PostgreSQL schema and
real Linux CAS. Initial Node/Attempt receipt admission remains explicitly seeded
by that fixture. Lease acquisition, fencing, file publication, historical read
authorization, readback and Domain acceptance are real implementations.

There is no authenticated Domain effect-registration command yet. The narrow
registration helper below performs real effect.write authorization and derives
candidate/lease identity from locked database rows; it inserts the observed
Gateway facts as fixture enrollment. It is not production registration code.
"""

from __future__ import annotations

import hashlib
import json
import sys

import psycopg
import pytest

from runtime.effects import LocalFileEffectGateway
from runtime.errors import AcceptanceGuardFailed, EffectUnavailable
from runtime.lease_authority import LeaseAuthority
from runtime.models import EffectReadback, LeaseRequest, WorkItemState
from runtime_tests import test_domain_evidence as evidence_suite

runtime = evidence_suite.runtime
pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="requires real Linux CAS/Gateway backend"
)


def lease_command(domain, operation):
    return evidence_suite.command(domain, f"lease.{operation}", 1).model_copy(
        update={"target_kind": "lease", "target_id": "publication-resource"}
    )


def owner_args(domain, lease):
    return {
        "lease_id": lease["lease_id"], "resource_id": lease["resource_id"],
        "generation": lease["generation"], "fencing_token": lease["fencing_token"],
        "caller": domain.context, "attempt_id": "attempt-1", "runtime_id": "runtime-1",
        "scope_id": "local-scope", "grant_ref": domain.context.grant_ref,
        "authority_incarnation": domain.context.authority_incarnation,
    }


def observer_args(domain, lease):
    return {
        key: value for key, value in owner_args(domain, lease).items()
        if key not in ("attempt_id", "runtime_id")
    }


def enroll_gateway_observation(f, lease, observed):
    """Explicit fixture enrollment; every authorization call below is real.

    The deliberately claimed verified status also exercises the negative case:
    a prepared actual readback must be rejected despite this database label.
    """
    cmd = evidence_suite.command(f.engineer, "effect.write", 1)
    with f.engineer._connect() as connection, connection.cursor() as cursor:
        f.engineer._authorize(cmd, cursor, "effect.write", "local-scope")
        cursor.execute(
            "SELECT revision FROM work_items WHERE tenant_id=%s AND work_item_id='work' FOR UPDATE",
            (f.engineer.tenant_id,),
        )
        assert cursor.fetchone() == (1,)
        cursor.execute(
            "INSERT INTO effects(effect_id,tenant_id,work_item_id,resource_id,baseline_ref,lease_id,"
            "fencing_token,generation,status,readback_ref,grant_ref,candidate_ref,operation_id,"
            "expected_sha256,expected_size_bytes,intent_sha256) "
            "SELECT 'publication-1',w.tenant_id,w.work_item_id,l.resource_id,w.source_baseline,l.lease_id,"
            "l.fencing_token,l.generation,'verified',%s,l.grant_ref,r.candidate_ref,%s,%s,%s,%s "
            "FROM leases l JOIN work_items w ON w.tenant_id=l.tenant_id AND w.work_item_id='work' "
            "JOIN accepted_state_revisions r ON r.tenant_id=w.tenant_id AND r.work_item_id=w.work_item_id "
            "AND r.revision=w.revision AND r.readiness_snapshot=TRUE "
            "WHERE l.lease_id=%s AND l.tenant_id=%s AND l.grant_ref=%s "
            "AND l.owner_attempt_id='attempt-1' AND l.owner_runtime_id='runtime-1' "
            "AND l.scope_id=w.scope_id AND w.state='acceptance_ready'",
            (observed["readback_ref"], observed["operation_id"], observed["sha256"],
             observed["size_bytes"], observed["intent_sha256"], lease["lease_id"],
             f.engineer.tenant_id, f.engineer.context.grant_ref),
        )
        assert cursor.rowcount == 1


@pytest.mark.parametrize("completion", ["completed", "prepared"])
def test_real_ready_publication_historical_callback_and_acceptance(runtime, tmp_path, monkeypatch, completion):
    f = runtime
    # Local test provisioning creates real current Grants, not stub verifiers.
    f.finalizer.bootstrap_local_grant((
        "work_item.transition", "acceptance.finalize", "review.assign", "work_item.read", "effect.read",
    ))
    evidence_suite.register(f)
    evidence_suite.review(f)
    evidence_suite.transition(f, WorkItemState.ACCEPTANCE_READY, 0)
    with psycopg.connect(f.dsn) as conn:
        ready = conn.execute(
            "SELECT effect_refs,readback_refs,readback_digest FROM accepted_state_revisions WHERE readiness_snapshot"
        ).fetchone()
        assert ready[:2] == ([], [])
        assert conn.execute("SELECT count(*) FROM effects").fetchone()[0] == 0

    assert isinstance(f.engineer.leases, LeaseAuthority)
    assert isinstance(f.finalizer.leases, LeaseAuthority)
    lease = f.engineer.leases.acquire_lease(lease_command(f.engineer, "acquire"), LeaseRequest(
        resource_id="publication-resource", owner_attempt_id="attempt-1", owner_runtime_id="runtime-1",
        scope_id="local-scope", work_item_id="work", grant_ref=f.engineer.context.grant_ref,
        authority_incarnation=f.engineer.context.authority_incarnation, ttl_seconds=300,
    ))
    payload = f.store.read(f.output)
    root = tmp_path / "protected-publication"
    operation = "actual-gateway-publication"
    observations = []
    callback_transactions = []
    with (
        LocalFileEffectGateway(f.engineer.leases, root, scope_id="local-scope",
                               resource_paths={"publication-resource": "output.txt"}) as writer,
        LocalFileEffectGateway(f.finalizer.leases, root, scope_id="local-scope",
                               resource_paths={"publication-resource": "output.txt"}) as observer,
    ):
        if completion == "completed":
            written = writer.write(**owner_args(f.engineer, lease), relative_path="output.txt",
                                   payload=payload, operation_id=operation)
            assert written["sha256"] == f.output.sha256
        else:
            record = writer._record
            def crash_before_completion_record(parent, name, body, check, **kwargs):
                if name.endswith(".completed"):
                    raise OSError("injected crash after actual file readback before completion publication")
                return record(parent, name, body, check, **kwargs)
            # Filesystem crash injection only; real LeaseAuthority authorization
            # runs unchanged before, during and after the actual replacement.
            with monkeypatch.context() as crash:
                crash.setattr(writer, "_record", crash_before_completion_record)
                with pytest.raises(EffectUnavailable, match="injected crash"):
                    writer.write(**owner_args(f.engineer, lease), relative_path="output.txt",
                                 payload=payload, operation_id=operation)
        assert (root / "output.txt").read_bytes() == payload
        first_observation = observer.historical_readback(
            **observer_args(f.finalizer, lease), readback_ref="output.txt", expected_operation_id=operation,
        )
        assert first_observation["completion_state"] == completion
        assert first_observation["sha256"] == hashlib.sha256(payload).hexdigest()
        assert first_observation["size_bytes"] == len(payload)
        enroll_gateway_observation(f, lease, first_observation)
        released = f.engineer.leases.release_lease(
            command=lease_command(f.engineer, "release"), lease_id=lease["lease_id"],
            resource_id=lease["resource_id"], generation=lease["generation"], fencing_token=lease["fencing_token"],
        )
        assert released["status"] == "released"

        def actual_gateway_callback(cursor, context, effect):
            assert context == f.finalizer.context
            assert cursor.connection.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS
            cursor.execute("SET LOCAL lock_timeout='1s'")
            callback_transactions.append(cursor.execute("SELECT txid_current()").fetchone()[0])
            observed = observer.historical_readback_in_transaction(
                cursor, lease_id=effect["lease_id"], resource_id=effect["resource_id"],
                generation=effect["generation"], fencing_token=effect["fencing_token"],
                readback_ref=effect["readback_ref"], caller=context, scope_id=effect["scope_id"],
                grant_ref=context.grant_ref, authority_incarnation=context.authority_incarnation,
                expected_operation_id=effect["operation_id"],
            )
            # Keep all real proof fields intact. Only Domain-owned parent IDs
            # are added; prepared observations stay prepared and are rejected.
            proof = {key: observed[key] for key in EffectReadback.model_fields
                     if key not in ("effect_id", "work_item_id")}
            proof.update(effect_id=effect["effect_id"], work_item_id=effect["work_item_id"])
            observations.append(proof)
            return proof

        f.finalizer._effect_readback_verifier = actual_gateway_callback
        before = evidence_suite.counts(f)
        if completion == "prepared":
            with pytest.raises(AcceptanceGuardFailed, match="live effect readback is invalid"):
                evidence_suite.transition(f, WorkItemState.ACCEPTED, 1,
                                          effects=("publication-1",), readbacks=("output.txt",))
            assert evidence_suite.counts(f) == before
            assert observations[0]["completion_state"] == "prepared"
            assert observations[0]["completion_sha256"] is None
            with psycopg.connect(f.dsn) as conn:
                assert conn.execute("SELECT state,revision FROM work_items WHERE work_item_id='work'").fetchone() == ("acceptance_ready", 1)
        else:
            result = evidence_suite.transition(f, WorkItemState.ACCEPTED, 1,
                                               effects=("publication-1",), readbacks=("output.txt",))
            assert result.state == "accepted" and result.revision == 2
            expected_digest = hashlib.sha256(json.dumps(
                {"source_readback_digest": ready[2], "effects": observations},
                sort_keys=True, separators=(",", ":"),
            ).encode()).hexdigest()
            with psycopg.connect(f.dsn) as conn:
                accepted = conn.execute(
                    "SELECT effect_refs,readback_refs,readback_digest,xmin::text::bigint "
                    "FROM accepted_state_revisions WHERE NOT readiness_snapshot"
                ).fetchone()
            assert accepted[:3] == (["publication-1"], ["output.txt"], expected_digest)
            assert accepted[3] == callback_transactions[0] % (2 ** 32)
            assert observations[0]["completion_state"] == "completed"
            assert observations[0]["completion_sha256"] == first_observation["completion_sha256"]
        assert len(observations) == len(callback_transactions) == 1
