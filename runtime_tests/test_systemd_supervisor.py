from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from runtime.supervisor import OwnedProcess, OwnershipMismatch
from runtime.systemd_supervisor import SystemdUserSupervisor

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "systemd_jsonl_fixture.py"
ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONUNBUFFERED": "1"}


def request(handle, value):
    handle.process.stdin.write((json.dumps(value) + "\n").encode())
    handle.process.stdin.flush()
    return json.loads(handle.process.stdout.readline())


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("condition did not become true")


@pytest.fixture
def supervisor():
    if not sys.platform.startswith("linux") or os.geteuid() == 0:
        pytest.skip("real systemd --user test requires a non-root Linux user")
    value = SystemdUserSupervisor(tasks_max=16, memory_max=134_217_728,
                                  cpu_quota_percent=50, termination_timeout=5)
    yield value
    value.close()


def launch(supervisor, label):
    return supervisor.launch([sys.executable, str(FIXTURE)], cwd=str(HERE), env=ENV, label=label)


def test_bidirectional_stdio_grandchild_root_exit_and_isolated_cleanup(supervisor):
    target = launch(supervisor, "jsonl-target")
    control = launch(supervisor, "jsonl-control")
    try:
        pong = request(target, {"command": "ping", "value": "round-trip"})
        assert pong["kind"] == "pong" and pong["value"] == "round-trip"
        error = json.loads(target.process.stderr.readline())
        assert error == {"kind": "stderr", "value": "round-trip"}
        spawned = request(target, {"command": "spawn"})
        before = supervisor.inspect(target)
        assert before["verified"] and {before["main_pid"], spawned["pid"]} <= set(before["remaining_pids"])
        exiting = request(target, {"command": "exit-root"})
        assert exiting["child_pid"] == spawned["pid"]
        after = wait_for(lambda: (proof if (proof := supervisor.inspect(target))["root_exited"] else None))
        assert spawned["pid"] in after["remaining_pids"]
        assert not after["wrapper_exited"] and after["active_state"] == "active"
        terminated = supervisor.terminate_tree(target)
        assert terminated["verified"] and terminated["remaining_pids"] == []
        assert terminated["active_state"] == "inactive" and terminated["wrapper_exited"]
        survivor = supervisor.inspect(control)
        assert survivor["verified"] and survivor["active_state"] == "active"
    finally:
        supervisor.terminate_tree(control)


def test_forged_handle_is_rejected(supervisor):
    owned = launch(supervisor, "forged-handle")
    try:
        forged = OwnedProcess(owned.process, owned.containment_id, owned.birth_ref)
        with pytest.raises(OwnershipMismatch, match="not issued"):
            supervisor.inspect(forged)
        with pytest.raises(OwnershipMismatch, match="not issued"):
            supervisor.terminate_tree(forged)
    finally:
        supervisor.terminate_tree(owned)


def test_secret_is_imported_by_name_without_cmdline_or_record_exposure(supervisor):
    secret = "fixture-secret-" + os.urandom(16).hex()
    environment = {**ENV, "FIXTURE_SERVER_PASSWORD": secret}
    owned = supervisor.launch([sys.executable, str(FIXTURE)], cwd=str(HERE), env=environment,
                              label="secret-environment")
    try:
        proof = supervisor.inspect(owned)
        wrapper_cmdline = Path(f"/proc/{owned.process.transport_pid}/cmdline").read_bytes()
        wrapper_environment = Path(f"/proc/{owned.process.transport_pid}/environ").read_bytes()
        exec_start = subprocess.run(
            ["/usr/bin/systemctl", "--user", "show", proof["unit"], "--property=ExecStart"],
            check=True, capture_output=True,
        ).stdout
        journal = subprocess.run(
            ["/usr/bin/journalctl", "--user-unit", proof["unit"], "--no-pager", "--output=cat"],
            check=False, capture_output=True,
        ).stdout
        transient = Path(f"/run/user/{os.geteuid()}/systemd/transient/{proof['unit']}")
        recorded = transient.read_bytes() if transient.exists() else b""
        assert secret.encode() not in wrapper_cmdline + wrapper_environment + exec_start + journal + recorded
        assert b"FIXTURE_SERVER_PASSWORD" not in wrapper_environment
        assert b"--setenv=FIXTURE_SERVER_PASSWORD" not in wrapper_cmdline
        assert b"EnvironmentFile=/run/user/" in wrapper_cmdline
        received = request(owned, {"command": "env-digest", "name": "FIXTURE_SERVER_PASSWORD"})
        assert received["sha256"] == hashlib.sha256(secret.encode()).hexdigest()
        assert secret not in json.dumps(supervisor.inspect(owned), sort_keys=True)
        assert list(supervisor._environment_directory().iterdir()) == []
    finally:
        supervisor.terminate_tree(owned)


def test_terminate_accepts_collected_unit_only_after_empty_cgroup_and_wrapper_exit(supervisor):
    owned = launch(supervisor, "fast-collect")
    proof = supervisor.inspect(owned)
    assert request(owned, {"command": "exit-clean"})["kind"] == "root-exiting-clean"
    owned.process.wait(timeout=5)
    wait_for(lambda: subprocess.run(
        ["/usr/bin/systemctl", "--user", "show", proof["unit"], "--property=LoadState", "--value"],
        check=True, capture_output=True, text=True,
    ).stdout.strip() == "not-found")
    terminated = supervisor.terminate_tree(owned)
    assert terminated["verified"] and terminated["load_state"] == "not-found"
    assert terminated["remaining_pids"] == [] and terminated["wrapper_exited"]


def test_launch_error_does_not_echo_environment_values(supervisor, tmp_path):
    secret = "error-secret-" + os.urandom(16).hex()
    with pytest.raises(ValueError) as caught:
        supervisor.launch(
            [sys.executable, str(FIXTURE)], cwd=str(tmp_path / "missing"),
            env={**ENV, "FIXTURE_SERVER_PASSWORD": secret}, label="secret-error",
        )
    assert secret not in str(caught.value)


def test_environment_file_escaping_round_trips_without_residue(supervisor):
    value = 'spaces " quotes \\ slash $ dollar ` tick and 世界'
    owned = supervisor.launch(
        [sys.executable, str(FIXTURE)], cwd=str(HERE),
        env={**ENV, "FIXTURE_COMPLEX_VALUE": value}, label="environment-escaping",
    )
    try:
        received = request(owned, {"command": "env-digest", "name": "FIXTURE_COMPLEX_VALUE"})
        assert received["sha256"] == hashlib.sha256(value.encode()).hexdigest()
        assert list(supervisor._environment_directory().iterdir()) == []
    finally:
        supervisor.terminate_tree(owned)


@pytest.mark.parametrize("change", [
    {"BAD-NAME": "value"},
    {"GOOD_NAME": "line1\nline2"},
    {"GOOD_NAME": "tab\tvalue"},
    {"GOOD_NAME": "control\x7fvalue"},
])
def test_environment_file_rejects_invalid_names_and_controls(supervisor, change):
    with pytest.raises(ValueError):
        supervisor.launch(
            [sys.executable, str(FIXTURE)], cwd=str(HERE), env={**ENV, **change},
            label="invalid-environment",
        )
    assert list(supervisor._environment_directory().iterdir()) == []


def test_post_creation_launch_failure_removes_environment_file(supervisor, tmp_path):
    executable = tmp_path / "not-executable"
    executable.write_text("fixture", encoding="utf-8")
    secret = "failure-secret-" + os.urandom(16).hex()
    with pytest.raises(Exception) as caught:
        supervisor.launch(
            [str(executable)], cwd=str(tmp_path),
            env={**ENV, "FIXTURE_SERVER_PASSWORD": secret}, label="failed-exec",
        )
    assert secret not in str(caught.value)
    assert list(supervisor._environment_directory().iterdir()) == []


def test_ld_preload_constructor_runs_only_in_owned_service(supervisor, tmp_path):
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("C compiler unavailable for LD_PRELOAD constructor regression")
    source = tmp_path / "constructor.c"
    library = tmp_path / "constructor.so"
    marker = tmp_path / "constructor-pids"
    source.write_text(
        "#include <fcntl.h>\n#include <stdio.h>\n#include <stdlib.h>\n#include <unistd.h>\n"
        "__attribute__((constructor)) static void loaded(void) {"
        "const char *p=getenv(\"PRELOAD_MARKER\"); if(!p)return; "
        "int f=open(p,O_WRONLY|O_CREAT|O_APPEND,0600); if(f>=0){dprintf(f,\"%d\\n\",getpid());close(f);}}\n",
        encoding="utf-8",
    )
    subprocess.run([compiler, "-shared", "-fPIC", "-o", str(library), str(source)], check=True)
    owned = supervisor.launch(
        [sys.executable, str(FIXTURE)], cwd=str(HERE),
        env={**ENV, "LD_PRELOAD": str(library), "PRELOAD_MARKER": str(marker)},
        label="preload-constructor",
    )
    try:
        wait_for(lambda: marker.exists() and marker.read_text().strip())
        loaded_pids = {int(value) for value in marker.read_text().split()}
        assert owned.process.pid in loaded_pids
        assert owned.process.transport_pid not in loaded_pids
        wrapper_environment = Path(f"/proc/{owned.process.transport_pid}/environ").read_bytes()
        assert b"LD_PRELOAD" not in wrapper_environment
        assert str(library).encode() not in wrapper_environment
    finally:
        supervisor.terminate_tree(owned)


def test_close_waits_for_inflight_launch_then_terminates_it(supervisor, monkeypatch):
    entered, release = Event(), Event()
    original = supervisor._launch

    def gated(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(supervisor, "_launch", gated)
    with ThreadPoolExecutor(max_workers=2) as pool:
        launched = pool.submit(launch, supervisor, "close-race")
        assert entered.wait(5)
        closing = pool.submit(supervisor.close)
        assert not closing.done()
        release.set()
        owned = launched.result(timeout=10)
        closing.result(timeout=10)
    assert owned.process.poll() is not None
    with pytest.raises(Exception, match="closed"):
        launch(supervisor, "after-close")


def test_close_continues_after_identity_conflict_and_reports_summary(supervisor, monkeypatch):
    conflicted = launch(supervisor, "close-conflict")
    healthy = launch(supervisor, "close-healthy")
    conflict_unit = supervisor.inspect(conflicted)["unit"]
    original = supervisor._show

    def conflict(unit):
        values = original(unit)
        if unit == conflict_unit:
            values["InvocationID"] += "-replacement"
        return values

    monkeypatch.setattr(supervisor, "_show", conflict)
    with pytest.raises(Exception, match="1 owned record"):
        supervisor.close()
    assert conflicted.process.poll() is None
    assert supervisor.inspect(healthy)["verified"]
    assert supervisor.inspect(healthy)["remaining_pids"] == []
    monkeypatch.setattr(supervisor, "_show", original)
    supervisor.terminate_tree(conflicted)


@pytest.mark.parametrize("field", ["Id", "InvocationID", "MainPID", "ControlGroup",
                                    "ExecMainStartTimestampMonotonic", "WorkingDirectory"])
def test_each_pinned_systemd_identity_replacement_is_rejected(supervisor, monkeypatch, field):
    owned = launch(supervisor, "identity-replacement")
    original = supervisor._show
    try:
        values = original(supervisor.inspect(owned)["unit"])
        changed = dict(values)
        changed[field] = "999999" if field == "MainPID" else values[field] + "-replacement"
        monkeypatch.setattr(supervisor, "_show", lambda _unit: changed)
        with pytest.raises(OwnershipMismatch):
            supervisor.inspect(owned)
    finally:
        monkeypatch.setattr(supervisor, "_show", original)
        supervisor.terminate_tree(owned)


def test_real_same_unit_replacement_rejects_old_handle(supervisor):
    owned = launch(supervisor, "real-unit-replacement")
    unit = supervisor.inspect(owned)["unit"]
    subprocess.run(["/usr/bin/systemctl", "--user", "stop", unit], check=True)
    owned.process.wait(timeout=5)
    subprocess.run([
        "/usr/bin/systemd-run", "--user", f"--unit={unit}", "--service-type=exec", "--collect",
        "--quiet", "--property=ExitType=cgroup", "--", "/bin/sleep", "30",
    ], check=True)
    try:
        wait_for(lambda: subprocess.run(
            ["/usr/bin/systemctl", "--user", "is-active", "--quiet", unit], check=False,
        ).returncode == 0)
        with pytest.raises(OwnershipMismatch, match="InvocationID changed"):
            supervisor.inspect(owned)
    finally:
        subprocess.run(["/usr/bin/systemctl", "--user", "stop", unit], check=False)
        supervisor._records.pop(owned.containment_id, None)


@pytest.mark.parametrize("label", ["../escape", "bad/unit", "", "x" * 97])
def test_unit_name_cannot_be_supplied_through_label(supervisor, label):
    with pytest.raises(ValueError):
        supervisor.launch([sys.executable, str(FIXTURE)], cwd=str(HERE), env=ENV, label=label)
