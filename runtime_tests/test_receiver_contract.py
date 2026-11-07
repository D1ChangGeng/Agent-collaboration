"""Evidence expiry, scope drift and safe input policy; synthetic contract fixtures."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from runtime.receiver_contract import (
    AXES,
    Capability,
    CapabilityScope,
    NativeAdmissionCommand,
    NativeAdmissionResult,
    Observation,
    ReceiverSnapshot,
    input_decision,
    unknown_capabilities,
    unknown_observations,
)

NOW = datetime(2026, 11, 6, tzinfo=UTC)
EXPIRES = NOW + timedelta(seconds=2)


def snapshot(*, readiness="ready", blocker="none", queue=False):
    scope = CapabilityScope(adapter_id="fixture-adapter", adapter_version="1", harness_kind="fixture",
        harness_version="1.0.0", execution_host_ref="fixture-host", binary_digest="a" * 64,
        config_digest="b" * 64, connection_epoch=7, provider_generation="fixture-generation")
    capabilities = tuple(capability.model_copy(update={"support": "supported", "availability": "available",
        "evidence_ref": "fixture:verified", "valid_until": EXPIRES})
        if capability.name in {"native.structured_input", *( {"native.safe_busy_enqueue"} if queue else set())}
        else capability for capability in unknown_capabilities())
    values = {"connection": "connected", "process": "present", "session": "present",
              "input": readiness, "blocker": blocker}
    observations = tuple(Observation(axis=axis, knowledge="observed", value=values[axis], source="native_api",
        observed_at=NOW, expires_at=EXPIRES, binding_epoch=7, provider_generation="fixture-generation",
        evidence_ref="fixture:readback", reason_code=None) for axis in AXES)
    return ReceiverSnapshot(receiver_id="fixture-receiver", address="collaborator:p:b", binding_epoch=7,
        revision=7, native_session_ref="fixture-session", capability_scope=scope, capabilities=capabilities,
        observations=observations, allowed_actions=())


def test_all_capabilities_default_unknown_and_wire_round_trip():
    item = snapshot()
    restored = ReceiverSnapshot.model_validate_json(item.model_dump_json())
    assert item == restored
    assert len(unknown_capabilities()) == 14
    assert all(c.support == c.availability == "unknown" for c in unknown_capabilities())
    assert all(o.knowledge == "unknown" and o.value is None
               for o in unknown_observations(1, None, "unmeasured"))


@pytest.mark.parametrize("field,value", [
    ("adapter_id", "other-adapter"), ("adapter_version", "2"), ("harness_kind", "other-harness"),
    ("harness_version", "2.0.0"), ("execution_host_ref", "other-host"),
    ("binary_digest", "c" * 64), ("config_digest", "d" * 64),
    ("connection_epoch", 8), ("provider_generation", "new-generation"),
])
def test_every_version_domain_invalidates_prior_evidence(field, value):
    item = snapshot()
    changed = item.capability_scope.model_copy(update={field: value})
    current = item.current(NOW, scope=changed)
    assert all(c.support == c.availability == "unknown" for c in current.capabilities)
    assert all(o.knowledge == "unknown" and o.value is None for o in current.observations)
    assert current.native_session_ref is None and current.allowed_actions == ()
    assert input_decision(item, now=NOW, scope=changed) == "deferred"


def test_expiry_is_strict_and_does_not_destroy_historical_evidence():
    item = snapshot()
    assert input_decision(item, now=EXPIRES - timedelta(microseconds=1), scope=item.capability_scope) == "structured"
    current = item.current(EXPIRES, scope=item.capability_scope)
    assert current.observations[0].knowledge == "unknown"
    assert current.observations[0].evidence_ref == "fixture:readback"
    assert item.observations[0].knowledge == "observed"
    assert input_decision(item, now=EXPIRES, scope=item.capability_scope) == "deferred"


@pytest.mark.parametrize("blocker", ["approval", "question", "user_draft", "paused", "unknown"])
def test_ready_or_queue_support_never_overrides_a_blocker(blocker):
    item = snapshot(blocker=blocker, queue=True)
    assert input_decision(item, now=NOW, scope=item.capability_scope) == "deferred"


def test_busy_requires_verified_safe_enqueue_and_never_implies_consumed():
    busy = snapshot(readiness="busy")
    assert input_decision(busy, now=NOW, scope=busy.capability_scope) == "deferred"
    queue = snapshot(readiness="busy", queue=True)
    assert input_decision(queue, now=NOW, scope=queue.capability_scope) == "safe_queue"
    assert next(c for c in queue.capabilities if c.name == "native.input_consumed").support == "unknown"


@pytest.mark.parametrize("axis", AXES)
def test_inference_or_missing_axis_cannot_prove_safe_input(axis):
    item = snapshot()
    inferred = item.model_copy(update={"observations": tuple(o.model_copy(update={"knowledge": "inferred"})
        if o.axis == axis else o for o in item.observations)})
    assert input_decision(inferred, now=NOW, scope=item.capability_scope) == "deferred"
    missing = item.model_copy(update={"observations": tuple(o for o in item.observations if o.axis != axis)})
    assert input_decision(missing, now=NOW, scope=item.capability_scope) == "deferred"


def test_missing_freshness_and_future_observation_are_unknown():
    item = snapshot()
    observed = item.observations[0]
    assert observed.model_copy(update={"expires_at": None}).current(NOW, epoch=7,
        generation="fixture-generation").knowledge == "unknown"
    assert observed.current(NOW - timedelta(seconds=1), epoch=7,
        generation="fixture-generation").reason_code == "observation_from_future"
    supported = item.capabilities[0]
    assert supported.model_copy(update={"valid_until": None}).current(NOW).support == "unknown"


def test_unknown_binary_or_generation_cannot_qualify_a_receiver():
    item = snapshot()
    for field in ("harness_version", "binary_digest", "config_digest", "provider_generation"):
        scope = item.capability_scope.model_copy(update={field: None})
        assert input_decision(item, now=NOW, scope=scope) == "deferred"


@pytest.mark.parametrize("changes", [
    {"knowledge": "unknown"}, {"knowledge": "unsupported"},
    {"source": "none"}, {"source": "pty_heuristic"}, {"evidence_ref": None},
    {"observed_at": None}, {"observed_at": NOW.replace(tzinfo=None)}, {"expires_at": NOW},
    {"binding_epoch": True},
])
def test_invalid_observation_cannot_be_serialized(changes):
    values = snapshot().observations[0].model_dump()
    with pytest.raises(ValidationError):
        Observation.model_validate({**values, **changes})


@pytest.mark.parametrize("changes", [{"evidence_ref": None}, {"support": "unknown"},
                                       {"support": "unsupported"}, {"name": "brand-implies-idle"}])
def test_unsupported_or_unproved_capability_cannot_claim_availability(changes):
    values = snapshot().capabilities[0].model_dump()
    with pytest.raises(ValidationError):
        Capability.model_validate({**values, **changes})


def test_conflicting_or_cross_generation_observations_are_rejected():
    item = snapshot()
    values = item.model_dump()
    for observations in (
        (item.observations[0], item.observations[0]),
        (item.observations[0].model_copy(update={"binding_epoch": 8}),),
        (item.observations[0].model_copy(update={"provider_generation": "retired"}),),
    ):
        with pytest.raises(ValidationError):
            ReceiverSnapshot.model_validate({**values, "observations": observations})


@pytest.mark.parametrize("outcome,effect,evidence", [
    ("accepted", False, "fixture:ack"), ("accepted", True, None),
    ("queued", True, None), ("definitively_not_admitted", False, None),
    ("definitively_not_admitted", True, "fixture:refusal"),
    ("unknown", False, None), ("unsupported", True, None),
])
def test_outcome_never_invents_negative_evidence(outcome, effect, evidence):
    with pytest.raises(ValidationError):
        NativeAdmissionResult(schema_version="acs-adapter/1", operation_id="op", outcome=outcome,
            effect_possible=effect, evidence_ref=evidence, native_input_ref=None, binding_epoch=1,
            provider_generation="g", reason_code=None)


def test_wire_rejects_sender_injection_and_invalid_sealed_bytes():
    data = {"schema_version": "acs-adapter/1", "operation_id": "op", "receiver_id": "receiver",
        "message_handles": ["message:p:1"], "canonical_hash": "a" * 64, "binding_epoch": 1,
        "provider_generation": "g", "auth_revision": "revision-1", "input_mode": "structured",
        "sealed_envelope": {"format": "existing-envelope", "encoding": "base64", "data": "e30="}, "deadline": None}
    assert NativeAdmissionCommand.model_validate_json(json.dumps(data)).operation_id == "op"
    for invalid in ({**data, "sender": "forged"}, {**data, "message_handles": ["message:p:1"] * 2},
        {**data, "sealed_envelope": {**data["sealed_envelope"], "data": "not base64!"}}):
        with pytest.raises(ValidationError):
            NativeAdmissionCommand.model_validate_json(json.dumps(invalid))


def test_naive_comparison_clock_is_rejected():
    item = snapshot()
    with pytest.raises(ValueError, match="aware clock"):
        item.current(NOW.replace(tzinfo=None), scope=item.capability_scope)
