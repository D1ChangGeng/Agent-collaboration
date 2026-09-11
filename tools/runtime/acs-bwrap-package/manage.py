#!/usr/bin/env python3
"""Scoped bwrap/AppArmor administrator package. Default: checks only.

No global sysctl, distribution profile, service, Node configuration, or user
credential is modified. Linux root privileges are used only with --apply.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import stat
import subprocess
import sys
import tempfile
from contextlib import ExitStack, contextmanager
from pathlib import Path

if sys.platform.startswith("linux"):
    import fcntl
    import grp
    import pwd

PACKAGE = "acs-bwrap-userns/v1"
SOURCE = Path("/usr/bin/bwrap")
HELPER = Path("/opt/acs/codex-sandbox/bin/bwrap")
PROFILE = Path("/etc/apparmor.d/acs-bwrap-userns")
MANIFEST = Path("/opt/acs/codex-sandbox/manifest.json")
PARSER = Path("/usr/sbin/apparmor_parser")
CREATE_DIRS = (Path("/opt/acs"), Path("/opt/acs/codex-sandbox"), Path("/opt/acs/codex-sandbox/bin"))
PROFILES = {"acs_bwrap", "acs_unpriv_bwrap"}
ENFORCING_PROFILES = {name: "enforce" for name in PROFILES}
HELPER_SHA = "52231e1caf55bcbc667b269f49c63599a6f7db4767ae6a039580d0ff853db712"
PROFILE_SHA = "7b2beb270c7218b549883337f53cbdca903d4e93803704af42788f63f93583a1"
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"}


class Refused(RuntimeError):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(data):
    return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode()


def check_info(info, *, directory=False, mode=None, gid=None):
    correct_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not correct_type or info.st_uid != 0 or info.st_mode & 0o022:
        raise Refused(
            "path must have expected type, root ownership and no group/other write access"
        )
    if not directory and info.st_nlink != 1:
        raise Refused("managed/source file must have exactly one link")
    if mode is not None and stat.S_IMODE(info.st_mode) != mode:
        raise Refused("managed file mode differs from package contract")
    if gid is not None and info.st_gid != gid:
        raise Refused("managed file group differs from manifest")


@contextmanager
def directory(path, *, create=False, created=None):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise Refused("administrator path must be absolute without traversal")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    current = Path("/")
    try:
        check_info(os.fstat(fd), directory=True)
        for component in path.parts[1:]:
            current /= component
            try:
                child = os.open(component, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create or current not in CREATE_DIRS:
                    raise
                os.mkdir(component, 0o755, dir_fd=fd)
                os.fsync(fd)
                if created is not None:
                    created.append(str(current))
                child = os.open(component, flags, dir_fd=fd)
            try:
                check_info(os.fstat(child), directory=True)
            except BaseException:
                os.close(child)
                raise
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def read_file(path, *, missing=False, mode=None, gid=None, maximum=4 * 1024 * 1024):
    try:
        with directory(path.parent) as parent:
            fd = os.open(
                path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent
            )
            try:
                check_info(os.fstat(fd), mode=mode, gid=gid)
                data = bytearray()
                while chunk := os.read(fd, min(65536, maximum - len(data) + 1)):
                    data.extend(chunk)
                    if len(data) > maximum:
                        raise Refused("file exceeds package read bound")
                return bytes(data)
            finally:
                os.close(fd)
    except FileNotFoundError:
        if missing:
            return None
        raise


def install_file(path, data, *, mode, gid=0):
    with directory(path.parent) as parent:
        temp = ".acs-package-" + secrets.token_hex(20)
        fd = os.open(
            temp,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent,
        )
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("write made no progress")
                view = view[written:]
            os.fchown(fd, 0, gid)
            os.fchmod(fd, mode)
            os.fsync(fd)
            # No replacement, including existing symlinks or coincidentally equal files.
            os.link(temp, path.name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
            os.fsync(parent)
        finally:
            os.close(fd)
            os.unlink(temp, dir_fd=parent)
            os.fsync(parent)


def remove_file(path, expected, *, mode, gid=0):
    existing = read_file(path, missing=True, mode=mode, gid=gid)
    if existing is None:
        return
    if existing != expected:
        raise Refused("refusing to remove file not matching this package")
    with directory(path.parent) as parent:
        os.unlink(path.name, dir_fd=parent)
        os.fsync(parent)


def bundled_profile():
    path = Path(__file__).with_name("acs-bwrap-userns.profile")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise Refused("package profile must be a regular file")
        data = os.read(fd, 65537)
    finally:
        os.close(fd)
    if len(data) > 65536 or sha(data) != PROFILE_SHA:
        raise Refused("package profile SHA mismatch")
    return data


def parse_profile(profile, action="check"):
    read_file(PARSER)  # Root-owned executable with guarded parent chain.
    options = {
        "check": ["--skip-kernel-load", "--skip-cache"],
        "load": ["--replace", "--skip-cache"],
        "remove": ["--remove", "--skip-cache"],
    }
    result = subprocess.run(
        [str(PARSER), *options[action]],
        input=profile,
        env=ENV,
        capture_output=True,
        timeout=20,
        check=False,
    )
    if result.returncode:
        raise Refused("AppArmor parser failed: " + result.stderr.decode(errors="replace")[-4096:])


def parse_loaded_profiles(lines):
    profiles = {}
    for line in lines:
        name, separator, mode = line.strip().rpartition(" (")
        if name not in PROFILES:
            if line.strip() in PROFILES:
                raise Refused("dedicated profile has no reported enforcement mode")
            continue
        if not separator or not mode.endswith(")") or name in profiles:
            raise Refused("dedicated profile mode is malformed or ambiguous")
        profiles[name] = mode[:-1]
    return profiles


def loaded_profiles():
    with open("/sys/kernel/security/apparmor/profiles", encoding="utf-8") as stream:
        return parse_loaded_profiles(stream)


def validate_manifest(value):
    expected = {
        "package",
        "helper",
        "profile",
        "helper_sha256",
        "profile_sha256",
        "runtime_user",
        "runtime_uid",
        "runtime_group",
        "runtime_gid",
        "created_directories",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise Refused("unknown manifest shape")
    if (
        value["package"] != PACKAGE
        or value["helper"] != str(HELPER)
        or value["profile"] != str(PROFILE)
        or value["helper_sha256"] != HELPER_SHA
        or value["profile_sha256"] != PROFILE_SHA
    ):
        raise Refused("manifest is not owned by this exact package")
    if (
        type(value["runtime_uid"]) is not int
        or value["runtime_uid"] <= 0
        or type(value["runtime_gid"]) is not int
        or value["runtime_gid"] <= 0
    ):
        raise Refused("runtime must be an unprivileged uid/gid")
    created = value["created_directories"]
    if (
        not isinstance(created, list)
        or any(not isinstance(path, str) for path in created)
        or len(created) != len(set(created))
        or any(path not in {str(p) for p in CREATE_DIRS} for path in created)
    ):
        raise Refused("manifest contains an unauthorized directory")
    return value


def state():
    raw = read_file(MANIFEST, missing=True, mode=0o600, gid=0, maximum=65536)
    return (None, None) if raw is None else (validate_manifest(json.loads(raw)), raw)


def matching_capacity():
    """Fail closed if a userspace process cannot be inspected completely."""
    matches, unknown = [], []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdecimal():
            continue
        try:
            exe = os.readlink(proc / "exe")
        except FileNotFoundError:
            continue  # Exited, zombie or kernel thread has no executable.
        except PermissionError:
            unknown.append(int(proc.name))
            continue
        try:
            label = (proc / "attr/current").read_text()
        except FileNotFoundError:
            continue
        except (PermissionError, OSError):
            unknown.append(int(proc.name))
            continue
        if exe.removesuffix(" (deleted)") == str(HELPER) or any(name in label for name in PROFILES):
            matches.append(int(proc.name))
    if matches or unknown:
        raise Refused(
            f"package capacity not proven stopped: matching_pids={matches}, unknown_pids={unknown}"
        )


def runtime_identity(args):
    user = pwd.getpwnam(args.runtime_user)
    group = grp.getgrnam(args.runtime_group)
    if user.pw_uid == 0 or group.gr_gid == 0:
        raise Refused("runtime identity must not be root")
    if user.pw_gid != group.gr_gid and args.runtime_user not in group.gr_mem:
        raise Refused("runtime user is not a member of the chosen group")
    return user.pw_uid, group.gr_gid


def existing_assets(manifest, *, allow_missing):
    for path, checksum, mode, gid in (
        (HELPER, HELPER_SHA, 0o750, manifest["runtime_gid"]),
        (PROFILE, PROFILE_SHA, 0o644, 0),
    ):
        data = read_file(path, missing=allow_missing, mode=mode, gid=gid)
        if data is not None and sha(data) != checksum:
            raise Refused("existing resource differs from package: " + str(path))


def sysctls(*, require_expected=True):
    keys = ("apparmor_restrict_unprivileged_userns", "unprivileged_userns_clone")
    values = {key: Path("/proc/sys/kernel", key).read_text().strip() for key in keys}
    if require_expected and any(value != "1" for value in values.values()):
        raise Refused("required userns restrictions differ; package never changes global sysctls")
    return values


def preflight(args):
    if not sys.platform.startswith("linux"):
        raise Refused("administrator package is Linux-only")
    profile = bundled_profile()
    manifest, _ = state()
    if manifest and args.action in {"verify", "uninstall"}:
        # Rollback remains possible after a distro bwrap update or user removal.
        uid, gid = manifest["runtime_uid"], manifest["runtime_gid"]
        helper = read_file(HELPER, missing=True, mode=0o750, gid=gid) or b""
    else:
        helper = read_file(SOURCE)
        if sha(helper) != HELPER_SHA:
            raise Refused("system bwrap differs from the reviewed helper SHA")
        uid, gid = runtime_identity(args)
    settings = sysctls(require_expected=args.action != "uninstall")
    parse_profile(profile)
    if manifest:
        existing_assets(manifest, allow_missing=True)
        if (manifest["runtime_uid"], manifest["runtime_gid"]) != (uid, gid):
            raise Refused("runtime identity differs from installed package")
    else:
        for path in (HELPER, PROFILE):
            if read_file(path, missing=True) is not None:
                raise Refused("unowned target exists; refusing adoption or overwrite")
    try:
        loaded = loaded_profiles()
    except PermissionError:
        if args.apply:
            raise Refused("administrator cannot inspect loaded AppArmor profiles") from None
        loaded = None
    if not manifest and loaded:
        raise Refused("profile names already loaded without this package manifest")
    return {
        "profile": profile,
        "helper": helper,
        "uid": uid,
        "gid": gid,
        "sysctls": settings,
        "manifest": manifest,
        "loaded": loaded,
    }


HOST_WRITE_CODE = r"""
import json, os, sys
assert os.geteuid() == int(sys.argv[2]) != 0
assert os.getegid() == int(sys.argv[3]) != 0
assert os.getgroups() == []
with open(sys.argv[1], "r+") as stream:
    assert stream.read() == "acs-readonly-sentinel\n"
    stream.seek(0)
    stream.write("acs-write-control\n")
    stream.truncate()
    stream.flush()
    os.fsync(stream.fileno())
    stream.seek(0)
    assert stream.read() == "acs-write-control\n"
    stream.seek(0)
    stream.write("acs-readonly-sentinel\n")
    stream.truncate()
    stream.flush()
    os.fsync(stream.fileno())
print(json.dumps({"host_writable": True, "uid": os.geteuid(), "gid": os.getegid()}))
"""


VERIFY_CODE = r"""
import errno, json, os, socket, sys
source = "/input/probe.txt"
assert open(source).read() == "acs-readonly-sentinel\n"
assert not os.path.exists(sys.argv[2])
fields = dict(line.split(":", 1) for line in open("/proc/self/status") if ":" in line)
assert int(fields["CapEff"].strip(), 16) == int(fields["CapPrm"].strip(), 16) == 0
label = open("/proc/self/attr/current").read().strip()
label_body, separator, label_mode = label.rpartition(" (")
label_profiles = label_body.split("//&")
assert separator and label_mode == "enforce)"
assert len(label_profiles) == 2 and set(label_profiles) == {"acs_bwrap", "acs_unpriv_bwrap"}
net = os.readlink("/proc/self/ns/net")
assert net != sys.argv[1]
interfaces = [name for _, name in socket.if_nameindex()]
assert interfaces == ["lo"]
assert len(open("/proc/net/route").read().splitlines()) == 1
proof = {"outside_source_hidden": True, "cap_eff": 0, "cap_prm": 0,
         "apparmor_label": label, "separate_netns": True, "interfaces": interfaces,
         "non_loopback_routes": 0}
try:
    with open(source, "w") as stream:
        stream.write("acs-write-control\n")
        stream.flush()
        os.fsync(stream.fileno())
except OSError as exc:
    assert exc.errno in (errno.EROFS, errno.EACCES, errno.EPERM)
    proof.update(readonly=True, write_errno=exc.errno)
else:
    # The identical verifier rejects a writable mount. The administrator must
    # observe this distinct failure for its deliberately writable control.
    proof.update(readonly=False, write_errno=None)
print(json.dumps(proof))
raise SystemExit(0 if proof["readonly"] else 42)
"""


def run_unprivileged(argv, info):
    return subprocess.run(
        argv, cwd="/", env=ENV, user=info["uid"], group=info["gid"],
        extra_groups=[], capture_output=True, timeout=15, check=False,
    )


def probe_json(result, expected_exit, reason):
    if result.returncode != expected_exit:
        raise Refused(reason + ": " + result.stderr.decode(errors="replace")[-4096:])
    try:
        proof = json.loads(result.stdout)
    except (TypeError, ValueError):
        raise Refused(reason + ": invalid proof JSON") from None
    if not isinstance(proof, dict):
        raise Refused(reason + ": proof must be an object")
    return proof


class PinnedFixture:
    """Bounded reads of the exact fixture inodes opened before UID access."""

    def __init__(self, parent_fd, root_name, root_fd, input_fd, probe_fd, inp, outside):
        self.input, self.outside = inp, outside
        self._entries = (
            (parent_fd, root_name, root_fd, True),
            (root_fd, "input", input_fd, True),
            (input_fd, "probe.txt", probe_fd, False),
        )
        self._identities = tuple(self._identity(os.fstat(fd)) for _, _, fd, _ in self._entries)
        self._probe_fd = probe_fd

    @staticmethod
    def _identity(info):
        return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_nlink

    def _check(self):
        try:
            for (parent, name, fd, is_directory), expected in zip(self._entries, self._identities, strict=True):
                held = os.fstat(fd)
                entry = os.stat(name, dir_fd=parent, follow_symlinks=False)
                correct_type = stat.S_ISDIR(held.st_mode) if is_directory else stat.S_ISREG(held.st_mode)
                if (not correct_type or self._identity(held) != expected
                        or self._identity(entry) != expected):
                    raise Refused("fixture inode, type or metadata changed")
        except OSError as exc:
            raise Refused("fixture identity is no longer available") from exc

    def read(self, maximum=64):
        self._check()
        if os.fstat(self._probe_fd).st_size > maximum:
            raise Refused("fixture exceeds bounded read limit")
        os.lseek(self._probe_fd, 0, os.SEEK_SET)
        data = bytearray()
        while chunk := os.read(self._probe_fd, min(65536, maximum - len(data) + 1)):
            data.extend(chunk)
            if len(data) > maximum:
                raise Refused("fixture grew beyond bounded read limit")
        self._check()
        if os.fstat(self._probe_fd).st_size > maximum:
            raise Refused("fixture grew beyond bounded read limit")
        return bytes(data)


@contextmanager
def verification_fixture(info):
    # A guarded package parent also excludes user-controlled TMPDIR ancestors.
    with directory(MANIFEST.parent) as parent_fd, tempfile.TemporaryDirectory(
        prefix="acs-bwrap-verify-", dir=MANIFEST.parent,
    ) as temporary, ExitStack() as handles:
        root = Path(temporary)
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        root_fd = os.open(root.name, flags, dir_fd=parent_fd)
        handles.callback(os.close, root_fd)
        check_info(os.fstat(root_fd), directory=True)
        os.mkdir("input", 0o700, dir_fd=root_fd)
        input_fd = os.open("input", flags, dir_fd=root_fd)
        handles.callback(os.close, input_fd)
        check_info(os.fstat(input_fd), directory=True)
        file_flags = os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
        probe_fd = os.open("probe.txt", file_flags, 0o600, dir_fd=input_fd)
        handles.callback(os.close, probe_fd)
        outside_fd = os.open("outside-scope.txt", file_flags, 0o600, dir_fd=root_fd)
        handles.callback(os.close, outside_fd)
        for fd, payload in ((probe_fd, b"acs-readonly-sentinel\n"), (outside_fd, b"synthetic outside scope")):
            if os.write(fd, payload) != len(payload):
                raise Refused("fixture initialization write was incomplete")
            os.fsync(fd)
        os.fchmod(probe_fd, 0o600)
        os.fchown(probe_fd, info["uid"], info["gid"])
        # Runtime can traverse these root-owned directories, but cannot rename
        # the input directory or any leaf. Only probe.txt is runtime-writable.
        os.fchmod(input_fd, 0o711)
        os.fchmod(root_fd, 0o711)
        fixture = PinnedFixture(parent_fd, root.name, root_fd, input_fd, probe_fd,
                                root / "input", root / "outside-scope.txt")
        fixture._check()
        yield fixture


def verify_installed(info):
    manifest = info["manifest"]
    existing_assets(manifest, allow_missing=False)
    if loaded_profiles() != ENFORCING_PROFILES:
        raise Refused("both dedicated profiles must be loaded in enforce mode")
    host_net = os.readlink("/proc/self/ns/net")
    # Owned temporary fixture only, independent from all real source/credentials.
    with verification_fixture(info) as fixture:
        inp, outside = fixture.input, fixture.outside
        # The same unprivileged UID must actually write and restore this file
        # on the host. Parent/root never rewrites a runtime-owned fixture path.
        host = probe_json(run_unprivileged(
            ["/usr/bin/python3", "-I", "-c", HOST_WRITE_CODE, str(inp / "probe.txt"),
             str(info["uid"]), str(info["gid"])], info), 0, "host writable control failed")
        if (host.get("host_writable") is not True or host.get("uid") != info["uid"]
                or host.get("gid") != info["gid"]
                or fixture.read() != b"acs-readonly-sentinel\n"):
            raise Refused("host writable control did not restore the sentinel")
        argv = [
            str(HELPER),
            "--new-session",
            "--die-with-parent",
            "--unshare-user",
            "--unshare-net",
            "--unshare-pid",
            "--unshare-ipc",
            "--tmpfs",
            "/",
        ]
        for path in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc"):
            if os.path.islink(path):
                argv.extend(("--symlink", os.readlink(path), path))
            elif os.path.isdir(path):
                argv.extend(("--ro-bind", path, path))
        argv.extend(
            (
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--ro-bind",
                str(inp),
                "/input",
                "--cap-drop",
                "ALL",
                "--",
                "/usr/bin/python3",
                "-I",
                "-c",
                VERIFY_CODE,
                host_net,
                str(outside),
            )
        )
        proof = probe_json(run_unprivileged(argv, info), 0, "strict post-install probe failed")
        if proof.get("readonly") is not True:
            raise Refused("strict post-install probe did not prove readonly input")
        if fixture.read() != b"acs-readonly-sentinel\n":
            raise Refused("readonly sentinel changed on host")
        # Change only this synthetic input's mount mode. Retain exactly the
        # same UID, environment, verifier, capability and namespace checks.
        writable_argv = list(argv)
        input_index = writable_argv.index(str(inp))
        if writable_argv[input_index - 1] != "--ro-bind":
            raise Refused("input mount does not match the readonly probe contract")
        writable_argv[input_index - 1] = "--bind"
        writable = probe_json(run_unprivileged(writable_argv, info), 42,
                              "writable mount did not fail the readonly verifier")
        if (writable.get("readonly") is not False or writable.get("write_errno") is not None
                or fixture.read() != b"acs-write-control\n"):
            raise Refused("writable mount control did not change the host sentinel")
        proof["host_write_control"] = host
        proof["readonly_host_sentinel_preserved"] = True
        proof["writable_bind_control"] = {
            "readonly_verifier_exit": 42, "host_write_observed": True, "proof": writable,
        }
    if sysctls() != info["sysctls"]:
        raise Refused("global settings changed during verification")
    return proof


def remove_owned(info, raw_manifest):
    manifest = info["manifest"]
    existing_assets(manifest, allow_missing=True)
    matching_capacity()
    helper_exists = (
        read_file(HELPER, missing=True, mode=0o750, gid=manifest["runtime_gid"]) is not None
    )
    held_fd = None
    try:
        if helper_exists:
            with directory(HELPER.parent) as parent:
                held_fd = os.open(
                    HELPER.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent
                )
            # Close new unprivileged admissions, then repeat the stopped check.
            os.fchmod(held_fd, 0o000)
            os.fsync(held_fd)
        matching_capacity()
        if set(loaded_profiles()) & PROFILES:
            parse_profile(info["profile"], "remove")
        if set(loaded_profiles()) & PROFILES:
            raise Refused("profile removal was not confirmed")
        if helper_exists:
            remove_file(HELPER, info["helper"], mode=0o000, gid=manifest["runtime_gid"])
        remove_file(PROFILE, info["profile"], mode=0o644)
        remove_file(MANIFEST, raw_manifest, mode=0o600)
    finally:
        if held_fd is not None:
            # Restore admission if rollback/uninstall was refused; an unlinked
            # inode is harmless and cannot reopen a removed pathname.
            os.fchmod(held_fd, 0o750)
            os.fsync(held_fd)
            os.close(held_fd)
    for name in reversed(manifest["created_directories"]):
        path = Path(name)
        with directory(path.parent) as parent:
            try:
                os.rmdir(path.name, dir_fd=parent)
                os.fsync(parent)
            except OSError as exc:
                if exc.errno not in (39, 17):
                    raise


def install(args, info):
    created = []
    with directory(HELPER.parent, create=True, created=created):
        pass
    manifest, raw = state()
    previously_owned = manifest is not None
    if manifest is None:
        manifest = {
            "package": PACKAGE,
            "helper": str(HELPER),
            "profile": str(PROFILE),
            "helper_sha256": HELPER_SHA,
            "profile_sha256": PROFILE_SHA,
            "runtime_user": args.runtime_user,
            "runtime_uid": info["uid"],
            "runtime_group": args.runtime_group,
            "runtime_gid": info["gid"],
            "created_directories": created,
        }
        raw = canonical(manifest)
        install_file(MANIFEST, raw, mode=0o600)
    info["manifest"] = manifest
    try:
        if read_file(HELPER, missing=True, mode=0o750, gid=info["gid"]) is None:
            install_file(HELPER, info["helper"], mode=0o750, gid=info["gid"])
        if read_file(PROFILE, missing=True, mode=0o644) is None:
            install_file(PROFILE, info["profile"], mode=0o644)
        if loaded_profiles() != ENFORCING_PROFILES:
            matching_capacity()
            parse_profile(info["profile"], "load")
        return verify_installed(info)
    except BaseException:
        # No unrelated processes are signalled. If capacity/ownership cannot be
        # proven safe, retain manifest/profile for explicit administrator repair.
        if not previously_owned:
            remove_owned(info, raw)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("check", "install", "verify", "uninstall"), nargs="?", default="check"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="explicitly authorize root installation/verification/removal",
    )
    parser.add_argument("--runtime-user", default="changgeng")
    parser.add_argument("--runtime-group", default="changgeng")
    parser.add_argument(
        "--capacity-stopped",
        action="store_true",
        help="operator confirms this package's Node capacity is stopped",
    )
    args = parser.parse_args(argv)
    if not sys.platform.startswith("linux"):
        raise Refused("administrator package is Linux-only")
    if args.apply and (args.action == "check" or os.geteuid() != 0):
        raise Refused("--apply requires root and an explicit install/verify/uninstall action")
    if args.apply:
        read_file(
            Path(__file__).absolute()
        )  # Apply only from a root-owned, non-writable package path.
    # A directory inode lock serializes this package without creating a global
    # lock file or touching other applications' policy resources.
    with directory(PROFILE.parent) as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        info = preflight(args)
        if not args.apply:
            print(
                json.dumps(
                    {
                        "mode": "check-only",
                        "requested_action": args.action,
                        "profile_parse": "pass",
                        "helper_sha256": HELPER_SHA,
                        "installed_manifest": info["manifest"] is not None,
                        "loaded_profiles": info["loaded"]
                        if info["loaded"] is not None
                        else "requires-admin-read",
                        "next": "administrator --apply required for changes",
                    }
                )
            )
            return 0
        if args.action == "install":
            proof = install(args, info)
        elif args.action == "verify":
            if info["manifest"] is None:
                raise Refused("package is not installed")
            proof = verify_installed(info)
        else:
            if not args.capacity_stopped:
                raise Refused("stop this package's capacity and explicitly pass --capacity-stopped")
            manifest, raw = state()
            if manifest is None:
                raise Refused("no owned package manifest; nothing will be removed")
            info["manifest"] = manifest
            remove_owned(info, raw)
            proof = {"removed": True, "unrelated_services_touched": False}
        print(json.dumps({"mode": "applied", "action": args.action, "proof": proof}))
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Refused, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"status": "refused", "reason": str(error)}), file=sys.stderr)
        raise SystemExit(1) from error
