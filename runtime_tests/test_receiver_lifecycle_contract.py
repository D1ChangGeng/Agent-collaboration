"""Real Ed25519/canonical and calibrated clock E1 contracts, no Host/DB/model.

Capacity witnesses below are explicitly controlled facts, not measurements of a
live process. The separate Node capacity builder owns those actual observations.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from nacl.signing import SigningKey
from pydantic import ValidationError

from runtime.codex_driver import BindingIdentity
from runtime.connection_clock import ConnectionClock
from runtime.receiver_contract import native_generation
from runtime.receiver_crypto import public_key, sha256
from runtime.receiver_lifecycle_contract import (
    CapacityObservation,
    LifecycleCapacityFact,
    LifecycleChallenge,
    LifecycleContractRejected,
    LifecyclePermit,
    LifecycleReceipt,
    LifecycleSource,
    LifecycleTarget,
    OwnedProcessEvidence,
    build_lifecycle_plan,
    capacity_semantic_digest,
    lifecycle_plan_digest,
    profile_fingerprint,
    sign_challenge,
    sign_observation,
    sign_permit,
    sign_receipt,
    to_driver_operation,
    verify_challenge,
    verify_observation,
    verify_permit,
    verify_receipt,
)
from runtime.receiver_models import EndpointRegistration

NOW = datetime(2026, 11, 7, tzinfo=UTC)
AUTHORITY_KEY = SigningKey(bytes.fromhex("11" * 32))
NODE_KEY = SigningKey(bytes.fromhex("22" * 32))
OTHER_KEY = SigningKey(bytes.fromhex("33" * 32))
BINDING = BindingIdentity("node", "boot", "runtime", "actual-capacity-id-not-delivery-attempt", "slot", 7)


def target(**updates):
    registration = EndpointRegistration(registration_id="registration", endpoint_id="endpoint", endpoint_revision=3,
        connection_ref="connection", tenant_id="tenant", authority_id="authority", authority_incarnation="incarnation",
        node_id="node", node_binding_revision=7, runtime_id="runtime", runtime_revision=9, machine_id="machine",
        boot_incarnation="boot", scope_id="scope", agent_slot_id="slot", tls_certificate_sha256="a" * 64,
        config_sha256="b" * 64, expires_at=NOW + timedelta(hours=1))
    return LifecycleTarget(registration=registration, binding_epoch=13, connection_revision=4,
        node_key_id="actual-node-key", journal_generation=2, **updates)


def source(**updates):
    return LifecycleSource(**({"operation_ref": "receiver-recovery-actual", "command_id": "original-command",
        "tenant_id": "tenant", "authority_id": "authority", "authority_incarnation": "incarnation",
        "project_id": "project", "actor_address": "collaborator:project:manager", "principal_ref": "agent:manager",
        "grant_ref": "original-grant", "profile": "root_manager", "command_digest": "c" * 64,
        "issuer_context_digest": "d" * 64, "request_digest": "e" * 64} | updates))


def capacity(state="fresh", **updates):
    process = OwnedProcessEvidence(pid=123, birth_ref="controlled-process-birth", containment_id="controlled-owned-tree",
                                  evidence_ref="controlled:process") if state == "existing" else None
    session = "controlled-existing-session" if state == "existing" else None
    return LifecycleCapacityFact(**({"state": state, "driver_binding_id": "actual-driver-binding", "binding": BINDING,
        "profile_fingerprint": profile_fingerprint({"actual_profile_digest": "a" * 64, "account_digest": "f" * 64}, {"selected": "env"}),
        "profile_evidence_ref": "controlled:profile", "ownership": "exclusive_owned" if state == "existing" else "exclusive_reserved",
        "journal_state": "clear", "kernel_claim_ref": "controlled:claim", "journal_evidence_ref": "controlled:journal",
        "absence_evidence_ref": None if state == "existing" else "controlled:absence", "process": process,
        "native_session_ref": session, "provider_generation": native_generation("actual-driver-binding", asdict(BINDING), session) if session else None,
        "input_state": "ready" if state == "existing" else "not_started", "blocker": "none",
        "evidence_refs": ("controlled:profile", "controlled:claim", "controlled:journal", "controlled:process") if state == "existing" else
            ("controlled:profile", "controlled:claim", "controlled:journal", "controlled:absence"),
        "observed_at": NOW - timedelta(milliseconds=100), "valid_until": NOW + timedelta(seconds=2), "reason_code": None} | updates))


def context(state="fresh", **source_changes):
    trusted_target, trusted_source = target(), source(**source_changes)
    fact = capacity(state)
    challenge = LifecycleChallenge(source=trusted_source, target=trusted_target, authority_key_id="actual-authority-key",
        authority_key_revision=5, request_id="original-request", nonce="4" * 64,
        issued_at=NOW - timedelta(seconds=1), deadline=NOW + timedelta(seconds=3))
    observation = CapacityObservation(challenge_digest=sha256(challenge), request_id=challenge.request_id,
        nonce=challenge.nonce, source_digest=sha256(trusted_source), target=trusted_target,
        node_key_id=trusted_target.node_key_id, capacity=fact)
    plan = build_lifecycle_plan(challenge, observation, "spawn" if state == "fresh" else "resume")
    permit = LifecyclePermit(plan=plan, semantic_digest=lifecycle_plan_digest(plan), challenge_digest=sha256(challenge),
        observation_digest=sha256(observation), authority_key_id=challenge.authority_key_id,
        authority_key_revision=challenge.authority_key_revision, request_id=challenge.request_id, nonce=challenge.nonce,
        issued_at=NOW - timedelta(milliseconds=50), deadline=NOW + timedelta(seconds=2))
    time = SimpleNamespace(elapsed=0.0, wall=datetime(2099, 1, 1, tzinfo=UTC), available=True)

    def authority_now():
        if not time.available:
            raise OSError("controlled Authority unavailable")
        return NOW + timedelta(seconds=time.elapsed)

    clock = ConnectionClock("actual-authority-reference", authority_now,
        identity={"authority_id": "authority", "authority_incarnation": "incarnation"},
        monotonic=lambda: time.elapsed, wall=lambda: time.wall)
    authorized = []

    def authorize(stage, actual_source, actual_target):
        assert actual_source == trusted_source and actual_target == trusted_target
        authorized.append(stage)

    return SimpleNamespace(source=trusted_source, target=trusted_target, fact=fact, challenge=challenge,
        observation=observation, plan=plan, permit=permit, clock=clock, time=time, authorize=authorize, authorized=authorized)


def challenge_args(f, **updates):
    return {"expected_source": f.source, "actual_target": f.target, "authority_key_id": "actual-authority-key",
        "authority_key_revision": 5, "authority_public_key": public_key(AUTHORITY_KEY),
        "clock": f.clock, "authorize_current": f.authorize} | updates


def observation_args(f, **updates):
    return {"challenge": f.challenge, "expected_source": f.source, "actual_target": f.target,
        "node_public_key": public_key(NODE_KEY), "clock": f.clock, "authorize_current": f.authorize} | updates


def permit_args(f, **updates):
    return challenge_args(f) | {"challenge": f.challenge, "observation": f.observation, "actual_capacity": f.fact} | updates


def receipt(f, **updates):
    session = f.fact.native_session_ref or "controlled-created-session"
    return LifecycleReceipt(**({"source": f.source, "target": f.target, "driver_operation_id": f.plan.driver_operation_id,
        "action": f.plan.action, "permit_digest": sha256(f.permit), "semantic_digest": f.permit.semantic_digest,
        "request_id": f.permit.request_id, "nonce": f.permit.nonce, "node_key_id": f.target.node_key_id,
        "outcome": "acknowledged", "effect_possible": True, "evidence_refs": ("controlled:original-driver-ack",),
        "native_session_ref": session, "provider_generation": native_generation(f.fact.driver_binding_id, asdict(BINDING), session),
        "reason_code": None, "observed_at": NOW, "issued_at": NOW, "deadline": NOW + timedelta(seconds=2)} | updates))


def receipt_args(f, **updates):
    return {"permit": f.permit, "expected_source": f.source, "actual_target": f.target,
        "node_public_key": public_key(NODE_KEY), "clock": f.clock, "authorize_current": f.authorize} | updates


@pytest.mark.parametrize("state", ["fresh", "existing"])
def test_actual_ed25519_full_chain_separates_business_identity_and_transport(state):
    f = context(state)
    assert f.target.binding_epoch == 13 and f.target.registration.endpoint_revision == 3
    assert verify_challenge(sign_challenge(f.challenge, AUTHORITY_KEY), **challenge_args(f)) == f.challenge
    assert verify_observation(sign_observation(f.observation, NODE_KEY), **observation_args(f)) == f.observation
    operation = verify_permit(sign_permit(f.permit, AUTHORITY_KEY), **permit_args(f))
    operation.validate(f.clock)
    assert operation.source_ref == f.source.operation_ref and operation.deadline is None
    assert not hasattr(operation, "message_id") and not hasattr(f.permit, "attempt_id")
    result = receipt(f)
    assert verify_receipt(sign_receipt(result, NODE_KEY), **receipt_args(f)) == result
    assert f.authorized == ["challenge", "observation", "permit", "receipt"]


def test_clock_uses_authenticated_authority_despite_host_wall_skew():
    f = context()
    f.time.wall -= timedelta(days=30000)
    assert verify_challenge(sign_challenge(f.challenge, AUTHORITY_KEY), **challenge_args(f)) == f.challenge
    f.time.wall += timedelta(days=50000)
    assert verify_permit(sign_permit(f.permit, AUTHORITY_KEY), **permit_args(f)).deadline is None


@pytest.mark.parametrize("stage", ["challenge", "observation", "permit", "receipt"])
def test_wrong_installed_signer_and_signature_tamper_fail(stage):
    f = context()
    functions = {"challenge": (sign_challenge, verify_challenge, f.challenge, challenge_args(f)),
        "observation": (sign_observation, verify_observation, f.observation, observation_args(f)),
        "permit": (sign_permit, verify_permit, f.permit, permit_args(f)),
        "receipt": (sign_receipt, verify_receipt, receipt(f), receipt_args(f))}
    signing, checking, body, args = functions[stage]
    with pytest.raises(LifecycleContractRejected, match="signature_rejected"):
        checking(signing(body, OTHER_KEY), **args)
    key = AUTHORITY_KEY if stage in {"challenge", "permit"} else NODE_KEY
    with pytest.raises(LifecycleContractRejected, match="signature_rejected"):
        checking(signing(body, key).model_copy(update={"signature": "0" * 128}), **args)
    assert f.authorized == []


@pytest.mark.parametrize("field,value", [("nonce", "5" * 64), ("request_id", "another-request"),
    ("source_digest", "0" * 64), ("challenge_digest", "0" * 64)])
def test_valid_node_signature_cannot_change_challenge_correlation(field, value):
    f = context()
    changed = f.observation.model_copy(update={field: value})
    with pytest.raises(LifecycleContractRejected, match="observation_binding_changed"):
        verify_observation(sign_observation(changed, NODE_KEY), **observation_args(f))


@pytest.mark.parametrize("field,value", [("binding_epoch", 14), ("connection_revision", 5),
    ("journal_generation", 3), ("node_key_id", "another-node-key")])
def test_actual_target_all_version_domains_are_independent_and_exact(field, value):
    f = context()
    changed = f.target.model_copy(update={field: value})
    with pytest.raises(LifecycleContractRejected, match="challenge_binding_changed"):
        verify_challenge(sign_challenge(f.challenge, AUTHORITY_KEY), **challenge_args(f, actual_target=changed))
    with pytest.raises(LifecycleContractRejected, match="permit_binding_changed"):
        verify_permit(sign_permit(f.permit, AUTHORITY_KEY), **permit_args(f, actual_target=changed))


@pytest.mark.parametrize("field,value", [("endpoint_revision", 4), ("node_binding_revision", 8),
    ("runtime_revision", 10), ("boot_incarnation", "another-boot"), ("scope_id", "another-scope"),
    ("machine_id", "another-host"), ("agent_slot_id", "another-slot")])
def test_challenge_cannot_target_another_registered_binding(field, value):
    f = context()
    changed = f.target.model_copy(update={"registration": f.target.registration.model_copy(update={field: value})})
    with pytest.raises(LifecycleContractRejected):
        verify_challenge(sign_challenge(f.challenge, AUTHORITY_KEY), **challenge_args(f, actual_target=changed))


@pytest.mark.parametrize("field,value", [("operation_ref", "another-operation"), ("command_id", "another-command"),
    ("project_id", "another-project"), ("actor_address", "collaborator:project:other-slot"),
    ("principal_ref", "another-principal"), ("grant_ref", "replacement-grant"), ("profile", "engineer"),
    ("command_digest", "0" * 64), ("issuer_context_digest", "0" * 64), ("request_digest", "0" * 64)])
def test_original_source_identity_and_digests_cannot_be_substituted(field, value):
    f = context()
    changed = f.source.model_copy(update={field: value})
    with pytest.raises(LifecycleContractRejected):
        verify_permit(sign_permit(f.permit, AUTHORITY_KEY), **permit_args(f, expected_source=changed))


@pytest.mark.parametrize("missing", [None, False, True])
def test_no_callable_current_authority_is_not_a_permission(missing):
    f = context()
    with pytest.raises(LifecycleContractRejected, match="current_authority_required"):
        verify_permit(sign_permit(f.permit, AUTHORITY_KEY), **permit_args(f, authorize_current=missing))


@pytest.mark.parametrize("returned", [False, True, {"verified": True}])
def test_callback_boolean_or_fake_verified_result_is_rejected(returned):
    f = context()
    with pytest.raises(LifecycleContractRejected, match="current_authority_rejected"):
        verify_challenge(sign_challenge(f.challenge, AUTHORITY_KEY), **challenge_args(f, authorize_current=lambda *_: returned))


@pytest.mark.parametrize("stage", ["challenge", "observation", "permit", "receipt"])
def test_expiry_during_authorization_wait_is_rechecked(stage):
    f = context()

    def waited(*_args):
        f.time.elapsed = 5

    checks = {"challenge": (verify_challenge, sign_challenge(f.challenge, AUTHORITY_KEY), challenge_args(f)),
        "observation": (verify_observation, sign_observation(f.observation, NODE_KEY), observation_args(f)),
        "permit": (verify_permit, sign_permit(f.permit, AUTHORITY_KEY), permit_args(f)),
        "receipt": (verify_receipt, sign_receipt(receipt(f), NODE_KEY), receipt_args(f))}
    checking, signed, args = checks[stage]
    with pytest.raises(LifecycleContractRejected, match="expired_or_uncertain"):
        checking(signed, **(args | {"authorize_current": waited}))


def test_clock_unavailable_wrong_identity_or_untrusted_wall_only_is_rejected():
    f = context()
    f.time.available = False
    with pytest.raises(LifecycleContractRejected, match="expired_or_uncertain"):
        verify_challenge(sign_challenge(f.challenge, AUTHORITY_KEY), **challenge_args(f))
    with pytest.raises(LifecycleContractRejected, match="clock_required"):
        verify_challenge(sign_challenge(f.challenge, AUTHORITY_KEY), **challenge_args(f, clock=lambda: NOW))
    other = ConnectionClock.local(reference=lambda: NOW, identity={"authority_id": "other", "authority_incarnation": "incarnation"})
    with pytest.raises(LifecycleContractRejected, match="clock_changed"):
        verify_challenge(sign_challenge(f.challenge, AUTHORITY_KEY), **challenge_args(f, clock=other))


@pytest.mark.parametrize("state,changes", [("fresh", {"kernel_claim_ref": None}), ("fresh", {"absence_evidence_ref": None}),
    ("fresh", {"journal_state": "unresolved"}), ("fresh", {"profile_evidence_ref": None}),
    ("existing", {"process": None}), ("existing", {"provider_generation": "peer-hash-is-not-generation"}),
    ("existing", {"profile_fingerprint": None})])
def test_none_or_arbitrary_values_are_not_positive_capacity_evidence(state, changes):
    with pytest.raises(ValidationError):
        capacity(state, **changes)


def test_unknown_can_retain_positive_presence_but_never_make_mutable_plan():
    f = context("existing")
    unknown = capacity("existing").model_copy(update={"state": "unknown", "reason_code": "profile_unavailable",
        "profile_fingerprint": None, "profile_evidence_ref": None, "journal_state": "unknown"})
    restored = LifecycleCapacityFact.model_validate_json(unknown.model_dump_json())
    assert restored.process is not None and restored.native_session_ref == f.fact.native_session_ref
    observation = f.observation.model_copy(update={"capacity": restored})
    with pytest.raises(ValidationError):
        build_lifecycle_plan(f.challenge, observation, "resume")


@pytest.mark.parametrize("changes", [{"journal_state": "unresolved"}, {"input_state": "busy"},
    {"blocker": "approval"}, {"blocker": "question"}, {"blocker": "draft"}, {"blocker": "unknown"}])
def test_existing_positive_facts_never_override_journal_readiness_or_human_blocker(changes):
    f = context("existing")
    fact = capacity("existing", **changes)
    assert fact.state == "existing" and fact.process is not None
    with pytest.raises(ValidationError):
        build_lifecycle_plan(f.challenge, f.observation.model_copy(update={"capacity": fact}), "resume")


@pytest.mark.parametrize("field,value", [("profile_fingerprint", "0" * 64), ("journal_state", "unresolved"),
    ("input_state", "busy"), ("blocker", "draft")])
def test_permit_rechecks_current_actual_capacity_before_driver_authority(field, value):
    f = context("existing")
    changed = capacity("existing", **{field: value})
    with pytest.raises(LifecycleContractRejected, match="permit_binding_changed"):
        verify_permit(sign_permit(f.permit, AUTHORITY_KEY), **permit_args(f, actual_capacity=changed))


def test_current_capacity_freshness_never_renews_expired_original_observation():
    f = context()
    f.time.elapsed = 5
    fresh = capacity(observed_at=NOW + timedelta(seconds=5), valid_until=NOW + timedelta(seconds=7))
    renewed = f.permit.model_copy(update={"issued_at": NOW + timedelta(seconds=5), "deadline": NOW + timedelta(seconds=7)})
    with pytest.raises(LifecycleContractRejected, match="expired_or_uncertain"):
        verify_permit(sign_permit(renewed, AUTHORITY_KEY), **permit_args(f, actual_capacity=fresh))


def test_live_permit_uses_fresh_same_capacity_after_initial_planning_snapshot_expires():
    f = context("existing")
    f.time.elapsed = 2.4
    fresh = capacity("existing", observed_at=NOW+timedelta(seconds=2.4), valid_until=NOW+timedelta(seconds=4.4))
    permit = f.permit.model_copy(update={"deadline": NOW+timedelta(seconds=2.9)})
    operation = verify_permit(sign_permit(permit, AUTHORITY_KEY), **permit_args(f, actual_capacity=fresh))
    assert operation.operation_id == to_driver_operation(f.plan).operation_id
    assert operation.native_session_ref == f.fact.native_session_ref


@pytest.mark.parametrize("change", ["permit_expired", "current_snapshot_expired", "blocker", "session"])
def test_planning_snapshot_cannot_bypass_current_lease_or_native_generation(change):
    f = context("existing")
    f.time.elapsed = 2.4
    fresh = capacity("existing", observed_at=NOW+timedelta(seconds=2.4), valid_until=NOW+timedelta(seconds=4.4))
    permit = f.permit.model_copy(update={"deadline": NOW+timedelta(seconds=2.9)})
    if change == "permit_expired":
        f.time.elapsed = 3
    elif change == "current_snapshot_expired":
        fresh = f.fact
    elif change == "blocker":
        fresh = fresh.model_copy(update={"blocker": "draft"})
    else:
        fresh = fresh.model_copy(update={"native_session_ref": "another-session",
            "provider_generation": native_generation(f.fact.driver_binding_id, asdict(BINDING), "another-session")})
    with pytest.raises(LifecycleContractRejected):
        verify_permit(sign_permit(permit, AUTHORITY_KEY), **permit_args(f, actual_capacity=fresh))


def test_timestamps_and_new_witness_refs_do_not_change_stable_driver_semantic_identity():
    f = context()
    newer = f.fact.model_copy(update={"observed_at": NOW, "valid_until": NOW + timedelta(seconds=3)})
    assert capacity_semantic_digest(newer) == capacity_semantic_digest(f.fact)
    renewed_plan = f.plan.model_copy(update={"capacity": newer})
    assert lifecycle_plan_digest(renewed_plan) == lifecycle_plan_digest(f.plan)
    assert to_driver_operation(renewed_plan) == to_driver_operation(f.plan)
    explicit = context(business_deadline=NOW + timedelta(seconds=1))
    assert to_driver_operation(explicit.plan).deadline == explicit.source.business_deadline


def test_short_transport_renewal_does_not_rewrite_business_deadline_or_operation_id():
    f = context()
    renewed = f.permit.model_copy(update={"issued_at": NOW, "deadline": NOW + timedelta(seconds=1)})
    assert sha256(renewed) != sha256(f.permit)
    assert renewed.semantic_digest == f.permit.semantic_digest
    assert to_driver_operation(renewed.plan) == to_driver_operation(f.permit.plan)


@pytest.mark.parametrize("changes", [{"effect_possible": False}, {"reason_code": None}])
def test_unknown_receipt_never_claims_no_effect_or_omits_reason(changes):
    f = context()
    with pytest.raises(ValidationError):
        receipt(f, **({"outcome": "unknown", "reason_code": "native_result_unknown"} | changes))


def test_late_original_ack_is_preserved_without_requiring_expired_mutation_permit():
    f = context("existing")
    f.time.elapsed = 50
    late = receipt(f, observed_at=NOW + timedelta(seconds=49), issued_at=NOW + timedelta(seconds=50),
                   deadline=NOW + timedelta(seconds=52))
    assert verify_receipt(sign_receipt(late, NODE_KEY), **receipt_args(f)).outcome == "acknowledged"
    assert f.authorized == ["receipt"]
    with pytest.raises(LifecycleContractRejected):
        verify_receipt(sign_receipt(late, NODE_KEY), **receipt_args(f, actual_target=f.target.model_copy(update={"binding_epoch": 14})))


def test_positive_resume_receipt_cannot_complete_another_native_session():
    f = context("existing")
    replacement = "another-session"
    changed = receipt(f, native_session_ref=replacement,
        provider_generation=native_generation(f.fact.driver_binding_id, asdict(BINDING), replacement))
    with pytest.raises(LifecycleContractRejected, match="generation_changed"):
        verify_receipt(sign_receipt(changed, NODE_KEY), **receipt_args(f))


@pytest.mark.parametrize("field", ["message_id", "attempt_id", "dispatch_id", "verified", "signing_key", "provider_url"])
def test_signed_contracts_forbid_fabricated_delivery_or_permission_fields(field):
    f = context()
    with pytest.raises(ValidationError):
        LifecyclePermit.model_validate_json(f.permit.model_dump_json()[:-1] + ',"' + field + '":"forged"}')


def test_signing_key_must_be_trusted_programmatic_key_not_body_text():
    with pytest.raises(TypeError, match="installed private"):
        sign_challenge(context().challenge, AUTHORITY_KEY.encode().hex())


@pytest.mark.parametrize("changes", [{"deadline": NOW + timedelta(seconds=31)}, {"deadline": NOW - timedelta(seconds=1)},
    {"authority_key_revision": True}, {"issued_at": NOW.replace(tzinfo=None)}])
def test_transport_windows_and_types_are_strict(changes):
    f = context()
    raw = json.loads(f.challenge.model_dump_json()) | {key: value.isoformat() if isinstance(value, datetime) else value
                                                     for key, value in changes.items()}
    with pytest.raises(ValidationError):
        LifecycleChallenge.model_validate_json(json.dumps(raw), strict=True)


def test_frozen_body_tamper_after_model_copy_is_revalidated_before_crypto_or_callback():
    f = context()
    corrupt = f.permit.model_copy(update={"semantic_digest": "0" * 64})
    with pytest.raises(LifecycleContractRejected, match="contract_invalid"):
        sign_permit(corrupt, AUTHORITY_KEY)
    assert f.authorized == []


def test_unvalidated_boolean_revision_cannot_be_normalized_into_a_signed_integer():
    f = context()
    corrupt = f.challenge.model_copy(update={"authority_key_revision": True})
    with pytest.raises(LifecycleContractRejected, match="contract_invalid"):
        sign_challenge(corrupt, AUTHORITY_KEY)
