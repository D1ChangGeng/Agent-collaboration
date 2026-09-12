"""POSIX owner-only local-file Human Bridge transport candidate.

The provider writes local notification envelopes and reads local manual-return
files. It does not authenticate users, grant authority, send network messages,
or advance Domain state. Those decisions remain with the trusted Surface and
the async-response/Human Bridge Domain authority.
"""
from __future__ import annotations

import ctypes
import errno
import functools
import hashlib
import json
import os
import secrets
import select
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import weakref
from collections.abc import Callable, Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

IS_POSIX = os.name == "posix"
MAX_FILE_BYTES = 65_536
HEX = frozenset("0123456789abcdef")
TERMINAL_INCIDENT_STATES = {"resolved_automatic", "resolved_manual", "expired", "cancelled"}
_PROVIDER_OPERATION_LOCK = threading.RLock()


class ProviderRejected(RuntimeError):
    pass


class ProviderConflict(ProviderRejected):
    pass


def _exclusive_operation(function):
    @functools.wraps(function)
    def guarded(*args, **kwargs):
        with _PROVIDER_OPERATION_LOCK:
            return function(*args, **kwargs)

    return guarded


def _text(value: object, field: str, maximum: int = 512) -> str:
    if (not isinstance(value, str) or not value or len(value) > maximum
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ProviderRejected(f"{field} is outside the reviewed bound")
    return value


def _digest(value: object, field: str) -> str:
    if (not isinstance(value, str) or len(value) != 64
            or any(char not in HEX for char in value)):
        raise ProviderRejected(f"{field} must be a lowercase SHA-256 digest")
    return value


def _aware(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ProviderRejected(f"{field} must include a timezone")
    return value


def _canonical(value: object) -> bytes:
    body = asdict(value) if hasattr(value, "__dataclass_fields__") else value
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         default=lambda item: item.astimezone(UTC).isoformat()).encode()
    if len(encoded) > MAX_FILE_BYTES:
        raise ProviderRejected("canonical payload exceeds the reviewed bound")
    return encoded


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def provider_attempt_id(effect_id: str) -> str:
    _text(effect_id, "effect_id")
    return "human-file:" + hashlib.sha256(effect_id.encode()).hexdigest()


@dataclass(frozen=True)
class CopyReadyEnvelope:
    incident_id: str
    request_id: str
    generation: int
    expires_at: datetime
    packet_digest: str
    artifact_digest: str

    def __post_init__(self) -> None:
        _text(self.incident_id, "incident_id")
        _text(self.request_id, "request_id")
        if type(self.generation) is not int or self.generation < 1:
            raise ProviderRejected("generation is invalid")
        _aware(self.expires_at, "expires_at")
        _digest(self.packet_digest, "packet_digest")
        _digest(self.artifact_digest, "artifact_digest")


@dataclass(frozen=True)
class NotificationIntent:
    effect_id: str
    provider_attempt_id: str
    incident_id: str
    request_id: str
    generation: int
    expires_at: datetime
    packet_digest: str
    artifact_digest: str
    envelope: CopyReadyEnvelope

    def __post_init__(self) -> None:
        _text(self.effect_id, "effect_id")
        _text(self.provider_attempt_id, "provider_attempt_id")
        _text(self.incident_id, "incident_id")
        _text(self.request_id, "request_id")
        if self.provider_attempt_id != provider_attempt_id(self.effect_id):
            raise ProviderRejected("provider attempt identity is not stable")
        if type(self.generation) is not int or self.generation < 1:
            raise ProviderRejected("generation is invalid")
        _aware(self.expires_at, "expires_at")
        _digest(self.packet_digest, "packet_digest")
        _digest(self.artifact_digest, "artifact_digest")
        if (
            self.envelope.incident_id,
            self.envelope.request_id,
            self.envelope.generation,
            self.envelope.expires_at,
            self.envelope.packet_digest,
            self.envelope.artifact_digest,
        ) != (
            self.incident_id,
            self.request_id,
            self.generation,
            self.expires_at,
            self.packet_digest,
            self.artifact_digest,
        ):
            raise ProviderRejected("copy-ready envelope identity differs")
        _canonical(self)


@dataclass(frozen=True)
class TrustedSurfaceContext:
    authenticated: bool
    tenant_id: str
    principal_ref: str
    grant_ref: str
    incident_id: str
    incident_generation: int
    incident_state: str
    expected_revision: int
    accepted_state_digest: str
    deadline: datetime

    def __post_init__(self) -> None:
        for name in ("tenant_id", "principal_ref", "grant_ref", "incident_id",
                     "incident_state"):
            _text(getattr(self, name), name)
        if type(self.authenticated) is not bool:
            raise ProviderRejected("authenticated must be boolean")
        if (type(self.incident_generation) is not int or self.incident_generation < 1
                or type(self.expected_revision) is not int or self.expected_revision < 0):
            raise ProviderRejected("trusted incident revision is invalid")
        _digest(self.accepted_state_digest, "accepted_state_digest")
        _aware(self.deadline, "deadline")


@dataclass(frozen=True)
class ManualReturn:
    schema_version: str
    packet_id: str
    tenant_id: str
    incident_id: str
    generation: int
    message_id: str
    operation_id: str
    direction: str
    expected_revision: int
    accepted_state_digest: str
    payload_digest: str
    artifact_digest: str
    expires_at: datetime

    @classmethod
    def parse(cls, data: bytes) -> ManualReturn:
        if len(data) > MAX_FILE_BYTES:
            raise ProviderRejected("manual return exceeds the reviewed bound")
        try:
            raw = json.loads(data)
            if not isinstance(raw, dict) or set(raw) != {
                "schema_version", "packet_id", "tenant_id", "incident_id", "generation",
                "message_id", "operation_id", "direction", "expected_revision",
                "accepted_state_digest", "payload_digest", "artifact_digest", "expires_at",
            }:
                raise ValueError
            raw["expires_at"] = datetime.fromisoformat(raw["expires_at"])
            value = cls(**raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            raise ProviderRejected("manual return is malformed") from None
        value.validate()
        return value

    def validate(self) -> None:
        if self.schema_version != "acs-human-bridge-manual-return/1":
            raise ProviderRejected("manual return schema is unsupported")
        for name in ("packet_id", "tenant_id", "incident_id", "message_id", "operation_id"):
            _text(getattr(self, name), name)
        if self.direction not in {"request", "response"}:
            raise ProviderRejected("manual return direction is invalid")
        if (type(self.generation) is not int or self.generation < 1
                or type(self.expected_revision) is not int or self.expected_revision < 0):
            raise ProviderRejected("manual return revision is invalid")
        for name in ("accepted_state_digest", "payload_digest", "artifact_digest"):
            _digest(getattr(self, name), name)
        _aware(self.expires_at, "expires_at")
        _canonical(self)


class _SecureLayout:
    def __init__(self, root: str | Path) -> None:
        if not IS_POSIX:
            raise ProviderRejected(
                "local Human Bridge file transport requires POSIX dirfd/NOFOLLOW semantics"
            )
        self.root = Path(root)
        if not self.root.is_absolute():
            raise ProviderRejected("provider root must be absolute")
        root_fd = self.open_root()
        try:
            for name in ("notifications", "inbox"):
                child_fd = self._open_child_dir(root_fd, name, create=True)
                os.close(child_fd)
            self._ensure_database(root_fd)
            os.fsync(root_fd)
        finally:
            os.close(root_fd)

    @staticmethod
    def _directory_ok(info: os.stat_result, *, final: bool) -> bool:
        mode = stat.S_IMODE(info.st_mode)
        if not stat.S_ISDIR(info.st_mode):
            return False
        if final:
            return info.st_uid == os.geteuid() and mode == 0o700
        if info.st_uid not in {0, os.geteuid()}:
            return False
        return not mode & 0o022 or bool(mode & stat.S_ISVTX and info.st_uid == 0)

    def open_root(self) -> int:
        parts = PurePosixPath(self.root).parts
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            for index, name in enumerate(parts[1:]):
                following = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=descriptor,
                )
                info = os.fstat(following)
                if not self._directory_ok(info, final=index == len(parts) - 2):
                    os.close(following)
                    raise ProviderRejected("provider directory ownership or mode rejected")
                os.close(descriptor)
                descriptor = following
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _open_child_dir(root_fd: int, name: str, *, create: bool) -> int:
        if create:
            try:
                os.mkdir(name, 0o700, dir_fd=root_fd)
            except FileExistsError:
                pass
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                     dir_fd=root_fd)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o700):
                raise ProviderRejected("provider child directory is not owner-only")
            return fd
        except BaseException:
            os.close(fd)
            raise

    @staticmethod
    def _file_ok(info: os.stat_result) -> bool:
        return (stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1)

    @staticmethod
    def file_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
        return (info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode), info.st_nlink)

    def _ensure_database(self, root_fd: int) -> None:
        try:
            fd = os.open(
                "provider.sqlite",
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=root_fd,
            )
        except FileExistsError:
            fd = os.open(
                "provider.sqlite", os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=root_fd,
            )
        try:
            if not self._file_ok(os.fstat(fd)):
                raise ProviderRejected("provider journal is not an owner-only regular file")
            os.fsync(fd)
        finally:
            os.close(fd)

    @contextmanager
    def child(self, name: str) -> Iterator[int]:
        root_fd = self.open_root()
        try:
            child_fd = self._open_child_dir(root_fd, name, create=False)
            try:
                yield child_fd
            finally:
                os.close(child_fd)
        finally:
            os.close(root_fd)

    def open_database_witness(self) -> int:
        root_fd = self.open_root()
        try:
            fd = os.open(
                "provider.sqlite", os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=root_fd,
            )
            if not self._file_ok(os.fstat(fd)):
                os.close(fd)
                raise ProviderRejected("provider journal changed identity or mode")
            return fd
        finally:
            os.close(root_fd)

    def check_database_path(self, witness_fd: int) -> tuple[int, int, int, int, int]:
        witness = os.fstat(witness_fd)
        if not self._file_ok(witness):
            raise ProviderRejected("provider journal witness changed identity or mode")
        path_fd = self.open_database_witness()
        try:
            path = os.fstat(path_fd)
            if self.file_identity(path) != self.file_identity(witness):
                raise ProviderRejected("provider journal path differs from held witness")
            return self.file_identity(witness)
        finally:
            os.close(path_fd)


class _HelperRow(Mapping[str, Any]):
    def __init__(self, columns: list[str], values: list[Any]) -> None:
        self.columns = columns
        self.values = values

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return self.values[key]
        return self.values[self.columns.index(key)]

    def __iter__(self) -> Iterator[str]:
        return iter(self.columns)

    def __len__(self) -> int:
        return len(self.columns)


class _HelperCursor:
    def __init__(self, columns: list[str], rows: list[list[Any]]) -> None:
        self.rows = [_HelperRow(columns, row) for row in rows]

    def fetchone(self) -> _HelperRow | None:
        return self.rows[0] if self.rows else None

    def __iter__(self) -> Iterator[_HelperRow]:
        return iter(self.rows)


class _SQLiteHelperConnection:
    """RPC lease for a SQLite connection proven inside a private helper process."""

    MAX_IPC_BYTES = 4 * 1024 * 1024

    def __init__(
        self,
        root: Path,
        expected: tuple[int, int, int, int, int],
        check_meta: bool,
        timeout_seconds: float,
    ) -> None:
        self.closed = False
        self.in_transaction = False
        self.timeout_seconds = timeout_seconds
        self._read_buffer = bytearray()
        self.process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--sqlite-helper"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            close_fds=True,
        )
        try:
            deadline = time.monotonic() + self.timeout_seconds
            self._send({
                "root": str(root), "expected": list(expected), "check_meta": check_meta,
            }, deadline)
            ready = self._receive(deadline)
            if ready.get("status") != "ready":
                raise ProviderRejected("SQLite helper returned an invalid startup response")
        except Exception as error:
            self.closed = True
            self._shutdown(force=True)
            if isinstance(error, ProviderRejected):
                raise
            raise ProviderRejected("SQLite helper startup failed") from None

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProviderRejected("SQLite helper IPC deadline exceeded")
        return remaining

    def _send(self, payload: dict[str, Any], deadline: float) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode() + b"\n"
        if len(encoded) > self.MAX_IPC_BYTES:
            raise ProviderRejected("SQLite helper request exceeds IPC bound")
        stream = self.process.stdin
        if stream is None:
            raise ProviderRejected("SQLite helper stdin is unavailable")
        descriptor = stream.fileno()
        view = memoryview(encoded)
        while view:
            _readable, writable, _exceptional = select.select(
                [], [descriptor], [], self._remaining(deadline),
            )
            if not writable:
                raise ProviderRejected("SQLite helper IPC write timed out")
            written = os.write(descriptor, view)
            if written <= 0:
                raise ProviderRejected("SQLite helper IPC write failed")
            view = view[written:]

    def _receive(self, deadline: float) -> dict[str, Any]:
        stream = self.process.stdout
        if stream is None:
            raise ProviderRejected("SQLite helper stdout is unavailable")
        descriptor = stream.fileno()
        while b"\n" not in self._read_buffer:
            readable, _writable, _exceptional = select.select(
                [descriptor], [], [], self._remaining(deadline),
            )
            if not readable:
                raise ProviderRejected("SQLite helper IPC response timed out")
            chunk = os.read(descriptor, 65_536)
            if not chunk:
                raise ProviderRejected("SQLite helper ended before a complete response")
            self._read_buffer.extend(chunk)
            if len(self._read_buffer) > self.MAX_IPC_BYTES:
                raise ProviderRejected("SQLite helper response exceeds IPC bound")
        line, _, remainder = self._read_buffer.partition(b"\n")
        self._read_buffer = bytearray(remainder)
        try:
            reply = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProviderRejected("SQLite helper returned malformed JSON") from None
        if not isinstance(reply, dict) or reply.get("status") not in {"ready", "ok", "error"}:
            raise ProviderRejected("SQLite helper returned a malformed response")
        if reply["status"] == "error":
            message = reply.get("message")
            raise ProviderRejected(message if isinstance(message, str) else "SQLite helper rejected operation")
        return reply

    def _request(self, operation: str, **payload: Any) -> dict[str, Any]:
        if self.closed:
            raise ProviderRejected("SQLite helper connection is closed")
        deadline = time.monotonic() + self.timeout_seconds
        try:
            self._send({"operation": operation, **payload}, deadline)
            reply = self._receive(deadline)
            self.in_transaction = bool(reply.get("in_transaction", self.in_transaction))
            return reply
        except Exception as error:
            self.closed = True
            self._shutdown(force=True)
            if isinstance(error, ProviderRejected):
                raise
            raise ProviderRejected("SQLite helper IPC failed") from None

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> _HelperCursor:
        reply = self._request("execute", sql=sql, parameters=list(parameters))
        return _HelperCursor(reply.get("columns", []), reply.get("rows", []))

    def executescript(self, sql: str) -> None:
        self._request("executescript", sql=sql)

    def close(self) -> None:
        if self.closed:
            return
        try:
            self._request("close")
        except ProviderRejected:
            pass
        finally:
            self.closed = True
            self._shutdown(force=False)

    def _shutdown(self, *, force: bool) -> None:
        if force and self.process.poll() is None:
            try:
                self.process.terminate()
            except (OSError, ProcessLookupError):
                pass
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except (BrokenPipeError, OSError, ValueError):
                    pass
        try:
            self.process.wait(timeout=0.25)
            return
        except (subprocess.TimeoutExpired, OSError):
            pass
        try:
            self.process.kill()
        except (OSError, ProcessLookupError):
            pass
        try:
            self.process.wait(timeout=2)
        except (subprocess.TimeoutExpired, OSError):
            pass


class LocalHumanBridgeTransport:
    SCHEMA_VERSION = "acs-human-bridge-file-provider/4"

    def __init__(
        self,
        root: str | Path,
        *,
        fault_after_publish: Callable[[], None] | None = None,
        helper_timeout_seconds: float = 5.0,
    ):
        if (isinstance(helper_timeout_seconds, bool)
                or not isinstance(helper_timeout_seconds, (int, float))
                or not 0.05 <= helper_timeout_seconds <= 30.0):
            raise ProviderRejected("SQLite helper timeout is outside the reviewed bound")
        self.layout = _SecureLayout(root)
        self.database = self.layout.root / "provider.sqlite"
        self.fault_after_publish = fault_after_publish
        self.helper_timeout_seconds = float(helper_timeout_seconds)
        self._connect_lock = threading.RLock()
        self._database_witness_fd = self.layout.open_database_witness()
        self._database_witness_identity = self.layout.file_identity(
            os.fstat(self._database_witness_fd)
        )
        self._witness_finalizer = weakref.finalize(self, os.close, self._database_witness_fd)
        with closing(self._connect(check_meta=False)) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS provider_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS notification_effects(
                    effect_id TEXT PRIMARY KEY,provider_attempt_id TEXT NOT NULL UNIQUE,
                    incident_id TEXT NOT NULL,request_id TEXT NOT NULL,generation INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,canonical_digest TEXT NOT NULL,file_digest TEXT,
                    file_dev INTEGER,file_ino INTEGER,file_uid INTEGER,file_mode INTEGER,file_nlink INTEGER,
                    intent_file_digest TEXT,intent_file_dev INTEGER,intent_file_ino INTEGER,
                    intent_file_uid INTEGER,intent_file_mode INTEGER,intent_file_nlink INTEGER,
                    intent_sidecar_digest TEXT,intent_sidecar_dev INTEGER,intent_sidecar_ino INTEGER,
                    intent_sidecar_uid INTEGER,intent_sidecar_mode INTEGER,intent_sidecar_nlink INTEGER,
                    filename TEXT NOT NULL UNIQUE,identity_filename TEXT NOT NULL UNIQUE,state TEXT NOT NULL,
                    created_at TEXT NOT NULL,updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notification_readbacks(
                    readback_id INTEGER PRIMARY KEY AUTOINCREMENT,effect_id TEXT NOT NULL,
                    file_digest TEXT NOT NULL,observed_at TEXT NOT NULL,
                    FOREIGN KEY(effect_id) REFERENCES notification_effects(effect_id)
                );
                CREATE TABLE IF NOT EXISTS manual_returns(
                    packet_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,incident_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,expected_revision INTEGER NOT NULL,
                    accepted_state_digest TEXT NOT NULL,file_digest TEXT NOT NULL,
                    canonical_digest TEXT NOT NULL,disposition TEXT NOT NULL,
                    filename TEXT NOT NULL,principal_ref TEXT NOT NULL,grant_ref TEXT NOT NULL,
                    observed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS provider_audit(
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,event_type TEXT NOT NULL,
                    object_id TEXT NOT NULL,evidence_json TEXT NOT NULL,observed_at TEXT NOT NULL
                );
                """
            )
            row = connection.execute(
                "SELECT value FROM provider_meta WHERE key='schema_version'"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO provider_meta(key,value) VALUES ('schema_version',?)",
                    (self.SCHEMA_VERSION,),
                )
            elif row[0] != self.SCHEMA_VERSION:
                raise ProviderRejected("provider journal schema is unsupported")
            witness = json.dumps(self._database_witness_identity)
            row = connection.execute(
                "SELECT value FROM provider_meta WHERE key='database_witness'"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO provider_meta(key,value) VALUES ('database_witness',?)",
                    (witness,),
                )
            elif row[0] != witness:
                raise ProviderRejected("provider journal inode differs from persistent witness")

    def close(self) -> None:
        self._witness_finalizer()

    def _connect(self, *, check_meta: bool = True) -> _SQLiteHelperConnection:
        expected = self.layout.check_database_path(self._database_witness_fd)
        connection = _SQLiteHelperConnection(
            self.layout.root, expected, check_meta, self.helper_timeout_seconds,
        )
        try:
            self.layout.check_database_path(self._database_witness_fd)
            return connection
        except BaseException:
            connection.close()
            raise

    @contextmanager
    def _transaction(self) -> Iterator[_SQLiteHelperConnection]:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                self.layout.check_database_path(self._database_witness_fd)
                connection.execute("COMMIT")
                self.layout.check_database_path(self._database_witness_fd)
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    @staticmethod
    def _notification_payload(intent: NotificationIntent) -> bytes:
        return _canonical({
            "schema_version": "acs-human-bridge-notification/1",
            "effect_id": intent.effect_id,
            "provider_attempt_id": intent.provider_attempt_id,
            "incident_id": intent.incident_id,
            "request_id": intent.request_id,
            "generation": intent.generation,
            "expires_at": intent.expires_at.astimezone(UTC).isoformat(),
            "packet_digest": intent.packet_digest,
            "artifact_digest": intent.artifact_digest,
            "copy_ready_envelope": {
                **asdict(intent.envelope),
                "expires_at": intent.envelope.expires_at.astimezone(UTC).isoformat(),
            },
        })

    @staticmethod
    def _filename(effect_id: str) -> str:
        return "notification-" + hashlib.sha256(effect_id.encode()).hexdigest() + ".json"

    @staticmethod
    def _identity_filename(effect_id: str) -> str:
        return ".identity-" + hashlib.sha256(effect_id.encode()).hexdigest() + ".json"

    @staticmethod
    def _identity_payload(
        intent: NotificationIntent,
        filename: str,
        file_digest: str,
        identity: tuple[int, int, int, int, int],
    ) -> bytes:
        return _canonical({
            "schema_version": "acs-human-bridge-notification-identity/1",
            "effect_id": intent.effect_id,
            "provider_attempt_id": intent.provider_attempt_id,
            "canonical_digest": _sha256(_canonical(intent)),
            "filename": filename,
            "file_digest": file_digest,
            "file_identity": {
                "dev": identity[0], "ino": identity[1], "uid": identity[2],
                "mode": identity[3], "nlink": identity[4],
            },
        })

    @staticmethod
    def _rename_noreplace(directory_fd: int, source: str, target: str) -> None:
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise ProviderRejected("atomic rename without replacement is unavailable")
        renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                              ctypes.c_char_p, ctypes.c_uint]
        renameat2.restype = ctypes.c_int
        if renameat2(directory_fd, source.encode(), directory_fd, target.encode(), 1) != 0:
            code = ctypes.get_errno()
            if code == errno.EEXIST:
                raise FileExistsError(target)
            raise ProviderRejected("atomic notification rename failed") from OSError(code, os.strerror(code))

    @staticmethod
    def _read_file(
        directory_fd: int, filename: str,
    ) -> tuple[bytes, tuple[int, int, int, int, int]]:
        _text(filename, "filename", 256)
        if filename != Path(filename).name:
            raise ProviderRejected("filename traversal rejected")
        try:
            fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=directory_fd)
        except OSError:
            raise ProviderRejected("provider file open rejected") from None
        try:
            info = os.fstat(fd)
            if not _SecureLayout._file_ok(info) or info.st_size > MAX_FILE_BYTES:
                raise ProviderRejected("provider file identity, mode, or size rejected")
            chunks = bytearray()
            while len(chunks) <= MAX_FILE_BYTES:
                piece = os.read(fd, min(65_536, MAX_FILE_BYTES + 1 - len(chunks)))
                if not piece:
                    break
                chunks.extend(piece)
            if len(chunks) > MAX_FILE_BYTES:
                raise ProviderRejected("provider file exceeds the reviewed bound")
            return bytes(chunks), _SecureLayout.file_identity(info)
        finally:
            os.close(fd)

    def _stage_file(
        self, directory_fd: int, data: bytes,
    ) -> tuple[str, tuple[int, int, int, int, int]]:
        temporary = ".tmp-" + secrets.token_hex(16)
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600, dir_fd=directory_fd,
        )
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
            info = os.fstat(fd)
            if not _SecureLayout._file_ok(info):
                raise ProviderRejected("temporary notification file is unsafe")
        except BaseException:
            os.close(fd)
            os.unlink(temporary, dir_fd=directory_fd)
            raise
        else:
            os.close(fd)
        return temporary, _SecureLayout.file_identity(info)

    def _install_staged(self, directory_fd: int, temporary: str, filename: str) -> None:
        try:
            self._rename_noreplace(directory_fd, temporary, filename)
        except FileExistsError:
            raise ProviderConflict("notification target exists before trusted rename") from None
        os.fsync(directory_fd)

    @staticmethod
    def _unlink_if_exists(directory_fd: int, filename: str) -> None:
        try:
            os.unlink(filename, dir_fd=directory_fd)
        except FileNotFoundError:
            pass

    @staticmethod
    def _intent_identity(row: Mapping[str, Any], prefix: str) -> tuple[int, int, int, int, int] | None:
        values = tuple(row[f"{prefix}_{name}"] for name in ("dev", "ino", "uid", "mode", "nlink"))
        if all(value is None for value in values):
            return None
        if any(value is None for value in values):
            raise ProviderConflict("notification journal intent is incomplete")
        return values  # type: ignore[return-value]

    @_exclusive_operation
    def publish(self, intent: NotificationIntent) -> dict[str, Any]:
        data = self._notification_payload(intent)
        canonical_digest = _sha256(_canonical(intent))
        file_digest = _sha256(data)
        filename = self._filename(intent.effect_id)
        identity_filename = self._identity_filename(intent.effect_id)
        now = datetime.now(UTC).isoformat()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM notification_effects WHERE effect_id=? OR provider_attempt_id=?",
                (intent.effect_id, intent.provider_attempt_id),
            ).fetchone()
            if row is not None:
                if (row["effect_id"] != intent.effect_id
                        or row["provider_attempt_id"] != intent.provider_attempt_id
                        or row["canonical_digest"] != canonical_digest
                        or row["filename"] != filename
                        or row["identity_filename"] != identity_filename):
                    raise ProviderConflict("notification effect identity changed")
            else:
                if datetime.now(UTC) >= intent.expires_at:
                    raise ProviderRejected("expired notification effect is not emitted")
                connection.execute(
                    "INSERT INTO notification_effects("
                    "effect_id,provider_attempt_id,incident_id,request_id,generation,expires_at,"
                    "canonical_digest,filename,identity_filename,state,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (intent.effect_id, intent.provider_attempt_id, intent.incident_id,
                     intent.request_id, intent.generation, intent.expires_at.isoformat(),
                     canonical_digest, filename, identity_filename, "prepared", now, now),
                )
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM notification_effects WHERE effect_id=?", (intent.effect_id,),
            ).fetchone()
            if row is None:
                raise ProviderConflict("notification prepared intent disappeared")
            expected_file_identity = self._intent_identity(row, "intent_file")
            expected_sidecar_identity = self._intent_identity(row, "intent_sidecar")
            prior_file_digest = row["intent_file_digest"]
            prior_sidecar_digest = row["intent_sidecar_digest"]
        created = False
        with self.layout.child("notifications") as directory_fd:
            if expected_file_identity is None:
                if expected_sidecar_identity is not None or prior_file_digest is not None \
                        or prior_sidecar_digest is not None:
                    raise ProviderConflict("notification journal intent is incomplete")
                for target in (filename, identity_filename):
                    try:
                        os.stat(target, dir_fd=directory_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    raise ProviderConflict("published file exists without trusted journal intent")
                file_temporary, staged_file_identity = self._stage_file(directory_fd, data)
                identity_data = self._identity_payload(
                    intent, filename, file_digest, staged_file_identity,
                )
                sidecar_digest = _sha256(identity_data)
                sidecar_temporary, staged_sidecar_identity = self._stage_file(
                    directory_fd, identity_data,
                )
                try:
                    with self._transaction() as connection:
                        current = connection.execute(
                            "SELECT * FROM notification_effects WHERE effect_id=?",
                            (intent.effect_id,),
                        ).fetchone()
                        if current is None or self._intent_identity(current, "intent_file") is not None:
                            raise ProviderConflict("notification journal intent changed while staging")
                        connection.execute(
                            "UPDATE notification_effects SET intent_file_digest=?,intent_file_dev=?,"
                            "intent_file_ino=?,intent_file_uid=?,intent_file_mode=?,intent_file_nlink=?,"
                            "intent_sidecar_digest=?,intent_sidecar_dev=?,intent_sidecar_ino=?,"
                            "intent_sidecar_uid=?,intent_sidecar_mode=?,intent_sidecar_nlink=?,updated_at=? "
                            "WHERE effect_id=?",
                            (file_digest, *staged_file_identity, sidecar_digest,
                             *staged_sidecar_identity, datetime.now(UTC).isoformat(), intent.effect_id),
                        )
                    self._install_staged(directory_fd, file_temporary, filename)
                    self._install_staged(directory_fd, sidecar_temporary, identity_filename)
                    created = True
                finally:
                    self._unlink_if_exists(directory_fd, file_temporary)
                    self._unlink_if_exists(directory_fd, sidecar_temporary)
                expected_file_identity = staged_file_identity
                expected_sidecar_identity = staged_sidecar_identity
                prior_file_digest = file_digest
                prior_sidecar_digest = sidecar_digest
            elif expected_sidecar_identity is None or prior_file_digest is None \
                    or prior_sidecar_digest is None:
                raise ProviderConflict("notification journal intent is incomplete")
            observed, file_identity = self._read_file(directory_fd, filename)
            observed_identity, sidecar_identity = self._read_file(directory_fd, identity_filename)
            if file_identity != expected_file_identity:
                raise ProviderConflict(
                    "notification identity differs from durable journal/sidecar intent"
                )
            if sidecar_identity != expected_sidecar_identity:
                raise ProviderConflict("notification sidecar inode differs from durable journal intent")
        if observed != data or _sha256(observed) != file_digest:
            raise ProviderConflict("notification readback differs")
        identity_data = self._identity_payload(intent, filename, file_digest, file_identity)
        if observed_identity != identity_data:
            raise ProviderConflict("notification identity sidecar differs")
        if prior_file_digest != file_digest or prior_sidecar_digest != _sha256(identity_data):
            raise ProviderConflict("notification bytes differ from durable journal intent")
        if self.fault_after_publish is not None:
            self.fault_after_publish()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * "
                "FROM notification_effects WHERE effect_id=?",
                (intent.effect_id,),
            ).fetchone()
            if row is None or row["canonical_digest"] != canonical_digest:
                raise ProviderConflict("notification journal identity changed")
            if row["file_digest"] not in (None, file_digest):
                raise ProviderConflict("notification file digest changed")
            if self._intent_identity(row, "intent_file") != file_identity:
                raise ProviderConflict("notification file differs from journal intent")
            if self._intent_identity(row, "intent_sidecar") != sidecar_identity:
                raise ProviderConflict("notification sidecar differs from journal intent")
            if (row["intent_file_digest"] != file_digest
                    or row["intent_sidecar_digest"] != _sha256(identity_data)):
                raise ProviderConflict("notification digest differs from journal intent")
            stored_identity = tuple(row[name] for name in (
                "file_dev", "file_ino", "file_uid", "file_mode", "file_nlink",
            ))
            if any(value is not None for value in stored_identity) and stored_identity != file_identity:
                raise ProviderConflict("notification file identity changed")
            if row["identity_filename"] != identity_filename:
                raise ProviderConflict("notification identity sidecar name changed")
            state = "acknowledged" if row["state"] == "acknowledged" else "published"
            connection.execute(
                "UPDATE notification_effects SET file_digest=?,file_dev=?,file_ino=?,file_uid=?,"
                "file_mode=?,file_nlink=?,state=?,updated_at=? WHERE effect_id=?",
                (file_digest, *file_identity, state, datetime.now(UTC).isoformat(), intent.effect_id),
            )
            connection.execute(
                "INSERT INTO notification_readbacks(effect_id,file_digest,observed_at) VALUES (?,?,?)",
                (intent.effect_id, file_digest, datetime.now(UTC).isoformat()),
            )
            connection.execute(
                "INSERT INTO provider_audit(event_type,object_id,evidence_json,observed_at) "
                "VALUES ('notification_readback',?,?,?)",
                (intent.effect_id, json.dumps({"file_digest": file_digest, "created": created}),
                 datetime.now(UTC).isoformat()),
            )
        return {"effect_id": intent.effect_id, "provider_attempt_id": intent.provider_attempt_id,
                "state": state, "file_digest": file_digest, "filename": filename,
                "created": created}

    @_exclusive_operation
    def readback(self, effect_id: str) -> dict[str, Any]:
        _text(effect_id, "effect_id")
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM notification_effects WHERE effect_id=?", (effect_id,),
            ).fetchone()
            if row is None or row["file_digest"] is None:
                raise ProviderRejected("notification is not published")
        with self.layout.child("notifications") as directory_fd:
            data, file_identity = self._read_file(directory_fd, row["filename"])
            sidecar, _sidecar_identity = self._read_file(
                directory_fd, row["identity_filename"],
            )
        digest = _sha256(data)
        if digest != row["file_digest"]:
            raise ProviderConflict("notification readback digest changed")
        stored_identity = tuple(row[name] for name in (
            "file_dev", "file_ino", "file_uid", "file_mode", "file_nlink",
        ))
        if stored_identity != file_identity:
            raise ProviderConflict("notification readback identity changed")
        if self._intent_identity(row, "intent_file") != file_identity:
            raise ProviderConflict("notification readback differs from journal intent")
        if self._intent_identity(row, "intent_sidecar") != _sidecar_identity:
            raise ProviderConflict("notification sidecar differs from journal intent")
        expected_sidecar = _canonical({
            "schema_version": "acs-human-bridge-notification-identity/1",
            "effect_id": effect_id,
            "provider_attempt_id": row["provider_attempt_id"],
            "canonical_digest": row["canonical_digest"],
            "filename": row["filename"],
            "file_digest": digest,
            "file_identity": {
                "dev": file_identity[0], "ino": file_identity[1], "uid": file_identity[2],
                "mode": file_identity[3], "nlink": file_identity[4],
            },
        })
        if sidecar != expected_sidecar:
            raise ProviderConflict("notification identity sidecar no longer matches")
        if (row["intent_file_digest"] != digest
                or row["intent_sidecar_digest"] != _sha256(expected_sidecar)):
            raise ProviderConflict("notification readback digest differs from journal intent")
        return {"effect_id": effect_id, "provider_attempt_id": row["provider_attempt_id"],
                "state": row["state"], "file_digest": digest, "filename": row["filename"]}

    @_exclusive_operation
    def acknowledge(self, effect_id: str, file_digest: str) -> dict[str, Any]:
        _digest(file_digest, "file_digest")
        observed = self.readback(effect_id)
        if observed["file_digest"] != file_digest:
            raise ProviderConflict("notification acknowledgment digest differs")
        with self._transaction() as connection:
            connection.execute(
                "UPDATE notification_effects SET state='acknowledged',updated_at=? WHERE effect_id=?",
                (datetime.now(UTC).isoformat(), effect_id),
            )
            connection.execute(
                "INSERT INTO provider_audit(event_type,object_id,evidence_json,observed_at) "
                "VALUES ('notification_acknowledged',?,?,?)",
                (effect_id, json.dumps({"file_digest": file_digest}), datetime.now(UTC).isoformat()),
            )
        return {**observed, "state": "acknowledged"}

    @_exclusive_operation
    def receive_manual(
        self,
        filename: str,
        *,
        context: TrustedSurfaceContext,
        now: datetime,
    ) -> dict[str, Any]:
        _aware(now, "now")
        if not context.authenticated:
            raise ProviderRejected("manual file is not an authorization credential")
        with self.layout.child("inbox") as directory_fd:
            data, _file_identity = self._read_file(directory_fd, filename)
        file_digest = _sha256(data)
        manual = ManualReturn.parse(data)
        if manual.tenant_id != context.tenant_id or manual.incident_id != context.incident_id:
            raise ProviderRejected("manual return crosses tenant or incident")
        canonical_digest = _sha256(_canonical(manual))
        with self._transaction() as connection:
            prior = connection.execute(
                "SELECT canonical_digest,file_digest,disposition FROM manual_returns WHERE packet_id=?",
                (manual.packet_id,),
            ).fetchone()
            if prior is not None:
                if prior["canonical_digest"] != canonical_digest or prior["file_digest"] != file_digest:
                    raise ProviderConflict("manual return packet identity changed")
                return {"packet_id": manual.packet_id, "disposition": prior["disposition"],
                        "file_digest": file_digest, "payload_digest": manual.payload_digest,
                        "artifact_digest": manual.artifact_digest,
                        "message_id": manual.message_id, "operation_id": manual.operation_id,
                        "direction": manual.direction}
            current = (
                manual.generation == context.incident_generation
                and manual.expected_revision == context.expected_revision
                and manual.accepted_state_digest == context.accepted_state_digest
                and context.incident_state == "human_requested"
                and now < min(manual.expires_at, context.deadline)
            )
            disposition = "committed" if current else "fenced_late"
            connection.execute(
                "INSERT INTO manual_returns("
                "packet_id,tenant_id,incident_id,generation,expected_revision,"
                "accepted_state_digest,file_digest,canonical_digest,disposition,filename,"
                "principal_ref,grant_ref,observed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (manual.packet_id, manual.tenant_id, manual.incident_id, manual.generation,
                 manual.expected_revision, manual.accepted_state_digest, file_digest,
                 canonical_digest, disposition, filename, context.principal_ref,
                 context.grant_ref, now.astimezone(UTC).isoformat()),
            )
            connection.execute(
                "INSERT INTO provider_audit(event_type,object_id,evidence_json,observed_at) "
                "VALUES (?,?,?,?)",
                ("manual_return_" + disposition, manual.packet_id,
                 json.dumps({"file_digest": file_digest, "incident_state": context.incident_state,
                             "generation": manual.generation}),
                 now.astimezone(UTC).isoformat()),
            )
        return {"packet_id": manual.packet_id, "disposition": disposition,
                "file_digest": file_digest, "payload_digest": manual.payload_digest,
                "artifact_digest": manual.artifact_digest,
                "message_id": manual.message_id, "operation_id": manual.operation_id,
                "direction": manual.direction}

    @_exclusive_operation
    def journal_snapshot(self) -> dict[str, list[dict[str, Any]]]:
        with closing(self._connect()) as connection:
            return {
                "notifications": [dict(row) for row in connection.execute(
                    "SELECT * FROM notification_effects ORDER BY effect_id")],
                "readbacks": [dict(row) for row in connection.execute(
                    "SELECT * FROM notification_readbacks ORDER BY readback_id")],
                "manual_returns": [dict(row) for row in connection.execute(
                    "SELECT * FROM manual_returns ORDER BY packet_id")],
                "audit": [dict(row) for row in connection.execute(
                    "SELECT * FROM provider_audit ORDER BY audit_id")],
            }


def _helper_live_descriptors() -> set[int]:
    try:
        names = os.listdir("/proc/self/fd")
    except OSError:
        raise ProviderRejected("procfs FD evidence is unavailable in SQLite helper") from None
    descriptors = set()
    for name in names:
        if name.isdigit():
            descriptor = int(name)
            try:
                os.fstat(descriptor)
            except OSError:
                continue
            descriptors.add(descriptor)
    return descriptors


def _sqlite_helper_main() -> int:
    """Own one connection in a fresh single-threaded process and serve SQL RPC."""
    connection: sqlite3.Connection | None = None
    witness_fd: int | None = None
    try:
        bootstrap = json.loads(sys.stdin.readline())
        root = Path(bootstrap["root"])
        expected = tuple(bootstrap["expected"])
        if len(expected) != 5 or any(type(value) is not int for value in expected):
            raise ProviderRejected("SQLite helper expected identity is malformed")
        layout = object.__new__(_SecureLayout)
        layout.root = root
        witness_fd = layout.open_database_witness()
        if layout.file_identity(os.fstat(witness_fd)) != expected:
            raise ProviderRejected("SQLite helper path witness differs from provider witness")
        before = _helper_live_descriptors()
        connection = sqlite3.connect(root / "provider.sqlite", timeout=10, isolation_level=None)
        after = _helper_live_descriptors()
        opened_regular = []
        for descriptor in after - before:
            try:
                info = os.fstat(descriptor)
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode):
                opened_regular.append(layout.file_identity(info))
        if opened_regular != [expected]:
            raise ProviderRejected("SQLite helper connection does not use the fixed journal inode")
        if layout.check_database_path(witness_fd) != expected:
            raise ProviderRejected("SQLite helper database path changed during connection")
        # No SQL or mutable PRAGMA runs until the helper has identified its own new FD.
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA temp_store=MEMORY")
        if bootstrap["check_meta"]:
            row = connection.execute(
                "SELECT value FROM provider_meta WHERE key='database_witness'"
            ).fetchone()
            if row is None or row[0] != json.dumps(expected):
                raise ProviderRejected("SQLite journal persistent witness changed")
        sys.stdout.write('{"status":"ready"}\n')
        sys.stdout.flush()
        for line in sys.stdin:
            request = json.loads(line)
            operation = request["operation"]
            if operation == "close":
                sys.stdout.write(json.dumps({
                    "status": "ok", "in_transaction": connection.in_transaction,
                }, separators=(",", ":")) + "\n")
                sys.stdout.flush()
                break
            if operation == "executescript":
                connection.executescript(request["sql"])
                reply = {"status": "ok", "in_transaction": connection.in_transaction}
            elif operation == "execute":
                cursor = connection.execute(request["sql"], request.get("parameters", []))
                columns = [item[0] for item in cursor.description] if cursor.description else []
                rows = [list(row) for row in cursor.fetchall()] if columns else []
                reply = {
                    "status": "ok", "columns": columns, "rows": rows,
                    "in_transaction": connection.in_transaction,
                }
            else:
                raise ProviderRejected("SQLite helper operation is unsupported")
            sys.stdout.write(json.dumps(reply, separators=(",", ":")) + "\n")
            sys.stdout.flush()
        return 0
    except Exception as error:  # noqa: BLE001 - isolated process boundary returns typed text
        sys.stdout.write(json.dumps({
            "status": "error", "message": f"{type(error).__name__}: {error}",
        }, separators=(",", ":")) + "\n")
        sys.stdout.flush()
        return 1
    finally:
        if connection is not None:
            connection.close()
        if witness_fd is not None:
            os.close(witness_fd)


if __name__ == "__main__" and sys.argv[1:] == ["--sqlite-helper"]:
    raise SystemExit(_sqlite_helper_main())
