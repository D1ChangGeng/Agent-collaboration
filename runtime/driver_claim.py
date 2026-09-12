"""Journal-owned kernel reservations; public descriptors do not own the lock."""
from __future__ import annotations

import os
import re
import secrets
import stat
import threading
from pathlib import Path


class ClaimRejected(RuntimeError):
    pass


def _file_identity(descriptor):
    info = os.fstat(descriptor)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or getattr(info, "st_file_attributes", 0) & 0x400):
        raise ClaimRejected("claim is not a private linked regular file")
    if os.name == "posix" and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600):
        raise ClaimRejected("claim requires owner uid and mode 0600")
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid


def _private_parent(path):
    path = Path(path)
    if os.name == "nt":
        if not re.match(r"^[A-Za-z]:[\\/]", str(path)):
            raise ClaimRejected("claim requires a local filesystem path")
        for component in (*reversed(path.parents), path):
            info = component.lstat()
            if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ClaimRejected("claim parent contains a reparse component")
        # Windows ACL admission remains the Node host's responsibility. These
        # checks prove directory identity/reparse exclusion, not owner-only ACLs.
        return None, (info.st_dev, info.st_ino, info.st_mode, getattr(info, "st_file_attributes", 0))
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    descriptor = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        info = os.fstat(descriptor)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ClaimRejected("claim parent requires owner uid and mode 0700")
        return descriptor, (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)
    except BaseException:
        os.close(descriptor)
        raise


def _windows_owner(path):
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    # Only readers may share the private RW file object. A competitor requesting
    # RW ownership cannot open it until all owner/witness handles are closed.
    handle = create(str(path), 0xC0000000, 1, None, 4, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ClaimRejected("binding already has an owner or cannot be reserved")
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY | os.O_NOINHERIT)
    except BaseException:
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close(handle)
        raise
    return descriptor


def _same_description(left, right):
    if os.name == "nt":
        import ctypes
        import msvcrt
        from ctypes import wintypes

        compare = ctypes.WinDLL("kernelbase", use_last_error=True).CompareObjectHandles
        compare.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        compare.restype = wintypes.BOOL
        return bool(compare(msvcrt.get_osfhandle(left), msvcrt.get_osfhandle(right)))
    if os.name == "posix":
        # Duplicates share an open-file-description offset; reopened same-inode
        # descriptors do not. This challenge runs under the claim's own mutex.
        saved_left = os.lseek(left, 0, os.SEEK_CUR)
        saved_right = os.lseek(right, 0, os.SEEK_CUR)
        challenge = secrets.randbits(30) + 1
        while challenge in (saved_left, saved_right):
            challenge = secrets.randbits(30) + 1
        try:
            os.lseek(right, challenge, os.SEEK_SET)
            if os.lseek(left, 0, os.SEEK_CUR) != challenge:
                return False
            os.lseek(left, challenge + 1, os.SEEK_SET)
            return os.lseek(right, 0, os.SEEK_CUR) == challenge + 1
        finally:
            os.lseek(right, saved_right, os.SEEK_SET)
            os.lseek(left, saved_left, os.SEEK_SET)
    raise ClaimRejected("kernel claim identity is unsupported")


class KernelClaim:
    def __init__(self, path, binding_id):
        self.path = str(Path(path).absolute())
        self.binding_id = binding_id
        self.process_id = os.getpid()
        self._mutex = threading.RLock()
        self._closed = False
        self._invalid = False
        self._ready = False
        self._owner_fd = self._owner_witness = self.public_fd = self._public_witness = None
        parent = None
        try:
            parent, self._parent_identity = _private_parent(Path(self.path).parent)
            if os.name == "nt":
                self._owner_fd = _windows_owner(self.path)
            elif os.name == "posix":
                import fcntl

                self._owner_fd = os.open(Path(self.path).name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                                         0o600, dir_fd=parent)
                fcntl.flock(self._owner_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                raise ClaimRejected("kernel reservation backend is unsupported")
            self._owner_witness = os.dup(self._owner_fd)
            self._identity = _file_identity(self._owner_fd)
            public_path = Path(self.path).name if parent is not None else self.path
            self.public_fd = os.open(public_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NOINHERIT", 0)
                                     | getattr(os, "O_NONBLOCK", 0), dir_fd=parent)
            self._public_witness = os.dup(self.public_fd)
            self.validate(self.public_fd)
            self._ready = True
        except BaseException:
            self.close()
            raise
        finally:
            if parent is not None:
                os.close(parent)

    def _kernel_owned(self):
        if os.name == "nt":
            # Share access is immutable on this retained file object; there is
            # no byte-range unlock that can remove its exclusive-writer claim.
            return _same_description(self._owner_fd, self._owner_witness)
        info = os.fstat(self._owner_fd)
        rows = Path(f"/proc/self/fdinfo/{self._owner_fd}").read_text().splitlines()
        for row in rows:
            fields = row.split()
            if len(fields) != 9 or fields[0] != "lock:" or fields[2:5] != ["FLOCK", "ADVISORY", "WRITE"]:
                continue
            device, inode = fields[6].rsplit(":", 1)
            major, minor = device.split(":")
            if (int(fields[5]) == self.process_id and int(inode) == info.st_ino
                    and int(major, 16) == os.major(info.st_dev) and int(minor, 16) == os.minor(info.st_dev)
                    and fields[7:] == ["0", "EOF"]):
                return True
        return False

    def validate(self, descriptor):
        with self._mutex:
            parent = None
            try:
                parent, parent_identity = _private_parent(Path(self.path).parent)
                path_info = os.stat(Path(self.path).name if parent is not None else self.path,
                                    dir_fd=parent, follow_symlinks=False)
                if (self._closed or self._invalid or self.process_id != os.getpid()
                        or type(descriptor) is not int or descriptor != self.public_fd
                        or _file_identity(descriptor) != self._identity
                        or _file_identity(self._owner_fd) != self._identity
                        or parent_identity != self._parent_identity
                        or (path_info.st_dev, path_info.st_ino, path_info.st_mode, path_info.st_uid, path_info.st_gid) != self._identity
                        or not _same_description(descriptor, self._public_witness)
                        or not _same_description(self._owner_fd, self._owner_witness)
                        or not self._kernel_owned()):
                    raise ClaimRejected("kernel claim continuity is lost")
            except (OSError, ValueError, TypeError, AttributeError, ClaimRejected):
                self._invalid = True
                raise ClaimRejected("kernel claim continuity is unavailable") from None
            finally:
                if parent is not None:
                    os.close(parent)

    def close(self):
        with self._mutex:
            if self._closed:
                return
            self._closed = True
            if not self._ready:
                for descriptor in {self.public_fd, self._public_witness, self._owner_fd, self._owner_witness} - {None}:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
                return
            # A reused descriptor may belong to an unrelated caller. Close it
            # only if it still refers to our witnessed open file description.
            for descriptor, witness in ((self.public_fd, self._public_witness), (self._owner_fd, self._owner_witness)):
                if descriptor is not None:
                    try:
                        if witness is None or _same_description(descriptor, witness):
                            os.close(descriptor)
                    except (OSError, ValueError, TypeError):
                        pass
                if witness is not None:
                    try:
                        os.close(witness)
                    except OSError:
                        pass
