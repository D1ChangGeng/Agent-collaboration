"""Pinned systemd --user transient-service process-tree supervision candidate."""
from __future__ import annotations

import os
import re
import stat
import subprocess
import threading
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from runtime.supervisor import (
    ContainmentUnavailable,
    OwnedProcess,
    OwnershipMismatch,
    _Ownership,
    _proc_birth,
    _Record,
    _validate_launch,
)

SYSTEMD_RUN = "/usr/bin/systemd-run"
SYSTEMCTL = "/usr/bin/systemctl"
CGROUP_ROOT = Path("/sys/fs/cgroup")
_UNIT = re.compile(r"acs-[a-z0-9][a-z0-9_.-]{0,180}\.service")
_ENVIRONMENT_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
_SHOW_PROPERTIES = (
    "Id", "LoadState", "ActiveState", "SubState", "Result", "Type", "ExitType",
    "InvocationID", "MainPID", "ControlGroup", "ExecMainStartTimestampMonotonic",
    "KillMode", "SendSIGKILL", "TimeoutStopUSec", "TasksMax", "MemoryMax",
    "CPUQuotaPerSecUSec", "NoNewPrivileges", "RestrictSUIDSGID", "LockPersonality",
    "UMask", "WorkingDirectory",
)


def _duration_us(value: str) -> int:
    units = {"us": 1, "ms": 1_000, "s": 1_000_000, "min": 60_000_000}
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(us|ms|s|min)", value)
    if match is None:
        raise ContainmentUnavailable("systemd returned an unsupported CPU quota duration")
    return int(float(match.group(1)) * units[match.group(2)])


class _SystemdProcess:
    def __init__(self, transport: subprocess.Popen[bytes], supervisor: SystemdUserSupervisor,
                 unit: str, root_pid: int) -> None:
        self._transport, self._supervisor, self._unit = transport, supervisor, unit
        self.pid = root_pid
        self.stdin, self.stdout, self.stderr = transport.stdin, transport.stdout, transport.stderr
        self.returncode: int | None = None

    @property
    def transport_pid(self) -> int:
        return self._transport.pid

    def poll(self) -> int | None:
        value = self._transport.poll()
        if value is not None:
            self.returncode = value
        return value

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = self._transport.wait(timeout=timeout)
        return self.returncode


class SystemdUserSupervisor(_Ownership):
    """One generated transient user service per owned native process tree."""

    def __init__(self, *, tasks_max: int = 128, memory_max: int = 1_073_741_824,
                 cpu_quota_percent: float = 100.0, termination_timeout: float = 10.0) -> None:
        super().__init__()
        if os.name != "posix" or os.geteuid() == 0:
            raise ContainmentUnavailable("systemd user supervision requires a non-root Linux user")
        if not all(Path(path).is_file() for path in (SYSTEMD_RUN, SYSTEMCTL)):
            raise ContainmentUnavailable("systemd-run and systemctl are required")
        if not 1 <= tasks_max <= 1024:
            raise ValueError("TasksMax is outside the reviewed bound")
        if not 67_108_864 <= memory_max <= 8_589_934_592:
            raise ValueError("MemoryMax is outside the reviewed bound")
        if not 1.0 <= cpu_quota_percent <= 800.0 or not 0 < termination_timeout <= 60:
            raise ValueError("CPUQuota or termination timeout is outside the reviewed bound")
        self.tasks_max = tasks_max
        self.memory_max = memory_max
        self.cpu_quota_percent = cpu_quota_percent
        self.termination_timeout = termination_timeout
        self._controller_lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._closed = False
        probe = self._run_systemctl(("is-system-running",), check=False)
        if probe.returncode not in (0, 1):
            raise ContainmentUnavailable("systemd --user manager is unavailable")

    @staticmethod
    def _unit_name(label: str) -> str:
        normalized = label.lower()
        unit = f"acs-{normalized}-{uuid.uuid4().hex}.service"
        if _UNIT.fullmatch(unit) is None:
            raise ValueError("generated systemd unit name is invalid")
        return unit

    @staticmethod
    def _encoded_environment(env: Mapping[str, str]) -> bytes:
        lines = []
        for key, value in sorted(env.items()):
            if _ENVIRONMENT_KEY.fullmatch(key) is None:
                raise ValueError("environment name is outside the systemd EnvironmentFile grammar")
            if any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise ValueError("environment values cannot contain control characters")
            escaped = (value.replace("\\", "\\\\").replace('"', '\\"')
                       .replace("$", "\\$").replace("`", "\\`"))
            lines.append(f'{key}="{escaped}"\n')
        encoded = "".join(lines).encode("utf-8")
        if len(encoded) > 65_536:
            raise ValueError("environment file exceeds the reviewed bound")
        return encoded

    @staticmethod
    def _environment_directory() -> Path:
        uid = os.geteuid()
        runtime = Path(f"/run/user/{uid}")
        info = runtime.stat(follow_symlinks=False)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise ContainmentUnavailable("XDG runtime directory ownership or mode is unsafe")
        directory = runtime / "acs-systemd-supervisor-env"
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
        info = directory.stat(follow_symlinks=False)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise ContainmentUnavailable("environment directory ownership or mode is unsafe")
        return directory

    def _write_environment_file(self, env: Mapping[str, str]) -> Path:
        data = self._encoded_environment(env)
        directory = self._environment_directory()
        name = f"environment-{uuid.uuid4().hex}.conf"
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            fd = os.open(
                name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600, dir_fd=directory_fd,
            )
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                        or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                    raise ContainmentUnavailable("environment file identity is unsafe")
                view = memoryview(data)
                while view:
                    written = os.write(fd, view)
                    view = view[written:]
                os.fsync(fd)
            except BaseException:
                os.close(fd)
                os.unlink(name, dir_fd=directory_fd)
                raise
            else:
                os.close(fd)
        finally:
            os.close(directory_fd)
        return directory / name

    @staticmethod
    def _remove_environment_file(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    @staticmethod
    def _run_systemctl(args: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [SYSTEMCTL, "--user", "--no-pager", *args],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10, check=False,
        )
        if check and result.returncode != 0:
            raise ContainmentUnavailable("systemctl --user failed: " + result.stderr[-2048:])
        return result

    def _show(self, unit: str) -> dict[str, str]:
        if _UNIT.fullmatch(unit) is None:
            raise OwnershipMismatch("stored unit name is outside the generated namespace")
        args = ["show", unit]
        for name in _SHOW_PROPERTIES:
            args.append(f"--property={name}")
        result = self._run_systemctl(args)
        values: dict[str, str] = {}
        for line in result.stdout.splitlines():
            key, separator, value = line.partition("=")
            if not separator or key not in _SHOW_PROPERTIES or key in values:
                raise ContainmentUnavailable("systemctl show output is malformed")
            values[key] = value
        if set(values) != set(_SHOW_PROPERTIES):
            raise ContainmentUnavailable("systemctl show omitted required identity or policy")
        return values

    def _validate_policy(self, values: Mapping[str, str]) -> dict[str, Any]:
        expected = {
            "Type": "exec", "ExitType": "cgroup", "KillMode": "control-group",
            "SendSIGKILL": "yes", "TasksMax": str(self.tasks_max),
            "MemoryMax": str(self.memory_max), "NoNewPrivileges": "yes",
            "RestrictSUIDSGID": "yes", "LockPersonality": "yes", "UMask": "0077",
        }
        if any(values.get(key) != value for key, value in expected.items()):
            raise OwnershipMismatch("transient service policy differs from the admitted unit")
        quota_us = _duration_us(values["CPUQuotaPerSecUSec"])
        if quota_us != int(self.cpu_quota_percent * 10_000):
            raise OwnershipMismatch("CPUQuota readback differs from the admitted unit")
        if values["TimeoutStopUSec"] != f"{self.termination_timeout:g}s":
            raise OwnershipMismatch("TimeoutStopSec readback differs from the admitted unit")
        return {**expected, "CPUQuotaPerSecUSec": values["CPUQuotaPerSecUSec"],
                "TimeoutStopUSec": values["TimeoutStopUSec"]}

    @staticmethod
    def _cgroup_path(control_group: str, unit: str) -> Path:
        uid = os.geteuid()
        prefix = f"/user.slice/user-{uid}.slice/user@{uid}.service/"
        if (not control_group.startswith(prefix) or not control_group.endswith("/" + unit)
                or ".." in Path(control_group).parts):
            raise OwnershipMismatch("ControlGroup is outside this user manager and unit")
        path = CGROUP_ROOT / control_group.lstrip("/")
        if path.exists() and not path.is_dir():
            raise OwnershipMismatch("ControlGroup path is not a directory")
        return path

    def _members(self, control_group: str, unit: str) -> tuple[list[int], dict[str, str]]:
        root = self._cgroup_path(control_group, unit)
        if not root.exists():
            return [], {}
        pids: set[int] = set()
        for source in (root / "cgroup.procs", *root.glob("**/cgroup.procs")):
            try:
                for value in source.read_text().split():
                    pids.add(int(value))
            except FileNotFoundError:
                continue
            if len(pids) > self.tasks_max:
                raise ContainmentUnavailable("cgroup membership exceeds TasksMax")
        births: dict[str, str] = {}
        for pid in sorted(pids):
            birth = _proc_birth(pid)
            if birth is not None:
                births[str(pid)] = birth
        return sorted(int(pid) for pid in births), births

    def _verify_identity(self, record: _Record, values: Mapping[str, str], *, retiring: bool = False) -> None:
        pinned = record.details
        if values["Id"] != pinned["unit"]:
            raise OwnershipMismatch("systemd unit identity changed")
        if values["InvocationID"] != pinned["invocation_id"]:
            raise OwnershipMismatch("systemd InvocationID changed")
        allowed_groups = (pinned["control_group"], "") if retiring else (pinned["control_group"],)
        if values["ControlGroup"] not in allowed_groups:
            raise OwnershipMismatch("systemd ControlGroup changed")
        if not retiring and values["ControlGroup"] == "":
            raise OwnershipMismatch("systemd ControlGroup disappeared")
        if values["ExecMainStartTimestampMonotonic"] != pinned["started_monotonic"]:
            raise OwnershipMismatch("systemd execution start identity changed")
        if values["WorkingDirectory"] != pinned["working_directory"]:
            raise OwnershipMismatch("systemd WorkingDirectory changed")
        current_main = int(values["MainPID"] or "0")
        if current_main not in (0, pinned["main_pid"]):
            raise OwnershipMismatch("systemd MainPID changed")
        birth = _proc_birth(pinned["main_pid"])
        if birth is not None and birth != record.owned.birth_ref:
            raise OwnershipMismatch("systemd MainPID birth identity changed")
        self._validate_policy(values)

    def launch(self, argv: Sequence[str], *, cwd: str, env: Mapping[str, str], label: str) -> OwnedProcess:
        with self._lifecycle_lock:
            if self._closed:
                raise ContainmentUnavailable("SystemdUserSupervisor is closed")
            return self._launch(argv, cwd=cwd, env=env, label=label)

    def _launch(self, argv: Sequence[str], *, cwd: str, env: Mapping[str, str], label: str) -> OwnedProcess:
        args = _validate_launch(argv, env, label)
        executable = Path(args[0])
        workdir = Path(cwd)
        if (not executable.is_absolute() or not executable.is_file()
                or not workdir.is_absolute() or not workdir.is_dir()
                or any(ord(char) < 32 for char in cwd)):
            raise ValueError("launch requires explicit executable and authorized absolute cwd")
        unit = self._unit_name(label)
        quota = f"{self.cpu_quota_percent:g}%"
        command = [
            SYSTEMD_RUN, "--user", f"--unit={unit}", "--service-type=exec", "--pipe",
            "--wait", "--collect", "--quiet", f"--property=WorkingDirectory={cwd}",
            "--property=ExitType=cgroup", "--property=KillMode=control-group",
            "--property=SendSIGKILL=yes", f"--property=TimeoutStopSec={self.termination_timeout:g}s",
            f"--property=TasksMax={self.tasks_max}", f"--property=MemoryMax={self.memory_max}",
            f"--property=CPUQuota={quota}", "--property=NoNewPrivileges=yes",
            "--property=RestrictSUIDSGID=yes", "--property=LockPersonality=yes",
            "--property=UMask=0077",
        ]
        connection_environment = {
            "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.geteuid()}"),
            "DBUS_SESSION_BUS_ADDRESS": os.environ.get(
                "DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{os.geteuid()}/bus",
            ),
        }
        if any(key in env and env[key] != value for key, value in connection_environment.items()):
            raise ValueError("target environment cannot replace the systemd user bus binding")
        environment_path = self._write_environment_file(env)
        command.append(f"--property=EnvironmentFile={environment_path}")
        command.extend(("--", *args))
        wrapper_environment = {**connection_environment, "LANG": "C.UTF-8"}
        transport = None
        try:
            transport = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                close_fds=True, env=wrapper_environment,
            )
            deadline = time.monotonic() + self.termination_timeout
            while True:
                values = self._show(unit)
                if values["ActiveState"] == "active" and int(values["MainPID"] or "0") > 0:
                    break
                if transport.poll() is not None:
                    raise ContainmentUnavailable("transient service exited before admission")
                if time.monotonic() >= deadline:
                    raise ContainmentUnavailable("transient service admission timed out")
                time.sleep(0.02)
            self._validate_policy(values)
            main_pid = int(values["MainPID"])
            birth = _proc_birth(main_pid)
            if birth is None:
                raise ContainmentUnavailable("systemd MainPID exited before birth was pinned")
            control_group = values["ControlGroup"]
            members, _ = self._members(control_group, unit)
            if main_pid not in members:
                raise ContainmentUnavailable("MainPID is not in the admitted ControlGroup")
            process = _SystemdProcess(transport, self, unit, main_pid)
            owned = OwnedProcess(process, f"systemd-user:{unit}:{values['InvocationID']}", birth)
            details = {
                "unit": unit, "invocation_id": values["InvocationID"], "main_pid": main_pid,
                "control_group": control_group,
                "started_monotonic": values["ExecMainStartTimestampMonotonic"],
                "working_directory": values["WorkingDirectory"],
                "policy": self._validate_policy(values), "transport_pid": transport.pid,
            }
            with self._lock:
                self._records[owned.containment_id] = _Record(owned, unit, label, details)
            return owned
        except BaseException:
            self._run_systemctl(("stop", unit), check=False)
            if transport is not None:
                try:
                    transport.wait(timeout=self.termination_timeout)
                except subprocess.TimeoutExpired:
                    transport.kill()
                    transport.wait(timeout=2)
            raise
        finally:
            self._remove_environment_file(environment_path)

    def inspect(self, handle: OwnedProcess) -> dict[str, Any]:
        with self._lock:
            record = self._record(handle)
            if record.terminal is not None:
                return dict(record.terminal)
            values = self._show(record.details["unit"])
            if values["LoadState"] == "not-found":
                raise OwnershipMismatch("owned transient unit disappeared before verified termination")
            self._verify_identity(record, values)
            members, births = self._members(record.details["control_group"], record.details["unit"])
            root_birth = _proc_birth(record.details["main_pid"])
            root_exited = root_birth is None
            if root_birth is not None and root_birth != handle.birth_ref:
                raise OwnershipMismatch("root PID was reused")
            return {
                "containment_id": handle.containment_id, "birth_ref": handle.birth_ref,
                "backend": "systemd-user-transient-service", "unit": record.details["unit"],
                "invocation_id": record.details["invocation_id"],
                "main_pid": record.details["main_pid"],
                "control_group": record.details["control_group"],
                "started_monotonic": record.details["started_monotonic"],
                "active_state": values["ActiveState"], "sub_state": values["SubState"],
                "root_exited": root_exited, "remaining_pids": members,
                "member_birth_refs": births, "policy": dict(record.details["policy"]),
                "transport_pid": record.details["transport_pid"],
                "wrapper_exited": handle.process.poll() is not None,
                "verified": values["ActiveState"] == "active" and bool(members),
                "scope": "one_transient_user_service_control_group",
            }

    def terminate_tree(self, handle: OwnedProcess) -> dict[str, Any]:
        with self._controller_lock, self._lock:
            record = self._record(handle)
            if record.terminal is not None:
                return dict(record.terminal)
            unit = record.details["unit"]
            initial = self._show(unit)
            if initial["LoadState"] != "not-found":
                self._verify_identity(record, initial)
                stopped = self._run_systemctl(("stop", unit), check=False)
                if stopped.returncode != 0 and self._show(unit)["LoadState"] != "not-found":
                    raise ContainmentUnavailable("systemctl could not stop the owned transient unit")
            deadline = time.monotonic() + self.termination_timeout
            last_state = "unknown"
            load_state = "unknown"
            while True:
                values = self._show(unit)
                load_state = values["LoadState"]
                if values["LoadState"] != "not-found":
                    self._verify_identity(record, values, retiring=True)
                members, _ = self._members(record.details["control_group"], unit)
                last_state = "inactive" if load_state == "not-found" else values["ActiveState"]
                wrapper_exited = handle.process.poll() is not None
                if not members and last_state in ("inactive", "failed") and wrapper_exited:
                    break
                if time.monotonic() >= deadline:
                    raise ContainmentUnavailable("systemd unit termination left residual capacity")
                time.sleep(0.02)
            returncode = handle.process.wait(timeout=2)
            record.terminal = {
                "containment_id": handle.containment_id, "birth_ref": handle.birth_ref,
                "backend": "systemd-user-transient-service", "unit": unit,
                "invocation_id": record.details["invocation_id"],
                "main_pid": record.details["main_pid"],
                "control_group": record.details["control_group"],
                "started_monotonic": record.details["started_monotonic"],
                "active_state": last_state, "root_exited": True, "remaining_pids": [],
                "load_state": load_state,
                "wrapper_exited": True, "wrapper_returncode": returncode,
                "verified": True, "scope": "one_transient_user_service_control_group",
            }
            return dict(record.terminal)

    def close(self) -> None:
        failures = []
        with self._lifecycle_lock:
            self._closed = True
            for record in list(self._records.values()):
                if record.terminal is not None:
                    continue
                try:
                    self.terminate_tree(record.owned)
                except (ContainmentUnavailable, OwnershipMismatch, OSError,
                        subprocess.SubprocessError) as error:
                    failures.append(type(error).__name__)
        if failures:
            kinds = ",".join(sorted(set(failures)))
            raise ContainmentUnavailable(
                f"Supervisor close failed for {len(failures)} owned record(s): {kinds}"
            )
