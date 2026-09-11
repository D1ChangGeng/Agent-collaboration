"""Lease/fence PostgreSQL tests. ACS_P1_DSN is required; every case owns a schema."""
from __future__ import annotations

import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from runtime.domain import DomainAuthority
from runtime.errors import (
    AuthorizationDenied,
    FencingRejected,
    IdempotencyConflict,
    LeaseRejected,
    RevisionConflict,
)
from runtime.models import CommandEnvelope, LeaseRequest

PERMISSIONS = ("lease.acquire", "lease.renew", "lease.release", "lease.revoke", "lease.inspect", "effect.write", "effect.read")


@pytest.fixture
def authority():
    base = os.environ.get("ACS_P1_DSN")
    if not base:
        pytest.skip("ACS_P1_DSN absent; real PostgreSQL not measured")
    name = "lease_test_" + uuid.uuid4().hex
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
    dsn = make_conninfo(base, application_name=name,
                       options=f"-csearch_path={name} -cstatement_timeout=12000 -clock_timeout=10000")
    try:
        domain = DomainAuthority(dsn)
        domain.initialize()
        domain.bootstrap_local_grant(PERMISSIONS)
        execute(domain, "INSERT INTO work_items(work_item_id,tenant_id,scope_id,agent_slot_id,state,source_baseline,created_by) "
                "VALUES ('w-1',%s,'local-scope','local-slot','candidate','baseline',%s)",
                (domain.tenant_id, domain.context.principal_ref))
        execute(domain, "INSERT INTO attempts(attempt_id,tenant_id,work_item_id,agent_slot_id,status,producer_ref,"
                "runtime_id,scope_id,grant_ref,authority_id,authority_incarnation) "
                "VALUES ('a-1',%s,'w-1','local-slot','running',%s,'runtime-1','local-scope',%s,%s,%s)",
                (domain.tenant_id, domain.context.principal_ref, domain.context.grant_ref,
                 domain.context.authority_id, domain.context.authority_incarnation))
        yield domain
    finally:
        with psycopg.connect(base, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))


def execute(domain, statement, params=()):
    with domain._connect() as conn:
        cursor = conn.execute(statement, params)
        return cursor.fetchall() if cursor.description else []


def counts(domain):
    return tuple(execute(domain, f"SELECT count(*) FROM {table}")[0][0]
                 for table in ("command_dedup", "domain_events", "operations", "outbox"))


def command(domain, operation="acquire", resource="resource-1", **changes):
    now = datetime.now(UTC)
    value = {"command_id": f"cmd-{uuid.uuid4()}", "idempotency_key": f"key-{uuid.uuid4()}",
                 "command_type": f"lease.{operation}", "correlation_id": "lease-test",
                 "tenant_id": domain.tenant_id, "authority_id": domain.context.authority_id,
                 "authority_incarnation": domain.context.authority_incarnation,
                 "principal_ref": domain.context.principal_ref, "grant_ref": domain.context.grant_ref,
                 "target_kind": "lease", "target_id": resource, "expected_revision": 0,
                 "issued_at": now - timedelta(seconds=1), "deadline": now + timedelta(minutes=5)}
    value.update(changes)
    return CommandEnvelope(**value)


def request(domain, resource="resource-1", ttl=300, **changes):
    value = {"resource_id": resource, "owner_attempt_id": "a-1", "owner_runtime_id": "runtime-1",
                 "grant_ref": domain.context.grant_ref, "authority_incarnation": domain.context.authority_incarnation,
                 "scope_id": "local-scope", "work_item_id": "w-1", "ttl_seconds": ttl}
    value.update(changes)
    return LeaseRequest(**value)


def acquire(domain, ttl=300):
    cmd, req = command(domain), request(domain, ttl=ttl)
    return domain.leases.acquire_lease(cmd, req), cmd, req


def fence_args(domain, result):
    return {"lease_id": result["lease_id"], "resource_id": result["resource_id"],
                "generation": result["generation"], "fencing_token": result["fencing_token"],
                "caller": domain.context, "attempt_id": "a-1", "runtime_id": "runtime-1",
                "scope_id": "local-scope", "grant_ref": domain.context.grant_ref,
                "authority_incarnation": domain.context.authority_incarnation}


def lifecycle(domain, result, operation, cmd=None, ttl=300):
    cmd = cmd or command(domain, operation)
    kwargs = {"command": cmd, "lease_id": result["lease_id"], "resource_id": result["resource_id"],
                  "generation": result["generation"], "fencing_token": result["fencing_token"]}
    if operation == "renew":
        kwargs["ttl_seconds"] = ttl
    return getattr(domain.leases, operation + "_lease")(**kwargs)


def wait_for_resource_wait(domain, future):
    application = conninfo_to_dict(domain._dsn)["application_name"]
    until = time.monotonic() + 4
    while time.monotonic() < until:
        if future.done():
            pytest.fail(f"operation completed inside held fence: {future.result()}")
        waiting = execute(domain, "SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a ON a.pid=l.pid "
                          "WHERE a.application_name=%s AND l.locktype='advisory' AND NOT l.granted", (application,))
        if waiting[0][0]:
            return
        time.sleep(0.02)
    pytest.fail("operation did not reach the resource advisory-lock wait")


def wait_past_expiry(result):
    duration = (result["expires_at"] - datetime.now(UTC)).total_seconds() + 0.1
    if duration > 0:
        time.sleep(duration)


def test_acquire_uses_current_canonical_ledger_and_replays_original_snapshot(authority):
    result, cmd, req = acquire(authority)
    lifecycle(authority, result, "release")
    execute(authority, "UPDATE attempts SET status='completed'")
    repeated = authority.leases.acquire_lease(cmd, req)
    assert repeated["duplicate"] and repeated["status"] == "granted"
    assert repeated["expires_at"] == result["expires_at"] and repeated["operation_id"] == result["operation_id"]
    digest = cmd.canonical_hash({"operation": "acquire", "request": req.model_dump(mode="json")})
    assert execute(authority, "SELECT payload_hash,canonical_hash,hash_version,migration_state FROM command_dedup "
                   "WHERE command_id=%s", (cmd.command_id,)) == [(digest, digest, "v2", "current")]
    assert execute(authority, "SELECT canonical_hash FROM domain_events WHERE command_id=%s", (cmd.command_id,)) == [(digest,)]
    assert counts(authority) == (2, 2, 2, 2)


def test_duplicate_renew_does_not_extend_expiry(authority):
    result, _, _ = acquire(authority)
    cmd = command(authority, "renew")
    renewed = lifecycle(authority, result, "renew", cmd, ttl=450)
    time.sleep(0.02)
    repeated = lifecycle(authority, result, "renew", cmd, ttl=450)
    assert repeated["duplicate"] and repeated["expires_at"] == renewed["expires_at"]
    assert execute(authority, "SELECT expires_at FROM leases") == [(renewed["expires_at"],)]
    with pytest.raises(IdempotencyConflict):
        lifecycle(authority, result, "renew", cmd, ttl=451)
    assert counts(authority) == (2, 2, 2, 2)


@pytest.mark.parametrize("operation", ["release", "revoke"])
def test_terminal_lifecycle_replays_before_state_owner_and_revision(authority, operation):
    result, _, _ = acquire(authority)
    cmd = command(authority, operation)
    first = lifecycle(authority, result, operation, cmd)
    execute(authority, "UPDATE attempts SET status='completed'")
    execute(authority, "UPDATE work_items SET revision=8")
    repeated = lifecycle(authority, result, operation, cmd)
    assert repeated["duplicate"] and repeated["operation_id"] == first["operation_id"]
    assert repeated["status"] == first["status"]
    assert counts(authority) == (2, 2, 2, 2)
    execute(authority, "UPDATE grants SET revoked_at=now()")
    with pytest.raises(AuthorizationDenied):
        lifecycle(authority, result, operation, cmd)
    assert counts(authority) == (2, 2, 2, 2)


@pytest.mark.parametrize("field", ["runtime_id", "producer_ref", "scope_id", "grant_ref", "authority_id", "authority_incarnation"])
def test_acquire_never_repairs_missing_owner_registration(authority, field):
    execute(authority, f"UPDATE attempts SET {field}=NULL")
    with pytest.raises(LeaseRejected, match="owner registration is incomplete"):
        acquire(authority)
    assert execute(authority, f"SELECT {field} FROM attempts") == [(None,)]
    assert counts(authority) == (0, 0, 0, 0)


@pytest.mark.parametrize("change", ["runtime_id", "producer_ref", "scope_id", "grant_ref", "authority_id", "authority_incarnation", "slot", "work_item_slot", "attempt_status"])
def test_fence_rechecks_full_registered_owner_and_slot(authority, change):
    result, _, _ = acquire(authority)
    if change == "slot":
        execute(authority, "UPDATE agent_slots SET status='revoked'")
    elif change == "work_item_slot":
        execute(authority, "UPDATE work_items SET agent_slot_id='different-slot'")
    elif change == "attempt_status":
        execute(authority, "UPDATE attempts SET status='completed'")
    else:
        execute(authority, f"UPDATE attempts SET {change}='mismatch'")
    with pytest.raises(FencingRejected):
        authority.leases.verify_fence(**fence_args(authority, result))
    assert counts(authority) == (1, 1, 1, 1)


def test_fence_requires_explicit_owner_tuple_and_current_caller_grant(authority):
    result, _, _ = acquire(authority)
    args = fence_args(authority, result)
    args["runtime_id"] = None
    with pytest.raises(FencingRejected):
        authority.leases.verify_fence(**args)
    args = fence_args(authority, result)
    args["caller"] = replace(authority.context, grant_ref="other-grant")
    with pytest.raises(FencingRejected):
        authority.leases.verify_fence(**args)
    assert counts(authority) == (1, 1, 1, 1)


def test_new_commands_check_registered_work_item_revision(authority):
    result, _, _ = acquire(authority)
    execute(authority, "UPDATE work_items SET revision=3")
    with pytest.raises(RevisionConflict) as caught:
        lifecycle(authority, result, "renew")
    assert (caught.value.expected, caught.value.actual) == (0, 3)
    assert counts(authority) == (1, 1, 1, 1)


@pytest.mark.parametrize("mutation", [{"command_type": "work_item.create"}, {"target_kind": "effect"}, {"target_id": "other"}])
def test_command_envelope_is_bound_to_method_and_resource(authority, mutation):
    with pytest.raises(LeaseRejected, match="command type or target"):
        authority.leases.acquire_lease(command(authority, **mutation), request(authority))
    assert counts(authority) == (0, 0, 0, 0)


@pytest.mark.parametrize("claim", ["legacy_command_id", "snapshot_column", "snapshot_result"])
def test_quarantined_historical_identity_claim_blocks_acquire(authority, claim):
    retained, original = "other-legacy", {"command_id": "other-column", "result_json": {"command_id": "other-result"}}
    if claim == "legacy_command_id":
        retained = "occupied"
    elif claim == "snapshot_column":
        original["command_id"] = "occupied"
    else:
        original["result_json"]["command_id"] = "occupied"
    execute(authority, "INSERT INTO command_dedup(tenant_id,idempotency_key,payload_hash,migration_state,replay_policy,"
            "legacy_command_id,legacy_record,result_json) VALUES (%s,'old-key',%s,'quarantined','quarantine',%s,%s,'{}')",
            (authority.tenant_id, "a"*64, retained, json.dumps(original)))
    with pytest.raises(IdempotencyConflict):
        authority.leases.acquire_lease(command(authority, command_id="occupied"), request(authority))
    assert counts(authority) == (1, 0, 0, 0)
    assert execute(authority, "SELECT count(*) FROM leases") == [(0,)]


def test_multiple_matching_rows_cannot_hide_historical_claim(authority):
    _result, cmd, req = acquire(authority)
    execute(authority, "INSERT INTO command_dedup(tenant_id,idempotency_key,payload_hash,migration_state,replay_policy,"
            "legacy_command_id,result_json) VALUES (%s,'old-key',%s,'quarantined','quarantine',%s,'{}')",
            (authority.tenant_id, "a"*64, cmd.command_id))
    with pytest.raises(IdempotencyConflict):
        authority.leases.acquire_lease(cmd, req)
    assert counts(authority) == (2, 1, 1, 1)


def test_no_fast_acquire_replay_after_ledger_is_quarantined(authority):
    _, cmd, req = acquire(authority)
    execute(authority, "UPDATE command_dedup SET migration_state='quarantined',replay_policy='quarantine'")
    with pytest.raises(IdempotencyConflict):
        authority.leases.acquire_lease(cmd, req)
    assert counts(authority) == (1, 1, 1, 1)


def test_same_command_different_keys_and_resources_race_has_one_commit(authority):
    barrier = Barrier(2)
    commands = [command(authority, resource=f"resource-{i}", command_id="same-command") for i in range(2)]
    def submit(index):
        barrier.wait(timeout=3)
        try:
            return authority.leases.acquire_lease(commands[index], request(authority, resource=f"resource-{index}"))
        except IdempotencyConflict as error:
            return error
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, (0, 1)))
    assert sum(isinstance(value, dict) for value in results) == 1
    assert sum(isinstance(value, IdempotencyConflict) for value in results) == 1
    assert counts(authority) == (1, 1, 1, 1)
    assert execute(authority, "SELECT count(*) FROM leases") == [(1,)]


def reader(domain, permissions=("effect.read",)):
    other = DomainAuthority(domain._dsn, replace(domain.context, principal_ref="reader", grant_ref="grant:reader"))
    other.bootstrap_local_grant(permissions)
    return other


def history_args(domain, result):
    return {"lease_id": result["lease_id"], "resource_id": result["resource_id"], "generation": result["generation"],
                "fencing_token": result["fencing_token"], "caller": domain.context, "scope_id": "local-scope",
                "grant_ref": domain.context.grant_ref, "authority_incarnation": domain.context.authority_incarnation}


def test_historical_read_after_release_uses_independent_effect_read(authority):
    result, _, _ = acquire(authority)
    lifecycle(authority, result, "release")
    read_domain = reader(authority)
    read_domain.leases.verify_historical_readback(**history_args(read_domain, result))
    with pytest.raises(FencingRejected):
        read_domain.leases.verify_fence(**fence_args(read_domain, result))
    assert counts(authority) == (2, 2, 2, 2)


@pytest.mark.parametrize("change", ["grant_argument", "scope", "old_authority", "no_permission", "legacy_permission"])
def test_historical_read_cannot_mix_scope_grant_or_authority(authority, change):
    result, _, _ = acquire(authority)
    lifecycle(authority, result, "release")
    read_domain = reader(authority, ("effect.readback",) if change == "legacy_permission" else () if change == "no_permission" else ("effect.read",))
    args = history_args(read_domain, result)
    if change == "grant_argument":
        args["grant_ref"] = authority.context.grant_ref
    elif change == "scope":
        execute(authority, "INSERT INTO scopes(scope_id,tenant_id,policy,status) VALUES ('other-scope',%s,'{}','active')",
                (authority.tenant_id,))
        execute(authority, "UPDATE grants SET scope_id='other-scope' WHERE grant_ref='grant:reader'")
        args["scope_id"] = "other-scope"
    elif change == "old_authority":
        execute(authority, "UPDATE leases SET authority_incarnation='old-incarnation'")
    with pytest.raises(FencingRejected):
        read_domain.leases.verify_historical_readback(**args)
    assert counts(authority) == (2, 2, 2, 2)


@pytest.mark.parametrize("operation", ["release", "revoke"])
def test_lifecycle_waits_for_held_fence(authority, operation):
    result, _, _ = acquire(authority)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with authority.leases.hold_fence(**fence_args(authority, result)) as fence:
            future = pool.submit(lifecycle, authority, result, operation)
            wait_for_resource_wait(authority, future)
            fence["check_current"]()
            assert not future.done()
        assert future.result(timeout=5)["status"] == ("released" if operation == "release" else "revoked")
    with pytest.raises(FencingRejected):
        fence["check_current"]()
    assert counts(authority) == (2, 2, 2, 2)


def test_expire_waits_for_held_fence_and_is_idempotent(authority):
    result, _, _ = acquire(authority, ttl=1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with authority.leases.hold_fence(**fence_args(authority, result)) as fence:
            wait_past_expiry(result)
            with pytest.raises(FencingRejected):
                fence["check_current"]()
            future = pool.submit(authority.leases.expire_leases)
            wait_for_resource_wait(authority, future)
        assert future.result(timeout=5) == 1
    assert authority.leases.expire_leases() == 0
    assert counts(authority) == (2, 2, 2, 2)
    assert execute(authority, "SELECT lineage_mode FROM domain_events WHERE to_state='lease.expired'") == [("deterministic_recovery",)]
    expiry = execute(authority, "SELECT result_json,canonical_hash FROM command_dedup WHERE command_id LIKE %s",
                     ("lease-expiry-%",))[0]
    assert expiry[0]["status"] == "expired"
    assert execute(authority, "SELECT canonical_hash FROM domain_events WHERE to_state='lease.expired'") == [(expiry[1],)]


def test_new_generation_cannot_overlap_old_owner_critical_section(authority):
    result, _, _ = acquire(authority, ttl=1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with authority.leases.hold_fence(**fence_args(authority, result)) as fence:
            wait_past_expiry(result)
            future = pool.submit(authority.leases.acquire_lease, command(authority), request(authority))
            wait_for_resource_wait(authority, future)
            with pytest.raises(FencingRejected):
                fence["check_current"]()
        successor = future.result(timeout=5)
    assert successor["generation"] == result["generation"] + 1
    assert successor["expired_lease_ids"] == [result["lease_id"]]
    with pytest.raises(FencingRejected):
        authority.leases.verify_fence(**fence_args(authority, result))
    authority.leases.verify_fence(**fence_args(authority, successor))
    assert counts(authority) == (2, 2, 2, 2)


def test_renewed_expiry_is_not_closed_by_old_timer(authority):
    result, _, _ = acquire(authority, ttl=1)
    renewed = lifecycle(authority, result, "renew", ttl=30)
    wait_past_expiry(result)
    assert authority.leases.expire_leases() == 0
    assert execute(authority, "SELECT status,expires_at FROM leases") == [("granted", renewed["expires_at"])]
    assert counts(authority) == (2, 2, 2, 2)


def test_expiry_recovers_recorded_lease_after_owner_grant_revocation(authority):
    result, _cmd, _ = acquire(authority, ttl=1)
    execute(authority, "UPDATE grants SET revoked_at=now()")
    wait_past_expiry(result)
    assert authority.leases.expire_leases() == 1
    assert authority.leases.expire_leases() == 0
    assert counts(authority) == (2, 2, 2, 2)
    event = execute(authority, "SELECT initiated_by,lineage_mode FROM domain_events WHERE to_state='lease.expired'")[0]
    assert event == ("runtime:lease-expiry", "deterministic_recovery")


def test_fence_exposes_registered_work_item_and_authority(authority):
    result, _, _ = acquire(authority)
    with authority.leases.hold_fence(**fence_args(authority, result)) as fence:
        assert fence["work_item_id"] == "w-1"
        assert fence["authority_id"] == authority.context.authority_id
        assert fence["authority_incarnation"] == authority.context.authority_incarnation
        assert fence["producer_ref"] == authority.context.principal_ref
        fence["check_current"]()
    assert counts(authority) == (1, 1, 1, 1)


def test_inspect_requires_own_current_grant(authority):
    result, _, _ = acquire(authority)
    inspected = authority.leases.inspect_lease(result["lease_id"])
    assert inspected["owner_attempt_id"] == "a-1" and inspected["generation"] == result["generation"]
    other = reader(authority, ("lease.inspect",))
    with pytest.raises(FencingRejected):
        other.leases.inspect_lease(result["lease_id"])
    assert counts(authority) == (1, 1, 1, 1)


def rollover_reader(domain, permissions=("effect.read",)):
    """Fixture-only operator rollover preserving the historical authority row."""
    with domain._connect() as connection:
        connection.execute("UPDATE authority_instances SET status='revoked' WHERE authority_id=%s",
                           (domain.context.authority_id,))
        connection.execute("INSERT INTO authority_instances(authority_id,authority_incarnation,status) "
                           "VALUES (%s,'rolled-2','active')", (domain.context.authority_id,))
    successor = DomainAuthority(domain._dsn, replace(domain.context, authority_incarnation="rolled-2",
                                                    principal_ref="reader:new", grant_ref="grant:reader-new"))
    successor.bootstrap_local_grant(permissions)
    return successor


def test_rollover_current_reader_can_read_old_lease_and_old_owner_cannot_write(authority):
    result, _, _ = acquire(authority)
    successor = rollover_reader(authority)
    successor.leases.verify_historical_readback(**history_args(successor, result))
    assert execute(authority, "SELECT authority_incarnation,status FROM leases") == [
        (authority.context.authority_incarnation, "granted")]
    with pytest.raises(FencingRejected):
        authority.leases.verify_fence(**fence_args(authority, result))
    with (
        pytest.raises(FencingRejected),
        authority.leases.hold_fence(**fence_args(authority, result)),
    ):
        pytest.fail("retired authority entered a protected write")
    with pytest.raises(FencingRejected):
        successor.leases.verify_fence(**fence_args(successor, result))
    assert counts(authority) == (1, 1, 1, 1)


@pytest.mark.parametrize("change", ["missing_read_permission", "unknown_old_incarnation", "different_logical_authority", "stale_reader_argument"])
def test_rollover_read_remains_bound_to_current_permission_and_registered_history(authority, change):
    result, _, _ = acquire(authority)
    successor = rollover_reader(authority, () if change == "missing_read_permission" else ("effect.read",))
    args = history_args(successor, result)
    if change == "unknown_old_incarnation":
        execute(authority, "UPDATE leases SET authority_incarnation='not-registered'")
    elif change == "different_logical_authority":
        execute(authority, "UPDATE leases SET authority_id='other-logical-authority'")
    elif change == "stale_reader_argument":
        args["authority_incarnation"] = authority.context.authority_incarnation
    with pytest.raises(FencingRejected):
        successor.leases.verify_historical_readback(**args)
    assert counts(authority) == (1, 1, 1, 1)


def test_shared_historical_verification_uses_outer_transaction_without_resource_inversion(authority, monkeypatch):
    result, _, _ = acquire(authority)
    lease_authority = authority.leases
    resource_held = Event()
    writer_finished = Event()
    def waiting_writer():
        with authority._connect() as connection, connection.cursor() as cursor:
            lease_authority._resource_lock(cursor, result["resource_id"])
            resource_held.set()
            authority._authorize(command(authority, "renew"), cursor, "lease.renew", "local-scope")
        writer_finished.set()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with authority._connect() as connection, connection.cursor() as cursor:
            authority._authorize(command(authority, "inspect"), cursor, "effect.read", "local-scope")
            cursor.execute("SELECT work_item_id FROM work_items WHERE work_item_id='w-1' FOR UPDATE")
            lease_authority._lease_row(cursor, result["lease_id"], result["resource_id"])
            future = pool.submit(waiting_writer)
            assert resource_held.wait(3), "writer never acquired the resource lock"
            # Writer now holds the resource lock and needs the outer Grant.
            # Shared read must use the outer cursor and never request that lock.
            def forbidden(*args, **kwargs):
                pytest.fail("shared verification opened a connection or reacquired resource lock")
            with monkeypatch.context() as patch:
                patch.setattr(authority, "_connect", forbidden)
                patch.setattr(lease_authority, "_resource_lock", forbidden)
                lease_authority.verify_historical_readback_in_transaction(cursor, **history_args(authority, result))
            assert not writer_finished.is_set()
        future.result(timeout=5)
    assert writer_finished.is_set()
    assert counts(authority) == (1, 1, 1, 1)


def test_shared_historical_verification_rechecks_uncommitted_current_authorization(authority):
    result, _, _ = acquire(authority)
    lease_authority = authority.leases
    with authority._connect() as connection, connection.cursor() as cursor:
        authority._authorize(command(authority, "inspect"), cursor, "effect.read", "local-scope")
        cursor.execute("SELECT work_item_id FROM work_items WHERE work_item_id='w-1' FOR UPDATE")
        lease_authority._lease_row(cursor, result["lease_id"], result["resource_id"])
        cursor.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                       (authority.context.grant_ref,))
        with pytest.raises(FencingRejected):
            lease_authority.verify_historical_readback_in_transaction(cursor, **history_args(authority, result))
    assert counts(authority) == (1, 1, 1, 1)

