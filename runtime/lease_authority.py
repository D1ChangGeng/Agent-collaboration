from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol

import psycopg

from runtime.errors import FencingRejected, LeaseRejected
from runtime.models import CommandEnvelope, LeaseRequest


class LeaseStore(Protocol):
    tenant_id: str

    def _connect(self) -> psycopg.Connection: ...

    def _authorize(self, command: CommandEnvelope, cursor: psycopg.Cursor | None = None) -> None: ...


class LeaseAuthority:
    def __init__(self, store: LeaseStore) -> None:
        self._store = store

    def acquire_lease(self, command: CommandEnvelope, request: LeaseRequest) -> dict[str, str | int | datetime]:
        now = datetime.now(UTC)
        lease_id = f"lease-{uuid.uuid4()}"
        token = secrets.token_hex(16)
        with self._store._connect() as connection, connection.cursor() as cursor:
            self._store._authorize(command, cursor)
            cursor.execute(
                "SELECT lease_id, generation, expires_at FROM leases WHERE tenant_id=%s AND resource_id=%s AND status='granted' FOR UPDATE",
                (self._store.tenant_id, request.resource_id),
            )
            current = cursor.fetchone()
            if current is not None and current[2] > now:
                raise LeaseRejected(request.resource_id, "resource already leased")
            generation = 1 if current is None else int(current[1]) + 1
            if current is not None:
                cursor.execute("UPDATE leases SET status='expired' WHERE lease_id=%s", (current[0],))
            expires_at = now + timedelta(seconds=request.ttl_seconds)
            cursor.execute(
                """
                INSERT INTO leases (lease_id, tenant_id, resource_id, owner_attempt_id, owner_runtime_id, authority_incarnation, generation, fencing_token, grant_ref, expires_at, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'granted')
                """,
                (lease_id, self._store.tenant_id, request.resource_id, request.owner_attempt_id, request.owner_runtime_id, request.authority_incarnation, generation, token, request.grant_ref, expires_at),
            )
        return {"lease_id": lease_id, "resource_id": request.resource_id, "generation": generation, "fencing_token": token, "expires_at": expires_at}

    def verify_fence(self, lease_id: str, resource_id: str, generation: int, fencing_token: str) -> None:
        with self._store._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM leases WHERE lease_id=%s AND tenant_id=%s AND resource_id=%s AND generation=%s AND fencing_token=%s AND status='granted' AND expires_at>now()",
                (lease_id, self._store.tenant_id, resource_id, generation, fencing_token),
            )
            if cursor.fetchone() is None:
                raise FencingRejected(resource_id)
