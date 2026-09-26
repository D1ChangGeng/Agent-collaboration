from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Self

from runtime.errors import EffectUnavailable


class EffectGateway:
    def __init__(self, authority: Any) -> None:
        self._authority = authority

    def verify_and_readback(self, lease_id, resource_id, generation, fencing_token, readback_ref):
        raise EffectUnavailable(resource_id, "no protected resource reader is configured")


class LocalFileEffectGateway(EffectGateway):
    """Linux effects under an exclusively service-owned root and held Domain fence.

    Directory descriptors pin identities across path replacement. Completed
    write replay returns an operation-completion observation, not a claim about
    current bytes. readback independently verifies the current target bytes.
    Processes sharing service credentials must not mutate its private storage.
    """

    MARKER_DIR = ".acs-effect-markers"
    SCHEMA = "acs-file-effect/2"
    META_LIMIT = 1024 * 1024

    def __init__(
        self,
        authority,
        root,
        *,
        scope_id="local-scope",
        operator_trust="explicit-local-test",
        resource_paths=None,
        max_bytes=16 * 1024 * 1024,
    ):
        self._require_backend()
        super().__init__(authority)
        if not isinstance(scope_id, str) or not scope_id or len(scope_id) > 256:
            raise ValueError("scope_id is required and bounded")
        if not operator_trust or type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("operator_trust and positive integer max_bytes are required")
        configured = Path(root)
        if ".." in configured.parts or chr(0) in str(configured):
            raise ValueError("root cannot contain traversal or NUL")
        self._root = Path(os.path.abspath(configured))
        self._scope_id, self._operator_trust, self._max_bytes = scope_id, operator_trust, max_bytes
        self._resources = {}
        for resource, path in (resource_paths or {}).items():
            self._identity(resource)
            relative = self._relative(path)
            if relative in self._resources.values():
                raise ValueError("multiple resources cannot share a path")
            self._resources[resource] = relative
        self._mutex = threading.RLock()
        self._fds = []
        self._root_fd = None
        try:
            self._root_fd = self._open_root(self.root)
            self._fds.append(self._root_fd)
            self._meta = self._directory(self._root_fd, self.MARKER_DIR, True)
            self._fds.append(self._meta)
            lock = os.open(
                "lock",
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=self._meta,
            )
            self._fds.append(lock)
            if not stat.S_ISREG(os.fstat(lock).st_mode):
                raise ValueError("gateway lock must be regular")
            self._lock_fd = lock
            with self._exclusive():
                entries = set(os.listdir(self._meta)) - {"lock"}
                if entries and "config.json" not in entries:
                    raise ValueError("existing unbound marker history requires explicit migration")
                config = {
                    "schema": self.SCHEMA,
                    "scope_id": scope_id,
                    "resources": self._resources,
                    "max_bytes": max_bytes,
                }
                self._install(self._meta, "config.json", self._encode(config), lambda: None)
                self._ops = self._directory(self._meta, "operations", True)
                self._fds.append(self._ops)
                self._current = self._directory(self._meta, "current", True)
                self._fds.append(self._current)
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _require_backend():
        if (
            not sys.platform.startswith("linux")
            or any(
                not hasattr(os, flag)
                for flag in ("O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC", "O_NONBLOCK")
            )
            or any(
                fn not in os.supports_dir_fd
                for fn in (os.open, os.mkdir, os.link, os.unlink, os.rename)
            )
            or os.link not in os.supports_follow_symlinks
            or os.listdir not in os.supports_fd
        ):
            raise ValueError("file effect backend requires Linux dir_fd/O_NOFOLLOW")
        import fcntl

        if not callable(fcntl.flock):
            raise TypeError("file effect backend requires flock")

    @property
    def root(self):
        return self._root

    @property
    def scope_id(self):
        return self._scope_id

    @property
    def operator_trust(self):
        return self._operator_trust

    @property
    def resource_paths(self):
        return dict(self._resources)

    @staticmethod
    def _identity(value):
        if (
            not isinstance(value, str)
            or not 1 <= len(value) <= 256
            or any(ord(c) < 32 for c in value)
        ):
            raise ValueError("identity must be a bounded nonempty string")

    @classmethod
    def _relative(cls, value):
        raw = str(value)
        parts = raw.split("/")
        if (
            not raw
            or chr(92) in raw
            or ":" in raw
            or any(ord(c) < 32 for c in raw)
            or any(p in {"", ".", "..", cls.MARKER_DIR} for p in parts)
        ):
            raise ValueError("resource path must be relative and outside gateway metadata")
        return raw

    @staticmethod
    def _flags():
        return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC

    @classmethod
    def _directory(cls, parent, name, create=False):
        if create:
            try:
                os.mkdir(name, 0o700, dir_fd=parent)
            except FileExistsError:
                pass
            os.fsync(parent)
        return os.open(name, cls._flags(), dir_fd=parent)

    @classmethod
    def _open_root(cls, path):
        fd = os.open("/", cls._flags())
        try:
            for part in path.parts[1:]:
                child = cls._directory(fd, part, True)
                os.close(fd)
                fd = child
            return fd
        except BaseException:
            os.close(fd)
            raise

    @contextmanager
    def _exclusive(self):
        import fcntl

        with self._mutex:
            if self._root_fd is None:
                raise EffectUnavailable("gateway", "gateway is closed")
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)

    def close(self):
        with self._mutex:
            fds, self._fds = self._fds, []
            self._root_fd = None
            for fd in reversed(fds):
                os.close(fd)

    def __enter__(self) -> Self:
        if self._root_fd is None:
            raise EffectUnavailable("gateway", "gateway is closed")
        return self

    def __exit__(self, *_):
        self.close()

    @contextmanager
    def _target(self, resource, relative):
        registered = self._resources.get(resource)
        if registered is None or (relative is not None and self._relative(relative) != registered):
            raise EffectUnavailable(resource, "resource/path is not registered")
        parent = os.dup(self._root_fd)
        parts = registered.split("/")
        try:
            for part in parts[:-1]:
                child = self._directory(parent, part)
                os.close(parent)
                parent = child
            yield parent, parts[-1], registered
        finally:
            os.close(parent)

    @staticmethod
    def _digest(data):
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _encode(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()

    @classmethod
    def _read(cls, parent, name, limit, *, missing=False):
        try:
            fd = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent
            )
        except FileNotFoundError:
            if missing:
                return None
            raise
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError("file is not regular or exceeds size limit")
            data = bytearray()
            while True:
                chunk = os.read(fd, min(65536, limit - len(data) + 1))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > limit:
                    raise ValueError("file grew beyond size limit")
            if os.fstat(fd).st_size > limit:
                raise ValueError("file grew beyond size limit")
            return bytes(data)
        finally:
            os.close(fd)

    @classmethod
    def _persist(cls, parent, name, data, check, *, immutable):
        temporary = ".tmp-" + secrets.token_hex(24)
        fd = os.open(
            temporary,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent,
        )
        try:
            view = memoryview(data)
            while view:
                n = os.write(fd, view)
                if n <= 0:
                    raise OSError("write made no progress")
                view = view[n:]
            os.fsync(fd)
            check()
            if immutable:
                try:
                    os.link(
                        temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False
                    )
                except FileExistsError:
                    pass
                if cls._read(parent, name, len(data)) != data:
                    raise ValueError("immutable operation intent/configuration conflicts")
            else:
                os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            os.close(fd)
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
            os.fsync(parent)

    @classmethod
    def _install(cls, parent, name, data, check):
        cls._persist(parent, name, data, check, immutable=True)

    @classmethod
    def _record(cls, parent, name, body, check, *, immutable=True):
        encoded = cls._encode(body)
        envelope = cls._encode({"body": body, "sha256": cls._digest(encoded)})
        if len(envelope) > cls.META_LIMIT:
            raise ValueError("metadata size exceeds limit")
        cls._persist(parent, name, envelope, check, immutable=immutable)

    @classmethod
    def _load(cls, parent, name):
        data = cls._read(parent, name, cls.META_LIMIT, missing=True)
        if data is None:
            return None
        envelope = json.loads(data)
        if (
            not isinstance(envelope, dict)
            or set(envelope) != {"body", "sha256"}
            or not isinstance(envelope["body"], dict)
            or envelope["sha256"] != cls._digest(cls._encode(envelope["body"]))
        ):
            raise ValueError("corrupt operation metadata")
        return envelope["body"]

    @classmethod
    def _state(cls, payload):
        return {
            "exists": payload is not None,
            "sha256": cls._digest(payload) if payload is not None else None,
            "bytes": len(payload) if payload is not None else 0,
        }

    @contextmanager
    def _fence(self, lease, resource, generation, token, owner):
        required = (
            "caller",
            "attempt_id",
            "runtime_id",
            "scope_id",
            "grant_ref",
            "authority_incarnation",
        )
        if any(not owner.get(k) for k in required) or owner["scope_id"] != self.scope_id:
            raise EffectUnavailable(
                resource, "complete authenticated owner in this scope is required"
            )
        with self._authority.hold_fence(
            lease, resource, generation, token, **owner, permission="effect.write"
        ) as fence:
            check = fence.get("check_current") if isinstance(fence, dict) else None
            if not callable(check):
                raise EffectUnavailable(resource, "held fence lacks check_current capability")
            if (
                not fence.get("work_item_id")
                or fence.get("authority_id") != owner["caller"].authority_id
            ):
                raise EffectUnavailable(resource, "held fence lacks WorkItem/authority binding")
            check()
            yield fence

    def _write(
        self,
        lease_id,
        resource_id,
        generation,
        fencing_token,
        relative_path,
        payload,
        *,
        operation_id=None,
        caller=None,
        attempt_id=None,
        runtime_id=None,
        scope_id=None,
        grant_ref=None,
        authority_incarnation=None,
        original=None,
    ):
        if not isinstance(payload, bytes) or len(payload) > self._max_bytes:
            raise EffectUnavailable(resource_id, "payload must be bounded bytes")
        owner = {
            "caller": caller,
            "attempt_id": attempt_id,
            "runtime_id": runtime_id,
            "scope_id": scope_id,
            "grant_ref": grant_ref,
            "authority_incarnation": authority_incarnation,
        }
        try:
            self._identity(operation_id)
            with self._fence(lease_id, resource_id, generation, fencing_token, owner) as fence:
                check = fence["check_current"]
                with (
                    self._exclusive(),
                    self._target(resource_id, relative_path) as (parent, name, path),
                ):
                    key = self._digest(operation_id.encode())
                    resource_key = self._digest(resource_id.encode()) + ".json"
                    identity = {
                        "schema": self.SCHEMA,
                        "operation_id": operation_id,
                        "lease_id": lease_id,
                        "resource_id": resource_id,
                        "generation": generation,
                        "fencing_token": fencing_token,
                        "relative_path": path,
                        "scope_id": self.scope_id,
                        "owner": {k: v for k, v in owner.items() if k != "caller"},
                        "principal_ref": caller.principal_ref,
                        "tenant_id": caller.tenant_id,
                        "authority_id": caller.authority_id,
                        "work_item_id": fence["work_item_id"],
                        "new": self._state(payload),
                    }
                    executor = {
                        "lease_id": lease_id,
                        "generation": generation,
                        "fencing_token": fencing_token,
                        "owner": identity["owner"],
                        "principal_ref": caller.principal_ref,
                        "tenant_id": caller.tenant_id,
                        "authority_id": caller.authority_id,
                        "work_item_id": fence["work_item_id"],
                    }
                    if original is not None:
                        if (
                            original["tenant_id"] != caller.tenant_id
                            or original["authority_id"] != caller.authority_id
                            or original["work_item_id"] != fence["work_item_id"]
                        ):
                            raise ValueError(
                                "recovery tenant/authority/WorkItem differs from original intent"
                            )
                        for field in (
                            "lease_id",
                            "generation",
                            "fencing_token",
                            "owner",
                            "principal_ref",
                            "authority_id",
                        ):
                            identity[field] = original[field]
                    intent = self._load(self._ops, key + ".intent")
                    pointer = self._load(self._current, resource_key)
                    if intent is None:
                        if pointer is not None and pointer.get("state") != "completed":
                            raise ValueError(
                                "resource has an unresolved operation; resume it first"
                            )
                        old = self._state(self._read(parent, name, self._max_bytes, missing=True))
                        intent = dict(identity, old=old, previous=pointer)
                        self._install(self._ops, key + ".payload", payload, check)
                        self._record(self._ops, key + ".intent", intent, check)
                    elif any(intent.get(k) != v for k, v in identity.items()):
                        raise ValueError("operation identity/input conflicts with immutable intent")
                    completed = self._load(self._ops, key + ".completed")
                    if completed is not None:
                        if completed.get("intent_sha256") != self._digest(self._encode(intent)):
                            raise ValueError("completion does not bind the recorded intent")
                        os.fsync(self._ops)
                        if pointer == {"operation_id": operation_id, "state": "prepared"}:
                            # Completion was durable but publishing the current
                            # pointer failed. Never repeat the resource write.
                            self._record(
                                self._current,
                                resource_key,
                                {"operation_id": operation_id, "state": "completed"},
                                check,
                                immutable=False,
                            )
                        return completed["result"]
                    prepared = {"operation_id": operation_id, "state": "prepared"}
                    if pointer not in (intent["previous"], prepared):
                        raise ValueError("resource advanced beyond this operation")
                    self._record(self._current, resource_key, prepared, check, immutable=False)
                    execution = {
                        "intent_sha256": self._digest(self._encode(intent)),
                        "executor": executor,
                    }
                    execution_key = self._digest(self._encode(executor))
                    self._record(self._ops, key + ".execution-" + execution_key, execution, check)
                    observed = self._state(self._read(parent, name, self._max_bytes, missing=True))
                    applied_now = False
                    if observed != intent["new"]:
                        if observed != intent["old"]:
                            raise ValueError(
                                "resource differs from both prewrite and intended states"
                            )
                        # Held resource fence isolates earlier owners; old bytes still
                        # present show that this replacement has not taken effect.
                        self._persist(parent, name, payload, check, immutable=False)
                        applied_now = True
                    if self._state(self._read(parent, name, self._max_bytes)) != intent["new"]:
                        raise ValueError("resource readback differs from intended state")
                    os.fsync(parent)
                    result = {
                        "status": "verified",
                        "observation": "operation_completion",
                        "operation_id": operation_id,
                        "resource_id": resource_id,
                        "readback_ref": path,
                        "sha256": intent["new"]["sha256"],
                        "bytes": intent["new"]["bytes"],
                        "marker_ref": f"{self.MARKER_DIR}/operations/{key}.completed",
                    }
                    self._record(
                        self._ops,
                        key + ".completed",
                        {
                            "intent_sha256": self._digest(self._encode(intent)),
                            "result": result,
                            "completed_by": executor,
                            "completion_basis": "applied_now" if applied_now else "observed_target",
                        },
                        check,
                    )
                    self._record(
                        self._current,
                        resource_key,
                        {"operation_id": operation_id, "state": "completed"},
                        check,
                        immutable=False,
                    )
                    return result
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise EffectUnavailable(resource_id, str(exc)) from exc

    def write(
        self,
        lease_id,
        resource_id,
        generation,
        fencing_token,
        relative_path,
        payload,
        *,
        operation_id=None,
        caller=None,
        attempt_id=None,
        runtime_id=None,
        scope_id=None,
        grant_ref=None,
        authority_incarnation=None,
    ):
        return self._write(
            lease_id,
            resource_id,
            generation,
            fencing_token,
            relative_path,
            payload,
            operation_id=operation_id,
            caller=caller,
            attempt_id=attempt_id,
            runtime_id=runtime_id,
            scope_id=scope_id,
            grant_ref=grant_ref,
            authority_incarnation=authority_incarnation,
        )

    def resume(
        self,
        lease_id,
        resource_id,
        generation,
        fencing_token,
        relative_path,
        *,
        operation_id,
        caller,
        attempt_id,
        runtime_id,
        scope_id,
        grant_ref,
        authority_incarnation,
    ):
        """Resume stored intent with the current owner's independently checked fence.

        Positional lease parameters name the current Lease, potentially a newer
        generation. Original producer/lease metadata remain immutable in history.
        The current owner must hold effect.write on the same registered resource.
        """
        try:
            self._identity(operation_id)
            with self._exclusive():
                key = self._digest(operation_id.encode())
                original = self._load(self._ops, key + ".intent")
                if original is None:
                    raise ValueError("operation has no prepared intent")
                payload = self._read(self._ops, key + ".payload", self._max_bytes)
            return self._write(
                lease_id,
                resource_id,
                generation,
                fencing_token,
                relative_path,
                payload,
                operation_id=operation_id,
                caller=caller,
                attempt_id=attempt_id,
                runtime_id=runtime_id,
                scope_id=scope_id,
                grant_ref=grant_ref,
                authority_incarnation=authority_incarnation,
                original=original,
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise EffectUnavailable(resource_id, str(exc)) from exc

    def _observe(self, lease, resource, generation, token, relative, operation):
        with self._exclusive(), self._target(resource, relative) as (parent, name, path):
            if operation is None:
                pointer = self._load(self._current, self._digest(resource.encode()) + ".json")
                if pointer is None:
                    raise ValueError("resource has no operation pointer")
                operation = pointer["operation_id"]
            self._identity(operation)
            intent = self._load(self._ops, self._digest(operation.encode()) + ".intent")
            expected = {
                "operation_id": operation,
                "lease_id": lease,
                "resource_id": resource,
                "generation": generation,
                "fencing_token": token,
                "relative_path": path,
                "scope_id": self.scope_id,
                "schema": self.SCHEMA,
            }
            if intent is None or any(intent.get(k) != v for k, v in expected.items()):
                raise ValueError("readback does not match original operation identity")
            observed = self._state(self._read(parent, name, self._max_bytes))
            if observed != intent["new"]:
                raise ValueError("current resource bytes differ from operation intent")
            intent_digest = self._digest(self._encode(intent))
            completed = self._load(self._ops, self._digest(operation.encode()) + ".completed")
            completion_digest = None
            if completed is not None:
                result = completed.get("result")
                if (
                    completed.get("intent_sha256") != intent_digest
                    or not isinstance(result, dict)
                    or any(
                        result.get(k) != value
                        for k, value in {
                            "operation_id": operation,
                            "resource_id": resource,
                            "readback_ref": path,
                            "sha256": observed["sha256"],
                            "bytes": observed["bytes"],
                            "status": "verified",
                        }.items()
                    )
                    or not isinstance(completed.get("completed_by"), dict)
                    or completed.get("completion_basis") not in {"applied_now", "observed_target"}
                ):
                    raise ValueError("completed record does not bind observed operation/intent")
                completion_digest = self._digest(self._encode(completed))
            return {
                "status": "verified",
                "operation_id": operation,
                "resource_id": resource,
                "readback_ref": path,
                "sha256": observed["sha256"],
                "bytes": observed["bytes"],
                "size_bytes": observed["bytes"],
                "intent_sha256": intent_digest,
                "completion_sha256": completion_digest,
                "completion_state": "completed" if completed is not None else "prepared",
                "observation": "current_resource",
            }

    def readback(
        self,
        lease_id,
        resource_id,
        generation,
        fencing_token,
        readback_ref,
        *,
        caller=None,
        attempt_id=None,
        runtime_id=None,
        scope_id=None,
        grant_ref=None,
        authority_incarnation=None,
        expected_operation_id=None,
    ):
        owner = {
            "caller": caller,
            "attempt_id": attempt_id,
            "runtime_id": runtime_id,
            "scope_id": scope_id,
            "grant_ref": grant_ref,
            "authority_incarnation": authority_incarnation,
        }
        try:
            with self._fence(lease_id, resource_id, generation, fencing_token, owner):
                return self._observe(
                    lease_id,
                    resource_id,
                    generation,
                    fencing_token,
                    readback_ref,
                    expected_operation_id,
                )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise EffectUnavailable(resource_id, str(exc)) from exc

    def historical_readback(
        self,
        lease_id,
        resource_id,
        generation,
        fencing_token,
        readback_ref,
        *,
        caller,
        scope_id,
        grant_ref,
        authority_incarnation,
        expected_operation_id=None,
    ):
        if scope_id != self.scope_id:
            raise EffectUnavailable(resource_id, "resource scope mismatch")
        try:
            self._authority.verify_historical_readback(
                lease_id,
                resource_id,
                generation,
                fencing_token,
                caller=caller,
                scope_id=scope_id,
                grant_ref=grant_ref,
                authority_incarnation=authority_incarnation,
                permission="effect.read",
            )
            return self._observe(
                lease_id,
                resource_id,
                generation,
                fencing_token,
                readback_ref,
                expected_operation_id,
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise EffectUnavailable(resource_id, str(exc)) from exc

    def historical_readback_in_transaction(
        self,
        cursor,
        lease_id,
        resource_id,
        generation,
        fencing_token,
        readback_ref,
        *,
        caller,
        scope_id,
        grant_ref,
        authority_incarnation,
        expected_operation_id=None,
    ):
        """Acceptance-only adapter with caller-held DB locks and live file readback.

        The caller already holds WorkItem, reader Grant/Scope/authority and
        historical Lease rows. Authorization is rechecked using that cursor;
        no new DB connection or resource advisory lock is acquired here.
        File serialization follows those DB locks, matching the writer order.
        The caller must keep its transaction open through acceptance commit.
        """
        if scope_id != self.scope_id:
            raise EffectUnavailable(resource_id, "resource scope mismatch")
        verifier = getattr(self._authority, "verify_historical_readback_in_transaction", None)
        if not callable(verifier):
            raise EffectUnavailable(
                resource_id, "shared-transaction historical authorization is unavailable"
            )
        try:
            verifier(
                cursor,
                lease_id,
                resource_id,
                generation,
                fencing_token,
                caller=caller,
                scope_id=scope_id,
                grant_ref=grant_ref,
                authority_incarnation=authority_incarnation,
                permission="effect.read",
            )
            return self._observe(
                lease_id,
                resource_id,
                generation,
                fencing_token,
                readback_ref,
                expected_operation_id,
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise EffectUnavailable(resource_id, str(exc)) from exc

    def reconcile(
        self,
        lease_id,
        resource_id,
        generation,
        fencing_token,
        relative_path,
        *,
        operation_id=None,
        caller=None,
        attempt_id=None,
        runtime_id=None,
        scope_id=None,
        grant_ref=None,
        authority_incarnation=None,
        historical=False,
    ):
        try:
            if historical:
                return self.historical_readback(
                    lease_id,
                    resource_id,
                    generation,
                    fencing_token,
                    relative_path,
                    caller=caller,
                    scope_id=scope_id,
                    grant_ref=grant_ref,
                    authority_incarnation=authority_incarnation,
                    expected_operation_id=operation_id,
                )
            return self.resume(
                lease_id,
                resource_id,
                generation,
                fencing_token,
                relative_path,
                operation_id=operation_id,
                caller=caller,
                attempt_id=attempt_id,
                runtime_id=runtime_id,
                scope_id=scope_id,
                grant_ref=grant_ref,
                authority_incarnation=authority_incarnation,
            )
        except (EffectUnavailable, OSError, ValueError, TypeError, KeyError) as exc:
            return {
                "status": "uncertain",
                "resource_id": resource_id,
                "readback_ref": relative_path,
                "reason": str(exc),
                "reexecute": False,
            }

    def verify_and_readback(
        self, lease_id, resource_id, generation, fencing_token, readback_ref, **kwargs
    ):
        return self.readback(
            lease_id, resource_id, generation, fencing_token, readback_ref, **kwargs
        )
