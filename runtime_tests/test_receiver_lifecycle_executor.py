"""E1 commit-boundary orchestration with real signed contracts/issuer helpers.

Core rows/transactions and Node actions are controlled ports. No PG/Host/process
or network is contacted, so these checks do not qualify an installed Receiver.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import timedelta
from types import MethodType, SimpleNamespace

import pytest

import runtime.receiver_lifecycle_executor as executor_module
from runtime.errors import AuthorizationDenied
from runtime.receiver_config import ReceiverClientConfig
from runtime.receiver_contract import native_generation
from runtime.receiver_crypto import key_fingerprint, public_key, sha256, verify
from runtime.receiver_lifecycle_contract import LifecycleReceipt, sign_receipt
from runtime.receiver_lifecycle_executor import LifecycleExecutorRejected, ReceiverLifecycleExecutor
from runtime.receiver_recovery_operations import ReceiverRecoveryOperations
from runtime_tests.test_receiver_lifecycle_issuance import (
    AUTHORITY_KEY,
    NODE_KEY,
    NOW,
    OPERATION,
    PROJECT,
    observation,
)
from runtime_tests.test_receiver_lifecycle_issuance import fixture as issuance_fixture

fixture = issuance_fixture


@pytest.fixture
def execution(fixture, monkeypatch):
    f = fixture
    f.active, f.authenticated, f.host_calls = 0, True, []
    authority = f.checked.authority
    authority._transaction_connection = None

    @contextmanager
    def transaction():
        f.active += 1
        try:
            with f.cursor.connection.transaction():
                yield authority, SimpleNamespace(cursor=lambda: cursor())
        finally:
            f.active -= 1

    @contextmanager
    def cursor():
        yield f.cursor

    authority.transaction = transaction
    f.recovery.authority = authority

    def authenticate(credential):
        if credential != "current-credential" or not f.authenticated:
            raise PermissionError("controlled current credential loss")

    f.recovery.projects = SimpleNamespace(context=SimpleNamespace(principal_ref="agent:manager", grant_ref="original-grant"),
        service=SimpleNamespace(authenticate=authenticate))
    f.recovery._authorize = lambda *_args, **_kwargs: (authority, None, {}, f.recovery.payload["actor"], None)
    f.recovery.read = lambda _project, _operation, credential: (authenticate(credential), deepcopy(f.recovery.payload["operation"]))[1]
    f.original_read_allowed = True

    def original_read(recovery, cursor, signed):
        assert recovery is f.recovery and cursor is f.cursor
        assert signed.model_dump(mode="json") == f.recovery.payload["lifecycle"]["permit"]
        if not f.original_read_allowed:
            raise AuthorizationDenied("agent:manager", "original-grant")
        return signed.permit.plan.source

    monkeypatch.setattr(executor_module, "require_original_lifecycle_read", original_read)
    target = f.snapshot.target()
    config = ReceiverClientConfig(f.snapshot.binding, f.snapshot.authority_key.key_id,
        f.snapshot.authority_key.revision, public_key(AUTHORITY_KEY), key_fingerprint(public_key(AUTHORITY_KEY)),
        target.registration.boot_incarnation, target.journal_generation, "controlled-old-boot-isolation")
    f.mode, f.outcome, f.observe_error, f.execute_error = "fresh", "acknowledged", None, None
    f.revoke_after_execute, f.wrong_nonce, f.bad_signature = False, False, False

    def receipt(permit):
        p = permit.permit
        session = p.plan.capacity.native_session_ref or "controlled-created-session"
        now = NOW + timedelta(seconds=f.elapsed)
        value = LifecycleReceipt(source=p.plan.source, target=p.plan.target,
            driver_operation_id=p.plan.driver_operation_id, action=p.plan.action,
            permit_digest=sha256(p),
            semantic_digest=p.semantic_digest, request_id=p.request_id, nonce="0" * 64 if f.wrong_nonce else p.nonce,
            node_key_id=p.plan.target.node_key_id, outcome=f.outcome, effect_possible=f.outcome != "definitively_not_started",
            evidence_refs=("controlled-original-driver-evidence",),
            native_session_ref=session if f.outcome == "acknowledged" else None,
            provider_generation=native_generation(p.plan.capacity.driver_binding_id, asdict(p.plan.capacity.binding), session)
                if f.outcome == "acknowledged" else None,
            reason_code=None if f.outcome == "acknowledged" else "controlled_node_outcome",
            observed_at=now, issued_at=now, deadline=now + timedelta(seconds=10))
        signed = sign_receipt(value, NODE_KEY)
        return signed.model_copy(update={"signature": "0" * 128}) if f.bad_signature else signed

    def observe(challenge):
        assert f.active == 0 and f.cursor.connection.depth == 0
        saved = f.recovery.payload
        assert saved["operation"]["state"] == "preparing" and saved["operation"]["effect_state"] == "committed"
        assert saved["lifecycle"]["challenge"] == challenge.model_dump(mode="json")
        f.host_calls.append("observe")
        if f.observe_error:
            raise f.observe_error
        return observation(f, SimpleNamespace(challenge=challenge), state=f.mode)

    def execute(permit, **_kwargs):
        assert f.active == 0 and f.cursor.connection.depth == 0
        saved = f.recovery.payload
        assert saved["operation"]["state"] == "submitting" and saved["operation"]["effect_state"] == "native_possible"
        assert saved["lifecycle"]["permit"] == permit.model_dump(mode="json")
        f.host_calls.append("execute")
        if f.revoke_after_execute:
            f.authenticated = False
        if f.execute_error:
            raise f.execute_error
        return receipt(permit)

    def readback(permit, **_kwargs):
        assert f.active == 0 and f.cursor.connection.depth == 0
        f.host_calls.append("readback")
        return receipt(permit)

    f.transport = SimpleNamespace(config=config, signing_key=AUTHORITY_KEY, observe=observe, execute=execute, readback=readback)
    f.executor = ReceiverLifecycleExecutor(f.recovery, f.transport)
    f.run = lambda: f.executor.advance(PROJECT, OPERATION, "current-credential")
    return f


def test_every_host_phase_follows_the_parent_commit_and_uses_original_signed_operation(execution):
    f = execution
    operation = f.run()
    assert f.host_calls == ["observe", "execute"]
    assert operation["state"] == "completed" and operation["operation_id"] == OPERATION
    saved = f.recovery.payload
    verify(public_key(NODE_KEY), saved["lifecycle"]["receipt"]["signature"],
           LifecycleReceipt.model_validate_json(json.dumps(saved["lifecycle"]["receipt"]["receipt"]), strict=True))
    assert saved["command"]["command_id"] == "original-command" and f.active == 0
    assert f.run() == operation and f.host_calls == ["observe", "execute"]


def test_expired_observation_before_permit_keeps_original_deferred_operation_without_native_entry(execution):
    f = execution
    actual = f.transport.observe

    def expired(challenge):
        signed = actual(challenge)
        f.elapsed = (signed.observation.capacity.valid_until - NOW).total_seconds() + 1
        return signed

    f.transport.observe = expired
    result = f.run()
    assert result["operation_id"] == OPERATION and result["state"] == "deferred"
    assert result["effect_state"] == "committed" and result["reason_code"] == "lifecycle_admission_unavailable"
    assert f.host_calls == ["observe"] and f.recovery.payload["lifecycle"].get("permit") is None


def test_possible_effect_uses_original_read_without_renewing_original_execution_authority(execution):
    f = execution
    f.execute_error = OSError("controlled lost response")
    assert f.run()["state"] == "unknown"
    f.denied = True  # The original source cannot be admitted for a new action.
    assert f.run()["state"] == "completed"
    assert f.host_calls == ["observe", "execute", "readback"]


def test_existing_ready_prepare_settles_from_observation_without_native_mutation(execution):
    execution.mode = "existing"
    result = execution.run()
    assert result["state"] == "completed" and result["effect_state"] == "committed"
    assert execution.host_calls == ["observe"] and execution.recovery.payload["lifecycle"]["permit"] is None


def test_observation_transport_failure_defers_without_possible_native_effect(execution):
    execution.observe_error = OSError("controlled disconnected observation")
    result = execution.run()
    assert result["state"] == "deferred" and result["effect_state"] == "committed"
    assert execution.host_calls == ["observe"] and execution.recovery.payload["lifecycle"]["permit"] is None


def test_possible_execution_error_uses_only_original_readback_and_never_executes_again(execution):
    f = execution
    f.execute_error = OSError("controlled lost ACK after possible effect")
    first = f.run()
    saved_permit = deepcopy(f.recovery.payload["lifecycle"]["permit"])
    assert first["state"] == "unknown" and first["effect_state"] == "native_possible"
    f.execute_error = None
    second = f.run()
    assert second["state"] == "completed"
    assert f.host_calls == ["observe", "execute", "readback"]
    assert f.recovery.payload["lifecycle"]["permit"] == saved_permit


@pytest.mark.parametrize("field", ["wrong_nonce", "bad_signature"])
def test_uncorrelated_or_unsigned_results_cannot_publish_a_positive_outcome(execution, field):
    setattr(execution, field, True)
    result = execution.run()
    assert result["state"] == "unknown" and result["effect_state"] == "native_possible"
    assert "receipt" not in execution.recovery.payload["lifecycle"]


def test_authentication_loss_after_effect_retains_authentic_fact_but_withholds_caller_result(execution):
    f = execution
    f.revoke_after_execute = True
    with pytest.raises(PermissionError):
        f.run()
    assert f.recovery.payload["operation"]["state"] == "completed"
    assert f.recovery.payload["lifecycle"]["receipt"]["receipt"]["outcome"] == "acknowledged"
    f.authenticated = True
    assert f.run()["state"] == "completed" and f.host_calls == ["observe", "execute"]


def test_changed_installed_transport_is_refused_before_host_contact(execution):
    f = execution
    f.transport.config = replace(f.transport.config, journal_generation=3)
    with pytest.raises(LifecycleExecutorRejected):
        f.run()
    assert f.host_calls == [] and f.recovery.payload["operation"]["effect_state"] == "committed"


def test_recovery_entry_advances_the_original_operation_through_runtime_installed_fenced_transport(execution):
    f = execution
    f.recovery.authority._receiver_lifecycle_transports = {"endpoint": f.transport}
    f.recovery._fenced_lifecycle = MethodType(ReceiverRecoveryOperations._fenced_lifecycle, f.recovery)
    result = ReceiverRecoveryOperations.advance(f.recovery, PROJECT, OPERATION, "current-credential")
    assert result["state"] == "completed" and result["operation_id"] == OPERATION
    assert f.host_calls == ["observe", "execute"]


def test_registered_transport_does_not_allow_another_actor_to_advance_private_recovery(execution):
    f = execution
    f.recovery.authority._receiver_lifecycle_transports = {"endpoint": f.transport}
    f.recovery._authorize = lambda *_args, **_kwargs: (f.recovery.authority, None, {}, "another-actor", None)
    with pytest.raises(AuthorizationDenied):
        ReceiverRecoveryOperations._fenced_lifecycle(f.recovery, PROJECT, OPERATION, "current-credential")
    assert f.host_calls == [] and f.recovery.payload["operation"]["state"] == "queued"
