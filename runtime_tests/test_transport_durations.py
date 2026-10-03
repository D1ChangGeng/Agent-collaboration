"""Local transport durations include queuing, authorization and response IO."""
from __future__ import annotations

import io
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import runtime.codex_jsonrpc as rpc
import runtime.opencode_http as http


class Monotonic:
    def __init__(self):
        self.value = 100.0

    def now(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class WriterLock:
    def __init__(self, clock, *, delay=0, acquire=True):
        self.clock, self.delay, self.acquired = clock, delay, acquire
        self.timeouts, self.releases = [], 0

    def acquire(self, *, timeout=None):
        self.timeouts.append(timeout)
        self.clock.advance(self.delay)
        return self.acquired

    def release(self):
        self.releases += 1


class Writer:
    def __init__(self, clock, delay=0):
        self.clock, self.delay = clock, delay
        self.frames, self.flushes = [], 0

    def write(self, value):
        self.frames.append(bytes(value))
        self.clock.advance(self.delay)
        return len(value)

    def flush(self):
        self.flushes += 1


@pytest.fixture
def rpc_client(monkeypatch):
    clock = Monotonic()
    monkeypatch.setattr(rpc, "time", SimpleNamespace(monotonic=clock.now))
    future = Mock()
    future.result.return_value = {"ack": True}
    monkeypatch.setattr(rpc, "Future", lambda: future)
    client = rpc.JsonRpcClient.__new__(rpc.JsonRpcClient)
    client._lock, client._write_lock = threading.RLock(), WriterLock(clock)
    client._closed, client._pending, client._issued_ids = None, {}, set()
    client.max_pending, client.max_requests, client.max_line_bytes = 4, 16, 4096
    client.events = queue.Queue()
    client.writer = Writer(clock)
    return client, clock, future


def test_rpc_wait_uses_budget_remaining_after_queue_and_authorization(rpc_client):
    client, clock, future = rpc_client
    client._write_lock.delay = 3
    dispatched = Mock()
    assert client.request("echo", {}, timeout=10,
        before_send=lambda: clock.advance(4), on_dispatch=dispatched) == {"ack": True}
    assert client._write_lock.timeouts == [10]
    future.result.assert_called_once_with(3)
    dispatched.assert_called_once_with()
    assert len(client.writer.frames) == 1 and client._pending == {}


@pytest.mark.parametrize("phase", ["queue", "authorization"])
def test_rpc_pre_call_expiry_never_dispatches_or_writes(rpc_client, phase):
    client, clock, future = rpc_client
    if phase == "queue":
        client._write_lock.delay = 11
    before_send = Mock(side_effect=lambda: clock.advance(11 if phase == "authorization" else 0))
    dispatched = Mock()
    with pytest.raises(rpc.RpcPreCallTimeout):
        client.request("turn/start", {}, timeout=10, request_id="budget-expired",
                       before_send=before_send, on_dispatch=dispatched)
    dispatched.assert_not_called()
    future.result.assert_not_called()
    assert client.writer.frames == [] and client._pending == {}
    assert client.connected and "budget-expired" in client._issued_ids
    assert client._write_lock.releases == 1


def test_rpc_writer_queue_timeout_is_a_pre_call_refusal(rpc_client):
    client, _clock, _future = rpc_client
    client._write_lock.acquired = False
    with pytest.raises(rpc.RpcPreCallTimeout, match="writer"):
        client.request("turn/start", {}, timeout=10)
    assert client.writer.frames == [] and client._write_lock.releases == 0


def test_rpc_expiry_after_dispatch_keeps_the_ambiguous_timeout_type(rpc_client):
    client, clock, future = rpc_client
    dispatched = Mock(side_effect=lambda: clock.advance(11))
    with pytest.raises(rpc.RpcTimeout):
        client.request("turn/start", {}, timeout=10, on_dispatch=dispatched)
    dispatched.assert_called_once_with()
    future.result.assert_not_called()
    assert client.writer.frames == []


def test_rpc_write_time_is_subtracted_from_acknowledgement_wait(rpc_client):
    client, _clock, future = rpc_client
    client.writer.delay = 7
    client.request("turn/start", {}, timeout=10)
    future.result.assert_called_once_with(3)


def test_rpc_completed_wait_cannot_extend_the_original_budget(rpc_client):
    client, clock, future = rpc_client
    future.result.side_effect = lambda _timeout: (clock.advance(11), {"ack": True})[1]
    with pytest.raises(rpc.RpcTimeout):
        client.request("turn/start", {}, timeout=10)


@pytest.mark.parametrize("invalid", [None, True, -1, float("nan"), float("inf")])
def test_rpc_rejects_invalid_local_durations_before_reserving_identity(rpc_client, invalid):
    client, _clock, _future = rpc_client
    with pytest.raises(ValueError, match="duration"):
        client.request("echo", {}, timeout=invalid)
    assert client._issued_ids == set() and client.writer.frames == []


class Socket:
    def __init__(self):
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)


class Response:
    status = 200

    def __init__(self, clock, delay=0):
        self.clock, self.delay, self.limits = clock, delay, []

    def read(self, limit):
        self.limits.append(limit)
        self.clock.advance(self.delay)
        return b'{"ack":true}'


@pytest.fixture
def http_client(monkeypatch):
    clock = Monotonic()
    monkeypatch.setattr(http, "time", SimpleNamespace(monotonic=clock.now))
    connections = []
    costs = {"owner": 0, "connect": 0, "request": 0, "headers": 0, "body": 0}

    class Connection:
        def __init__(self, _host, _port, timeout):
            self.initial_timeout, self.timeout = timeout, timeout
            self.sock, self.requests, self.closed = Socket(), [], False
            self.response = Response(clock, costs["body"])
            connections.append(self)

        def connect(self):
            clock.advance(costs["connect"])

        def request(self, *args, **kwargs):
            self.requests.append((args, kwargs))
            clock.advance(costs["request"])

        def getresponse(self):
            clock.advance(costs["headers"])
            return self.response

        def close(self):
            self.closed = True

    monkeypatch.setattr(http.http.client, "HTTPConnection", Connection)

    def owner():
        clock.advance(costs["owner"])
        return True

    return http.LoopbackHttp(43210, "fixture-password-" + "x" * 32, "/fixture", owner), clock, costs, connections


def test_http_connect_auth_send_and_read_share_one_budget(http_client):
    client, clock, costs, connections = http_client
    costs.update(owner=1, connect=1, request=1, headers=1, body=1)
    dispatched = Mock()
    assert client.request("POST", "/session", {}, timeout=10,
        before_send=lambda: clock.advance(2), on_dispatch=dispatched) == (200, {"ack": True})
    connection = connections[0]
    assert connection.initial_timeout == 9
    assert connection.sock.timeouts == [8, 5, 5, 4, 3]
    assert connection.response.limits == [4 * 1024 * 1024 + 1]
    assert connection.closed and len(connection.requests) == 1
    dispatched.assert_called_once_with()


@pytest.mark.parametrize("phase", ["owner", "connect", "authorization"])
def test_http_pre_call_expiry_never_sends_credentials_or_dispatches(http_client, phase):
    client, clock, costs, connections = http_client
    if phase in costs:
        costs[phase] = 11
    dispatched = Mock()
    with pytest.raises(http.HttpPreCallTimeout):
        client.request("POST", "/session", {}, timeout=10,
            before_send=lambda: clock.advance(11 if phase == "authorization" else 0), on_dispatch=dispatched)
    dispatched.assert_not_called()
    assert all(connection.requests == [] and connection.closed for connection in connections)


def test_http_expiry_after_dispatch_is_not_a_pre_call_refusal(http_client):
    client, clock, _costs, connections = http_client
    dispatched = Mock(side_effect=lambda: clock.advance(11))
    with pytest.raises(TimeoutError) as caught:
        client.request("POST", "/session", {}, timeout=10, on_dispatch=dispatched)
    assert not isinstance(caught.value, http.HttpPreCallTimeout)
    dispatched.assert_called_once_with()
    assert connections[0].requests == [] and connections[0].closed


@pytest.mark.parametrize("phase", ["request", "headers", "body"])
def test_http_each_io_phase_uses_the_original_deadline(http_client, phase):
    client, _clock, costs, connections = http_client
    costs[phase] = 11
    with pytest.raises(TimeoutError):
        client.request("POST", "/session", {}, timeout=10)
    assert len(connections[0].requests) == 1 and connections[0].closed


def test_http_zero_timeout_does_not_fall_back_to_the_default(http_client):
    client, _clock, _costs, connections = http_client
    with pytest.raises(http.HttpPreCallTimeout):
        client.request("GET", "/global/health", timeout=0)
    assert connections == []


def test_http_underlying_receives_refresh_remaining_time(monkeypatch):
    clock, sock = Monotonic(), Socket()
    monkeypatch.setattr(http, "time", SimpleNamespace(monotonic=clock.now))

    class Raw(io.RawIOBase):
        def readinto(self, buffer):
            clock.advance(2)
            buffer[:1] = b"x"
            return 1

    raw = Raw()
    reader = http._DeadlineReader(raw, sock, 110)
    try:
        for _ in range(4):
            assert reader.readinto(bytearray(1)) == 1
        with pytest.raises(TimeoutError):
            reader.readinto(bytearray(1))
        assert sock.timeouts == [10, 8, 6, 4, 2]
    finally:
        reader.close()
    assert raw.closed


def test_slow_real_http_headers_cannot_restart_each_receive_budget():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            try:
                self.wfile.write(b"HTTP/1.1 200 OK\r\n")
                self.wfile.flush()
                for _ in range(25):
                    time.sleep(0.03)
                    self.wfile.write(b"X-Fixture: slow\r\n")
                    self.wfile.flush()
                self.wfile.write(b"Content-Length: 2\r\n\r\n{}")
                self.wfile.flush()
            except OSError:
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = http.LoopbackHttp(server.server_port, "fixture-password-" + "x" * 32, "/fixture", lambda: True)
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            client.request("GET", "/global/health", timeout=0.08)
        assert time.monotonic() - started < 0.6
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_event_startup_counts_pre_send_authorization(http_client):
    client, clock, _costs, connections = http_client
    stop, opened = threading.Event(), Mock()
    with pytest.raises(http.HttpPreCallTimeout):
        client.events(stop, Mock(), before_send=lambda: clock.advance(11), opened=opened)
    opened.assert_not_called()
    assert connections[0].requests == [] and connections[0].closed


def test_opened_event_stream_releases_its_startup_budget():
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def do_GET(self):
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.flush()
                time.sleep(0.3)
                self.wfile.write(b'data: {"type":"late_fixture_event"}\n\n')
                self.wfile.flush()
            except OSError:
                pass
            self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = http.LoopbackHttp(server.server_port, "fixture-password-" + "x" * 32,
                               "/fixture", lambda: True, timeout=0.15)
    stop, observed, opened = threading.Event(), [], Mock()

    def observe(event):
        observed.append(event)
        stop.set()

    try:
        client.events(stop, observe, opened=opened)
        opened.assert_called_once_with()
        assert observed == [{"type": "late_fixture_event"}]
    finally:
        client.stop_events()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
