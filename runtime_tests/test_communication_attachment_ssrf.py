"""T052: real attachment requests reject fetch URLs before any network effect."""
from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx

from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_attachment_live_http import BASE, bearer, live
from runtime_tests.test_communication_client_attachments import attached as attached_fixture
from runtime_tests.test_communication_client_attachments import (
    client,
    declare,
    ready,
)

comm = comm_fixture
attached = attached_fixture


def test_t052_attachment_url_fields_never_fetch_and_guessed_private_ids_are_not_readable(attached, monkeypatch):
    requests = []

    class Trap(BaseHTTPRequestHandler):
        def parse_request(self):
            parsed = super().parse_request()
            if parsed:
                requests.append((self.command, self.path))
            return parsed

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OWNED_LOOPBACK_SSRF_TRAP")

        def log_message(self, *_args):
            pass

    trap = ThreadingHTTPServer(("127.0.0.1", 0), Trap)
    thread = Thread(target=trap.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    destination = "http://127.0.0.1:" + str(trap.server_port) + "/owned-private-resource"
    assert httpx.get(destination, trust_env=False, timeout=5).content == b"OWNED_LOOPBACK_SSRF_TRAP"
    assert requests == [("GET", "/owned-private-resource")]
    requests.clear()

    async def exercise():
        async with live(attached, monkeypatch) as (_app, http):
            private_body = b"PRIVATE_CAS_B_NOT_SHARED_WITH_A"
            private = ready(client(attached, "b"), private_body, key="t052-private")
            with attached.authority._connect() as connection:
                baseline = {name: connection.execute("SELECT count(*) FROM " + name).fetchone()[0]
                            for name in ("communication_attachments", "communication_messages", "communication_replies", "outbox")}
            for field in ("url", "source_url", "upload_path", "local_path"):
                denied = await http.post(BASE, headers=bearer() | {"Idempotency-Key": "t052-" + field},
                    json=declare(b"An upload declaration cannot request a fetch") | {field: destination})
                assert denied.status_code == 400, denied.text
                assert denied.json()["error"]["code"] == "invalid_argument"
            for reference in (private["attachment_id"], "attachment-" + "0" * 32):
                for suffix in ("", "/content"):
                    denied = await http.get(BASE + "/" + reference + suffix, headers=bearer())
                    assert denied.status_code == 404, denied.text
                    assert private_body not in denied.content
            with attached.authority._connect() as connection:
                actual = {name: connection.execute("SELECT count(*) FROM " + name).fetchone()[0]
                          for name in baseline}
            assert actual == baseline
            assert requests == []
            assert not any(driver.calls for driver in attached.drivers.values())

    try:
        asyncio.run(exercise())
    finally:
        trap.shutdown()
        trap.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()
