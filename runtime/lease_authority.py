from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol

import psycopg

from runtime.errors import FencingRejected, LeaseRejected
from runtime.models import CommandEnvelope, LeaseRequest


class LeaseStore(Protocol):
    @property
    def tenant_id(self) -> str: ...

    @property
    def authority_id(self) -> str: ...

    def _connect(self) -> psycopg.Connection: ...

    def _authorize(self, command: CommandEnvelope, cursor: psycopg.Cursor | None = None, permission: str = "lease.acquire", scope_id: str | None = None) -> None: ...


class LeaseAuthority:
    def __init__(self, store: LeaseStore) -> None:
        self._store = store

    def acquire_lease(self, command: CommandEnvelope, request: LeaseRequest) -> dict[str, str | int | datetime]:
        now = datetime.now(UTC)
        lease_id = f"lease-{uuid.uuid4()}"
        token = secrets.token_hex(16)
        request_hash = hashlib.sha256(
            json.dumps(
                {
                    "command": command.model_dump(mode="json"),
                    "request": request.model_dump(mode="json"),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with self._store._connect() as connection, connection.cursor() as cursor:
            self._store._authorize(command, cursor, "lease.acquire", request.scope_id)
            if request.grant_ref != command.grant_ref or request.authority_incarnation != command.authority_incarnation:
                raise LeaseRejected(request.resource_id, "grant or authority mismatch")
            if request.work_item_id is not None:
                cursor.execute("SELECT 1 FROM work_items WHERE work_item_id=%s AND tenant_id=%s AND scope_id=%s", (request.work_item_id, self._store.tenant_id, request.scope_id))
                if cursor.fetchone() is None:
                    raise LeaseRejected(request.resource_id, "owner work item mismatch")
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"acs-p1-lease:{self._store.tenant_id}:{request.resource_id}",))
            cursor.execute("SELECT lease_id,generation,expires_at,fencing_token,owner_attempt_id,owner_runtime_id,request_hash FROM leases WHERE tenant_id=%s AND command_id=%s OR (tenant_id=%s AND idempotency_key=%s) FOR UPDATE", (self._store.tenant_id, command.command_id, self._store.tenant_id, command.idempotency_key))
            prior = cursor.fetchone()
            if prior is not None:
                if prior[6] != request_hash:
                    raise LeaseRejected(request.resource_id, "lease identity reused with different input")
                return {"lease_id": prior[0], "resource_id": request.resource_id, "generation": int(prior[1]), "fencing_token": prior[3], "expires_at": prior[2], "duplicate": True}
            cursor.execute(
                "SELECT lease_id, generation, expires_at FROM leases WHERE tenant_id=%s AND resource_id=%s AND status='granted' FOR UPDATE",
                (self._store.tenant_id, request.resource_id),
            )
            current = cursor.fetchone()
            if current is not None and current[2] > now:
                raise LeaseRejected(request.resource_id, "resource already leased")
            cursor.execute("SELECT generation FROM leases WHERE tenant_id=%s AND resource_id=%s", (self._store.tenant_id, request.resource_id))
            generations = [int(row[0]) for row in cursor.fetchall()]
            generation = max(generations, default=0) + 1
            if current is not None:
                cursor.execute("UPDATE leases SET status='expired' WHERE lease_id=%s", (current[0],))
            expires_at = now + timedelta(seconds=request.ttl_seconds)
            cursor.execute(
                """
                INSERT INTO leases (lease_id, tenant_id, resource_id, owner_attempt_id, owner_runtime_id, authority_id, authority_incarnation, generation, fencing_token, grant_ref, command_id, idempotency_key, scope_id, request_hash, expires_at, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'granted')
                """,
                (lease_id, self._store.tenant_id, request.resource_id, request.owner_attempt_id, request.owner_runtime_id, self._store.authority_id, request.authority_incarnation, generation, token, request.grant_ref, command.command_id, command.idempotency_key, request.scope_id, request_hash, expires_at),
            )
        return {"lease_id": lease_id, "resource_id": request.resource_id, "generation": generation, "fencing_token": token, "expires_at": expires_at}

    def verify_fence(self, lease_id: str, resource_id: str, generation: int, fencing_token: str) -> None:
        with self._store._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM leases l JOIN grants g ON g.grant_ref=l.grant_ref AND g.tenant_id=l.tenant_id AND g.authority_id=l.authority_id AND g.authority_incarnation=l.authority_incarnation JOIN authority_instances a ON a.authority_id=l.authority_id AND a.authority_incarnation=l.authority_incarnation WHERE l.lease_id=%s AND l.tenant_id=%s AND l.resource_id=%s AND l.generation=%s AND l.fencing_token=%s AND l.status='granted' AND l.expires_at>now() AND g.revoked_at IS NULL AND g.expires_at>now() AND a.status='active'",
                (lease_id, self._store.tenant_id, resource_id, generation, fencing_token),
            )
            if cursor.fetchone() is None:
                raise FencingRejected(resource_id)
