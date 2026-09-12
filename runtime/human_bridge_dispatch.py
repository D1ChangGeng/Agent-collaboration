"""Dispatch committed Human Bridge Outbox effects to the local file provider."""
from __future__ import annotations

import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from runtime.human_bridge_file_provider import (
    CopyReadyEnvelope,
    LocalHumanBridgeTransport,
    NotificationIntent,
    TrustedSurfaceContext,
    provider_attempt_id,
)
from runtime.models import CommandEnvelope
from runtime.recovery_service import RecoveryService


def provision_local_provider(root: str | Path) -> Path:
    if os.name != "posix":
        raise ValueError("Human Bridge local provider requires POSIX owner-only paths")
    path = Path(root)
    if not path.is_absolute():
        raise ValueError("Human Bridge provider root must be absolute")
    created = False
    try:
        os.mkdir(path, 0o700)
        created = True
    except FileExistsError:
        pass
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
            raise ValueError("Human Bridge provider root ownership is invalid")
        if created:
            os.fchmod(descriptor, 0o700)
            os.fsync(descriptor)
        elif stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("existing Human Bridge provider root is not owner-only")
    finally:
        os.close(descriptor)
    provider = LocalHumanBridgeTransport(path)
    provider.close()
    return path


class HumanBridgeProviderDispatcher:
    """Read one committed request and publish/reconcile one stable local effect."""

    def __init__(self, dsn: str, root: str | Path) -> None:
        self.dsn = dsn
        self.provider = LocalHumanBridgeTransport(root)

    def close(self) -> None:
        self.provider.close()

    def __call__(self, identity: dict[str, Any]) -> dict[str, Any]:
        request_id = identity.get("request_id")
        tenant_id = identity.get("tenant_id")
        if not isinstance(request_id, str) or not isinstance(tenant_id, str):
            raise TypeError("Human Bridge request identity is incomplete")
        with psycopg.connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT r.incident_id,r.generation,r.canonical_digest,i.expires_at,"
                "i.accepted_state_digest FROM human_bridge_requests r "
                "JOIN recovery_incidents i ON i.tenant_id=r.tenant_id "
                "AND i.incident_id=r.incident_id WHERE r.tenant_id=%s AND r.request_id=%s",
                (tenant_id, request_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError("committed Human Bridge request is unavailable")
            incident_id, generation, packet_digest, expires_at, artifact_digest = row
            if expires_at <= datetime.now(UTC):
                raise ValueError("Human Bridge request is expired")
        envelope = CopyReadyEnvelope(
            incident_id=incident_id,
            request_id=request_id,
            generation=generation,
            expires_at=expires_at,
            packet_digest=packet_digest,
            artifact_digest=artifact_digest,
        )
        effect_id = "human-bridge:" + request_id
        intent = NotificationIntent(
            effect_id=effect_id,
            provider_attempt_id=provider_attempt_id(effect_id),
            incident_id=incident_id,
            request_id=request_id,
            generation=generation,
            expires_at=expires_at,
            packet_digest=packet_digest,
            artifact_digest=artifact_digest,
            envelope=envelope,
        )
        published = self.provider.publish(intent)
        observed = self.provider.readback(effect_id)
        if observed["file_digest"] != published["file_digest"]:
            raise ValueError("Human Bridge provider readback changed")
        with psycopg.connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE outbox SET delivered_at=COALESCE(delivered_at,clock_timestamp()) "
                "WHERE tenant_id=%s AND message_id=%s AND topic='human_bridge.request'",
                (tenant_id, request_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Human Bridge Outbox identity is unavailable")
        return {
            "status": "published",
            "tenant_id": tenant_id,
            "request_id": request_id,
            "effect_id": effect_id,
            "provider_attempt_id": published["provider_attempt_id"],
            "file_digest": published["file_digest"],
            "filename": published["filename"],
        }


class HumanBridgeManualInbox:
    """Turn an owner-only file observation into the normal authenticated Domain command."""

    def __init__(self, authority: Any, root: str | Path) -> None:
        self.authority = authority
        self.provider = LocalHumanBridgeTransport(root)
        self.recovery = RecoveryService(authority)

    def close(self) -> None:
        self.provider.close()

    def receive(self, filename: str, incident_id: str, command: CommandEnvelope) -> Any:
        with self.authority._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT generation,message_id,operation_id,source_scope_id,target_scope_id,"
                "accepted_revision,accepted_state_digest,expires_at,state "
                "FROM recovery_incidents WHERE tenant_id=%s AND incident_id=%s",
                (command.tenant_id, incident_id),
            )
            incident = cursor.fetchone()
            if incident is None:
                raise ValueError("Human Bridge incident is unavailable")
            self.authority._authorize(
                command, cursor, "human_bridge.receive", str(incident[3]),
            )
            cursor.execute(
                "SELECT attempt_id,dispatch_id FROM delivery_attempts "
                "WHERE tenant_id=%s AND message_id=%s ORDER BY ordinal DESC LIMIT 1",
                (command.tenant_id, incident[1]),
            )
            attempt = cursor.fetchone()
            if attempt is None or attempt[1] is None:
                raise ValueError("Human Bridge delivery attempt is unavailable")
        context = TrustedSurfaceContext(
            authenticated=True,
            tenant_id=command.tenant_id,
            principal_ref=command.principal_ref,
            grant_ref=command.grant_ref,
            incident_id=incident_id,
            incident_generation=incident[0],
            incident_state=incident[8],
            expected_revision=incident[5],
            accepted_state_digest=incident[6],
            deadline=min(command.deadline, incident[7]),
        )
        observed = self.provider.receive_manual(
            filename, context=context, now=datetime.now(UTC),
        )
        packet = {
            "packet_id": observed["packet_id"],
            "incident_id": incident_id,
            "incident_generation": incident[0],
            "tenant_id": command.tenant_id,
            "message_id": observed["message_id"],
            "operation_id": observed["operation_id"],
            "attempt_id": attempt[0],
            "dispatch_id": attempt[1],
            "source_scope_id": incident[3],
            "target_scope_id": incident[4],
            "direction": observed["direction"],
            "expected_accepted_revision": incident[5],
            "accepted_state_digest": incident[6],
            "payload_digest": observed["payload_digest"],
            "expires_at": incident[7],
        }
        return self.recovery.execute(
            command, "recovery.manual.receive",
            {"incident_id": incident_id, "packet": packet},
        )
