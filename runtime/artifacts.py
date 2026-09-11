from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
import sys
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Self

from runtime.models import ArtifactRef


class ArtifactError(ValueError):
    pass


class LocalArtifactStore:
    """Linux, scope-bound CAS; Domain/Node still authorize callers and references.

    Directory descriptors pin authorized objects, including across pathname
    replacement. The owning service must exclusively control CAS directories;
    this is not a sandbox for another process sharing that service's credentials.
    Contents modified outside this API are detected on each read. Initialization
    rejects symlinks in *every* configured root component. Source roots must
    exist, are explicit grants, and are pinned for this instance's lifetime.
    """

    def __init__(
        self,
        root: Path | str,
        scope_id: str = "local-scope",
        *,
        authorized_source_roots: Iterable[Path | str] = (),
        max_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        self._require_backend()  # No filesystem mutation before this check.
        if type(max_bytes) is not int or max_bytes < 1:
            raise ArtifactError("max_bytes must be a positive integer")
        if (
            not isinstance(scope_id, str)
            or not 1 <= len(scope_id) <= 256
            or scope_id in {".", ".."}
            or any(c in "/\\" or ord(c) < 32 for c in scope_id)
        ):
            raise ArtifactError("invalid artifact scope")
        self._root = self._absolute(root)
        self._scope_id = scope_id
        self._max_bytes = max_bytes
        self._root_fd: int | None = None
        self._sources: list[tuple[Path, int]] = []
        self._lock = threading.RLock()
        try:
            for source in authorized_source_roots:
                path = self._absolute(source)
                self._sources.append((path, self._open_directory(path, create=False)))
            self._root_fd = self._open_directory(self._root, create=True)
            entries = os.listdir(self._root_fd)
            if entries and ".scope" not in entries:
                raise ArtifactError("cannot claim a nonempty artifact root without a scope binding")
            self._publish(self._root_fd, ".scope", scope_id.encode("utf-8"))
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _require_backend() -> None:
        required = (os.open, os.mkdir, os.link, os.unlink)
        if (
            not sys.platform.startswith("linux")
            or any(not hasattr(os, name) for name in (
                "O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC", "O_NONBLOCK"
            ))
            or any(fn not in os.supports_dir_fd for fn in required)
            or os.link not in os.supports_follow_symlinks
            or os.listdir not in os.supports_fd
        ):
            raise ArtifactError("local artifact backend requires Linux dir_fd/O_NOFOLLOW support")

    @property
    def root(self) -> Path:
        return self._root

    @property
    def scope_id(self) -> str:
        return self._scope_id

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @staticmethod
    def _absolute(value: Path | str) -> Path:
        path = Path(value)
        if ".." in path.parts or "\x00" in str(path):
            raise ArtifactError("configured and source paths must not contain traversal or NUL")
        return Path(os.path.abspath(path))

    @staticmethod
    def _dir_flags() -> int:
        return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC

    @classmethod
    def _open_child_directory(cls, parent: int, name: str, *, create: bool) -> int:
        try:
            if create:
                try:
                    os.mkdir(name, 0o700, dir_fd=parent)
                except FileExistsError:
                    pass
                # Also persists a directory created by a competing initializer.
                os.fsync(parent)
            return os.open(name, cls._dir_flags(), dir_fd=parent)
        except OSError as exc:
            raise ArtifactError("directory is missing, inaccessible, or linked") from exc

    @classmethod
    def _open_directory(cls, path: Path, *, create: bool) -> int:
        fd = os.open("/", cls._dir_flags())
        try:
            for component in path.parts[1:]:
                child = cls._open_child_directory(fd, component, create=create)
                os.close(fd)
                fd = child
            return fd
        except BaseException:
            os.close(fd)
            raise

    def _ensure_open(self) -> int:
        if self._root_fd is None:
            raise ArtifactError("artifact store is closed")
        return self._root_fd

    def close(self) -> None:
        with self._lock:
            descriptors = [fd for _, fd in self._sources]
            if self._root_fd is not None:
                descriptors.append(self._root_fd)
            self._sources = []
            self._root_fd = None
            for fd in descriptors:
                os.close(fd)

    def __enter__(self) -> Self:
        self._ensure_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _relative_path(sha256: str) -> str:
        return f"{sha256[:2]}/{sha256}"

    def _validate_ref(self, ref: ArtifactRef) -> None:
        # Revalidate even model_construct/model_copy values, which bypass Pydantic.
        if not isinstance(ref, ArtifactRef):
            raise ArtifactError("a complete typed artifact reference is required")
        try:
            ArtifactRef.model_validate(ref.model_dump(), strict=True)
        except (ValueError, TypeError) as exc:
            raise ArtifactError("invalid typed artifact reference") from exc
        if ref.immutable is not True or ref.scope_id != self.scope_id:
            raise ArtifactError("artifact is mutable or belongs to another scope")
        if not isinstance(ref.sha256, str) or re.fullmatch(r"[a-f0-9]{64}", ref.sha256) is None:
            raise ArtifactError("invalid artifact digest")
        if ref.path != self._relative_path(ref.sha256):
            raise ArtifactError("artifact path does not match its digest")
        if type(ref.size_bytes) is not int or not 0 <= ref.size_bytes <= self.max_bytes:
            raise ArtifactError("artifact size is invalid or exceeds max_bytes")

    @staticmethod
    def _read_fd(fd: int, limit: int) -> bytes:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ArtifactError("artifact/source must be a regular file")
        if info.st_size > limit:
            raise ArtifactError("artifact/source exceeds max_bytes")
        data = bytearray()
        while True:
            # Read one excess byte at most, including if a file grows after fstat.
            chunk = os.read(fd, min(64 * 1024, limit - len(data) + 1))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > limit:
                raise ArtifactError("artifact/source exceeds max_bytes while reading")
        if os.fstat(fd).st_size > limit:
            raise ArtifactError("artifact/source grew beyond max_bytes")
        return bytes(data)

    @classmethod
    def _read_at(cls, parent: int, name: str, limit: int) -> bytes:
        try:
            fd = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=parent,
            )
        except OSError as exc:
            raise ArtifactError("artifact/source is missing, inaccessible, or linked") from exc
        try:
            return cls._read_fd(fd, limit)
        finally:
            os.close(fd)

    @classmethod
    def _publish(cls, parent: int, name: str, data: bytes) -> None:
        """Durable link-if-absent publication; never replace an existing object."""
        temporary = f".artifact-{secrets.token_hex(24)}"
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600, dir_fd=parent,
        )
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise ArtifactError("artifact write made no progress")
                view = view[written:]
            os.fchmod(fd, 0o400)
            os.fsync(fd)
            try:
                os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent,
                        follow_symlinks=False)
            except FileExistsError:
                pass
            # Existing objects are read and compared, never silently overwritten.
            if cls._read_at(parent, name, len(data)) != data:
                raise ArtifactError("existing artifact or scope binding is corrupt/incompatible")
            os.fsync(parent)
        finally:
            os.close(fd)
            os.unlink(temporary, dir_fd=parent)
            os.fsync(parent)

    def put_bytes(
        self, data: bytes, *, kind: str = "other",
        media_type: str = "application/octet-stream",
    ) -> ArtifactRef:
        with self._lock:
            root = self._ensure_open()
            if not isinstance(data, bytes):
                raise TypeError("artifact data must be bytes")
            if len(data) > self.max_bytes:
                raise ArtifactError("artifact exceeds max_bytes")
            digest = hashlib.sha256(data).hexdigest()
            ref = ArtifactRef(path=self._relative_path(digest), sha256=digest,
                              size_bytes=len(data), media_type=media_type, kind=kind,
                              scope_id=self.scope_id, immutable=True)
            self._validate_ref(ref)
            parent = self._open_child_directory(root, digest[:2], create=True)
            try:
                self._publish(parent, digest, data)
            finally:
                os.close(parent)
            return ref

    def put_file(
        self, source: Path | str, *, kind: str = "other",
        media_type: str = "application/octet-stream",
    ) -> ArtifactRef:
        with self._lock:
            self._ensure_open()
            path = self._absolute(source)
            for authorized, root in self._sources:
                if path != authorized and path.is_relative_to(authorized):
                    parts = path.relative_to(authorized).parts
                    parent = os.dup(root)
                    try:
                        for component in parts[:-1]:
                            child = self._open_child_directory(parent, component, create=False)
                            os.close(parent)
                            parent = child
                        data = self._read_at(parent, parts[-1], self.max_bytes)
                    finally:
                        os.close(parent)
                    return self.put_bytes(data, kind=kind, media_type=media_type)
            raise ArtifactError("source path is outside authorized_source_roots")

    def _read_verified(self, ref: ArtifactRef) -> bytes:
        root = self._ensure_open()
        self._validate_ref(ref)
        parent = self._open_child_directory(root, ref.sha256[:2], create=False)
        try:
            payload = self._read_at(parent, ref.sha256, ref.size_bytes)
        finally:
            os.close(parent)
        if len(payload) != ref.size_bytes:
            raise ArtifactError("artifact size mismatch")
        if hashlib.sha256(payload).hexdigest() != ref.sha256:
            raise ArtifactError("artifact digest mismatch")
        return payload

    def verify(self, ref: ArtifactRef) -> ArtifactRef:
        with self._lock:
            self._read_verified(ref)
            return ref

    def read(self, ref: ArtifactRef) -> bytes:
        with self._lock:
            return self._read_verified(ref)
