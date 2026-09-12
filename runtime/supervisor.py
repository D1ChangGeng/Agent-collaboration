"""Owned native-process containment for Node lifecycle control.

This supervises descendants; it is not a filesystem, network, credential or
external process-broker sandbox. Windows uses an unnamed non-breakaway Job.
Linux supports an explicit pinned Docker policy. The separate
``runtime.systemd_supervisor`` module provides reviewed non-root transient user
service containment. There is no process-group or Popen.kill fallback
advertised as subtree containment.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import stat
import subprocess
import threading
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ContainmentUnavailable(RuntimeError):
    pass


class OwnershipMismatch(RuntimeError):
    pass


@dataclass(frozen=True)
class OwnedProcess:
    process: Any
    containment_id: str
    birth_ref: str


@dataclass
class _Record:
    owned: OwnedProcess
    backend_ref: Any
    label: str
    details: dict[str, Any] = field(default_factory=dict)
    terminal: dict[str, Any] | None = None


def _validate_launch(argv: Sequence[str], env: Mapping[str, str], label: str) -> list[str]:
    if isinstance(argv, (str, bytes)) or not argv or any(not isinstance(v, str) or "\0" in v for v in argv):
        raise ValueError("argv must be a nonempty argument vector")
    if not isinstance(env, Mapping) or any(
        not isinstance(k, str) or not isinstance(v, str) or not k or "=" in k or "\0" in k + v
        for k, v in env.items()
    ):
        raise ValueError("env must be an explicit string allowlist")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", label):
        raise ValueError("label must be an explicit operation label of at most 96 characters")
    return list(argv)


class _Ownership:
    def __init__(self) -> None:
        self._records: dict[str, _Record] = {}
        self._lock = threading.RLock()

    def _record(self, owned: OwnedProcess) -> _Record:
        record = self._records.get(owned.containment_id)
        if record is None or record.owned is not owned:
            raise OwnershipMismatch("handle was not issued by this Supervisor instance")
        return record


class _WinAPI:
    """Win32 functions and structures, imported only on Windows."""
    def __init__(self) -> None:
        if os.name != "nt":
            raise ContainmentUnavailable("Windows Job Objects require Windows")
        from ctypes import wintypes as w
        self.w = w
        self.dll = ctypes.WinDLL("kernel32", use_last_error=True)
        size = ctypes.c_size_t

        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                        ("flags", w.DWORD), ("minimum", size), ("maximum", size),
                        ("active_limit", w.DWORD), ("affinity", size),
                        ("priority", w.DWORD), ("scheduling", w.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", IO), ("process_memory", size), ("job_memory", size),
                        ("peak_process", size), ("peak_job", size)]

        class ThreadEntry(ctypes.Structure):
            _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("tid", w.DWORD), ("pid", w.DWORD),
                        ("base_priority", w.LONG), ("delta_priority", w.LONG), ("flags", w.DWORD)]

        self.Extended, self.ThreadEntry = Extended, ThreadEntry
        prototypes = {
            "CreateJobObjectW": ([ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
            "SetInformationJobObject": ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
            "QueryInformationJobObject": ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD,
                                          ctypes.POINTER(w.DWORD)], w.BOOL),
            "AssignProcessToJobObject": ([w.HANDLE, w.HANDLE], w.BOOL),
            "IsProcessInJob": ([w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)], w.BOOL),
            "TerminateJobObject": ([w.HANDLE, w.UINT], w.BOOL),
            "OpenProcess": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
            "CloseHandle": ([w.HANDLE], w.BOOL),
            "GetProcessTimes": ([w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4, w.BOOL),
            "QueryFullProcessImageNameW": ([w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)], w.BOOL),
            "CreateToolhelp32Snapshot": ([w.DWORD, w.DWORD], w.HANDLE),
            "Thread32First": ([w.HANDLE, ctypes.POINTER(ThreadEntry)], w.BOOL),
            "Thread32Next": ([w.HANDLE, ctypes.POINTER(ThreadEntry)], w.BOOL),
            "OpenThread": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "ResumeThread": ([w.HANDLE], w.DWORD),
        }
        for name, (args, result) in prototypes.items():
            fn = getattr(self.dll, name)
            fn.argtypes, fn.restype = args, result

    @staticmethod
    def check(ok: Any, operation: str) -> None:
        if not ok:
            raise ContainmentUnavailable(f"{operation}: WinError {ctypes.get_last_error()}")

    def birth(self, process: subprocess.Popen) -> str:
        return self.birth_handle(process.pid, int(process._handle))

    def birth_handle(self, pid: int, process_handle: int) -> str:
        values = [self.w.FILETIME() for _ in range(4)]
        self.check(self.dll.GetProcessTimes(process_handle, *(ctypes.byref(v) for v in values)),
                   "GetProcessTimes")
        return f"win32:{pid}:{(values[0].dwHighDateTime << 32) | values[0].dwLowDateTime}"

    def image(self, process: subprocess.Popen) -> str:
        value = ctypes.create_unicode_buffer(32768)
        length = self.w.DWORD(len(value))
        self.check(self.dll.QueryFullProcessImageNameW(int(process._handle), 0, value, ctypes.byref(length)),
                   "QueryFullProcessImageNameW")
        return value.value

    def resume_root(self, pid: int) -> None:
        snapshot = self.dll.CreateToolhelp32Snapshot(0x4, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            self.check(False, "CreateToolhelp32Snapshot")
        threads = []
        try:
            entry = self.ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            ok = self.dll.Thread32First(snapshot, ctypes.byref(entry))
            while ok:
                if entry.pid == pid:
                    threads.append(entry.tid)
                ok = self.dll.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            self.dll.CloseHandle(snapshot)
        if len(threads) != 1:
            raise ContainmentUnavailable("suspended root does not have exactly one primary thread")
        thread = self.dll.OpenThread(0x2, False, threads[0])
        self.check(thread, "OpenThread")
        try:
            if self.dll.ResumeThread(thread) != 1:
                raise ContainmentUnavailable("primary thread suspension state changed before admission")
        finally:
            self.dll.CloseHandle(thread)

    def pids(self, job: int) -> list[int]:
        capacity = 256
        while capacity <= 65536:
            class Pids(ctypes.Structure):
                _fields_ = [("assigned", self.w.DWORD), ("count", self.w.DWORD),
                            ("pids", ctypes.c_size_t * capacity)]
            value = Pids()
            if self.dll.QueryInformationJobObject(job, 3, ctypes.byref(value), ctypes.sizeof(value), None):
                return sorted(int(v) for v in value.pids[:value.count])
            if ctypes.get_last_error() != 234:
                self.check(False, "QueryInformationJobObject(process list)")
            capacity *= 2
        raise ContainmentUnavailable("Job member inventory exceeds the verification bound")


class WindowsJobSupervisor(_Ownership):
    def __init__(self, *, max_processes: int = 128, termination_timeout: float = 5.0) -> None:
        super().__init__()
        if not 1 <= max_processes <= 1024 or not 0 < termination_timeout <= 60:
            raise ValueError("invalid process or termination bound")
        self.api = _WinAPI()
        self.max_processes, self.termination_timeout = max_processes, termination_timeout

    def _track_members(self, record: _Record) -> list[int]:
        pids = self.api.pids(record.backend_ref)
        tracked = record.details["member_handles"]
        for pid in pids:
            if pid in tracked:
                continue
            process_handle = self.api.dll.OpenProcess(0x00100000 | 0x1000, False, pid)
            if not process_handle:
                if pid not in self.api.pids(record.backend_ref):
                    continue  # already fully departed before a handle could be retained
                self.api.check(False, "OpenProcess(Job member)")
            try:
                birth = self.api.birth_handle(pid, process_handle)
            except BaseException:
                self.api.dll.CloseHandle(process_handle)
                raise
            tracked[pid] = (process_handle, birth)
        return pids

    def _close_tracked(self, record: _Record) -> None:
        for process_handle, _ in record.details["member_handles"].values():
            self.api.dll.CloseHandle(process_handle)
        record.details["member_handles"].clear()

    def launch(self, argv: Sequence[str], *, cwd: str, env: Mapping[str, str], label: str) -> OwnedProcess:
        args = _validate_launch(argv, env, label)
        if not Path(cwd).is_dir():
            raise ValueError("cwd must be an existing authorized directory")
        if not Path(args[0]).is_absolute() or not Path(args[0]).is_file():
            raise ValueError("Windows containment requires an explicit native executable path")
        job = self.api.dll.CreateJobObjectW(None, None)  # unnamed, non-inheritable
        self.api.check(job, "CreateJobObjectW")
        process = None
        assigned = False
        try:
            limits = self.api.Extended()
            limits.basic.flags = 0x2000 | 0x8  # KILL_ON_JOB_CLOSE | ACTIVE_PROCESS
            limits.basic.active_limit = self.max_processes
            self.api.check(self.api.dll.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)),
                           "SetInformationJobObject")
            process = subprocess.Popen(args, cwd=cwd, env=dict(env), stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       creationflags=0x4 | 0x08000000, close_fds=True)  # SUSPENDED | NO_WINDOW
            birth = self.api.birth(process)
            root_image = self.api.image(process)
            if Path(root_image).resolve() != Path(args[0]).resolve():
                raise ContainmentUnavailable("created root image differs from the authorized executable")
            self.api.check(self.api.dll.AssignProcessToJobObject(job, int(process._handle)), "AssignProcessToJobObject")
            assigned = True
            inside = self.api.w.BOOL()
            self.api.check(self.api.dll.IsProcessInJob(int(process._handle), job, ctypes.byref(inside)), "IsProcessInJob")
            if not inside.value or process.pid not in self.api.pids(job):
                raise ContainmentUnavailable("root Job membership was not verified before execution")
            owned = OwnedProcess(process, f"job:{label}:{uuid.uuid4().hex}", birth)
            record = _Record(owned, job, label, {"root_image": root_image, "member_handles": {}})
            with self._lock:
                self._records[owned.containment_id] = record
                self._track_members(record)
                self.api.resume_root(process.pid)
            return owned
        except BaseException:
            if process is not None:
                if assigned:
                    self.api.dll.TerminateJobObject(job, 1)
                else:
                    # Root is still suspended and has never executed payload.
                    process.kill()
                process.wait(timeout=self.termination_timeout)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
            if "record" in locals():
                self._close_tracked(record)
            self.api.dll.CloseHandle(job)
            if "owned" in locals():
                self._records.pop(owned.containment_id, None)
            raise

    def inspect(self, handle: OwnedProcess) -> dict[str, Any]:
        with self._lock:
            record = self._record(handle)
            if record.terminal is not None:
                return dict(record.terminal)
            limits = self.api.Extended()
            self.api.check(self.api.dll.QueryInformationJobObject(
                record.backend_ref, 9, ctypes.byref(limits), ctypes.sizeof(limits), None), "QueryInformationJobObject(limits)")
            identity_ok = self.api.birth(handle.process) == handle.birth_ref
            flags_ok = bool(limits.basic.flags & 0x2000) and not bool(limits.basic.flags & (0x800 | 0x1000))
            members = self._track_members(record)
            pending = []
            member_births = {}
            for pid, (process_handle, birth) in record.details["member_handles"].items():
                state = self.api.dll.WaitForSingleObject(process_handle, 0)
                if state == 0x102:  # Job enumeration may remove a member before its process signals exit.
                    pending.append(pid)
                elif state != 0:
                    self.api.check(False, "WaitForSingleObject(Job member)")
                member_births[str(pid)] = birth
            return {"containment_id": handle.containment_id, "birth_ref": handle.birth_ref,
                    "backend": "windows-job-object", "root_pid": handle.process.pid,
                    "root_exited": handle.process.poll() is not None, "remaining_pids": sorted(set(members + pending)),
                    "verified": identity_ok and flags_ok, "kill_on_close": bool(limits.basic.flags & 0x2000),
                    "breakaway_allowed": bool(limits.basic.flags & (0x800 | 0x1000)),
                    "label": record.label, "scope": "native_process_descendants",
                    "root_image": record.details["root_image"], "job_hierarchy": "owned_outer_job_and_nested_jobs",
                    "member_birth_refs": member_births, "pending_process_exits": sorted(set(pending) - set(members))}

    def terminate_tree(self, handle: OwnedProcess) -> dict[str, Any]:
        with self._lock:
            record = self._record(handle)
            if record.terminal is not None:
                return dict(record.terminal)
            self._track_members(record)
            self.api.check(self.api.dll.TerminateJobObject(record.backend_ref, 1), "TerminateJobObject")
            deadline = time.monotonic() + self.termination_timeout
            while True:
                proof = self.inspect(handle)
                if proof["root_exited"] and not proof["remaining_pids"]:
                    self._close_tracked(record)
                    self.api.dll.CloseHandle(record.backend_ref)
                    record.terminal = proof
                    return dict(proof)
                if time.monotonic() >= deadline:
                    proof["verified"] = False
                    proof["reason"] = "termination residuals remain"
                    return proof
                time.sleep(0.01)

    def close(self) -> None:
        for record in list(self._records.values()):
            self.terminate_tree(record.owned)


@dataclass(frozen=True)
class DockerBind:
    source: str
    target: str
    read_only: bool = True


@dataclass(frozen=True)
class DockerPolicy:
    image: str
    binds: tuple[DockerBind, ...] = ()
    uid: int = 65534
    gid: int = 65534
    pids_limit: int = 128
    memory_bytes: int = 268435456
    cpus: float = 1.0


def _proc_birth(pid: int) -> str | None:
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
        return f"linux:{pid}:{text[text.rfind(')') + 2:].split()[19]}"
    except (FileNotFoundError, ProcessLookupError):
        return None


class _DockerProcess:
    def __init__(self, transport: subprocess.Popen, supervisor: DockerSupervisor, cid: str, pid: int,
                 *, operation: str, started_at: str, root_birth: str) -> None:
        self._transport, self._supervisor, self._cid = transport, supervisor, cid
        self._operation, self._started_at, self._root_birth = operation, started_at, root_birth
        self.pid = pid
        self.stdin, self.stdout, self.stderr = transport.stdin, transport.stdout, transport.stderr
        self.returncode = None

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        value = self._supervisor._require_incarnation(
            self._cid, self._operation, self._started_at, self.pid, self._root_birth)
        if value["State"]["Running"]:
            return None
        self.returncode = int(value["State"]["ExitCode"])
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if self.returncode is not None:
                return self.returncode
            value = self.poll()
            if value is not None:
                self._transport.wait(timeout=5)
                return value
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(self._cid, timeout)
            time.sleep(0.02)


class DockerSupervisor(_Ownership):
    """An explicit local-image container, with no host Docker control mount."""
    LABEL = "org.achp.supervisor.operation"
    TMPFS_OPTIONS = frozenset(("rw", "nosuid", "nodev", "noexec", "size=16777216"))

    def __init__(self, policy: DockerPolicy, *, termination_timeout: float = 10.0) -> None:
        super().__init__()
        if os.name != "posix" or not Path("/proc/self/cgroup").exists():
            raise ContainmentUnavailable("Docker supervision requires a local Linux daemon and procfs")
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", policy.image):
            raise ValueError("Docker policy must pin a local full image ID; tags and automatic pulls are prohibited")
        if policy.uid <= 0 or policy.gid <= 0 or not 1 <= policy.pids_limit <= 1024:
            raise ValueError("container requires a non-root identity and bounded process count")
        if not 16777216 <= policy.memory_bytes <= 8589934592 or not 0 < policy.cpus <= 16:
            raise ValueError("container resource limits are outside policy bounds")
        self.policy, self.termination_timeout = policy, termination_timeout
        self._bind_identities: dict[str, tuple[int, int, int]] = {}
        forbidden = {"/", "/root", "/home", "/run", "/var", "/var/run", "/proc", "/sys", "/dev", "/etc"}
        targets = []
        for bind in policy.binds:
            path = Path(bind.source)
            target = Path(bind.target)
            mode = path.lstat().st_mode if path.exists() else 0
            if (not path.is_absolute() or not path.exists() or path.is_symlink()
                    or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))
                    or any(char in bind.source + bind.target for char in (",", "\n", "\r", "\0"))
                    or str(path.resolve()) in forbidden or path.name.endswith(".sock")
                    or not target.is_absolute() or ".." in target.parts or str(target) in forbidden
                    or str(target).startswith(("/proc/", "/sys/", "/dev/", "/run/"))):
                raise ValueError("bind must select a prepared authorized file/directory and an isolated target")
            info = path.lstat()
            self._bind_identities[bind.source] = (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode))
            if any(target == prior or target in prior.parents or prior in target.parents for prior in targets):
                raise ValueError("nested or overlapping bind targets are not supported")
            targets.append(target)
        image = json.loads(self._run(["image", "inspect", policy.image]).stdout)[0]
        if image["Id"] != policy.image or image["Os"] != "linux":
            raise ContainmentUnavailable("pinned local Linux image could not be verified")
        if image.get("Config", {}).get("Volumes"):
            raise ContainmentUnavailable("implicit image volumes are not admitted by the explicit mount policy")
        info = json.loads(self._run(["info", "--format", "{{json .}}"]).stdout)
        if info.get("CgroupVersion") != "2":
            raise ContainmentUnavailable("cgroup v2 read-back is required")

    @staticmethod
    def _run(arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(["docker", *arguments], capture_output=True, check=False, text=True, timeout=15)
        if check and result.returncode:
            raise ContainmentUnavailable(f"Docker operation {arguments[0]} failed: {result.stderr.strip()}")
        return result

    def _container(self, cid: str) -> dict[str, Any]:
        return json.loads(self._run(["inspect", cid]).stdout)[0]

    def _require_incarnation(self, cid: str, operation: str, started_at: str,
                             root_pid: int, root_birth: str | None) -> dict[str, Any]:
        """Revalidate the original incarnation before every Docker kill or rm."""
        value = self._container(cid)
        state = value["State"]
        if (value["Id"] != cid or value["Image"] != self.policy.image
                or value["Config"].get("Labels", {}).get(self.LABEL) != operation
                or state["StartedAt"] != started_at):
            raise OwnershipMismatch("container identity or StartedAt changed; lifecycle mutation refused")
        if state["Running"] and (
            root_pid <= 0 or state["Pid"] != root_pid or root_birth is None or _proc_birth(root_pid) != root_birth
        ):
            raise OwnershipMismatch("container process birth changed; lifecycle mutation refused")
        return value

    @classmethod
    def _tmpfs_verified(cls, host: dict[str, Any]) -> bool:
        tmpfs = host.get("Tmpfs")
        if not isinstance(tmpfs, dict) or set(tmpfs) != {"/tmp"} or not isinstance(tmpfs["/tmp"], str):
            return False
        options = tmpfs["/tmp"].split(",")
        return len(options) == len(cls.TMPFS_OPTIONS) and set(options) == cls.TMPFS_OPTIONS

    def _policy_verified(self, value: dict[str, Any], operation: str) -> bool:
        config, host = value["Config"], value["HostConfig"]
        mounts = sorted((entry["Type"], entry["Source"], entry["Destination"], entry["RW"])
                        for entry in value["Mounts"])
        expected_mounts = sorted(("bind", str(Path(bind.source).resolve()), bind.target, not bind.read_only)
                                 for bind in self.policy.binds)
        return bool(
            value["Image"] == self.policy.image
            and config.get("Labels", {}).get(self.LABEL) == operation
            and config["User"] == f"{self.policy.uid}:{self.policy.gid}"
            and host["ReadonlyRootfs"] and not host["Privileged"] and not host["CapAdd"]
            and "ALL" in host["CapDrop"] and host["NetworkMode"] == "none"
            and host["PidMode"] == "" and host["CgroupnsMode"] == "private" and host["IpcMode"] == "private"
            and host["SecurityOpt"] == ["no-new-privileges:true"] and not host["Devices"]
            and not host.get("DeviceRequests") and not host.get("DeviceCgroupRules")
            and host["RestartPolicy"]["Name"] in ("", "no")
            and host["PidsLimit"] == self.policy.pids_limit and host["Memory"] == self.policy.memory_bytes
            and host["MemorySwap"] == self.policy.memory_bytes and host["NanoCpus"] == int(self.policy.cpus * 1e9)
            and mounts == expected_mounts and self._tmpfs_verified(host)
        )

    def _cwd(self, cwd: str) -> str:
        candidate = Path(cwd)
        for bind in self.policy.binds:
            source = Path(bind.source).resolve()
            if source.is_dir() and candidate.is_absolute() and candidate.resolve().is_relative_to(source):
                return str(Path(bind.target) / candidate.resolve().relative_to(source))
        if cwd in ("/", "/tmp"):
            return cwd
        raise ValueError("cwd must resolve inside an explicitly mounted input or container /tmp")

    def launch(self, argv: Sequence[str], *, cwd: str, env: Mapping[str, str], label: str) -> OwnedProcess:
        args = _validate_launch(argv, env, label)
        if not args[0].startswith("/"):
            raise ValueError("container executable must be an explicit absolute path")
        operation = f"achp-{label.lower()}-{uuid.uuid4().hex}"
        cid = None
        transport = None
        cleanup_identity = None
        flags = ["create", "--pull=never", "--name", operation, "--label", f"{self.LABEL}={operation}",
                 "--interactive", "--network=none", "--read-only", "--cap-drop=ALL",
                 "--security-opt=no-new-privileges:true", "--cgroupns=private", "--ipc=private",
                 "--user", f"{self.policy.uid}:{self.policy.gid}", "--pids-limit", str(self.policy.pids_limit),
                 "--memory", str(self.policy.memory_bytes), "--memory-swap", str(self.policy.memory_bytes),
                 "--cpus", str(self.policy.cpus), "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=16777216",
                 "--workdir", self._cwd(cwd)]
        for key, value in env.items():
            flags += ["--env", f"{key}={value}"]
        for bind in self.policy.binds:
            info = Path(bind.source).lstat()
            identity = (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode))
            if identity != self._bind_identities[bind.source] or not (
                stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)
            ):
                raise ContainmentUnavailable("bind source type or identity changed before admission")
            flags += ["--mount", f"type=bind,source={Path(bind.source).resolve()},target={bind.target}"
                      + (",readonly" if bind.read_only else "")]
        flags += ["--entrypoint", args[0], self.policy.image, *args[1:]]
        try:
            cid = self._run(flags).stdout.strip()
            if not re.fullmatch(r"[a-f0-9]{64}", cid):
                raise ContainmentUnavailable("Docker create did not return a complete container ID")
            created = self._container(cid)
            cleanup_identity = (created["State"]["StartedAt"], int(created["State"]["Pid"]), None)
            if created["Id"] != cid or created["State"]["Running"] or not self._policy_verified(created, operation):
                raise ContainmentUnavailable("container policy did not verify before payload execution")
            transport = subprocess.Popen(["docker", "start", "--attach", "--interactive", cid],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            deadline = time.monotonic() + 5
            while True:
                value = self._container(cid)
                pid = int(value["State"]["Pid"])
                cleanup_identity = (value["State"]["StartedAt"], pid, _proc_birth(pid) if pid > 0 else None)
                if value["State"]["Running"] and pid > 0:
                    break
                if transport.poll() is not None or time.monotonic() > deadline:
                    raise ContainmentUnavailable("container exited before its process identity could be verified")
                time.sleep(0.02)
            proc_birth = _proc_birth(pid)
            membership = Path(f"/proc/{pid}/cgroup").read_text()
            relative = next((line.split(":", 2)[2] for line in membership.splitlines() if line.startswith("0::")), None)
            if not proc_birth or not relative or cid not in relative:
                raise ContainmentUnavailable("local container-specific cgroup identity is unavailable")
            cgroup = (Path("/sys/fs/cgroup") / relative.lstrip("/")).resolve()
            if not cgroup.is_relative_to("/sys/fs/cgroup"):
                raise ContainmentUnavailable("container cgroup escaped the cgroup filesystem")
            birth = f"docker:{cid}:{value['State']['StartedAt']}:{proc_birth}"
            process = _DockerProcess(transport, self, cid, pid, operation=operation,
                                     started_at=value["State"]["StartedAt"], root_birth=proc_birth)
            owned = OwnedProcess(process, operation, birth)
            record = _Record(owned, cid, label, {"started_at": value["State"]["StartedAt"],
                             "root_birth": proc_birth, "cgroup": str(cgroup), "observed": {pid: proc_birth}})
            with self._lock:
                self._records[operation] = record
                proof = self.inspect(owned)
                if not proof["verified"] or pid not in proof["remaining_pids"]:
                    raise ContainmentUnavailable("container isolation settings or membership did not verify")
            return owned
        except BaseException:
            if cid and re.fullmatch(r"[a-f0-9]{64}", cid) and cleanup_identity is not None:
                value = self._require_incarnation(cid, operation, *cleanup_identity)
                if value["State"]["Running"]:
                    self._require_incarnation(cid, operation, *cleanup_identity)
                    self._run(["kill", "--signal=KILL", cid])
                value = self._require_incarnation(cid, operation, *cleanup_identity)
                if value["State"]["Running"]:
                    raise ContainmentUnavailable("owned admission-failure container did not stop") from None
                self._run(["rm", cid])
            if transport is not None:
                transport.wait(timeout=5)
            self._records.pop(operation, None)
            raise

    def inspect(self, handle: OwnedProcess) -> dict[str, Any]:
        with self._lock:
            record = self._record(handle)
            if record.terminal is not None:
                return dict(record.terminal)
            value = self._container(record.backend_ref)
            host, state = value["HostConfig"], value["State"]
            policy_ok = (
                value["Id"] == record.backend_ref and self._policy_verified(value, handle.containment_id)
                and state["StartedAt"] == record.details["started_at"]
            )
            cgroup = Path(record.details["cgroup"])
            exists = cgroup.exists()
            pids = sorted(int(line) for line in (cgroup / "cgroup.procs").read_text().split()) if exists else []
            populated = bool(int(dict(line.split() for line in (cgroup / "cgroup.events").read_text().splitlines())["populated"])) if exists else False
            for pid in pids:
                birth = _proc_birth(pid)
                if birth is not None:
                    record.details["observed"][pid] = birth
            escaped = [pid for pid, birth in record.details["observed"].items()
                       if pid not in pids and _proc_birth(pid) == birth]
            running = bool(state["Running"])
            identity_ok = (not running or (state["Pid"] == handle.process.pid
                                          and _proc_birth(handle.process.pid) == record.details["root_birth"]))
            residuals = sorted(set(pids + escaped))
            return {"containment_id": handle.containment_id, "birth_ref": handle.birth_ref,
                    "backend": "docker-cgroup-v2", "container_id": record.backend_ref,
                    "root_pid": handle.process.pid, "root_exited": not running, "remaining_pids": residuals,
                    "verified": bool(policy_ok and identity_ok and not escaped and (exists if running else not populated)),
                    "cgroup": str(cgroup), "cgroup_populated": populated, "label": record.label,
                    "image": self.policy.image, "network": "none", "scope": "container_pid_namespace",
                    "uid": self.policy.uid, "read_only_root": bool(host["ReadonlyRootfs"]),
                    "capabilities_dropped": host["CapDrop"], "pids_limit": host["PidsLimit"],
                    "tmpfs": dict(host["Tmpfs"])}

    def terminate_tree(self, handle: OwnedProcess) -> dict[str, Any]:
        with self._lock:
            record = self._record(handle)
            if record.terminal is not None:
                return dict(record.terminal)
            identity = (record.details["started_at"], handle.process.pid, record.details["root_birth"])
            value = self._require_incarnation(record.backend_ref, handle.containment_id, *identity)
            initial = self.inspect(handle)
            if not initial["verified"]:
                raise OwnershipMismatch("containment proof is unverified; lifecycle mutation refused")
            if value["State"]["Running"]:
                self._require_incarnation(record.backend_ref, handle.containment_id, *identity)
                self._run(["kill", "--signal=KILL", record.backend_ref])
            deadline = time.monotonic() + self.termination_timeout
            while True:
                self._require_incarnation(record.backend_ref, handle.containment_id, *identity)
                proof = self.inspect(handle)
                if proof["root_exited"] and not proof["remaining_pids"] and proof["verified"]:
                    current = self._require_incarnation(record.backend_ref, handle.containment_id, *identity)
                    handle.process.returncode = int(current["State"]["ExitCode"])
                    handle.process._transport.wait(timeout=5)
                    current = self._require_incarnation(record.backend_ref, handle.containment_id, *identity)
                    if current["State"]["Running"]:
                        raise OwnershipMismatch("container restarted before removal; lifecycle mutation refused")
                    self._run(["rm", record.backend_ref])
                    proof["container_removed"] = True
                    record.terminal = proof
                    return dict(proof)
                if time.monotonic() >= deadline:
                    proof["verified"] = False
                    proof["reason"] = "termination residuals or unverifiable cgroup remain"
                    return proof
                time.sleep(0.02)

    def close(self) -> None:
        for record in list(self._records.values()):
            self.terminate_tree(record.owned)


class Supervisor:
    def __init__(self, *, docker_policy: DockerPolicy | None = None) -> None:
        if docker_policy is not None:
            self.backend = DockerSupervisor(docker_policy)
        elif os.name == "nt":
            self.backend = WindowsJobSupervisor()
        else:
            raise ContainmentUnavailable("no verified delegated cgroup or explicit Docker policy; launch is blocked")

    def launch(self, argv: Sequence[str], *, cwd: str, env: Mapping[str, str], label: str) -> OwnedProcess:
        return self.backend.launch(argv, cwd=cwd, env=env, label=label)

    def inspect(self, handle: OwnedProcess) -> dict[str, Any]:
        return self.backend.inspect(handle)

    def terminate_tree(self, handle: OwnedProcess) -> dict[str, Any]:
        return self.backend.terminate_tree(handle)

    def close(self) -> None:
        self.backend.close()
