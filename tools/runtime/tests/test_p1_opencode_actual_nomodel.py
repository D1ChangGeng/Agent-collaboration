"""Start the pinned OpenCode HTTP Driver under Systemd without a model request."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from runtime.codex_driver import AuthorizedOperation, BindingIdentity, DriverJournal
from runtime.opencode_driver import OpenCodeLaunchProfile, OpenCodeNativeDriver
from runtime.systemd_supervisor import SystemdUserSupervisor

NATIVE_SHA256 = "87bd160e053af86b5b409daabf71f8dc05bbc3a2a3a5f563f36011cdf706a999"
NATIVE_SIZE = 184_825_984
SCHEMA_SHA256 = "cf12e9739510a196c7f25eb938555cfb66d901957f66f840a12d4489ae440ac3"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


@pytest.mark.skipif(sys.platform != "linux", reason="OpenCode Systemd probe requires Linux")
def test_actual_11830_private_server_session_and_termination_without_model():
    if os.geteuid() == 0:
        pytest.skip("non-root user manager required")
    source = Path(os.environ.get("ACS_P1_OPENCODE_NATIVE_PATH", ""))
    if not source.is_file():
        pytest.skip("reviewed native OpenCode binary unavailable")
    assert source.stat().st_size == NATIVE_SIZE and _sha(source) == NATIVE_SHA256
    schema = Path(__file__).parents[3] / "runtime_tests/schema-1.18.30/opencode-openapi.json"
    assert _sha(schema) == SCHEMA_SHA256
    parent = Path(f"/run/user/{os.geteuid()}/acs-p1-opencode-nomodel")
    parent.mkdir(mode=0o700, exist_ok=True)
    assert parent.stat().st_uid == os.geteuid()
    assert stat.S_IMODE(parent.stat().st_mode) == 0o700
    run_id = "p1-opencode-" + uuid.uuid4().hex
    root = parent / run_id
    root.mkdir(mode=0o700)
    supervisor = None
    driver = None
    try:
        roots = {
            name: root / name
            for name in ("home", "config", "data", "state", "cache", "input", "tmp", "bin", "ledger")
        }
        for directory in roots.values():
            directory.mkdir(mode=0o700)
        executable = roots["bin"] / "opencode"
        shutil.copyfile(source, executable)
        executable.chmod(0o500)
        assert _sha(executable) == NATIVE_SHA256
        config_dir = roots["config"] / "opencode"
        config_dir.mkdir(mode=0o700)
        config = config_dir / "opencode.json"
        config.write_text(json.dumps({
            "permission": {"*": "deny", "task": "deny"},
            "default_agent": "p1-observer",
            "model": "fixture-provider/fixture-model",
            "agent": {"p1-observer": {
                "model": "fixture-provider/fixture-model",
                "permission": {"*": "deny", "task": "deny"},
            }},
            "plugin": [], "mcp": {},
        }), encoding="utf-8")
        config.chmod(0o600)
        identity = BindingIdentity(
            "fixture-node", "fixture-boot", "fixture-runtime", "fixture-execution", "local-slot", 1
        )
        launch = OpenCodeLaunchProfile(
            str(executable), NATIVE_SHA256, "1.18.30", str(schema), SCHEMA_SHA256,
            str(roots["input"]), str(roots["home"]), str(roots["config"]),
            str(roots["data"]), str(roots["state"]), str(roots["cache"]),
            str(roots["tmp"]), _sha(config), "p1-observer", "fixture-provider",
            "fixture-model", {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        )
        supervisor = SystemdUserSupervisor(
            tasks_max=64, memory_max=1_073_741_824, cpu_quota_percent=100,
            termination_timeout=10,
        )
        driver = OpenCodeNativeDriver(
            run_id + "-binding", launch, DriverJournal(roots["ledger"] / "driver.sqlite"),
            identity=identity,
            check_current=lambda _operation, observed: observed == identity
            or pytest.fail("Node binding changed"),
            supervisor=supervisor,
            http_timeout=10,
        )
        operation = AuthorizedOperation(
            run_id + "-spawn", run_id + "-command", run_id + "-message", "fixture-grant",
            datetime.now(UTC) + timedelta(seconds=90),
        )
        receipt = driver.spawn(operation)
        assert receipt["receipt_layer"] == "runtime_acknowledged"
        assert receipt["native_session_id"].startswith("ses_")
        with driver.journal._connect() as connection:
            assert connection.execute(
                "SELECT count(*) FROM driver_events WHERE kind='http_dispatch' "
                "AND body LIKE '%prompt_async%'"
            ).fetchone() == (0,)
        terminated = driver.terminate(AuthorizedOperation(
            run_id + "-stop", run_id + "-stop-command", run_id + "-stop-message", "fixture-grant",
            datetime.now(UTC) + timedelta(seconds=60),
        ))
        proof = terminated["supervisor_proof"]
        assert proof["verified"] is True and proof["remaining_pids"] == []
        driver.detach_transport()
    finally:
        if supervisor is not None:
            supervisor.close()
        resolved = root.resolve(strict=True)
        assert resolved.parent == parent.resolve(strict=True)
        shutil.rmtree(resolved)
