"""Actual Core transactions/issuer/executor with controlled signed Node facts.

No Native process, model, Host or socket is created. This is E2 metadata and
commit-boundary acceptance, not an installed Receiver qualification.
"""
from __future__ import annotations

import os
from dataclasses import asdict
from datetime import timedelta
from types import SimpleNamespace

import pytest

from runtime.codex_driver import BindingIdentity
from runtime.errors import AuthorizationDenied
from runtime.receiver_config import ReceiverClientConfig
from runtime.receiver_contract import native_generation
from runtime.receiver_crypto import key_fingerprint, sha256
from runtime.receiver_lifecycle_contract import LifecycleReceipt, sign_observation, sign_receipt
from runtime.receiver_lifecycle_executor import ReceiverLifecycleExecutor
from runtime.receiver_recovery_operations import TOPIC
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_receiver_lifecycle_issuance_pg import (
    PROJECT,
    RECEIVER,
    no_message_or_input,
    observe,
    payload,
    plan,
    snapshot,
    submit,
)
from runtime_tests.test_receiver_lifecycle_issuance_pg import registered as registered_fixture

comm = comm_fixture
registered = registered_fixture


@pytest.mark.parametrize("retained_history", [False, True])
def test_actual_enrollment_authorizes_only_new_private_namespace_without_retained_core_plan(registered, tmp_path, retained_history):
    from runtime.receiver_lifecycle_capacity import CapacityEvidenceUnavailable
    from runtime_deployment.receiver_lifecycle import _namespace_authority, lifecycle_journal
    from runtime_tests.probe_receiver_windows_backend import private_root

    f = registered
    private = tmp_path / "node-private"
    if os.name == "nt":
        private_root(private)
    else:
        private.mkdir(mode=0o700)
    namespace = private / "new-capacity"
    with f.authority._connect() as connection:
        selected = snapshot(f, connection)
    registration = selected.binding.registration
    identity = BindingIdentity(registration.node_id, registration.boot_incarnation, registration.runtime_id,
        "actual-configured-capacity", registration.agent_slot_id, registration.node_binding_revision)
    capacity = SimpleNamespace(authority=f.authority, config=SimpleNamespace(binding=selected.binding), binding=identity,
        settings={"lifecycle_control": True, "lifecycle_initialize_journal": True,
            "driver_journal": str(namespace / "driver.sqlite"), "binding_id": "controlled-installed-driver-binding"})
    if retained_history:
        plan(f, submit(f))
        with pytest.raises(PermissionError, match="history"):
            _namespace_authority(capacity, namespace, capacity.settings["binding_id"], identity, for_provision=True)
        with pytest.raises(CapacityEvidenceUnavailable):
            lifecycle_journal(capacity)
        assert not namespace.exists()
    else:
        journal = lifecycle_journal(capacity)
        assert journal.preview_lifecycle_adoption()["schema_version"] == 2
        assert journal.preview_lifecycle_adoption()["operation_count"] == 0
        # Later normal observation verifies the original retained namespace;
        # it does not treat a now-created Core plan as a new provisioning request.
        plan(f, submit(f))
        capacity._lifecycle_reservation._authorize_namespace(namespace, capacity.settings["binding_id"], identity)
    no_message_or_input(f)


def test_request_local_core_connection_never_caches_authority_across_committed_checks(registered):
    from runtime.receiver_lifecycle_core import LifecycleCoreCallbacks
    from runtime_tests.test_receiver_lifecycle_issuance_pg import issue

    f = registered
    original = submit(f)
    source = issue(f, original).challenge.challenge.source
    core = LifecycleCoreCallbacks(f.recovery.projects, journal_generation=1)
    with core.session():
        first, connection = core._current()
        assert first.authority is not f.recovery.authority
        assert core.resolve("observe", source)[0] == source
        assert core._current()[1] is connection
        with core.session():
            assert core._current()[1] is connection
        # The previous check committed: an independent writer can revoke the
        # exact original issuer while the same request connection stays open.
        with f.authority._connect() as writer:
            writer.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                (source.grant_ref,))
        with pytest.raises(AuthorizationDenied):
            core.resolve("observe", source)
        core._current()  # Failed authorization rolled back, retaining no SQL transaction.
    assert connection.closed
    with pytest.raises(RuntimeError, match="request-local session"):
        core.resolve("observe", source)
    no_message_or_input(f)


def test_core_connection_callback_refuses_an_active_transaction_before_node_work(registered):
    from runtime.receiver_lifecycle_core import LifecycleCoreCallbacks

    core = LifecycleCoreCallbacks(registered.recovery.projects, journal_generation=1)
    with core.session():
        _recovery, connection = core._current()
        connection.execute("BEGIN")
        try:
            with pytest.raises(RuntimeError, match="active SQL transaction"):
                core._current()
        finally:
            connection.rollback()
        core._current()


def installed(f, operation, *, capacity_state="fresh", lose_ack=False, revoke_after=False):
    with f.authority._connect() as connection:
        selected = snapshot(f, connection)
    config = ReceiverClientConfig(selected.binding, selected.authority_key.key_id, selected.authority_key.revision,
        selected.authority_key.public_key, key_fingerprint(selected.authority_key.public_key),
        selected.binding.registration.boot_incarnation, selected.journal_generation)
    calls = []

    def visible(phase):
        # A separate physical connection can acquire the exact operation row:
        # the executor's previous parent transaction has actually committed.
        with f.authority._connect() as reader:
            row = reader.execute("SELECT payload FROM outbox WHERE tenant_id=%s AND operation_id=%s AND topic=%s "
                "FOR UPDATE NOWAIT", (f.authority.tenant_id, operation["operation_id"], TOPIC)).fetchone()[0]
            assert row["lifecycle"]["phase"] == phase
            return row

    def signed_receipt(signed):
        permit = signed.permit
        now = f.authority.canonical_now()
        session = permit.plan.capacity.native_session_ref or "controlled_actual_created_session"
        return sign_receipt(LifecycleReceipt(source=permit.plan.source, target=permit.plan.target,
            driver_operation_id=permit.plan.driver_operation_id, action=permit.plan.action,
            permit_digest=sha256(permit), semantic_digest=permit.semantic_digest, request_id=permit.request_id,
            nonce=permit.nonce, node_key_id=permit.plan.target.node_key_id, outcome="acknowledged", effect_possible=True,
            evidence_refs=("controlled-original-native-protocol-evidence",), native_session_ref=session,
            provider_generation=native_generation(permit.plan.capacity.driver_binding_id, asdict(permit.plan.capacity.binding), session),
            reason_code=None, observed_at=now, issued_at=now, deadline=now + timedelta(seconds=10)), f.node_key)

    def read_capacity(challenge):
        row = visible("observing")
        assert row["operation"]["effect_state"] == "committed"
        calls.append("observe")
        return observe(f, SimpleNamespace(challenge=challenge), state=capacity_state)

    def execute(permit, **_kwargs):
        row = visible("executing")
        assert row["operation"]["effect_state"] == "native_possible" and row["lifecycle"]["permit"] == permit.model_dump(mode="json")
        calls.append("execute")
        signed = signed_receipt(permit)
        if revoke_after:
            with f.authority._connect() as connection:
                connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                                   (f.recovery.projects.context.grant_ref,))
        if lose_ack:
            raise OSError("controlled lost response after possible Native effect")
        return signed

    def readback(permit, **_kwargs):
        visible("executing")
        calls.append("readback")
        return signed_receipt(permit)

    transport = SimpleNamespace(config=config, signing_key=f.authority_key,
        observe=read_capacity, execute=execute, readback=readback)
    f.recovery.authority._receiver_lifecycle_transports = {RECEIVER: transport}
    return ReceiverLifecycleExecutor(f.recovery, transport), calls


@pytest.mark.parametrize("action,state,expected", [("prepare_receiver", "fresh", ["observe", "execute"]),
    ("prepare_receiver", "existing", ["observe"]), ("resume_receiver", "existing", ["observe", "execute"])])
def test_registered_recovery_entry_commits_each_phase_before_node_and_records_original_result(registered, action, state, expected):
    f = registered
    original = submit(f, action)
    _executor, calls = installed(f, original, capacity_state=state)
    result = f.recovery.advance(PROJECT, original["operation_id"], f.secret)
    assert result["operation_id"] == original["operation_id"] and result["state"] == "completed"
    assert calls == expected
    assert f.recovery.advance(PROJECT, original["operation_id"], f.secret) == result and calls == expected
    no_message_or_input(f)


def test_lost_response_keeps_possible_marker_and_uses_only_original_readback(registered):
    f = registered
    original = submit(f)
    executor, calls = installed(f, original, lose_ack=True)
    first = executor.advance(PROJECT, original["operation_id"], f.secret)
    before = payload(f, original)["lifecycle"]["permit"]
    assert first["state"] == "unknown" and first["effect_state"] == "native_possible"
    second = executor.advance(PROJECT, original["operation_id"], f.secret)
    assert second["state"] == "completed" and calls == ["observe", "execute", "readback"]
    assert payload(f, original)["lifecycle"]["permit"] == before
    no_message_or_input(f)


def test_actual_pg_expired_signed_capacity_returns_original_deferred_operation_without_execution(registered):
    f = registered
    original = submit(f)
    _executor, calls = installed(f, original)
    transport = f.recovery.authority._receiver_lifecycle_transports[RECEIVER]
    actual = transport.observe

    def expired(challenge):
        signed = actual(challenge)
        observation = signed.observation
        capacity = observation.capacity.model_copy(update={"valid_until": observation.capacity.observed_at + timedelta(microseconds=1)})
        return sign_observation(observation.model_copy(update={"capacity": capacity}), f.node_key)

    transport.observe = expired
    result = f.recovery.advance(PROJECT, original["operation_id"], f.secret)
    assert result["state"] == "deferred" and result["effect_state"] == "committed"
    assert result["operation_id"] == original["operation_id"] and result["reason_code"] == "lifecycle_admission_unavailable"
    assert calls == ["observe"] and payload(f, original)["lifecycle"].get("permit") is None
    no_message_or_input(f)


def test_current_caller_loss_after_node_effect_retains_authenticated_result(registered):
    f = registered
    original = submit(f)
    executor, calls = installed(f, original, revoke_after=True)
    with pytest.raises(AuthorizationDenied):
        executor.advance(PROJECT, original["operation_id"], f.secret)
    saved = payload(f, original)
    assert saved["operation"]["state"] == "completed"
    assert saved["lifecycle"]["receipt"]["receipt"]["outcome"] == "acknowledged"
    assert calls == ["observe", "execute"]
    no_message_or_input(f)


def test_team_preparation_uses_the_same_fenced_executor_after_configuration_commit(registered):
    f = registered
    original = {}
    _executor, calls = installed(f, original)
    transport = f.recovery.authority._receiver_lifecycle_transports[RECEIVER]
    actual_observe = transport.observe

    def linked(challenge):
        original["operation_id"] = challenge.challenge.source.operation_ref
        return actual_observe(challenge)

    transport.observe = linked
    args = {"project_id": PROJECT, "prepare_native": True, "members": [{"agent_slot_id": "slot-b",
        "principal_ref": f.comm.clients["b"].service.context.principal_ref, "endpoint_id": RECEIVER}]}
    result = f.recovery.projects.execute("configure_team", args, f.secret)
    item = result[1]["native_sessions"][0]
    assert item["state"] == "native_observed" and item["observation"] == "signed_lifecycle_receipt"
    assert item["session_ref"] == "controlled_actual_created_session"
    assert item["preparation_operation_ref"] == original["operation_id"] and calls == ["observe", "execute"]
    saved = payload(f, original)
    assert saved["request"]["reason"] == "Prepare committed team revision " + str(result[1]["team_revision"])
    # Re-observing exactly the same committed configuration uses the original
    # command key and does not create another Node execution.
    repeated = f.recovery.projects._prepare_communication_sessions(result, args, f.secret)
    assert repeated[1]["native_sessions"][0]["preparation_operation_ref"] == original["operation_id"]
    assert calls == ["observe", "execute"]
    no_message_or_input(f)


def test_ready_existing_team_capacity_preparation_is_read_only_and_does_not_invoke_legacy_callback(registered, monkeypatch):
    f = registered
    original = {}
    _executor, calls = installed(f, original, capacity_state="existing")
    transport = f.recovery.authority._receiver_lifecycle_transports[RECEIVER]
    actual_observe = transport.observe

    def linked(challenge):
        original["operation_id"] = challenge.challenge.source.operation_ref
        return actual_observe(challenge)

    transport.observe = linked
    monkeypatch.setattr(f.endpoint, "prepare_runtime", lambda: pytest.fail("unfenced legacy preparation was called"))
    result = f.recovery.projects.execute("configure_team", {"project_id": PROJECT, "members": [{
        "agent_slot_id": "slot-b", "principal_ref": f.comm.clients["b"].service.context.principal_ref,
        "endpoint_id": RECEIVER}]}, f.secret)
    item = result[1]["native_sessions"][0]
    assert item["state"] == "native_observed" and item["observation"] == "signed_lifecycle_observation"
    assert calls == ["observe"] and payload(f, original)["operation"]["effect_state"] == "committed"
    no_message_or_input(f)
