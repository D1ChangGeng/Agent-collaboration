"""Actual PG scheduling/original authority; signed Native facts are controlled.

No Native process/model/Host is contacted. Claims, expiry, revocation and each
commit before callbacks use actual independent database connections.
"""
from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event
from time import monotonic, sleep

import pytest

from runtime.communication_dispatch import maintain_communication_deliveries
from runtime.errors import AuthorizationDenied
from runtime.receiver_lifecycle_executor import LifecycleExecutorRejected
from runtime.receiver_lifecycle_maintenance import (
    advance_lifecycle_work,
    claim_lifecycle_work,
    finish_lifecycle_work,
)
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_receiver_lifecycle_executor_pg import installed
from runtime_tests.test_receiver_lifecycle_issuance_pg import (
    PROJECT,
    no_message_or_input,
    payload,
    submit,
)
from runtime_tests.test_receiver_lifecycle_issuance_pg import registered as registered_fixture

comm, registered = comm_fixture, registered_fixture


def setup(f, *, lose_ack=False):
    original = submit(f)
    _executor, calls = installed(f, original, lose_ack=lose_ack)
    service = f.recovery.projects.service
    service.authority._receiver_lifecycle_catalog = f.recovery.projects.catalog
    return original, calls, service


def test_claimed_original_continues_without_bearer_or_new_command(registered):
    f = registered
    original, calls, service = setup(f)
    [work] = claim_lifecycle_work(service.authority)
    before = payload(f, original)
    assert before["maintenance"]["owner_token"] == work.owner_token
    assert claim_lifecycle_work(service.authority) == []
    result = advance_lifecycle_work(service, work)
    assert result["state"] == "completed" and result["operation_id"] == original["operation_id"]
    assert calls == ["observe", "execute"]
    finish_lifecycle_work(service.authority, work)
    assert claim_lifecycle_work(service.authority) == []
    assert payload(f, original)["command"] == before["command"]
    no_message_or_input(f)


def test_original_issuer_revocation_prevents_background_native_admission(registered):
    f = registered
    original, calls, service = setup(f)
    [work] = claim_lifecycle_work(service.authority)
    with f.authority._connect() as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
            (f.recovery.projects.context.grant_ref,))
    with pytest.raises(AuthorizationDenied):
        advance_lifecycle_work(service, work)
    assert calls == [] and payload(f, original)["operation"]["effect_state"] == "committed"
    finish_lifecycle_work(service.authority, work)
    no_message_or_input(f)


def test_possible_effect_after_restart_only_reads_original_with_read_permission(registered):
    f = registered
    original, calls, service = setup(f, lose_ack=True)
    assert f.recovery.advance(PROJECT, original["operation_id"], f.secret)["state"] == "unknown"
    before = payload(f, original)
    assert before["lifecycle"]["phase"] == "executing"
    with f.authority._connect() as connection:
        row = connection.execute("SELECT permissions FROM grants WHERE grant_ref=%s",
            (f.recovery.projects.context.grant_ref,)).fetchone()
        assert "runtime.invoke" in row[0] and "runtime.read" in row[0]
        connection.execute("UPDATE grants SET permissions=%s WHERE grant_ref=%s",
            (json.dumps([p for p in row[0] if p != "runtime.invoke"]), f.recovery.projects.context.grant_ref))
    [work] = claim_lifecycle_work(service.authority)
    result = advance_lifecycle_work(service, work)
    assert result["state"] == "completed" and calls == ["observe", "execute", "readback"]
    after = payload(f, original)
    assert after["lifecycle"]["permit"] == before["lifecycle"]["permit"]
    assert after["command"] == before["command"]
    no_message_or_input(f)


def test_two_workers_claim_disjoint_operations_and_stale_owner_cannot_finish_successor(registered):
    f = registered
    first, calls, service = setup(f)
    second = submit(f)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(claim_lifecycle_work, service.authority, limit=1)
        b = pool.submit(claim_lifecycle_work, service.authority, limit=1)
        left, right = a.result(timeout=10), b.result(timeout=10)
    assert len(left) == len(right) == 1 and left[0].operation_ref != right[0].operation_ref
    assert {left[0].operation_ref, right[0].operation_ref} == {first["operation_id"], second["operation_id"]}
    with pytest.raises(LifecycleExecutorRejected):
        advance_lifecycle_work(service, replace(left[0], owner_token="not-the-current-owner"))
    finish_lifecycle_work(service.authority, replace(left[0], owner_token="not-the-current-owner"))
    assert payload(f, {"operation_id": left[0].operation_ref})["maintenance"]["owner_token"] == left[0].owner_token
    assert calls == []
    no_message_or_input(f)


def test_expired_lease_can_be_reclaimed_but_old_worker_never_executes(registered):
    f = registered
    original, calls, service = setup(f)
    [old] = claim_lifecycle_work(service.authority, lease_seconds=1)
    expiry = payload(f, original)["maintenance"]["not_before_us"]
    end = monotonic() + 5
    while int(f.authority.canonical_now().timestamp() * 1_000_000) <= expiry:
        assert monotonic() < end
        sleep(0.02)
    [current] = claim_lifecycle_work(service.authority)
    assert current.operation_ref == old.operation_ref and current.owner_token != old.owner_token
    with pytest.raises(LifecycleExecutorRejected):
        advance_lifecycle_work(service, old)
    finish_lifecycle_work(service.authority, old)
    assert payload(f, original)["maintenance"]["owner_token"] == current.owner_token
    assert advance_lifecycle_work(service, current)["state"] == "completed"
    assert calls == ["observe", "execute"]
    no_message_or_input(f)


def test_existing_maintenance_loop_advances_accepted_recovery_and_stops_cleanly(registered):
    f = registered
    original, calls, service = setup(f)

    async def exercise():
        task = asyncio.create_task(maintain_communication_deliveries(service))
        try:
            end = monotonic() + 20
            while True:
                row = await asyncio.to_thread(payload, f, original)
                if row["operation"]["state"] == "completed":
                    break
                assert not task.done() and monotonic() < end
                await asyncio.sleep(0.05)
            assert service.authority._receiver_lifecycle_maintenance_running is True
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert service.authority._receiver_lifecycle_maintenance_running is False

    asyncio.run(exercise())
    assert calls == ["observe", "execute"]
    no_message_or_input(f)


def test_external_dispatch_mode_does_not_automatically_admit_lifecycle(registered):
    f = registered
    original, calls, service = setup(f)
    service.authority._communication_maintenance_mode = "external"
    asyncio.run(maintain_communication_deliveries(service))
    assert calls == [] and payload(f, original)["operation"]["state"] == "queued"
    no_message_or_input(f)


def test_backoff_yields_to_another_due_operation_without_changing_original_intent(registered):
    f = registered
    original, _calls, service = setup(f)
    other = submit(f)
    [first] = claim_lifecycle_work(service.authority, limit=1)
    before = payload(f, {"operation_id": first.operation_ref})
    finish_lifecycle_work(service.authority, first)
    after = payload(f, {"operation_id": first.operation_ref})
    assert after["maintenance"]["owner_token"] is None
    assert after["maintenance"]["attempts"] == 1
    assert after["maintenance"]["not_before_us"] > int(f.authority.canonical_now().timestamp() * 1_000_000)
    assert all(after[k] == before[k] for k in ("command", "issuer_context", "request", "operation"))
    [next_work] = claim_lifecycle_work(service.authority, limit=1)
    assert next_work.operation_ref != first.operation_ref
    assert {first.operation_ref, next_work.operation_ref} == {original["operation_id"], other["operation_id"]}


def test_corrupt_due_row_is_not_executed_or_allowed_to_starve_independent_work(registered):
    f = registered
    original, calls, service = setup(f)
    other = submit(f)
    with f.authority._connect() as connection:
        connection.execute("UPDATE outbox SET payload=jsonb_set(payload,'{request,expected_revision}','\"invalid\"'::jsonb) "
            "WHERE operation_id=%s", (original["operation_id"],))
    # The first bounded scan may only encounter the corrupt oldest row. Its
    # immutable source remains intact for diagnosis; only its due time is paced.
    assert claim_lifecycle_work(service.authority, limit=1) == []
    [work] = claim_lifecycle_work(service.authority, limit=1)
    assert work.operation_ref == other["operation_id"] and calls == []
    bad = payload(f, original)
    assert bad["request"]["expected_revision"] == "invalid"
    assert bad["maintenance"]["reason_code"] == "lifecycle_scheduling_source_invalid"


def test_cancelled_loop_keeps_inflight_lease_until_thread_settles_without_replay(registered):
    f = registered
    original, calls, service = setup(f)
    entered, release, settled = Event(), Event(), Event()
    transport = service.authority._receiver_lifecycle_transports[original["receiver_ref"]]
    actual = transport.observe

    def waiting(challenge):
        entered.set()
        assert release.wait(10)
        try:
            return actual(challenge)
        finally:
            settled.set()

    transport.observe = waiting

    async def exercise():
        task = asyncio.create_task(maintain_communication_deliveries(service))
        try:
            assert await asyncio.to_thread(entered.wait, 10)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            retained = await asyncio.to_thread(payload, f, original)
            assert retained["maintenance"]["owner_token"] is not None
            assert await asyncio.to_thread(claim_lifecycle_work, service.authority) == []
        finally:
            release.set()
            assert await asyncio.to_thread(settled.wait, 10)
        # The already-running thread may record its real original result. The
        # cancelled scheduler must not release its lease early or start again.
        end = monotonic() + 10
        while (await asyncio.to_thread(payload, f, original))["operation"]["state"] != "completed":
            assert monotonic() < end
            await asyncio.sleep(0.05)

    asyncio.run(exercise())
    assert calls == ["observe", "execute"]
    no_message_or_input(f)
