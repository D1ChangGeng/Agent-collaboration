"""Evidence-bearing receiver contracts shared by Native, MCP and HTTP adapters.

These DTOs are observations, never authorization or permission to retry an input.
The existing endpoint revision is the receiving epoch; a Native binding/session
generation is independently pinned. No new message or identity authority exists.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Reference = Annotated[str, Field(min_length=1, max_length=512)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Epoch = Annotated[int, Field(ge=0)]
Knowledge = Literal["observed", "inferred", "unknown", "unsupported"]
Support = Literal["supported", "unsupported", "unknown"]
Availability = Literal["available", "temporarily_unavailable", "unknown"]
Axis = Literal["connection", "process", "session", "input", "blocker"]
CAPABILITY_NAMES = (
    "native.structured_input", "native.operation_lookup", "native.idempotency",
    "native.safe_busy_enqueue", "native.safe_steer", "native.session_resume",
    "native.receiver_prepare", "native.input_consumed", "native.observe_stream",
    "native.transcript_read", "native.approval_roundtrip", "native.attachment_delivery",
    "native.terminal_pointer", "native.rebind_fence",
)
AXES: tuple[Axis, ...] = ("connection", "process", "session", "input", "blocker")


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _aware(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("evidence comparison requires an aware clock")


class ReceiverBinding(Contract):
    receiver_id: Reference
    actor_address: Reference
    binding_epoch: Epoch
    provider_generation: Reference | None
    native_session_ref: Reference | None
    authority_id: Reference
    authority_incarnation: Reference
    execution_host_ref: Reference


class NativeHandoffContext(Contract):
    """Internal evidence bound into the existing Driver operation transaction."""

    schema_version: Literal["acs-native-handoff/1"]
    operation_id: Reference
    command_id: Reference
    message_id: Reference
    message_handle: Reference
    receiver_id: Reference
    actor_address: Reference
    authority_id: Reference
    authority_incarnation: Reference
    binding_epoch: Epoch
    provider_generation: Reference
    native_session_ref: Reference
    driver_binding_id: Reference
    canonical_hash: Digest
    input_digest: Digest
    selection_digest: Digest
    auth_revision: Digest


def native_generation(binding_id: str, identity: dict, session: str | None) -> str:
    return hashlib.sha256(json.dumps({"binding_id": binding_id, "identity": identity,
        "session": session}, sort_keys=True).encode()).hexdigest()


class Capability(Contract):
    model_config = ConfigDict(json_schema_extra={"allOf": [
        {"if": {"properties": {"support": {"const": "supported"}}},
         "then": {"properties": {"evidence_ref": {"type": "string", "minLength": 1}}}},
        {"if": {"properties": {"availability": {"const": "available"}}},
         "then": {"properties": {"support": {"const": "supported"}}}},
    ]})
    name: Literal[*CAPABILITY_NAMES]
    support: Support
    availability: Availability
    evidence_ref: Reference | None
    valid_until: AwareDatetime | None
    conditions: tuple[str, ...] = Field(max_length=32)

    @model_validator(mode="after")
    def evidence_invariants(self):
        if self.name not in CAPABILITY_NAMES:
            raise ValueError("unregistered receiver capability")
        if self.support == "supported" and self.evidence_ref is None:
            raise ValueError("supported capability requires evidence")
        if self.availability == "available" and self.support != "supported":
            raise ValueError("availability cannot imply unproven support")
        return self

    def current(self, now: datetime, *, scope_current: bool = True) -> Capability:
        _aware(now)
        reason = None
        if not scope_current:
            reason = "capability_scope_changed"
        elif self.valid_until is None and self.support != "unknown":
            reason = "capability_freshness_unknown"
        elif self.valid_until is not None and now >= self.valid_until:
            reason = "capability_expired"
        if reason:
            return self.model_copy(update={"support": "unknown", "availability": "unknown",
                "conditions": tuple(dict.fromkeys((*self.conditions, reason)))})
        return self


class CapabilityScope(Contract):
    adapter_id: Reference
    adapter_version: Reference
    harness_kind: Reference
    harness_version: Reference | None
    execution_host_ref: Reference
    binary_digest: Digest | None
    config_digest: Digest | None
    connection_epoch: Epoch
    provider_generation: Reference | None

    @property
    def complete(self) -> bool:
        return all(value is not None for value in (
            self.harness_version, self.binary_digest, self.config_digest, self.provider_generation,
        ))


class Observation(Contract):
    model_config = ConfigDict(json_schema_extra={"allOf": [
        {"if": {"properties": {"knowledge": {"enum": ["unknown", "unsupported"]}}},
         "then": {"properties": {"value": {"type": "null"}}}},
        {"if": {"properties": {"knowledge": {"enum": ["observed", "inferred"]}}},
         "then": {"properties": {"value": {"type": "string"},
             "observed_at": {"type": "string", "format": "date-time"},
             "evidence_ref": {"type": "string", "minLength": 1},
             "source": {"not": {"const": "none"}}}}},
        {"if": {"properties": {"source": {"const": "pty_heuristic"}}},
         "then": {"properties": {"knowledge": {"const": "inferred"}}}},
    ]})
    knowledge: Knowledge
    axis: Axis
    value: str | None
    source: Literal["authority", "native_api", "authenticated_hook", "pty_heuristic", "none"]
    observed_at: AwareDatetime | None
    expires_at: AwareDatetime | None
    binding_epoch: Epoch
    provider_generation: Reference | None
    evidence_ref: Reference | None
    reason_code: str | None

    @model_validator(mode="after")
    def evidence_invariants(self):
        if self.knowledge in {"unknown", "unsupported"} and self.value is not None:
            raise ValueError("unknown or unsupported observation has no asserted value")
        if self.knowledge in {"observed", "inferred"}:
            if self.observed_at is None or self.evidence_ref is None or self.value is None:
                raise ValueError("known observation requires value, time and evidence")
            if self.source == "none":
                raise ValueError("known observation requires a source")
        if self.source == "pty_heuristic" and self.knowledge != "inferred":
            raise ValueError("terminal heuristics are inferences")
        if (self.observed_at is not None and self.expires_at is not None
                and self.expires_at <= self.observed_at):
            raise ValueError("observation expiry must follow its observation")
        return self

    def unknown(self, reason: str) -> Observation:
        return self.model_copy(update={"knowledge": "unknown", "value": None, "source": "none",
                                      "reason_code": reason})

    def current(self, now: datetime, *, epoch: int, generation: str | None) -> Observation:
        _aware(now)
        if self.binding_epoch != epoch or self.provider_generation != generation:
            return self.unknown("receiver_generation_changed")
        if self.knowledge in {"observed", "inferred"}:
            if self.observed_at > now:
                return self.unknown("observation_from_future")
            if self.expires_at is None:
                return self.unknown("observation_freshness_unknown")
            if now >= self.expires_at:
                return self.unknown("observation_expired")
        return self


class ReceiverSnapshot(Contract):
    receiver_id: Reference
    address: Reference
    binding_epoch: Epoch
    revision: Epoch
    native_session_ref: Reference | None
    capability_scope: CapabilityScope
    capabilities: tuple[Capability, ...] = Field(max_length=len(CAPABILITY_NAMES))
    observations: tuple[Observation, ...] = Field(max_length=len(AXES))
    allowed_actions: tuple[str, ...] = Field(max_length=32)

    @model_validator(mode="after")
    def unique_and_bound(self):
        if len({c.name for c in self.capabilities}) != len(self.capabilities):
            raise ValueError("duplicate capability")
        if len({o.axis for o in self.observations}) != len(self.observations):
            raise ValueError("conflicting observation axis; resolve before projection")
        if self.capability_scope.connection_epoch != self.binding_epoch:
            raise ValueError("capability scope belongs to another receiving epoch")
        for observation in self.observations:
            if (observation.binding_epoch != self.binding_epoch or
                    observation.provider_generation != self.capability_scope.provider_generation):
                raise ValueError("observation belongs to another receiver generation")
        return self

    def current(self, now: datetime, *, scope: CapabilityScope) -> ReceiverSnapshot:
        _aware(now)
        same = scope == self.capability_scope and scope.complete
        observations = tuple(o.current(now, epoch=scope.connection_epoch,
            generation=scope.provider_generation) if same else o.unknown("capability_scope_changed")
            for o in self.observations)
        return self.model_copy(update={
            "capabilities": tuple(c.current(now, scope_current=same) for c in self.capabilities),
            "observations": observations,
            "native_session_ref": self.native_session_ref if same else None,
            "allowed_actions": self.allowed_actions if same else (),
        })


class SealedEnvelope(Contract):
    format: Reference
    encoding: Literal["base64"]
    data: Annotated[str, Field(min_length=1, max_length=2 * 1024 * 1024)]

    @model_validator(mode="after")
    def valid_encoding(self):
        try:
            decoded = base64.b64decode(self.data, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError("invalid sealed envelope encoding") from error
        if not decoded:
            raise ValueError("empty sealed envelope")
        return self


class NativeAdmissionCommand(Contract):
    schema_version: Literal["acs-adapter/1"]
    operation_id: Reference
    receiver_id: Reference
    message_handles: tuple[Reference, ...] = Field(min_length=1, max_length=32,
                                                json_schema_extra={"uniqueItems": True})
    canonical_hash: Digest
    binding_epoch: Epoch
    provider_generation: Reference | None
    auth_revision: Reference
    input_mode: Literal["structured", "safe_queue", "terminal_pointer"]
    sealed_envelope: SealedEnvelope
    deadline: AwareDatetime | None

    @model_validator(mode="after")
    def unique_messages(self):
        if len(set(self.message_handles)) != len(self.message_handles):
            raise ValueError("duplicate message handle")
        return self


class NativeAdmissionResult(Contract):
    model_config = ConfigDict(json_schema_extra={"allOf": [
        {"if": {"properties": {"outcome": {"enum": ["accepted", "queued", "definitively_not_admitted"]}}},
         "then": {"properties": {"evidence_ref": {"type": "string", "minLength": 1}}}},
        {"if": {"properties": {"outcome": {"enum": ["unsupported", "definitively_not_admitted"]}}},
         "then": {"properties": {"effect_possible": {"const": False}}}},
        {"if": {"properties": {"outcome": {"enum": ["accepted", "queued", "unknown"]}}},
         "then": {"properties": {"effect_possible": {"const": True}}}},
    ]})
    schema_version: Literal["acs-adapter/1"]
    operation_id: Reference
    outcome: Literal["accepted", "queued", "definitively_not_admitted", "unknown", "unsupported"]
    effect_possible: bool
    evidence_ref: Reference | None
    native_input_ref: Reference | None
    binding_epoch: Epoch
    provider_generation: Reference | None
    reason_code: str | None

    @model_validator(mode="after")
    def effect_invariants(self):
        if self.outcome in {"accepted", "queued", "definitively_not_admitted"} and not self.evidence_ref:
            raise ValueError("definite input outcome requires evidence")
        if self.effect_possible != (self.outcome in {"accepted", "queued", "unknown"}):
            raise ValueError("input outcome cannot hide a possible Native effect")
        return self


def unknown_capabilities() -> tuple[Capability, ...]:
    return tuple(Capability(name=name, support="unknown", availability="unknown", evidence_ref=None,
                            valid_until=None, conditions=()) for name in CAPABILITY_NAMES)


def unknown_observations(epoch: int, generation: str | None, reason: str) -> tuple[Observation, ...]:
    return tuple(Observation(axis=axis, knowledge="unknown", value=None, source="none",
        observed_at=None, expires_at=None, binding_epoch=epoch, provider_generation=generation,
        evidence_ref=None, reason_code=reason) for axis in AXES)


def input_decision(snapshot: ReceiverSnapshot, *, now: datetime,
                   scope: CapabilityScope) -> Literal["structured", "safe_queue", "deferred", "unsupported"]:
    """Conservative policy hint. The receiver must still authorize/fence/journal."""
    current = snapshot.current(now, scope=scope)
    capabilities = {c.name: c for c in current.capabilities}
    structured = capabilities.get("native.structured_input")
    if structured is not None and structured.support == "unsupported":
        return "unsupported"
    if structured is None or (structured.support, structured.availability) != ("supported", "available"):
        return "deferred"
    observations = {o.axis: o for o in current.observations}
    # Every independent axis must be current and positively observed. Inferred
    # quietness, missing blockers and process presence cannot establish readiness.
    expected = {"connection": "connected", "process": "present", "session": "present", "blocker": "none"}
    if any(axis not in observations or observations[axis].knowledge != "observed"
           or observations[axis].value != value for axis, value in expected.items()):
        return "deferred"
    readiness = observations.get("input")
    if readiness is None or readiness.knowledge != "observed":
        return "deferred"
    if readiness.value == "ready":
        return "structured"
    enqueue = capabilities.get("native.safe_busy_enqueue")
    if (readiness.value == "busy" and enqueue is not None
            and (enqueue.support, enqueue.availability) == ("supported", "available")):
        return "safe_queue"
    return "deferred"
