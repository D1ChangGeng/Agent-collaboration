"""Descriptor-based admission for receiver-owned POSIX paths."""
from __future__ import annotations

import os
import stat
from pathlib import Path

PLATFORM = os.name


class PathSecurityRejected(ValueError):
    pass


def require_posix() -> None:
    if PLATFORM != "posix" or not hasattr(os, "geteuid"):
        raise PathSecurityRejected("receiver path security requires POSIX descriptor semantics")


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


def private_parent(path: str | Path) -> tuple[int, tuple[int, int, int, int, int]]:
    """Open every parent component without following links; require a private leaf."""
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
    mode = stat.S_IMODE(info.st_mode)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid()
            or (private and mode != 0o600)
            or (not private and mode & 0o022)):
        requirement = "owner mode 0600" if private else "an owner-controlled regular file"
        raise PathSecurityRejected(f"receiver file requires {requirement}")
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_nlink


def open_validated_file(path: str | Path, *, private: bool = True) -> tuple[int, tuple[int, ...]]:
    source = Path(path)
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
