from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RECEIPT_LAYERS = (
    "accepted_by_authority",
    "target_inbox_committed",
    "runtime_dispatched",
    "runtime_acknowledged",
    "response_received",
)
_RECEIPT_INDEX = {name: index for index, name in enumerate(RECEIPT_LAYERS)}
_SHA256_CHARS = frozenset("0123456789abcdef")


class NodeJournalError(RuntimeError):
    """Base error for deterministic local Node journal failures."""


class OperationIdentityConflict(NodeJournalError, ValueError):
    """An operation, command, message, or payload identity was reused differently."""


class JournalCorruptionError(NodeJournalError):
    """The persisted SQLite journal is malformed or unsupported."""


class UncertainSpawnError(NodeJournalError):
    """A spawn operation has an uncertain durable outcome and cannot auto-repeat."""


class ReceiptOrderError(NodeJournalError, ValueError):
    """A lifecycle receipt would violate the observed completion ordering."""


class NotFoundError(NodeJournalError, KeyError):
    """A requested local journal object does not exist."""


@dataclass(frozen=True, slots=True)
class JournalOperation:
    operation_id: str
    command_id: str
    message_id: str
    operation_kind: str
    payload_sha256: str


@dataclass(frozen=True, slots=True)
class NodeIdentity:
    machine_id: str
    node_id: str
    boot_incarnation: str


@dataclass(frozen=True, slots=True)
class LifecycleReceipt:
    operation_id: str
    layer: str
    status: str
    receipt_id: str
    observed_at: str
    evidence: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class MailboxMessage:
    message_id: str
    command_id: str
    operation_id: str
    payload_sha256: str
    payload_json: str
    state: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ProcessObservation:
    operation_id: str
    process_label: str
    pid: int
    start_identity: str
    observed_at: str
    containment_claimed: bool = False


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _validate_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{field} must not contain control characters")
    return value


def _validate_sha256(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in _SHA256_CHARS for char in value)
    ):
        raise ValueError("payload_sha256 must be a lowercase SHA-256 digest")
    return value


def _canonical_payload(payload: Any) -> tuple[str, str]:
    # Tag both branches: tagging bytes alone permits a JSON object to impersonate
    # that byte envelope. Historical stored operation digests are not rewritten.
    envelope = (
        {"kind": "bytes", "value": payload.hex()}
        if isinstance(payload, bytes)
        else {"kind": "json", "value": payload}
    )
    encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":"))

    return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _operation_from_row(row: sqlite3.Row) -> JournalOperation:
    return JournalOperation(
        str(row["operation_id"]),
        str(row["command_id"]),
        str(row["message_id"]),
        str(row["operation_kind"]),
        str(row["payload_sha256"]),
    )


class NodeJournal:
    """Durable local observation journal for one Node identity.

    This class owns SQLite observation, mailbox, receipt, spawn-observation,
    and process-observation state only. It never imports or writes the Domain
    authority. Journal rows are observations and recovery inputs; they do not
    prove OS containment, Harness conformance, authorization, acceptance, or
    publication.

    The same database preserves machine_id and node_id across process restarts.
    Each normal construction creates and records a new boot_incarnation unless
    an explicit boot_incarnation is supplied for deterministic recovery/testing.
    """

    SCHEMA_VERSION = "acs-node-journal/2"

    _SCHEMA_STATEMENTS = (
        """
        CREATE TABLE IF NOT EXISTS node_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS node_boots (
            boot_incarnation TEXT PRIMARY KEY,
            machine_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            started_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS journal (
            operation_id TEXT PRIMARY KEY,
            command_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            operation_kind TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'recorded',
            created_at TEXT NOT NULL,
            machine_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            boot_incarnation TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS lifecycle_receipts (
            receipt_id TEXT PRIMARY KEY,
            operation_id TEXT NOT NULL REFERENCES journal(operation_id),
            layer TEXT NOT NULL,
            status TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            UNIQUE(operation_id, layer)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS mailbox (
            message_id TEXT PRIMARY KEY,
            command_id TEXT NOT NULL,
            operation_id TEXT NOT NULL REFERENCES journal(operation_id),
            payload_sha256 TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'committed',
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS process_observations (
            observation_id TEXT PRIMARY KEY,
            operation_id TEXT NOT NULL REFERENCES journal(operation_id),
            process_label TEXT NOT NULL,
            pid INTEGER NOT NULL,
            start_identity TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            containment_claimed INTEGER NOT NULL DEFAULT 0
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS spawn_states (
            operation_id TEXT PRIMARY KEY REFERENCES journal(operation_id),
            state TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            detail_json TEXT NOT NULL
        )
        """,
    )

    def __init__(
        self,
        path: str | Path,
        *,
        machine_id: str | None = None,
        node_id: str | None = None,
        boot_incarnation: str | None = None,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        if type(busy_timeout_ms) is not int or busy_timeout_ms < 0:
            raise ValueError("busy_timeout_ms must be a non-negative integer")

        self._path = str(path)
        _validate_text(self._path, "path")
        if self._path == ":memory:":
            raise ValueError("Node journal requires durable file storage")
        self._requested_machine_id = machine_id
        self._requested_node_id = node_id
        self._requested_boot_incarnation = boot_incarnation
        self._busy_timeout_ms = busy_timeout_ms
        self._identity: NodeIdentity | None = None

        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)

        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._path,
            timeout=max(self._busy_timeout_ms / 1000.0, 0.001),
            isolation_level=None,
            check_same_thread=False,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
        except BaseException:
            connection.close()
            raise
        return connection

    @contextmanager
    def _transaction(
        self,
        *,
        retries: int = 4,
    ) -> Iterator[sqlite3.Connection]:
        for attempt in range(retries + 1):
            connection = None
            try:
                connection = self._connect()
                connection.execute("BEGIN IMMEDIATE")
            except BaseException as exc:
                if connection is not None:
                    connection.close()
                if (not isinstance(exc, sqlite3.OperationalError)
                        or "locked" not in str(exc).lower() or attempt >= retries):
                    raise
                time.sleep(0.01 * (2**attempt))
            else:
                break
        try:
            if self._identity is not None:
                current = connection.execute(
                    "SELECT value FROM node_meta WHERE key='boot_incarnation'"
                ).fetchone()
                if current is None or current[0] != self.boot_incarnation:
                    raise OperationIdentityConflict("retired Node boot cannot mutate journal")
            yield connection
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._transaction() as connection:
            for statement in self._SCHEMA_STATEMENTS:
                connection.execute(statement)

            # Migrate the original five-column journal in place when a caller
            # reopens a database created by the pre-hardening implementation.
            journal_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(journal)")
            }
            legacy_columns = (
                (
                    "state",
                    "TEXT NOT NULL DEFAULT 'recorded'",
                ),
                (
                    "created_at",
                    "TEXT NOT NULL DEFAULT ''",
                ),
                (
                    "machine_id",
                    "TEXT NOT NULL DEFAULT 'legacy-machine'",
                ),
                (
                    "node_id",
                    "TEXT NOT NULL DEFAULT 'legacy-node'",
                ),
                (
                    "boot_incarnation",
                    "TEXT NOT NULL DEFAULT 'legacy-boot'",
                ),
            )
            for name, definition in legacy_columns:
                if name not in journal_columns:
                    connection.execute(
                        f"ALTER TABLE journal ADD COLUMN {name} {definition}"
                    )

            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS journal_command_identity
                    ON journal(command_id)
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS journal_message_identity
                    ON journal(message_id)
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS mailbox_command_identity
                    ON mailbox(command_id)
                """
            )

            schema_row = connection.execute(
                "SELECT value FROM node_meta WHERE key='schema_version'"
            ).fetchone()
            if schema_row is None:
                connection.execute(
                    "INSERT INTO node_meta(key,value) VALUES('schema_version',?)",
                    (self.SCHEMA_VERSION,),
                )
            elif schema_row["value"] != self.SCHEMA_VERSION:
                raise JournalCorruptionError(
                    f"unsupported node journal schema: {schema_row['value']}"
                )

            machine_row = connection.execute(
                "SELECT value FROM node_meta WHERE key='machine_id'"
            ).fetchone()
            node_row = connection.execute(
                "SELECT value FROM node_meta WHERE key='node_id'"
            ).fetchone()

            if machine_row is None:
                machine_value = self._requested_machine_id or f"machine-{uuid.uuid4()}"
                connection.execute(
                    "INSERT INTO node_meta(key,value) VALUES('machine_id',?)",
                    (machine_value,),
                )
            else:
                machine_value = str(machine_row["value"])
                if self._requested_machine_id not in (None, machine_value):
                    raise OperationIdentityConflict("machine_id")

            if node_row is None:
                node_value = self._requested_node_id or f"node-{uuid.uuid4()}"
                connection.execute(
                    "INSERT INTO node_meta(key,value) VALUES('node_id',?)",
                    (node_value,),
                )
            else:
                node_value = str(node_row["value"])
                if self._requested_node_id not in (None, node_value):
                    raise OperationIdentityConflict("node_id")

            _validate_text(machine_value, "machine_id")
            _validate_text(node_value, "node_id")

            boot_value = (
                self._requested_boot_incarnation
                or f"boot-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}"
                f"-{secrets.token_hex(8)}"
            )
            _validate_text(boot_value, "boot_incarnation")

            existing_boot = connection.execute(
                """
                SELECT machine_id,node_id
                FROM node_boots
                WHERE boot_incarnation=?
                """,
                (boot_value,),
            ).fetchone()
            if existing_boot is not None and (
                existing_boot["machine_id"] != machine_value
                or existing_boot["node_id"] != node_value
            ):
                raise OperationIdentityConflict("boot_incarnation")

            previous_boot = connection.execute(
                "SELECT value FROM node_meta WHERE key='boot_incarnation'"
            ).fetchone()
            if existing_boot is not None and previous_boot is not None and previous_boot[0] != boot_value:
                raise OperationIdentityConflict("retired boot incarnation cannot be reactivated")
            if previous_boot is not None and previous_boot[0] != boot_value:
                connection.execute(
                    "UPDATE spawn_states SET state='uncertain',updated_at=? "
                    "WHERE state IN ('intent','dispatched','still_running')", (_utc_now(),)
                )

            connection.execute(
                """
                INSERT INTO node_boots(
                    boot_incarnation,machine_id,node_id,started_at
                )
                VALUES (?,?,?,?)
                ON CONFLICT(boot_incarnation) DO NOTHING
                """,
                (
                    boot_value,
                    machine_value,
                    node_value,
                    _utc_now(),
                ),
            )
            connection.execute(
                """
                INSERT INTO node_meta(key,value)
                VALUES('boot_incarnation',?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (boot_value,),
            )

            self._identity = NodeIdentity(
                machine_id=machine_value,
                node_id=node_value,
                boot_incarnation=boot_value,
            )

            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise JournalCorruptionError("SQLite integrity_check failed")

    @property
    def identity(self) -> NodeIdentity:
        if self._identity is None:
            raise JournalCorruptionError("node identity is unavailable")
        return self._identity

    @property
    def machine_id(self) -> str:
        return self.identity.machine_id

    @property
    def node_id(self) -> str:
        return self.identity.node_id

    @property
    def boot_incarnation(self) -> str:
        return self.identity.boot_incarnation

    @staticmethod
    def payload_digest(payload: Any) -> str:
        return _canonical_payload(payload)[1]

    def append(self, operation: JournalOperation) -> JournalOperation:
        _validate_text(operation.operation_id, "operation_id")
        _validate_text(operation.command_id, "command_id")
        _validate_text(operation.message_id, "message_id")
        _validate_text(operation.operation_kind, "operation_kind")
        _validate_sha256(operation.payload_sha256)

        try:
            with self._transaction() as connection:
                existing = connection.execute(
                    """
                    SELECT operation_id,command_id,message_id,
                           operation_kind,payload_sha256
                    FROM journal
                    WHERE operation_id=?
                    """,
                    (operation.operation_id,),
                ).fetchone()
                if existing is not None:
                    candidate = _operation_from_row(existing)
                    if candidate != operation:
                        raise OperationIdentityConflict(operation.operation_id)
                    return candidate

                for column, value in (
                    ("command_id", operation.command_id),
                    ("message_id", operation.message_id),
                ):
                    row = connection.execute(
                        f"""
                        SELECT operation_id,command_id,message_id,
                               operation_kind,payload_sha256
                        FROM journal
                        WHERE {column}=?
                        """,
                        (value,),
                    ).fetchone()
                    if row is not None:
                        existing_operation = _operation_from_row(row)
                        if existing_operation != operation:
                            raise OperationIdentityConflict(value)
                        return existing_operation

                connection.execute(
                    """
                    INSERT INTO journal(
                        operation_id,command_id,message_id,operation_kind,
                        payload_sha256,state,created_at,machine_id,node_id,
                        boot_incarnation
                    )
                    VALUES (?,?,?,?,?,'recorded',?,?,?,?)
                    """,
                    (
                        operation.operation_id,
                        operation.command_id,
                        operation.message_id,
                        operation.operation_kind,
                        operation.payload_sha256,
                        _utc_now(),
                        self.machine_id,
                        self.node_id,
                        self.boot_incarnation,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            # A concurrent writer may have committed the same identity after
            # the first transaction checked it. Resolve exact replay or fail
            # closed as a conflict.
            with closing(self._connect()) as connection:
                for column, value in (
                    ("operation_id", operation.operation_id),
                    ("command_id", operation.command_id),
                    ("message_id", operation.message_id),
                ):
                    row = connection.execute(
                        f"""
                        SELECT operation_id,command_id,message_id,
                               operation_kind,payload_sha256
                        FROM journal
                        WHERE {column}=?
                        """,
                        (value,),
                    ).fetchone()
                    if row is not None:
                        existing_operation = _operation_from_row(row)
                        if existing_operation == operation:
                            return existing_operation
            raise OperationIdentityConflict(operation.operation_id) from exc

        return operation

    def read(self, operation_id: str) -> JournalOperation | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT operation_id,command_id,message_id,
                       operation_kind,payload_sha256
                FROM journal
                WHERE operation_id=?
                """,
                (operation_id,),
            ).fetchone()
        return None if row is None else _operation_from_row(row)

    def digest(self, operation: JournalOperation) -> str:
        # Preserve the historical public digest behavior of the baseline
        # interface, including its default JSON spacing.
        return hashlib.sha256(
            json.dumps(asdict(operation), sort_keys=True).encode("utf-8")
        ).hexdigest()

    def enqueue(
        self,
        *,
        message_id: str,
        command_id: str,
        operation_id: str,
        payload: Any,
        payload_sha256: str | None = None,
    ) -> MailboxMessage:
        _validate_text(message_id, "message_id")
        _validate_text(command_id, "command_id")
        _validate_text(operation_id, "operation_id")

        payload_json, computed_digest = _canonical_payload(payload)
        digest = _validate_sha256(computed_digest if payload_sha256 is None else payload_sha256)
        if digest != computed_digest:
            raise OperationIdentityConflict(message_id)

        created_at = _utc_now()

        try:
            with self._transaction() as connection:
                operation_row = connection.execute(
                    """
                    SELECT operation_id,command_id,message_id,
                           operation_kind,payload_sha256
                    FROM journal
                    WHERE operation_id=?
                    """,
                    (operation_id,),
                ).fetchone()
                if operation_row is None:
                    raise NotFoundError(operation_id)

                operation = _operation_from_row(operation_row)
                if (
                    operation.command_id != command_id
                    or operation.message_id != message_id
                    or operation.payload_sha256 != computed_digest
                ):
                    raise OperationIdentityConflict(operation_id)

                row = connection.execute(
                    """
                    SELECT message_id,command_id,operation_id,
                           payload_sha256,payload_json,state,created_at
                    FROM mailbox
                    WHERE message_id=?
                    """,
                    (message_id,),
                ).fetchone()
                if row is not None:
                    existing = MailboxMessage(*tuple(row))
                    if (
                        existing.command_id != command_id
                        or existing.operation_id != operation_id
                        or existing.payload_sha256 != digest
                        or existing.payload_json != payload_json
                    ):
                        raise OperationIdentityConflict(message_id)
                    return existing

                command_row = connection.execute(
                    """
                    SELECT message_id,command_id,operation_id,
                           payload_sha256,payload_json,state,created_at
                    FROM mailbox
                    WHERE command_id=?
                    """,
                    (command_id,),
                ).fetchone()
                if command_row is not None:
                    existing = MailboxMessage(*tuple(command_row))
                    if (
                        existing.message_id != message_id
                        or existing.operation_id != operation_id
                        or existing.payload_sha256 != digest
                        or existing.payload_json != payload_json
                    ):
                        raise OperationIdentityConflict(command_id)
                    return existing

                receipt_rows = connection.execute(
                    "SELECT layer FROM lifecycle_receipts WHERE operation_id=?", (operation_id,),
                ).fetchall()
                try:
                    inherited_state = (
                        max((str(row["layer"]) for row in receipt_rows), key=_RECEIPT_INDEX.__getitem__)
                        if receipt_rows else "committed"
                    )
                except KeyError as exc:
                    raise JournalCorruptionError(f"unknown stored receipt layer for {operation_id}") from exc
                connection.execute(
                    """
                    INSERT INTO mailbox(
                        message_id,command_id,operation_id,payload_sha256,
                        payload_json,state,created_at
                    )
                    VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        message_id,
                        command_id,
                        operation_id,
                        digest,
                        payload_json,
                        inherited_state,
                        created_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise OperationIdentityConflict(message_id) from exc

        return MailboxMessage(
            message_id=message_id,
            command_id=command_id,
            operation_id=operation_id,
            payload_sha256=digest,
            payload_json=payload_json,
            state=inherited_state,
            created_at=created_at,
        )

    def get_message(self, message_id: str) -> MailboxMessage | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT message_id,command_id,operation_id,
                       payload_sha256,payload_json,state,created_at
                FROM mailbox
                WHERE message_id=?
                """,
                (message_id,),
            ).fetchone()
        return None if row is None else MailboxMessage(*tuple(row))

    def list_mailbox(
        self,
        *,
        state: str | None = None,
    ) -> tuple[MailboxMessage, ...]:
        with closing(self._connect()) as connection:
            if state is None:
                rows = connection.execute(
                    """
                    SELECT message_id,command_id,operation_id,
                           payload_sha256,payload_json,state,created_at
                    FROM mailbox
                    ORDER BY created_at,message_id
                    """
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT message_id,command_id,operation_id,
                           payload_sha256,payload_json,state,created_at
                    FROM mailbox
                    WHERE state=?
                    ORDER BY created_at,message_id
                    """,
                    (state,),
                ).fetchall()

        return tuple(MailboxMessage(*tuple(row)) for row in rows)

    def record_receipt(
        self,
        operation_id: str,
        layer: str,
        *,
        status: str = "observed",
        evidence: Mapping[str, Any] | None = None,
        receipt_id: str | None = None,
        observed_at: str | None = None,
    ) -> LifecycleReceipt:
        _validate_text(operation_id, "operation_id")
        _validate_text(layer, "layer")
        _validate_text(status, "status")

        if layer not in _RECEIPT_INDEX:
            raise ValueError(f"unsupported lifecycle receipt layer: {layer}")

        evidence_value = dict(evidence or {})
        evidence_json = json.dumps(
            evidence_value,
            sort_keys=True,
            separators=(",", ":"),
        )
        observed = observed_at or _utc_now()
        receipt = receipt_id or f"{operation_id}:{layer}"

        with self._transaction() as connection:
            operation_row = connection.execute(
                """
                SELECT operation_id FROM journal WHERE operation_id=?
                """,
                (operation_id,),
            ).fetchone()
            if operation_row is None:
                raise NotFoundError(operation_id)

            rows = connection.execute(
                """
                SELECT layer FROM lifecycle_receipts
                WHERE operation_id=?
                """,
                (operation_id,),
            ).fetchall()

            try:
                existing_layers = {
                    _RECEIPT_INDEX[str(row["layer"])]
                    for row in rows
                }
            except KeyError as exc:
                raise JournalCorruptionError(
                    f"unknown stored receipt layer for {operation_id}"
                ) from exc

            current_index = _RECEIPT_INDEX[layer]
            prior = connection.execute(
                """
                SELECT receipt_id,operation_id,layer,status,
                       observed_at,evidence_json
                FROM lifecycle_receipts
                WHERE operation_id=? AND layer=?
                """,
                (operation_id, layer),
            ).fetchone()

            if prior is not None:
                existing = LifecycleReceipt(
                    operation_id=str(prior["operation_id"]),
                    layer=str(prior["layer"]),
                    status=str(prior["status"]),
                    receipt_id=str(prior["receipt_id"]),
                    observed_at=str(prior["observed_at"]),
                    evidence=json.loads(str(prior["evidence_json"])),
                )
                if (
                    existing.receipt_id != receipt
                    or existing.status != status
                    or existing.evidence != evidence_value
                ):
                    raise OperationIdentityConflict(operation_id)
                return existing

            if any(index > current_index for index in existing_layers):
                raise ReceiptOrderError(operation_id)

            connection.execute(
                """
                INSERT INTO lifecycle_receipts(
                    receipt_id,operation_id,layer,status,
                    observed_at,evidence_json
                )
                VALUES (?,?,?,?,?,?)
                """,
                (
                    receipt,
                    operation_id,
                    layer,
                    status,
                    observed,
                    evidence_json,
                ),
            )
            connection.execute(
                "UPDATE journal SET state=? WHERE operation_id=?",
                (layer, operation_id),
            )
            connection.execute(
                """
                UPDATE mailbox
                SET state=?
                WHERE operation_id=?
                """,
                (layer, operation_id),
            )

        return LifecycleReceipt(
            operation_id=operation_id,
            layer=layer,
            status=status,
            receipt_id=receipt,
            observed_at=observed,
            evidence=evidence_value,
        )

    def receipts(self, operation_id: str) -> tuple[LifecycleReceipt, ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT receipt_id,operation_id,layer,status,
                       observed_at,evidence_json
                FROM lifecycle_receipts
                WHERE operation_id=?
                """,
                (operation_id,),
            ).fetchall()

        receipts = tuple(
            LifecycleReceipt(
                operation_id=str(row["operation_id"]),
                layer=str(row["layer"]),
                status=str(row["status"]),
                receipt_id=str(row["receipt_id"]),
                observed_at=str(row["observed_at"]),
                evidence=json.loads(str(row["evidence_json"])),
            )
            for row in rows
        )
        return tuple(sorted(receipts, key=lambda item: _RECEIPT_INDEX[item.layer]))

    @staticmethod
    def _spawn_detail(row: sqlite3.Row, operation_id: str) -> dict[str, Any]:
        try:
            detail = json.loads(str(row["detail_json"]))
            if not isinstance(detail, dict):
                raise TypeError("spawn detail is not an object")
            _validate_text(detail.get("process_label"), "process_label")
            return detail
        except (TypeError, ValueError) as exc:
            raise JournalCorruptionError(operation_id) from exc

    @staticmethod
    def _process_evidence(
        connection: sqlite3.Connection, operation_id: str,
        detail: Mapping[str, Any], evidence: Mapping[str, Any], *, absent: bool = False,
    ) -> None:
        if evidence.get("process_label") != detail["process_label"]:
            raise OperationIdentityConflict("process label differs from spawn identity")
        identity = detail.get("process_identity")
        if absent and identity is None:
            if evidence.get("observation") != "absent" or any(
                key in evidence for key in ("pid", "start_identity")
            ):
                raise OperationIdentityConflict("absence requires an explicit label-bound Node observation")
            return
        if (not isinstance(identity, dict) or type(evidence.get("pid")) is not int
                or evidence.get("pid") != identity.get("pid")
                or evidence.get("start_identity") != identity.get("start_identity")):
            raise OperationIdentityConflict("process PID/start identity is not bound")
        if absent and evidence.get("observation") != "absent":
            raise OperationIdentityConflict("absence requires an explicit Node observation")
        row = connection.execute(
            "SELECT 1 FROM process_observations WHERE operation_id=? AND process_label=? "
            "AND pid=? AND start_identity=? LIMIT 1",
            (operation_id, detail["process_label"], evidence["pid"], evidence["start_identity"]),
        ).fetchone()
        if row is None:
            raise OperationIdentityConflict("process observation is not recorded")

    def begin_spawn(
        self, operation: JournalOperation, *, process_label: str | None = None,
    ) -> JournalOperation:
        """Prepare intent only; a True mark_spawn_dispatched result permits dispatch.

        Replaying this method is never permission to create another OS process.
        Completed/absent operations retain their original operation identity.
        """
        if operation.operation_kind != "spawn":
            raise ValueError("begin_spawn requires operation_kind='spawn'")
        if process_label is not None:
            _validate_text(process_label, "process_label")
        self.append(operation)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT state,detail_json FROM spawn_states WHERE operation_id=?",
                (operation.operation_id,),
            ).fetchone()
            if row is not None:
                detail = self._spawn_detail(row, operation.operation_id)
                if process_label is not None and process_label != detail["process_label"]:
                    raise OperationIdentityConflict("process label differs from spawn identity")
                state = str(row["state"])
                if state in {"uncertain", "dispatched", "still_running"}:
                    raise UncertainSpawnError("spawn is dispatched, running, or requires reconciliation")
                if state in {"intent", "completed", "absent"}:
                    return operation
                raise JournalCorruptionError(operation.operation_id)
            detail = {
                "operation_id": operation.operation_id,
                "process_label": process_label or f"node-process:{operation.operation_id}",
                "intent_boot": self.boot_incarnation,
            }
            connection.execute(
                "INSERT INTO spawn_states(operation_id,state,updated_at,detail_json) VALUES (?,'intent',?,?)",
                (operation.operation_id, _utc_now(), json.dumps(detail, sort_keys=True)),
            )
        return operation

    def _set_spawn_state(
        self, operation_id: str, state: str, detail: Mapping[str, Any] | None = None,
    ) -> bool:
        _validate_text(operation_id, "operation_id")
        if state not in {"dispatched", "completed", "uncertain"}:
            raise ValueError("spawn state requires explicit preparation or reconciliation")
        supplied = dict(detail or {})
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT s.state,s.detail_json FROM spawn_states s JOIN journal j "
                "ON j.operation_id=s.operation_id WHERE s.operation_id=? AND j.operation_kind='spawn'",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise UncertainSpawnError("spawn intent is not recorded")
            stored = self._spawn_detail(row, operation_id)
            current = str(row["state"])
            if (supplied.get("process_label") is not None
                    and supplied["process_label"] != stored["process_label"]):
                raise OperationIdentityConflict("process label differs from spawn identity")
            if state == "dispatched":
                if current in {"dispatched", "still_running", "completed", "absent"}:
                    return False
                if current != "intent":
                    raise UncertainSpawnError("uncertain spawn cannot be dispatched")
                stored["dispatch_boot"] = self.boot_incarnation
            elif state == "completed":
                if current == "completed" and stored.get("completion_evidence") == supplied:
                    return False
                if current not in {"dispatched", "still_running"}:
                    raise OperationIdentityConflict("completion requires a dispatched process")
                self._process_evidence(connection, operation_id, stored, supplied)
                stored["completion_evidence"] = supplied
            else:
                _validate_text(supplied.get("reason"), "reason")
                if current == "uncertain" and stored.get("uncertainty_reason") == supplied["reason"]:
                    return False
                if current not in {"intent", "dispatched", "still_running"}:
                    raise OperationIdentityConflict("spawn state cannot regress or overwrite uncertainty")
                stored["uncertainty_reason"] = supplied["reason"]
            connection.execute(
                "UPDATE spawn_states SET state=?,updated_at=?,detail_json=? WHERE operation_id=? AND state=?",
                (state, _utc_now(), json.dumps(stored, sort_keys=True), operation_id, current),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise OperationIdentityConflict("spawn transition lost its state binding")
            return True

    def mark_spawn_dispatched(
        self, operation_id: str, *, process_label: str | None = None,
    ) -> bool:
        """Atomically claim dispatch; only True authorizes one OS dispatch."""
        return self._set_spawn_state(operation_id, "dispatched", {"process_label": process_label})

    def mark_spawn_completed(
        self, operation_id: str, *, evidence: Mapping[str, Any] | None = None,
    ) -> None:
        self._set_spawn_state(operation_id, "completed", evidence)

    def mark_spawn_uncertain(self, operation_id: str, *, reason: str) -> None:
        _validate_text(reason, "reason")
        self._set_spawn_state(operation_id, "uncertain", {"reason": reason})

    def reconcile_spawn(
        self, operation_id: str, *, outcome: str, evidence: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Record trusted Node observations; this does not attest OS containment."""
        _validate_text(operation_id, "operation_id")
        if outcome not in {"completed", "absent", "still_running", "uncertain"}:
            raise ValueError("unsupported spawn reconciliation outcome")
        observed = dict(evidence or {})
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT state,detail_json FROM spawn_states WHERE operation_id=?", (operation_id,),
            ).fetchone()
            if row is None:
                raise UncertainSpawnError("spawn intent is not recorded")
            state = str(row["state"])
            detail = self._spawn_detail(row, operation_id)
            if state in {"completed", "absent"}:
                if outcome == state and detail.get("reconciliation") == observed:
                    return detail
                raise OperationIdentityConflict("terminal spawn observation cannot be rewritten")
            if state not in {"uncertain", "still_running"}:
                raise OperationIdentityConflict("spawn reconciliation requires uncertainty or a running observation")
            if outcome in {"completed", "still_running", "absent"}:
                self._process_evidence(connection, operation_id, detail, observed, absent=outcome == "absent")
            elif observed.get("process_label") != detail["process_label"]:
                raise OperationIdentityConflict("process label differs from spawn identity")
            elif any(key in observed for key in ("pid", "start_identity")):
                self._process_evidence(connection, operation_id, detail, observed)
            detail["reconciliation"] = observed
            detail["reconciled_at"] = _utc_now()
            detail["reconciled_by_boot"] = self.boot_incarnation
            connection.execute(
                "UPDATE spawn_states SET state=?,updated_at=?,detail_json=? WHERE operation_id=?",
                (outcome, _utc_now(), json.dumps(detail, sort_keys=True), operation_id),
            )
        return detail

    def spawn_state(
        self,
        operation_id: str,
    ) -> tuple[str, Mapping[str, Any]] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT state,detail_json
                FROM spawn_states
                WHERE operation_id=?
                """,
                (operation_id,),
            ).fetchone()

        if row is None:
            return None

        detail = json.loads(str(row["detail_json"]))
        if not isinstance(detail, dict):
            raise JournalCorruptionError(operation_id)
        return str(row["state"]), detail

    def record_process_observation(
        self,
        operation_id: str,
        *,
        process_label: str,
        pid: int,
        start_identity: str,
        containment_claimed: bool = False,
    ) -> ProcessObservation:
        _validate_text(operation_id, "operation_id")
        _validate_text(process_label, "process_label")
        _validate_text(start_identity, "start_identity")

        if type(pid) is not int:
            raise TypeError("pid must be an integer")
        if pid <= 0:
            raise ValueError("pid must be a positive integer")

        # Node may record an observation, but it cannot promote that observation
        # into an OS containment claim.
        if containment_claimed:
            raise ValueError(
                "NodeJournal records process observations only; "
                "it cannot claim containment"
            )

        observed = ProcessObservation(
            operation_id=operation_id,
            process_label=process_label,
            pid=pid,
            start_identity=start_identity,
            observed_at=_utc_now(),
            containment_claimed=False,
        )

        with self._transaction() as connection:
            row = connection.execute(
                "SELECT j.operation_kind,s.state,s.detail_json FROM journal j LEFT JOIN spawn_states s "
                "ON s.operation_id=j.operation_id WHERE j.operation_id=?", (operation_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError(operation_id)
            if row["operation_kind"] != "spawn" or row["state"] is None:
                raise UncertainSpawnError("spawn intent is not recorded")
            if row["state"] not in {"dispatched", "uncertain", "still_running"}:
                raise OperationIdentityConflict("process observation requires a dispatched or uncertain spawn")
            detail = self._spawn_detail(row, operation_id)
            if process_label != detail["process_label"]:
                raise OperationIdentityConflict("process label differs from spawn identity")
            identity = {"pid": pid, "start_identity": start_identity}
            if detail.get("process_identity") not in (None, identity):
                raise OperationIdentityConflict("process PID/start identity differs from recorded spawn")
            detail["process_identity"] = identity
            connection.execute("UPDATE spawn_states SET detail_json=? WHERE operation_id=?",
                               (json.dumps(detail, sort_keys=True), operation_id))
            connection.execute(
                """
                INSERT INTO process_observations(
                    observation_id,operation_id,process_label,pid,
                    start_identity,observed_at,containment_claimed
                )
                VALUES (?,?,?,?,?,?,0)
                """,
                (
                    f"observation-{uuid.uuid4()}",
                    operation_id,
                    process_label,
                    pid,
                    start_identity,
                    observed.observed_at,
                ),
            )

        return observed

    def process_observations(
        self,
        operation_id: str,
    ) -> tuple[ProcessObservation, ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT operation_id,process_label,pid,
                       start_identity,observed_at,containment_claimed
                FROM process_observations
                WHERE operation_id=?
                ORDER BY observed_at
                """,
                (operation_id,),
            ).fetchall()

        return tuple(
            ProcessObservation(
                operation_id=str(row["operation_id"]),
                process_label=str(row["process_label"]),
                pid=int(row["pid"]),
                start_identity=str(row["start_identity"]),
                observed_at=str(row["observed_at"]),
                containment_claimed=bool(row["containment_claimed"]),
            )
            for row in rows
        )

    def recover(self) -> dict[str, Any]:
        """Return durable local state requiring external reconciliation.

        Recovery never spawns, retries an effect, writes Domain state, or
        upgrades observations into containment/conformance evidence.
        """
        with closing(self._connect()) as connection:
            uncertain_rows = connection.execute(
                """
                SELECT operation_id,detail_json
                FROM spawn_states
                WHERE state='uncertain'
                ORDER BY updated_at
                """
            ).fetchall()
            pending_rows = connection.execute(
                """
                SELECT message_id,operation_id,state
                FROM mailbox
                WHERE state != 'response_received'
                ORDER BY created_at,message_id
                """
            ).fetchall()

        return {
            "identity": asdict(self.identity),
            "uncertain_spawns": tuple(
                {
                    "operation_id": str(row["operation_id"]),
                    **json.loads(str(row["detail_json"])),
                }
                for row in uncertain_rows
            ),
            "pending_mailbox": tuple(
                {
                    "message_id": str(row["message_id"]),
                    "operation_id": str(row["operation_id"]),
                    "state": str(row["state"]),
                }
                for row in pending_rows
            ),
        }
