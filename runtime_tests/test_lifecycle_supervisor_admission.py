"""Final launch callback boundaries; no payload process is started."""
import os
import sys
import threading
from pathlib import Path

import pytest

from runtime.posix_process_supervisor import PosixProcessSupervisor
from runtime.supervisor import WindowsJobSupervisor
from runtime.systemd_supervisor import SystemdUserSupervisor


def denied():
    raise PermissionError("current lifecycle admission revoked")


def test_posix_owner_checks_final_admission_immediately_before_popen(tmp_path, monkeypatch):
    import runtime.posix_process_supervisor as module

    supervisor = object.__new__(PosixProcessSupervisor)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("payload was started"))
    with pytest.raises(PermissionError, match="revoked"):
        supervisor.launch([sys.executable, "--version"], cwd=str(tmp_path), env={}, label="original-operation", before_start=denied)


def test_systemd_rechecks_after_preparation_and_does_not_stop_an_uncreated_or_other_unit(tmp_path, monkeypatch):
    import runtime.systemd_supervisor as module

    supervisor = object.__new__(SystemdUserSupervisor)
    # Exercise the Linux owner path without starting a process on this host.
    monkeypatch.setattr(module.os, "geteuid", lambda: 1000, raising=False)
    supervisor._lifecycle_lock = threading.RLock()
    supervisor._closed = False
    supervisor.termination_timeout = 1
    supervisor.cpu_quota_percent, supervisor.tasks_max, supervisor.memory_max = 50, 10, 1024
    state = {"prepared": False, "removed": False}
    supervisor._unit_name = lambda _label: "original-operation.service"

    def environment(_env):
        state["prepared"] = True
        return tmp_path / "private.env"

    def final():
        assert state["prepared"]
        denied()

    supervisor._write_environment_file = environment
    supervisor._remove_environment_file = lambda _path: state.update(removed=True)
    supervisor._run_systemctl = lambda *_args, **_kwargs: pytest.fail("pre-effect refusal stopped an unowned unit")
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("payload was started"))
    with pytest.raises(PermissionError, match="revoked"):
        supervisor.launch([str(Path(sys.executable).resolve()), "--version"], cwd=str(tmp_path), env={},
                          label="original-operation", before_start=final)
    assert state["removed"]


@pytest.mark.skipif(os.name != "nt", reason="actual Windows Job admission boundary")
def test_windows_job_checks_admission_after_policy_and_before_suspended_process_creation(tmp_path, monkeypatch):
    import runtime.supervisor as module

    supervisor = WindowsJobSupervisor()
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("payload was created"))
    try:
        with pytest.raises(PermissionError, match="revoked"):
            supervisor.launch([str(Path(sys.executable).resolve()), "--version"], cwd=str(tmp_path), env={},
                              label="original-operation", before_start=denied)
    finally:
        supervisor.close()
