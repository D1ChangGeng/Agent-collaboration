"""One fake OpenCode HTTP turn under actual Systemd ownership, no model."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from runtime.codex_driver import AuthorizedOperation, BindingIdentity, DriverJournal
from runtime.opencode_driver import OpenCodeLaunchProfile, OpenCodeNativeDriver
from runtime.systemd_supervisor import SystemdUserSupervisor


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.skipif(sys.platform != "linux", reason="Systemd ownership requires Linux")
def test_one_http_prompt_has_original_terminal_and_empty_cgroup():
    if os.geteuid() == 0:
        pytest.skip("non-root user manager required")
    parent = Path(f"/run/user/{os.geteuid()}/acs-p1-opencode-fixture")
    parent.mkdir(mode=0o700, exist_ok=True)
    parent.chmod(0o700)
    run_id = "p1-opencode-" + uuid.uuid4().hex
    root = parent / run_id
    root.mkdir(mode=0o700)
    supervisor = None
    try:
        roots = {
            name: root / name
            for name in ("home", "config", "data", "state", "cache", "input", "tmp", "bin", "ledger")
        }
        for directory in roots.values():
            directory.mkdir(mode=0o700)
        native = roots["bin"] / "opencode"
        fixture = (Path(__file__).parents[3] / "runtime_tests/p1_opencode_http_fixture.py").read_bytes()
        assert fixture.startswith(b'"""A no-model OpenCode-shaped HTTP process')
        native.write_bytes(b"#!" + sys.executable.encode() + b"\n" + fixture)
        native.chmod(0o500)
        config_dir = roots["config"] / "opencode"
        config_dir.mkdir(mode=0o700)
        config = config_dir / "opencode.json"
        config.write_text(json.dumps({
            "permission": {"*": "deny", "task": "deny"},
            "default_agent": "engineer", "model": "fixture-provider/fixture-model",
            "agent": {"engineer": {
                "model": "fixture-provider/fixture-model",
                "permission": {"*": "deny", "task": "deny"},
            }},
            "plugin": [], "mcp": {},
        }), encoding="utf-8")
        config.chmod(0o600)
        schema = Path(__file__).parents[3] / "runtime_tests/schema-1.18.30/opencode-openapi.json"
        identity = BindingIdentity(
            "fixture-node", "fixture-boot", "fixture-runtime", "fixture-execution", "local-slot", 1
        )
        profile = OpenCodeLaunchProfile(
            str(native), _sha(native), "1.18.30", str(schema), _sha(schema),
            str(roots["input"]), str(roots["home"]), str(roots["config"]),
            str(roots["data"]), str(roots["state"]), str(roots["cache"]),
            str(roots["tmp"]), _sha(config), "engineer", "fixture-provider",
            "fixture-model", {
                "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
                "PYTHONPATH": str(Path(__file__).parents[3]),
                "ACS_P1_FIXTURE_SCHEMA": str(schema),
            },
        )
        supervisor = SystemdUserSupervisor(
            tasks_max=64, memory_max=1_073_741_824, cpu_quota_percent=100,
            termination_timeout=10,
        )
        driver = OpenCodeNativeDriver(
            run_id + "-binding", profile, DriverJournal(roots["ledger"] / "driver.sqlite"),
            identity=identity,
            check_current=lambda _operation, observed: observed == identity
            or pytest.fail("Node binding changed"),
            supervisor=supervisor,
        )

        def operation(stage: str) -> AuthorizedOperation:
            return AuthorizedOperation(
                run_id + "-" + stage, run_id + "-command-" + stage,
                run_id + "-message-" + stage, "fixture-grant",
                datetime.now(UTC) + timedelta(seconds=90),
            )

        started = driver.spawn(operation("spawn"))
        assert started["receipt_layer"] == "runtime_acknowledged"
        invoked = driver.invoke(operation("invoke"), "Reply with one fixture sentinel")
        assert invoked["receipt_layer"] == "runtime_acknowledged"
        terminal = driver.collect_result(operation("collect"), run_id + "-invoke")
        assert terminal["receipt_layer"] == "response_received"
        assert terminal["native_terminal_outcome"] == "completed"
        assert terminal["assistant_text"] == ["synthetic final answer"]
        with driver.journal._connect() as connection:
            count = connection.execute(
                "SELECT count(*) FROM driver_events WHERE kind='http_dispatch' "
                "AND body LIKE '%prompt_async%'"
            ).fetchone()[0]
        assert count == 1
        stopped = driver.terminate(operation("stop"))["supervisor_proof"]
        assert stopped["verified"] is True and stopped["remaining_pids"] == []
        driver.detach_transport()
    finally:
        if supervisor is not None:
            supervisor.close()
        resolved = root.resolve(strict=True)
        assert resolved.parent == parent.resolve(strict=True)
        shutil.rmtree(resolved)
