from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from contextlib import contextmanager, nullcontext
from copy import copy
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from runtime.communication_permissions import expanded_permissions
from runtime.errors import (
    AuthorizationDenied,
    IdempotencyConflict,
)
from runtime.migrations import LegacyCommandRecord, classify_replay
from runtime.models import (
    AuthenticatedContext,
    CommandEnvelope,
    CommandResult,
)


class DomainAuthority:
    """Authenticated communication, source access and technical registration."""

    SCHEMA_NAME = "acs-communication-core"
    SCHEMA_VERSION = "1"

    def __init__(
        self,
        dsn: str,
        context: AuthenticatedContext | None = None,
        artifact_store: Any | None = None,
        *,
        authority_binding: tuple[str, str] = ("acs-p1-authority", "local-1"),
        delivery_endpoints: Mapping[str, Any] | None = None,
        node_response_reader: Any | None = None,
        access_mode: str = "shared",
    ) -> None:
        if access_mode not in {"owner", "shared"}:
            raise ValueError("unsupported service access mode")
        self.access_mode = access_mode
        self._dsn = dsn
        self._authority_binding = authority_binding
        self.context = context or AuthenticatedContext(
            "local-tenant",
            "acs-p1-authority",
            "local-1",
            "agent:engineer",
            "grant:p1",
        )
        self.owner_identity_ref = self.context.grant_ref
        self._artifact_store = artifact_store
        self._delivery_endpoints = dict(delivery_endpoints or {})
        self._node_response_reader = node_response_reader
        self._transaction_connection: psycopg.Connection | None = None

    def send_message(self, command: CommandEnvelope, packet: Any, *, endpoint_id: str,
                     binding_revision: int) -> CommandResult:
        from runtime.delivery import DeliveryService

        if getattr(packet, "schema_version", None) not in {"acs-message/1", "acs-notice/1"}:
            from runtime.delivery import DeliveryRejected
            raise DeliveryRejected("historical_delivery_read_only")

        return DeliveryService(self, self._delivery_endpoints).send_message(
            command, packet, endpoint_id=endpoint_id, binding_revision=binding_revision,
        )

    def bind_message_endpoint(self, command: CommandEnvelope, request: Any) -> CommandResult:
        from runtime.delivery import DeliveryService

        return DeliveryService(self, self._delivery_endpoints).bind_endpoint(command, request)

    def read_message(self, command: CommandEnvelope, message_id: str) -> dict[str, Any]:
        from runtime.delivery import DeliveryService

        return DeliveryService(self, self._delivery_endpoints).inspect(command, message_id)


    def bind_artifact_store(self, command: CommandEnvelope, store: Any) -> Any:
        """Bind a filesystem CAS to the authenticated command's data policy.

        The underlying store remains responsible for dirfd, ownership, scope,
        immutability and digest checks.  This adapter adds a fresh Domain Grant
        check before each protected byte operation; callers must create it for
        the concrete command that is reading or writing the artifact.
        """
        from runtime.data_policy import DomainBoundArtifactStore

        return DomainBoundArtifactStore(store, self, command)

    def bind_artifact_store_for_command(
        self, command: CommandEnvelope, store: Any,
    ) -> Any:
        return self.bind_artifact_store(command, store)

    def source_authorizer(self, command: CommandEnvelope):
        """Return a command-bound Source callback requiring ``source.read``."""
        from runtime.data_policy import source_authorizer

        return source_authorizer(self, command)

    def admit_source(self, service: Any, command: CommandEnvelope, request: Any) -> Any:
        """Admit a Source snapshot through the live Domain data-policy boundary."""
        from runtime.data_policy import artifact_authorizer

        return service.admit(
            request,
            self.source_authorizer(command),
            artifact_authorize=artifact_authorizer(self, command),
        )

    def readback_source(self, service: Any, command: CommandEnvelope, snapshot: Any) -> Any:
        """Read back Source/CAS bytes through the same authenticated Grant."""
        from runtime.data_policy import artifact_authorizer

        return service.readback(
            snapshot,
            self.source_authorizer(command),
            artifact_authorize=artifact_authorizer(self, command),
        )

    @property
    def enrollment(self):
        from runtime.enrollment import EnrollmentAuthority
        return EnrollmentAuthority(self)

    @property
    def receiver_transport(self):
        from runtime.receiver_domain import ReceiverTransportAuthority

        return ReceiverTransportAuthority(self)

    def register_authority_transport_key(self, command, request):
        return self.receiver_transport.register_authority_key(command, request)

    def register_receiver_connection(self, command, request):
        return self.receiver_transport.register_connection(command, request)

    def register_receiver_endpoint(self, command, request):
        return self.receiver_transport.register_endpoint(command, request)

    def enroll_node(self, command, request):
        return self.enrollment.enroll_node(command, request)

    def rotate_node(self, command, request):
        return self.enrollment.rotate_node(command, request)

    def revoke_node(self, command, request):
        return self.enrollment.revoke_node(command, request)

    def challenge_node(self, command, request):
        return self.enrollment.challenge_node(command, request)

    def register_runtime(self, command, request, proof=None):
        return self.enrollment.register_runtime(command, request, proof)


    @property
    def tenant_id(self) -> str:
        return self.context.tenant_id

    @property
    def authority_id(self) -> str:
        return self.context.authority_id

    def _connect(self, *, clock_probe: bool = False):
        if self._transaction_connection is not None:
            return nullcontext(self._transaction_connection)
        # Startup options avoid SET TIME ZONE opening an implicit transaction,
        # and preserve caller search_path, lock and statement timeout settings.
        options = psycopg.conninfo.conninfo_to_dict(self._dsn).get("options", "")
        options = (options + " -ctimezone=UTC").strip()
        if clock_probe:
            return psycopg.connect(
                self._dsn, options=options + " -cstatement_timeout=5000", connect_timeout=5,
            )
        return psycopg.connect(self._dsn, options=options)

    def canonical_now(self, cursor: psycopg.Cursor | None = None) -> datetime:
        """Read fresh authority time, including after transaction lock waits."""
        if cursor is None:
            with self._connect(clock_probe=True) as connection, connection.cursor() as clock_cursor:
                return self.canonical_now(clock_cursor)
        cursor.execute("SELECT clock_timestamp()")
        current = cursor.fetchone()[0]
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("database clock must return a timezone-aware instant")
        return current.astimezone(UTC)

    @contextmanager
    def transaction(self):
        """Compose Domain commands and their projections in one transaction.

        The borrowed authority is private to the caller. Nested Domain methods
        neither commit nor close the connection; the outer owner commits only
        after every command and projection has completed.
        """
        with self._connect() as connection, connection.transaction():
            authority = copy(self)
            authority._transaction_connection = connection
            yield authority, connection


    def initialize(self) -> None:
        from runtime.communication_storage import adopt_core

        with self._connect() as connection, connection.cursor() as cursor:
            adopt_core(connection)

            # Bootstrap only the explicit local profile. A caller-supplied context
            # is authentication input, never an authority-incarnation command.
            cursor.execute("LOCK TABLE authority_instances IN SHARE ROW EXCLUSIVE MODE")
            cursor.execute(
                "INSERT INTO authority_instances"
                "(authority_id,authority_incarnation,status) "
                "SELECT %s,%s,'active' "
                "WHERE NOT EXISTS (SELECT 1 FROM authority_instances)",
                self._authority_binding,
            )
            cursor.execute(
                "INSERT INTO scopes(scope_id,tenant_id,policy,status) "
                "VALUES ('local-scope',%s,'{}','active') "
                "ON CONFLICT DO NOTHING",
                (self.context.tenant_id,),
            )
            cursor.execute(
                "INSERT INTO agent_slots(agent_slot_id,tenant_id,scope_id,status) "
                "VALUES ('local-slot',%s,'local-scope','active') "
                "ON CONFLICT DO NOTHING",
                (self.context.tenant_id,),
            )

    def bootstrap_local_grant(
        self,
        permissions: tuple[str, ...] = (
            "profile.engineer", "message.send", "message.read", "runtime.invoke",
        ),
        *,
        preserve_existing: bool = False,
    ) -> None:
        if self.access_mode == "owner":
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,"
                    "scope_id,permissions,expires_at,identity_only) VALUES (%s,%s,%s,%s,%s,'local-scope','[]',NULL,TRUE) "
                    "ON CONFLICT(grant_ref) DO NOTHING", (self.context.grant_ref,self.context.tenant_id,
                    self.context.principal_ref,self.context.authority_id,self.context.authority_incarnation))
            return
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO grants("
                "grant_ref,tenant_id,principal_ref,authority_id,"
                "authority_incarnation,scope_id,permissions,expires_at,revoked_at) "
                "VALUES (%s,%s,%s,%s,%s,'local-scope',%s,"
                "now()+interval '365 days',NULL) "
                + ("ON CONFLICT (grant_ref) DO NOTHING" if preserve_existing else
                 "ON CONFLICT (grant_ref) DO UPDATE SET "
                 "tenant_id=EXCLUDED.tenant_id,"
                 "principal_ref=EXCLUDED.principal_ref,"
                 "authority_id=EXCLUDED.authority_id,"
                 "authority_incarnation=EXCLUDED.authority_incarnation,"
                 "scope_id=EXCLUDED.scope_id,"
                 "permissions=EXCLUDED.permissions,"
                 "expires_at=EXCLUDED.expires_at,"
                 "revoked_at=NULL"),
                (
                    self.context.grant_ref,
                    self.context.tenant_id,
                    self.context.principal_ref,
                    self.context.authority_id,
                    self.context.authority_incarnation,
                    json.dumps(permissions),
                ),
            )

    def _authorize(
        self,
        command: CommandEnvelope,
        cursor: psycopg.Cursor | None = None,
        permission: str = "message.read",
        scope_id: str | None = None,
        *,
        clock_skew_seconds: int = 0,
    ) -> None:
        if cursor is None:
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)

        if self.access_mode == "owner":
            self._authorize_owner(command, cursor, scope_id)
            return

        if type(clock_skew_seconds) is not int or not 0 <= clock_skew_seconds <= 30:
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)

        now = self.canonical_now(cursor)
        clock_skew = timedelta(seconds=clock_skew_seconds)
        current = self.context

        natural_message = command.command_type == "message.send" and command.payload.get("schema_version") in {"acs-message/1", "acs-notice/1"}
        if (
            command.issued_at.tzinfo is None
            or (command.deadline is None and not natural_message)
            or (command.deadline is not None and (command.deadline.tzinfo is None or command.deadline <= now))
            or command.issued_at > now + clock_skew
        ):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)

        if (
            command.tenant_id,
            command.authority_id,
            command.authority_incarnation,
            command.principal_ref,
            command.grant_ref,
        ) != (
            current.tenant_id,
            current.authority_id,
            current.authority_incarnation,
            current.principal_ref,
            current.grant_ref,
        ):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)

        self._lock_command_identity(cursor, command)
        self._authorize_delegation(cursor, command, permission)
        cursor.execute(
            "SELECT g.scope_id,g.permissions,g.expires_at "
            "FROM grants g "
            "JOIN authority_instances a "
            "ON a.authority_id=g.authority_id "
            "AND a.authority_incarnation=g.authority_incarnation "
            "JOIN scopes s ON s.scope_id=g.scope_id "
            "WHERE g.grant_ref=%s "
            "AND g.tenant_id=%s "
            "AND g.principal_ref=%s "
            "AND g.authority_id=%s "
            "AND g.authority_incarnation=%s "
            "AND a.status='active' "
            "AND (SELECT count(*) FROM authority_instances current_authority "
            "WHERE current_authority.authority_id=g.authority_id "
            "AND current_authority.status='active')=1 "
            "AND s.tenant_id=%s "
            "AND s.status='active' "
            "AND g.revoked_at IS NULL "
            "AND g.expires_at>clock_timestamp() FOR UPDATE",
            (
                current.grant_ref,
                current.tenant_id,
                current.principal_ref,
                current.authority_id,
                current.authority_incarnation,
                current.tenant_id,
            ),
        )
        row = cursor.fetchone()

        now = self.canonical_now(cursor)
        scope_allowed = row is not None and (scope_id is None or str(row[0]) == str(scope_id))
        if (not scope_allowed and row is not None and natural_message
                and permission in {"message.send", "message.read", "runtime.invoke"}):
            from runtime.communication_permissions import permits_project_message_scope
            scope_allowed = permits_project_message_scope(cursor,current,command,row[0],scope_id)
        if (
            row is None
            or (command.deadline is not None and command.deadline <= now)
            or command.issued_at > now + clock_skew
            or row[2] <= now
            or permission not in expanded_permissions(row[1])
            or not scope_allowed
        ):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)

    def _authorize_owner(self, command, cursor, scope_id):
        """Validate trusted service context and target; roles are collaboration metadata."""
        from runtime.errors import BusinessDeadlineExpired, IdentityRejected
        if command.deadline is not None and command.deadline <= self.canonical_now(cursor):
            raise BusinessDeadlineExpired(command.target_id)
        current = self.context
        expected = (current.tenant_id, current.authority_id, current.authority_incarnation,
                    current.principal_ref, current.grant_ref)
        actual = (command.tenant_id, command.authority_id, command.authority_incarnation,
                  command.principal_ref, command.grant_ref)
        if actual != expected:
            raise IdentityRejected(command.principal_ref, command.grant_ref, "identity_mismatch")
        cursor.execute(
            "SELECT 1 FROM authority_instances a WHERE a.authority_id=%s "
            "AND a.authority_incarnation=%s AND a.status='active' "
            "AND (SELECT count(*) FROM authority_instances x "
            "WHERE x.authority_id=a.authority_id AND x.status='active')=1",
            (current.authority_id, current.authority_incarnation),
        )
        if cursor.fetchone() is None:
            raise IdentityRejected(command.principal_ref, command.grant_ref, "service_identity_inactive")
        if scope_id is not None:
            cursor.execute("SELECT 1 FROM scopes WHERE tenant_id=%s AND scope_id=%s AND status='active'",
                           (current.tenant_id, scope_id))
            if cursor.fetchone() is None:
                raise IdentityRejected(command.principal_ref, command.grant_ref, "scope_unavailable")
        cursor.execute("SELECT grant_ref,revoked_at FROM grants WHERE tenant_id=%s AND grant_ref=ANY(%s)",
                       (current.tenant_id, list({self.owner_identity_ref, current.grant_ref})))
        identities = {reference: revoked for reference, revoked in cursor.fetchall()}
        if (set(identities) != {self.owner_identity_ref, current.grant_ref}
                or any(revoked is not None for revoked in identities.values())):
            raise IdentityRejected(command.principal_ref, command.grant_ref, "identity_revoked")
        self._lock_command_identity(cursor, command)

    def _authorize_delegation(self, cursor, command, permission):
        """Lock the finite Grant chain root-first and enforce current ancestry."""
        if self.access_mode == "owner":
            cursor.execute("SELECT revoked_at FROM grants WHERE tenant_id=%s AND grant_ref=%s AND principal_ref=%s",
                           (command.tenant_id, command.grant_ref, command.principal_ref))
            identity = cursor.fetchone()
            if identity is None or identity[0] is not None:
                raise AuthorizationDenied(command.principal_ref, command.grant_ref)
            return
        cursor.execute(
            "WITH RECURSIVE ancestry AS ("
            "SELECT %s::text AS ref,0 AS depth,ARRAY[%s::text] AS path,FALSE AS cycle "
            "UNION ALL SELECT d.parent_grant_ref,a.depth+1,a.path || d.parent_grant_ref,"
            "d.parent_grant_ref=ANY(a.path) FROM ancestry a JOIN grant_delegations d "
            "ON d.grant_ref=a.ref WHERE NOT a.cycle AND a.depth<9) "
            "SELECT a.ref,a.depth,a.cycle,g.tenant_id,g.permissions,g.expires_at,g.revoked_at,"
            "g.authority_id,g.authority_incarnation,s.status,s.policy,d.parent_policy_digest "
            "FROM ancestry a JOIN grants g ON g.grant_ref=a.ref JOIN scopes s ON s.scope_id=g.scope_id "
            "LEFT JOIN grant_delegations d ON d.grant_ref=a.ref "
            "ORDER BY a.depth DESC FOR UPDATE OF g,s",
            (command.grant_ref, command.grant_ref),
        )
        chain = cursor.fetchall()
        if not chain or chain[0][1] > 8 or any(row[2] for row in chain):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        now = self.canonical_now(cursor)
        parent = None
        for row in chain:
            if (row[3] != command.tenant_id or permission not in expanded_permissions(row[4])
                    or row[5] <= now or row[6] is not None or row[9] != "active"
                    or (row[7], row[8]) != (command.authority_id, command.authority_incarnation)):
                raise AuthorizationDenied(command.principal_ref, command.grant_ref)
            if parent is not None:
                policy_digest = hashlib.sha256(json.dumps(parent[10], sort_keys=True,
                    separators=(",", ":")).encode()).hexdigest()
                if (row[11] != policy_digest or not set(row[4] or ()) <= expanded_permissions(parent[4])
                        or row[5] > parent[5]):
                    raise AuthorizationDenied(command.principal_ref, command.grant_ref)
            parent = row

    @staticmethod
    def _hash(command: CommandEnvelope, extra: Mapping[str, object]) -> str:
        return command.canonical_hash(extra)

    def _dedup(
        self,
        cursor: psycopg.Cursor,
        command: CommandEnvelope,
        result: CommandResult,
        extra: Mapping[str, object],
    ) -> tuple[CommandResult | None, str]:
        digest = self._hash(command, extra)
        self._lock_command_identity(cursor, command)
        cursor.execute(
            "SELECT idempotency_key,command_id,payload_hash,hash_version,"
            "canonical_hash,migration_state,replay_policy,result_json,legacy_record "
            "FROM command_dedup WHERE tenant_id=%s AND ("
            "idempotency_key=%s OR command_id=%s OR legacy_command_id=%s "
            "OR legacy_record ->> 'command_id'=%s "
            "OR legacy_record -> 'result_json' ->> 'command_id'=%s) "
            "ORDER BY idempotency_key FOR UPDATE",
            (command.tenant_id, command.idempotency_key, command.command_id,
             command.command_id, command.command_id, command.command_id),
        )
        rows = cursor.fetchall()
        if rows:
            # Matching one key does not erase another row's historical claim.
            if len(rows) != 1:
                raise IdempotencyConflict(command.idempotency_key)
            row = rows[0]
            if row[0] != command.idempotency_key or row[5] == "quarantined" or row[6] == "quarantine":
                raise IdempotencyConflict(command.idempotency_key)
            if row[5] == "current":
                if (row[1] != command.command_id or row[3] != "v2"
                        or row[6] != "replay_safe" or row[4] != digest or row[2] != digest):
                    raise IdempotencyConflict(command.idempotency_key)
            else:
                if row[5] not in ("legacy", "migrated") or row[6] != "verify_legacy_hash":
                    raise IdempotencyConflict(command.idempotency_key)
                original = row[8] if isinstance(row[8], Mapping) else {
                    "tenant_id": command.tenant_id, "idempotency_key": row[0],
                    "command_id": row[1], "payload_hash": row[2],
                    "hash_version": row[3], "result_json": row[7],
                }
                # The historical event is trusted database provenance; no field
                # in the retry body supplies or repairs the historical principal.
                cursor.execute(
                    "SELECT DISTINCT initiated_by FROM domain_events "
                    "WHERE tenant_id=%s AND command_id=%s AND work_item_id=%s "
                    "AND lineage_mode='external_command'",
                    (command.tenant_id, command.command_id, command.target_id),
                )
                principals = cursor.fetchall()
                if len(principals) > 1:
                    raise IdempotencyConflict(command.idempotency_key)
                record = LegacyCommandRecord(
                    tenant_id=original.get("tenant_id"),
                    idempotency_key=original.get("idempotency_key"),
                    command_id=original.get("command_id"),
                    payload_hash=original.get("payload_hash"),
                    result_json=original.get("result_json"),
                    hash_version=original.get("hash_version"),
                    principal_ref=principals[0][0] if principals else None,
                )
                decision = classify_replay(record, command, extra=extra)
                if decision.action != "replay":
                    raise IdempotencyConflict(command.idempotency_key)
            try:
                replay = CommandResult.model_validate(row[7])
            except (TypeError, ValueError):
                raise IdempotencyConflict(command.idempotency_key) from None
            if replay.command_id != command.command_id or replay.target_id != command.target_id:
                raise IdempotencyConflict(command.idempotency_key)
            return replay.model_copy(update={"duplicate": True}), digest

        if command.hash_version != "v2":
            raise IdempotencyConflict(command.idempotency_key)
        cursor.execute(
            "INSERT INTO command_dedup("
            "tenant_id,idempotency_key,command_id,payload_hash,hash_version,"
            "canonical_hash,migration_state,replay_policy,result_json) "
            "VALUES (%s,%s,%s,%s,'v2',%s,'current','replay_safe',%s)",
            (command.tenant_id, command.idempotency_key, command.command_id,
             digest, digest, result.model_dump_json()),
        )
        return None, digest


    @staticmethod
    def _operation(
        cursor: psycopg.Cursor,
        command: CommandEnvelope,
        operation_id: str,
    ) -> None:
        cursor.execute(
            "INSERT INTO operations("
            "operation_id,tenant_id,command_id,provider,provider_workflow_id,status) "
            "VALUES (%s,%s,%s,'temporal',%s,'committed')",
            (
                operation_id,
                command.tenant_id,
                command.command_id,
                f"acs-p1/{command.command_id}",
            ),
        )

    @staticmethod
    def _outbox(
        cursor: psycopg.Cursor,
        command: CommandEnvelope,
        operation_id: str,
        topic: str,
        payload: Mapping[str, str],
    ) -> None:
        cursor.execute(
            "INSERT INTO outbox(tenant_id,message_id,operation_id,topic,payload) "
            "VALUES (%s,%s,%s,%s,%s)",
            (
                command.tenant_id,
                f"msg-{command.command_id}",
                operation_id,
                topic,
                json.dumps(dict(payload)),
            ),
        )

    @staticmethod
    def _lock_command_identity(cursor: psycopg.Cursor, command: CommandEnvelope) -> None:
        # Distinct namespaces and JSON tuples avoid delimiter ambiguity. Sorting
        # the actual signed lock IDs also makes hash collisions deadlock-safe.
        identities = (
            ("acs-p1-command-id", command.tenant_id, command.command_id),
            ("acs-p1-idempotency-key", command.tenant_id, command.idempotency_key),
        )
        lock_ids = sorted({
            int.from_bytes(
                hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).digest()[:8],
                "big", signed=True,
            )
            for identity in identities
        })
        for lock_id in lock_ids:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (lock_id,))
