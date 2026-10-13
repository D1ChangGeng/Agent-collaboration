"""Owner-selected POSIX process management for a single process session.

Controls the owned process group. Commands can create processes outside that
session; select Systemd/Docker supervision when subtree containment is required.
"""
from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import time

from runtime.supervisor import (
    OwnedProcess,
    OwnershipMismatch,
    _Ownership,
    _proc_birth,
    _Record,
    _validate_launch,
)


class PosixProcessSupervisor(_Ownership):
    def __init__(self, *, termination_timeout=5.0):
        super().__init__()
        if os.name != "posix" or not os.path.isdir("/proc"):
            raise RuntimeError("POSIX process identity is unavailable")
        self.termination_timeout = termination_timeout

    @staticmethod
    def _members(pid):
        members = []
        for entry in os.scandir("/proc"):
            if not entry.name.isdigit():
                continue
            try:
                with open(entry.path + "/stat") as source:
                    fields = source.read().rsplit(")", 1)[1].split()
                if fields[0] != "Z" and int(fields[2]) == pid and int(fields[3]) == pid:
                    members.append(int(entry.name))
            except (OSError, ValueError, IndexError):
                continue
        return sorted(members)

    def launch(self, argv, *, cwd, env, label):
        if not isinstance(label, str) or not label or "\0" in label:
            raise ValueError("operation label is invalid")
        process_label = "acs-native-"+hashlib.sha256(label.encode()).hexdigest()[:32]
        arguments = _validate_launch(argv, env, process_label)
        process = subprocess.Popen(arguments, cwd=cwd, env=dict(env), start_new_session=True,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        birth = _proc_birth(process.pid)
        if not birth:
            process.kill()
            process.wait()
            raise RuntimeError("launched process identity is unavailable")
        handle = OwnedProcess(process, f"process-session:{process.pid}:{birth}", birth)
        self._records[handle.containment_id] = _Record(handle, process.pid, label)
        return handle

    def inspect(self, handle):
        self._record(handle)
        actual = _proc_birth(handle.process.pid)
        if actual is not None and actual != handle.birth_ref:
            raise OwnershipMismatch("owned process ID has been reused")
        members = self._members(handle.process.pid)
        return {"verified": True, "containment_id": handle.containment_id,
                "birth_ref": handle.birth_ref, "backend": "posix-process-session",
                "scope": "owned_process_group", "subtree_containment": False,
                "alive": bool(members), "pid": handle.process.pid, "members": members,
                "root_exit_code": handle.process.poll(), "remaining_group_members": members}

    def terminate_tree(self, handle):
        self.inspect(handle)
        for selected_signal in (signal.SIGTERM, signal.SIGKILL):
            if not self._members(handle.process.pid):
                break
            self.inspect(handle)
            try:
                os.killpg(handle.process.pid, selected_signal)
            except ProcessLookupError:
                break
            end = time.monotonic() + self.termination_timeout
            while self._members(handle.process.pid) and time.monotonic() < end:
                time.sleep(0.02)
        handle.process.wait(timeout=self.termination_timeout)
        proof = self.inspect(handle)
        if proof["alive"]:
            raise RuntimeError("owned process group has not stopped")
        root_status = handle.process.poll()
        remaining = self._members(handle.process.pid)
        if root_status is None or remaining:
            raise RuntimeError("owned process stop readback is incomplete")
        return {**proof, "stopped": root_status is not None and not remaining,
                "root_exit_code": root_status, "remaining_group_members": remaining}

    def close(self):
        for record in tuple(self._records.values()):
            self.terminate_tree(record.owned)
