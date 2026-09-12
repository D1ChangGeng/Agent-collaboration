from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
from collections.abc import Callable
from contextlib import closing, contextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

from nacl.signing import SigningKey

from runtime.receiver_config import ReceiverRuntimeConfig
from runtime.receiver_crypto import canonical, sha256, sign, verify
from runtime.receiver_models import (
    DeliveryAdmission,
    DispatchBody,
    PrepareBody,
    ReadbackBody,
    ReceiverReceipt,
    RecoveryBody,
    SignedReceipt,
    SignedRequest,
)
from runtime.receiver_paths import (
    PathSecurityRejected,
    ensure_private_database,
    open_validated_file,
    validated_file_identity,
)


class ReceiverRejected(RuntimeError):
    pass


_ACTIVE_EXECUTION_LEASES: set[str] = set()
_ACTIVE_EXECUTION_LEASES_LOCK = threading.Lock()


def _process_start(process_id: int) -> str:
    try:
        return Path(f"/proc/{process_id}/stat").read_text(encoding="ascii").split()[21]
    except (OSError, IndexError, UnicodeDecodeError):
        return ""


@contextmanager
def _active_execution_lease(lease_id: str):
    with _ACTIVE_EXECUTION_LEASES_LOCK:
        _ACTIVE_EXECUTION_LEASES.add(lease_id)
    try:
        yield
    finally:
        with _ACTIVE_EXECUTION_LEASES_LOCK:
            _ACTIVE_EXECUTION_LEASES.discard(lease_id)


class ReceiverLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._witness_fd: int | None = None
        try:
            created_identity = ensure_private_database(self.path)
            self._witness_fd, self._identity = open_validated_file(self.path, private=True)
            if self._identity != created_identity:
                raise ReceiverRejected("receiver journal identity changed after creation")
        except PathSecurityRejected:
            self.close()
            raise ReceiverRejected("receiver journal path admission rejected") from None
        except BaseException:
            self.close()
            raise
        with closing(self.connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS receiver_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS receiver_requests(
                    request_id TEXT PRIMARY KEY, nonce TEXT NOT NULL UNIQUE,
                    canonical_hash TEXT NOT NULL, purpose TEXT NOT NULL,
                    body_sha256 TEXT NOT NULL, admission_sha256 TEXT NOT NULL,
                    signed_request_sha256 TEXT NOT NULL, signed_request_json TEXT NOT NULL,
                    admission_json TEXT NOT NULL, body_json TEXT NOT NULL,
                    authority_signature TEXT NOT NULL, prepare_identity_json TEXT NOT NULL,
                    operation_id TEXT NOT NULL, attempt_id TEXT NOT NULL, dispatch_id TEXT NOT NULL,
                    admitted_boot TEXT NOT NULL, journal_generation INTEGER NOT NULL,
                    state TEXT NOT NULL, local_dispatch_marker INTEGER NOT NULL,
                    receipt_json TEXT NOT NULL, receipt_signature TEXT NOT NULL,
                    receipt_sha256 TEXT NOT NULL, signed_receipt_sha256 TEXT NOT NULL,
                    execution_lease_id TEXT NOT NULL DEFAULT '',
                    execution_lease_expires_at TEXT NOT NULL DEFAULT '',
                    execution_process_id INTEGER NOT NULL DEFAULT 0,
                    execution_process_start TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS receiver_dispatch_lookup
                  ON receiver_requests(operation_id,dispatch_id,purpose);
                CREATE UNIQUE INDEX IF NOT EXISTS receiver_one_prepare_identity
                  ON receiver_requests(operation_id,attempt_id,dispatch_id)
                  WHERE purpose='delivery.prepare';
                CREATE UNIQUE INDEX IF NOT EXISTS receiver_one_dispatch_marker
                  ON receiver_requests(operation_id,attempt_id,dispatch_id)
                  WHERE local_dispatch_marker=1;
                CREATE TABLE IF NOT EXISTS native_calls(
                    dispatch_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, called_at TEXT NOT NULL
                );
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(receiver_requests)")}
            if "execution_lease_id" not in columns:
                connection.execute(
                    "ALTER TABLE receiver_requests ADD COLUMN execution_lease_id TEXT NOT NULL DEFAULT ''"
                )
            if "execution_lease_expires_at" not in columns:
                connection.execute(
                    "ALTER TABLE receiver_requests ADD COLUMN execution_lease_expires_at "
                    "TEXT NOT NULL DEFAULT ''"
                )
            if "execution_process_id" not in columns:
                connection.execute(
                    "ALTER TABLE receiver_requests ADD COLUMN execution_process_id "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            if "execution_process_start" not in columns:
                connection.execute(
                    "ALTER TABLE receiver_requests ADD COLUMN execution_process_start "
                    "TEXT NOT NULL DEFAULT ''"
                )

    def connect(self):
        connection = None
        try:
            before = validated_file_identity(self.path, private=True)
            witness = os.fstat(self._witness_fd)
            witness_identity = (
                witness.st_dev, witness.st_ino, witness.st_mode, witness.st_uid,
                witness.st_gid, witness.st_nlink,
            )
            if before != self._identity or witness_identity != self._identity:
                raise ReceiverRejected("receiver journal identity changed")
            connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
            after = validated_file_identity(self.path, private=True)
            if after != before or after != self._identity:
                raise ReceiverRejected("receiver journal identity changed while opening")
            connection.row_factory = sqlite3.Row
            return connection
        except PathSecurityRejected:
            if connection is not None:
                connection.close()
            raise ReceiverRejected("receiver journal path admission rejected") from None
        except BaseException:
            if connection is not None:
                connection.close()
            raise

    def close(self):
        if self._witness_fd is not None:
            os.close(self._witness_fd)
            self._witness_fd = None

    def __del__(self):
        try:
            self.close()
        except OSError:
            pass

    @contextmanager
    def transaction(self):
        with closing(self.connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def claim_boot(self, boot: str, generation: int, *, old_boot_isolation_ref: str | None = None):
        if not boot or generation < 1:
            raise ReceiverRejected("invalid boot claim")
        with self.transaction() as connection:
            rows = dict(connection.execute("SELECT key,value FROM receiver_meta"))
            if not rows:
                if generation != 1 or old_boot_isolation_ref is not None:
                    raise ReceiverRejected("initial journal generation must be one")
                values = {"current_boot": boot, "journal_generation": "1",
                          "previous_boot": "", "old_boot_isolation_ref": ""}
                connection.executemany("INSERT INTO receiver_meta(key,value) VALUES (?,?)", values.items())
                return
            if rows["current_boot"] == boot and int(rows["journal_generation"]) == generation:
                return
            if generation != int(rows["journal_generation"]) + 1 or not old_boot_isolation_ref:
                raise ReceiverRejected("boot replacement lacks monotonic generation or isolation proof")
            connection.execute("UPDATE receiver_meta SET value=? WHERE key='previous_boot'", (rows["current_boot"],))
            connection.execute("UPDATE receiver_meta SET value=? WHERE key='current_boot'", (boot,))
            connection.execute("UPDATE receiver_meta SET value=? WHERE key='journal_generation'", (str(generation),))
            connection.execute("UPDATE receiver_meta SET value=? WHERE key='old_boot_isolation_ref'",
                               (old_boot_isolation_ref,))

    @staticmethod
    def meta(connection) -> dict[str, str]:
        values = dict(connection.execute("SELECT key,value FROM receiver_meta"))
        if not values:
            raise ReceiverRejected("receiver boot is not claimed")
        return values


class ReceiverService:
    PATHS: ClassVar[dict[str, str]] = {
        "delivery.prepare": "/v1/delivery/prepare",
        "delivery.dispatch": "/v1/delivery/dispatch",
        "delivery.readback": "/v1/delivery/readback",
        "delivery.recover": "/v1/delivery/recover",
    }

    def __init__(self, config: ReceiverRuntimeConfig, node_signing_key: SigningKey,
                 *, authorize_current: Callable[[DeliveryAdmission], bool]):
        config.validate()
        from runtime.receiver_crypto import public_key
        if public_key(node_signing_key) != config.binding.node_public_key:
            raise ReceiverRejected("Node receipt signing key differs from endpoint registration")
        if not callable(authorize_current):
            raise ReceiverRejected("current authority callback is required")
        self.config = config
        self.binding = config.binding
        self.node_signing_key = node_signing_key
        self.authorize_current = authorize_current
        self.ledger = ReceiverLedger(config.ledger_path)

    def claim_boot(self, boot: str, generation: int, *, old_boot_isolation_ref: str | None = None):
        if (boot != self.config.expected_boot_incarnation
                or generation != self.config.journal_generation
                or old_boot_isolation_ref != self.config.old_boot_isolation_ref):
            raise ReceiverRejected("boot claim differs from receiver startup configuration")
        self.ledger.claim_boot(boot, generation, old_boot_isolation_ref=old_boot_isolation_ref)

    def _typed_body(self, request: SignedRequest):
        models = {
            "delivery.prepare": PrepareBody,
            "delivery.dispatch": DispatchBody,
            "delivery.readback": ReadbackBody,
            "delivery.recover": RecoveryBody,
        }
        return models[request.admission.purpose].model_validate(request.body, strict=True)

    def _verify(self, request: SignedRequest):
        admission = request.admission
        body = self._typed_body(request)
        registration = self.binding.registration
        now = datetime.now(UTC)
        expected = (
            registration.tenant_id, registration.authority_id, registration.authority_incarnation,
            registration.endpoint_id, registration.node_id, registration.machine_id,
            registration.scope_id, registration.agent_slot_id, registration.runtime_id,
            registration.runtime_revision,
        )
        actual = (
            admission.tenant_id, admission.authority_id, admission.authority_incarnation,
            admission.endpoint_id, admission.node_id, admission.machine_id,
            admission.scope_id, admission.agent_slot_id, admission.runtime_id,
            admission.runtime_revision,
        )
        if (actual != expected or admission.endpoint_revision != registration.endpoint_revision
                or admission.path != self.PATHS[admission.purpose]
                or admission.authority_key_id != self.config.authority_key_id
                or admission.authority_key_revision != self.config.authority_key_revision
                or admission.body_sha256 != sha256(body)
                or admission.deadline <= now
                or registration.expires_at <= now
                or admission.issued_at > now + timedelta(seconds=self.config.clock_skew_seconds)):
            raise ReceiverRejected("delivery admission context rejected")
        verify(self.config.authority_public_key, request.signature, admission)
        if isinstance(body, PrepareBody) and (
            admission.envelope_digest != sha256(body.envelope)
            or admission.invocation_digest != sha256(body.invocation)
            or admission.selection_digest != sha256(body.selection)
        ):
            raise ReceiverRejected("prepare canonical envelope/invocation/selection digest rejected")
        return body, sha256({"admission": admission.model_dump(mode="json"), "body": body.model_dump(mode="json")})

    @staticmethod
    def _identity(admission: DeliveryAdmission) -> dict[str, Any]:
        fields = (
            "tenant_id", "authority_id", "authority_incarnation", "message_id", "command_id",
            "operation_id", "attempt_id", "dispatch_id", "endpoint_id", "endpoint_revision",
            "runtime_id", "runtime_revision", "node_id", "machine_id", "boot_incarnation",
            "scope_id", "agent_slot_id", "accepted_revision", "accepted_state_digest",
            "envelope_digest", "selection_digest", "invocation_digest", "journal_generation",
            "deadline",
        )
        return {field: admission.model_dump(mode="json")[field] for field in fields}

    def _match_prepare(self, prepared, admission: DeliveryAdmission,
                       recovery: RecoveryBody | None = None) -> DeliveryAdmission:
        original = DeliveryAdmission.model_validate_json(prepared["admission_json"], strict=True)
        expected = self._identity(original)
        actual = self._identity(admission)
        if recovery is None:
            if actual != expected:
                raise ReceiverRejected("dispatch identity differs from prepared request")
            return original
        transitions = {
            "boot_incarnation": (recovery.old_boot_incarnation, recovery.new_boot_incarnation),
            "endpoint_revision": (recovery.old_endpoint_revision, recovery.new_endpoint_revision),
            "runtime_revision": (recovery.old_runtime_revision, recovery.new_runtime_revision),
            "journal_generation": (original.journal_generation, recovery.journal_generation),
        }
        for field, (old, new) in transitions.items():
            if expected[field] != old or actual[field] != new:
                raise ReceiverRejected("boot recovery identity transition rejected")
            expected[field] = new
        if actual != expected:
            raise ReceiverRejected("boot recovery identity differs from prepared request")
        return original

    def _receipt(self, request: SignedRequest, request_hash: str, state: str,
                 evidence: dict[str, Any] | None = None, *,
                 identity_admission: DeliveryAdmission | None = None,
                 target_request_id: str | None = None) -> SignedReceipt:
        admission = request.admission
        identity = identity_admission or admission
        registration = self.binding.registration
        receipt = ReceiverReceipt(
            receipt_id=f"receiver:{admission.request_id}:{state}", request_id=admission.request_id,
            challenge_nonce=admission.nonce, purpose=admission.purpose, state=state,
            target_request_id=target_request_id or admission.request_id,
            readback_request_id=admission.request_id if admission.purpose == "delivery.readback" else None,
            tenant_id=identity.tenant_id, authority_id=identity.authority_id,
            authority_incarnation=identity.authority_incarnation,
            message_id=identity.message_id, command_id=identity.command_id,
            operation_id=identity.operation_id, attempt_id=identity.attempt_id,
            dispatch_id=identity.dispatch_id, endpoint_id=identity.endpoint_id,
            endpoint_revision=identity.endpoint_revision, runtime_id=identity.runtime_id,
            runtime_revision=identity.runtime_revision, node_id=identity.node_id,
            node_binding_revision=registration.node_binding_revision,
            machine_id=identity.machine_id, boot_incarnation=identity.boot_incarnation,
            scope_id=identity.scope_id, agent_slot_id=identity.agent_slot_id,
            accepted_revision=identity.accepted_revision,
            accepted_state_digest=identity.accepted_state_digest,
            envelope_digest=identity.envelope_digest,
            selection_digest=identity.selection_digest,
            invocation_digest=identity.invocation_digest,
            journal_generation=identity.journal_generation, request_sha256=request_hash,
            evidence=evidence or {}, observed_at=datetime.now(UTC),
        )
        return SignedReceipt(receipt=receipt, node_key_id=self.binding.node_key_id,
                             signature=sign(self.node_signing_key, receipt))

    @staticmethod
    def _stored(row: sqlite3.Row) -> SignedReceipt:
        return SignedReceipt.model_validate_json(row["receipt_json"], strict=True)

    def _identity_fence(self, connection, admission: DeliveryAdmission):
        rows = connection.execute(
            "SELECT attempt_id FROM receiver_requests WHERE operation_id=? AND dispatch_id=?",
            (admission.operation_id, admission.dispatch_id),
        ).fetchall()
        if any(row[0] != admission.attempt_id for row in rows):
            raise ReceiverRejected("attempt or dispatch identity replacement rejected")

    def _existing(self, connection, request: SignedRequest, request_hash: str):
        row = connection.execute("SELECT * FROM receiver_requests WHERE request_id=?",
                                 (request.admission.request_id,)).fetchone()
        if row is None:
            return None
        admission_json = canonical(request.admission).decode()
        body_json = canonical(request.body).decode()
        signed_json = canonical(request).decode()
        if (row["canonical_hash"] != request_hash
                or row["body_sha256"] != request.admission.body_sha256
                or row["admission_sha256"] != sha256(request.admission)
                or row["signed_request_sha256"] != sha256(request)
                or row["signed_request_json"] != signed_json
                or row["admission_json"] != admission_json
                or row["body_json"] != body_json
                or row["authority_signature"] != request.signature):
            raise ReceiverRejected("request identity replay changed")
        return row

    def _insert(self, connection, request: SignedRequest, request_hash: str,
                state: str, marker: bool, evidence=None, *,
                prepare_identity: dict[str, Any] | None = None,
                identity_admission: DeliveryAdmission | None = None,
                target_request_id: str | None = None,
                execution_lease_id: str = "") -> SignedReceipt:
        receipt = self._receipt(
            request, request_hash, state, evidence, identity_admission=identity_admission,
            target_request_id=target_request_id,
        )
        now = datetime.now(UTC).isoformat()
        process_start = _process_start(os.getpid()) if execution_lease_id else ""
        if execution_lease_id and not process_start:
            raise ReceiverRejected("receiver execution process identity is unavailable")
        try:
            connection.execute(
                "INSERT INTO receiver_requests(request_id,nonce,canonical_hash,purpose,body_sha256,"
                "admission_sha256,signed_request_sha256,"
                "signed_request_json,admission_json,body_json,authority_signature,prepare_identity_json,"
                "operation_id,attempt_id,"
                "dispatch_id,admitted_boot,journal_generation,state,local_dispatch_marker,receipt_json,"
                "receipt_signature,receipt_sha256,signed_receipt_sha256,execution_lease_id,"
                "execution_lease_expires_at,execution_process_id,execution_process_start,"
                "created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (request.admission.request_id, request.admission.nonce, request_hash,
                 request.admission.purpose, request.admission.body_sha256,
                 sha256(request.admission), sha256(request),
                 canonical(request).decode(), canonical(request.admission).decode(),
                 canonical(request.body).decode(), request.signature,
                 canonical(prepare_identity or self._identity(identity_admission or request.admission)).decode(),
                 request.admission.operation_id, request.admission.attempt_id,
                 request.admission.dispatch_id, request.admission.boot_incarnation,
                 request.admission.journal_generation, state, int(marker), receipt.model_dump_json(),
                 receipt.signature, sha256(receipt.receipt), sha256(receipt), execution_lease_id,
                 request.admission.deadline.isoformat() if execution_lease_id else "",
                 os.getpid() if execution_lease_id else 0,
                 process_start, now, now),
            )
        except sqlite3.IntegrityError:
            raise ReceiverRejected("request nonce or logical identity replay rejected") from None
        return receipt

    def _check_current_boot(self, connection, admission: DeliveryAdmission):
        meta = self.ledger.meta(connection)
        if (meta["current_boot"] != admission.boot_incarnation
                or int(meta["journal_generation"]) != admission.journal_generation):
            raise ReceiverRejected("receiver boot or journal generation changed")
        return meta

    def prepare(self, request: SignedRequest) -> SignedReceipt:
        _, request_hash = self._verify(request)
        with self.ledger.transaction() as connection:
            self._check_current_boot(connection, request.admission)
            self._identity_fence(connection, request.admission)
            existing = self._existing(connection, request, request_hash)
            if existing:
                return self._stored(existing)
            marked = connection.execute(
                "SELECT 1 FROM receiver_requests WHERE operation_id=? AND dispatch_id=? "
                "AND local_dispatch_marker=1",
                (request.admission.operation_id, request.admission.dispatch_id),
            ).fetchone()
            if marked:
                raise ReceiverRejected("dispatch is already marked")
            return self._insert(
                connection, request, request_hash, "prepared", False,
                prepare_identity=self._identity(request.admission),
            )

    def _prepared(self, connection, admission: DeliveryAdmission, prepare_request_id: str):
        row = connection.execute("SELECT * FROM receiver_requests WHERE request_id=? AND purpose='delivery.prepare'",
                                 (prepare_request_id,)).fetchone()
        if (row is None or row["operation_id"] != admission.operation_id
                or row["attempt_id"] != admission.attempt_id or row["dispatch_id"] != admission.dispatch_id
                or row["state"] != "prepared" or row["local_dispatch_marker"]):
            raise ReceiverRejected("matching unmarked prepared request is unavailable")
        return row

    def _update(self, connection, request: SignedRequest, request_hash: str,
                state: str, evidence=None, *, identity_admission=None,
                target_request_id=None) -> SignedReceipt:
        receipt = self._receipt(
            request, request_hash, state, evidence, identity_admission=identity_admission,
            target_request_id=target_request_id,
        )
        cursor = connection.execute(
            "UPDATE receiver_requests SET state=?,receipt_json=?,receipt_signature=?,"
            "receipt_sha256=?,signed_receipt_sha256=?,execution_lease_id='',"
            "execution_lease_expires_at='',execution_process_id=0,"
            "execution_process_start='',updated_at=? "
            "WHERE request_id=? AND local_dispatch_marker=1",
            (state, receipt.model_dump_json(), receipt.signature, sha256(receipt.receipt),
             sha256(receipt), datetime.now(UTC).isoformat(),
             request.admission.request_id),
        )
        if cursor.rowcount != 1:
            raise ReceiverRejected("dispatch marker disappeared")
        return receipt

    @staticmethod
    def _execution_lease_active(row: sqlite3.Row) -> bool:
        lease_id = row["execution_lease_id"]
        expires = row["execution_lease_expires_at"]
        process_id = row["execution_process_id"]
        process_start = row["execution_process_start"]
        if (not lease_id or not expires or not process_id or not process_start
                or datetime.fromisoformat(expires) <= datetime.now(UTC)):
            return False
        if process_id == os.getpid():
            with _ACTIVE_EXECUTION_LEASES_LOCK:
                return lease_id in _ACTIVE_EXECUTION_LEASES and process_start == _process_start(process_id)
        return process_start == _process_start(process_id)

    def _abandon_execution(self, request: SignedRequest, request_hash: str,
                           execution_lease_id: str, error: BaseException) -> None:
        with (suppress(ReceiverRejected, sqlite3.Error, OSError, ValueError),
              self.ledger.transaction() as connection):
            row = self._existing(connection, request, request_hash)
            if (row is not None and row["state"] == "runtime_dispatched"
                    and row["execution_lease_id"] == execution_lease_id):
                self._update(
                    connection, request, request_hash, "uncertain",
                    {"reason": "execution_aborted_after_local_marker",
                     "error_type": type(error).__name__},
                )

    def _invoke_with_fence(self, request: SignedRequest, request_hash: str, execution_lease_id: str,
                           invoke: Callable[[DeliveryAdmission], dict[str, Any]]) -> SignedReceipt:
        # This BEGIN IMMEDIATE is the boot-writer fence. It is held from current
        # authorization/deadline checks through native dispatch and result write.
        with self.ledger.transaction() as connection:
            row = self._existing(connection, request, request_hash)
            if (row is None or row["state"] != "runtime_dispatched"
                    or not row["local_dispatch_marker"]
                    or row["execution_lease_id"] != execution_lease_id):
                raise ReceiverRejected("durable local dispatch marker is unavailable")
            meta = self.ledger.meta(connection)
            if (meta["current_boot"] != request.admission.boot_incarnation
                    or int(meta["journal_generation"]) != request.admission.journal_generation):
                return self._update(connection, request, request_hash, "blocked",
                                    {"reason": "boot_or_journal_generation_changed"})
            now = datetime.now(UTC)
            registration = self.binding.registration
            if request.admission.deadline <= now or registration.expires_at <= now:
                return self._update(connection, request, request_hash, "blocked",
                                    {"reason": "deadline_or_registration_expired"})
            try:
                current = self.authorize_current(request.admission)
            except Exception as error:  # noqa: BLE001 -- failure is recorded without invoking
                return self._update(connection, request, request_hash, "blocked",
                                    {"reason": "current_authority_unavailable",
                                     "error_type": type(error).__name__})
            now = datetime.now(UTC)
            if current is not True or request.admission.deadline <= now or registration.expires_at <= now:
                return self._update(connection, request, request_hash, "blocked",
                                    {"reason": "current_authority_or_time_rejected"})
            try:
                evidence = invoke(request.admission)
            except Exception as error:  # noqa: BLE001 -- any post-marker native failure is uncertain
                return self._update(connection, request, request_hash, "uncertain",
                                    {"error_type": type(error).__name__})
            try:
                connection.execute(
                    "INSERT INTO native_calls(dispatch_id,request_id,called_at) VALUES (?,?,?)",
                    (request.admission.dispatch_id, request.admission.request_id,
                     datetime.now(UTC).isoformat()),
                )
            except sqlite3.IntegrityError:
                return self._update(connection, request, request_hash, "uncertain",
                                    {"reason": "native_call_identity_already_recorded"})
            return self._update(connection, request, request_hash, "runtime_acknowledged", evidence)

    def dispatch(self, request: SignedRequest, invoke: Callable[[DeliveryAdmission], dict[str, Any]],
                 *, after_marker: Callable[[], None] | None = None) -> SignedReceipt:
        body, request_hash = self._verify(request)
        if not isinstance(body, DispatchBody):
            raise ReceiverRejected("dispatch body rejected")
        execution_lease_id = secrets.token_hex(32)
        with _active_execution_lease(execution_lease_id):
            with self.ledger.transaction() as connection:
                self._check_current_boot(connection, request.admission)
                self._identity_fence(connection, request.admission)
                existing = self._existing(connection, request, request_hash)
                if existing:
                    if existing["state"] == "runtime_dispatched":
                        if self._execution_lease_active(existing):
                            return self._stored(existing)
                        return self._update(
                            connection, request, request_hash, "uncertain",
                            {"reason": "inactive_execution_lease_after_local_marker"},
                        )
                    return self._stored(existing)
                prepared = self._prepared(connection, request.admission, body.prepare_request_id)
                self._match_prepare(prepared, request.admission)
                self._insert(
                    connection, request, request_hash, "runtime_dispatched", True,
                    prepare_identity=json.loads(prepared["prepare_identity_json"]),
                    execution_lease_id=execution_lease_id,
                )
            if after_marker:
                try:
                    after_marker()
                except BaseException as error:
                    self._abandon_execution(request, request_hash, execution_lease_id, error)
                    raise
            try:
                return self._invoke_with_fence(request, request_hash, execution_lease_id, invoke)
            except BaseException as error:
                self._abandon_execution(request, request_hash, execution_lease_id, error)
                raise

    def recover(self, request: SignedRequest, invoke: Callable[[DeliveryAdmission], dict[str, Any]],
                *, after_marker: Callable[[], None] | None = None) -> SignedReceipt:
        body, request_hash = self._verify(request)
        if not isinstance(body, RecoveryBody):
            raise ReceiverRejected("recovery body rejected")
        execution_lease_id = secrets.token_hex(32)
        with _active_execution_lease(execution_lease_id):
            with self.ledger.transaction() as connection:
                meta = self._check_current_boot(connection, request.admission)
                self._identity_fence(connection, request.admission)
                existing = self._existing(connection, request, request_hash)
                if existing:
                    if existing["state"] == "runtime_dispatched":
                        if self._execution_lease_active(existing):
                            return self._stored(existing)
                        return self._update(
                            connection, request, request_hash, "uncertain",
                            {"reason": "inactive_execution_lease_after_local_marker"},
                        )
                    return self._stored(existing)
                if (body.old_boot_incarnation != meta["previous_boot"]
                        or body.new_boot_incarnation != meta["current_boot"]
                        or body.journal_generation != int(meta["journal_generation"])
                        or body.old_boot_isolation_ref != meta["old_boot_isolation_ref"]):
                    raise ReceiverRejected("boot-recovery isolation or generation rejected")
                prepared = self._prepared(connection, request.admission, body.prepare_request_id)
                if prepared["admitted_boot"] != body.old_boot_incarnation:
                    raise ReceiverRejected("recovery old boot does not own preparation")
                self._match_prepare(prepared, request.admission, body)
                marked = connection.execute(
                    "SELECT 1 FROM receiver_requests WHERE operation_id=? AND dispatch_id=? "
                    "AND local_dispatch_marker=1",
                    (request.admission.operation_id, request.admission.dispatch_id),
                ).fetchone()
                if marked:
                    raise ReceiverRejected("marked dispatch cannot be recovered by reinvocation")
                self._insert(
                    connection, request, request_hash, "runtime_dispatched", True,
                    {"old_boot": body.old_boot_incarnation, "new_boot": body.new_boot_incarnation},
                    prepare_identity=json.loads(prepared["prepare_identity_json"]),
                    execution_lease_id=execution_lease_id,
                )
            if after_marker:
                try:
                    after_marker()
                except BaseException as error:
                    self._abandon_execution(request, request_hash, execution_lease_id, error)
                    raise
            try:
                return self._invoke_with_fence(request, request_hash, execution_lease_id, invoke)
            except BaseException as error:
                self._abandon_execution(request, request_hash, execution_lease_id, error)
                raise

    def readback(self, request: SignedRequest) -> SignedReceipt:
        body, request_hash = self._verify(request)
        if not isinstance(body, ReadbackBody):
            raise ReceiverRejected("readback body rejected")
        if (body.operation_id, body.dispatch_id) != (
            request.admission.operation_id, request.admission.dispatch_id,
        ):
            raise ReceiverRejected("readback body and admission identity differ")
        with self.ledger.transaction() as connection:
            self._check_current_boot(connection, request.admission)
            existing = self._existing(connection, request, request_hash)
            if existing:
                return self._stored(existing)
            target = connection.execute(
                "SELECT * FROM receiver_requests WHERE operation_id=? AND dispatch_id=? "
                "AND purpose IN ('delivery.dispatch','delivery.recover') "
                "ORDER BY updated_at DESC LIMIT 1",
                (body.operation_id, body.dispatch_id),
            ).fetchone()
            if target is None:
                raise ReceiverRejected("dispatch readback is unavailable")
            target_admission = DeliveryAdmission.model_validate_json(target["admission_json"], strict=True)
            if self._identity(target_admission) != self._identity(request.admission):
                raise ReceiverRejected("readback admission differs from stored dispatch identity")
            evidence = {"stored_state": target["state"],
                        "stored_receipt_sha256": sha256(target["receipt_json"].encode()),
                        "target_request_id": target["request_id"]}
            return self._insert(
                connection, request, request_hash, "readback", False, evidence,
                prepare_identity=json.loads(target["prepare_identity_json"]),
                identity_admission=target_admission, target_request_id=target["request_id"],
            )

    def handle(self, request: SignedRequest, invoke: Callable[[DeliveryAdmission], dict[str, Any]],
               *, after_marker=None) -> SignedReceipt:
        actions = {
            "delivery.prepare": lambda: self.prepare(request),
            "delivery.dispatch": lambda: self.dispatch(request, invoke, after_marker=after_marker),
            "delivery.readback": lambda: self.readback(request),
            "delivery.recover": lambda: self.recover(request, invoke, after_marker=after_marker),
        }
        return actions[request.admission.purpose]()
