"""Read-only Native capability boundaries with real Drivers and isolated PostgreSQL.

Driver peers are explicitly synthetic. PostgreSQL tests use actual enrollment,
delivery attempts and revocation through the normal isolated comm fixture; they
do not establish model or production-host qualification.
"""
from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from runtime.codex_driver import AuthorizedObservation, AuthorizedOperation, DriverRejected
from runtime.delivery_models import InvocationRequest
from runtime.delivery_node import invocation_for
from runtime.errors import AcceptanceGuardFailed, AuthorizationDenied
from runtime_deployment.receiver_authority import (
    NativeReceiverAuthority,
    NativeReceiverRejected,
    bind_registered_receiver,
)
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send
from runtime_tests.test_receiver_evidence_native import receiver as receiver_fixture
from runtime_tests.test_receiver_opencode_factory import enrolled_opencode_config

comm = comm_fixture
receiver = receiver_fixture


def observation(name="fixture-observer"):
    return AuthorizedObservation(name, "fixture-observer-command", "fixture-observer-message",
                                 "fixture-observer-grant", None)


def journal_counts(driver):
    with driver.journal._connect() as connection:
        return (connection.execute("SELECT count(*) FROM driver_operations").fetchone()[0],
                connection.execute("SELECT count(*) FROM driver_events").fetchone()[0])


def test_observer_capability_retains_original_dataclass_serialization():
    ordinary = AuthorizedOperation("operation", "command", "message", "grant", None)
    readonly = AuthorizedObservation("operation", "command", "message", "grant", None)
    assert ordinary.read_only is False and readonly.read_only is True
    assert asdict(ordinary) == asdict(readonly)
    assert set(asdict(readonly)) == {"operation_id", "command_id", "message_id", "grant_ref", "deadline"}


@pytest.mark.parametrize("action", ["spawn", "attach", "invoke", "resume", "cancel", "terminate", "unknown-action"])
def test_all_driver_run_actions_reject_observation_before_journal_or_io(receiver, action):
    _module, state, _adapter, _binding = receiver
    driver = state.driver
    before = journal_counts(driver)
    with pytest.raises(DriverRejected, match="read-only"):
        driver._run(observation(), action, {}, lambda: pytest.fail("observer reached mutation body"))
    assert journal_counts(driver) == before


@pytest.mark.parametrize("action", ["invoke", "resume", "cancel", "terminate"])
def test_public_driver_mutations_cannot_spend_observer_authority(receiver, action):
    _module, state, _adapter, _binding = receiver
    driver = state.driver
    before = journal_counts(driver)
    observe = observation()
    with pytest.raises(DriverRejected, match="read-only"):
        if action == "invoke":
            driver.invoke(observe, "observer cannot submit this text")
        elif action == "cancel":
            driver.cancel(observe, "turn-target" if driver.harness == "codex" else "msg_synthetic-target")
        else:
            getattr(driver, action)(observe)
    assert journal_counts(driver) == before


def test_observer_can_read_existing_native_context_without_mutations(receiver):
    _module, state, _adapter, _binding = receiver
    driver = state.driver
    with driver.journal._connect() as connection:
        before = connection.execute("SELECT count(*) FROM driver_operations").fetchone()[0]
    view = driver.inspect(observation())
    if driver.harness == "codex":
        assert view["thread"]["id"] == driver.thread_id
        assert state.state["turn_calls"] == 0
    else:
        assert view["session"]["id"] == driver.session_id
        assert not any(path.endswith("/prompt_async") for _, path, _ in state.peer.requests)
    with driver.journal._connect() as connection:
        assert connection.execute("SELECT count(*) FROM driver_operations").fetchone()[0] == before


def original_invocation(comm, recipient="b"):
    submitted = send(comm, to=recipient)["data"]
    result = comm.dispatcher.dispatch({"tenant_id": comm.authority.tenant_id,
        "message_id": submitted["message_id"], "operation_id": submitted["operation_id"]})
    assert result["status"] == "delivered", result
    with comm.authority._connect() as connection:
        row = connection.execute("SELECT invocation_json FROM delivery_attempts WHERE tenant_id=%s AND message_id=%s",
                                 (comm.authority.tenant_id, submitted["message_id"])).fetchone()
    assert row is not None and row[0] is not None
    return InvocationRequest.model_validate_json(json.dumps(row[0]), strict=True)


@pytest.fixture
def enrolled_observer(comm, tmp_path):
    config, settings, authority = enrolled_opencode_config(comm, tmp_path)
    capacity = object.__new__(NativeReceiverAuthority)
    capacity.authority = authority
    capacity.binding = bind_registered_receiver(authority, config.binding.registration, "c" * 64,
        settings["runtime_id"], settings["capacity_attempt_id"])
    capacity.config = config

    def require_before(deadline):
        # The authority decisions and expiries are real PG facts. This test-only
        # clock supplies the current canonical PG UTC, not connection calibration.
        if authority.canonical_now() >= deadline:
            raise ValueError("observer admission expired")

    capacity.clock = SimpleNamespace(require_before=require_before)
    return capacity


def test_pg_current_enrolled_receiver_observes_its_original_attempt(comm, enrolled_observer):
    invocation = original_invocation(comm)
    capacity = enrolled_observer
    result = capacity._authorize_observation(invocation, capacity.binding)
    assert isinstance(result, AuthorizedObservation) and result.read_only
    assert result.operation_id == "native-observation:" + invocation.invocation_id
    assert result.command_id == invocation.command_id and result.message_id == invocation.message_id
    assert result.grant_ref == capacity.authority.context.grant_ref and result.deadline is None
    assert capacity._observation_current(result) == invocation


def test_pg_observer_read_does_not_inherit_original_senders_revocation(comm, enrolled_observer):
    invocation = original_invocation(comm)
    with comm.authority._connect() as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                           (comm.authority.context.grant_ref,))
    capacity = enrolled_observer
    result = capacity._authorize_observation(invocation, capacity.binding)
    assert result.deadline is None and capacity._observation_current(result) == invocation
    assert len(comm.drivers["b"].calls) == 1  # Only fixture setup delivery; no new input on observation.


def test_pg_foreign_receiving_slot_and_changed_binding_are_rejected(comm, enrolled_observer):
    foreign = original_invocation(comm, "c")
    capacity = enrolled_observer
    with pytest.raises(NativeReceiverRejected, match="another receiving Slot"):
        capacity._authorize_observation(foreign, capacity.binding)
    own = original_invocation(comm)
    with pytest.raises(NativeReceiverRejected, match="binding changed"):
        capacity._authorize_observation(own, replace(capacity.binding, agent_slot_id="slot-c"))


@pytest.mark.parametrize("revoked", ["runtime", "node", "observer_grant"])
def test_pg_observer_authority_tracks_live_enrollment_revocation(comm, enrolled_observer, revoked):
    invocation = original_invocation(comm)
    capacity = enrolled_observer
    capability = capacity._authorize_observation(invocation, capacity.binding)
    with capacity.authority._connect() as connection:
        if revoked == "runtime":
            connection.execute("UPDATE enrolled_runtimes SET status='revoked' WHERE runtime_id=%s", (capacity.binding.runtime_id,))
        elif revoked == "node":
            connection.execute("UPDATE enrolled_nodes SET status='revoked' WHERE node_id=%s", (capacity.binding.node_id,))
        else:
            connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (capability.grant_ref,))
    with pytest.raises((AcceptanceGuardFailed, AuthorizationDenied)):
        capacity._observation_current(capability)


def test_pg_forged_observer_capability_and_changed_original_input_are_rejected(comm, enrolled_observer):
    invocation = original_invocation(comm)
    capacity = enrolled_observer
    good = capacity._authorize_observation(invocation, capacity.binding)
    for forged in (AuthorizedOperation(**asdict(good)), replace(good, grant_ref="another-observer"),
                   replace(good, operation_id="delivery-invocation:not-an-observer")):
        with pytest.raises(NativeReceiverRejected, match="capability differs"):
            capacity._observation_current(forged)
    changed = invocation.model_copy(update={"selection_digest": "b" * 64})
    with pytest.raises(NativeReceiverRejected, match="original invocation"):
        capacity._authorize_observation(changed, capacity.binding)


def test_observer_can_reference_expired_business_deadline_in_controlled_authority_fixture(receiver):
    # The PG cases above measure enrollment authorization. This separate cursor
    # fixture isolates business-deadline independence without sleeping or editing
    # an already committed real message packet.
    from contextlib import contextmanager

    from runtime_tests.test_native_handoff import delivery

    _state, _adapter, original = delivery(receiver)
    packet = original.envelope.packet.model_copy(update={"deadline": datetime.now(UTC) - timedelta(seconds=5)})
    historical = invocation_for(original.envelope.model_copy(update={"packet": packet}), original.attempt_id)

    class Cursor:
        def execute(self, _statement, _params):
            return None

        def fetchone(self):
            return (historical.model_dump(mode="json"),)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    @contextmanager
    def connection():
        yield SimpleNamespace(cursor=Cursor)

    capacity = object.__new__(NativeReceiverAuthority)
    capacity.binding = SimpleNamespace(runtime_id="runtime", agent_slot_id=packet.target_agent_slot_id)
    capacity.authority = SimpleNamespace(tenant_id="tenant", context=SimpleNamespace(principal_ref="observer", grant_ref="observer-grant"),
        _connect=connection, enrollment=SimpleNamespace(_active_runtime=lambda *_args: (
            {"observer_ref": "observer", "observer_grant_ref": "observer-grant", "scope_id": packet.target_scope_id},
            None, None, None, None)))
    result = capacity._authorize_observation(historical, capacity.binding)
    assert isinstance(result, AuthorizedObservation) and result.deadline is None
