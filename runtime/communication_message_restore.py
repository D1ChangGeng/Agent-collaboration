"""Continue an accepted Message after its positively known receiver stops.

All state stays in that Message's original delivery Outbox. A past successful
startup is archived, never reinterpreted as a Message ACK or erased as unknown.
Only a new signed observation of the same stopped Native context permits a
further resume cycle. Host I/O never holds a SQL transaction.
"""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from runtime.receiver_crypto import sha256, verify
from runtime.receiver_lifecycle_contract import (
    LifecycleChallenge,
    SignedCapacityObservation,
    SignedLifecyclePermit,
    SignedLifecycleReceipt,
    sign_challenge,
    verify_observation,
)
from runtime.receiver_lifecycle_issuance import _checked, _clock, _deadline, _typed

MAX_RESTORE_CYCLES = 16


def _original_context(data, source, target, public_key):
    raw = data.get("receipt")
    if raw is not None:
        signed = _typed(SignedLifecycleReceipt, raw)
        receipt = signed.receipt
        permit = _typed(SignedLifecyclePermit, data["permit"]).permit
        if (receipt.outcome != "acknowledged" or receipt.source != source or receipt.target != target
                or receipt.permit_digest != sha256(permit) or receipt.semantic_digest != permit.semantic_digest
                or receipt.driver_operation_id != permit.plan.driver_operation_id):
            raise ValueError("original successful wake receipt is unavailable")
        verify(public_key, signed.signature, receipt)
        return receipt.native_session_ref, receipt.provider_generation, permit.plan.capacity.driver_binding_id
    observed = _typed(SignedCapacityObservation, data["observation"])
    value = observed.observation
    if (value.source_digest != sha256(source) or value.target != target or value.capacity.state != "existing"
            or value.capacity.native_session_ref is None):
        raise ValueError("original ready receiver observation is unavailable")
    verify(public_key, observed.signature, value)
    return value.capacity.native_session_ref, value.capacity.provider_generation, value.capacity.driver_binding_id


def continue_stopped_message(store, transport, project, operation_ref):
    """Return true only when the same Message was reopened for a safe resume."""
    from runtime.communication_message_wake import MessageWakeUnavailable, enabled

    authority = store.authority
    generation = transport.config.journal_generation
    with authority.transaction() as (_bound, connection), connection.cursor() as cursor:
        payload = store._row(cursor, project, operation_ref, lock=True)
        data = payload.get("lifecycle")
        if payload["operation"]["state"] != "completed" or not isinstance(data, dict) or data.get("phase") != "settled":
            return False
        if not enabled(authority, payload["receiver_id"]):
            return False
        _payload, checked, source, snapshot = _checked(store, cursor, project, operation_ref, generation, data)
        if snapshot.binding != transport.config.binding:
            raise MessageWakeUnavailable("message_restore_transport_changed")
        original = _original_context(data, source, snapshot.target(), snapshot.binding.node_public_key)
        frozen = sha256(data)
        now = checked.authority.canonical_now(cursor)
        challenge = LifecycleChallenge(source=source, target=snapshot.target(),
            authority_key_id=snapshot.authority_key.key_id, authority_key_revision=snapshot.authority_key.revision,
            request_id="message-restore-observe-" + uuid4().hex, nonce=uuid4().hex + uuid4().hex,
            issued_at=now, deadline=_deadline(now, snapshot, 30, source.business_deadline))
        signed_challenge = sign_challenge(challenge, transport.signing_key)
    # Read-only observation, with the original sender/scope checked at the Node.
    from runtime.receiver_lifecycle_executor import ReceiverLifecycleExecutor

    ReceiverLifecycleExecutor(store, transport)._host_boundary()
    observed = transport.observe(signed_challenge)
    with authority.transaction() as (_bound, connection), connection.cursor() as cursor:
        payload = store._row(cursor, project, operation_ref, lock=True)
        data = payload.get("lifecycle")
        if payload["operation"]["state"] != "completed" or sha256(data) != frozen:
            raise MessageWakeUnavailable("message_restore_original_phase_changed")
        _payload, checked, actual_source, snapshot = _checked(store, cursor, project, operation_ref, generation, data)
        if actual_source != source or snapshot.target() != challenge.target or not enabled(authority, payload["receiver_id"]):
            raise MessageWakeUnavailable("message_restore_current_authority_changed")

        def current(_stage, expected_source, expected_target):
            if (expected_source, expected_target) != (source, snapshot.target()):
                raise MessageWakeUnavailable("message_restore_scope_changed")

        signed = _typed(SignedCapacityObservation, observed)
        observation = verify_observation(signed, challenge=challenge, expected_source=source, actual_target=snapshot.target(),
            node_public_key=snapshot.binding.node_public_key, clock=_clock(checked, cursor, source, snapshot.target()),
            authorize_current=current)
        capacity = observation.capacity
        if capacity.state != "stopped":
            return False
        if len(data.get("history", [])) >= MAX_RESTORE_CYCLES:
            raise MessageWakeUnavailable("message_restore_cycle_budget_exhausted")
        if (capacity.native_session_ref, capacity.provider_generation, capacity.driver_binding_id) != original:
            raise MessageWakeUnavailable("message_restore_original_native_context_changed")
        previous = deepcopy(data)
        history = previous.pop("history", [])
        next_data = {"schema_version": data["schema_version"], "phase": "observing", "source": source.model_dump(mode="json"),
            "target": snapshot.target().model_dump(mode="json"), "selection_digest": snapshot.selection_digest,
            "first_plan_digest": None, "plan": None, "challenge": signed_challenge.model_dump(mode="json"),
            "observation": None, "permit": None, "permit_digest": None,
            "driver_binding_id": capacity.driver_binding_id,
            "original_capacity_digest": data.get("original_capacity_digest") or sha256(previous),
            "history": [*history, previous]}
        old = payload["operation"]
        operation = old | {"state": "preparing", "effect_state": "committed", "reason_code": "message_original_session_restore_required",
            "revision": old["revision"] + 1, "updated_at": checked.authority.canonical_now(cursor).isoformat()}
        store._save(cursor, payload | {"lifecycle": next_data}, operation, done=False)
        return True
