"""Bounded operator configuration reads with descriptor/path identity checks."""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path


class OperatorFileError(RuntimeError):
    pass


def _identity(info):
    # On Windows, path stat may retain creation-time st_ctime while fstat uses
    # change-time st_ctime. Birth time is the common object-identity field.
    generation_time = getattr(info, "st_birthtime_ns", None) if os.name == "nt" else info.st_ctime_ns
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_size, info.st_mtime_ns, generation_time,
            getattr(info, "st_file_attributes", 0), getattr(info, "st_reparse_tag", 0))


def _directory_identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            getattr(info, "st_file_attributes", 0), getattr(info, "st_reparse_tag", 0))


def _directory(path):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    descriptor = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _windows_open(path):
    # Windows config support establishes reparse/handle identity, not an ACL.
    # Secret-file references remain POSIX-only in PrivateReference.resolve.
    import ctypes
    import msvcrt
    from ctypes import wintypes

    if not re.match(r"^[A-Za-z]:[\\/]", str(path)):
        raise OperatorFileError("configuration requires a local filesystem path")
    for component in (*reversed(path.parents), path):
        info = component.lstat()
        if getattr(info, "st_file_attributes", 0) & 0x400:
            raise OperatorFileError("configuration contains a reparse component")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    final_path = kernel.GetFinalPathNameByHandleW
    final_path.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    final_path.restype = wintypes.DWORD
    handle = create(str(path), 0x80000000, 7, None, 3, 0x00200000 | 0x02000000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OperatorFileError("configuration handle is unavailable")
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = final_path(handle, buffer, len(buffer), 0)
        if not 0 < length < len(buffer):
            raise OperatorFileError("configuration handle path is unavailable")
        actual = buffer.value.removeprefix("\\\\?\\")
        if os.path.normcase(os.path.normpath(actual)) != os.path.normcase(str(path)):
            raise OperatorFileError("configuration handle path differs")
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)
        handle = None  # Descriptor now owns the OS handle.
        return descriptor
    finally:
        if handle is not None:
            close(handle)


def read_operator_file(value, *, maximum=65536):
    descriptor = parent = None
    try:
        path = Path(value)
        if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
            raise OperatorFileError("configuration path is invalid")
        before_path = path.lstat()
        if not stat.S_ISREG(before_path.st_mode) or getattr(before_path, "st_file_attributes", 0) & 0x400:
            raise OperatorFileError("configuration is not a regular file")
        if os.name == "posix":
            parent = _directory(path.parent)
            parent_info = os.fstat(parent)
            if parent_info.st_uid != os.getuid() or stat.S_IMODE(parent_info.st_mode) & 0o022:
                raise OperatorFileError("configuration directory is not operator controlled")
            descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
        elif os.name == "nt":
            parent_info = path.parent.lstat()
            descriptor = _windows_open(path)
        else:
            raise OperatorFileError("configuration file backend is unsupported")
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_size > maximum
                or _identity(before) != _identity(before_path)):
            raise OperatorFileError("configuration file identity or size differs")
        if os.name == "posix" and (before.st_uid != os.getuid() or stat.S_IMODE(before.st_mode) & 0o077):
            raise OperatorFileError("configuration file is not owner-only")
        data = bytearray()
        while len(data) <= maximum:
            chunk = os.read(descriptor, min(65536, maximum + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        # Windows may defer timestamp updates while handles remain open. Compare
        # actual bytes again on the same bounded handle, not just cached stats.
        os.lseek(descriptor, 0, os.SEEK_SET)
        readback = bytearray()
        while len(readback) <= maximum:
            chunk = os.read(descriptor, min(65536, maximum + 1 - len(readback)))
            if not chunk:
                break
            readback.extend(chunk)
        if (len(data) > maximum or len(data) != before.st_size
                or readback != data
                or _identity(os.fstat(descriptor)) != _identity(before)
                or _identity(path.lstat()) != _identity(before)
                or _directory_identity(path.parent.lstat()) != _directory_identity(parent_info)
                or parent is not None and _directory_identity(os.fstat(parent)) != _directory_identity(parent_info)):
            raise OperatorFileError("configuration changed during read")
        return bytes(data)
    except OperatorFileError:
        raise
    except (OSError, ValueError, TypeError):
        raise OperatorFileError("configuration file is unavailable") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent is not None:
            os.close(parent)
