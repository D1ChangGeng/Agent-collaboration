"""Signed message-less lifecycle contracts, not a Node implementation.

Installed keys, actual target/capacity and current authorization are injected by
trusted Core/Node code. These helpers never open storage or contact a Host. The
existing BindingIdentity.attempt_id is the configured capacity identity, not a
DeliveryAttempt. Transport deadlines never replace a Driver business deadline.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Annotated, Literal

from nacl.signing import SigningKey
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_serializer, model_validator

from runtime.codex_driver import BindingIdentity
from runtime.connection_clock import ClockReading, ConnectionClock
from runtime.receiver_contract import native_generation
from runtime.receiver_crypto import sha256, sign, verify
from runtime.receiver_lifecycle import AuthorizedLifecycleOperation, lifecycle_operation_id
from runtime.receiver_models import EndpointRegistration

Reference = Annotated[str, Field(min_length=1, max_length=512)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Signature = Annotated[str, Field(pattern=r"^[0-9a-f]{128}$")]
Revision = Annotated[int, Field(ge=1, le=2**63 - 1)]
Action = Literal["spawn", "resume"]
MAX_TRANSPORT_SECONDS = 30


class LifecycleContractRejected(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, revalidate_instances="always")


class LifecycleSource(Contract):
    operation_ref: Reference
    command_id: Annotated[str, Field(min_length=1, max_length=256)]
    tenant_id: Reference
    authority_id: Reference
    authority_incarnation: Reference
    project_id: Reference
    actor_address: Reference
    principal_ref: Reference
    grant_ref: Annotated[str, Field(min_length=1, max_length=256)]
    profile: Reference
    command_digest: Digest
    issuer_context_digest: Digest
    request_digest: Digest
    business_deadline: AwareDatetime | None = None


class LifecycleTarget(Contract):
    registration: EndpointRegistration
    binding_epoch: Annotated[int, Field(ge=0, le=2**63 - 1)]
    connection_revision: Revision
    node_key_id: Reference
    journal_generation: Revision

    @model_validator(mode="after")
    def validate_registration(self):
        if any(type(getattr(self.registration, field)) is not int
               for field in ("endpoint_revision", "node_binding_revision", "runtime_revision")):
            raise ValueError("actual registration revisions must be strict integers")
        registration = EndpointRegistration.model_validate_json(self.registration.model_dump_json(), strict=True)
        for field in ("tenant_id", "authority_id", "authority_incarnation", "node_id", "runtime_id", "machine_id",
                      "boot_incarnation", "scope_id", "agent_slot_id"):
            value = getattr(registration, field)
            if type(value) is not str or not 1 <= len(value) <= 512:
                raise ValueError("complete bounded actual endpoint registration required")
        object.__setattr__(self, "registration", registration)
        return self


class OwnedProcessEvidence(Contract):
    pid: Annotated[int, Field(gt=0)]
    birth_ref: Reference
    containment_id: Reference
    evidence_ref: Reference


class LifecycleCapacityFact(Contract):
    state: Literal["fresh", "existing", "stopped", "unknown"]
    driver_binding_id: Reference
    binding: BindingIdentity
    profile_fingerprint: Digest | None
    profile_evidence_ref: Reference | None
    ownership: Literal["exclusive_reserved", "exclusive_owned", "unknown"]
    journal_state: Literal["clear", "unresolved", "unknown"]
    kernel_claim_ref: Reference | None
    journal_evidence_ref: Reference | None
    absence_evidence_ref: Reference | None
    process: OwnedProcessEvidence | None
    native_session_ref: Reference | None
    provider_generation: Reference | None
    input_state: Literal["ready", "busy", "not_started", "unknown"]
    blocker: Literal["none", "approval", "question", "draft", "unknown"]
    evidence_refs: tuple[Reference, ...] = Field(max_length=32)
    observed_at: AwareDatetime
    valid_until: AwareDatetime
    reason_code: Reference | None

    @model_validator(mode="after")
    def positive_evidence(self):
        if type(self.binding) is not BindingIdentity:
            raise ValueError("actual Driver BindingIdentity required")
        self.binding.validate()
        if not 0 < (self.valid_until - self.observed_at).total_seconds() <= MAX_TRANSPORT_SECONDS:
            raise ValueError("capacity freshness must be positive and bounded")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("capacity evidence references must be unique")
        if self.state == "unknown":
            if self.reason_code is None:
                raise ValueError("unknown capacity requires an honest reason")
            return self  # Known positive facts can be retained without mutable authority.
        if self.profile_fingerprint is None or self.profile_evidence_ref is None or self.kernel_claim_ref is None:
            raise ValueError("known capacity needs an actual profile/claim witness")
        required = [self.profile_evidence_ref, self.kernel_claim_ref]
        if self.state == "fresh":
            if (self.ownership != "exclusive_reserved" or self.journal_state != "clear"
                    or self.journal_evidence_ref is None or self.absence_evidence_ref is None
                    or any(value is not None for value in (self.process, self.native_session_ref, self.provider_generation))):
                raise ValueError("fresh capacity needs positive journal/ownership/absence evidence")
            required.extend((self.journal_evidence_ref, self.absence_evidence_ref))
        else:
            allowed_owner = {"exclusive_owned", "exclusive_reserved"} if self.state == "stopped" else {"exclusive_owned"}
            if (self.ownership not in allowed_owner or self.process is None or self.native_session_ref is None
                    or self.provider_generation is None or self.absence_evidence_ref is not None
                    or self.provider_generation != native_generation(self.driver_binding_id, asdict(self.binding), self.native_session_ref)):
                raise ValueError("existing capacity needs exact owned process/session/generation evidence")
            required.append(self.process.evidence_ref)
            if self.state == "stopped" and (self.journal_state not in {"clear", "unresolved"} or self.input_state != "unknown"
                    or self.blocker != "unknown" or not self.process.evidence_ref.startswith("stopped-process:")):
                raise ValueError("stopped capacity requires original termination evidence and no invented Native readiness")
        if any(reference not in self.evidence_refs for reference in required):
            raise ValueError("capacity witness reference is not in its evidence set")
        return self


def profile_fingerprint(captured_profile: dict, environment: dict[str, str]) -> str:
    if type(captured_profile) is not dict or type(environment) is not dict or any(
            type(key) is not str or type(value) is not str for key, value in environment.items()):
        raise TypeError("actual captured profile and selected environment required")
    return sha256({"profile": captured_profile, "environment": environment})


def capacity_semantic_digest(capacity: LifecycleCapacityFact) -> str:
    capacity = _wire(LifecycleCapacityFact, capacity)
    value = capacity.model_dump(mode="json")
    for field in ("observed_at", "valid_until", "evidence_refs", "profile_evidence_ref", "kernel_claim_ref",
                  "journal_evidence_ref", "absence_evidence_ref", "reason_code"):
        value.pop(field)
    if value["process"] is not None:
        value["process"].pop("evidence_ref")
    return sha256(value)


def capacity_restore_ref(capacity: LifecycleCapacityFact) -> str | None:
    return capacity.process.evidence_ref if capacity.state == "stopped" and capacity.process is not None else None


class LifecycleChallenge(Contract):
    schema_version: Literal["acs-lifecycle-challenge/1"] = "acs-lifecycle-challenge/1"
    purpose: Literal["receiver.lifecycle.observe"] = "receiver.lifecycle.observe"
    source: LifecycleSource
    target: LifecycleTarget
    authority_key_id: Reference
    authority_key_revision: Revision
    request_id: Reference
    nonce: Digest
    issued_at: AwareDatetime
    deadline: AwareDatetime

    @model_validator(mode="after")
    def bounded_source(self):
        _source_target(self.source, self.target)
        _bounded(self.issued_at, self.deadline)
        return self


class SignedLifecycleChallenge(Contract):
    challenge: LifecycleChallenge
    signature: Signature


class CapacityObservation(Contract):
    schema_version: Literal["acs-lifecycle-observation/1"] = "acs-lifecycle-observation/1"
    purpose: Literal["receiver.lifecycle.capacity"] = "receiver.lifecycle.capacity"
    challenge_digest: Digest
    request_id: Reference
    nonce: Digest
    source_digest: Digest
    target: LifecycleTarget
    node_key_id: Reference
    capacity: LifecycleCapacityFact

    @model_validator(mode="after")
    def actual_capacity_subject(self):
        if self.node_key_id != self.target.node_key_id:
            raise ValueError("capacity Node signer differs from actual target")
        _capacity_target(self.capacity, self.target)
        return self


class SignedCapacityObservation(Contract):
    observation: CapacityObservation
    signature: Signature


class LifecyclePlan(Contract):
    source: LifecycleSource
    target: LifecycleTarget
    action: Action
    capacity: LifecycleCapacityFact
    driver_operation_id: Reference

    @model_validator(mode="after")
    def eligible_mutation(self):
        _source_target(self.source, self.target)
        _capacity_target(self.capacity, self.target)
        if (self.driver_operation_id != lifecycle_operation_id(self.source.operation_ref, self.action,
                    restore_process_ref=capacity_restore_ref(self.capacity))
                or self.capacity.state == "unknown" or self.capacity.state != "stopped" and self.capacity.journal_state != "clear"
                or self.capacity.journal_evidence_ref is None or self.capacity.journal_evidence_ref not in self.capacity.evidence_refs
                or self.capacity.state != "stopped" and self.capacity.blocker != "none"):
            raise ValueError("lifecycle plan requires a clear current qualified capacity")
        if ((self.action == "spawn" and (self.capacity.state != "fresh" or self.capacity.input_state != "not_started"))
                or (self.action == "resume" and self.capacity.state != "stopped" and (
                    self.capacity.state != "existing" or self.capacity.input_state != "ready"))):
            raise ValueError("lifecycle action differs from observed safe readiness")
        return self


def lifecycle_plan_digest(plan: LifecyclePlan) -> str:
    plan = _wire(LifecyclePlan, plan)
    return sha256({"source": plan.source.model_dump(mode="json"), "target": plan.target.model_dump(mode="json"),
        "action": plan.action, "driver_operation_id": plan.driver_operation_id,
        "capacity_digest": capacity_semantic_digest(plan.capacity)})


class LifecyclePermit(Contract):
    schema_version: Literal["acs-lifecycle-permit/1"] = "acs-lifecycle-permit/1"
    purpose: Literal["receiver.lifecycle.execute"] = "receiver.lifecycle.execute"
    plan: LifecyclePlan
    semantic_digest: Digest
    challenge_digest: Digest
    observation_digest: Digest
    authority_key_id: Reference
    authority_key_revision: Revision
    request_id: Reference
    nonce: Digest
    issued_at: AwareDatetime
    deadline: AwareDatetime

    @model_validator(mode="after")
    def stable_plan(self):
        _bounded(self.issued_at, self.deadline)
        if self.semantic_digest != lifecycle_plan_digest(self.plan):
            raise ValueError("permit differs from its stable semantic plan")
        return self


class SignedLifecyclePermit(Contract):
    permit: LifecyclePermit
    signature: Signature


class LifecycleReceipt(Contract):
    schema_version: Literal["acs-lifecycle-receipt/1"] = "acs-lifecycle-receipt/1"
    purpose: Literal["receiver.lifecycle.result"] = "receiver.lifecycle.result"
    source: LifecycleSource
    target: LifecycleTarget
    driver_operation_id: Reference
    action: Action
    permit_digest: Digest
    semantic_digest: Digest
    request_id: Reference
    nonce: Digest
    node_key_id: Reference
    outcome: Literal["acknowledged", "definitively_not_started", "unknown"]
    effect_possible: bool
    evidence_refs: tuple[Reference, ...] = Field(min_length=1, max_length=32)
    native_session_ref: Reference | None
    provider_generation: Reference | None
    reason_code: Reference | None
    observed_at: AwareDatetime
    issued_at: AwareDatetime
    deadline: AwareDatetime
    restore_process_ref: Reference | None = None

    @model_serializer(mode="wrap")
    def legacy_compatible_fields(self, serialize):
        value = serialize(self)
        if self.restore_process_ref is None:
            value.pop("restore_process_ref", None)
        return value

    @model_validator(mode="after")
    def honest_result(self):
        _source_target(self.source, self.target)
        _bounded(self.issued_at, self.deadline)
        if (self.node_key_id != self.target.node_key_id
                or self.driver_operation_id != lifecycle_operation_id(self.source.operation_ref, self.action,
                    restore_process_ref=self.restore_process_ref)
                or self.observed_at > self.issued_at):
            raise ValueError("receipt source/target/time lineage differs")
        if self.outcome == "acknowledged":
            if not self.effect_possible or self.native_session_ref is None or self.provider_generation is None:
                raise ValueError("positive lifecycle ACK needs actual session/generation evidence")
        elif self.outcome == "unknown":
            if not self.effect_possible or self.reason_code is None:
                raise ValueError("unknown lifecycle result retains possible effects and reason")
        elif self.effect_possible or self.reason_code is None:
            raise ValueError("definite pre-effect rejection needs no-effect evidence and reason")
        return self


class SignedLifecycleReceipt(Contract):
    receipt: LifecycleReceipt
    signature: Signature


def _wire(model, value):
    if type(value) is not model:
        raise LifecycleContractRejected("lifecycle_typed_contract_required")
    try:
        return model.model_validate(value, strict=True)
    except (TypeError, ValueError) as error:
        raise LifecycleContractRejected("lifecycle_contract_invalid") from error


def _bounded(issued_at, deadline):
    if not 0 < (deadline - issued_at).total_seconds() <= MAX_TRANSPORT_SECONDS:
        raise ValueError("mandatory lifecycle transport window must be positive and at most30 seconds")


def _source_target(source, target):
    registration = target.registration
    if (source.tenant_id, source.authority_id, source.authority_incarnation) != (
            registration.tenant_id, registration.authority_id, registration.authority_incarnation):
        raise ValueError("lifecycle source differs from actual Authority target")


def _capacity_target(capacity, target):
    registration, binding = target.registration, capacity.binding
    if (binding.node_id, binding.node_boot_id, binding.runtime_id, binding.agent_slot_id, binding.revision) != (
            registration.node_id, registration.boot_incarnation, registration.runtime_id,
            registration.agent_slot_id, registration.node_binding_revision):
        raise ValueError("actual Driver capacity differs from registered Node/Runtime binding")


def _current(callback: Callable, stage, source, target):
    if not callable(callback):
        raise LifecycleContractRejected("lifecycle_current_authority_required")
    try:
        if callback(stage, source, target) is not None:
            raise LifecycleContractRejected("lifecycle_current_authority_rejected")
    except Exception as error:
        raise LifecycleContractRejected("lifecycle_current_authority_rejected") from error


def _window(clock, target, issued_at, deadline):
    if not isinstance(clock, ConnectionClock):
        raise LifecycleContractRejected("lifecycle_authority_clock_required")
    registration = target.registration
    expected = {"authority_id": registration.authority_id, "authority_incarnation": registration.authority_incarnation}
    if any(clock.identity.get(key) != value for key, value in expected.items()):
        raise LifecycleContractRejected("lifecycle_authority_clock_changed")
    for key, value in (("node_id", registration.node_id), ("boot_incarnation", registration.boot_incarnation),
                       ("machine_id", registration.machine_id), ("endpoint_id", registration.endpoint_id)):
        if key in clock.identity and clock.identity[key] != value:
            raise LifecycleContractRejected("lifecycle_authority_clock_changed")
    try:
        _bounded(issued_at, deadline)
        reading = clock.require_before(deadline)
        if type(reading) is not ClockReading or issued_at > reading.latest_utc:
            raise ValueError("future or unbounded clock observation")
        return reading
    except (TypeError, ValueError) as error:
        raise LifecycleContractRejected("lifecycle_transport_expired_or_uncertain") from error


def _sign(model, field, value, key):
    if type(key) is not SigningKey:
        raise TypeError("an installed private SigningKey object is required")
    value = _wire(model.model_fields[field].annotation, value)
    return model(**{field: value, "signature": sign(key, value)})


def _signature(public_key, signature, payload):
    try:
        verify(public_key, signature, payload)
    except ValueError as error:
        raise LifecycleContractRejected("lifecycle_signature_rejected") from error


def sign_challenge(challenge, key):
    return _sign(SignedLifecycleChallenge, "challenge", challenge, key)


def sign_observation(observation, key):
    return _sign(SignedCapacityObservation, "observation", observation, key)


def sign_permit(permit, key):
    return _sign(SignedLifecyclePermit, "permit", permit, key)


def sign_receipt(receipt, key):
    return _sign(SignedLifecycleReceipt, "receipt", receipt, key)


def verify_challenge(signed, *, expected_source, actual_target, authority_key_id, authority_key_revision,
                     authority_public_key, clock, authorize_current):
    signed = _wire(SignedLifecycleChallenge, signed)
    challenge = signed.challenge
    source, target = _wire(LifecycleSource, expected_source), _wire(LifecycleTarget, actual_target)
    if (challenge.source, challenge.target, challenge.authority_key_id, challenge.authority_key_revision) != (
            source, target, authority_key_id, authority_key_revision):
        raise LifecycleContractRejected("lifecycle_challenge_binding_changed")
    _signature(authority_public_key, signed.signature, challenge)
    _window(clock, target, challenge.issued_at, challenge.deadline)
    _current(authorize_current, "challenge", source, target)
    _window(clock, target, challenge.issued_at, challenge.deadline)
    return challenge


def verify_observation(signed, *, challenge, expected_source, actual_target, node_public_key, clock, authorize_current):
    signed = _wire(SignedCapacityObservation, signed)
    challenge = _wire(LifecycleChallenge, challenge)
    source, target = _wire(LifecycleSource, expected_source), _wire(LifecycleTarget, actual_target)
    observation = signed.observation
    if ((challenge.source, challenge.target) != (source, target)
            or (observation.challenge_digest, observation.request_id, observation.nonce, observation.source_digest,
                observation.target, observation.node_key_id) !=
               (sha256(challenge), challenge.request_id, challenge.nonce, sha256(source), target, target.node_key_id)):
        raise LifecycleContractRejected("lifecycle_observation_binding_changed")
    _signature(node_public_key, signed.signature, observation)
    _window(clock, target, challenge.issued_at, challenge.deadline)
    _window(clock, target, observation.capacity.observed_at, observation.capacity.valid_until)
    _current(authorize_current, "observation", source, target)
    _window(clock, target, observation.capacity.observed_at, min(observation.capacity.valid_until, challenge.deadline))
    return observation


def build_lifecycle_plan(challenge, observation, action):
    challenge, observation = _wire(LifecycleChallenge, challenge), _wire(CapacityObservation, observation)
    if (observation.challenge_digest, observation.request_id, observation.nonce, observation.source_digest, observation.target) != (
            sha256(challenge), challenge.request_id, challenge.nonce, sha256(challenge.source), challenge.target):
        raise LifecycleContractRejected("lifecycle_observation_binding_changed")
    return LifecyclePlan(source=challenge.source, target=challenge.target, action=action, capacity=observation.capacity,
                         driver_operation_id=lifecycle_operation_id(challenge.source.operation_ref, action,
                            restore_process_ref=capacity_restore_ref(observation.capacity)))


def verify_permit(signed, *, challenge, observation, expected_source, actual_target, actual_capacity,
                  authority_key_id, authority_key_revision, authority_public_key, clock, authorize_current):
    signed = _wire(SignedLifecyclePermit, signed)
    challenge, observation = _wire(LifecycleChallenge, challenge), _wire(CapacityObservation, observation)
    source, target = _wire(LifecycleSource, expected_source), _wire(LifecycleTarget, actual_target)
    actual_capacity = _wire(LifecycleCapacityFact, actual_capacity)
    permit, plan = signed.permit, signed.permit.plan
    expected_plan = build_lifecycle_plan(challenge, observation, plan.action)
    if ((challenge.source, challenge.target) != (source, target) or plan != expected_plan
            or (permit.challenge_digest, permit.observation_digest, permit.request_id, permit.nonce,
                permit.authority_key_id, permit.authority_key_revision) !=
               (sha256(challenge), sha256(observation), challenge.request_id, challenge.nonce, authority_key_id, authority_key_revision)
            or capacity_semantic_digest(actual_capacity) != capacity_semantic_digest(plan.capacity)):
        raise LifecycleContractRejected("lifecycle_permit_binding_changed")
    _signature(authority_public_key, signed.signature, permit)
    _window(clock, target, permit.issued_at, permit.deadline)
    require_fresh_capacity_at_issuance(plan.capacity, permit.issued_at)
    _window(clock, target, challenge.issued_at, challenge.deadline)
    _window(clock, target, actual_capacity.observed_at, actual_capacity.valid_until)
    _current(authorize_current, "permit", source, target)
    deadline = min(permit.deadline, challenge.deadline, actual_capacity.valid_until,
                   *((source.business_deadline,) if source.business_deadline is not None else ()))
    _window(clock, target, permit.issued_at, deadline)
    return to_driver_operation(plan)


def require_fresh_capacity_at_issuance(capacity, issued_at):
    """The signed planning snapshot must have been live when authority was issued.

    Execution separately requires a new current snapshot of the same semantic
    capacity. This never renews an observation, permit, source or Native lease.
    """
    if not capacity.observed_at <= issued_at < capacity.valid_until:
        raise LifecycleContractRejected("lifecycle_transport_expired_or_uncertain")


def to_driver_operation(plan):
    plan = _wire(LifecyclePlan, plan)
    return AuthorizedLifecycleOperation(operation_id=plan.driver_operation_id, command_id=plan.source.command_id,
        source_ref=plan.source.operation_ref, grant_ref=plan.source.grant_ref, deadline=plan.source.business_deadline,
        action=plan.action, binding_id=plan.capacity.driver_binding_id, binding=plan.capacity.binding,
        native_session_ref=plan.capacity.native_session_ref, provider_generation=plan.capacity.provider_generation,
        restore_process_ref=capacity_restore_ref(plan.capacity))


def verify_receipt(signed, *, permit, expected_source, actual_target, node_public_key, clock, authorize_current):
    signed, permit = _wire(SignedLifecycleReceipt, signed), _wire(LifecyclePermit, permit)
    source, target = _wire(LifecycleSource, expected_source), _wire(LifecycleTarget, actual_target)
    receipt, plan = signed.receipt, permit.plan
    if ((plan.source, plan.target) != (source, target)
            or receipt.restore_process_ref != capacity_restore_ref(plan.capacity)
            or (receipt.source, receipt.target, receipt.driver_operation_id, receipt.action, receipt.permit_digest,
                receipt.semantic_digest, receipt.request_id, receipt.nonce, receipt.node_key_id) !=
               (source, target, plan.driver_operation_id, plan.action, sha256(permit), permit.semantic_digest,
                permit.request_id, permit.nonce, target.node_key_id)):
        raise LifecycleContractRejected("lifecycle_receipt_binding_changed")
    if receipt.outcome == "acknowledged":
        if receipt.provider_generation != native_generation(plan.capacity.driver_binding_id, asdict(plan.capacity.binding), receipt.native_session_ref):
            raise LifecycleContractRejected("lifecycle_receipt_generation_changed")
        if plan.action == "resume" and (receipt.native_session_ref, receipt.provider_generation) != (
                plan.capacity.native_session_ref, plan.capacity.provider_generation):
            raise LifecycleContractRejected("lifecycle_receipt_generation_changed")
    _signature(node_public_key, signed.signature, receipt)
    _window(clock, target, receipt.issued_at, receipt.deadline)
    _current(authorize_current, "receipt", source, target)
    _window(clock, target, receipt.issued_at, receipt.deadline)
    return receipt
