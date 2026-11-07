"""Cursor/state E1 issuance tests with real Ed25519 and ConnectionClock.

The cursor, recovery rows and current-authority snapshots are controlled models
of caller transactions, not PostgreSQL evidence. No Host/Native/process/network.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from nacl.signing import SigningKey
from psycopg.pq import TransactionStatus

import runtime.receiver_lifecycle_issuance as module
from runtime.errors import AcceptanceGuardFailed, AuthorizationDenied
from runtime.receiver_crypto import key_fingerprint, public_key, sha256, sign, verify
from runtime.receiver_lifecycle_contract import (
    CapacityObservation,
    LifecycleContractRejected,
    sign_observation,
    to_driver_operation,
)
from runtime.receiver_lifecycle_domain import LifecycleAuthorityKey, LifecycleEndpointSnapshot
from runtime.receiver_lifecycle_issuance import (
    LifecycleIssuance,
    LifecycleIssuanceRejected,
    require_current_execution,
)
from runtime.receiver_models import EndpointBinding
from runtime_tests.test_receiver_lifecycle_contract import capacity, target

NOW = datetime(2026, 11, 7, tzinfo=UTC)
AUTHORITY_KEY = SigningKey(bytes.fromhex("11" * 32))
NODE_KEY = SigningKey(bytes.fromhex("22" * 32))
OTHER_KEY = SigningKey(bytes.fromhex("33" * 32))
PROJECT, OPERATION = "project", "receiver-recovery-actual"


class ControlledConnection:
    def __init__(self, recovery):
        self.recovery = recovery
        self.autocommit = False
        self.info = SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        self.depth, self.commits, self.rollbacks = 0, 0, 0

    @contextmanager
    def transaction(self):
        before = deepcopy(self.recovery.payload)
        self.depth += 1
        try:
            yield
        except BaseException:
            self.recovery.payload = before
            self.rollbacks += 1
            raise
        finally:
            self.depth -= 1


class ControlledCursor:
    def __init__(self, recovery):
        self.connection = ControlledConnection(recovery)
        self.events = []

    def execute(self, sql):
        assert sql == "SELECT 1", "issuance attempted SQL outside the existing domain/recovery helpers"
        self.events.append("read-transaction")
        self.connection.info.transaction_status = TransactionStatus.INTRANS


class ControlledRecovery:
    def __init__(self, fixture, action):
        self.fixture = fixture
        self.payload = {"schema_version": "acs-receiver-recovery/1", "project_id": PROJECT, "receiver_id": "endpoint",
            "actor": "collaborator:project:manager", "issuer_context": {"tenant_id": "tenant", "authority_id": "authority",
                "authority_incarnation": "incarnation", "principal_ref": "agent:manager", "grant_ref": "original-grant"},
            "profile": "root_manager", "request": {"action": action, "expected_revision": 13, "reason": "explicit authorized recovery"},
            "command": {"command_id": "original-command", "deadline": (NOW + timedelta(seconds=30)).isoformat()},
            "operation": {"operation_id": OPERATION, "kind": "recovery", "state": "queued", "message_handle": None,
                "receiver_ref": "endpoint", "binding_epoch": 13, "effect_state": "committed", "reason_code": None,
                "evidence_refs": ["command:original-command"], "revision": 1, "created_at": NOW.isoformat(), "updated_at": NOW.isoformat()}}
        self.saves, self.after_save = [], None

    def _row(self, cursor, project, operation_ref, *, lock=False):
        assert cursor is self.fixture.cursor and lock is True
        assert project == PROJECT and operation_ref == OPERATION
        cursor.events.append("locked-outbox")
        return deepcopy(self.payload)

    def _save(self, cursor, payload, operation, *, done=False):
        assert cursor is self.fixture.cursor and cursor.connection.depth > 0
        assert operation["operation_id"] == OPERATION
        cursor.events.append("save-existing-outbox-operation")
        self.payload = deepcopy(payload | {"operation": operation})
        self.saves.append((operation["state"], operation["effect_state"], done))
        if self.after_save:
            self.after_save(self.payload)


@pytest.fixture
def fixture(monkeypatch):
    f = SimpleNamespace(elapsed=0.0, denied=False, domain_calls=[], selection_suffix="")
    f.recovery = ControlledRecovery(f, "prepare_receiver")
    f.cursor = ControlledCursor(f.recovery)
    authority = SimpleNamespace(canonical_now=lambda cursor: NOW + timedelta(seconds=f.elapsed))
    f.checked = SimpleNamespace(authority=authority)
    registered = target()
    binding = EndpointBinding(registration=registered.registration, locator_host="127.0.0.1", locator_port=12345,
        route_class="loopback", node_key_id=registered.node_key_id, node_public_key=public_key(NODE_KEY),
        registration_signature=sign(NODE_KEY, registered.registration))
    f.snapshot = LifecycleEndpointSnapshot(binding, registered.binding_epoch, registered.connection_revision,
        "controlled-policy", LifecycleAuthorityKey("actual-authority-key", 5, public_key(AUTHORITY_KEY),
            key_fingerprint(public_key(AUTHORITY_KEY))), registered.journal_generation, NOW, NOW + timedelta(seconds=120))

    def original(recovery, cursor, payload):
        from runtime.receiver_lifecycle_contract import LifecycleSource

        assert recovery is f.recovery and cursor is f.cursor
        assert cursor.events[-1] == "locked-outbox" or "locked-outbox" in cursor.events
        f.domain_calls.append("original")
        if f.denied:
            raise AuthorizationDenied("agent:manager", "original-grant")
        if payload["request"]["action"] not in {"prepare_receiver", "resume_receiver"}:
            raise AcceptanceGuardFailed("original request is not a lifecycle action")
        context = payload["issuer_context"]
        source = LifecycleSource(operation_ref=payload["operation"]["operation_id"], command_id=payload["command"]["command_id"],
            tenant_id=context["tenant_id"], authority_id=context["authority_id"], authority_incarnation=context["authority_incarnation"],
            project_id=payload["project_id"], actor_address=payload["actor"], principal_ref=context["principal_ref"],
            grant_ref=context["grant_ref"], profile=payload["profile"], command_digest=sha256(payload["command"]),
            issuer_context_digest=sha256(context), request_digest=sha256(payload["request"]), business_deadline=None)
        return f.checked, source

    def checked(recovery, cursor, payload, *, journal_generation, expected_source=None, expected_target=None):
        authority, source = original(recovery, cursor, payload)
        f.domain_calls.append("checked")
        snapshot = replace(f.snapshot, checked_at=authority.authority.canonical_now(cursor))
        if (journal_generation != snapshot.journal_generation or expected_source is not None and expected_source != source
                or expected_target is not None and expected_target != snapshot.target()
                or snapshot.valid_until is not None and snapshot.valid_until <= snapshot.checked_at):
            raise AcceptanceGuardFailed("current original source/target changed")
        return authority, source, snapshot

    monkeypatch.setattr(module, "original_lifecycle_source", original)
    monkeypatch.setattr(module, "checked_lifecycle_authority", checked)
    f.issuer = LifecycleIssuance(f.recovery, AUTHORITY_KEY, journal_generation=2)
    return f


def challenge(f):
    return f.issuer.issue_challenge(f.cursor, PROJECT, OPERATION)


def observation(f, result, *, state="fresh", key=NODE_KEY, **changes):
    fact = capacity(state, observed_at=NOW + timedelta(seconds=f.elapsed), valid_until=NOW + timedelta(seconds=f.elapsed + 2), **changes)
    body = CapacityObservation(challenge_digest=sha256(result.challenge.challenge), request_id=result.challenge.challenge.request_id,
        nonce=result.challenge.challenge.nonce, source_digest=sha256(result.challenge.challenge.source),
        target=result.challenge.challenge.target, node_key_id=result.challenge.challenge.target.node_key_id, capacity=fact)
    return sign_observation(body, key)


def planned(f, *, state="fresh", **changes):
    issued = challenge(f)
    signed = observation(f, issued, state=state, **changes)
    result = f.issuer.record_observation(f.cursor, PROJECT, OPERATION, signed)
    return issued, signed, result


def permit(f, *, state="fresh"):
    planned(f, state=state)
    return f.issuer.issue_permit(f.cursor, PROJECT, OPERATION)


def test_constructor_and_validation_have_zero_storage_or_host_effect(fixture):
    f = fixture
    assert f.cursor.events == [] and f.recovery.saves == [] and f.domain_calls == []
    with pytest.raises(TypeError):
        LifecycleIssuance(f.recovery, AUTHORITY_KEY.encode().hex(), journal_generation=2)
    for changes in ({"journal_generation": True}, {"journal_generation": 0}, {"transport_seconds": 31}):
        with pytest.raises(ValueError):
            LifecycleIssuance(f.recovery, AUTHORITY_KEY, **({"journal_generation": 2} | changes))


def test_challenge_is_signed_and_saved_in_existing_recovery_before_any_host_read(fixture):
    f = fixture
    original_id, original_command = f.recovery.payload["operation"]["operation_id"], deepcopy(f.recovery.payload["command"])
    result = challenge(f)
    assert result.kind == "challenge" and result.operation["state"] == "preparing"
    assert f.recovery.payload["lifecycle"]["challenge"] == result.challenge.model_dump(mode="json")
    assert result.challenge.challenge.source.operation_ref == original_id
    assert f.recovery.payload["command"] == original_command and result.challenge.challenge.source.business_deadline is None
    verify(public_key(AUTHORITY_KEY), result.challenge.signature, result.challenge.challenge)
    assert f.recovery.saves == [("preparing", "committed", False)]
    assert f.cursor.connection.commits == 0 and f.cursor.connection.depth == 0


def test_same_live_challenge_is_replayed_without_reissuing_or_rewriting(fixture):
    first = challenge(fixture)
    before = deepcopy(fixture.recovery.payload)
    again = challenge(fixture)
    assert again.challenge == first.challenge and fixture.recovery.payload == before
    assert len(fixture.recovery.saves) == 1


def test_actual_signer_must_match_current_snapshot_installed_key(fixture):
    f = fixture
    f.issuer = LifecycleIssuance(f.recovery, OTHER_KEY, journal_generation=2)
    before = deepcopy(f.recovery.payload)
    with pytest.raises(LifecycleIssuanceRejected, match="signer_current_key_mismatch"):
        challenge(f)
    assert f.recovery.payload == before and f.recovery.saves == []


@pytest.mark.parametrize("state,action", [("fresh", "prepare_receiver"), ("existing", "resume_receiver")])
def test_verified_observation_pins_first_plan_and_permit_marker_atomically(fixture, state, action):
    f = fixture
    f.recovery.payload["request"]["action"] = action
    issued, signed, accepted = planned(f, state=state)
    assert accepted.kind == "planned" and accepted.operation["effect_state"] == "committed"
    before_digest = f.recovery.payload["lifecycle"]["first_plan_digest"]
    result = f.issuer.issue_permit(f.cursor, PROJECT, OPERATION)
    assert result.kind == "permit" and result.operation["state"] == "submitting"
    assert result.operation["effect_state"] == "native_possible" and f.recovery.saves[-1] == ("submitting", "native_possible", False)
    stored = f.recovery.payload["lifecycle"]
    assert stored["permit"] == result.permit.model_dump(mode="json") and stored["permit_digest"] == sha256(result.permit.permit)
    assert stored["first_plan_digest"] == before_digest == result.permit.permit.semantic_digest
    assert result.permit.permit.observation_digest == sha256(signed.observation)
    assert result.permit.permit.challenge_digest == sha256(issued.challenge.challenge)
    assert to_driver_operation(result.permit.permit.plan).deadline is None
    assert f.cursor.connection.commits == 0
    assert require_current_execution(f.recovery, f.cursor, PROJECT, OPERATION, result.permit, journal_generation=2) is None


def test_prepare_existing_ready_settles_from_signed_evidence_without_mutation_permit(fixture):
    f = fixture
    _issued, _signed, result = planned(f, state="existing")
    assert result.kind == "settled" and result.operation["state"] == "completed"
    assert result.operation["reason_code"] == "lifecycle_already_ready" and result.operation["effect_state"] == "committed"
    assert f.recovery.payload["lifecycle"]["permit"] is None and f.recovery.payload["lifecycle"]["plan"] is None
    assert f.issuer.issue_permit(f.cursor, PROJECT, OPERATION).kind == "settled"


@pytest.mark.parametrize("action,state,changes,reason", [
    ("prepare_receiver", "existing", {"input_state": "busy"}, "lifecycle_input_busy"),
    ("resume_receiver", "existing", {"journal_state": "unresolved"}, "lifecycle_journal_unresolved"),
    ("resume_receiver", "existing", {"blocker": "approval"}, "lifecycle_blocker_approval"),
    ("resume_receiver", "existing", {"blocker": "question"}, "lifecycle_blocker_question"),
    ("resume_receiver", "existing", {"blocker": "draft"}, "lifecycle_blocker_draft"),
    ("resume_receiver", "fresh", {}, "lifecycle_capacity_not_ready"),
    ("prepare_receiver", "existing", {"state": "unknown", "reason_code": "readback_unknown"}, "lifecycle_capacity_unknown")])
def test_unknown_busy_blocked_or_missing_session_defer_without_new_effect(fixture, action, state, changes, reason):
    f = fixture
    f.recovery.payload["request"]["action"] = action
    issued = challenge(f)
    if "state" in changes:
        fact = capacity(state).model_copy(update=changes)
        body = CapacityObservation(challenge_digest=sha256(issued.challenge.challenge), request_id=issued.challenge.challenge.request_id,
            nonce=issued.challenge.challenge.nonce, source_digest=sha256(issued.challenge.challenge.source),
            target=issued.challenge.challenge.target, node_key_id=issued.challenge.challenge.target.node_key_id, capacity=fact)
        signed = sign_observation(body, NODE_KEY)
    else:
        signed = observation(f, issued, state=state, **changes)
    result = f.issuer.record_observation(f.cursor, PROJECT, OPERATION, signed)
    assert result.kind == "deferred" and result.operation["reason_code"] == reason
    assert result.operation["effect_state"] == "committed" and f.recovery.payload["lifecycle"]["permit"] is None
    assert f.recovery.payload["lifecycle"]["first_plan_digest"] is None


@pytest.mark.parametrize("action", ["inspect", "reconcile", "retry_delivery", "rebind_receiver"])
def test_action_always_comes_from_committed_request_not_caller_or_observed_capacity(fixture, action):
    f = fixture
    f.recovery.payload["request"]["action"] = action
    with pytest.raises(AcceptanceGuardFailed):
        challenge(f)
    assert f.recovery.saves == []


def test_wrong_node_signature_or_nonce_cannot_record_a_plan(fixture):
    f = fixture
    issued = challenge(f)
    before = deepcopy(f.recovery.payload)
    with pytest.raises(LifecycleContractRejected, match="signature_rejected"):
        f.issuer.record_observation(f.cursor, PROJECT, OPERATION, observation(f, issued, key=OTHER_KEY))
    signed = observation(f, issued)
    wrong = signed.observation.model_copy(update={"nonce": "a" * 64})
    with pytest.raises(LifecycleContractRejected, match="observation_binding_changed"):
        f.issuer.record_observation(f.cursor, PROJECT, OPERATION, sign_observation(wrong, NODE_KEY))
    assert f.recovery.payload == before


def test_observation_expiry_is_not_authority_to_issue_a_new_permit(fixture):
    f = fixture
    planned(f)
    before = deepcopy(f.recovery.payload)
    f.elapsed = 4
    with pytest.raises(LifecycleContractRejected, match="expired_or_uncertain"):
        f.issuer.issue_permit(f.cursor, PROJECT, OPERATION)
    assert f.recovery.payload == before and f.recovery.payload["operation"]["effect_state"] == "committed"


def test_transport_can_renew_before_possible_effect_without_replacing_stable_plan(fixture):
    f = fixture
    first, _observation, _accepted = planned(f)
    original_digest = f.recovery.payload["lifecycle"]["first_plan_digest"]
    original_driver = to_driver_operation(module._typed(module.LifecyclePlan, f.recovery.payload["lifecycle"]["plan"]))
    f.elapsed = (first.challenge.challenge.deadline - NOW).total_seconds() + 1
    renewed = challenge(f)
    assert renewed.challenge.challenge.nonce != first.challenge.challenge.nonce
    assert f.recovery.payload["lifecycle"]["first_plan_digest"] == original_digest
    assert f.recovery.payload["lifecycle"]["observation"] is None
    f.issuer.record_observation(f.cursor, PROJECT, OPERATION, observation(f, renewed))
    current = f.issuer.issue_permit(f.cursor, PROJECT, OPERATION)
    assert current.permit.permit.semantic_digest == original_digest
    assert to_driver_operation(current.permit.permit.plan) == original_driver


def test_first_plan_cannot_be_replaced_with_new_profile_even_before_effect(fixture):
    f = fixture
    planned(f)
    f.elapsed = 11
    renewed = challenge(f)
    before = deepcopy(f.recovery.payload)
    changed = observation(f, renewed, profile_fingerprint="f" * 64)
    with pytest.raises(LifecycleIssuanceRejected, match="stable_plan_changed"):
        f.issuer.record_observation(f.cursor, PROJECT, OPERATION, changed)
    assert f.recovery.payload == before


def test_possible_effect_marker_only_allows_original_readback_after_expiry(fixture):
    f = fixture
    result = permit(f)
    before = deepcopy(f.recovery.payload)
    f.elapsed = 50
    assert challenge(f).kind == "readback_only"
    assert f.issuer.issue_permit(f.cursor, PROJECT, OPERATION).kind == "readback_only"
    assert f.issuer.record_observation(f.cursor, PROJECT, OPERATION, None).kind == "readback_only"
    assert f.recovery.payload == before
    with pytest.raises(ValueError):
        require_current_execution(f.recovery, f.cursor, PROJECT, OPERATION, result.permit, journal_generation=2)
    assert f.recovery.payload == before


@pytest.mark.parametrize("field,value", [("state", "queued"), ("state", "completed"), ("effect_state", "committed")])
def test_execution_callback_uses_fresh_persisted_phase_and_effect(fixture, field, value):
    f = fixture
    signed = permit(f).permit
    f.recovery.payload["operation"][field] = value
    before = deepcopy(f.recovery.payload)
    with pytest.raises(LifecycleIssuanceRejected, match="execution_state_rejected"):
        require_current_execution(f.recovery, f.cursor, PROJECT, OPERATION, signed, journal_generation=2)
    assert f.recovery.payload == before


def test_execution_callback_rejects_forged_permit_or_replaced_original_source(fixture):
    f = fixture
    signed = permit(f).permit
    changed = signed.model_copy(update={"signature": "0" * 128})
    with pytest.raises(LifecycleIssuanceRejected, match="execution_permit_changed"):
        require_current_execution(f.recovery, f.cursor, PROJECT, OPERATION, changed, journal_generation=2)
    f.recovery.payload["issuer_context"]["grant_ref"] = "replacement-grant"
    with pytest.raises(AcceptanceGuardFailed):
        require_current_execution(f.recovery, f.cursor, PROJECT, OPERATION, signed, journal_generation=2)


def test_current_role_loss_after_plan_or_possible_marker_never_grants_execution(fixture):
    f = fixture
    signed = permit(f).permit
    f.denied = True
    before = deepcopy(f.recovery.payload)
    with pytest.raises(AuthorizationDenied):
        require_current_execution(f.recovery, f.cursor, PROJECT, OPERATION, signed, journal_generation=2)
    with pytest.raises(AuthorizationDenied):
        challenge(f)
    assert f.recovery.payload == before


def test_late_role_loss_rolls_back_permit_and_possible_marker_in_same_parent_transaction(fixture):
    f = fixture
    planned(f)
    before = deepcopy(f.recovery.payload)

    def revoke(saved):
        if saved["operation"]["effect_state"] == "native_possible":
            f.denied = True

    f.recovery.after_save = revoke
    with pytest.raises(AuthorizationDenied):
        f.issuer.issue_permit(f.cursor, PROJECT, OPERATION)
    assert f.recovery.payload == before and f.cursor.connection.rollbacks >= 1
    assert f.recovery.payload["lifecycle"]["permit"] is None


def test_late_transport_expiry_rolls_back_marker_not_accepted_recovery(fixture):
    f = fixture
    planned(f)
    before = deepcopy(f.recovery.payload)

    def wait(saved):
        if saved["operation"]["effect_state"] == "native_possible":
            deadline = datetime.fromisoformat(saved["lifecycle"]["permit"]["permit"]["deadline"])
            f.elapsed = (deadline-NOW).total_seconds()+1

    f.recovery.after_save = wait
    with pytest.raises(ValueError):
        f.issuer.issue_permit(f.cursor, PROJECT, OPERATION)
    assert f.recovery.payload == before and f.recovery.payload["operation"]["operation_id"] == OPERATION


@pytest.mark.parametrize("field,value", [("binding_epoch", 14), ("connection_revision", 5), ("connection_policy_digest", "changed-policy")])
def test_current_endpoint_or_transport_snapshot_change_rejects_old_plan(fixture, field, value):
    f = fixture
    planned(f)
    before = deepcopy(f.recovery.payload)
    f.snapshot = replace(f.snapshot, **{field: value})
    with pytest.raises((AcceptanceGuardFailed, LifecycleIssuanceRejected)):
        f.issuer.issue_permit(f.cursor, PROJECT, OPERATION)
    assert f.recovery.payload == before


def test_owner_snapshot_without_technical_expiry_still_gets_bounded_transport(fixture):
    f = fixture
    f.snapshot = replace(f.snapshot, valid_until=None)
    result = challenge(f)
    assert (result.challenge.challenge.deadline - result.challenge.challenge.issued_at).total_seconds() == f.issuer.transport_seconds
    assert result.challenge.challenge.source.business_deadline is None


def test_all_methods_borrow_explicit_parent_transaction_and_never_commit(fixture):
    f = fixture
    f.cursor.connection.autocommit = True
    f.cursor.connection.info.transaction_status = TransactionStatus.IDLE
    with pytest.raises(LifecycleIssuanceRejected, match="caller_transaction_required"):
        challenge(f)
    f.cursor.connection.info.transaction_status = TransactionStatus.INTRANS
    result = permit(f)
    assert result.kind == "permit" and f.cursor.connection.commits == 0


def test_parent_rollback_preserves_only_already_accepted_original_recovery(fixture):
    f = fixture
    before = deepcopy(f.recovery.payload)
    with pytest.raises(RuntimeError), f.cursor.connection.transaction():
        result = permit(f)
        assert result.kind == "permit"
        raise RuntimeError("caller chooses rollback before any Host I/O")
    assert f.recovery.payload == before


def test_constructor_cached_state_and_returned_dto_cannot_override_locked_outbox(fixture):
    f = fixture
    cached = deepcopy(f.recovery.payload)
    result = challenge(f)
    result.operation["state"] = "submitting"
    assert f.recovery.payload["operation"]["state"] == "preparing"
    f.recovery.payload["operation"].update(state="unknown", effect_state="native_possible")
    assert cached["operation"]["state"] == "queued"
    assert f.issuer.issue_permit(f.cursor, PROJECT, OPERATION).kind == "readback_only"


def test_automatic_original_command_budget_is_historical_not_new_business_deadline(fixture):
    f = fixture
    original = deepcopy(f.recovery.payload["command"])
    f.elapsed = 40
    result = challenge(f)
    assert result.challenge.challenge.issued_at > datetime.fromisoformat(original["deadline"])
    assert result.challenge.challenge.source.command_digest == sha256(original)
    assert result.challenge.challenge.source.business_deadline is None
    assert f.recovery.payload["command"] == original


def test_corrupted_stored_authority_challenge_cannot_be_used_to_record_node_fact(fixture):
    f = fixture
    issued = challenge(f)
    signed = observation(f, issued)
    f.recovery.payload["lifecycle"]["challenge"]["signature"] = "0" * 128
    before = deepcopy(f.recovery.payload)
    with pytest.raises(LifecycleContractRejected, match="signature_rejected"):
        f.issuer.record_observation(f.cursor, PROJECT, OPERATION, signed)
    assert f.recovery.payload == before and f.recovery.payload["lifecycle"]["first_plan_digest"] is None


@pytest.mark.parametrize("envelope", ["challenge", "observation"])
def test_execution_rechecks_stored_signature_chain_not_only_plan_hash(fixture, envelope):
    f = fixture
    result = permit(f)
    f.recovery.payload["lifecycle"][envelope]["signature"] = "0" * 128
    before = deepcopy(f.recovery.payload)
    with pytest.raises(ValueError, match="signature rejected"):
        require_current_execution(f.recovery, f.cursor, PROJECT, OPERATION, result.permit, journal_generation=2)
    assert f.recovery.payload == before and f.recovery.payload["operation"]["effect_state"] == "native_possible"


def test_free_execution_checker_needs_no_authority_private_key(fixture):
    f = fixture
    result = permit(f)
    del f.issuer
    assert require_current_execution(f.recovery, f.cursor, PROJECT, OPERATION, result.permit, journal_generation=2) is None


def test_possible_effect_readback_does_not_require_a_new_current_target_or_signer(fixture):
    f = fixture
    result = permit(f)
    before = deepcopy(f.recovery.payload)
    f.snapshot = replace(f.snapshot, binding_epoch=14)
    f.issuer = LifecycleIssuance(f.recovery, OTHER_KEY, journal_generation=2)
    assert f.issuer.issue_permit(f.cursor, PROJECT, OPERATION).kind == "readback_only"
    assert f.recovery.payload == before
    with pytest.raises(AcceptanceGuardFailed):
        require_current_execution(f.recovery, f.cursor, PROJECT, OPERATION, result.permit, journal_generation=2)
