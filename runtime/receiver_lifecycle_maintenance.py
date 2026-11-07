"""Bounded deterministic continuation of already accepted lifecycle operations.

Scheduling lives in the existing recovery Outbox payload. A Runtime-installed
transport/catalog is required; no bearer, sender or new command is synthesized.
Every effect reuses the original issuer's current Core/Node authorization.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from runtime.project_service import ProjectService
from runtime.receiver_lifecycle_contract import SignedLifecyclePermit
from runtime.receiver_lifecycle_domain import original_lifecycle_source
from runtime.receiver_lifecycle_executor import LifecycleExecutorRejected, ReceiverLifecycleExecutor
from runtime.receiver_lifecycle_issuance import _possible, _state
from runtime.receiver_lifecycle_readback import require_original_lifecycle_read
from runtime.receiver_rebind import lifecycle_receiver
from runtime.receiver_recovery_operations import (
    FINAL,
    TOPIC,
    ReceiverRecoveryOperations,
    RecoveryRequest,
)

MAX_LIFECYCLE_INFLIGHT = 2
LEASE_SECONDS = 180
ACTIVE_STATES = ("queued", "preparing", "deferred", "submitting", "unknown")


def _micros(now):
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("lifecycle maintenance requires actual aware Authority time")
    return int(now.astimezone(UTC).timestamp() * 1_000_000)


@dataclass(frozen=True)
class LifecycleWork:
    tenant_id: str
    project_id: str
    operation_ref: str
    receiver_id: str
    owner_token: str


def claim_lifecycle_work(authority, *, exclude=(), limit=MAX_LIFECYCLE_INFLIGHT, lease_seconds=LEASE_SECONDS):
    if (type(limit) is not int or not 1 <= limit <= 16
            or type(lease_seconds) is not int or not 1 <= lease_seconds <= 300):
        raise ValueError("lifecycle maintenance budgets must be explicit bounded integers")
    endpoints = getattr(authority, "_receiver_lifecycle_transports", {})
    if not endpoints or getattr(authority, "_receiver_lifecycle_catalog", None) is None:
        return []
    claimed = []
    with authority.transaction() as (_bound, connection), connection.cursor() as cursor:
        now = _micros(authority.canonical_now(cursor))
        cursor.execute("SELECT operation_id,payload FROM outbox WHERE tenant_id=%s AND topic=%s "
            "AND payload->'request'->>'action' IN ('prepare_receiver','resume_receiver','rebind_receiver') "
            "AND payload->'operation'->>'state'=ANY(%s::text[]) "
            "AND (CASE WHEN payload->'request'->>'action'='rebind_receiver' "
            "THEN payload->'rebind_selection'->>'target_endpoint_id' ELSE payload->>'receiver_id' END)=ANY(%s::text[]) "
            "AND NOT (operation_id=ANY(%s::text[])) "
            "AND COALESCE(payload->'maintenance'->'not_before_us','0'::jsonb)<=to_jsonb(%s::bigint) "
            "ORDER BY COALESCE(payload->'maintenance'->'not_before_us','0'::jsonb),created_at,operation_id "
            "LIMIT %s FOR UPDATE SKIP LOCKED",
            (authority.tenant_id, TOPIC, list(ACTIVE_STATES), list(endpoints), list(exclude), now, limit))
        for operation_ref, payload in cursor.fetchall():
            try:
                request = RecoveryRequest.model_validate(payload["request"])
                old = payload.get("maintenance") or {}
                attempts = old.get("attempts", 0)
                if (payload.get("schema_version") != "acs-receiver-recovery/1"
                        or payload["operation"].get("operation_id") != operation_ref
                        or request.action not in {"prepare_receiver", "resume_receiver", "rebind_receiver"}
                        or type(payload.get("project_id")) is not str or not payload["project_id"]
                        or type(attempts) is not int or not 0 <= attempts <= 2**31 - 2):
                    raise ValueError("invalid retained lifecycle scheduling source")
            except (ValueError, TypeError, KeyError, AttributeError):
                # A corrupt accepted row is never repaired or executed here.
                # Pace only its scheduling metadata so independent due rows
                # cannot be starved by a repeatedly failing first candidate.
                scheduling = {"owner_token": None, "attempts": 0,
                    "not_before_us": now + 30_000_000, "reason_code": "lifecycle_scheduling_source_invalid"}
                cursor.execute("UPDATE outbox SET payload=jsonb_set(payload,'{maintenance}',%s::jsonb) "
                    "WHERE tenant_id=%s AND topic=%s AND operation_id=%s",
                    (json.dumps(scheduling), authority.tenant_id, TOPIC, operation_ref))
                continue
            token = uuid4().hex
            scheduling = {"owner_token": token, "attempts": attempts + 1,
                "not_before_us": now + lease_seconds * 1_000_000}
            cursor.execute("UPDATE outbox SET payload=jsonb_set(payload,'{maintenance}',%s::jsonb) "
                "WHERE tenant_id=%s AND topic=%s AND operation_id=%s",
                (json.dumps(scheduling), authority.tenant_id, TOPIC, operation_ref))
            claimed.append(LifecycleWork(authority.tenant_id, payload["project_id"], operation_ref,
                payload["receiver_id"], token))
    return claimed


def _leased(authority, cursor, work, payload):
    scheduled = payload.get("maintenance") or {}
    if (work.tenant_id != authority.tenant_id or work.project_id != payload.get("project_id")
            or work.operation_ref != payload.get("operation", {}).get("operation_id")
            or work.receiver_id != payload.get("receiver_id") or scheduled.get("owner_token") != work.owner_token
            or type(scheduled.get("not_before_us")) is not int
            or scheduled["not_before_us"] <= _micros(authority.canonical_now(cursor))):
        raise LifecycleExecutorRejected("original lifecycle maintenance lease is no longer current")


def finish_lifecycle_work(authority, work):
    """Pace only this lease; a late worker cannot overwrite its successor."""
    with authority.transaction() as (_bound, connection), connection.cursor() as cursor:
        cursor.execute("SELECT payload FROM outbox WHERE tenant_id=%s AND topic=%s AND operation_id=%s FOR UPDATE",
            (authority.tenant_id, TOPIC, work.operation_ref))
        row = cursor.fetchone()
        if row is None:
            return
        payload, now = row[0], _micros(authority.canonical_now(cursor))
        schedule = payload.get("maintenance") or {}
        if schedule.get("owner_token") != work.owner_token:
            return
        attempts = schedule.get("attempts", 1)
        if type(attempts) is not int or not 1 <= attempts <= 2**31 - 1:
            return
        # Unknown may have an original positive receipt still arriving. It
        # remains readback-only; backoff never makes it an executable retry.
        delay = min(30, 2 ** min(attempts - 1, 5))
        schedule = {"owner_token": None, "attempts": attempts,
            "not_before_us": now + delay * 1_000_000}
        cursor.execute("UPDATE outbox SET payload=jsonb_set(payload,'{maintenance}',%s::jsonb) "
            "WHERE tenant_id=%s AND topic=%s AND operation_id=%s",
            (json.dumps(schedule), authority.tenant_id, TOPIC, work.operation_ref))


class _CommittedLifecycleExecutor(ReceiverLifecycleExecutor):
    """Runtime-only original-command continuation, never an HTTP caller mode."""
    def __init__(self, recovery, transport, work):
        super().__init__(recovery, transport)
        self.work = work

    def _caller(self, cursor, authority, project, operation_ref, _credential):
        if (project, operation_ref) != (self.work.project_id, self.work.operation_ref):
            raise LifecycleExecutorRejected("maintenance cannot select another original operation")
        payload = self.recovery._row(cursor, project, operation_ref, lock=True)
        _leased(authority, cursor, self.work, payload)
        request = RecoveryRequest.model_validate(payload["request"])
        if (request.action not in {"prepare_receiver", "resume_receiver", "rebind_receiver"}
                or lifecycle_receiver(payload)[0] != self.config.binding.registration.endpoint_id):
            raise LifecycleExecutorRejected("maintenance original action or installed receiver differs")
        if payload["operation"]["state"] in FINAL and payload["operation"]["state"] != "unknown":
            return payload
        data = _state(payload)
        if _possible(payload, data):
            if data is None or data.get("permit") is None:
                raise LifecycleExecutorRejected("possible lifecycle effect has no original read artifacts")
            signed = SignedLifecyclePermit.model_validate_json(json.dumps(data["permit"]), strict=True)
            require_original_lifecycle_read(self.recovery, cursor, signed)
        else:
            original_lifecycle_source(self.recovery, cursor, payload)
        return payload

    def _operation(self, project, operation_ref, _credential):
        # Technical outcome is used only by this trusted worker, not disclosed
        # under its operator's identity to a replaced/revoked external caller.
        with self.authority.transaction() as (_authority, connection), connection.cursor() as cursor:
            return self.recovery._row(cursor, project, operation_ref)["operation"]


def advance_lifecycle_work(service, work):
    authority = service.authority
    if (type(work) is not LifecycleWork or work.tenant_id != authority.tenant_id
            or getattr(authority, "_receiver_lifecycle_catalog", None) is None):
        raise LifecycleExecutorRejected("accepted tenant operation and installed Runtime catalog required")
    projects = ProjectService(service, authority._receiver_lifecycle_catalog, profile="engineer")
    recovery = ReceiverRecoveryOperations(projects)
    with authority.transaction() as (_bound, connection), connection.cursor() as cursor:
        payload = recovery._row(cursor, work.project_id, work.operation_ref, lock=True)
        _leased(authority, cursor, work, payload)
        endpoint_id, _epoch = lifecycle_receiver(payload)
    transport = getattr(authority, "_receiver_lifecycle_transports", {}).get(endpoint_id)
    if transport is None:
        raise LifecycleExecutorRejected("original lifecycle transport is no longer installed")
    executor = _CommittedLifecycleExecutor(recovery, transport, work)
    return executor.advance(work.project_id, work.operation_ref, None)
