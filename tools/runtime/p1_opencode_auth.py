"""Stage a pinned owner key in OpenCode's private XDG auth store for one run."""

from __future__ import annotations

import hmac
import json
import os
import stat
from pathlib import Path

from runtime.opencode_driver import OpenCodeLaunchProfile
from runtime.receiver_paths import (
    PathSecurityRejected,
    open_validated_file,
    private_parent,
)
from tools.runtime.p1_opencode_gate import OpenCodeGateAdmission, OpenCodeGateRejected


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode), info.st_nlink


class PrivateOpenCodeAuth:
    """One-use host stager; the key bytes never enter argv, env or evidence."""

    def __init__(self, admission: OpenCodeGateAdmission):
        if admission.run_id is None or admission.scene["auth_storage"] != "xdg-data-auth-json":
            raise OpenCodeGateRejected("OpenCode private auth has no bound run")
        self.admission = admission
        self.reference_identity = admission.key_reference_identity()
        self.staged_identity: tuple[int, int, int, int, int] | None = None

    def _read_reference(self) -> bytearray:
        path = Path(self.admission.scene["auth_key_ref_path"])
        parent = descriptor = None
        try:
            parent, _ = private_parent(path.parent)
            descriptor = os.open(
                path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent,
            )
            info = os.fstat(descriptor)
            present = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if (
                not stat.S_ISREG(info.st_mode)
                or (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink)
                != self.reference_identity
                or (present.st_dev, present.st_ino) != (info.st_dev, info.st_ino)
            ):
                raise OpenCodeGateRejected("OpenCode source key reference changed")
            value = bytearray(os.read(descriptor, 8195))
            if value.endswith(b"\r\n"):
                del value[-2:]
            elif value.endswith(b"\n"):
                del value[-1:]
            if (
                not 1 <= len(value) <= 8192
                or any(character < 33 or character > 126 for character in value)
                or os.read(descriptor, 1)
            ):
                raise OpenCodeGateRejected("OpenCode source key has unsafe bounded format")
            return value
        except (OSError, PathSecurityRejected) as error:
            raise OpenCodeGateRejected("OpenCode source key path is unsafe") from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if parent is not None:
                os.close(parent)

    def _auth_path(self, profile: OpenCodeLaunchProfile) -> Path:
        expected = (
            Path(f"/run/user/{os.geteuid()}/acs-p1-opencode")
            / self.admission.run_id / "data"
        )
        if os.name != "posix" or Path(profile.data_root) != expected:
            raise OpenCodeGateRejected("OpenCode XDG auth root left current private run")
        descriptor, _ = private_parent(expected)
        os.close(descriptor)
        return expected / "opencode" / "auth.json"

    def stage(self, profile: OpenCodeLaunchProfile) -> dict[str, object]:
        if self.staged_identity is not None:
            raise OpenCodeGateRejected("OpenCode owner auth was already staged")
        self.admission.assert_native_profile(profile)
        path = self._auth_path(profile)
        key = self._read_reference()
        auth_dir = path.parent
        data_fd = auth_fd = temporary_fd = None
        published = False
        directory_created = False
        success = False
        try:
            data_fd, _ = private_parent(auth_dir.parent)
            os.mkdir(auth_dir.name, 0o700, dir_fd=data_fd)
            directory_created = True
            auth_fd, _ = private_parent(auth_dir)
            temporary_fd = os.open(
                "auth.json.tmp", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600, dir_fd=auth_fd,
            )
            payload = json.dumps({
                self.admission.scene["provider_id"]: {"type": "api", "key": key.decode("ascii")},
            }, sort_keys=True, separators=(",", ":")).encode()
            view = memoryview(payload)
            while view:
                written = os.write(temporary_fd, view)
                if written <= 0:
                    raise OpenCodeGateRejected("OpenCode auth stage write made no progress")
                view = view[written:]
            os.fsync(temporary_fd)
            os.close(temporary_fd)
            temporary_fd = None
            os.replace("auth.json.tmp", "auth.json", src_dir_fd=auth_fd, dst_dir_fd=auth_fd)
            published = True
            os.fsync(auth_fd)
            self.staged_identity = self._read_staged(profile, key)
            self.assert_current(profile)
            success = True
            return {"storage": "xdg-data-auth-json", "provider_id": self.admission.scene["provider_id"],
                    "owner_mode": "0600", "same_reference": True}
        except (OSError, PathSecurityRejected) as error:
            raise OpenCodeGateRejected("OpenCode private auth staging failed") from error
        finally:
            cleanup_error = None
            for index in range(len(key)):
                key[index] = 0
            if temporary_fd is not None:
                os.close(temporary_fd)
            if auth_fd is not None:
                if not success:
                    try:
                        os.unlink("auth.json" if published else "auth.json.tmp", dir_fd=auth_fd)
                        os.fsync(auth_fd)
                    except FileNotFoundError:
                        pass
                    except OSError as error:
                        cleanup_error = error
                os.close(auth_fd)
            if not success and directory_created and data_fd is not None:
                try:
                    os.rmdir(auth_dir.name, dir_fd=data_fd)
                    os.fsync(data_fd)
                except OSError as error:
                    cleanup_error = error
            if data_fd is not None:
                os.close(data_fd)
            if not success:
                self.staged_identity = None
            if cleanup_error is not None:
                raise OpenCodeGateRejected("OpenCode auth stage cleanup is unverified") from cleanup_error

    def _read_staged(
        self, profile: OpenCodeLaunchProfile, key: bytearray
    ) -> tuple[int, int, int, int, int]:
        path = self._auth_path(profile)
        try:
            descriptor, _ = open_validated_file(path, private=True)
        except (OSError, PathSecurityRejected) as error:
            raise OpenCodeGateRejected("OpenCode staged auth path is unsafe") from error
        try:
            info = os.fstat(descriptor)
            data = os.read(descriptor, 100_001)
            if len(data) > 100_000 or os.read(descriptor, 1):
                raise OpenCodeGateRejected("OpenCode staged auth exceeds bound")
            value = json.loads(data)
            expected = self.admission.scene["provider_id"]
            if (
                not isinstance(value, dict) or set(value) != {expected}
                or not isinstance(value[expected], dict)
                or set(value[expected]) != {"type", "key"}
                or value[expected]["type"] != "api"
                or not isinstance(value[expected]["key"], str)
                or not hmac.compare_digest(value[expected]["key"].encode(), key)
            ):
                raise OpenCodeGateRejected("OpenCode staged auth no longer matches pinned key")
            return _identity(info)
        except (UnicodeError, ValueError) as error:
            raise OpenCodeGateRejected("OpenCode staged auth format differs") from error
        finally:
            os.close(descriptor)

    def assert_current(self, profile: OpenCodeLaunchProfile) -> dict[str, object]:
        if self.staged_identity is None:
            raise OpenCodeGateRejected("OpenCode native auth has not been staged")
        key = self._read_reference()
        try:
            if self._read_staged(profile, key) != self.staged_identity:
                raise OpenCodeGateRejected("OpenCode staged auth inode changed")
        finally:
            for index in range(len(key)):
                key[index] = 0
        return {"storage": "xdg-data-auth-json", "provider_id": self.admission.scene["provider_id"],
                "owner_mode": "0600", "same_reference": True}
