from __future__ import annotations

import fnmatch
import hashlib
import json
import mimetypes
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from runtime.artifacts import LocalArtifactStore
from runtime.models import ArtifactRef
from runtime.source_models import SourceFile, SourceRequest, SourceSnapshot

DEFAULT_SECRET_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "credentials.json",
    "credentials",
    "secrets.json",
    ".aws/credentials",
    ".aws/*",
    "*/.aws/*",
    ".ssh/*",
    "*/.ssh/*",
    ".config/gcloud",
    ".config/gcloud/*",
    "*/.config/gcloud/*",
    ".codex/*",
    "*/.codex/*",
    ".omo/*",
    "*/.omo/*",
    ".agents/runtime/*",
    "*/.agents/runtime/*",
    ".venv/*",
    "*/.venv/*",
)

_AUTHORIZER = Callable[[SourceRequest], object]


class SourceError(RuntimeError):
    """Base class for fail-closed Source admission/readback errors."""


class SourceAuthorizationError(SourceError):
    pass


class SourceBackendUnavailable(SourceError):
    pass


class SourcePathError(SourceError):
    pass


class SourceRepositoryError(SourceError):
    pass


class SourceDirtyError(SourceError):
    pass


class SourceSecretError(SourceError):
    pass


class SourceOversizeError(SourceError):
    pass


class SourceChangedDuringSnapshot(SourceError):
    pass


class SourceArtifactError(SourceError):
    pass


class SourceReadbackError(SourceError):
    pass


class SourceCommitMismatch(SourceRepositoryError):
    pass


def _validate_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{field} must not contain control characters")
    return value


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


class SourceService:
    """Bounded, read-only Git Source admission/readback service.

    SourceService owns no Domain state and performs no checkout/reset/clean,
    model execution, packet creation, grant creation, or external dispatch.

    Source contents are read only from an explicitly authorized repository root.
    Every admitted source byte is copied into the caller-provided
    LocalArtifactStore, verified by actual-byte SHA-256 readback, and referenced
    by an immutable SourceSnapshot manifest.

    The first implementation is intentionally Linux-only because the existing
    LocalArtifactStore is a Linux dirfd/O_NOFOLLOW backend. Unsupported host
    backends fail closed before any source filesystem read or mutation.
    """

    SCHEMA_VERSION = "acs-source-snapshot/1"
    DEFAULT_MAX_BYTES = 16 * 1024 * 1024
    DEFAULT_MAX_METADATA_BYTES = 8 * 1024 * 1024
    DEFAULT_MAX_FILES = 100_000
    DEFAULT_MAX_GIT_OBJECT_BYTES = 512 * 1024 * 1024
    DEFAULT_MAX_GIT_OBJECT_FILES = 200_000

    def __init__(
        self,
        artifact_store: LocalArtifactStore,
        authorized_roots: Iterable[Path | str],
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_metadata_bytes: int = DEFAULT_MAX_METADATA_BYTES,
        max_files: int = DEFAULT_MAX_FILES,
        max_git_object_bytes: int = DEFAULT_MAX_GIT_OBJECT_BYTES,
        max_git_object_files: int = DEFAULT_MAX_GIT_OBJECT_FILES,
        command_timeout_seconds: float = 20.0,
        secret_patterns: Iterable[str] = DEFAULT_SECRET_PATTERNS,
        git_executable: Path | str | None = None,
    ) -> None:
        self._require_backend()

        if not hasattr(artifact_store, "put_bytes"):
            raise TypeError("artifact_store must provide put_bytes")
        if not hasattr(artifact_store, "verify"):
            raise TypeError("artifact_store must provide verify")
        if not hasattr(artifact_store, "read"):
            raise TypeError("artifact_store must provide read")
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        if type(max_metadata_bytes) is not int or max_metadata_bytes <= 0:
            raise ValueError("max_metadata_bytes must be a positive integer")
        if type(max_files) is not int or max_files <= 0:
            raise ValueError("max_files must be a positive integer")
        if type(max_git_object_bytes) is not int or max_git_object_bytes <= 0:
            raise ValueError("max_git_object_bytes must be a positive integer")
        if type(max_git_object_files) is not int or max_git_object_files <= 0:
            raise ValueError("max_git_object_files must be a positive integer")
        if command_timeout_seconds <= 0:
            raise ValueError("command_timeout_seconds must be positive")

        roots = tuple(self._prepare_authorized_root(value) for value in authorized_roots)
        if not roots:
            raise ValueError("at least one authorized Source root is required")

        self._artifact_store = artifact_store
        self._authorized_roots = roots
        self._max_bytes = max_bytes
        self._max_metadata_bytes = max_metadata_bytes
        self._max_files = max_files
        self._max_git_object_bytes = max_git_object_bytes
        self._max_git_object_files = max_git_object_files
        self._command_timeout_seconds = command_timeout_seconds
        self._secret_patterns = tuple(
            _validate_text(pattern, "secret_pattern")
            for pattern in secret_patterns
        )
        candidate = Path(
            git_executable
            or shutil.which("git", path="/usr/bin:/bin")
            or ""
        )
        if not candidate.is_absolute():
            raise SourceBackendUnavailable("an absolute system Git executable is required")
        self._check_no_symlink_components(candidate)
        resolved_git = candidate.resolve(strict=True)
        for component in (resolved_git, *resolved_git.parents[:-1]):
            info = component.lstat()
            if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
                raise SourceBackendUnavailable(
                    f"Git executable path is not root-owned and non-writable: {component}"
                )
        git_info = resolved_git.lstat()
        if not stat.S_ISREG(git_info.st_mode) or not os.access(resolved_git, os.X_OK):
            raise SourceBackendUnavailable("configured Git executable is not executable regular file")
        self._git_executable = str(resolved_git)
        self._git_identity = (
            git_info.st_dev, git_info.st_ino, git_info.st_size,
            git_info.st_mtime_ns, git_info.st_mode, git_info.st_uid,
        )
        with resolved_git.open("rb") as stream:
            self._git_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
        anchors: list[int] = []
        try:
            for root in roots:
                anchors.append(self._open_directory_from_root(root))
        except BaseException:
            for descriptor in anchors:
                os.close(descriptor)
            raise
        self._authorized_root_fds = tuple(anchors)
        self._closed = False

    @staticmethod
    def _require_backend() -> None:
        if not sys.platform.startswith("linux"):
            raise SourceBackendUnavailable(
                "Source backend requires the Linux dirfd/O_NOFOLLOW implementation"
            )
        required = (
            "O_NOFOLLOW",
            "O_DIRECTORY",
            "O_CLOEXEC",
            "O_NONBLOCK",
        )
        if any(not hasattr(os, name) for name in required):
            raise SourceBackendUnavailable(
                "Source backend lacks required dirfd/O_NOFOLLOW capabilities"
            )
        if os.open not in getattr(os, "supports_dir_fd", set()):
            raise SourceBackendUnavailable(
                "Source backend lacks dirfd open support"
            )

    @staticmethod
    def _check_no_symlink_components(path: Path) -> None:
        absolute = Path(os.path.abspath(path))
        current = Path(absolute.anchor or os.sep)

        for part in absolute.parts[1:] if absolute.is_absolute() else absolute.parts:
            current = current / part
            try:
                info = current.lstat()
            except FileNotFoundError as exc:
                raise SourcePathError(
                    f"Source path component does not exist: {current}"
                ) from exc
            if stat.S_ISLNK(info.st_mode):
                raise SourcePathError(
                    f"Source path component is a symlink/reparse point: {current}"
                )

    @staticmethod
    def _open_directory_from_root(path: Path) -> int:
        absolute = Path(os.path.abspath(path))
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        descriptor = os.open(absolute.anchor or os.sep, flags)
        try:
            for part in absolute.parts[1:]:
                child = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def _open_authorized_directory(self, path: Path) -> int:
        if self._closed:
            raise SourceBackendUnavailable("Source service is closed")
        absolute = Path(os.path.abspath(path))
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        for authorized_root, anchor in zip(
            self._authorized_roots,
            self._authorized_root_fds,
            strict=True,
        ):
            try:
                relative = absolute.relative_to(authorized_root)
            except ValueError:
                continue
            descriptor = os.dup(anchor)
            try:
                for part in relative.parts:
                    child = os.open(part, flags, dir_fd=descriptor)
                    os.close(descriptor)
                    descriptor = child
                return descriptor
            except BaseException:
                os.close(descriptor)
                raise
        raise SourceAuthorizationError(
            f"Source path is outside authorized roots: {absolute}"
        )

    @staticmethod
    def _read_control_at(
        directory_fd: int,
        relative_path: str,
        *,
        maximum: int = 1024 * 1024,
    ) -> bytes:
        parts = relative_path.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise SourceRepositoryError("Git control path is invalid")
        directory_flags = (
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        current_fd = os.dup(directory_fd)
        try:
            for part in parts[:-1]:
                child_fd = os.open(part, directory_flags, dir_fd=current_fd)
                os.close(current_fd)
                current_fd = child_fd
            descriptor = os.open(
                parts[-1],
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=current_fd,
            )
        finally:
            os.close(current_fd)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
                raise SourceRepositoryError("Git control file is not a bounded regular file")
            data = os.read(descriptor, maximum + 1)
            if len(data) > maximum:
                raise SourceRepositoryError("Git control file exceeds its bound")
            return data
        finally:
            os.close(descriptor)

    def close(self) -> None:
        if self._closed:
            return
        for descriptor in self._authorized_root_fds:
            os.close(descriptor)
        self._authorized_root_fds = ()
        self._closed = True

    def __enter__(self) -> Self:
        if self._closed:
            raise SourceBackendUnavailable("Source service is closed")
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        with suppress(AttributeError, OSError):
            self.close()

    @classmethod
    def _prepare_authorized_root(cls, value: Path | str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = Path(os.path.abspath(path))
        cls._check_no_symlink_components(path)
        resolved = path.resolve(strict=True)
        info = resolved.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise SourcePathError(f"authorized Source root is not a directory: {resolved}")
        return resolved

    def _prepare_repository_root(
        self,
        value: Path | str,
        authorized_roots: tuple[Path, ...],
    ) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = Path(os.path.abspath(path))
        absolute = Path(os.path.abspath(path))
        if not any(self._is_relative_to(absolute, root) for root in authorized_roots):
            raise SourceAuthorizationError(
                f"Source root is outside authorized roots: {absolute}"
            )
        descriptor = self._open_authorized_directory(absolute)
        try:
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise SourcePathError(f"Source root is not a directory: {absolute}")
        finally:
            os.close(descriptor)
        return absolute

    @classmethod
    def _read_control_file(cls, path: Path, *, maximum: int = 1024 * 1024) -> bytes:
        cls._check_no_symlink_components(path)
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
        )
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
                raise SourceRepositoryError("Git control file is not a bounded regular file")
            data = os.read(descriptor, maximum + 1)
            if len(data) > maximum:
                raise SourceRepositoryError("Git control file exceeds its bound")
            return data
        finally:
            os.close(descriptor)

    def _repository_metadata(
        self,
        root: Path,
        authorized_roots: tuple[Path, ...],
    ) -> tuple[Path, Path]:
        del authorized_roots  # Authorization is enforced by the pinned directory anchors.
        root = Path(os.path.abspath(root))
        root_fd = self._open_authorized_directory(root)
        try:
            marker_info = os.stat(".git", dir_fd=root_fd, follow_symlinks=False)
            if stat.S_ISDIR(marker_info.st_mode):
                git_dir = root / ".git"
            elif stat.S_ISREG(marker_info.st_mode):
                data = self._read_control_at(root_fd, ".git", maximum=4096)
                try:
                    text = data.decode("utf-8").strip()
                except UnicodeError:
                    raise SourceRepositoryError(
                        "Git worktree marker is not valid UTF-8"
                    ) from None
                if not text.startswith("gitdir: ") or "\n" in text or "\r" in text:
                    raise SourceRepositoryError("Git worktree marker is malformed")
                raw = Path(text.removeprefix("gitdir: "))
                git_dir = Path(os.path.abspath(raw if raw.is_absolute() else root / raw))
            else:
                raise SourceRepositoryError("Git metadata marker is unavailable")
        finally:
            os.close(root_fd)

        try:
            git_fd = self._open_authorized_directory(git_dir)
        except SourceAuthorizationError:
            raise SourceAuthorizationError(
                "Git control metadata is outside authorized roots"
            ) from None
        common_dir = git_dir
        common_fd = os.dup(git_fd)
        try:
            try:
                common_text = self._read_control_at(
                    git_fd,
                    "commondir",
                    maximum=4096,
                ).decode("utf-8").strip()
            except FileNotFoundError:
                common_text = ""
            if common_text:
                raw_common = Path(common_text)
                common_dir = Path(
                    os.path.abspath(
                        raw_common if raw_common.is_absolute() else git_dir / raw_common
                    )
                )
                os.close(common_fd)
                try:
                    common_fd = self._open_authorized_directory(common_dir)
                except SourceAuthorizationError:
                    raise SourceAuthorizationError(
                        "Git common metadata is outside authorized roots"
                    ) from None

            for directory_fd, config_name in (
                (common_fd, "config"),
                (git_fd, "config.worktree"),
            ):
                try:
                    raw_config = self._read_control_at(directory_fd, config_name)
                except FileNotFoundError:
                    continue
                try:
                    config_text = raw_config.decode("utf-8")
                except UnicodeError:
                    raise SourceRepositoryError(
                        "Git repository config is not valid UTF-8"
                    ) from None
                forbidden_section = re.search(
                    r"(?im)^\s*\[\s*(include(?:if\b[^]]*)?|filter\b[^]]*|diff\b[^]]*)\s*\]",
                    config_text,
                )
                if forbidden_section:
                    raise SourceRepositoryError(
                        "Git repository config contains an unsafe include/filter/diff section"
                    )

            for alternate_name in ("alternates", "http-alternates"):
                try:
                    alternate_data = self._read_control_at(
                        common_fd,
                        f"objects/info/{alternate_name}",
                    )
                except FileNotFoundError:
                    continue
                if alternate_data.strip():
                    raise SourceRepositoryError(
                        "Git object alternates are not supported by this Source profile"
                    )
        finally:
            os.close(common_fd)
            os.close(git_fd)
        return git_dir, common_dir

    def _resolve_head(self, git_fd: int, common_fd: int) -> str:
        value = self._read_control_at(git_fd, "HEAD", maximum=4096).decode(
            "ascii",
            "strict",
        ).strip()
        visited: set[str] = set()
        for _depth in range(8):
            if not value.startswith("ref: "):
                break
            ref = value.removeprefix("ref: ")
            if (
                ref in visited
                or not ref.startswith("refs/")
                or ".." in ref.split("/")
                or not re.fullmatch(r"refs/[A-Za-z0-9._/-]+", ref)
            ):
                raise SourceRepositoryError("Git HEAD contains an unsafe symbolic ref")
            visited.add(ref)
            value = ""
            for directory_fd in (git_fd, common_fd):
                try:
                    ref_value = self._read_control_at(
                        directory_fd,
                        ref,
                        maximum=4096,
                    )
                except FileNotFoundError:
                    continue
                value = ref_value.decode("ascii", "strict").strip()
                break
            if value:
                continue
            try:
                packed = self._read_control_at(
                    common_fd,
                    "packed-refs",
                    maximum=16 * 1024 * 1024,
                ).decode("ascii", "strict")
            except FileNotFoundError:
                packed = ""
            for line in packed.splitlines():
                if not line or line.startswith(("#", "^")):
                    continue
                try:
                    object_id, packed_ref = line.split(" ", 1)
                except ValueError:
                    raise SourceRepositoryError("Git packed-refs is malformed") from None
                if packed_ref == ref:
                    value = object_id
                    break
            if not value:
                raise SourceRepositoryError("Git HEAD symbolic ref is unresolved")
        else:
            raise SourceRepositoryError("Git HEAD symbolic ref depth exceeded")

        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise SourceRepositoryError(
                "Git HEAD must resolve to one SHA-1 object in this Source profile"
            )
        return value

    def _copy_git_objects(self, source_fd: int, destination: Path) -> None:
        if not stat.S_ISDIR(os.fstat(source_fd).st_mode):
            raise SourceRepositoryError("Git object database is not a directory")
        destination.mkdir(mode=0o700)
        total_bytes = 0
        total_files = 0

        for current, directories, files, current_fd in os.fwalk(
            ".",
            topdown=True,
            follow_symlinks=False,
            dir_fd=source_fd,
        ):
            relative = Path(current)
            depth = len(relative.parts)
            retained: list[str] = []
            for name in directories:
                info = os.stat(name, dir_fd=current_fd, follow_symlinks=False)
                if not stat.S_ISDIR(info.st_mode):
                    raise SourceRepositoryError(
                        "Git object database contains a non-directory component"
                    )
                allowed = (
                    depth == 0 and (name == "pack" or re.fullmatch(r"[0-9a-f]{2}", name))
                )
                if name == "info" and depth == 0:
                    # Deliberately omit alternates, grafts and commit-graph hints.
                    continue
                if not allowed:
                    raise SourceRepositoryError(
                        f"Git object database contains an unsupported directory: {name}"
                    )
                retained.append(name)
            directories[:] = retained

            target_directory = destination / relative
            target_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            for name in files:
                allowed_file = (
                    depth == 1
                    and (
                        (relative.name == "pack" and re.fullmatch(r"[A-Za-z0-9._-]+", name))
                        or (
                            re.fullmatch(r"[0-9a-f]{2}", relative.name)
                            and re.fullmatch(r"[0-9a-f]{38}", name)
                        )
                    )
                )
                if not allowed_file:
                    raise SourceRepositoryError(
                        f"Git object database contains an unsupported file: {name}"
                    )
                descriptor = os.open(
                    name,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                    dir_fd=current_fd,
                )
                try:
                    before = os.fstat(descriptor)
                    if not stat.S_ISREG(before.st_mode):
                        raise SourceRepositoryError(
                            "Git object database contains a non-regular file"
                        )
                    total_files += 1
                    total_bytes += before.st_size
                    if total_files > self._max_git_object_files:
                        raise SourceOversizeError("Git object file count exceeded its bound")
                    if total_bytes > self._max_git_object_bytes:
                        raise SourceOversizeError("Git object database exceeded its byte bound")
                    target = target_directory / name
                    with target.open("xb") as output:
                        remaining = before.st_size
                        while remaining:
                            chunk = os.read(descriptor, min(1024 * 1024, remaining))
                            if not chunk:
                                raise SourceRepositoryError(
                                    "Git object changed while copying the safe view"
                                )
                            output.write(chunk)
                            remaining -= len(chunk)
                    after = os.fstat(descriptor)
                    if (
                        before.st_dev,
                        before.st_ino,
                        before.st_size,
                        before.st_mtime_ns,
                    ) != (
                        after.st_dev,
                        after.st_ino,
                        after.st_size,
                        after.st_mtime_ns,
                    ):
                        raise SourceChangedDuringSnapshot(
                            "Git object changed while copying the safe view"
                        )
                finally:
                    os.close(descriptor)

    @contextmanager
    def _safe_git_view(
        self,
        root: Path,
        git_dir: Path,
        common_dir: Path,
    ) -> Iterator[Path]:
        del root
        git_fd = self._open_authorized_directory(git_dir)
        common_fd = self._open_authorized_directory(common_dir)
        object_fd: int | None = None
        try:
            head = self._resolve_head(git_fd, common_fd)
            with tempfile.TemporaryDirectory(prefix="acs-source-git-") as directory:
                safe_git = Path(directory) / "git"
                safe_git.mkdir(mode=0o700)
                (safe_git / "refs" / "heads").mkdir(mode=0o700, parents=True)
                (safe_git / "refs" / "tags").mkdir(mode=0o700, parents=True)
                (safe_git / "HEAD").write_text(head + "\n", encoding="ascii")
                (safe_git / "config").write_text(
                    "[core]\n\trepositoryformatversion = 0\n\tbare = false\n",
                    encoding="ascii",
                )
                index = self._read_control_at(
                    git_fd,
                    "index",
                    maximum=self._max_metadata_bytes,
                )
                (safe_git / "index").write_bytes(index)
                for base_fd in (git_fd, common_fd):
                    for name in os.listdir(base_fd):
                        if not re.fullmatch(r"sharedindex\.[0-9a-f]{40}", name):
                            continue
                        payload = self._read_control_at(
                            base_fd,
                            name,
                            maximum=self._max_metadata_bytes,
                        )
                        target = safe_git / name
                        if not target.exists():
                            target.write_bytes(payload)
                object_fd = os.open(
                    "objects",
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=common_fd,
                )
                self._copy_git_objects(object_fd, safe_git / "objects")
                yield safe_git
        finally:
            if object_fd is not None:
                os.close(object_fd)
            os.close(common_fd)
            os.close(git_fd)

    @staticmethod
    def _is_relative_to(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
        except ValueError:
            return False
        return True

    @staticmethod
    def _validate_relative_path(value: str) -> str:
        if (
            not value
            or "\x00" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or value.startswith(("/", "\\", "//", "\\\\"))
            or (len(value) >= 2 and value[1] == ":")
            or ":" in value
            or "\\" in value
        ):
            raise SourcePathError(
                f"Source path is absolute, ambiguous, or contains controls: {value!r}"
            )

        parts = value.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise SourcePathError(f"Source path contains traversal: {value!r}")

        return "/".join(parts)

    def _effective_max_bytes(self, request: SourceRequest) -> int:
        if request.max_bytes is None:
            return self._max_bytes
        if type(request.max_bytes) is not int or request.max_bytes <= 0:
            raise ValueError("request.max_bytes must be a positive integer")
        # A request may narrow the service limit but can never expand it.
        return min(self._max_bytes, request.max_bytes)

    def _secret_patterns_for(self, request: SourceRequest) -> tuple[str, ...]:
        # Caller-supplied patterns can add exclusions but cannot remove the
        # service's configured credential/secret exclusions.
        return tuple(dict.fromkeys(self._secret_patterns + tuple(request.secret_patterns)))

    @staticmethod
    def _is_secret_path(path: str, patterns: tuple[str, ...]) -> bool:
        normalized = path.replace("\\", "/")
        basename = normalized.rsplit("/", 1)[-1]
        return any(
            fnmatch.fnmatch(normalized, pattern)
            or fnmatch.fnmatch(basename, pattern)
            for pattern in patterns
        )

    @staticmethod
    def _git_env(root: Path | None = None, git_dir: Path | None = None) -> dict[str, str]:
        # Deliberately omit HOME, credential helpers, XDG config and arbitrary
        # caller environment. Git hooks/pagers/prompts are disabled explicitly.
        environment = {
            "PATH": "/usr/bin:/bin",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_PAGER": "cat",
            "PAGER": "cat",
            "GIT_EDITOR": "true",
            "GIT_SEQUENCE_EDITOR": "true",
            "GIT_OPTIONAL_LOCKS": "0",
            "LC_ALL": "C",
            "LANG": "C",
        }
        if git_dir is not None:
            if root is None:
                raise ValueError("a Git work tree is required with the safe Git directory")
            environment.update(
                {
                    "GIT_DIR": str(git_dir),
                    "GIT_COMMON_DIR": str(git_dir),
                    "GIT_INDEX_FILE": str(git_dir / "index"),
                    "GIT_WORK_TREE": str(root),
                    "GIT_CEILING_DIRECTORIES": str(root.parent),
                }
            )
        return environment

    def _run_git(
        self,
        root: Path | None,
        args: list[str],
        *,
        git_dir: Path | None = None,
        output_limit: int | None = None,
    ) -> bytes:
        if any(not isinstance(arg, str) for arg in args):
            raise ValueError("Git arguments must be strings")
        if output_limit is None:
            output_limit = self._max_metadata_bytes
        if output_limit <= 0:
            raise ValueError("output_limit must be positive")
        if root is not None and git_dir is None:
            source_git_dir, common_dir = self._repository_metadata(
                root,
                self._authorized_roots,
            )
            with self._safe_git_view(root, source_git_dir, common_dir) as safe_git:
                return self._run_git(
                    root,
                    args,
                    git_dir=safe_git,
                    output_limit=output_limit,
                )

        current = os.stat(self._git_executable, follow_symlinks=False)
        if (
            current.st_dev, current.st_ino, current.st_size,
            current.st_mtime_ns, current.st_mode, current.st_uid,
        ) != self._git_identity:
            raise SourceBackendUnavailable("configured Git executable identity changed")
        command = [
            self._git_executable,
            "--no-replace-objects",
            "--literal-pathspecs",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.pager=cat",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.untrackedCache=false",
            "-c",
            "core.attributesFile=/dev/null",
            "-c",
            "core.excludesFile=/dev/null",
            "--no-optional-locks",
            *args,
        ]

        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            try:
                process = subprocess.Popen(
                    command,
                    cwd=str(root) if root is not None else None,
                    env=self._git_env(root, git_dir),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    shell=False,
                    close_fds=True,
                )
            except OSError as exc:
                raise SourceRepositoryError(
                    f"unable to start Git executable: {exc}"
                ) from exc

            try:
                process.wait(timeout=self._command_timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.wait()
                raise SourceRepositoryError(
                    f"Git command timed out: {' '.join(args)}"
                ) from exc

            stdout_file.seek(0)
            output = stdout_file.read(output_limit + 1)
            stderr_file.seek(0)
            error = stderr_file.read(64 * 1024)

        if len(output) > output_limit:
            raise SourceOversizeError(
                f"Git output exceeded bounded limit for command: {' '.join(args)}"
            )

        if process.returncode != 0:
            message = error.decode("utf-8", "replace").strip()
            raise SourceRepositoryError(
                f"Git command failed ({process.returncode}): {' '.join(args)}"
                + (f": {message}" if message else "")
            )

        return output

    def _repository_details(
        self,
        root: Path,
        git_dir: Path | None = None,
    ) -> tuple[str, str, str, str]:
        inside = self._run_git(
            root,
            ["rev-parse", "--is-inside-work-tree"],
            git_dir=git_dir,
        ).decode(
            "ascii",
            "replace",
        ).strip()
        if inside != "true":
            raise SourceRepositoryError("path is not inside a Git work tree")

        top_level = self._run_git(
            root,
            ["rev-parse", "--show-toplevel"],
            git_dir=git_dir,
        ).decode(
            "utf-8",
            "surrogateescape",
        ).strip()
        if not top_level:
            raise SourceRepositoryError("Git did not return a repository root")

        top_path = Path(top_level).resolve(strict=True)
        if top_path != root:
            raise SourceRepositoryError(
                f"wrong or nested repository root: Git reports {top_path}, requested {root}"
            )

        try:
            commit = self._run_git(
                root,
                ["rev-parse", "HEAD"],
                git_dir=git_dir,
            ).decode(
                "ascii",
                "replace",
            ).strip()
            tree = self._run_git(
                root,
                ["rev-parse", "HEAD^{tree}"],
                git_dir=git_dir,
            ).decode(
                "ascii",
                "replace",
            ).strip()
        except SourceRepositoryError as exc:
            raise SourceRepositoryError(
                "repository must have a committed HEAD and tree"
            ) from exc

        if not commit or not tree:
            raise SourceRepositoryError("repository HEAD/tree is empty")

        return commit, tree, top_level, inside

    def _scan_tree(self, root: Path) -> None:
        count = 0

        for current, directories, files in os.walk(
            root,
            topdown=True,
            followlinks=False,
        ):
            current_path = Path(current)

            retained_directories: list[str] = []
            for name in directories:
                entry = current_path / name
                info = entry.lstat()

                if stat.S_ISLNK(info.st_mode):
                    raise SourcePathError(
                        f"Source tree contains a symlink/reparse directory: "
                        f"{entry.relative_to(root)}"
                    )

                if name == ".git":
                    if current_path == root:
                        # The repository control directory is not Source
                        # content and is never copied to the CAS.
                        continue
                    raise SourceRepositoryError(
                        f"nested repository detected at {entry.relative_to(root)}"
                    )

                if not stat.S_ISDIR(info.st_mode):
                    raise SourcePathError(
                        f"Source tree contains a non-directory path component: "
                        f"{entry.relative_to(root)}"
                    )

                retained_directories.append(name)

            directories[:] = retained_directories

            for name in files:
                entry = current_path / name
                info = entry.lstat()

                if name == ".git" and current_path == root:
                    # Worktrees can use a .git file. It is control metadata and
                    # never enters Source contents.
                    continue

                if stat.S_ISLNK(info.st_mode):
                    raise SourcePathError(
                        f"Source tree contains a symlink/reparse file: "
                        f"{entry.relative_to(root)}"
                    )

                if not stat.S_ISREG(info.st_mode):
                    raise SourcePathError(
                        f"Source tree contains a non-regular file: "
                        f"{entry.relative_to(root)}"
                    )

                count += 1
                if count > self._max_files:
                    raise SourceOversizeError(
                        f"Source file count exceeded limit {self._max_files}"
                    )

    @staticmethod
    def _decode_git_path(value: bytes) -> str:
        return value.decode("utf-8", "surrogateescape")

    def _tree_entries(
        self,
        root: Path,
        git_dir: Path | None = None,
    ) -> dict[str, str]:
        raw = self._run_git(
            root,
            ["ls-tree", "-r", "-z", "--full-tree", "HEAD"],
            git_dir=git_dir,
            output_limit=self._max_metadata_bytes,
        )
        entries: dict[str, str] = {}

        for record in raw.split(b"\x00"):
            if not record:
                continue
            try:
                header, path_bytes = record.split(b"\t", 1)
            except ValueError as exc:
                raise SourceRepositoryError("malformed Git tree record") from exc

            fields = header.split(b" ")
            if len(fields) != 3:
                raise SourceRepositoryError("malformed Git tree header")

            mode_bytes, object_type, _object_id = fields
            path = self._validate_relative_path(self._decode_git_path(path_bytes))
            mode = mode_bytes.decode("ascii", "strict")

            if object_type != b"blob":
                raise SourceRepositoryError(
                    f"unsupported Git tree object for Source path {path}: "
                    f"{object_type!r}"
                )
            if mode == "120000":
                raise SourcePathError(
                    f"tracked Git symlink is not admissible: {path}"
                )

            entries[path] = mode

        if not entries:
            raise SourceRepositoryError("Git HEAD tree contains no files")

        return entries

    def _status_entries(self, raw: bytes) -> list[tuple[str, str]]:
        records = raw.split(b"\x00")
        entries: list[tuple[str, str]] = []
        index = 0

        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                continue

            text = self._decode_git_path(record)
            if len(text) < 3:
                raise SourceRepositoryError("malformed Git status record")

            xy = text[:2]
            raw_path = text[3:]
            if raw_path.endswith("/"):
                raise SourceRepositoryError(
                    "untracked directory was not expanded; nested repositories are not admissible"
                )
            path = self._validate_relative_path(raw_path)

            if "R" in xy or "C" in xy:
                if index >= len(records) or not records[index]:
                    raise SourceRepositoryError(
                        "Git rename/copy status lacks destination path"
                    )
                destination = self._validate_relative_path(
                    self._decode_git_path(records[index])
                )
                index += 1
                entries.append((xy, path))
                entries.append((xy, destination))
            else:
                entries.append((xy, path))

        return entries

    def _open_relative(self, root: Path, relative_path: str) -> int:
        path = self._validate_relative_path(relative_path)
        parts = path.split("/")
        root_flags = (
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | os.O_CLOEXEC
            | os.O_NONBLOCK
        )
        file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK

        root_fd = self._open_authorized_directory(root)
        parent_fd = root_fd
        opened_children: list[int] = []

        try:
            for part in parts[:-1]:
                child_fd = os.open(
                    part,
                    root_flags,
                    dir_fd=parent_fd,
                )
                opened_children.append(child_fd)
                parent_fd = child_fd

            file_fd = os.open(
                parts[-1],
                file_flags,
                dir_fd=parent_fd,
            )
        except BaseException:
            for descriptor in reversed(opened_children):
                os.close(descriptor)
            os.close(root_fd)
            raise

        for descriptor in reversed(opened_children):
            os.close(descriptor)
        os.close(root_fd)
        return file_fd

    def _read_bounded(
        self,
        root: Path,
        relative_path: str,
        max_bytes: int,
    ) -> tuple[bytes, tuple[int, int, int, int, int]]:
        descriptor = self._open_relative(root, relative_path)

        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise SourcePathError(
                    f"Source path is not a regular file: {relative_path}"
                )
            if before.st_size > max_bytes:
                raise SourceOversizeError(
                    f"Source file exceeds max_bytes: {relative_path}"
                )

            payload = bytearray()
            while True:
                chunk = os.read(
                    descriptor,
                    min(64 * 1024, max_bytes - len(payload) + 1),
                )
                if not chunk:
                    break
                payload.extend(chunk)
                if len(payload) > max_bytes:
                    raise SourceOversizeError(
                        f"Source file exceeded max_bytes while reading: "
                        f"{relative_path}"
                    )

            after = os.fstat(descriptor)
            before_signature = (
                int(before.st_dev),
                int(before.st_ino),
                int(before.st_size),
                int(before.st_mtime_ns),
                int(stat.S_IMODE(before.st_mode)),
            )
            after_signature = (
                int(after.st_dev),
                int(after.st_ino),
                int(after.st_size),
                int(after.st_mtime_ns),
                int(stat.S_IMODE(after.st_mode)),
            )
            if before_signature != after_signature:
                raise SourceChangedDuringSnapshot(
                    f"Source file changed while being read: {relative_path}"
                )

            return bytes(payload), after_signature
        finally:
            os.close(descriptor)

    @staticmethod
    def _artifact_dict(value: object) -> dict[str, Any]:
        if hasattr(value, "model_dump"):
            dumped = value.model_dump(mode="json")
            if isinstance(dumped, dict):
                return dict(dumped)
        if isinstance(value, Mapping):
            return dict(value)
        raise SourceArtifactError("artifact store returned an invalid reference")

    def _store_verified(
        self,
        payload: bytes,
        *,
        kind: str,
        media_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        expected_digest = _sha256(payload)

        try:
            reference = self._artifact_store.put_bytes(
                payload,
                kind=kind,
                media_type=media_type,
            )
            self._artifact_store.verify(reference)
            readback = self._artifact_store.read(reference)
        except Exception as exc:
            raise SourceArtifactError(
                f"artifact store rejected Source bytes: {exc}"
            ) from exc

        if readback != payload:
            raise SourceArtifactError(
                "artifact store readback differs from Source bytes"
            )

        reference_dict = self._artifact_dict(reference)
        if reference_dict.get("sha256") != expected_digest:
            raise SourceArtifactError(
                "artifact reference digest does not match actual Source bytes"
            )
        if reference_dict.get("size_bytes") != len(payload):
            raise SourceArtifactError(
                "artifact reference size does not match actual Source bytes"
            )
        if reference_dict.get("immutable") is not True:
            raise SourceArtifactError(
                "artifact reference is not immutable"
            )
        return reference_dict

    @staticmethod
    def _file_media_type(path: str) -> str:
        return mimetypes.guess_type(path)[0] or "application/octet-stream"

    @staticmethod
    def _manifest_payload(snapshot: SourceSnapshot) -> dict[str, Any]:
        value = snapshot.manifest_dict(include_digest=False)
        # The manifest cannot recursively contain its own CAS reference.
        value["manifest_ref"] = None
        return value

    def _snapshot_token(
        self,
        root: Path,
        git_dir: Path | None = None,
    ) -> tuple[str, str, bytes]:
        commit, tree, _top, _inside = self._repository_details(root, git_dir)
        status = self._run_git(
            root,
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
            git_dir=git_dir,
            output_limit=self._max_metadata_bytes,
        )
        return commit, tree, status

    def _diff_for_paths(
        self,
        root: Path,
        paths: Iterable[str],
        *,
        git_dir: Path | None = None,
    ) -> bytes:
        ordered = tuple(sorted(dict.fromkeys(paths)))
        if not ordered:
            return b""
        chunks: list[bytes] = []
        batch: list[str] = []
        batch_bytes = 0
        total_bytes = 0

        def flush() -> None:
            nonlocal batch, batch_bytes, total_bytes
            if not batch:
                return
            remaining = self._max_metadata_bytes - total_bytes
            if remaining <= 0:
                raise SourceOversizeError("Git diff exceeded its bounded limit")
            payload = self._run_git(
                root,
                [
                    "diff",
                    "--binary",
                    "--no-ext-diff",
                    "--no-textconv",
                    "HEAD",
                    "--",
                    *batch,
                ],
                git_dir=git_dir,
                output_limit=remaining,
            )
            chunks.append(payload)
            total_bytes += len(payload)
            batch = []
            batch_bytes = 0

        for path in ordered:
            encoded_size = len(os.fsencode(path)) + 1
            if batch and (len(batch) >= 512 or batch_bytes + encoded_size > 64 * 1024):
                flush()
            batch.append(path)
            batch_bytes += encoded_size
        flush()
        return b"".join(chunks)

    def _diff_for_captured_files(
        self,
        root: Path,
        paths: Iterable[str],
        captured: Mapping[str, tuple[bytes, str]],
    ) -> bytes:
        git_dir, common_dir = self._repository_metadata(
            root,
            self._authorized_roots,
        )
        with (
            self._safe_git_view(root, git_dir, common_dir) as safe_git,
            tempfile.TemporaryDirectory(prefix="acs-source-tree-") as directory,
        ):
            worktree = Path(directory)
            for path, (payload, mode) in captured.items():
                normalized = self._validate_relative_path(path)
                target = worktree.joinpath(*normalized.split("/"))
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                target.write_bytes(payload)
                try:
                    executable = bool(int(mode, 8) & 0o111)
                except ValueError:
                    raise SourceRepositoryError(
                        f"Source file mode is invalid: {path}"
                    ) from None
                target.chmod(0o700 if executable else 0o600)
            return self._diff_for_paths(
                worktree,
                paths,
                git_dir=safe_git,
            )

    def _authorize(
        self,
        request: SourceRequest,
        authorize: _AUTHORIZER | None,
    ) -> None:
        if authorize is None:
            raise SourceAuthorizationError(
                "an authenticated Source authorization callback is required"
            )

        try:
            decision = authorize(request)
        except Exception:  # noqa: BLE001 - authorization plugin boundary must fail closed.
            raise SourceAuthorizationError(
                "Source authorization callback failed"
            ) from None

        if not decision:
            raise SourceAuthorizationError(
                "Source authorization callback denied the request"
            )

    def admit(
        self,
        request: SourceRequest,
        authorize: _AUTHORIZER | None,
    ) -> SourceSnapshot:
        """Admit and seal one immutable Source snapshot."""

        self._authorize(request, authorize)

        for field in (
            "tenant_id",
            "scope_id",
            "root_id",
            "route_id",
        ):
            _validate_text(getattr(request, field), field)

        root = self._prepare_repository_root(
            request.root,
            self._authorized_roots,
        )
        self._repository_metadata(root, self._authorized_roots)
        max_bytes = self._effective_max_bytes(request)
        secret_patterns = self._secret_patterns_for(request)

        source_commit, source_tree, repository_root, _inside = (
            self._repository_details(root)
        )

        if (
            request.expected_commit is not None
            and request.expected_commit != source_commit
        ):
            raise SourceCommitMismatch(
                "requested commit does not match the actual repository HEAD"
            )
        if (
            request.expected_tree is not None
            and request.expected_tree != source_tree
        ):
            raise SourceCommitMismatch(
                "requested tree does not match the actual repository HEAD tree"
            )

        tree_entries = self._tree_entries(root)
        status_raw = self._run_git(
            root,
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
            output_limit=self._max_metadata_bytes,
        )
        status_entries = self._status_entries(status_raw)
        dirty = bool(status_entries)

        changed_paths = [path for _xy, path in status_entries]
        changed_secret_paths = sorted(
            {
                path
                for path in changed_paths
                if self._is_secret_path(path, secret_patterns)
            }
        )
        if changed_secret_paths:
            raise SourceSecretError(
                "changed credential/secret paths are excluded and cannot be "
                f"read or diffed: {changed_secret_paths}"
            )

        if dirty and not request.allow_dirty:
            raise SourceDirtyError(
                "Source repository is dirty; allow_dirty=True is required"
            )

        untracked_paths = sorted(
            {
                path
                for xy, path in status_entries
                if xy == "??"
            }
        )
        if untracked_paths and not request.include_untracked:
            raise SourceDirtyError(
                "untracked Source files are present but include_untracked=False"
            )

        # Capture HEAD-relative tracked files plus staged/working-tree additions.
        paths_to_read: set[str] = set(tree_entries)
        for xy, path in status_entries:
            if xy == "??":
                continue
            if "D" in xy:
                continue
            paths_to_read.add(path)

        selected_paths = paths_to_read | set(untracked_paths)
        if len(selected_paths) > self._max_files:
            raise SourceOversizeError(
                f"Source file count exceeded limit {self._max_files}"
            )
        diff_paths = tuple(
            sorted(
                path
                for path in paths_to_read
                if not self._is_secret_path(path, secret_patterns)
            )
        )

        files: list[SourceFile] = []
        signatures: dict[str, tuple[int, int, int, int, int]] = {}
        captured_payloads: dict[str, tuple[bytes, str]] = {}
        excluded_paths: set[str] = set()
        total_source_bytes = 0

        for path in sorted(paths_to_read):
            if self._is_secret_path(path, secret_patterns):
                excluded_paths.add(path)
                continue

            try:
                remaining_bytes = max_bytes - total_source_bytes
                if remaining_bytes <= 0:
                    raise SourceOversizeError("Source snapshot exceeded max_bytes")
                payload, signature = self._read_bounded(
                    root,
                    path,
                    remaining_bytes,
                )
            except FileNotFoundError:
                if dirty:
                    # Deleted/renamed old paths remain represented by the Git
                    # diff/status metadata; they have no current bytes to copy.
                    continue
                raise SourceChangedDuringSnapshot(
                    f"tracked Source path disappeared during snapshot: {path}"
                ) from None

            signatures[path] = signature
            ref = self._store_verified(
                payload,
                kind="source",
                media_type=self._file_media_type(path),
            )
            mode = "100755" if signature[4] & 0o111 else "100644"
            total_source_bytes += len(payload)
            captured_payloads[path] = (payload, mode)
            files.append(
                SourceFile(
                    path=path,
                    mode=mode,
                    size_bytes=len(payload),
                    sha256=_sha256(payload),
                    artifact_ref=ref,
                    kind="tracked" if path in tree_entries else "working_tree",
                )
            )

        untracked_entries: list[dict[str, Any]] = []
        for path in untracked_paths:
            if self._is_secret_path(path, secret_patterns):
                excluded_paths.add(path)
                continue

            remaining_bytes = max_bytes - total_source_bytes
            if remaining_bytes <= 0:
                raise SourceOversizeError("Source snapshot exceeded max_bytes")
            payload, signature = self._read_bounded(
                root,
                path,
                remaining_bytes,
            )
            signatures[path] = signature
            ref = self._store_verified(
                payload,
                kind="source",
                media_type=self._file_media_type(path),
            )
            mode = "100755" if signature[4] & 0o111 else "100644"
            source_file = SourceFile(
                path=path,
                mode=mode,
                size_bytes=len(payload),
                sha256=_sha256(payload),
                artifact_ref=ref,
                kind="untracked",
            )
            files.append(source_file)
            total_source_bytes += len(payload)
            captured_payloads[path] = (payload, mode)
            untracked_entries.append(source_file.to_dict())

        diff_payload = self._diff_for_captured_files(
            root,
            diff_paths,
            captured_payloads,
        )
        diff_ref = self._store_verified(
            diff_payload,
            kind="manifest",
            media_type="text/plain",
        )

        untracked_manifest_payload = _canonical_json(
            {
                "schema_version": "acs-source-untracked-manifest/1",
                "paths": untracked_entries,
                "excluded_paths": sorted(excluded_paths),
            }
        )
        untracked_manifest_ref = self._store_verified(
            untracked_manifest_payload,
            kind="manifest",
            media_type="application/json",
        )

        observed_at = datetime.now(UTC).isoformat()
        provisional = SourceSnapshot(
            schema_version=self.SCHEMA_VERSION,
            tenant_id=request.tenant_id,
            scope_id=request.scope_id,
            root_id=request.root_id,
            route_id=request.route_id,
            repository_root=repository_root,
            source_commit=source_commit,
            source_tree=source_tree,
            git_version=self._run_git(
                root,
                ["--version"],
                output_limit=64 * 1024,
            ).decode("utf-8", "replace").strip(),
            git_executable=self._git_executable,
            git_executable_sha256=self._git_sha256,
            os_name=platform.platform(),
            python_version=platform.python_version(),
            observed_at=observed_at,
            files=tuple(sorted(files, key=lambda item: item.path)),
            diff_ref=diff_ref,
            untracked_manifest_ref=untracked_manifest_ref,
            manifest_ref={},
            excluded_paths=tuple(sorted(excluded_paths)),
            dirty=dirty,
            working_tree_status_sha256=_sha256(status_raw),
            source_class="directly_verified",
            snapshot_sha256="",
        )

        manifest_payload = _canonical_json(
            self._manifest_payload(provisional)
        )
        manifest_ref = self._store_verified(
            manifest_payload,
            kind="manifest",
            media_type="application/json",
        )
        snapshot = replace(
            provisional,
            manifest_ref=manifest_ref,
            snapshot_sha256=str(manifest_ref["sha256"]),
        )

        # Final source-integrity check. Git identity/status and every admitted
        # file must still match the bytes that entered the CAS.
        final_commit, final_tree, final_status = self._snapshot_token(root)
        if (
            final_commit != source_commit
            or final_tree != source_tree
            or final_status != status_raw
        ):
            raise SourceChangedDuringSnapshot(
                "Git commit/tree/status changed during Source snapshot"
            )

        for path, original_signature in signatures.items():
            try:
                reread, reread_signature = self._read_bounded(
                    root,
                    path,
                    max_bytes,
                )
            except FileNotFoundError as exc:
                raise SourceChangedDuringSnapshot(
                    f"Source path disappeared during final readback: {path}"
                ) from exc
            expected_file = next(
                (item for item in snapshot.files if item.path == path),
                None,
            )
            if expected_file is None:
                continue
            if (
                reread_signature != original_signature
                or _sha256(reread) != expected_file.sha256
            ):
                raise SourceChangedDuringSnapshot(
                    f"Source bytes changed during final readback: {path}"
                )

        return snapshot

    def readback(
        self,
        snapshot: SourceSnapshot,
        authorize: _AUTHORIZER | None,
    ) -> SourceSnapshot:
        """Verify CAS bytes and current Source readback for a snapshot."""

        request = SourceRequest(
            root=snapshot.repository_root,
            tenant_id=snapshot.tenant_id,
            scope_id=snapshot.scope_id,
            root_id=snapshot.root_id,
            route_id=snapshot.route_id,
            expected_commit=snapshot.source_commit,
            expected_tree=snapshot.source_tree,
            allow_dirty=snapshot.dirty,
            include_untracked=True,
        )
        self._authorize(request, authorize)

        root = self._prepare_repository_root(
            snapshot.repository_root,
            self._authorized_roots,
        )
        self._repository_metadata(root, self._authorized_roots)
        current_commit, current_tree, _top, _inside = (
            self._repository_details(root)
        )
        if (
            current_commit != snapshot.source_commit
            or current_tree != snapshot.source_tree
        ):
            raise SourceChangedDuringSnapshot(
                "Source commit/tree no longer matches the admitted snapshot"
            )

        current_status = self._run_git(
            root,
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
            output_limit=self._max_metadata_bytes,
        )
        if _sha256(current_status) != snapshot.working_tree_status_sha256:
            raise SourceChangedDuringSnapshot(
                "Source working-tree status changed after admission"
            )

        def artifact_ref(value: Mapping[str, Any]) -> ArtifactRef:
            try:
                return ArtifactRef.model_validate(value, strict=True)
            except Exception as exc:
                raise SourceReadbackError(
                    "snapshot contains an invalid typed ArtifactRef"
                ) from exc

        try:
            manifest_reference = artifact_ref(snapshot.manifest_ref)
            manifest_bytes = self._artifact_store.read(manifest_reference)
            self._artifact_store.verify(manifest_reference)

            if _sha256(manifest_bytes) != snapshot.snapshot_sha256:
                raise SourceReadbackError(
                    "snapshot manifest digest does not match its CAS bytes"
                )

            stored_manifest = json.loads(manifest_bytes.decode("utf-8"))
            if not isinstance(stored_manifest, dict):
                raise SourceReadbackError("snapshot manifest is not a JSON object")

            stored_normalized = dict(stored_manifest)
            stored_normalized["manifest_ref"] = None
            stored_normalized.pop("snapshot_sha256", None)

            expected_normalized = self._manifest_payload(snapshot)
            if stored_normalized != expected_normalized:
                raise SourceReadbackError(
                    "snapshot manifest content differs from the immutable snapshot"
                )

            diff_reference = artifact_ref(snapshot.diff_ref)
            diff_bytes = self._artifact_store.read(diff_reference)
            stored_files: dict[str, tuple[bytes, str]] = {}
            for item in snapshot.files:
                reference = artifact_ref(item.artifact_ref)
                stored_bytes = self._artifact_store.read(reference)
                if (
                    len(stored_bytes) != item.size_bytes
                    or _sha256(stored_bytes) != item.sha256
                ):
                    raise SourceReadbackError(
                        f"CAS Source artifact mismatch: {item.path}"
                    )
                stored_files[item.path] = (stored_bytes, item.mode)
            current_tree_entries = self._tree_entries(root)
            current_status_entries = self._status_entries(current_status)
            current_diff_paths: set[str] = set(current_tree_entries)
            for xy, path in current_status_entries:
                if xy != "??" and "D" not in xy:
                    current_diff_paths.add(path)
            current_diff = self._diff_for_captured_files(
                root,
                current_diff_paths - set(snapshot.excluded_paths),
                stored_files,
            )
            if diff_bytes != current_diff:
                raise SourceChangedDuringSnapshot(
                    "Git diff changed after Source admission"
                )

            untracked_reference = artifact_ref(snapshot.untracked_manifest_ref)
            untracked_bytes = self._artifact_store.read(untracked_reference)
            if not untracked_bytes:
                raise SourceReadbackError(
                    "untracked manifest readback is empty"
                )

            for item in snapshot.files:
                stored_bytes = stored_files[item.path][0]

                current_bytes, current_signature = self._read_bounded(
                    root,
                    item.path,
                    self._effective_max_bytes(request),
                )
                if (
                    len(current_bytes) != item.size_bytes
                    or _sha256(current_bytes) != item.sha256
                ):
                    raise SourceChangedDuringSnapshot(
                        f"Source file changed after admission: {item.path}"
                    )
                current_mode = "100755" if current_signature[4] & 0o111 else "100644"
                if current_mode != item.mode:
                    raise SourceChangedDuringSnapshot(
                        f"Source file mode changed after admission: {item.path}"
                    )
        except SourceError:
            raise
        except Exception as exc:
            raise SourceReadbackError(
                f"Source readback failed: {exc}"
            ) from exc

        return snapshot

    # Explicit aliases make the boundary discoverable without adding another
    # mutable authority or a second source of policy.
    admit_source = admit
    readback_source = readback
