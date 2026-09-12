"""Executable reference model for two remaining Runtime recovery boundaries.

This file is deliberately independent of the formal Runtime. PostgreSQL must
provide the transaction, uniqueness, authorization, and Outbox boundaries in a
production candidate; these classes specify the deterministic transitions.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock

MAX_CANONICAL_BYTES = 65_536
MAX_PATHS = 16
MAX_REFS = 16
HEX = frozenset("0123456789abcdef")


class StateConflict(ValueError):
    pass


class BoundaryRejected(ValueError):
    pass


def canonical_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode()) > MAX_CANONICAL_BYTES:
        raise BoundaryRejected("canonical_input_exceeds_bound")
    return hashlib.sha256(encoded.encode()).hexdigest()


def response_receipt_id(identity: DispatchIdentity, projection_id: str) -> str:
    suffix = canonical_digest({
        "tenant_id": identity.tenant_id,
        "message_id": identity.message_id,
        "attempt_id": identity.attempt_id,
        "invocation_id": identity.invocation_id,
        "projection_id": projection_id,
    })[:24]
    return f"delivery:{identity.message_id}:{identity.attempt_id}:response_received:{suffix}"


def _text(value: str, field: str, *, maximum: int = 512) -> None:
    if (not isinstance(value, str) or not value or len(value) > maximum
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise BoundaryRejected(f"{field}_outside_bound")


def _digest(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in HEX for char in value):
        raise BoundaryRejected(f"{field}_invalid")


def _aware(value: datetime, field: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise BoundaryRejected(f"{field}_timezone_required")


class ProjectionState(StrEnum):
    APPLIED = "applied"
    FENCED_LATE = "fenced_late"


@dataclass(frozen=True)
class DispatchIdentity:
    tenant_id: str
    message_id: str
    operation_id: str
    invocation_id: str
    attempt_id: str
    dispatch_id: str
    endpoint_id: str
    binding_revision: int
    machine_id: str
    node_id: str
    boot_incarnation: str
    accepted_revision: int
    accepted_state_digest: str

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if name in {"binding_revision", "accepted_revision", "accepted_state_digest"}:
                continue
            _text(value, name)
        if self.binding_revision < 1 or self.accepted_revision < 0:
            raise BoundaryRejected("dispatch_revision_outside_bound")
        _digest(self.accepted_state_digest, "accepted_state_digest")


@dataclass(frozen=True)
class NativeResponseObservation:
    projection_id: str
    receipt_id: str
    identity: DispatchIdentity
    native_response_ref: str
    native_outcome: str
    response_artifact_ref: str
    response_digest: str
    evidence_digest: str
    observed_at: datetime

    def __post_init__(self) -> None:
        for name in ("projection_id", "receipt_id", "native_response_ref",
                     "response_artifact_ref"):
            _text(getattr(self, name), name)
        if self.native_outcome not in {"completed", "failed", "interrupted"}:
            raise BoundaryRejected("native_response_is_not_terminal")
        _digest(self.response_digest, "response_digest")
        _digest(self.evidence_digest, "evidence_digest")
        _aware(self.observed_at, "observed_at")

    def canonical(self) -> dict:
        value = asdict(self)
        value["observed_at"] = self.observed_at.astimezone(UTC).isoformat()
        return value


@dataclass
class DeliveryProjection:
    identity: DispatchIdentity
    deadline: datetime
    current_attempt_id: str
    current_accepted_revision: int
    current_accepted_state_digest: str
    receipt_high_water: str = "runtime_dispatched"
    receipts: dict[str, dict] = field(default_factory=dict)
    observations: dict[str, tuple[str, ProjectionState]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _aware(self.deadline, "delivery_deadline")
        _text(self.current_attempt_id, "current_attempt_id")
        if self.current_accepted_revision < 0:
            raise BoundaryRejected("current accepted revision outside bound")
        _digest(self.current_accepted_state_digest, "current_accepted_state_digest")


class DelayedResponseProjector:
    """Reference for one PostgreSQL transaction that projects a Node observation."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._projection_ids: dict[tuple[str, str], tuple[str, str, ProjectionState]] = {}
        self._receipt_ids: dict[tuple[str, str], str] = {}
        self._native_refs: dict[tuple[str, str, str], str] = {}
        self._invocation_terminals: dict[tuple[str, str], tuple[str, str]] = {}

    def project(
        self,
        delivery: DeliveryProjection,
        observation: NativeResponseObservation,
        *,
        now: datetime,
        producer_authenticated: bool,
        current_authority_valid: bool,
    ) -> ProjectionState:
        with self._lock:
            _aware(now, "projection_now")
            if not isinstance(producer_authenticated, bool) or not isinstance(
                current_authority_valid, bool
            ):
                raise BoundaryRejected("projection authority flags must be boolean")
            if not producer_authenticated:
                raise BoundaryRejected("native_observation_producer_not_authenticated")
            payload_digest = canonical_digest(observation.canonical())
            tenant = delivery.identity.tenant_id
            projection_key = (tenant, observation.projection_id)
            global_prior = self._projection_ids.get(projection_key)
            prior = delivery.observations.get(observation.projection_id)
            if global_prior is not None or prior is not None:
                if (global_prior is None or prior is None
                        or global_prior[:2] != (delivery.identity.message_id, payload_digest)
                        or prior[0] != payload_digest or prior[1] is not global_prior[2]):
                    raise StateConflict("projection_id_reused_with_different_payload")
                return prior[1]
            if observation.identity != delivery.identity:
                raise BoundaryRejected("committed_dispatch_identity_mismatch")
            if observation.receipt_id != response_receipt_id(
                observation.identity, observation.projection_id
            ):
                raise BoundaryRejected("response_receipt_identity_is_not_canonical")
            native_key = (tenant, observation.identity.invocation_id,
                          observation.native_response_ref)
            prior_projection = self._native_refs.get(native_key)
            if prior_projection not in (None, observation.projection_id):
                raise StateConflict("native_response_ref_already_bound")
            invocation_key = (tenant, observation.identity.invocation_id)
            prior_terminal = self._invocation_terminals.get(invocation_key)
            terminal_identity = (observation.native_response_ref, observation.projection_id)
            if prior_terminal not in (None, terminal_identity):
                raise StateConflict("invocation_terminal_already_bound")

            can_advance = (
                current_authority_valid
                and now < delivery.deadline
                and delivery.current_attempt_id == observation.identity.attempt_id
                and delivery.current_accepted_revision == observation.identity.accepted_revision
                and delivery.current_accepted_state_digest
                == observation.identity.accepted_state_digest
            )
            state = ProjectionState.APPLIED if can_advance else ProjectionState.FENCED_LATE
            receipt = {
                "receipt_id": observation.receipt_id,
                "attempt_id": observation.identity.attempt_id,
                "dispatch_id": observation.identity.dispatch_id,
                "invocation_id": observation.identity.invocation_id,
                "native_response_ref": observation.native_response_ref,
                "native_outcome": observation.native_outcome,
                "response_artifact_ref": observation.response_artifact_ref,
                "response_digest": observation.response_digest,
                "evidence_digest": observation.evidence_digest,
                "disposition": state,
            }
            receipt_digest = canonical_digest(receipt)
            receipt_key = (tenant, observation.receipt_id)
            previous_receipt_id = self._receipt_ids.get(receipt_key)
            if previous_receipt_id not in (None, receipt_digest):
                raise StateConflict("receipt_id_reused_with_different_payload")
            if state is ProjectionState.APPLIED:
                existing = delivery.receipts.get("response_received")
                applied_receipt = {key: value for key, value in receipt.items()
                                   if key != "disposition"}
                if existing not in (None, applied_receipt):
                    raise StateConflict("response_receipt_conflict")

            # Commit only after every identity/uniqueness/receipt check has passed.
            self._projection_ids[projection_key] = (
                delivery.identity.message_id, payload_digest, state,
            )
            self._receipt_ids[receipt_key] = receipt_digest
            self._native_refs[native_key] = observation.projection_id
            self._invocation_terminals[invocation_key] = terminal_identity
            delivery.observations[observation.projection_id] = (payload_digest, state)
            if state is ProjectionState.APPLIED:
                delivery.receipts["response_received"] = applied_receipt
                delivery.receipt_high_water = "response_received"
            return state


class IncidentState(StrEnum):
    OPEN = "open"
    HUMAN_REQUESTED = "human_requested"
    MANUAL_PACKET_COMMITTED = "manual_packet_committed"
    RESOLVED_AUTOMATIC = "resolved_automatic"
    RESOLVED_MANUAL = "resolved_manual"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


TERMINAL_INCIDENT_STATES = {
    IncidentState.RESOLVED_AUTOMATIC,
    IncidentState.RESOLVED_MANUAL,
    IncidentState.EXPIRED,
    IncidentState.CANCELLED,
}
EXHAUSTED_PATH_STATES = {"failed", "unavailable", "unsupported", "budget_exhausted"}


@dataclass(frozen=True)
class RecoveryPath:
    path_id: str
    status: str
    attempt_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.path_id, "path_id")
        if self.status not in EXHAUSTED_PATH_STATES:
            raise BoundaryRejected("automatic_path_status_not_exhausted")
        for name, values in (("attempt_refs", self.attempt_refs),
                             ("evidence_refs", self.evidence_refs)):
            if not values or len(values) > MAX_REFS or len(set(values)) != len(values):
                raise BoundaryRejected(f"{name}_outside_bound")
            for value in values:
                _text(value, name, maximum=256)


@dataclass(frozen=True)
class ManualPacket:
    packet_id: str
    incident_id: str
    incident_generation: int
    tenant_id: str
    message_id: str
    operation_id: str
    attempt_id: str
    dispatch_id: str
    source_scope_id: str
    target_scope_id: str
    direction: str
    expected_accepted_revision: int
    accepted_state_digest: str
    payload_digest: str
    expires_at: datetime

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if name in {"incident_generation", "expected_accepted_revision", "expires_at"}:
                continue
            if name in {"accepted_state_digest", "payload_digest"}:
                _digest(value, name)
            else:
                _text(value, name)
        if self.incident_generation < 1 or self.expected_accepted_revision < 0:
            raise BoundaryRejected("manual_packet_revision_outside_bound")
        if self.direction not in {"request", "response"}:
            raise BoundaryRejected("manual_packet_direction_invalid")
        _aware(self.expires_at, "packet_expires_at")

    def canonical(self) -> dict:
        value = asdict(self)
        value["expires_at"] = self.expires_at.astimezone(UTC).isoformat()
        return value


@dataclass
class RecoveryIncident:
    incident_id: str
    generation: int
    tenant_id: str
    message_id: str
    operation_id: str
    source_scope_id: str
    target_scope_id: str
    accepted_revision: int
    accepted_state_digest: str
    expires_at: datetime
    paths: tuple[RecoveryPath, ...]
    state: IncidentState = IncidentState.OPEN
    request_id: str | None = None
    packet_results: dict[str, tuple[str, str]] = field(default_factory=dict)
    packets: dict[str, ManualPacket] = field(default_factory=dict)
    applied_packet_id: str | None = None
    audit: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class NormalReceipt:
    receipt_id: str
    layer: str
    tenant_id: str
    message_id: str
    operation_id: str
    incident_id: str
    incident_generation: int
    packet_id: str
    attempt_id: str
    dispatch_id: str
    direction: str
    payload_digest: str
    evidence_digest: str

    def canonical(self) -> dict:
        return asdict(self)

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if name == "incident_generation":
                continue
            if name in {"payload_digest", "evidence_digest"}:
                _digest(value, name)
            else:
                _text(value, name)
        if self.incident_generation < 1:
            raise BoundaryRejected("normal_receipt_generation_outside_bound")
        if self.direction not in {"request", "response"}:
            raise BoundaryRejected("normal_receipt_direction_invalid")


class HumanBridgeCoordinator:
    """Reference Domain state machine; manual transport never owns these states."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._incidents: dict[tuple[str, str], tuple[str, RecoveryIncident]] = {}
        self._request_ids: dict[tuple[str, str], str] = {}
        self._packet_ids: dict[tuple[str, str], str] = {}
        self._normal_receipt_ids: dict[tuple[str, str], str] = {}

    def open_incident(
        self,
        *,
        incident_id: str,
        generation: int,
        tenant_id: str,
        message_id: str,
        operation_id: str,
        source_scope_id: str,
        target_scope_id: str,
        accepted_revision: int,
        accepted_state_digest: str,
        expires_at: datetime,
        eligible_path_ids: tuple[str, ...],
        paths: tuple[RecoveryPath, ...],
        now: datetime,
        task_valid: bool,
        current_authority_valid: bool,
    ) -> RecoveryIncident:
        with self._lock:
            _aware(now, "incident_now")
            for name, value in {
                "incident_id": incident_id, "tenant_id": tenant_id,
                "message_id": message_id, "operation_id": operation_id,
                "source_scope_id": source_scope_id, "target_scope_id": target_scope_id,
            }.items():
                _text(value, name)
            if generation < 1 or accepted_revision < 0:
                raise BoundaryRejected("incident_revision_outside_bound")
            _digest(accepted_state_digest, "accepted_state_digest")
            _aware(expires_at, "incident_expires_at")
            if not task_valid or not current_authority_valid or now >= expires_at:
                raise BoundaryRejected("bridge_incident_requires_current_authority")
            if (not eligible_path_ids or len(eligible_path_ids) > MAX_PATHS
                    or len(set(eligible_path_ids)) != len(eligible_path_ids)
                    or len(paths) != len(eligible_path_ids)
                    or len({path.path_id for path in paths}) != len(paths)
                    or {path.path_id for path in paths} != set(eligible_path_ids)):
                raise BoundaryRejected("eligible_automatic_path_census_incomplete")
            for path_id in eligible_path_ids:
                _text(path_id, "eligible_path_id")
            if any(path.status not in EXHAUSTED_PATH_STATES or not path.attempt_refs or not path.evidence_refs
                   for path in paths):
                raise BoundaryRejected("automatic_recovery_not_proven_exhausted")
            spec = {
                "incident_id": incident_id, "generation": generation, "tenant_id": tenant_id,
                "message_id": message_id, "operation_id": operation_id,
                "source_scope_id": source_scope_id, "target_scope_id": target_scope_id,
                "accepted_revision": accepted_revision,
                "accepted_state_digest": accepted_state_digest,
                "expires_at": expires_at.astimezone(UTC).isoformat(),
                "eligible_path_ids": eligible_path_ids,
                "paths": [asdict(path) for path in paths],
            }
            spec_digest = canonical_digest(spec)
            key = (tenant_id, incident_id)
            prior = self._incidents.get(key)
            if prior is not None:
                if prior[0] != spec_digest:
                    raise StateConflict("incident_id_reused_with_different_spec")
                return prior[1]
            incident = RecoveryIncident(
                incident_id, generation, tenant_id, message_id, operation_id,
                source_scope_id, target_scope_id, accepted_revision,
                accepted_state_digest, expires_at, paths,
            )
            incident.audit.append({"event": "incident_opened", "at": now.isoformat()})
            self._incidents[key] = (spec_digest, incident)
            return incident

    def request_human(
        self,
        incident: RecoveryIncident,
        *,
        request_id: str,
        now: datetime,
        send_authorized: bool,
    ) -> str:
        with self._lock:
            _aware(now, "request_now")
            _text(request_id, "request_id")
            if incident.request_id is not None:
                if incident.request_id != request_id:
                    raise StateConflict("human_request_identity_conflict")
                return incident.request_id
            if incident.state is not IncidentState.OPEN or now >= incident.expires_at or not send_authorized:
                raise BoundaryRejected("human_request_boundary_rejected")
            request_digest = canonical_digest({
                "request_id": request_id, "incident_id": incident.incident_id,
                "generation": incident.generation, "tenant_id": incident.tenant_id,
            })
            request_key = (incident.tenant_id, request_id)
            prior_request = self._request_ids.get(request_key)
            if prior_request not in (None, request_digest):
                raise StateConflict("human_request_id_reused")
            self._request_ids[request_key] = request_digest
            incident.request_id = request_id
            incident.state = IncidentState.HUMAN_REQUESTED
            incident.audit.append({"event": "human_request_outbox_committed", "request_id": request_id})
            return request_id

    def reprobe_succeeded(
        self, incident: RecoveryIncident, *, observation_ref: str, now: datetime
    ) -> IncidentState:
        with self._lock:
            _aware(now, "reprobe_now")
            _text(observation_ref, "observation_ref")
            if incident.state in TERMINAL_INCIDENT_STATES:
                return incident.state
            if incident.state is IncidentState.MANUAL_PACKET_COMMITTED:
                raise StateConflict("manual_packet_already_committed")
            incident.state = IncidentState.RESOLVED_AUTOMATIC
            incident.audit.append({"event": "automatic_path_restored", "ref": observation_ref,
                                   "at": now.isoformat()})
            return incident.state

    def submit_manual(
        self,
        incident: RecoveryIncident,
        packet: ManualPacket,
        *,
        now: datetime,
        authenticated_subject: bool,
        current_authority_valid: bool,
        task_valid: bool,
        current_accepted_revision: int,
        current_accepted_state_digest: str,
    ) -> str:
        with self._lock:
            _aware(now, "manual_now")
            if current_accepted_revision < 0:
                raise BoundaryRejected("current accepted revision outside bound")
            _digest(current_accepted_state_digest, "current_accepted_state_digest")
            if not authenticated_subject:
                raise BoundaryRejected("manual_packet_subject_not_authenticated")
            encoded = canonical_digest(packet.canonical())
            if packet.tenant_id != incident.tenant_id or packet.incident_id != incident.incident_id:
                raise BoundaryRejected("manual_packet_cross_incident")
            packet_key = (incident.tenant_id, packet.packet_id)
            global_prior = self._packet_ids.get(packet_key)
            prior = incident.packet_results.get(packet.packet_id)
            if global_prior is not None or prior is not None:
                if global_prior != encoded or prior is None or prior[0] != encoded:
                    raise StateConflict("manual_packet_id_reused_with_different_payload")
                return prior[1]
            identity_ok = (
                packet.message_id == incident.message_id
                and packet.operation_id == incident.operation_id
                and packet.source_scope_id == incident.source_scope_id
                and packet.target_scope_id == incident.target_scope_id
                and packet.expected_accepted_revision == incident.accepted_revision
                and packet.accepted_state_digest == incident.accepted_state_digest
            )
            if not identity_ok:
                raise BoundaryRejected("manual_packet_identity_mismatch")
            current = (
                packet.incident_generation == incident.generation
                and current_authority_valid
                and task_valid
                and now < incident.expires_at
                and now < packet.expires_at
                and current_accepted_revision == incident.accepted_revision
                and current_accepted_state_digest == incident.accepted_state_digest
                and incident.state is IncidentState.HUMAN_REQUESTED
            )
            result = "committed" if current else "fenced_late"
            self._packet_ids[packet_key] = encoded
            incident.packet_results[packet.packet_id] = (encoded, result)
            incident.packets[packet.packet_id] = packet
            incident.audit.append({"event": "manual_packet_" + result, "packet_id": packet.packet_id})
            if current:
                incident.applied_packet_id = packet.packet_id
                incident.state = IncidentState.MANUAL_PACKET_COMMITTED
            return result

    def confirm_manual_delivery(
        self, incident: RecoveryIncident, *, packet_id: str, receipt: NormalReceipt
    ) -> IncidentState:
        with self._lock:
            packet = incident.packets.get(packet_id)
            if packet is None:
                raise BoundaryRejected("manual_delivery_confirmation_mismatch")
            expected_layer = (
                "target_inbox_committed" if packet.direction == "request" else "response_received"
            )
            receipt_digest = canonical_digest(receipt.canonical())
            receipt_key = (incident.tenant_id, receipt.receipt_id)
            prior = self._normal_receipt_ids.get(receipt_key)
            if incident.state is IncidentState.RESOLVED_MANUAL:
                if prior != receipt_digest:
                    raise StateConflict("normal_receipt_replay_conflict")
                return incident.state
            identity_ok = (
                receipt.layer == expected_layer
                and receipt.tenant_id == incident.tenant_id
                and receipt.message_id == incident.message_id
                and receipt.operation_id == incident.operation_id
                and receipt.incident_id == incident.incident_id
                and receipt.incident_generation == incident.generation
                and receipt.packet_id == packet_id
                and receipt.attempt_id == packet.attempt_id
                and receipt.dispatch_id == packet.dispatch_id
                and receipt.direction == packet.direction
                and receipt.payload_digest == packet.payload_digest
            )
            if (incident.state is not IncidentState.MANUAL_PACKET_COMMITTED
                    or incident.applied_packet_id != packet_id or not identity_ok):
                raise BoundaryRejected("manual_delivery_confirmation_mismatch")
            if prior not in (None, receipt_digest):
                raise StateConflict("normal_receipt_id_reused_with_different_payload")
            self._normal_receipt_ids[receipt_key] = receipt_digest
            incident.state = IncidentState.RESOLVED_MANUAL
            incident.audit.append({"event": "manual_path_resolved", "receipt_id": receipt.receipt_id,
                                   "receipt_layer": receipt.layer,
                                   "receipt_digest": receipt_digest})
            return incident.state

    def expire(self, incident: RecoveryIncident, *, now: datetime) -> IncidentState:
        with self._lock:
            _aware(now, "expire_now")
            if incident.state in TERMINAL_INCIDENT_STATES:
                return incident.state
            if now < incident.expires_at:
                raise BoundaryRejected("incident_not_expired")
            incident.state = IncidentState.EXPIRED
            incident.audit.append({"event": "incident_expired", "at": now.isoformat()})
            return incident.state
