"""Independent signed-receiver identity checks for P1 continuity evidence.

This module validates one observed transport exchange. It does not create a
Delivery, restart a process, or turn component observations into a Gate result.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from runtime.receiver_crypto import SignatureRejected, sha256, verify
from runtime.receiver_models import EndpointBinding, RecoveryBody, SignedReceipt, SignedRequest

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ContinuityRejected(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LogicalIdentity:
    tenant_id: str
    authority_id: str
    authority_incarnation: str
    work_item_id: str
    scope_id: str
    agent_slot_id: str
    machine_id: str
    node_id: str
    message_id: str
    command_id: str
    operation_id: str
    source_commit: str
    source_tree: str
    accepted_revision: int
    accepted_state_digest: str
    envelope_digest: str

    def __post_init__(self) -> None:
        strings = (
            self.tenant_id, self.authority_id, self.authority_incarnation,
            self.work_item_id, self.scope_id, self.agent_slot_id,
            self.machine_id, self.node_id, self.message_id,
            self.command_id, self.operation_id,
        )
        if any(not isinstance(value, str) or not 1 <= len(value) <= 256 for value in strings):
            raise ContinuityRejected("logical identity is empty or unbounded")
        if (
            not _FULL_SHA.fullmatch(self.source_commit)
            or not _FULL_SHA.fullmatch(self.source_tree)
            or not _SHA256.fullmatch(self.accepted_state_digest)
            or not _SHA256.fullmatch(self.envelope_digest)
            or type(self.accepted_revision) is not int or self.accepted_revision < 0
        ):
            raise ContinuityRejected("source or accepted-state identity is invalid")


@dataclass(frozen=True, slots=True)
class AttemptReadback:
    ordinal: int
    tenant_id: str
    attempt_id: str
    dispatch_id: str
    message_id: str
    command_id: str
    operation_id: str
    work_item_id: str
    scope_id: str
    agent_slot_id: str
    machine_id: str
    node_id: str
    authority_id: str
    authority_incarnation: str
    source_commit: str
    source_tree: str
    endpoint_id: str
    endpoint_revision: int
    runtime_id: str
    runtime_revision: int
    node_binding_revision: int
    boot_incarnation: str
    status: str


def _same_fields(value: Any, expected: dict[str, Any], label: str) -> None:
    if any(getattr(value, name, None) != item for name, item in expected.items()):
        raise ContinuityRejected(f"{label} changed immutable identity")


def verify_signed_exchange(
    logical: LogicalIdentity,
    attempt: AttemptReadback,
    binding: EndpointBinding,
    request: SignedRequest,
    signed_receipt: SignedReceipt,
    *,
    authority_public_key: str,
) -> dict[str, Any]:
    """Verify actual authority, Node and registration signatures and exact lineage."""
    registration = binding.registration
    admission = request.admission
    receipt = signed_receipt.receipt
    try:
        verify(binding.node_public_key, binding.registration_signature, registration)
        verify(authority_public_key, request.signature, admission)
        verify(binding.node_public_key, signed_receipt.signature, receipt)
    except SignatureRejected:
        raise ContinuityRejected("signed receiver identity is invalid") from None
    logical_fields = {
        "tenant_id": logical.tenant_id,
        "authority_id": logical.authority_id,
        "authority_incarnation": logical.authority_incarnation,
        "message_id": logical.message_id,
        "command_id": logical.command_id,
        "operation_id": logical.operation_id,
        "machine_id": logical.machine_id,
        "node_id": logical.node_id,
        "scope_id": logical.scope_id,
        "agent_slot_id": logical.agent_slot_id,
    }
    _same_fields(registration, {
        key: logical_fields[key] for key in (
            "tenant_id", "authority_id", "authority_incarnation",
            "machine_id", "node_id", "scope_id", "agent_slot_id",
        )
    }, "registered receiver")
    _same_fields(attempt, {
        **logical_fields, "work_item_id": logical.work_item_id,
        "source_commit": logical.source_commit,
        "source_tree": logical.source_tree,
    }, "committed Attempt")
    if (
        attempt.ordinal < 1 or not attempt.attempt_id or not attempt.dispatch_id
        or attempt.status not in {"delivered", "retry_wait", "uncertain"}
    ):
        raise ContinuityRejected("Attempt admission is incomplete")
    _same_fields(admission, {
        **logical_fields,
        "attempt_id": attempt.attempt_id,
        "dispatch_id": attempt.dispatch_id,
        "endpoint_id": registration.endpoint_id,
        "endpoint_revision": registration.endpoint_revision,
        "runtime_id": registration.runtime_id,
        "runtime_revision": registration.runtime_revision,
        "boot_incarnation": registration.boot_incarnation,
        "accepted_revision": logical.accepted_revision,
        "accepted_state_digest": logical.accepted_state_digest,
        "envelope_digest": logical.envelope_digest,
    }, "receiver admission")
    if admission.purpose == "delivery.recover":
        try:
            recovery = RecoveryBody.model_validate(request.body, strict=True)
        except ValueError:
            raise ContinuityRejected("receiver recovery body is invalid") from None
        selected = (
            attempt.endpoint_id == registration.endpoint_id
            and attempt.runtime_id == registration.runtime_id
            and attempt.endpoint_revision == recovery.old_endpoint_revision
            and registration.endpoint_revision == recovery.new_endpoint_revision
            and attempt.runtime_revision == recovery.old_runtime_revision
            and registration.runtime_revision == recovery.new_runtime_revision
            and attempt.boot_incarnation == recovery.old_boot_incarnation
            and registration.boot_incarnation == recovery.new_boot_incarnation
            and registration.node_binding_revision > attempt.node_binding_revision
            and recovery.journal_generation == admission.journal_generation
            and recovery.journal_generation >= 2
            and bool(recovery.old_boot_isolation_ref)
        )
    else:
        selected = (
            attempt.endpoint_id == registration.endpoint_id
            and attempt.endpoint_revision == registration.endpoint_revision
            and attempt.runtime_id == registration.runtime_id
            and attempt.runtime_revision == registration.runtime_revision
            and attempt.node_binding_revision == registration.node_binding_revision
            and attempt.boot_incarnation == registration.boot_incarnation
        )
    if (
        not selected
        or signed_receipt.node_key_id != binding.node_key_id
        or admission.body_sha256 != sha256(request.body)
        or receipt.request_sha256 != sha256({
            "admission": admission.model_dump(mode="json"), "body": request.body,
        })
    ):
        raise ContinuityRejected("receiver Attempt, body or key binding changed")
    _same_fields(receipt, {
        **logical_fields,
        "attempt_id": attempt.attempt_id,
        "dispatch_id": attempt.dispatch_id,
        "endpoint_id": admission.endpoint_id,
        "endpoint_revision": admission.endpoint_revision,
        "runtime_id": admission.runtime_id,
        "runtime_revision": admission.runtime_revision,
        "node_binding_revision": registration.node_binding_revision,
        "boot_incarnation": admission.boot_incarnation,
        "accepted_revision": admission.accepted_revision,
        "accepted_state_digest": admission.accepted_state_digest,
        "envelope_digest": admission.envelope_digest,
        "selection_digest": admission.selection_digest,
        "invocation_digest": admission.invocation_digest,
        "journal_generation": admission.journal_generation,
    }, "signed receiver receipt")
    allowed = {
        "delivery.prepare": {"prepared"},
        "delivery.dispatch": {"runtime_dispatched", "runtime_acknowledged", "uncertain", "blocked"},
        "delivery.readback": {"readback"},
        "delivery.recover": {"runtime_dispatched", "runtime_acknowledged", "uncertain", "blocked"},
    }
    paths = {
        "delivery.prepare": "/v1/delivery/prepare",
        "delivery.dispatch": "/v1/delivery/dispatch",
        "delivery.readback": "/v1/delivery/readback",
        "delivery.recover": "/v1/delivery/recover",
    }
    links_ok = (
        receipt.readback_request_id == admission.request_id
        and receipt.target_request_id == receipt.evidence.get("target_request_id")
        if admission.purpose == "delivery.readback"
        else receipt.readback_request_id is None
        and receipt.target_request_id == admission.request_id
    )
    if (
        receipt.purpose != admission.purpose
        or receipt.state not in allowed.get(admission.purpose, set())
        or admission.path != paths.get(admission.purpose)
        or admission.method != "POST"
        or admission.issued_at >= registration.expires_at
        or receipt.receipt_id != f"receiver:{admission.request_id}:{receipt.state}"
        or receipt.request_id != admission.request_id
        or receipt.challenge_nonce != admission.nonce
        or not links_ok
        or receipt.observed_at.tzinfo is None
        or admission.issued_at > receipt.observed_at
        or receipt.observed_at > admission.deadline
    ):
        raise ContinuityRejected("signed receiver receipt timing or state changed")
    return {
        "request_id": admission.request_id,
        "receipt_id": receipt.receipt_id,
        "purpose": admission.purpose,
        "state": receipt.state,
        "attempt_id": attempt.attempt_id,
        "dispatch_id": attempt.dispatch_id,
        "endpoint_revision": registration.endpoint_revision,
        "node_binding_revision": registration.node_binding_revision,
        "machine_id": registration.machine_id,
        "node_id": registration.node_id,
        "boot_incarnation": registration.boot_incarnation,
        "source_commit": logical.source_commit,
        "source_tree": logical.source_tree,
        "signed_receipt_sha256": hashlib.sha256(
            json.dumps(signed_receipt.model_dump(mode="json"), sort_keys=True,
                       separators=(",", ":")).encode(),
        ).hexdigest(),
    }



@dataclass(frozen=True, slots=True)
class NodeBootReadback:
    binding_revision: int
    boot_incarnation: str
    machine_id: str
    node_id: str


def audit_component_chain(
    logical: LogicalIdentity,
    exchanges: tuple[tuple[AttemptReadback, EndpointBinding, SignedRequest, SignedReceipt], ...],
    node_boots: tuple[NodeBootReadback, ...],
    *,
    authority_public_key: str,
    inbox_projection_ids: tuple[str, ...],
    driver_dispatch_ids: tuple[str, ...],
    temporal_workflow_id: str | None = None,
) -> dict[str, Any]:
    """Check one logical receiver lineage; report component scope only.

    Caller-provided PG/SQLite/Temporal rows need independent live readback before
    they can be accepted as Gate evidence. This function never emits Gate PASS.
    """
    if not 1 <= len(exchanges) <= 32 or not 1 <= len(node_boots) <= 8:
        raise ContinuityRejected("receiver observations are missing or unbounded")
    if len(inbox_projection_ids) > 1 or len(driver_dispatch_ids) > 1:
        raise ContinuityRejected("logical message was projected or dispatched twice")
    selected_dispatches = {item[0].dispatch_id for item in exchanges}
    if any(value not in selected_dispatches for value in driver_dispatch_ids):
        raise ContinuityRejected("native dispatch belongs to another Attempt")
    boots: dict[tuple[int, str], NodeBootReadback] = {}
    for boot in node_boots:
        key = (boot.binding_revision, boot.boot_incarnation)
        if (
            key in boots or boot.binding_revision < 1 or not boot.boot_incarnation
            or (boot.machine_id, boot.node_id) != (logical.machine_id, logical.node_id)
        ):
            raise ContinuityRejected("Node boot readback changed logical Machine or Node")
        boots[key] = boot
    attempts: dict[str, AttemptReadback] = {}
    requests: dict[str, str] = {}
    seen: list[dict[str, Any]] = []
    prepared: set[str] = set()
    prepare_requests: dict[str, set[str]] = {}
    acknowledged: set[str] = set()
    for attempt, binding, request, receipt in exchanges:
        prior = attempts.setdefault(attempt.attempt_id, attempt)
        if prior != attempt:
            raise ContinuityRejected("Attempt identity changed across receiver exchanges")
        observed = verify_signed_exchange(
            logical, attempt, binding, request, receipt,
            authority_public_key=authority_public_key,
        )
        if (
            (binding.registration.node_binding_revision,
             binding.registration.boot_incarnation) not in boots
        ):
            raise ContinuityRejected("signed receiver boot lacks Node journal readback")
        request_id = observed["request_id"]
        digest = observed["signed_receipt_sha256"]
        existing = requests.get(request_id)
        if existing is not None:
            if existing != digest:
                raise ContinuityRejected("receiver request replay changed signed receipt")
            continue
        requests[request_id] = digest
        if observed["purpose"] == "delivery.prepare":
            prepared.add(attempt.attempt_id)
            prepare_requests.setdefault(attempt.attempt_id, set()).add(request_id)
        elif observed["purpose"] in {"delivery.dispatch", "delivery.recover"}:
            if attempt.attempt_id not in prepared:
                raise ContinuityRejected("receiver dispatch has no original prepare")
            if (
                observed["purpose"] == "delivery.recover"
                and request.body.get("prepare_request_id")
                not in prepare_requests.get(attempt.attempt_id, set())
            ):
                raise ContinuityRejected("recovery lost the original prepare request")
            if observed["state"] == "runtime_acknowledged":
                acknowledged.add(attempt.attempt_id)
        seen.append(observed)
    ordered = sorted(attempts.values(), key=lambda item: item.ordinal)
    if (
        [item.ordinal for item in ordered] != list(range(1, len(ordered) + 1))
        or len({item.dispatch_id for item in ordered}) != len(ordered)
        or sum(item.status == "delivered" for item in ordered) > 1
        or len(acknowledged) > 1
    ):
        raise ContinuityRejected("retry attempts duplicated delivery or native ACK")
    if temporal_workflow_id is not None and temporal_workflow_id != (
        "acs-delivery/" + logical.operation_id
    ):
        raise ContinuityRejected("Temporal workflow belongs to another operation")
    missing = ["postgresql_live", "sqlite_live", "temporal_live", "os_restart_live"]
    if not inbox_projection_ids:
        missing.append("core_inbox_projection")
    if not acknowledged:
        missing.append("receiver_runtime_ack")
    return {
        "status": "component_only",
        "gate_status": "not_run",
        "logical_operation_id": logical.operation_id,
        "signed_exchange_count": len(seen),
        "attempt_ids": [item.attempt_id for item in ordered],
        "boot_revisions": sorted({boot.binding_revision for boot in node_boots}),
        "inbox_projection_count": len(inbox_projection_ids),
        "driver_dispatch_count": len(driver_dispatch_ids),
        "missing": missing,
    }


def read_receiver_ledger(
    ledger,
    logical: LogicalIdentity,
    *,
    allowed_attempt_ids: tuple[str, ...],
) -> dict[str, Any]:
    """Read an already witness-bound ReceiverLedger without manufacturing receipts."""
    if not 1 <= len(allowed_attempt_ids) <= 8 or len(set(allowed_attempt_ids)) != len(
        allowed_attempt_ids
    ):
        raise ContinuityRejected("receiver Attempt allowlist is missing or duplicated")
    from contextlib import closing

    with closing(ledger.connect()) as connection:
        rows = connection.execute(
            "SELECT request_id,purpose,operation_id,attempt_id,dispatch_id,"
            "admitted_boot,journal_generation,state,local_dispatch_marker,"
            "signed_request_sha256,signed_receipt_sha256 "
            "FROM receiver_requests WHERE operation_id=? ORDER BY created_at,request_id",
            (logical.operation_id,),
        ).fetchall()
        all_calls = connection.execute(
            "SELECT dispatch_id,request_id FROM native_calls ORDER BY called_at,dispatch_id",
        ).fetchall()
    requests = {row[0]: row for row in rows}
    selected_dispatches = {row[4] for row in rows}
    calls = [item for item in all_calls if item[0] in selected_dispatches]
    if not 1 <= len(rows) <= 32 or len(calls) > 1:
        raise ContinuityRejected("receiver ledger has missing or duplicate effects")
    if (
        len(requests) != len(rows)
        or any(
            row[2] != logical.operation_id
            or row[3] not in allowed_attempt_ids
            or not row[4]
            or not row[5]
            or row[6] < 1
            or row[8] not in (0, 1)
            or not _SHA256.fullmatch(row[9])
            or not _SHA256.fullmatch(row[10])
            for row in rows
        )
        or any(
            request_id not in requests
            or requests[request_id][4] != dispatch_id
            or requests[request_id][1] not in {"delivery.dispatch", "delivery.recover"}
            for dispatch_id, request_id in calls
        )
    ):
        raise ContinuityRejected("receiver ledger request/native lineage changed")
    return {
        "operation_id": logical.operation_id,
        "request_ids": [row[0] for row in rows],
        "states": [row[7] for row in rows],
        "native_dispatch_ids": [item[0] for item in calls],
        "boot_incarnations": sorted({row[5] for row in rows}),
        "journal_generations": sorted({row[6] for row in rows}),
    }
