"""Narrow host-side entry for one P1 Codex delivery operation.

The sandbox can address this socket, but never receives a user-bus socket,
Systemd command, executable path, credential, Driver instance, or shell API.
The trusted host constructs the DeliveryDispatcher and pins the run policy.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import stat
import struct
import threading
import time
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from runtime.codex_driver import AuthorizedOperation, CodexAppServerDriver
from runtime.delivery import DeliveryDispatcher
from runtime.errors import AuthorizationDenied
from runtime.models import CommandEnvelope
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.receiver_paths import (
    PathSecurityRejected,
    ensure_private_database,
    private_parent,
)
from runtime.systemd_supervisor import SystemdUserSupervisor


class HostNodeRejected(RuntimeError):
    """The host did not admit the requested operation."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CodexHostRunPolicy(_Strict):
    schema_version: Literal["acs-p1-codex-host-policy/1"] = "acs-p1-codex-host-policy/1"
    run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{7,127}$")
    tenant_id: str = Field(min_length=1, max_length=256)
    authority_id: str = Field(min_length=1, max_length=256)
    authority_incarnation: str = Field(min_length=1, max_length=256)
    scope_id: str = Field(min_length=1, max_length=256)
    agent_slot_id: str = Field(min_length=1, max_length=256)
    scope_policy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    endpoint_id: str = Field(min_length=1, max_length=256)
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    native_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    deadline: datetime

    @field_validator("deadline")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("host policy deadline must have a timezone")
        return value.astimezone(UTC)


class CodexHostRequest(_Strict):
    schema_version: Literal["acs-p1-codex-host-request/1"] = "acs-p1-codex-host-request/1"
    action: Literal["dispatch", "readback"]
    run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{7,127}$")
    tenant_id: str = Field(min_length=1, max_length=256)
    message_id: str = Field(min_length=1, max_length=256)
    command_id: str = Field(min_length=1, max_length=256)
    operation_id: str = Field(min_length=1, max_length=256)
    endpoint_id: str = Field(min_length=1, max_length=256)
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    native_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class CodexHostResult(_Strict):
    schema_version: Literal["acs-p1-codex-host-result/1"] = "acs-p1-codex-host-result/1"
    run_id: str
    tenant_id: str
    message_id: str
    command_id: str
    operation_id: str
    status: str
    attempt_id: str | None = None
    dispatch_id: str | None = None
    pg_receipts: tuple[dict, ...] = ()
    node_receipts: tuple[dict, ...] = ()
    os_observation: dict | None = None
    scene_readback: dict | None = None
    scene_readback_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


def _json_digest(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sha256_owner_file(path: Path, *, executable: bool) -> str:
    """Read only an owner-controlled, single-link regular file; never return bytes."""
    if os.name != "posix" or os.geteuid() == 0:
        raise HostNodeRejected("host artifact inspection requires a non-root POSIX owner")
    parent = None
    try:
        parent, _ = private_parent(path.parent)
        descriptor = os.open(path.name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=parent)
    except (OSError, PathSecurityRejected) as error:
        if parent is not None:
            os.close(parent)
        raise HostNodeRejected("host artifact path is unsafe") from error
    try:
        info = os.fstat(descriptor)
        mode = stat.S_IMODE(info.st_mode)
        allowed = {0o500} if executable else {0o400, 0o600}
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or mode not in allowed
        ):
            raise HostNodeRejected("host artifact identity or mode is unsafe")
        digest = hashlib.sha256()
        while block := os.read(descriptor, 1 << 20):
            digest.update(block)
        after = os.fstat(descriptor)
        current = path.stat(follow_symlinks=False)
        if (
            after.st_ino != info.st_ino
            or after.st_dev != info.st_dev
            or after.st_size != info.st_size
            or after.st_mtime_ns != info.st_mtime_ns
            or current.st_ino != info.st_ino
            or current.st_dev != info.st_dev
        ):
            raise HostNodeRejected("host artifact changed during verification")
        return digest.hexdigest()
    finally:
        os.close(descriptor)
        os.close(parent)


class CodexHostNodeEndpoint:
    """Host-only Domain/Node composition with a durable one-operation run fence."""

    def __init__(
        self,
        policy: CodexHostRunPolicy,
        dispatcher: DeliveryDispatcher,
        ledger_path: Path,
        *,
        native_path: Path,
        config_path: Path,
        fixture_mode: bool = False,
    ) -> None:
        self.policy = policy
        self.dispatcher = dispatcher
        self.ledger_path = Path(ledger_path)
        self.native_path = Path(native_path)
        self.config_path = Path(config_path)
        self.fixture_mode = fixture_mode
        self._lock = threading.RLock()
        if os.name != "posix" or os.geteuid() == 0:
            raise HostNodeRejected("host Node endpoint requires a non-root POSIX owner")
        endpoint = dispatcher.service.endpoints.get(policy.endpoint_id)
        if endpoint is None or endpoint.driver is None:
            raise HostNodeRejected("host-pinned native endpoint is unavailable")
        if not fixture_mode:
            adapter = endpoint.driver
            if (
                not isinstance(adapter, NativeDeliveryAdapter)
                or not isinstance(adapter.driver, CodexAppServerDriver)
                or not isinstance(adapter.driver.supervisor, SystemdUserSupervisor)
            ):
                raise HostNodeRejected("host endpoint requires Codex with host Systemd supervision")
            profile = adapter.driver.profile
            if (
                Path(profile.executable) != self.native_path
                or Path(profile.codex_home) / "config.toml" != self.config_path
                or profile.executable_sha256 != policy.native_sha256
                or profile.config_sha256 != policy.config_sha256
            ):
                raise HostNodeRejected("host Codex profile differs from pinned native artifacts")
        try:
            ensure_private_database(self.ledger_path)
        except PathSecurityRejected as error:
            raise HostNodeRejected("host ledger path is unsafe") from error
        with closing(self._connect()) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS codex_host_runs ("
                "run_id TEXT PRIMARY KEY, identity_json TEXT NOT NULL,"
                "policy_sha256 TEXT NOT NULL,"
                "created_at TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS codex_host_boot ("
                "run_id TEXT PRIMARY KEY, state TEXT NOT NULL,"
                "proof_json TEXT, created_at TEXT NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.ledger_path, timeout=10, isolation_level=None)

    def _verify_artifacts(self) -> None:
        if _sha256_owner_file(self.native_path, executable=True) != self.policy.native_sha256:
            raise HostNodeRejected("pinned native binary digest changed")
        if _sha256_owner_file(self.config_path, executable=False) != self.policy.config_sha256:
            raise HostNodeRejected("pinned native config digest changed")

    def _preflight(self, request: CodexHostRequest) -> dict[str, str]:
        policy = self.policy
        if any(
            (
                request.run_id != policy.run_id,
                request.tenant_id != policy.tenant_id,
                request.endpoint_id != policy.endpoint_id,
                request.source_commit != policy.source_commit,
                request.native_sha256 != policy.native_sha256,
                request.config_sha256 != policy.config_sha256,
            )
        ):
            raise HostNodeRejected("request differs from host-pinned run policy")
        if request.action == "dispatch" and datetime.now(UTC) >= policy.deadline:
            raise HostNodeRejected("host run deadline expired")
        authority = self.dispatcher.service.authority
        if authority.tenant_id != policy.tenant_id:
            raise HostNodeRejected("host authority tenant differs")
        if (
            authority.context.authority_id != policy.authority_id
            or authority.context.authority_incarnation != policy.authority_incarnation
        ):
            raise HostNodeRejected("host authority identity differs from pinned run policy")
        with authority._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT command_id,operation_id,endpoint_id,command_json,packet_json,"
                "deadline,clock_timestamp() FROM delivery_messages "
                "WHERE tenant_id=%s AND message_id=%s",
                (request.tenant_id, request.message_id),
            )
            row = cursor.fetchone()
        if row is None:
            raise HostNodeRejected("committed delivery message is unavailable")
        command_id, operation_id, endpoint_id, command, packet, deadline, db_now = row
        if (
            command_id != request.command_id
            or operation_id != request.operation_id
            or endpoint_id != policy.endpoint_id
            or command.get("command_id") != request.command_id
            or command.get("correlation_id") != policy.run_id
            or command.get("authority_id") != policy.authority_id
            or command.get("authority_incarnation") != policy.authority_incarnation
            or command.get("target_kind") != "message"
            or command.get("target_id") != request.message_id
            or packet.get("activation") != "invoke"
            or packet.get("source_baseline") != policy.source_commit
            or packet.get("target_scope_id") != policy.scope_id
            or packet.get("target_agent_slot_id") != policy.agent_slot_id
            or (request.action == "dispatch" and deadline <= db_now)
            or (request.action == "dispatch" and policy.deadline <= db_now)
        ):
            raise HostNodeRejected("committed command, attempt policy, or deadline differs")
        if request.action == "dispatch":
            self._verify_artifacts()
        return {
            "tenant_id": request.tenant_id,
            "message_id": request.message_id,
            "operation_id": request.operation_id,
        }

    def _bind_once(self, request: CodexHostRequest) -> None:
        policy_sha256 = hashlib.sha256(self.policy.model_dump_json().encode()).hexdigest()
        identity = json.dumps(
            {
                "tenant_id": request.tenant_id,
                "message_id": request.message_id,
                "command_id": request.command_id,
                "operation_id": request.operation_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT identity_json,policy_sha256 FROM codex_host_runs WHERE run_id=?",
                (request.run_id,),
            ).fetchone()
            if row is None:
                if request.action != "dispatch":
                    raise HostNodeRejected("readback has no previously bound host operation")
                connection.execute(
                    "INSERT INTO codex_host_runs VALUES (?,?,?,?)",
                    (request.run_id, identity, policy_sha256, datetime.now(UTC).isoformat()),
                )
            elif row != (identity, policy_sha256):
                raise HostNodeRejected("run is already bound to another command or operation")
            connection.commit()

    def _host_driver(self):
        endpoint = self.dispatcher.service.endpoints.get(self.policy.endpoint_id)
        driver = endpoint.driver if endpoint is not None else None
        if driver is None:
            raise HostNodeRejected("host native Driver is unavailable")
        if self.fixture_mode:
            return driver
        if not isinstance(driver, NativeDeliveryAdapter):
            raise HostNodeRejected("host native adapter changed")
        return driver.driver

    @contextmanager
    def _spawn_authority_fence(self, request: CodexHostRequest, operation: AuthorizedOperation):
        """Hold the current Domain/Scope/Slot rows through the actual OS spawn."""
        authority = self.dispatcher.service.authority
        context = authority.context
        if (
            operation.operation_id != self.policy.run_id + "-spawn"
            or operation.command_id != self.policy.run_id + "-command-spawn"
            or operation.message_id != self.policy.run_id + "-message-spawn"
            or operation.grant_ref != context.grant_ref
            or operation.deadline > self.policy.deadline
        ):
            raise HostNodeRejected("host spawn operation differs from the current run")
        operation.validate()
        with authority._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT command_json FROM delivery_messages WHERE tenant_id=%s "
                "AND message_id=%s AND operation_id=%s AND command_id=%s",
                (request.tenant_id, request.message_id, request.operation_id, request.command_id),
            )
            stored = cursor.fetchone()
            if stored is None:
                raise HostNodeRejected("host spawn has no committed Domain command")
            command = CommandEnvelope.model_validate_json(
                json.dumps(stored[0], default=str),
                strict=True,
            )
            if (
                command.command_id != request.command_id
                or command.target_id != request.message_id
                or command.target_kind != "message"
                or command.command_type != "message.send"
                or command.grant_ref != operation.grant_ref
                or command.authority_id != self.policy.authority_id
                or command.authority_incarnation != self.policy.authority_incarnation
                or command.deadline < operation.deadline
            ):
                raise HostNodeRejected("host spawn command lineage differs")
            try:
                authority._authorize(command, cursor, "message.send", self.policy.scope_id)
                authority._authorize(command, cursor, "runtime.invoke", self.policy.scope_id)
            except AuthorizationDenied as error:
                raise HostNodeRejected("host spawn Grant/Scope/Authority is not current") from error
            cursor.execute(
                "SELECT expires_at,revoked_at,permissions,clock_timestamp() FROM grants "
                "WHERE tenant_id=%s AND grant_ref=%s FOR UPDATE",
                (self.policy.tenant_id, operation.grant_ref),
            )
            grant = cursor.fetchone()
            if (
                grant is None
                or grant[1] is not None
                or grant[0] <= grant[3]
                or not {"message.send", "runtime.invoke"}.issubset(set(grant[2]))
            ):
                raise HostNodeRejected("host spawn current Grant permissions or deadline changed")
            cursor.execute(
                "SELECT packet_json,deadline,clock_timestamp() FROM delivery_messages "
                "WHERE tenant_id=%s AND message_id=%s AND operation_id=%s "
                "AND command_id=%s FOR UPDATE",
                (request.tenant_id, request.message_id, request.operation_id, request.command_id),
            )
            message = cursor.fetchone()
            if message is None:
                raise HostNodeRejected("host spawn committed message disappeared")
            packet, message_deadline, db_now = message
            if (
                message_deadline <= db_now
                or self.policy.deadline <= db_now
                or packet.get("activation") != "invoke"
                or packet.get("source_baseline") != self.policy.source_commit
                or packet.get("target_scope_id") != self.policy.scope_id
                or packet.get("target_agent_slot_id") != self.policy.agent_slot_id
            ):
                raise HostNodeRejected("host spawn packet identity or final deadline changed")
            cursor.execute(
                "SELECT scope_id,agent_slot_id,execution_status FROM work_items "
                "WHERE tenant_id=%s AND work_item_id=%s FOR UPDATE",
                (self.policy.tenant_id, packet["work_item_id"]),
            )
            work = cursor.fetchone()
            cursor.execute(
                "SELECT status FROM agent_slots WHERE tenant_id=%s AND scope_id=%s "
                "AND agent_slot_id=%s FOR UPDATE",
                (self.policy.tenant_id, self.policy.scope_id, self.policy.agent_slot_id),
            )
            slot = cursor.fetchone()
            cursor.execute(
                "SELECT policy,status FROM scopes WHERE tenant_id=%s AND scope_id=%s FOR UPDATE",
                (self.policy.tenant_id, self.policy.scope_id),
            )
            scope = cursor.fetchone()
            if (
                work is None
                or work[0:2] != (self.policy.scope_id, self.policy.agent_slot_id)
                or work[2] in {"blocked", "failed", "cancelled"}
                or slot != ("active",)
                or scope is None
                or scope[1] != "active"
                or _json_digest(scope[0]) != self.policy.scope_policy_sha256
            ):
                raise HostNodeRejected("host spawn WorkItem/AgentSlot/Policy is not current")
            # The enclosing PostgreSQL transaction holds all current rows until
            # the Systemd unit has been observed. Revocation cannot pass this fence.
            yield (
                cursor,
                min(
                    self.policy.deadline,
                    operation.deadline,
                    command.deadline,
                    message_deadline,
                    grant[0],
                ),
            )

    def start_native(self, request: CodexHostRequest, operation: AuthorizedOperation) -> dict:
        """Trusted host caller only. The socket schema cannot name this action."""
        if request.action != "dispatch":
            raise HostNodeRejected("host bootstrap requires the committed dispatch identity")
        with self._lock:
            self._preflight(request)
            with self._spawn_authority_fence(request, operation) as (cursor, final_deadline):
                return self._start_native_admitted(request, operation, cursor, final_deadline)

    def _start_native_admitted(
        self,
        request: CodexHostRequest,
        operation: AuthorizedOperation,
        cursor,
        final_deadline: datetime,
    ) -> dict:
        self._bind_once(request)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT state FROM codex_host_boot WHERE run_id=?", (request.run_id,)
            ).fetchone()
            if row is not None:
                raise HostNodeRejected("host native start already attempted; inspect original")
            connection.execute(
                "INSERT INTO codex_host_boot VALUES (?,'intent',NULL,?)",
                (request.run_id, datetime.now(UTC).isoformat()),
            )
            connection.commit()
        driver = self._host_driver()
        try:
            driver.spawn(operation)
            owned = getattr(driver, "owned", None)
            supervisor = getattr(driver, "supervisor", None)
            if owned is None or supervisor is None:
                raise HostNodeRejected("host native spawn has no owned Systemd process")
            proof = supervisor.inspect(owned)
            if (
                proof.get("verified") is not True
                or not proof.get("remaining_pids")
                or proof.get("backend") != "systemd-user-transient-service"
                or self.policy.run_id not in proof.get("unit", "")
            ):
                raise HostNodeRejected("host native process tree was not positively observed")
            cursor.execute("SELECT clock_timestamp()")
            if cursor.fetchone()[0] >= final_deadline:
                raise HostNodeRejected("host native start exceeded the final authority deadline")
        except BaseException:
            owned = getattr(driver, "owned", None)
            supervisor = getattr(driver, "supervisor", None)
            if owned is not None and supervisor is not None:
                try:
                    supervisor.terminate_tree(owned)
                except Exception as cleanup_error:
                    raise HostNodeRejected(
                        "host native start failed and cleanup is unverified"
                    ) from cleanup_error
            raise
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE codex_host_boot SET state='started',proof_json=? "
                "WHERE run_id=? AND state='intent'",
                (json.dumps(proof, sort_keys=True), request.run_id),
            )
        return proof

    def inspect_native(self) -> dict:
        """Read-only host process-tree evidence, with no guest-selected unit/PID."""
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT state,proof_json FROM codex_host_boot WHERE run_id=?",
                (self.policy.run_id,),
            ).fetchone()
        if row is None or row[1] is None:
            raise HostNodeRejected("host native boot proof is unavailable")
        if row[0] == "stopped":
            proof = json.loads(row[1])
            if (
                proof.get("verified") is not True
                or proof.get("remaining_pids") != []
                or self.policy.run_id not in proof.get("unit", "")
            ):
                raise HostNodeRejected("host stored termination proof is incomplete")
            return proof
        if row[0] != "started":
            raise HostNodeRejected("host native boot is unresolved")
        driver = self._host_driver()
        owned = getattr(driver, "owned", None)
        supervisor = getattr(driver, "supervisor", None)
        if owned is None or supervisor is None:
            raise HostNodeRejected("host native process identity is unavailable")
        proof = supervisor.inspect(owned)
        original = json.loads(row[1])
        for field in ("unit", "containment_id", "birth_ref", "invocation_id"):
            if proof.get(field) != original.get(field):
                raise HostNodeRejected("host native process identity changed")
        return proof

    def stop_native(self) -> dict:
        """Host owner cleanup remains possible after the command deadline or Grant loss."""
        with self._lock:
            driver = self._host_driver()
            owned = getattr(driver, "owned", None)
            supervisor = getattr(driver, "supervisor", None)
            if owned is None or supervisor is None:
                raise HostNodeRejected(
                    "host native owner is unavailable; global postflight required"
                )
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT proof_json FROM codex_host_boot WHERE run_id=?",
                    (self.policy.run_id,),
                ).fetchone()
            if row is None or row[0] is None:
                raise HostNodeRejected("host native boot proof is unavailable")
            original = json.loads(row[0])
            current = supervisor.inspect(owned)
            for field in ("unit", "containment_id", "birth_ref", "invocation_id"):
                if current.get(field) != original.get(field):
                    raise HostNodeRejected("host native process identity changed")
            proof = supervisor.terminate_tree(owned)
            if proof.get("verified") is not True or proof.get("remaining_pids") != []:
                raise HostNodeRejected("host native termination lacks empty-cgroup proof")
            with closing(self._connect()) as connection:
                for field in ("unit", "containment_id", "birth_ref", "invocation_id"):
                    if proof.get(field) != original.get(field):
                        raise HostNodeRejected("host native termination identity changed")
                connection.execute(
                    "UPDATE codex_host_boot SET state='stopped',proof_json=? "
                    "WHERE run_id=? AND state IN ('intent','started')",
                    (json.dumps(proof, sort_keys=True), self.policy.run_id),
                )
            return proof

    def handle(self, request: CodexHostRequest) -> CodexHostResult:
        request = CodexHostRequest.model_validate_json(request.model_dump_json(), strict=True)
        with self._lock:
            identity = self._preflight(request)
            self._bind_once(request)
            if request.action == "dispatch":
                self.dispatcher.dispatch(identity)
            authority = self.dispatcher.service.authority
            with authority._connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    "SELECT state FROM delivery_messages WHERE tenant_id=%s AND message_id=%s "
                    "AND command_id=%s AND operation_id=%s",
                    (
                        request.tenant_id,
                        request.message_id,
                        request.command_id,
                        request.operation_id,
                    ),
                )
                state = cursor.fetchone()
                cursor.execute(
                    "SELECT attempt_id,dispatch_id FROM delivery_attempts WHERE tenant_id=%s "
                    "AND message_id=%s ORDER BY ordinal DESC LIMIT 1",
                    (request.tenant_id, request.message_id),
                )
                attempt = cursor.fetchone()
                cursor.execute(
                    "SELECT receipt_id,layer,evidence_json FROM delivery_receipts WHERE tenant_id=%s "
                    "AND message_id=%s ORDER BY observed_at,receipt_id",
                    (request.tenant_id, request.message_id),
                )
                pg_receipts = tuple(
                    {"receipt_id": row[0], "layer": row[1], "evidence": row[2]}
                    for row in cursor.fetchall()
                )
            endpoint = self.dispatcher.service.endpoints.get(self.policy.endpoint_id)
            node_receipts = ()
            if endpoint is not None and hasattr(endpoint, "journal"):
                node_receipts = tuple(
                    {
                        "receipt_id": item.receipt_id,
                        "layer": item.layer,
                        "evidence": dict(item.evidence),
                    }
                    for item in endpoint.journal.receipts(request.operation_id)
                )
            os_observation = None
            try:
                os_observation = self.inspect_native()
            except HostNodeRejected:
                pass
            return CodexHostResult(
                run_id=request.run_id,
                tenant_id=request.tenant_id,
                message_id=request.message_id,
                command_id=request.command_id,
                operation_id=request.operation_id,
                status=state[0] if state else "uncertain",
                attempt_id=attempt[0] if attempt else None,
                dispatch_id=attempt[1] if attempt else None,
                pg_receipts=pg_receipts,
                node_receipts=node_receipts,
                os_observation=os_observation,
            )


class CodexHostUnixServer:
    """One fixed-schema request per connection; host retains all privileged objects."""

    MAX_REQUEST = 8192
    MAX_RESPONSE = 262144

    def __init__(self, endpoint: CodexHostNodeEndpoint, socket_path: Path) -> None:
        if os.name != "posix" or not hasattr(socket, "SO_PEERCRED"):
            raise HostNodeRejected("Unix peer credentials are required")
        self.endpoint = endpoint
        self.socket_path = Path(socket_path)
        try:
            parent, _ = private_parent(self.socket_path.parent)
            os.close(parent)
        except PathSecurityRejected as error:
            raise HostNodeRejected("host socket parent must be owner 0700") from error
        if self.socket_path.exists() or self.socket_path.is_symlink():
            raise HostNodeRejected("host socket path already exists")
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.socket.bind(str(self.socket_path))
            os.chmod(self.socket_path, 0o600)
            self.socket.listen(8)
        except BaseException:
            self.socket.close()
            raise

    def serve_one(self, *, accept_timeout: float = 10.0) -> None:
        self.socket.settimeout(accept_timeout)
        peer, _ = self.socket.accept()
        with peer:
            try:
                _, uid, _ = struct.unpack(
                    "3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                )
                if uid != os.geteuid():
                    raise HostNodeRejected("peer UID differs from host Node owner")
                payload = bytearray()
                request_deadline = time.monotonic() + 10
                while len(payload) <= self.MAX_REQUEST:
                    remaining = request_deadline - time.monotonic()
                    if remaining <= 0:
                        raise HostNodeRejected("host request receive deadline expired")
                    peer.settimeout(remaining)
                    block = peer.recv(min(4096, self.MAX_REQUEST + 1 - len(payload)))
                    if not block:
                        break
                    payload.extend(block)
                    if b"\n" in block:
                        break
                if (
                    len(payload) > self.MAX_REQUEST
                    or payload.count(b"\n") != 1
                    or not payload.endswith(b"\n")
                ):
                    raise HostNodeRejected("host request frame is invalid or oversized")
                try:
                    request = CodexHostRequest.model_validate_json(payload[:-1], strict=True)
                except ValueError as error:
                    raise HostNodeRejected("host request schema is invalid") from error
                result = self.endpoint.handle(request)
                data = result.model_dump_json().encode() + b"\n"
                if len(data) > self.MAX_RESPONSE:
                    data = b'{"schema_version":"acs-p1-codex-host-error/1","state":"uncertain"}\n'
            except HostNodeRejected:
                data = b'{"schema_version":"acs-p1-codex-host-error/1","state":"rejected"}\n'
            except Exception:  # noqa: BLE001 -- unknown dispatch outcome is never retried here
                data = b'{"schema_version":"acs-p1-codex-host-error/1","state":"uncertain"}\n'
            try:
                peer.settimeout(2)
                peer.sendall(data)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                return

    def close(self) -> None:
        self.socket.close()
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
