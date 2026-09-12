"""Isolated formal candidate for delayed response and Human Bridge recovery.

The Node half is executable with SQLite. The PostgreSQL authority requires a
trusted integration hook to supply current authorization snapshots; it is not
wired into the formal Runtime or public Surfaces in this candidate.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from runtime.recovery_models import (
    BoundaryRejected,
    DispatchIdentity,
    HumanBridgeCoordinator,
    ManualPacket,
    NativeResponseObservation,
    NormalReceipt,
    RecoveryPath,
    StateConflict,
    _aware,
    _digest,
    _text,
    canonical_digest,
    response_receipt_id,
)


@dataclass(frozen=True)
class ProjectionDisposition:
    projection_id: str
    canonical_digest: str
    disposition: str


class NodeResponseOutbox:
    """Node-owned durable observation and retry state; never Domain authority."""

    SCHEMA_VERSION = "acs-node-response-outbox/1"
    _SCHEMA = (
        "CREATE TABLE IF NOT EXISTS response_outbox_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)",
        """CREATE TABLE IF NOT EXISTS native_response_observations(
            projection_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,receipt_id TEXT NOT NULL,
            invocation_id TEXT NOT NULL,native_response_ref TEXT NOT NULL,
            canonical_digest TEXT NOT NULL,payload_json TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('pending','applied','fenced_late')),
            observed_at TEXT NOT NULL,updated_at TEXT NOT NULL,
            UNIQUE(tenant_id,receipt_id),UNIQUE(tenant_id,invocation_id))""",
        """CREATE TABLE IF NOT EXISTS native_response_projection_outbox(
            projection_id TEXT PRIMARY KEY REFERENCES native_response_observations(projection_id),
            attempts INTEGER NOT NULL DEFAULT 0,last_error TEXT,next_attempt_at TEXT NOT NULL,
            created_at TEXT NOT NULL)""",
    )

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as connection:
            for statement in self._SCHEMA:
                connection.execute(statement)
            row = connection.execute(
                "SELECT value FROM response_outbox_meta WHERE key='schema_version'"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO response_outbox_meta(key,value) VALUES ('schema_version',?)",
                    (self.SCHEMA_VERSION,),
                )
            elif row[0] != self.SCHEMA_VERSION:
                raise RuntimeError("unsupported Node response Outbox schema")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def _transaction(self):
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    @staticmethod
    def _payload(observation: NativeResponseObservation) -> tuple[str, str]:
        payload = observation.canonical()
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return encoded, canonical_digest(payload)

    def record(self, observation: NativeResponseObservation) -> bool:
        encoded, digest = self._payload(observation)
        identity = observation.identity
        if observation.receipt_id != response_receipt_id(
            identity, observation.projection_id
        ):
            raise BoundaryRejected("Node response receipt identity is not canonical")
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT projection_id,canonical_digest FROM native_response_observations "
                "WHERE projection_id=? OR (tenant_id=? AND receipt_id=?) OR "
                "(tenant_id=? AND invocation_id=?)",
                (observation.projection_id, identity.tenant_id, observation.receipt_id,
                 identity.tenant_id, identity.invocation_id),
            ).fetchall()
            if rows:
                if len(rows) != 1 or rows[0]["projection_id"] != observation.projection_id:
                    raise StateConflict("Node response identity already belongs to another projection")
                if rows[0]["canonical_digest"] != digest:
                    raise StateConflict("Node projection identity changed")
                return False
            now = datetime.now(UTC).isoformat()
            connection.execute(
                "INSERT INTO native_response_observations("
                "projection_id,tenant_id,receipt_id,invocation_id,native_response_ref,"
                "canonical_digest,payload_json,state,observed_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,'pending',?,?)",
                (observation.projection_id, identity.tenant_id, observation.receipt_id,
                 identity.invocation_id, observation.native_response_ref, digest, encoded,
                 observation.observed_at.astimezone(UTC).isoformat(), now),
            )
            connection.execute(
                "INSERT INTO native_response_projection_outbox("
                "projection_id,next_attempt_at,created_at) VALUES (?,?,?)",
                (observation.projection_id, now, now),
            )
            return True

    def pending(self, *, limit: int = 32) -> tuple[NativeResponseObservation, ...]:
        if not 1 <= limit <= 128:
            raise ValueError("pending limit outside bound")
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT o.payload_json FROM native_response_projection_outbox x "
                "JOIN native_response_observations o USING(projection_id) "
                "WHERE x.next_attempt_at<=? ORDER BY x.created_at,x.projection_id LIMIT ?",
                (datetime.now(UTC).isoformat(), limit),
            ).fetchall()
        values = []
        for row in rows:
            payload = json.loads(row[0])
            payload["identity"] = DispatchIdentity(**payload["identity"])
            payload["observed_at"] = datetime.fromisoformat(payload["observed_at"])
            values.append(NativeResponseObservation(**payload))
        return tuple(values)

    def by_invocation(self, identity: DispatchIdentity) -> NativeResponseObservation | None:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM native_response_observations "
                "WHERE tenant_id=? AND invocation_id=?",
                (identity.tenant_id, identity.invocation_id),
            ).fetchall()
        if len(rows) > 1:
            raise StateConflict("multiple terminal observations for one invocation")
        if not rows:
            return None
        payload = json.loads(rows[0][0])
        payload["identity"] = DispatchIdentity(**payload["identity"])
        payload["observed_at"] = datetime.fromisoformat(payload["observed_at"])
        observation = NativeResponseObservation(**payload)
        if observation.identity != identity:
            raise StateConflict("cached terminal belongs to a different DispatchIdentity")
        return observation

    def mark(self, disposition: ProjectionDisposition) -> None:
        if disposition.disposition not in {"applied", "fenced_late"}:
            raise ValueError("invalid Domain projection disposition")
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT canonical_digest,state FROM native_response_observations WHERE projection_id=?",
                (disposition.projection_id,),
            ).fetchone()
            if row is None or row["canonical_digest"] != disposition.canonical_digest:
                raise StateConflict("Domain disposition does not match Node observation")
            if row["state"] not in {"pending", disposition.disposition}:
                raise StateConflict("Domain disposition changed")
            connection.execute(
                "UPDATE native_response_observations SET state=?,updated_at=? WHERE projection_id=?",
                (disposition.disposition, datetime.now(UTC).isoformat(),
                 disposition.projection_id),
            )
            connection.execute(
                "DELETE FROM native_response_projection_outbox WHERE projection_id=?",
                (disposition.projection_id,),
            )

    def fail(self, projection_id: str, error_code: str) -> None:
        if not error_code or len(error_code) > 256:
            raise ValueError("bounded error code required")
        with self._transaction() as connection:
            changed = connection.execute(
                "UPDATE native_response_projection_outbox SET attempts=attempts+1,last_error=?,"
                "next_attempt_at=? WHERE projection_id=?",
                (error_code, datetime.now(UTC).isoformat(), projection_id),
            ).rowcount
            if changed != 1:
                raise StateConflict("unknown pending projection")

    def recover(self) -> tuple[dict[str, Any], ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT o.projection_id,o.canonical_digest,x.attempts,x.last_error "
                "FROM native_response_projection_outbox x "
                "JOIN native_response_observations o USING(projection_id) "
                "ORDER BY x.created_at,x.projection_id"
            ).fetchall()
        return tuple(dict(row) for row in rows)


@dataclass(frozen=True)
class InvocationCollectionIdentity:
    dispatch: DispatchIdentity
    command_id: str
    binding_id: str
    binding_items: tuple[tuple[str, str | int], ...]
    driver_kind: str
    native_session_ref: str
    native_turn_ref: str
    native_thread_ref: str | None = None

    def __post_init__(self) -> None:
        for name in ("command_id", "binding_id", "driver_kind", "native_session_ref",
                     "native_turn_ref"):
            _text(getattr(self, name), name)
        if self.driver_kind not in {"codex", "opencode"}:
            raise BoundaryRejected("unsupported collector driver kind")
        if self.driver_kind == "codex" and self.native_thread_ref is None:
            raise BoundaryRejected("Codex collector requires thread identity")
        if self.native_thread_ref is not None:
            _text(self.native_thread_ref, "native_thread_ref")
        if (not self.binding_items or len(self.binding_items) > 32
                or len({key for key, _ in self.binding_items}) != len(self.binding_items)):
            raise BoundaryRejected("binding fields outside bound")
        required_binding = {
            "node_id", "node_boot_id", "runtime_id", "attempt_id", "agent_slot_id", "revision",
        }
        if {key for key, _ in self.binding_items} != required_binding:
            raise BoundaryRejected("collector requires the complete Driver binding")
        for key, value in self.binding_items:
            _text(key, "binding_key", maximum=128)
            if isinstance(value, str):
                _text(value, "binding_value")
            elif type(value) is not int or value < 0:
                raise BoundaryRejected("binding value outside bound")
        canonical_digest(self.canonical_binding())
        binding = self.canonical_binding()
        if (binding["node_id"] != self.dispatch.node_id
                or binding["node_boot_id"] != self.dispatch.boot_incarnation
                or binding["attempt_id"] != self.dispatch.attempt_id):
            raise BoundaryRejected("Driver binding differs from dispatch identity")
        if binding["revision"] != self.dispatch.binding_revision:
            raise BoundaryRejected("Driver binding revision differs from dispatch revision")

    def canonical_binding(self) -> dict[str, str | int]:
        return dict(self.binding_items)


class DriverCollectorAdapter:
    """Calls only Driver.collect_result and commits the exact terminal observation."""

    def __init__(
        self,
        driver: Any,
        outbox: NodeResponseOutbox,
        response_store: Callable[[dict[str, Any]], tuple[str, str]],
    ) -> None:
        if not callable(getattr(driver, "collect_result", None)):
            raise TypeError("Driver must expose collect_result")
        if not callable(response_store):
            raise TypeError("response artifact store callback is required")
        self.driver, self.outbox, self.response_store = driver, outbox, response_store

    def collect(
        self, operation: Any, invocation_operation_id: str,
        collection: InvocationCollectionIdentity,
    ) -> NativeResponseObservation:
        identity = collection.dispatch
        if invocation_operation_id != identity.operation_id:
            raise BoundaryRejected("collector invocation operation changed")
        cached = self.outbox.by_invocation(identity)
        if cached is not None:
            return cached
        result = self.driver.collect_result(operation, invocation_operation_id)
        if not isinstance(result, dict) or result.get("receipt_layer") != "response_received":
            raise BoundaryRejected("Driver has no exact terminal response")
        expected_common = {
            "operation_id": identity.operation_id,
            "command_id": collection.command_id,
            "message_id": identity.message_id,
            "invocation_id": identity.invocation_id,
            "attempt_id": identity.attempt_id,
            "dispatch_id": identity.dispatch_id,
            "binding_id": collection.binding_id,
            "binding": collection.canonical_binding(),
        }
        if any(result.get(name) != expected for name, expected in expected_common.items()):
            raise BoundaryRejected("Driver terminal response lineage changed")
        if collection.driver_kind == "codex":
            native_matches = (
                result.get("session_id") == collection.native_session_ref
                and result.get("thread_id") == collection.native_thread_ref
                and result.get("turn_id") == collection.native_turn_ref
            )
        else:
            native_matches = (
                result.get("native_session_id") == collection.native_session_ref
                and result.get("native_message_id") == collection.native_turn_ref
            )
        if not native_matches:
            raise BoundaryRejected("Driver terminal native turn or session changed")
        outcome = result.get("native_terminal_outcome", result.get("native_status"))
        if outcome not in {"completed", "failed", "interrupted"}:
            raise BoundaryRejected("Driver terminal outcome is unsupported")
        native_identity = {
            key: result.get(key) for key in (
                "turn_id", "native_message_id", "native_assistant_ids", "assistant_messages",
            ) if result.get(key) is not None
        }
        if not native_identity:
            raise BoundaryRejected("Driver terminal response lacks native identity")
        observed_at = result.get("native_terminal_observed_at")
        if not isinstance(observed_at, str):
            raise BoundaryRejected("Driver terminal timestamp is missing")
        try:
            terminal_observed_at = datetime.fromisoformat(observed_at)
        except ValueError as error:
            raise BoundaryRejected("Driver terminal timestamp is malformed") from error
        _aware(terminal_observed_at, "native_terminal_observed_at")
        normalized = {key: value for key, value in result.items() if key != "observed_at"}
        evidence_digest = canonical_digest(normalized)
        response_artifact_ref, response_digest = self.response_store(normalized)
        native_response_ref = "native-response:" + canonical_digest(native_identity)
        stable = {"tenant_id": identity.tenant_id, "invocation_id": identity.invocation_id,
                  "native_response_ref": native_response_ref}
        projection_id = "projection:" + canonical_digest(stable)
        observation = NativeResponseObservation(
            projection_id=projection_id,
            receipt_id=response_receipt_id(identity, projection_id),
            identity=identity,
            native_response_ref=native_response_ref,
            native_outcome=outcome,
            response_artifact_ref=response_artifact_ref,
            response_digest=response_digest,
            evidence_digest=evidence_digest,
            observed_at=terminal_observed_at,
        )
        self.outbox.record(observation)
        return observation


@dataclass(frozen=True)
class AuthoritySnapshot:
    committed_identity: DispatchIdentity
    producer_authenticated: bool
    current_authority_valid: bool
    task_valid: bool
    current_attempt_id: str
    current_accepted_revision: int
    current_accepted_state_digest: str
    deadline: datetime
    principal_ref: str
    grant_ref: str
    policy_version: str

    def __post_init__(self) -> None:
        _aware(self.deadline, "authority_deadline")
        for name in ("current_attempt_id", "principal_ref", "grant_ref", "policy_version"):
            _text(getattr(self, name), name)
        if self.current_accepted_revision < 0:
            raise BoundaryRejected("current accepted revision outside bound")
        _digest(self.current_accepted_state_digest, "current_accepted_state_digest")


class PostgresDelayedResponseAuthority:
    """Transactional Domain projection candidate behind a trusted snapshot hook."""

    def __init__(self, dsn: str, snapshot: Callable[[Any, NativeResponseObservation], AuthoritySnapshot]) -> None:
        self.dsn, self.snapshot = dsn, snapshot

    def project(self, observation: NativeResponseObservation) -> ProjectionDisposition:
        import psycopg

        payload = observation.canonical()
        digest = canonical_digest(payload)
        identity = observation.identity
        if observation.receipt_id != response_receipt_id(
            identity, observation.projection_id
        ):
            raise BoundaryRejected("response receipt identity is not canonical")
        with psycopg.connect(self.dsn) as connection, connection.cursor() as cursor:
            authority = self.snapshot(cursor, observation)
            if not authority.producer_authenticated:
                raise BoundaryRejected("native observation producer not authenticated")
            if authority.committed_identity != identity:
                raise BoundaryRejected("committed dispatch identity changed")
            cursor.execute(
                "SELECT operation_id,deadline,accepted_state_digest FROM delivery_messages "
                "WHERE tenant_id=%s AND message_id=%s FOR UPDATE",
                (identity.tenant_id, identity.message_id),
            )
            message = cursor.fetchone()
            if (message is None or message[0] != identity.operation_id
                    or message[2] != identity.accepted_state_digest):
                raise BoundaryRejected("committed delivery message identity changed")
            cursor.execute(
                "SELECT operation_id,dispatch_id,runtime_dispatched_receipt_id "
                "FROM delivery_attempts WHERE tenant_id=%s "
                "AND message_id=%s AND attempt_id=%s FOR UPDATE",
                (identity.tenant_id, identity.message_id, identity.attempt_id),
            )
            attempt = cursor.fetchone()
            if (attempt is None or attempt[:2] != (identity.operation_id, identity.dispatch_id)
                    or attempt[2] is None):
                raise BoundaryRejected("committed delivery attempt identity changed")
            cursor.execute(
                "SELECT attempt_id,dispatch_id FROM delivery_receipts WHERE tenant_id=%s "
                "AND message_id=%s AND receipt_id=%s AND layer='runtime_dispatched' FOR UPDATE",
                (identity.tenant_id, identity.message_id, attempt[2]),
            )
            if cursor.fetchone() != (identity.attempt_id, identity.dispatch_id):
                raise BoundaryRejected("runtime dispatch receipt is not committed")
            cursor.execute(
                "SELECT canonical_digest,disposition FROM native_response_observations "
                "WHERE tenant_id=%s AND projection_id=%s FOR UPDATE",
                (identity.tenant_id, observation.projection_id),
            )
            prior = cursor.fetchone()
            if prior is not None:
                if prior[0] != digest:
                    raise StateConflict("projection identity conflict")
                return ProjectionDisposition(observation.projection_id, digest, prior[1])
            cursor.execute(
                "SELECT projection_id FROM native_response_observations WHERE tenant_id=%s "
                "AND (receipt_id=%s OR invocation_id=%s) FOR UPDATE",
                (identity.tenant_id, observation.receipt_id, identity.invocation_id),
            )
            if cursor.fetchone() is not None:
                raise StateConflict("receipt or native response identity conflict")
            cursor.execute(
                "SELECT receipt_id,evidence_json,attempt_id,dispatch_id FROM delivery_receipts "
                "WHERE tenant_id=%s AND message_id=%s AND layer='response_received' FOR UPDATE",
                (identity.tenant_id, identity.message_id),
            )
            existing = cursor.fetchone()
            receipt_evidence = {
                "projection_id": observation.projection_id,
                "invocation_id": identity.invocation_id,
                "native_response_ref": observation.native_response_ref,
                "native_outcome": observation.native_outcome,
                "response_artifact_ref": observation.response_artifact_ref,
                "response_digest": observation.response_digest,
                "evidence_digest": observation.evidence_digest,
            }
            # The trusted callback and database clock are reread only after the
            # message/attempt/receipt rows are locked, immediately before write.
            authority = self.snapshot(cursor, observation)
            if not authority.producer_authenticated or authority.committed_identity != identity:
                raise BoundaryRejected("final native observation authority changed")
            cursor.execute("SELECT clock_timestamp()")
            database_now = cursor.fetchone()[0]
            current = (
                authority.current_authority_valid and authority.task_valid
                and database_now < min(authority.deadline, message[1])
                and authority.current_attempt_id == identity.attempt_id
                and authority.current_accepted_revision == identity.accepted_revision
                and authority.current_accepted_state_digest == identity.accepted_state_digest
            )
            disposition = "applied" if current else "fenced_late"
            if disposition == "applied":
                expected = (observation.receipt_id, receipt_evidence,
                            identity.attempt_id, identity.dispatch_id)
                if existing not in (None, expected):
                    raise StateConflict("response receipt conflict")
            cursor.execute(
                "INSERT INTO native_response_observations("
                "tenant_id,projection_id,receipt_id,message_id,operation_id,invocation_id,"
                "attempt_id,dispatch_id,endpoint_id,binding_revision,machine_id,node_id,"
                "boot_incarnation,accepted_revision,accepted_state_digest,native_response_ref,"
                "native_outcome,response_artifact_ref,response_digest,evidence_digest,observed_at,"
                "canonical_digest,disposition) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (identity.tenant_id, observation.projection_id, observation.receipt_id,
                 identity.message_id, identity.operation_id, identity.invocation_id,
                 identity.attempt_id, identity.dispatch_id, identity.endpoint_id,
                 identity.binding_revision, identity.machine_id, identity.node_id,
                 identity.boot_incarnation, identity.accepted_revision,
                 identity.accepted_state_digest, observation.native_response_ref,
                 observation.native_outcome, observation.response_artifact_ref,
                 observation.response_digest, observation.evidence_digest,
                 observation.observed_at, digest, disposition),
            )
            if disposition == "applied" and existing is None:
                cursor.execute(
                    "INSERT INTO delivery_receipts("
                    "tenant_id,message_id,receipt_id,layer,evidence_json,attempt_id,dispatch_id) "
                    "VALUES (%s,%s,%s,'response_received',%s,%s,%s)",
                    (identity.tenant_id, identity.message_id, observation.receipt_id,
                     json.dumps(receipt_evidence), identity.attempt_id, identity.dispatch_id),
                )
                cursor.execute(
                    "UPDATE delivery_messages SET receipt_high_water='response_received' "
                    "WHERE tenant_id=%s AND message_id=%s",
                    (identity.tenant_id, identity.message_id),
                )
            cursor.execute(
                "INSERT INTO recovery_audit_events("
                "tenant_id,projection_id,event_type,command_id,principal_ref,grant_ref,"
                "policy_version,evidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (identity.tenant_id, observation.projection_id,
                 "native_response_" + disposition, identity.operation_id,
                authority.principal_ref, authority.grant_ref, authority.policy_version,
                 json.dumps({"canonical_digest": digest,
                             "native_response_ref": observation.native_response_ref,
                             "response_artifact_ref": observation.response_artifact_ref,
                             "response_digest": observation.response_digest,
                             "evidence_digest": observation.evidence_digest})),
            )
        return ProjectionDisposition(observation.projection_id, digest, disposition)


@dataclass(frozen=True)
class IncidentOpenCommand:
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
    eligible_path_ids: tuple[str, ...]
    paths: tuple[RecoveryPath, ...]
    command_id: str

    def __post_init__(self) -> None:
        for name in ("incident_id", "tenant_id", "message_id", "operation_id",
                     "source_scope_id", "target_scope_id", "command_id"):
            _text(getattr(self, name), name)
        if self.generation < 1 or self.accepted_revision < 0:
            raise BoundaryRejected("incident command revision outside bound")
        _digest(self.accepted_state_digest, "accepted_state_digest")
        _aware(self.expires_at, "incident_expires_at")
        canonical_digest(self.canonical())

    def canonical(self) -> dict:
        value = asdict(self)
        value["expires_at"] = self.expires_at.astimezone(UTC).isoformat()
        return value


@dataclass(frozen=True)
class BridgeAuthoritySnapshot:
    authenticated: bool
    current_authority_valid: bool
    task_valid: bool
    send_authorized: bool
    current_accepted_revision: int
    current_accepted_state_digest: str
    deadline: datetime
    principal_ref: str
    grant_ref: str
    policy_version: str

    def __post_init__(self) -> None:
        _aware(self.deadline, "bridge_authority_deadline")
        for name in ("principal_ref", "grant_ref", "policy_version"):
            _text(getattr(self, name), name)
        _digest(self.current_accepted_state_digest, "current_accepted_state_digest")
        if self.current_accepted_revision < 0:
            raise BoundaryRejected("current accepted revision outside bound")


class PostgresHumanBridgeAuthority:
    """PostgreSQL incident authority; provider delivery stays in the formal Outbox."""

    def __init__(
        self,
        dsn: str,
        snapshot: Callable[[Any, str, str], BridgeAuthoritySnapshot],
    ) -> None:
        self.dsn, self.snapshot = dsn, snapshot

    @staticmethod
    def _audit(cursor, *, tenant_id: str, incident_id: str, event_type: str,
               command_id: str, authority: BridgeAuthoritySnapshot, evidence: dict) -> None:
        cursor.execute(
            "INSERT INTO recovery_audit_events("
            "tenant_id,incident_id,event_type,command_id,principal_ref,grant_ref,"
            "policy_version,evidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (tenant_id, incident_id, event_type, command_id, authority.principal_ref,
             authority.grant_ref, authority.policy_version, json.dumps(evidence)),
        )

    def open_incident(self, command: IncidentOpenCommand) -> str:
        import psycopg

        digest = canonical_digest(command.canonical())
        with psycopg.connect(self.dsn) as connection, connection.cursor() as cursor:
            authority = self.snapshot(cursor, "incident.open", command.incident_id)
            # Reuse the executable validator before any database mutation.
            HumanBridgeCoordinator().open_incident(
                incident_id=command.incident_id, generation=command.generation,
                tenant_id=command.tenant_id, message_id=command.message_id,
                operation_id=command.operation_id, source_scope_id=command.source_scope_id,
                target_scope_id=command.target_scope_id,
                accepted_revision=command.accepted_revision,
                accepted_state_digest=command.accepted_state_digest,
                expires_at=command.expires_at,
                eligible_path_ids=command.eligible_path_ids, paths=command.paths,
                now=datetime.now(UTC), task_valid=authority.task_valid,
                current_authority_valid=(authority.authenticated
                                         and authority.current_authority_valid),
            )
            if (authority.current_accepted_revision != command.accepted_revision
                    or authority.current_accepted_state_digest
                    != command.accepted_state_digest):
                raise BoundaryRejected("incident accepted state changed")
            cursor.execute(
                "SELECT canonical_digest FROM recovery_incidents WHERE tenant_id=%s "
                "AND incident_id=%s FOR UPDATE",
                (command.tenant_id, command.incident_id),
            )
            prior = cursor.fetchone()
            if prior is not None:
                if prior[0] != digest:
                    raise StateConflict("incident identity conflict")
                return "open"
            cursor.execute(
                "INSERT INTO recovery_incidents("
                "tenant_id,incident_id,generation,message_id,operation_id,source_scope_id,"
                "target_scope_id,accepted_revision,accepted_state_digest,expires_at,state,"
                "canonical_digest) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'open',%s)",
                (command.tenant_id, command.incident_id, command.generation,
                 command.message_id, command.operation_id, command.source_scope_id,
                 command.target_scope_id, command.accepted_revision,
                 command.accepted_state_digest, command.expires_at, digest),
            )
            for path in command.paths:
                path_digest = canonical_digest(asdict(path))
                cursor.execute(
                    "INSERT INTO recovery_path_attempts("
                    "tenant_id,incident_id,path_id,status,attempt_refs,evidence_refs,"
                    "canonical_digest) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (command.tenant_id, command.incident_id, path.path_id, path.status,
                     json.dumps(path.attempt_refs), json.dumps(path.evidence_refs), path_digest),
                )
            self._audit(
                cursor, tenant_id=command.tenant_id, incident_id=command.incident_id,
                event_type="incident_opened", command_id=command.command_id,
                authority=authority,
                evidence={"canonical_digest": digest,
                          "path_ids": list(command.eligible_path_ids)},
            )
        return "open"

    def request_human(self, *, tenant_id: str, incident_id: str, request_id: str,
                      command_id: str) -> str:
        import psycopg

        for name, value in (("tenant_id", tenant_id), ("incident_id", incident_id),
                            ("request_id", request_id), ("command_id", command_id)):
            _text(value, name)
        request = {"tenant_id": tenant_id, "incident_id": incident_id,
                   "request_id": request_id, "command_id": command_id}
        digest = canonical_digest(request)
        with psycopg.connect(self.dsn) as connection, connection.cursor() as cursor:
            authority = self.snapshot(cursor, "human.request", incident_id)
            if not authority.authenticated:
                raise BoundaryRejected("human request is not authorized")
            cursor.execute(
                "SELECT generation,message_id,operation_id,expires_at,state,accepted_revision,"
                "accepted_state_digest FROM recovery_incidents "
                "WHERE tenant_id=%s AND incident_id=%s FOR UPDATE",
                (tenant_id, incident_id),
            )
            incident = cursor.fetchone()
            if incident is None:
                raise BoundaryRejected("incident is not open")
            authority = self.snapshot(cursor, "human.request.final", incident_id)
            cursor.execute("SELECT clock_timestamp()")
            current_time = cursor.fetchone()[0]
            if not (authority.authenticated and authority.current_authority_valid
                    and authority.task_valid and authority.send_authorized
                    and authority.current_accepted_revision == incident[5]
                    and authority.current_accepted_state_digest == incident[6]
                    and current_time < min(incident[3], authority.deadline)):
                raise BoundaryRejected("human request final authority changed")
            cursor.execute(
                "SELECT canonical_digest FROM human_bridge_requests WHERE tenant_id=%s "
                "AND request_id=%s FOR UPDATE",
                (tenant_id, request_id),
            )
            prior = cursor.fetchone()
            if prior is not None:
                if prior[0] != digest:
                    raise StateConflict("human request identity conflict")
                return "human_requested"
            if incident[4] != "open":
                raise BoundaryRejected("incident is not open")
            cursor.execute(
                "INSERT INTO human_bridge_requests("
                "tenant_id,request_id,incident_id,generation,canonical_digest,outbox_message_id) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (tenant_id, request_id, incident_id, incident[0], digest, request_id),
            )
            cursor.execute(
                "INSERT INTO outbox(tenant_id,message_id,operation_id,topic,payload) "
                "VALUES (%s,%s,%s,'human_bridge.request',%s)",
                (tenant_id, request_id, incident[2], json.dumps({
                    "incident_id": incident_id, "generation": incident[0],
                    "logical_message_id": incident[1], "request_digest": digest,
                })),
            )
            cursor.execute(
                "UPDATE recovery_incidents SET state='human_requested',updated_at=clock_timestamp() "
                "WHERE tenant_id=%s AND incident_id=%s",
                (tenant_id, incident_id),
            )
            self._audit(
                cursor, tenant_id=tenant_id, incident_id=incident_id,
                event_type="human_request_outbox_committed", command_id=command_id,
                authority=authority, evidence={"request_id": request_id,
                                               "canonical_digest": digest},
            )
        return "human_requested"

    def reprobe(self, *, tenant_id: str, incident_id: str, reprobe_id: str,
                observation_ref: str, succeeded: bool, command_id: str) -> str:
        import psycopg

        for name, value in (("tenant_id", tenant_id), ("incident_id", incident_id),
                            ("reprobe_id", reprobe_id),
                            ("observation_ref", observation_ref),
                            ("command_id", command_id)):
            _text(value, name)
        if not isinstance(succeeded, bool):
            raise BoundaryRejected("reprobe outcome must be boolean")
        body = {"tenant_id": tenant_id, "incident_id": incident_id,
                "reprobe_id": reprobe_id, "observation_ref": observation_ref,
                "succeeded": succeeded, "command_id": command_id}
        digest = canonical_digest(body)
        with psycopg.connect(self.dsn) as connection, connection.cursor() as cursor:
            authority = self.snapshot(cursor, "automatic.reprobe", incident_id)
            if not authority.authenticated:
                raise BoundaryRejected("reprobe producer not authenticated")
            cursor.execute(
                "SELECT state,accepted_revision,accepted_state_digest,expires_at "
                "FROM recovery_incidents WHERE tenant_id=%s AND incident_id=%s "
                "FOR UPDATE", (tenant_id, incident_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise BoundaryRejected("incident not found")
            authority = self.snapshot(cursor, "automatic.reprobe.final", incident_id)
            cursor.execute("SELECT clock_timestamp()")
            current_time = cursor.fetchone()[0]
            current = (
                authority.authenticated and authority.current_authority_valid
                and authority.task_valid and authority.current_accepted_revision == row[1]
                and authority.current_accepted_state_digest == row[2]
                and current_time < min(row[3], authority.deadline)
                and row[0] in {"open", "human_requested"}
            )
            cursor.execute(
                "SELECT canonical_digest,disposition FROM recovery_reprobes WHERE tenant_id=%s "
                "AND reprobe_id=%s FOR UPDATE", (tenant_id, reprobe_id),
            )
            prior = cursor.fetchone()
            if prior is not None:
                if prior[0] != digest:
                    raise StateConflict("reprobe identity conflict")
                return "fenced_late" if prior[1] == "fenced_late" else row[0]
            cursor.execute(
                "INSERT INTO recovery_reprobes("
                "tenant_id,reprobe_id,incident_id,observation_ref,succeeded,disposition,"
                "canonical_digest) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (tenant_id, reprobe_id, incident_id, observation_ref, succeeded,
                 "observed" if current else "fenced_late", digest),
            )
            state = row[0]
            if current and succeeded and state in {"open", "human_requested"}:
                state = "resolved_automatic"
                cursor.execute(
                    "UPDATE recovery_incidents SET state=%s,updated_at=clock_timestamp() "
                    "WHERE tenant_id=%s AND incident_id=%s",
                    (state, tenant_id, incident_id),
                )
            self._audit(
                cursor, tenant_id=tenant_id, incident_id=incident_id,
                event_type=("automatic_reprobe_fenced" if not current else
                            "automatic_path_restored" if succeeded else
                            "automatic_reprobe_failed"),
                command_id=command_id, authority=authority,
                evidence={"reprobe_id": reprobe_id, "observation_ref": observation_ref},
            )
        return state if current else "fenced_late"

    def receive_manual(self, packet: ManualPacket, *, command_id: str) -> str:
        import psycopg

        _text(command_id, "command_id")
        digest = canonical_digest(packet.canonical())
        with psycopg.connect(self.dsn) as connection, connection.cursor() as cursor:
            authority = self.snapshot(cursor, "manual.receive", packet.incident_id)
            if not authority.authenticated:
                raise BoundaryRejected("manual packet subject not authenticated")
            cursor.execute(
                "SELECT generation,message_id,operation_id,source_scope_id,target_scope_id,"
                "accepted_revision,accepted_state_digest,expires_at,state "
                "FROM recovery_incidents WHERE tenant_id=%s AND incident_id=%s FOR UPDATE",
                (packet.tenant_id, packet.incident_id),
            )
            incident = cursor.fetchone()
            if incident is None:
                raise BoundaryRejected("manual packet crosses tenant or incident")
            cursor.execute(
                "SELECT canonical_digest,disposition FROM human_bridge_packets "
                "WHERE tenant_id=%s AND packet_id=%s FOR UPDATE",
                (packet.tenant_id, packet.packet_id),
            )
            prior = cursor.fetchone()
            if prior is not None:
                if prior[0] != digest:
                    raise StateConflict("manual packet identity conflict")
                return prior[1]
            immutable = (
                packet.message_id == incident[1] and packet.operation_id == incident[2]
                and packet.source_scope_id == incident[3]
                and packet.target_scope_id == incident[4]
                and packet.expected_accepted_revision == incident[5]
                and packet.accepted_state_digest == incident[6]
            )
            if not immutable:
                raise BoundaryRejected("manual packet lineage mismatch")
            cursor.execute(
                "SELECT operation_id,deadline,accepted_state_digest FROM delivery_messages "
                "WHERE tenant_id=%s AND message_id=%s FOR UPDATE",
                (packet.tenant_id, packet.message_id),
            )
            message = cursor.fetchone()
            if (message is None or message[0] != packet.operation_id
                    or message[2] != packet.accepted_state_digest):
                raise BoundaryRejected("manual packet delivery message is not current")
            cursor.execute(
                "SELECT operation_id,dispatch_id FROM delivery_attempts WHERE tenant_id=%s "
                "AND message_id=%s AND attempt_id=%s FOR UPDATE",
                (packet.tenant_id, packet.message_id, packet.attempt_id),
            )
            attempt = cursor.fetchone()
            if attempt != (packet.operation_id, packet.dispatch_id):
                raise BoundaryRejected("manual packet delivery attempt does not exist")
            # Recheck only after incident/message/attempt rows are locked.
            authority = self.snapshot(cursor, "manual.receive.final", packet.incident_id)
            cursor.execute("SELECT clock_timestamp()")
            database_now = cursor.fetchone()[0]
            current = (
                packet.incident_generation == incident[0]
                and authority.authenticated and authority.current_authority_valid
                and authority.task_valid
                and authority.current_accepted_revision == incident[5]
                and authority.current_accepted_state_digest == incident[6]
                and database_now < min(
                    packet.expires_at, incident[7], message[1], authority.deadline,
                )
                and incident[8] == "human_requested"
            )
            disposition = "committed" if current else "fenced_late"
            normal_outbox = packet.packet_id if current else None
            cursor.execute(
                "INSERT INTO human_bridge_packets("
                "tenant_id,packet_id,incident_id,incident_generation,message_id,operation_id,"
                "attempt_id,dispatch_id,source_scope_id,target_scope_id,direction,expected_accepted_revision,"
                "accepted_state_digest,payload_digest,expires_at,canonical_digest,disposition,"
                "normal_outbox_message_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                "%s,%s,%s,%s,%s,%s)",
                (packet.tenant_id, packet.packet_id, packet.incident_id,
                 packet.incident_generation, packet.message_id, packet.operation_id,
                 packet.attempt_id, packet.dispatch_id, packet.source_scope_id,
                 packet.target_scope_id, packet.direction,
                 packet.expected_accepted_revision, packet.accepted_state_digest,
                 packet.payload_digest, packet.expires_at, digest, disposition, normal_outbox),
            )
            if current:
                cursor.execute(
                    "INSERT INTO outbox(tenant_id,message_id,operation_id,topic,payload) "
                    "VALUES (%s,%s,%s,'human_bridge.manual_packet_committed',%s)",
                    (packet.tenant_id, packet.packet_id, packet.operation_id, json.dumps({
                        "incident_id": packet.incident_id,
                        "generation": packet.incident_generation,
                        "packet_id": packet.packet_id,
                        "message_id": packet.message_id,
                        "operation_id": packet.operation_id,
                        "attempt_id": packet.attempt_id,
                        "dispatch_id": packet.dispatch_id,
                        "direction": packet.direction,
                        "payload_digest": packet.payload_digest,
                    })),
                )
                cursor.execute(
                    "UPDATE recovery_incidents SET state='manual_packet_committed',"
                    "applied_packet_id=%s,updated_at=clock_timestamp() "
                    "WHERE tenant_id=%s AND incident_id=%s",
                    (packet.packet_id, packet.tenant_id, packet.incident_id),
                )
            self._audit(
                cursor, tenant_id=packet.tenant_id, incident_id=packet.incident_id,
                event_type="manual_packet_" + disposition, command_id=command_id,
                authority=authority, evidence={"packet_id": packet.packet_id,
                                               "canonical_digest": digest},
            )
        return disposition

    def confirm_manual(self, receipt: NormalReceipt, *, command_id: str) -> str:
        import psycopg

        _text(command_id, "command_id")
        digest = canonical_digest(receipt.canonical())
        with psycopg.connect(self.dsn) as connection, connection.cursor() as cursor:
            authority = self.snapshot(cursor, "manual.confirm", receipt.incident_id)
            if not authority.authenticated:
                raise BoundaryRejected("manual confirmation subject not authenticated")
            cursor.execute(
                "SELECT i.state,i.generation,i.message_id,i.operation_id,i.applied_packet_id,"
                "p.direction,p.payload_digest,p.attempt_id,p.dispatch_id,p.accepted_state_digest "
                "FROM recovery_incidents i "
                "JOIN human_bridge_packets p ON p.tenant_id=i.tenant_id "
                "AND p.packet_id=i.applied_packet_id WHERE i.tenant_id=%s AND i.incident_id=%s "
                "FOR UPDATE", (receipt.tenant_id, receipt.incident_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise BoundaryRejected("manual incident or packet not found")
            expected_layer = "target_inbox_committed" if row[5] == "request" else "response_received"
            immutable = (
                row[0] in {"manual_packet_committed", "resolved_manual"}
                and receipt.incident_generation == row[1]
                and receipt.message_id == row[2]
                and receipt.operation_id == row[3]
                and receipt.packet_id == row[4]
                and receipt.layer == expected_layer
                and receipt.payload_digest == row[6]
                and receipt.attempt_id == row[7]
                and receipt.dispatch_id == row[8]
                and receipt.direction == row[5]
            )
            if not immutable:
                raise BoundaryRejected("normal receipt lineage or direction mismatch")
            cursor.execute(
                "SELECT operation_id,accepted_state_digest FROM delivery_messages "
                "WHERE tenant_id=%s AND message_id=%s FOR UPDATE",
                (receipt.tenant_id, receipt.message_id),
            )
            message = cursor.fetchone()
            if message != (receipt.operation_id, row[9]):
                raise BoundaryRejected("normal receipt delivery message does not exist")
            cursor.execute(
                "SELECT operation_id,dispatch_id FROM delivery_attempts WHERE tenant_id=%s "
                "AND message_id=%s AND attempt_id=%s FOR UPDATE",
                (receipt.tenant_id, receipt.message_id, receipt.attempt_id),
            )
            attempt = cursor.fetchone()
            if attempt != (receipt.operation_id, receipt.dispatch_id):
                raise BoundaryRejected("normal receipt delivery attempt does not exist")
            cursor.execute(
                "SELECT receipt_id,evidence_json,attempt_id,dispatch_id FROM delivery_receipts "
                "WHERE tenant_id=%s AND message_id=%s AND receipt_id=%s AND layer=%s",
                (receipt.tenant_id, receipt.message_id, receipt.receipt_id, receipt.layer),
            )
            normal = cursor.fetchone()
            if normal is None:
                raise BoundaryRejected("normal receipt is not committed")
            bridge_evidence = {
                "incident_id": receipt.incident_id,
                "incident_generation": receipt.incident_generation,
                "packet_id": receipt.packet_id,
                "message_id": receipt.message_id,
                "operation_id": receipt.operation_id,
                "attempt_id": receipt.attempt_id,
                "dispatch_id": receipt.dispatch_id,
                "direction": receipt.direction,
                "layer": receipt.layer,
                "payload_digest": receipt.payload_digest,
            }
            if normal[1].get("human_bridge") != bridge_evidence:
                raise BoundaryRejected("normal receipt does not bind the current manual packet")
            if normal[2] != receipt.attempt_id or normal[3] != receipt.dispatch_id:
                raise BoundaryRejected("normal receipt attempt or dispatch changed")
            actual_evidence_digest = canonical_digest({
                "receipt_id": normal[0], "layer": receipt.layer,
                "message_id": receipt.message_id, "evidence": normal[1],
                "attempt_id": normal[2], "dispatch_id": normal[3],
            })
            if actual_evidence_digest != receipt.evidence_digest:
                raise BoundaryRejected("normal receipt digest mismatch")
            cursor.execute(
                "SELECT canonical_digest FROM human_bridge_normal_receipts "
                "WHERE tenant_id=%s AND receipt_id=%s FOR UPDATE",
                (receipt.tenant_id, receipt.receipt_id),
            )
            prior = cursor.fetchone()
            if prior is not None:
                if prior[0] != digest:
                    raise StateConflict("normal receipt identity conflict")
                return "resolved_manual"
            cursor.execute(
                "INSERT INTO human_bridge_normal_receipts("
                "tenant_id,receipt_id,incident_id,packet_id,message_id,operation_id,"
                "attempt_id,dispatch_id,direction,layer,payload_digest,evidence_digest,"
                "canonical_digest) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (receipt.tenant_id, receipt.receipt_id, receipt.incident_id,
                 receipt.packet_id, receipt.message_id, receipt.operation_id,
                 receipt.attempt_id, receipt.dispatch_id, receipt.direction,
                 receipt.layer, receipt.payload_digest, receipt.evidence_digest, digest),
            )
            cursor.execute(
                "UPDATE recovery_incidents SET state='resolved_manual',updated_at=clock_timestamp() "
                "WHERE tenant_id=%s AND incident_id=%s",
                (receipt.tenant_id, receipt.incident_id),
            )
            self._audit(
                cursor, tenant_id=receipt.tenant_id, incident_id=receipt.incident_id,
                event_type="manual_path_resolved", command_id=command_id,
                authority=authority, evidence={"receipt_id": receipt.receipt_id,
                                               "receipt_digest": receipt.evidence_digest},
            )
        return "resolved_manual"

    def expire(self, *, tenant_id: str, incident_id: str, command_id: str) -> str:
        """Expire one still-open generation using the database clock and current authority."""
        import psycopg

        for name, value in (
            ("tenant_id", tenant_id), ("incident_id", incident_id),
            ("command_id", command_id),
        ):
            _text(value, name)
        with psycopg.connect(self.dsn) as connection, connection.cursor() as cursor:
            authority = self.snapshot(cursor, "incident.expire", incident_id)
            if not authority.authenticated:
                raise BoundaryRejected("incident expiry subject not authenticated")
            cursor.execute(
                "SELECT state,expires_at FROM recovery_incidents "
                "WHERE tenant_id=%s AND incident_id=%s FOR UPDATE",
                (tenant_id, incident_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise BoundaryRejected("incident not found")
            if row[0] in {"resolved_automatic", "resolved_manual", "expired", "cancelled"}:
                return str(row[0])
            authority = self.snapshot(cursor, "incident.expire.final", incident_id)
            cursor.execute("SELECT clock_timestamp()")
            database_now = cursor.fetchone()[0]
            if database_now < min(row[1], authority.deadline):
                raise BoundaryRejected("incident expiry deadline has not elapsed")
            cursor.execute(
                "UPDATE recovery_incidents SET state='expired',updated_at=clock_timestamp() "
                "WHERE tenant_id=%s AND incident_id=%s",
                (tenant_id, incident_id),
            )
            self._audit(
                cursor, tenant_id=tenant_id, incident_id=incident_id,
                event_type="incident_expired", command_id=command_id,
                authority=authority, evidence={"expired_at": database_now.isoformat()},
            )
        return "expired"
