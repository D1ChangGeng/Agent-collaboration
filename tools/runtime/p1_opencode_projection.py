"""Collect one original OpenCode response into Node CAS and PostgreSQL."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from runtime.artifacts import LocalArtifactStore
from runtime.codex_driver import OutcomeUncertain
from runtime.delivery_models import InvocationRequest
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.node import NodeJournal
from runtime.opencode_driver import OpenCodeNativeDriver
from runtime.recovery import AuthoritySnapshot, PostgresDelayedResponseAuthority
from runtime.recovery_models import BoundaryRejected
from runtime.response_collector import NativeResponseCollector, artifact_response_store


def project_original_opencode_terminal(
    dispatch: dict[str, Any],
    node: NodeJournal,
    driver: OpenCodeNativeDriver,
    adapter: NativeDeliveryAdapter,
    artifact_root: Path,
    *,
    max_collect_reads: int = 6,
) -> dict[str, Any]:
    if not 1 <= max_collect_reads <= 6:
        raise BoundaryRejected("OpenCode terminal readback budget is invalid")
    authority = dispatch["authority"]
    identity = dispatch["identity"]
    with authority._connect() as connection:
        row = connection.execute(
            "SELECT invocation_json FROM delivery_attempts "
            "WHERE message_id=%s AND attempt_id=%s AND dispatch_id=%s",
            (identity["message_id"], dispatch["attempt_id"], dispatch["dispatch_id"]),
        ).fetchone()
    if row is None or not isinstance(row[0], dict):
        raise BoundaryRejected("OpenCode original PG invocation is unavailable")
    invocation = InvocationRequest.model_validate_json(json.dumps(row[0]), strict=True)
    if invocation.invocation_id != dispatch["invocation_id"]:
        raise BoundaryRejected("OpenCode collector left original attempt")

    def snapshot(cursor: Any, observation: Any) -> AuthoritySnapshot:
        native = observation.identity
        message = cursor.execute(
            "SELECT packet_json,envelope_json,deadline,policy_hash,accepted_state_digest "
            "FROM delivery_messages WHERE tenant_id=%s AND message_id=%s FOR UPDATE",
            (native.tenant_id, native.message_id),
        ).fetchone()
        attempt = cursor.execute(
            "SELECT invocation_json,attempt_id,status FROM delivery_attempts "
            "WHERE tenant_id=%s AND message_id=%s ORDER BY ordinal DESC LIMIT 1 FOR UPDATE",
            (native.tenant_id, native.message_id),
        ).fetchone()
        if message is None or attempt is None or not isinstance(attempt[0], dict):
            raise BoundaryRejected("OpenCode current PG delivery identity is absent")
        recorded = InvocationRequest.model_validate_json(json.dumps(attempt[0]), strict=True)
        if NativeResponseCollector.dispatch_identity(recorded) != native:
            raise BoundaryRejected("OpenCode terminal is not current PG dispatch")
        envelope = message[1]
        grant = cursor.execute(
            "SELECT revoked_at,expires_at,principal_ref,authority_id,authority_incarnation "
            "FROM grants WHERE grant_ref=%s AND tenant_id=%s FOR UPDATE",
            (envelope["grant_ref"], native.tenant_id),
        ).fetchone()
        work = cursor.execute(
            "SELECT state,execution_status FROM work_items WHERE work_item_id=%s "
            "AND tenant_id=%s FOR UPDATE",
            (message[0]["work_item_id"], native.tenant_id),
        ).fetchone()
        authorized = bool(
            grant
            and grant[0] is None
            and grant[1] > datetime.now(UTC)
            and grant[2] == envelope["principal_ref"]
            and (grant[3], grant[4])
            == (authority.context.authority_id, authority.context.authority_incarnation)
        )
        producer = False
        try:
            adapter._check_binding()
            record = driver.journal.read(native.invocation_id)
            producer = (
                node.node_id == native.node_id
                and node.boot_incarnation == native.boot_incarnation
                and any(receipt.layer == "runtime_dispatched" for receipt in node.receipts(native.operation_id))
                and record is not None
                and record["state"] == "acknowledged"
            )
        except (RuntimeError, ValueError, TypeError, KeyError):
            producer = False
        return AuthoritySnapshot(
            committed_identity=NativeResponseCollector.dispatch_identity(recorded),
            producer_authenticated=producer,
            current_authority_valid=authorized,
            task_valid=bool(
                work and work[0] == "candidate"
                and work[1] not in {"blocked", "failed", "cancelled"}
            ),
            current_attempt_id=attempt[1],
            current_accepted_revision=message[0]["accepted_revision"],
            current_accepted_state_digest=message[4],
            deadline=message[2],
            principal_ref=envelope["principal_ref"],
            grant_ref=envelope["grant_ref"],
            policy_version="p1-opencode:" + message[3],
        )

    outbox = node.response_outbox()
    projector = PostgresDelayedResponseAuthority(authority._dsn, snapshot)
    with LocalArtifactStore(artifact_root, scope_id="local-scope") as store:
        collector = NativeResponseCollector(
            adapter, outbox, artifact_response_store(store), projector.project,
        )
        started = time.monotonic()
        for index in range(max_collect_reads):
            try:
                disposition = collector.collect_and_project(invocation)
                break
            except OutcomeUncertain:
                if index + 1 == max_collect_reads:
                    raise
                remaining = 120.0 - (time.monotonic() - started)
                reads_left = max_collect_reads - index - 1
                if remaining <= 0:
                    raise OutcomeUncertain("OpenCode terminal readback exceeded the scene deadline")
                time.sleep(min(remaining / reads_left, remaining))
        observed = outbox.by_invocation(NativeResponseCollector.dispatch_identity(invocation))
        if observed is None or observed.projection_id != disposition.projection_id:
            raise BoundaryRejected("OpenCode Node Outbox differs from PG projection")
        artifact_sha = observed.response_artifact_ref.removeprefix("artifact:")
        artifact = artifact_root / artifact_sha[:2] / artifact_sha
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != observed.response_digest:
            raise BoundaryRejected("OpenCode terminal CAS readback differs")
        return {
            "projection_id": disposition.projection_id,
            "disposition": disposition.disposition,
            "response_artifact_ref": observed.response_artifact_ref,
            "response_digest": observed.response_digest,
            "invocation_id": invocation.invocation_id,
            "attempt_id": invocation.attempt_id,
            "dispatch_id": invocation.dispatch_id,
            "collector_reads": index + 1,
        }
