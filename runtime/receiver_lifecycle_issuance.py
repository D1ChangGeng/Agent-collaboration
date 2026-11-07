"""Core lifecycle issuance inside the accepted recovery operation/outbox.

Every method borrows a caller transaction and reloads its locked outbox row.
Caller must commit before sending a returned challenge/permit to a Host. No
transport, Node inspection, new ledger, connection or commit is performed here.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from nacl.signing import SigningKey
from psycopg.pq import TransactionStatus

from runtime.connection_clock import ConnectionClock
from runtime.receiver_crypto import public_key, sha256, verify
from runtime.receiver_lifecycle_contract import (
    LifecycleChallenge,
    LifecycleContractRejected,
    LifecyclePermit,
    LifecyclePlan,
    LifecycleSource,
    LifecycleTarget,
    SignedCapacityObservation,
    SignedLifecycleChallenge,
    SignedLifecyclePermit,
    build_lifecycle_plan,
    capacity_semantic_digest,
    lifecycle_plan_digest,
    sign_challenge,
    sign_permit,
    verify_challenge,
    verify_observation,
)
from runtime.receiver_lifecycle_domain import checked_lifecycle_authority, original_lifecycle_source
from runtime.receiver_recovery_operations import FINAL

SCHEMA = "acs-recovery-lifecycle/1"


class LifecycleIssuanceRejected(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class LifecycleIssuanceResult:
    kind: str
    operation: dict
    challenge: SignedLifecycleChallenge | None = None
    permit: SignedLifecyclePermit | None = None


def _typed(model, value):
    try:
        if type(value) is model:
            return model.model_validate(value, strict=True)
        if type(value) is dict:
            import json

            return model.model_validate_json(json.dumps(value), strict=True)
    except (TypeError, ValueError) as error:
        raise LifecycleIssuanceRejected("lifecycle_stored_contract_invalid") from error
    raise LifecycleIssuanceRejected("lifecycle_stored_contract_invalid")


def _transaction(cursor):
    connection = cursor.connection
    if connection.autocommit and connection.info.transaction_status != TransactionStatus.INTRANS:
        raise LifecycleIssuanceRejected("lifecycle_caller_transaction_required")
    cursor.execute("SELECT 1")  # Start an implicit parent, never commit it here.
    return connection.transaction()


def _fresh(recovery, cursor, project, operation_ref):
    payload = recovery._row(cursor, project, operation_ref, lock=True)
    operation = payload.get("operation", {})
    if (operation.get("operation_id") != operation_ref or payload.get("project_id") != project
            or operation.get("kind") != ("message_wake" if payload.get("schema_version") == "acs-message-wake/1" else "recovery")
            or operation.get("receiver_ref") != payload.get("receiver_id")
            or type(operation.get("revision")) is not int or operation["revision"] < 1):
        raise LifecycleIssuanceRejected("lifecycle_recovery_state_invalid")
    return payload


def _intent(payload):
    # Map the actual invoke Message to preparation of its configured receiver;
    # no recovery request or command is created.
    return "prepare_receiver" if payload.get("schema_version") == "acs-message-wake/1" else payload["request"]["action"]


def _state(payload):
    from runtime.receiver_rebind import lifecycle_receiver

    data = payload.get("lifecycle")
    if data is None:
        return None
    if (type(data) is not dict or data.get("schema_version") != SCHEMA
            or data.get("phase") not in {"observing", "planned", "deferred", "executing", "settled", "rebind_ready"}):
        raise LifecycleIssuanceRejected("lifecycle_recovery_state_invalid")
    source, target = _typed(LifecycleSource, data.get("source")), _typed(LifecycleTarget, data.get("target"))
    endpoint_id, epoch = lifecycle_receiver(payload)
    if (source.operation_ref != payload["operation"]["operation_id"] or source.project_id != payload["project_id"]
            or target.registration.endpoint_id != endpoint_id or target.binding_epoch != epoch):
        raise LifecycleIssuanceRejected("lifecycle_recovery_state_invalid")
    plan = data.get("plan")
    if plan is not None:
        plan = _typed(LifecyclePlan, plan)
        if (plan.source != source or plan.target != target or data.get("first_plan_digest") != lifecycle_plan_digest(plan)):
            raise LifecycleIssuanceRejected("lifecycle_stable_plan_changed")
    elif data.get("first_plan_digest") is not None:
        raise LifecycleIssuanceRejected("lifecycle_stable_plan_changed")
    return deepcopy(data)


def _possible(payload, data):
    operation = payload["operation"]
    return (operation.get("effect_state") in {"native_possible", "unknown"}
            or operation.get("state") in {"submitting", "accepted", "unknown"}
            or data is not None and (data.get("phase") == "executing" or data.get("permit") is not None))


def _clock(checked, cursor, source, target):
    registration = target.registration
    return ConnectionClock("lifecycle-db:" + source.operation_ref,
        lambda: checked.authority.canonical_now(cursor), identity={"authority_id": source.authority_id,
            "authority_incarnation": source.authority_incarnation, "endpoint_id": registration.endpoint_id,
            "node_id": registration.node_id, "boot_incarnation": registration.boot_incarnation,
            "machine_id": registration.machine_id})


def _checked(recovery, cursor, project, operation_ref, journal_generation, data=None):
    payload = _fresh(recovery, cursor, project, operation_ref)
    options = {} if data is None else {"expected_source": _typed(LifecycleSource, data["source"]),
                                      "expected_target": _typed(LifecycleTarget, data["target"])}
    checked, source, snapshot = checked_lifecycle_authority(recovery, cursor, payload,
        journal_generation=journal_generation, **options)
    if data is not None and snapshot.selection_digest != data.get("selection_digest"):
        raise LifecycleIssuanceRejected("lifecycle_current_selection_changed")
    return payload, checked, source, snapshot


def _authorizer(recovery, cursor, project, operation_ref, generation, data, *, pinned=None):
    def current(_stage, expected_source, expected_target):
        if pinned is None:
            _payload, _checked_authority, source, snapshot = _checked(recovery, cursor, project, operation_ref, generation, data)
        else:
            # Only a caller-owned transaction's already locked snapshot may be
            # reused during crypto validation. No cache crosses a commit. The
            # enclosing issuer performs a full check again before returning.
            checked, source, snapshot = pinned
            _transaction(cursor)
            if snapshot.valid_until is not None and checked.authority.canonical_now(cursor) >= snapshot.valid_until:
                raise LifecycleIssuanceRejected("lifecycle_transport_expired")
        if source != expected_source or snapshot.target() != expected_target:
            raise LifecycleIssuanceRejected("lifecycle_current_selection_changed")
    return current


def _deadline(now, snapshot, seconds, *bounds):
    deadline = min([now + timedelta(seconds=seconds), *(value for value in (snapshot.valid_until, *bounds) if value is not None)])
    if deadline <= now:
        raise LifecycleIssuanceRejected("lifecycle_transport_expired")
    return deadline


def _save(recovery, cursor, payload, checked, data, *, state, reason=None, effect="committed", done=False):
    operation = payload["operation"]
    if _possible(payload, _state(payload)):
        raise LifecycleIssuanceRejected("lifecycle_original_readback_required")
    after = operation | {"state": state, "reason_code": reason, "effect_state": effect,
        "revision": operation["revision"] + 1, "updated_at": checked.authority.canonical_now(cursor).isoformat()}
    recovery._save(cursor, payload | {"lifecycle": data}, after, done=done)
    return after


def _result(kind, operation, **values):
    return LifecycleIssuanceResult(kind, deepcopy(operation), **values)


def _derive(request_action, capacity):
    if request_action not in {"prepare_receiver", "resume_receiver", "rebind_receiver"}:
        raise LifecycleIssuanceRejected("lifecycle_original_action_not_mutable")
    if capacity.state == "unknown":
        return None, "lifecycle_capacity_unknown"
    if capacity.state == "stopped":
        return (None, "lifecycle_rebind_prepare_target_first") if request_action == "rebind_receiver" else ("resume", None)
    if capacity.journal_state != "clear":
        return None, "lifecycle_journal_unresolved"
    if capacity.blocker != "none":
        return None, "lifecycle_blocker_" + capacity.blocker
    if capacity.input_state == "busy":
        return None, "lifecycle_input_busy"
    if request_action == "rebind_receiver":
        return (None, "lifecycle_rebind_ready") if capacity.state == "existing" and capacity.input_state == "ready" else (
            None, "lifecycle_rebind_prepare_target_first")
    if request_action == "prepare_receiver" and capacity.state == "existing" and capacity.input_state == "ready":
        return None, "lifecycle_already_ready"
    if request_action == "prepare_receiver" and capacity.state == "fresh" and capacity.input_state == "not_started":
        return "spawn", None
    if request_action == "resume_receiver" and capacity.state == "existing" and capacity.input_state == "ready":
        return "resume", None
    return None, "lifecycle_capacity_not_ready"


class LifecycleIssuance:
    def __init__(self, recovery, signing_key, *, journal_generation, transport_seconds=30):
        if type(signing_key) is not SigningKey:
            raise TypeError("trusted installed Authority SigningKey required")
        if type(journal_generation) is not int or journal_generation < 1:
            raise ValueError("trusted journal generation required")
        if type(transport_seconds) is not int or not 1 <= transport_seconds <= 30:
            raise ValueError("lifecycle transport window must be between1 and30 seconds")
        self.recovery, self.signing_key = recovery, signing_key
        self.journal_generation, self.transport_seconds = journal_generation, transport_seconds

    def _signer(self, snapshot):
        if public_key(self.signing_key) != snapshot.authority_key.public_key:
            raise LifecycleIssuanceRejected("lifecycle_signer_current_key_mismatch")

    def _admit(self, cursor, project, operation_ref):
        payload = _fresh(self.recovery, cursor, project, operation_ref)
        _checked_authority, _source = original_lifecycle_source(self.recovery, cursor, payload)
        data = _state(payload)
        if _possible(payload, data):
            return payload, data, _result("readback_only", payload["operation"])
        if payload["operation"]["state"] in FINAL:
            return payload, data, _result("settled", payload["operation"])
        if payload["operation"].get("effect_state") != "committed":
            raise LifecycleIssuanceRejected("lifecycle_recovery_state_invalid")
        return payload, data, None

    def issue_challenge(self, cursor, project, operation_ref):
        with _transaction(cursor):
            payload, data, early = self._admit(cursor, project, operation_ref)
            if early is not None:
                return early
            payload, checked, source, snapshot = _checked(self.recovery, cursor, project, operation_ref, self.journal_generation, data)
            self._signer(snapshot)
            target = snapshot.target()
            if data is None:
                data = {"schema_version": SCHEMA, "phase": "observing", "source": source.model_dump(mode="json"),
                    "target": target.model_dump(mode="json"), "selection_digest": snapshot.selection_digest,
                    "first_plan_digest": None, "plan": None, "challenge": None, "observation": None,
                    "permit": None, "permit_digest": None}
            clock = _clock(checked, cursor, source, target)
            if data.get("challenge") is not None:
                previous = _typed(SignedLifecycleChallenge, data["challenge"])
                try:
                    verify_challenge(previous, expected_source=source, actual_target=target,
                        authority_key_id=snapshot.authority_key.key_id, authority_key_revision=snapshot.authority_key.revision,
                        authority_public_key=snapshot.authority_key.public_key, clock=clock,
                        authorize_current=_authorizer(self.recovery, cursor, project, operation_ref, self.journal_generation, data))
                except LifecycleContractRejected as error:
                    if error.code != "lifecycle_transport_expired_or_uncertain":
                        raise
                else:
                    operation = payload["operation"]
                    if data["phase"] != "observing":
                        data.update(phase="observing", observation=None)
                        operation = _save(self.recovery, cursor, payload, checked, data, state="preparing",
                            reason="lifecycle_capacity_observation_required")
                    return _result("challenge", operation, challenge=previous)
            now = checked.authority.canonical_now(cursor)
            challenge = LifecycleChallenge(source=source, target=target, authority_key_id=snapshot.authority_key.key_id,
                authority_key_revision=snapshot.authority_key.revision, request_id="lifecycle-request-" + uuid4().hex,
                nonce=uuid4().hex + uuid4().hex, issued_at=now,
                deadline=_deadline(now, snapshot, self.transport_seconds, source.business_deadline))
            signed = sign_challenge(challenge, self.signing_key)
            data.update(phase="observing", challenge=signed.model_dump(mode="json"), observation=None)
            operation = _save(self.recovery, cursor, payload, checked, data, state="preparing", reason="lifecycle_capacity_observation_required")
            verify_challenge(signed, expected_source=source, actual_target=target,
                authority_key_id=snapshot.authority_key.key_id, authority_key_revision=snapshot.authority_key.revision,
                authority_public_key=snapshot.authority_key.public_key, clock=clock,
                authorize_current=_authorizer(self.recovery, cursor, project, operation_ref, self.journal_generation, data))
            return _result("challenge", operation, challenge=signed)

    def record_observation(self, cursor, project, operation_ref, signed_observation):
        with _transaction(cursor):
            payload, data, early = self._admit(cursor, project, operation_ref)
            if early is not None:
                return early
            if data is None or data.get("challenge") is None:
                raise LifecycleIssuanceRejected("lifecycle_challenge_required")
            payload, checked, source, snapshot = _checked(self.recovery, cursor, project, operation_ref, self.journal_generation, data)
            challenge = _typed(SignedLifecycleChallenge, data["challenge"]).challenge
            signed_observation = _typed(SignedCapacityObservation, signed_observation)
            clock = _clock(checked, cursor, source, snapshot.target())
            current = _authorizer(self.recovery, cursor, project, operation_ref, self.journal_generation,
                data, pinned=(checked, source, snapshot))
            verify_challenge(_typed(SignedLifecycleChallenge, data["challenge"]), expected_source=source,
                actual_target=snapshot.target(), authority_key_id=snapshot.authority_key.key_id,
                authority_key_revision=snapshot.authority_key.revision,
                authority_public_key=snapshot.authority_key.public_key, clock=clock, authorize_current=current)
            observed = verify_observation(signed_observation, challenge=challenge, expected_source=source,
                actual_target=snapshot.target(), node_public_key=snapshot.binding.node_public_key,
                clock=clock, authorize_current=current)
            action, reason = _derive(_intent(payload), observed.capacity)
            if action is not None:
                plan = build_lifecycle_plan(challenge, observed, action)
                digest = lifecycle_plan_digest(plan)
                if data.get("first_plan_digest") not in {None, digest}:
                    raise LifecycleIssuanceRejected("lifecycle_stable_plan_changed")
                data.update(first_plan_digest=digest, plan=plan.model_dump(mode="json"), phase="planned")
                state, kind, done = "preparing", "planned", False
            elif reason == "lifecycle_rebind_ready":
                data["phase"] = "rebind_ready"
                state, kind, done = "preparing", "rebind_ready", False
            elif reason == "lifecycle_already_ready":
                if data.get("plan") is not None and capacity_semantic_digest(observed.capacity) != capacity_semantic_digest(
                        _typed(LifecyclePlan, data["plan"]).capacity):
                    raise LifecycleIssuanceRejected("lifecycle_stable_plan_changed")
                data["phase"] = "settled"
                state, kind, done = "completed", "settled", True
            else:
                data["phase"] = "deferred"
                state, kind, done = "deferred", "deferred", False
            data["observation"] = signed_observation.model_dump(mode="json")
            operation = _save(self.recovery, cursor, payload, checked, data, state=state, reason=reason, done=done)
            _checked(self.recovery, cursor, project, operation_ref, self.journal_generation, data)
            verify_observation(signed_observation, challenge=challenge, expected_source=source,
                actual_target=snapshot.target(), node_public_key=snapshot.binding.node_public_key,
                clock=clock, authorize_current=current)
            return _result(kind, operation)

    def issue_permit(self, cursor, project, operation_ref):
        with _transaction(cursor):
            payload, data, early = self._admit(cursor, project, operation_ref)
            if early is not None:
                return early
            if data is None or data.get("plan") is None or data.get("observation") is None or data.get("phase") != "planned":
                raise LifecycleIssuanceRejected("lifecycle_planned_observation_required")
            payload, checked, source, snapshot = _checked(self.recovery, cursor, project, operation_ref, self.journal_generation, data)
            self._signer(snapshot)
            challenge = _typed(SignedLifecycleChallenge, data["challenge"]).challenge
            signed_observation = _typed(SignedCapacityObservation, data["observation"])
            clock = _clock(checked, cursor, source, snapshot.target())
            current = _authorizer(self.recovery, cursor, project, operation_ref, self.journal_generation,
                data, pinned=(checked, source, snapshot))
            observed = verify_observation(signed_observation, challenge=challenge, expected_source=source,
                actual_target=snapshot.target(), node_public_key=snapshot.binding.node_public_key, clock=clock, authorize_current=current)
            action, reason = _derive(_intent(payload), observed.capacity)
            if action is None:
                raise LifecycleIssuanceRejected(reason)
            plan = build_lifecycle_plan(challenge, observed, action)
            if lifecycle_plan_digest(plan) != data["first_plan_digest"] or plan != _typed(LifecyclePlan, data["plan"]):
                raise LifecycleIssuanceRejected("lifecycle_stable_plan_changed")
            now = checked.authority.canonical_now(cursor)
            permit = LifecyclePermit(plan=plan, semantic_digest=data["first_plan_digest"], challenge_digest=sha256(challenge),
                observation_digest=sha256(observed), authority_key_id=snapshot.authority_key.key_id,
                authority_key_revision=snapshot.authority_key.revision, request_id=challenge.request_id, nonce=challenge.nonce,
                issued_at=now, deadline=_deadline(now, snapshot, self.transport_seconds, challenge.deadline,
                                                source.business_deadline))
            from runtime.receiver_lifecycle_contract import require_fresh_capacity_at_issuance

            require_fresh_capacity_at_issuance(observed.capacity, permit.issued_at)
            signed = sign_permit(permit, self.signing_key)
            data.update(phase="executing", permit=signed.model_dump(mode="json"), permit_digest=sha256(permit))
            operation = _save(self.recovery, cursor, payload, checked, data, state="submitting", effect="native_possible",
                              reason="lifecycle_execution_possible")
            require_current_execution(self.recovery, cursor, project, operation_ref, signed,
                                      journal_generation=self.journal_generation)
            return _result("permit", operation, permit=signed)


def require_current_execution(recovery, cursor, project, operation_ref, signed_permit, *, journal_generation):
    """Core current-authority callback only; Node still checks actual capacity.

    This function needs no Authority private key. It never renews a permit or
    changes any operation fact, even when an old possible-effect lease expires.
    """
    payload = _fresh(recovery, cursor, project, operation_ref)
    data, operation = _state(payload), payload["operation"]
    if (data is None or data.get("phase") != "executing" or operation.get("state") != "submitting"
            or operation.get("effect_state") != "native_possible" or data.get("permit") is None):
        raise LifecycleIssuanceRejected("lifecycle_current_execution_state_rejected")
    signed = _typed(SignedLifecyclePermit, signed_permit)
    stored = _typed(SignedLifecyclePermit, data["permit"])
    permit = signed.permit
    if (signed != stored or data.get("permit_digest") != sha256(permit)
            or data.get("first_plan_digest") != permit.semantic_digest
            or permit.plan != _typed(LifecyclePlan, data.get("plan"))):
        raise LifecycleIssuanceRejected("lifecycle_current_execution_permit_changed")
    action, _reason = _derive(_intent(payload), permit.plan.capacity)
    if action != permit.plan.action:
        raise LifecycleIssuanceRejected("lifecycle_original_action_not_mutable")
    payload, checked, source, snapshot = _checked(recovery, cursor, project, operation_ref, journal_generation, data)
    if (permit.plan.source != source or permit.plan.target != snapshot.target()
            or permit.authority_key_id != snapshot.authority_key.key_id
            or permit.authority_key_revision != snapshot.authority_key.revision):
        raise LifecycleIssuanceRejected("lifecycle_current_execution_permit_changed")
    verify(snapshot.authority_key.public_key, signed.signature, permit)
    signed_observation = _typed(SignedCapacityObservation, data.get("observation"))
    signed_challenge = _typed(SignedLifecycleChallenge, data.get("challenge"))
    observation, challenge = signed_observation.observation, signed_challenge.challenge
    verify(snapshot.authority_key.public_key, signed_challenge.signature, challenge)
    verify(snapshot.binding.node_public_key, signed_observation.signature, observation)
    if (permit.observation_digest != sha256(observation) or permit.challenge_digest != sha256(challenge)
            or permit.request_id != challenge.request_id or permit.nonce != challenge.nonce
            or permit.plan != build_lifecycle_plan(challenge, observation, action)
            or challenge.source != source or challenge.target != snapshot.target()
            or (challenge.authority_key_id, challenge.authority_key_revision) !=
               (snapshot.authority_key.key_id, snapshot.authority_key.revision)):
        raise LifecycleIssuanceRejected("lifecycle_current_execution_permit_changed")
    clock = _clock(checked, cursor, source, snapshot.target())
    from runtime.receiver_lifecycle_contract import require_fresh_capacity_at_issuance

    require_fresh_capacity_at_issuance(observation.capacity, permit.issued_at)
    deadline = min(permit.deadline, challenge.deadline,
                   *((source.business_deadline,) if source.business_deadline is not None else ()))
    reading = clock.require_before(deadline)
    if permit.issued_at > reading.latest_utc:
        raise LifecycleIssuanceRejected("lifecycle_transport_from_future")
