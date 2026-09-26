from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import psycopg

from runtime.errors import (
    AcceptanceGuardFailed,
    AuthorizationDenied,
    FencingRejected,
    IdempotencyConflict,
    LeaseRejected,
    RevisionConflict,
)
from runtime.models import AuthenticatedContext, CommandEnvelope, LeaseRequest


class LeaseStore(Protocol):
    @property
    def enrollment(self) -> Any: ...

    tenant_id: str
    authority_id: str
    context: AuthenticatedContext

    def _connect(self) -> psycopg.Connection: ...

    def _authorize(self, command: CommandEnvelope, cursor: psycopg.Cursor | None = None,
                   permission: str = "lease.acquire", scope_id: str | None = None) -> None: ...

    def _lock_command_identity(self, cursor: psycopg.Cursor, command: CommandEnvelope) -> None: ...


class LeaseAuthority:
    """A lease mutation and a held file fence serialize on the same resource.

    Lock order is resource, command identities/current authorization, then lease
    and registered owner rows. A returned fence's check_current callback must be
    called immediately before a protected write; expiry is checked using wall
    time even while the transaction remains open.
    """

    def __init__(self, store: LeaseStore) -> None:
        self._store = store

    @property
    def context(self) -> AuthenticatedContext:
        return self._store.context

    @staticmethod
    def _active_attempt(status: object) -> bool:
        return status in ("active", "running", "ready", "started")

    @staticmethod
    def _public_result(result: dict[str, Any], *, duplicate: bool = False) -> dict[str, Any]:
        value = dict(result)
        if isinstance(value.get("expires_at"), str):
            value["expires_at"] = datetime.fromisoformat(value["expires_at"])
        value["duplicate"] = duplicate
        return value

    def _resource_lock(self, cursor: psycopg.Cursor, resource_id: str) -> None:
        identity = json.dumps(("acs-p1-lease", self._store.tenant_id, resource_id), separators=(",", ":"))
        lock_id = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big", signed=True)
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", (lock_id,))

    @staticmethod
    def _now(cursor: psycopg.Cursor) -> datetime:
        cursor.execute("SELECT clock_timestamp()")
        return cursor.fetchone()[0]

    @staticmethod
    def _bind_command(command: CommandEnvelope, operation: str, resource_id: str) -> None:
        if (command.command_type != f"lease.{operation}" or command.target_kind != "lease"
                or command.target_id != resource_id):
            raise LeaseRejected(resource_id, "command type or target does not match lease operation")

    def _read_command(self, resource_id: str, permission: str) -> CommandEnvelope:
        now = datetime.now(UTC)
        return CommandEnvelope(
            command_id=f"lease-read-{uuid.uuid4()}", idempotency_key=f"lease-read-{uuid.uuid4()}",
            correlation_id="lease-authority-read", command_type=permission,
            tenant_id=self.context.tenant_id, authority_id=self.context.authority_id,
            authority_incarnation=self.context.authority_incarnation,
            principal_ref=self.context.principal_ref, grant_ref=self.context.grant_ref,
            target_kind="lease", target_id=resource_id, expected_revision=0,
            issued_at=now, deadline=now + timedelta(minutes=5),
        )

    def _owner_row(self, cursor: psycopg.Cursor, request: LeaseRequest) -> tuple[Any, ...] | None:
        try:
            self._store.enrollment.current_attempt_binding(cursor, request.owner_attempt_id)
        except (AcceptanceGuardFailed, AuthorizationDenied):
            return None
        cursor.execute(
            "SELECT a.attempt_id,a.work_item_id,a.agent_slot_id,a.status,a.runtime_id,"
            "a.scope_id,a.grant_ref,a.authority_id,a.authority_incarnation,w.scope_id,"
            "a.producer_ref,slot.status,slot.scope_id,w.agent_slot_id,w.revision "
            "FROM attempts a JOIN work_items w ON w.tenant_id=a.tenant_id AND w.work_item_id=a.work_item_id "
            "JOIN agent_slots slot ON slot.tenant_id=a.tenant_id AND slot.agent_slot_id=a.agent_slot_id "
            "WHERE a.tenant_id=%s AND a.attempt_id=%s FOR SHARE OF a,w,slot",
            (self._store.tenant_id, request.owner_attempt_id),
        )
        row = cursor.fetchone()
        if row is None or any(value is None for value in row):
            return None
        if (not all(str(row[index]).strip() for index in (0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 12, 13))
                or request.work_item_id is not None and row[1] != request.work_item_id
                or row[4] != request.owner_runtime_id
                or row[5] != request.scope_id or row[9] != request.scope_id or row[12] != request.scope_id
                or row[6] != request.grant_ref or row[6] != self.context.grant_ref
                or row[7] != self.context.authority_id
                or row[8] != request.authority_incarnation or row[8] != self.context.authority_incarnation
                or row[10] != self.context.principal_ref or row[2] != row[13]
                or row[11] != "active" or not self._active_attempt(row[3])):
            return None
        return row

    def _admit_command(self, cursor: psycopg.Cursor, command: CommandEnvelope,
                       result: dict[str, Any] | None, extra: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """Use the Domain journal and the Domain's exact identity-lock scheme.

        A None result is a read-only admission probe before mutable business
        checks. A result inserts only after those checks have passed; all locks
        remain held in the same transaction.
        """
        digest = command.canonical_hash(extra)
        self._store._lock_command_identity(cursor, command)
        cursor.execute(
            "SELECT idempotency_key,command_id,payload_hash,canonical_hash,hash_version,"
            "migration_state,replay_policy,result_json FROM command_dedup WHERE tenant_id=%s AND ("
            "idempotency_key=%s OR command_id=%s OR legacy_command_id=%s "
            "OR legacy_record->>'command_id'=%s OR legacy_record->'result_json'->>'command_id'=%s) "
            "ORDER BY idempotency_key FOR UPDATE",
            (command.tenant_id, command.idempotency_key, command.command_id, command.command_id,
             command.command_id, command.command_id),
        )
        rows = cursor.fetchall()
        if rows:
            if len(rows) != 1:
                raise IdempotencyConflict(command.idempotency_key)
            row = rows[0]
            if (row[:2] != (command.idempotency_key, command.command_id)
                    or row[2:7] != (digest, digest, "v2", "current", "replay_safe")
                    or not isinstance(row[7], dict)
                    or row[7].get("command_id") != command.command_id
                    or row[7].get("resource_id") != command.target_id):
                raise IdempotencyConflict(command.idempotency_key)
            return dict(row[7]), digest
        if command.hash_version != "v2":
            raise IdempotencyConflict(command.idempotency_key)
        if result is not None:
            cursor.execute(
                "INSERT INTO command_dedup(tenant_id,idempotency_key,command_id,payload_hash,hash_version,"
                "canonical_hash,migration_state,replay_policy,result_json) "
                "VALUES (%s,%s,%s,%s,'v2',%s,'current','replay_safe',%s)",
                (command.tenant_id, command.idempotency_key, command.command_id, digest, digest, json.dumps(result)),
            )
        return None, digest

    def _append_journal(self, cursor: psycopg.Cursor, command: CommandEnvelope,
                        operation_id: str, topic: str, payload: dict[str, Any], digest: str,
                        work_item_id: str, *, recovery: bool = False) -> None:
        cursor.execute(
            "INSERT INTO operations(operation_id,tenant_id,command_id,provider,provider_workflow_id,status) "
            "VALUES (%s,%s,%s,'local-lease',%s,'committed')",
            (operation_id, command.tenant_id, command.command_id, f"acs-p1/{command.command_id}"),
        )
        cursor.execute(
            "INSERT INTO domain_events(tenant_id,work_item_id,from_state,to_state,initiated_by,lineage_mode,"
            "command_id,resulting_revision,evidence_refs,command_hash_version,canonical_hash) "
            "VALUES (%s,%s,NULL,%s,%s,%s,%s,%s,%s,'v2',%s)",
            (command.tenant_id, work_item_id, topic, command.principal_ref,
             "deterministic_recovery" if recovery else "external_command",
             command.command_id, command.expected_revision, json.dumps([payload]), digest),
        )
        cursor.execute(
            "INSERT INTO outbox(tenant_id,message_id,operation_id,topic,payload) VALUES (%s,%s,%s,%s,%s)",
            (command.tenant_id, f"msg-{command.command_id}", operation_id, topic, json.dumps(payload)),
        )

    def _lease_row(self, cursor: psycopg.Cursor, lease_id: str, resource_id: str,
                   *, lock: bool = True) -> tuple[Any, ...] | None:
        cursor.execute(
            "SELECT lease_id,generation,fencing_token,status,expires_at,owner_attempt_id,"
            "owner_runtime_id,scope_id,grant_ref,authority_incarnation,authority_id,command_id "
            "FROM leases WHERE tenant_id=%s AND lease_id=%s AND resource_id=%s" + (" FOR UPDATE" if lock else ""),
            (self._store.tenant_id, lease_id, resource_id),
        )
        return cursor.fetchone()

    def acquire_lease(self, command: CommandEnvelope, request: LeaseRequest) -> dict[str, Any]:
        self._bind_command(command, "acquire", request.resource_id)
        extra = {"operation": "acquire", "request": request.model_dump(mode="json")}
        with self._store._connect() as connection, connection.cursor() as cursor:
            self._resource_lock(cursor, request.resource_id)
            self._store._authorize(command, cursor, "lease.acquire", request.scope_id)
            prior, _ = self._admit_command(cursor, command, None, extra)
            if prior is not None:
                return self._public_result(prior, duplicate=True)
            if (request.grant_ref != command.grant_ref or request.authority_incarnation != command.authority_incarnation):
                raise LeaseRejected(request.resource_id, "grant or authority mismatch")
            if request.mode != "exclusive":
                raise LeaseRejected(request.resource_id, "only exclusive leases are supported")
            owner = self._owner_row(cursor, request)
            if owner is None:
                raise LeaseRejected(request.resource_id, "owner registration is incomplete, inactive or mismatched")
            if command.expected_revision != int(owner[14]):
                raise RevisionConflict(str(owner[1]), command.expected_revision, int(owner[14]))
            # Pre-journal lease identities cannot silently bypass the Domain
            # ledger, nor can a fresh key reclaim those identities.
            cursor.execute(
                "SELECT lease_id FROM leases WHERE tenant_id=%s AND (command_id=%s OR idempotency_key=%s) FOR UPDATE",
                (command.tenant_id, command.command_id, command.idempotency_key),
            )
            if cursor.fetchall():
                raise IdempotencyConflict(command.idempotency_key)
            cursor.execute(
                "SELECT lease_id,expires_at FROM leases WHERE tenant_id=%s AND resource_id=%s "
                "AND status='granted' FOR UPDATE", (command.tenant_id, request.resource_id),
            )
            active = cursor.fetchall()
            now = self._now(cursor)
            if len(active) > 1 or any(row[1] > now for row in active):
                raise LeaseRejected(request.resource_id, "resource already leased")
            # Closing expired predecessors is part of this acquire command's
            # atomic result. Do not acquire a second command's identity locks
            # while already holding this command's authorization locks.
            expired_predecessors = [str(row[0]) for row in active]
            cursor.execute("SELECT COALESCE(MAX(generation),0) FROM leases WHERE tenant_id=%s AND resource_id=%s",
                           (command.tenant_id, request.resource_id))
            generation = int(cursor.fetchone()[0]) + 1
            result = {
                "command_id": command.command_id, "operation_id": f"op-{uuid.uuid4()}",
                "lease_id": f"lease-{uuid.uuid4()}", "resource_id": request.resource_id,
                "generation": generation, "fencing_token": secrets.token_hex(16),
                "expires_at": (self._now(cursor) + timedelta(seconds=request.ttl_seconds)).isoformat(), "status": "granted",
                "expired_lease_ids": expired_predecessors,
            }
            self._store._authorize(command, cursor, "lease.acquire", request.scope_id)
            _, digest = self._admit_command(cursor, command, result, extra)
            for predecessor in expired_predecessors:
                cursor.execute("UPDATE leases SET status='expired' WHERE tenant_id=%s AND lease_id=%s",
                               (command.tenant_id, predecessor))
            cursor.execute(
                "INSERT INTO leases(lease_id,tenant_id,resource_id,owner_attempt_id,owner_runtime_id,"
                "authority_id,authority_incarnation,generation,fencing_token,grant_ref,command_id,idempotency_key,"
                "scope_id,request_hash,expires_at,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'granted')",
                (result["lease_id"], command.tenant_id, request.resource_id, request.owner_attempt_id,
                 request.owner_runtime_id, command.authority_id, command.authority_incarnation, generation,
                 result["fencing_token"], command.grant_ref, command.command_id, command.idempotency_key,
                 request.scope_id, digest, result["expires_at"]),
            )
            self._append_journal(cursor, command, result["operation_id"], "lease.acquired", result, digest, str(owner[1]))
            return self._public_result(result)

    def _verify_row(self, cursor: psycopg.Cursor, lease_id: str, resource_id: str,
                    generation: int, fencing_token: str, *, caller: AuthenticatedContext,
                    attempt_id: str | None, runtime_id: str | None, scope_id: str | None,
                    grant_ref: str | None, authority_incarnation: str | None,
                    permission: str) -> tuple[Any, ...]:
        if (caller != self.context or not all((attempt_id, runtime_id, scope_id, grant_ref, authority_incarnation))
                or grant_ref != caller.grant_ref or authority_incarnation != caller.authority_incarnation):
            raise FencingRejected(resource_id)
        # Authorization is performed before the lease/owner rows, in the same
        # order used by command methods. It holds Grant/Scope/Authority rows.
        try:
            self._store._authorize(self._read_command(resource_id, permission), cursor, permission, scope_id)
        except AuthorizationDenied:
            raise FencingRejected(resource_id) from None
        row = self._lease_row(cursor, lease_id, resource_id)
        if (row is None or any(value is None for value in row)
                or row[1] != generation or row[2] != fencing_token or row[3] != "granted"
                or row[4] <= self._now(cursor)
                or row[5:11] != (attempt_id, runtime_id, scope_id, grant_ref, authority_incarnation, caller.authority_id)):
            raise FencingRejected(resource_id)
        request = LeaseRequest(resource_id=resource_id, owner_attempt_id=attempt_id, owner_runtime_id=runtime_id,
                               grant_ref=grant_ref, authority_incarnation=authority_incarnation,
                               scope_id=scope_id, ttl_seconds=1)
        owner = self._owner_row(cursor, request)
        if owner is None:
            raise FencingRejected(resource_id)
        # Preserve historical index positions consumed by hold_fence callers.
        return row[5], row[6], row[7], row[8], row[9], row[3], row[4], owner[1]

    def verify_fence(self, lease_id: str, resource_id: str, generation: int, fencing_token: str, *,
                     caller: AuthenticatedContext | None = None, attempt_id: str | None = None,
                     runtime_id: str | None = None, scope_id: str | None = None, grant_ref: str | None = None,
                     authority_incarnation: str | None = None, permission: str = "effect.write") -> None:
        if permission != "effect.write":
            raise FencingRejected(resource_id)
        with self._store._connect() as connection, connection.cursor() as cursor:
            self._resource_lock(cursor, resource_id)
            self._verify_row(cursor, lease_id, resource_id, generation, fencing_token,
                             caller=caller or self.context, attempt_id=attempt_id, runtime_id=runtime_id,
                             scope_id=scope_id, grant_ref=grant_ref, authority_incarnation=authority_incarnation,
                             permission=permission)

    @contextmanager
    def hold_fence(self, lease_id: str, resource_id: str, generation: int, fencing_token: str, *,
                   caller: AuthenticatedContext, attempt_id: str, runtime_id: str, scope_id: str,
                   grant_ref: str, authority_incarnation: str, permission: str = "effect.write") -> Iterator[dict[str, Any]]:
        if permission != "effect.write":
            raise FencingRejected(resource_id)
        with self._store._connect() as connection, connection.cursor() as cursor:
            self._resource_lock(cursor, resource_id)
            active = True
            def check_current() -> tuple[Any, ...]:
                if not active:
                    raise FencingRejected(resource_id)
                return self._verify_row(cursor, lease_id, resource_id, generation, fencing_token,
                                        caller=caller, attempt_id=attempt_id, runtime_id=runtime_id,
                                        scope_id=scope_id, grant_ref=grant_ref,
                                        authority_incarnation=authority_incarnation, permission=permission)
            row = check_current()
            try:
                yield {"lease_id": lease_id, "resource_id": resource_id, "generation": generation,
                       "fencing_token": fencing_token, "owner_attempt_id": row[0], "owner_runtime_id": row[1],
                       "scope_id": row[2], "grant_ref": row[3], "work_item_id": row[7],
                       "authority_id": caller.authority_id, "authority_incarnation": caller.authority_incarnation,
                       "producer_ref": caller.principal_ref, "check_current": check_current}
            finally:
                active = False

    def verify_historical_readback(self, lease_id: str, resource_id: str, generation: int, fencing_token: str, *,
                                   caller: AuthenticatedContext, scope_id: str, grant_ref: str,
                                   authority_incarnation: str, permission: str = "effect.read") -> None:
        """Read a recorded lease under the caller's current read authorization.

        authority_incarnation identifies the current reader, while the immutable
        historical lease retains its own registered incarnation. Retired
        incarnations remain readable and never regain write authority.
        """
        if (caller != self.context or grant_ref != caller.grant_ref
                or authority_incarnation != caller.authority_incarnation or permission != "effect.read"):
            raise FencingRejected(resource_id)
        with self._store._connect() as connection, connection.cursor() as cursor:
            self._resource_lock(cursor, resource_id)
            self.verify_historical_readback_in_transaction(
                cursor, lease_id, resource_id, generation, fencing_token,
                caller=caller, scope_id=scope_id, grant_ref=grant_ref,
                authority_incarnation=authority_incarnation, permission=permission,
            )

    def verify_historical_readback_in_transaction(
        self, cursor: psycopg.Cursor, lease_id: str, resource_id: str,
        generation: int, fencing_token: str, *, caller: AuthenticatedContext,
        scope_id: str, grant_ref: str, authority_incarnation: str,
        permission: str = "effect.read",
    ) -> None:
        """Internal Domain verification using the caller's existing transaction.

        The Domain caller already holds its WorkItem, current Grant, Scope,
        Authority and historical Lease row locks. The standalone entry above
        instead supplies the resource lock before entering this validator.
        This method must not open a connection or acquire a resource advisory
        lock: either would invert the outer transaction's lock order.
        """
        if (cursor.connection.autocommit
                or cursor.connection.info.transaction_status != psycopg.pq.TransactionStatus.INTRANS
                or caller != self.context or grant_ref != caller.grant_ref
                or authority_incarnation != caller.authority_incarnation or permission != "effect.read"):
            raise FencingRejected(resource_id)
        try:
            self._store._authorize(self._read_command(resource_id, "effect.read"), cursor, "effect.read", scope_id)
        except AuthorizationDenied:
            raise FencingRejected(resource_id) from None
        row = self._lease_row(cursor, lease_id, resource_id)
        if (row is None or row[1] != generation or row[2] != fencing_token
                or row[7] != scope_id or row[10] != caller.authority_id):
            raise FencingRejected(resource_id)
        cursor.execute(
            "SELECT status FROM authority_instances WHERE authority_id=%s "
            "AND authority_incarnation=%s FOR SHARE",
            (row[10], row[9]),
        )
        historical = cursor.fetchone()
        if (historical is None or historical[0] not in ("active", "revoked")
                or historical[0] == "active" and row[9] != caller.authority_incarnation):
            raise FencingRejected(resource_id)

    def _lifecycle(self, command: CommandEnvelope, lease_id: str, resource_id: str,
                    generation: int | None, fencing_token: str | None, *, operation: str,
                    permission: str, status: str, ttl_seconds: int | None = None) -> dict[str, Any]:
        self._bind_command(command, operation, resource_id)
        extra = {"operation": operation, "lease_id": lease_id, "resource_id": resource_id,
                 "generation": generation, "fencing_token": fencing_token, "ttl_seconds": ttl_seconds}
        with self._store._connect() as connection, connection.cursor() as cursor:
            self._resource_lock(cursor, resource_id)
            # Read immutable scope before taking the normal authorization locks.
            cursor.execute("SELECT scope_id FROM leases WHERE tenant_id=%s AND lease_id=%s AND resource_id=%s",
                           (command.tenant_id, lease_id, resource_id))
            scope = cursor.fetchone()
            self._store._authorize(command, cursor, permission, str(scope[0]) if scope else None)
            prior, _ = self._admit_command(cursor, command, None, extra)
            if prior is not None:
                return self._public_result(prior, duplicate=True)
            row = self._lease_row(cursor, lease_id, resource_id)
            if row is None:
                raise LeaseRejected(resource_id, "lease not found")
            if (generation is not None and row[1] != generation
                    or fencing_token is not None and row[2] != fencing_token):
                raise LeaseRejected(resource_id, "stale lease generation or fencing token")
            if operation == "renew" and (ttl_seconds is None or ttl_seconds <= 0 or ttl_seconds > 3600):
                raise LeaseRejected(resource_id, "invalid renewal TTL")
            self._verify_row(cursor, lease_id, resource_id, int(row[1]), str(row[2]),
                             caller=self.context, attempt_id=row[5], runtime_id=row[6], scope_id=row[7],
                             grant_ref=row[8], authority_incarnation=row[9], permission=permission)
            owner = self._owner_row(cursor, LeaseRequest(resource_id=resource_id, owner_attempt_id=row[5],
                owner_runtime_id=row[6], scope_id=row[7], grant_ref=row[8], authority_incarnation=row[9], ttl_seconds=1))
            if owner is None:
                raise LeaseRejected(resource_id, "owner registration is incomplete, inactive or mismatched")
            if command.expected_revision != int(owner[14]):
                raise RevisionConflict(str(owner[1]), command.expected_revision, int(owner[14]))
            expires = self._now(cursor) + timedelta(seconds=ttl_seconds) if operation == "renew" else row[4]
            result = {"command_id": command.command_id, "operation_id": f"op-{uuid.uuid4()}",
                      "lease_id": lease_id, "resource_id": resource_id, "generation": int(row[1]),
                      "fencing_token": row[2], "expires_at": expires.isoformat(), "status": status}
            self._store._authorize(command, cursor, permission, str(row[7]))
            _, digest = self._admit_command(cursor, command, result, extra)
            cursor.execute("UPDATE leases SET expires_at=%s,status=%s WHERE tenant_id=%s AND lease_id=%s",
                           (expires, status, command.tenant_id, lease_id))
            self._append_journal(cursor, command, result["operation_id"], f"lease.{operation}",
                                 result, digest, str(owner[1]))
            return self._public_result(result)

    def renew_lease(self, command: CommandEnvelope, lease_id: str, resource_id: str,
                    generation: int, fencing_token: str, ttl_seconds: int) -> dict[str, Any]:
        return self._lifecycle(command, lease_id, resource_id, generation, fencing_token,
                               operation="renew", permission="lease.renew", status="granted", ttl_seconds=ttl_seconds)

    def release_lease(self, command: CommandEnvelope, lease_id: str, resource_id: str,
                      generation: int, fencing_token: str) -> dict[str, Any]:
        return self._lifecycle(command, lease_id, resource_id, generation, fencing_token,
                               operation="release", permission="lease.release", status="released")

    def revoke_lease(self, command: CommandEnvelope, lease_id: str, resource_id: str,
                     generation: int | None = None, fencing_token: str | None = None) -> dict[str, Any]:
        return self._lifecycle(command, lease_id, resource_id, generation, fencing_token,
                               operation="revoke", permission="lease.revoke", status="revoked")

    def _expire_locked(self, cursor: psycopg.Cursor, lease_id: str, resource_id: str) -> bool:
        row = self._lease_row(cursor, lease_id, resource_id, lock=False)
        if (row is None or row[10] != self._store.authority_id
                or row[3] != "granted" or row[4] > self._now(cursor)):
            return False
        # Expiry is deterministic recovery of recorded state, not an Agent turn.
        # Stable IDs/timestamps make the command independent of scheduler retries.
        identity = hashlib.sha256(json.dumps((self._store.tenant_id, lease_id, row[1], row[4].isoformat()),
                                             separators=(",", ":")).encode()).hexdigest()
        command = CommandEnvelope(
            command_id=f"lease-expiry-{identity}", idempotency_key=f"lease-expiry-{identity}",
            correlation_id=f"lease-expiry-{lease_id}", causation_id=row[11], command_type="lease.expire",
            tenant_id=self._store.tenant_id, authority_id=row[10], authority_incarnation=row[9],
            principal_ref="runtime:lease-expiry", grant_ref=row[8], target_kind="lease",
            target_id=resource_id, expected_revision=0, issued_at=row[4], deadline=row[4],
        )
        result = {"command_id": command.command_id, "operation_id": f"lease-expiry-op-{identity}",
                  "lease_id": lease_id, "resource_id": resource_id, "generation": row[1],
                  "expires_at": row[4].isoformat(), "status": "expired"}
        extra = {"operation": "expire", "lease_id": lease_id, "resource_id": resource_id,
                 "generation": row[1], "expires_at": row[4].isoformat(), "original_command_id": row[11],
                 "original_grant_ref": row[8]}
        prior, digest = self._admit_command(cursor, command, None, extra)
        if prior is not None:
            return False
        locked = self._lease_row(cursor, lease_id, resource_id)
        if locked != row or locked[3] != "granted" or locked[4] > self._now(cursor):
            return False
        self._admit_command(cursor, command, result, extra)
        cursor.execute("UPDATE leases SET status='expired' WHERE tenant_id=%s AND lease_id=%s",
                       (self._store.tenant_id, lease_id))
        cursor.execute("SELECT work_item_id FROM attempts WHERE tenant_id=%s AND attempt_id=%s",
                       (self._store.tenant_id, row[5]))
        owner = cursor.fetchone()
        self._append_journal(cursor, command, result["operation_id"], "lease.expired", result, digest,
                             str(owner[0]) if owner else resource_id, recovery=True)
        return True

    def expire_leases(self) -> int:
        """Trusted Core maintenance API, not an externally dispatchable command."""
        with self._store._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT lease_id,resource_id FROM leases WHERE tenant_id=%s AND authority_id=%s "
                           "AND status='granted' AND expires_at<=clock_timestamp() ORDER BY resource_id,lease_id",
                           (self._store.tenant_id, self._store.authority_id))
            candidates = cursor.fetchall()
        expired = 0
        # One resource per transaction avoids holding multiple resource locks in
        # an order dependent on the set of concurrently expiring rows.
        for lease_id, resource_id in candidates:
            with self._store._connect() as connection, connection.cursor() as cursor:
                self._resource_lock(cursor, str(resource_id))
                expired += int(self._expire_locked(cursor, str(lease_id), str(resource_id)))
        return expired

    def inspect_lease(self, lease_id: str, resource_id: str | None = None) -> dict[str, Any] | None:
        with self._store._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT resource_id,scope_id FROM leases WHERE tenant_id=%s AND lease_id=%s",
                           (self._store.tenant_id, lease_id))
            identity = cursor.fetchone()
            if identity is None:
                return None
            if resource_id is not None and identity[0] != resource_id:
                return None
            resource_id = str(identity[0])
            self._resource_lock(cursor, resource_id)
            self._store._authorize(self._read_command(resource_id, "lease.inspect"), cursor, "lease.inspect", str(identity[1]))
            row = self._lease_row(cursor, lease_id, resource_id)
            if row is None:
                return None
            if (row[8] != self.context.grant_ref or row[9] != self.context.authority_incarnation
                    or row[10] != self.context.authority_id):
                raise FencingRejected(resource_id)
            return {"lease_id": row[0], "resource_id": resource_id, "generation": row[1],
                    "fencing_token": row[2], "status": row[3], "expires_at": row[4],
                    "owner_attempt_id": row[5], "owner_runtime_id": row[6], "scope_id": row[7],
                    "grant_ref": row[8], "authority_incarnation": row[9]}
