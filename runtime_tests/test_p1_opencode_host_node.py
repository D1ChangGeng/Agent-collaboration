"""Fixed OpenCode host socket schema and peer boundary, without PostgreSQL."""

from __future__ import annotations

import json
import os
import socket
import threading
from pathlib import Path

import pytest

from runtime.p1_codex_host_node import CodexHostResult
from runtime.p1_opencode_host_node import OpenCodeHostRequest, OpenCodeHostUnixServer


def _request() -> OpenCodeHostRequest:
    return OpenCodeHostRequest(
        action="readback",
        run_id="p1-opencode-fixture-run",
        tenant_id="tenant",
        message_id="message",
        command_id="command",
        operation_id="operation",
        endpoint_id="endpoint",
        source_commit="a" * 40,
        native_sha256="b" * 64,
        config_sha256="c" * 64,
    )


def test_only_fixed_dispatch_and_readback_schema_is_admitted():
    value = _request().model_dump()
    assert OpenCodeHostRequest.model_validate(value, strict=True) == _request()
    for changed in (
        {**value, "action": "shell"},
        {**value, "schema_version": "acs-p1-codex-host-request/1"},
        {**value, "argv": ["/bin/sh"]},
        {**value, "source_commit": "wrong"},
    ):
        with pytest.raises(ValueError):
            OpenCodeHostRequest.model_validate(changed, strict=True)


@pytest.mark.skipif(os.name != "posix", reason="Unix peer credentials required")
def test_host_socket_rejects_general_command_and_returns_same_identity(tmp_path: Path):
    parent = tmp_path / "owner"
    parent.mkdir(mode=0o700)
    parent.chmod(0o700)
    request = _request()

    class Endpoint:
        calls = 0

        def handle(self, observed):
            self.calls += 1
            assert observed.schema_version == "acs-p1-codex-host-request/1"
            assert observed.action == "readback"
            return CodexHostResult(
                run_id=observed.run_id,
                tenant_id=observed.tenant_id,
                message_id=observed.message_id,
                command_id=observed.command_id,
                operation_id=observed.operation_id,
                status="delivered",
            )

    endpoint = Endpoint()
    server = OpenCodeHostUnixServer(endpoint, parent / "host.sock")

    def roundtrip(payload: dict) -> dict:
        thread = threading.Thread(target=server.serve_one)
        thread.start()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(5)
            client.connect(str(server.socket_path))
            client.sendall(json.dumps(payload).encode() + b"\n")
            response = json.loads(client.recv(8192))
        thread.join(timeout=5)
        assert not thread.is_alive()
        return response

    try:
        rejected = roundtrip({**request.model_dump(mode="json"), "action": "shell"})
        assert rejected == {"schema_version": "acs-p1-opencode-host-error/1", "state": "rejected"}
        assert endpoint.calls == 0
        result = roundtrip(request.model_dump(mode="json"))
        assert result["schema_version"] == "acs-p1-opencode-host-result/1"
        assert result["status"] == "delivered"
        assert (result["run_id"], result["command_id"], result["message_id"]) == (
            request.run_id, request.command_id, request.message_id,
        )
        assert endpoint.calls == 1
    finally:
        server.close()
        assert not server.socket_path.exists()
