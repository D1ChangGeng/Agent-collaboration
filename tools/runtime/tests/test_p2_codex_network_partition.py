import os
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.runtime.p2_codex_network_partition import RelayPartition, _wait


def free_port():
    with socket.socket() as source:
        source.bind(("127.0.0.1", 0))
        return source.getsockname()[1]


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal lifecycle probe")
def test_partition_stops_and_restores_only_the_relay(tmp_path):
    token = tmp_path / "token"
    token.write_text("a" * 64)
    token.chmod(0o600)
    worker, client = free_port(), free_port()
    script = Path(__file__).parents[1] / "reverse_tcp_tunnel.py"
    log = tmp_path / "relay.log"
    process = subprocess.Popen([
        os.fspath(Path(os.sys.executable)), os.fspath(script), "listen",
        "--host", "127.0.0.1", "--worker-port", str(worker),
        "--client-port", str(client), "--token", os.fspath(token),
    ], stdout=log.open("ab"), stderr=subprocess.STDOUT)
    _wait(worker, True)
    _wait(client, True)
    pid = tmp_path / "relay.pid"
    pid.write_text(str(process.pid))
    args = SimpleNamespace(
        worker_port=worker, client_port=client, relay_pid_file=pid,
        partition_seconds=0.1, worker_reconnect_seconds=0.1,
        tunnel_script=script, token=token, relay_log=log,
    )
    partition = RelayPartition(args)
    invocation = SimpleNamespace(
        message_id="message", operation_id="operation",
        attempt_id="attempt", dispatch_id="dispatch",
    )
    try:
        partition(invocation)
        assert [event["phase"] for event in partition.events] == [
            "before_partition", "partitioned",
        ]
        partition.restore(invocation)
        assert [event["phase"] for event in partition.events] == [
            "before_partition", "partitioned", "restored",
        ]
        assert partition.events[-1]["logical_message_id"] == "message"
    finally:
        restored = int(pid.read_text())
        os.kill(restored, 15)
