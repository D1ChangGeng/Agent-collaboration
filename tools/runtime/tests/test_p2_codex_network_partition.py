import os
import socket
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from nacl.signing import SigningKey

from runtime.receiver_crypto import public_key
from tools.runtime.p2_codex_network_partition import RelayPartition
from tools.runtime.p2_control_proof import answer


def free_port():
    with socket.socket() as source:
        source.bind(("127.0.0.1", 0))
        return source.getsockname()[1]


@pytest.mark.skipif(os.name == "nt", reason="systemd user lifecycle probe")
def test_partition_stops_and_restores_supervised_relay(tmp_path, monkeypatch):
    token = tmp_path / "token"
    token.write_text("a" * 64); token.chmod(0o600)
    worker, client = free_port(), free_port()
    script = Path(__file__).parents[1] / "reverse_tcp_tunnel.py"
    key = SigningKey.generate()
    key_path = tmp_path / "control.seed"
    key_path.write_text(key.encode().hex()); key_path.chmod(0o600)
    args = SimpleNamespace(
        worker_port=worker, client_port=client, relay_pid_file=tmp_path / "relay.pid",
        partition_seconds=0.1, worker_reconnect_seconds=0.1,
        tunnel_script=script, token=token, relay_log=tmp_path / "relay.log",
        control_challenge=tmp_path / "control-challenge",
        control_proof=tmp_path / "control-proof", control_timeout_seconds=2,
        suffix="run", control_host="windows-local", control_session="ssh-control-1",
        control_public_key=public_key(key), control_authority_public_key=public_key(key),
        expected_tls_fingerprint="0" * 64,
    )
    partition = RelayPartition(args)
    invocation = SimpleNamespace(
        message_id="message", operation_id="operation",
        attempt_id="attempt", dispatch_id="dispatch",
    )
    signed = SimpleNamespace(admission=SimpleNamespace(), signature="0" * 128)
    monkeypatch.setattr("tools.runtime.p2_codex_network_partition.verify", lambda *values: None)
    monkeypatch.setattr("tools.runtime.p2_codex_network_partition.sha256", lambda value: "f" * 64)

    def control():
        while not args.control_challenge.exists():
            pass
        answer(
            args.control_challenge, key_path, args.control_proof,
            host=args.control_host, session=args.control_session,
        )

    threading.Thread(target=control, daemon=True).start()
    try:
        partition.start()
        partition(invocation, signed)
        assert [event["phase"] for event in partition.events] == [
            "initial", "before_partition", "partitioned",
        ]
        partition.restore(invocation)
        assert partition.events[-1]["phase"] == "restored"
        assert partition.events[-1]["logical_message_id"] == "message"
    finally:
        partition.supervisor.close()
