"""Host-side exact-run cleanup after a no-model supervisor owner exits abruptly."""

from __future__ import annotations

import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from tools.runtime.p1_codex_host_scene import postflight_run


def _private_root():
    root = Path(f"/run/user/{os.geteuid()}/acs-p1-codex")
    root.mkdir(mode=0o700, exist_ok=True)
    info = root.stat(follow_symlinks=False)
    assert stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
    assert stat.S_IMODE(info.st_mode) == 0o700
    return root


@pytest.mark.skipif(sys.platform != "linux", reason="Linux user manager required")
def test_postflight_requires_environment_file_directory_empty():
    if os.geteuid() == 0:
        pytest.skip("non-root user manager required")
    root = _private_root()
    run_id = "p1-run-" + uuid.uuid4().hex
    host_root = root / run_id
    host_root.mkdir(mode=0o700)
    (host_root / "ledger").mkdir(mode=0o700)
    environment = host_root / "systemd-env"
    environment.mkdir(mode=0o700)
    residue = environment / "leftover.env"
    residue.write_text("FIXTURE=1\n", encoding="utf-8")
    residue.chmod(0o600)
    try:
        observed = postflight_run(host_root, run_id)
        assert observed["status"] == "uncertain"
        assert observed["environment_files_remaining"] == 1
        residue.unlink()
        cleared = postflight_run(host_root, run_id)
        assert cleared["status"] == "clean"
        assert cleared["environment_files_remaining"] == 0
    finally:
        resolved = host_root.resolve(strict=True)
        assert resolved.parent == root.resolve(strict=True)
        shutil.rmtree(resolved)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux user manager required")
def test_killed_host_owner_leaves_uncertain_intent_and_quarantines_run_unit():
    if os.geteuid() == 0:
        pytest.skip("non-root user manager required")
    root = _private_root()
    run_id = "p1-run-" + uuid.uuid4().hex
    host_root = root / run_id
    host_root.mkdir(mode=0o700)
    ledger_dir = host_root / "ledger"
    ledger_dir.mkdir(mode=0o700)
    ledger = ledger_dir / "runs.sqlite"
    descriptor = os.open(ledger, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(descriptor)
    with sqlite3.connect(ledger) as connection:
        connection.execute(
            "CREATE TABLE codex_host_boot (run_id TEXT PRIMARY KEY,state TEXT NOT NULL,"
            "proof_json TEXT,created_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO codex_host_boot VALUES (?,'intent',NULL,'fixture')", (run_id,)
        )
    child_code = (
        "import os,sys;"
        "from runtime.systemd_supervisor import SystemdUserSupervisor;"
        "s=SystemdUserSupervisor(tasks_max=16,memory_max=134217728,"
        "cpu_quota_percent=50,termination_timeout=5);"
        "s.launch(['/usr/bin/sleep','30'],cwd='/tmp',"
        "env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},label=sys.argv[1]);"
        "os._exit(83)"
    )
    inherited = os.environ.get("PYTHONPATH")
    pythonpath = str(Path(__file__).parents[3])
    if inherited:
        pythonpath += os.pathsep + inherited
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "PYTHONPATH": pythonpath,
        "XDG_RUNTIME_DIR": f"/run/user/{os.geteuid()}",
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{os.geteuid()}/bus",
    }
    try:
        crashed = subprocess.run(
            [sys.executable, "-c", child_code, run_id],
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=15,
            check=False,
        )
        assert crashed.returncode == 83, crashed.stderr.decode()[-500:]
        proof = postflight_run(host_root, run_id)
        assert proof["status"] == "uncertain" and proof["boot_state"] == "intent"
        assert proof["quarantined_units"], "test did not reach a surviving host unit"
        assert proof["remaining_pids"] == []
        assert all(unit.startswith("acs-" + run_id + "-") for unit in proof["units_seen"])
        repeated = postflight_run(host_root, run_id)
        assert repeated["status"] == "uncertain" and repeated["remaining_pids"] == []
    finally:
        resolved = host_root.resolve(strict=True)
        assert resolved.parent == root.resolve(strict=True)
        shutil.rmtree(resolved)
