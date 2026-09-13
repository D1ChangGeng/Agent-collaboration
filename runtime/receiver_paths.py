"""Descriptor-based admission for receiver-owned POSIX paths."""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

PLATFORM = os.name


class PathSecurityRejected(ValueError):
    pass


def require_posix() -> None:
    if PLATFORM != "posix" or not hasattr(os, "geteuid"):
        raise PathSecurityRejected("receiver path security requires POSIX descriptor semantics")


def _windows_private(path: Path) -> None:
    if not path.is_absolute() or not path.exists():
        raise PathSecurityRejected("receiver Windows path is unavailable")
    for component in (*reversed(path.parents), path):
        try:
            info = component.lstat()
        except OSError:
            raise PathSecurityRejected("receiver Windows path component is unavailable") from None
        if getattr(info, "st_file_attributes", 0) & 0x400:
            raise PathSecurityRejected("receiver Windows path contains a reparse component")
    result = subprocess.run(
        ["icacls.exe", str(path)], capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=10, check=False,
    )
    text = result.stdout + result.stderr
    broad = (
        "Everyone:", "BUILTIN\\Users:", "Authenticated Users:",
        "INTERACTIVE:", "ANONYMOUS LOGON:", "APPLICATION PACKAGE AUTHORITY\\ALL APPLICATION PACKAGES:",
    )
    if result.returncode != 0 or any(name.casefold() in text.casefold() for name in broad):
        raise PathSecurityRejected("receiver Windows ACL is not private")


def _windows_open(path: Path) -> int:
    from runtime.operator_files import OperatorFileError, _windows_open as open_handle

    try:
        return open_handle(path)
    except OperatorFileError:
        raise PathSecurityRejected("receiver Windows file handle rejected") from None


def _identity(info) -> tuple[int, ...]:
    return (
        info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_nlink,
        getattr(info, "st_birthtime_ns", 0), getattr(info, "st_file_attributes", 0),
        getattr(info, "st_reparse_tag", 0),
    )


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


def private_parent(path: str | Path) -> tuple[int, tuple[int, ...]]:
    """Open every parent component without following links; require a private leaf."""
    if PLATFORM == "nt":
        source = Path(path)
        _windows_private(source)
        return -1, _identity(source.stat(follow_symlinks=False))
    require_posix()
    source = Path(path)
    if not source.is_absolute():
        raise PathSecurityRejected("receiver path must be absolute")
    descriptor = os.open(source.anchor, _directory_flags())
    try:
        for part in source.parts[1:]:
            child = os.open(part, _directory_flags(), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        info = os.fstat(descriptor)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise PathSecurityRejected("receiver parent requires owner uid and mode 0700")
        return descriptor, (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)
    except BaseException:
        os.close(descriptor)
        raise


def _file_identity(descriptor: int, *, private: bool) -> tuple[int, int, int, int, int, int]:
    info = os.fstat(descriptor)
    if PLATFORM == "nt":
        if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise PathSecurityRejected("receiver Windows file requires a regular non-reparse handle")
        return _identity(info)
    mode = stat.S_IMODE(info.st_mode)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid()
            or (private and mode != 0o600)
            or (not private and mode & 0o022)):
        requirement = "owner mode 0600" if private else "an owner-controlled regular file"
        raise PathSecurityRejected(f"receiver file requires {requirement}")
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_nlink


def descriptor_file_identity(descriptor: int, *, private: bool = True) -> tuple[int, ...]:
    return _file_identity(descriptor, private=private)


def open_validated_file(path: str | Path, *, private: bool = True) -> tuple[int, tuple[int, ...]]:
    source = Path(path)
    if PLATFORM == "nt":
        _windows_private(source.parent)
        if private:
            _windows_private(source)
        descriptor = _windows_open(source)
        try:
            identity = _file_identity(descriptor, private=private)
            if identity != _identity(source.stat(follow_symlinks=False)):
                raise PathSecurityRejected("receiver Windows path and handle identity differ")
            return descriptor, identity
        except BaseException:
            os.close(descriptor)
            raise
    parent = None
    try:
        parent, _ = private_parent(source.parent)
        descriptor = os.open(
            source.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            dir_fd=parent,
        )
        try:
            identity = _file_identity(descriptor, private=private)
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor, identity
    except OSError:
        raise PathSecurityRejected("receiver file open rejected") from None
    finally:
        if parent is not None:
            os.close(parent)


def validated_file_identity(path: str | Path, *, private: bool = True) -> tuple[int, ...]:
    descriptor, identity = open_validated_file(path, private=private)
    os.close(descriptor)
    return identity


def optional_private_file_identity(path: str | Path) -> tuple[int, ...] | None:
    """Validate an existing private file, or prove that its private parent has no entry."""
    source = Path(path)
    if PLATFORM == "nt":
        _windows_private(source.parent)
        if not source.exists():
            return None
        return validated_file_identity(source, private=True)
    parent = None
    descriptor = None
    try:
        parent, _ = private_parent(source.parent)
        try:
            descriptor = os.open(
                source.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=parent,
            )
        except FileNotFoundError:
            return None
        return _file_identity(descriptor, private=True)
    except OSError:
        raise PathSecurityRejected("receiver file open rejected") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent is not None:
            os.close(parent)


def ensure_private_database(path: str | Path) -> tuple[int, ...]:
    """Create a missing journal exclusively at 0600, or validate the existing file."""
    source = Path(path)
    if PLATFORM == "nt":
        _windows_private(source.parent)
        if not source.exists():
            try:
                descriptor = os.open(
                    source, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_BINARY | os.O_NOINHERIT,
                )
            except OSError:
                raise PathSecurityRejected("receiver Windows journal creation rejected") from None
            else:
                os.close(descriptor)
        _windows_private(source)
        return validated_file_identity(source, private=True)
    parent = None
    descriptor = None
    try:
        parent, _ = private_parent(source.parent)
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
        try:
            descriptor = os.open(source.name, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
            os.fchmod(descriptor, 0o600)
        except FileExistsError:
            descriptor = os.open(source.name, flags, dir_fd=parent)
        return _file_identity(descriptor, private=True)
    except OSError:
        raise PathSecurityRejected("receiver journal open or creation rejected") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent is not None:
            os.close(parent)
