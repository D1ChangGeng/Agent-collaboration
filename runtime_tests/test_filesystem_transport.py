"""Real TLS file requests keep machine identity, replay and native independence."""
import os
import secrets
import threading
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from runtime.filesystem_transport import node_request
from runtime.machine_filesystem import FilesystemError
from runtime.receiver_crypto import sign
from runtime.remote_endpoint import ReceiverHTTPServer, fixture_authority_current

pytest_plugins = ("runtime_tests.test_receiver_protocol",)
pytestmark = pytest.mark.skipif(os.name != "posix", reason="TLS Receiver uses its POSIX backend")


class NativeProvider:
    def __init__(self):
        self.allowed = True
        self.calls = 0
        self.authority = SimpleNamespace(receiver_transport=SimpleNamespace(
            current_filesystem_authority=lambda request: self.allowed))

    def invoke(self, admission):
        self.calls += 1
        raise AssertionError("file operation started a native Agent")

    def health(self):
        return {"state": "busy", "harness": "fixture", "version": "fixture"}


def request(env, operation, arguments):
    registration = env.config.binding.registration
    value = {"schema_version": "acs-machine-files/1", "request_id": uuid.uuid4().hex,
        "nonce": secrets.token_hex(32), "principal_ref": "owner", "grant_ref": "owner-reference",
        **{name: getattr(registration, name) for name in ["tenant_id", "authority_id", "authority_incarnation",
            "endpoint_id", "endpoint_revision", "node_id", "machine_id", "boot_incarnation"]},
        "authority_key_id": env.config.authority_key_id, "authority_key_revision": env.config.authority_key_revision,
        "operation": operation, "arguments": arguments, "issued_at": datetime.now(UTC).isoformat()}
    return {"command": value, "signature": sign(env.authority_key, value)}


def test_real_tls_current_files_and_replay_while_native_busy(env, tmp_path):
    env.config = replace(env.config, access_mode="owner")
    provider = NativeProvider()
    server = ReceiverHTTPServer(env.config, env.node_key, fixture_authority_current, provider.invoke)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    adapter = SimpleNamespace(config=env.config, _signing_key=env.authority_key)
    caller = SimpleNamespace(principal_ref="owner", grant_ref="owner-reference")
    path = tmp_path/"outside/new/file.txt"
    try:
        write = request(env, "write_file", {"path": str(path), "content": "current bytes\n"})
        data = node_request(adapter, caller, "write_file", write["command"]["arguments"], request=write)
        assert data["machine_id"] == "machine"
        assert path.read_text() == "current bytes\n"
        path.write_text("external newer bytes\n")
        replay = node_request(adapter, caller, "write_file", write["command"]["arguments"], request=write)
        assert replay == data
        assert path.read_text() == "external newer bytes\n"
        read = node_request(adapter, caller, "read_file", {"path": str(path)})
        assert read["content"] == "external newer bytes\n"
        assert provider.calls == 0
        changed = {**write, "command": {**write["command"], "arguments": {"path": str(path), "content": "different"}}}
        changed["signature"] = sign(env.authority_key, changed["command"])
        with pytest.raises(FilesystemError):
            node_request(adapter, caller, "write_file", changed["command"]["arguments"], request=changed)
        provider.allowed = False
        with pytest.raises(FilesystemError):
            node_request(adapter, caller, "read_file", {"path": str(path)})
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        assert not worker.is_alive()


def test_configured_endpoint_does_not_repeat_a_write_after_lost_response(env, tmp_path, monkeypatch):
    import http.client
    from runtime.machine_connections import ConfiguredRemoteEndpoint
    env.config = replace(env.config, access_mode="owner")
    provider = NativeProvider()
    server = ReceiverHTTPServer(env.config, env.node_key, fixture_authority_current, provider.invoke)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    adapter = SimpleNamespace(config=env.config, _signing_key=env.authority_key)
    endpoint = ConfiguredRemoteEndpoint(SimpleNamespace(), SimpleNamespace())
    monkeypatch.setattr(endpoint, "_adapter", lambda: adapter)

    def prepare():
        raise AssertionError("potentially completed mutation must not be retried")

    monkeypatch.setattr(endpoint, "_prepare", prepare)
    path = tmp_path/"once.txt"
    original = http.client.HTTPSConnection.getresponse

    def lost(connection):
        response = original(connection)
        response.read()
        raise OSError("response lost after receiver completed write")

    monkeypatch.setattr(http.client.HTTPSConnection, "getresponse", lost)
    try:
        caller = SimpleNamespace(principal_ref="owner", grant_ref="owner-reference")
        with pytest.raises(FilesystemError, match="write_uncertain") as caught:
            endpoint.filesystem(caller, "write_file", {"path": str(path), "content": "written once"})
        assert caught.value.details["request_id"]
        assert path.read_text() == "written once"
        import sqlite3
        with sqlite3.connect(env.config.ledger_path) as ledger:
            assert ledger.execute("SELECT count(*) FROM filesystem_requests").fetchone()[0] == 1
        monkeypatch.setattr(http.client.HTTPSConnection, "getresponse", original)
        assert endpoint.filesystem(caller, "read_file", {"path": str(path)})["content"] == "written once"
        assert provider.calls == 0
    finally:
        server.shutdown()
        server.server_close()
        worker.join(5)
        assert not worker.is_alive()
