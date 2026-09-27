"""Read the stopped same-run Systemd proof through the guest's sole host socket."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from runtime.codex_driver import AuthorizedOperation
from runtime.p1_codex_host_node import CodexHostUnixServer
from runtime.systemd_supervisor import SystemdUserSupervisor
from runtime_tests.test_p1_codex_host_node import _host, _send, _systemd_fixture_driver

pytest_plugins = ("runtime_tests.test_delivery",)


def test_bwrap_guest_reads_only_original_stopped_host_unit(setup, tmp_path):
    if not sys.platform.startswith("linux") or os.geteuid() == 0:
        pytest.skip("reviewed non-root Linux bubblewrap and Systemd are required")
    helper = Path("/opt/acs/codex-sandbox/bin/bwrap")
    if not helper.is_file():
        pytest.skip("reviewed bubblewrap helper unavailable")
    host, _, _, private = _host(setup, tmp_path)
    request = _send(setup, host.policy)
    supervisor = SystemdUserSupervisor(
        tasks_max=16,
        memory_max=134_217_728,
        cpu_quota_percent=50,
        termination_timeout=5,
    )
    driver = _systemd_fixture_driver(supervisor, host.policy.run_id)
    setup.endpoint.driver = driver
    spawn = AuthorizedOperation(
        host.policy.run_id + "-spawn",
        host.policy.run_id + "-command-spawn",
        host.policy.run_id + "-message-spawn",
        setup.authority.context.grant_ref,
        host.policy.deadline,
    )
    server = None
    try:
        assert host.start_native(request, spawn)["verified"]
        assert host.handle(request).status == "delivered"
        stopped = host.stop_native()
        assert stopped["verified"] and stopped["remaining_pids"] == []
        socket_path = private / "os-readback.sock"
        server = CodexHostUnixServer(host, socket_path)
        errors = []

        def serve():
            try:
                server.serve_one()
            except Exception as error:  # noqa: BLE001 -- exact failure asserted below
                errors.append(type(error).__name__)

        thread = threading.Thread(target=serve)
        thread.start()
        guest_code = (
            "import json,os,sys;"
            "assert not os.path.exists('/run/user/%s/bus'%os.getuid());"
            "from tools.runtime.p1_codex_lifecycle import read_host_os_from_socket;"
            "from runtime.p1_codex_host_node import CodexHostRequest;"
            "x=json.load(sys.stdin);"
            "r=CodexHostRequest.model_validate(x['request']);"
            "p=read_host_os_from_socket(r,x['lineage']);"
            "print(json.dumps({'verified':p['verified'],'unit':p['unit'],"
            "'remaining_pids':p['remaining_pids']}))"
        )
        payload = {
            "request": request.model_copy(update={"action": "readback"}).model_dump(mode="json"),
            "lineage": {
                "run_id": request.run_id,
                "message_id": request.message_id,
                "command_id": request.command_id,
                "operation_id": request.operation_id,
                "os": stopped,
            },
        }
        source = Path(__file__).parents[3]
        venv = Path(sys.executable).parents[1]
        guest = subprocess.run(
            [
                str(helper),
                "--ro-bind",
                "/",
                "/",
                "--tmpfs",
                "/home",
                "--tmpfs",
                "/root",
                "--tmpfs",
                "/tmp",
                "--tmpfs",
                "/opt",
                "--tmpfs",
                "/run",
                "--dev",
                "/dev",
                "--proc",
                "/proc",
                "--unshare-user",
                "--unshare-pid",
                "--unshare-uts",
                "--unshare-ipc",
                "--share-net",
                "--die-with-parent",
                "--new-session",
                "--perms",
                "0700",
                "--dir",
                "/run/acs-p1",
                "--ro-bind",
                str(venv),
                "/run/acs-p1/runtime",
                "--ro-bind",
                str(source),
                "/mnt",
                "--ro-bind",
                str(socket_path),
                "/run/acs-p1/codex-host.sock",
                "--setenv",
                "PYTHONPATH",
                "/mnt",
                "--setenv",
                "PYTHONDONTWRITEBYTECODE",
                "1",
                "--",
                "/run/acs-p1/runtime/bin/python",
                "-c",
                guest_code,
            ],
            input=json.dumps(payload).encode(),
            capture_output=True,
            timeout=15,
            check=False,
        )
        thread.join(timeout=15)
        assert guest.returncode == 0, guest.stderr.decode()[-1000:]
        assert not thread.is_alive() and errors == []
        observed = json.loads(guest.stdout)
        assert observed == {"verified": True, "unit": stopped["unit"], "remaining_pids": []}
    finally:
        if server is not None:
            server.close()
        supervisor.close()
