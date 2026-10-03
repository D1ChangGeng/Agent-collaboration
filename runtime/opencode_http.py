"""Bounded OpenCode loopback HTTP transport: no proxy, redirect, or credential log."""
from __future__ import annotations

import base64
import ctypes
import http.client
import io
import json
import math
import os
import re
import socket
import struct
import time
from functools import partial
from pathlib import Path
from urllib.parse import urlencode


class HttpRejected(ValueError):
    pass


class HttpPreCallTimeout(HttpRejected):
    """The local request budget elapsed before dispatch was admitted."""


class HttpFailure(RuntimeError):
    def __init__(self, status, path):
        self.status, self.path = status, path
        super().__init__(f"OpenCode HTTP {status} at {path}")


def _remaining(deadline, *, dispatched=False):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        if dispatched:
            raise TimeoutError("HTTP local deadline elapsed after dispatch")
        raise HttpPreCallTimeout("HTTP local deadline elapsed before dispatch")
    return remaining


def _duration(timeout):
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout < 0):
        raise HttpRejected("HTTP timeout must be a finite nonnegative duration")
    return timeout


class _DeadlineReader(io.RawIOBase):
    """Refresh a socket's remaining budget before every underlying receive."""

    def __init__(self, raw, sock, deadline):
        self.raw, self.sock, self.deadline = raw, sock, deadline

    def readable(self):
        return True

    def readinto(self, buffer):
        if self.deadline is not None:
            self.sock.settimeout(_remaining(self.deadline, dispatched=True))
        count = self.raw.readinto(buffer)
        if self.deadline is not None:
            _remaining(self.deadline, dispatched=True)
        return count

    def close(self):
        if not self.closed:
            try:
                self.raw.close()
            finally:
                super().close()


class _DeadlineResponse(http.client.HTTPResponse):
    def __init__(self, sock, *args, deadline, **kwargs):
        super().__init__(sock, *args, **kwargs)
        self.fp = io.BufferedReader(_DeadlineReader(self.fp.detach(), sock, deadline))

    def opened_stream(self):
        if self.fp is not None:
            self.fp.raw.deadline = None


def _socket_budget(connection, deadline, *, dispatched=False, sock=None):
    remaining = _remaining(deadline, dispatched=dispatched)
    connection.timeout = remaining
    active_socket = connection.sock if sock is None else sock
    if active_socket is not None:
        active_socket.settimeout(remaining)
    return remaining


def listener_owner_pids(port):
    """Observe the actual local TCP listener; inability to inspect is an error."""
    if os.name == "nt":
        api = ctypes.WinDLL("iphlpapi", use_last_error=True)
        function = api.GetExtendedTcpTable
        function.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_bool,
                             ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
        function.restype = ctypes.c_uint32
        size = ctypes.c_uint32()
        result = function(None, ctypes.byref(size), False, socket.AF_INET, 3, 0)
        if result not in (0, 122):
            raise HttpRejected("cannot inspect TCP listener ownership")
        buffer = ctypes.create_string_buffer(size.value)
        if function(buffer, ctypes.byref(size), False, socket.AF_INET, 3, 0):
            raise HttpRejected("TCP listener ownership changed during inspection")
        count = struct.unpack_from("<I", buffer.raw)[0]
        owners = set()
        for index in range(count):
            state, address, local_port, _, _, pid = struct.unpack_from("<6I", buffer.raw, 4 + index * 24)
            if state == 2 and socket.ntohs(local_port & 0xFFFF) == port:
                if socket.inet_ntoa(struct.pack("<I", address)) != "127.0.0.1":
                    raise HttpRejected("OpenCode listener is not restricted to IPv4 loopback")
                owners.add(pid)
        return owners
    if os.name == "posix":
        inodes = set()
        for line in Path("/proc/net/tcp").read_text().splitlines()[1:]:
            fields = line.split()
            address, encoded_port = fields[1].split(":")
            if fields[3] == "0A" and int(encoded_port, 16) == port:
                if address != "0100007F":
                    raise HttpRejected("OpenCode listener is not restricted to IPv4 loopback")
                inodes.add(fields[9])
        owners = set()
        for process in Path("/proc").iterdir():
            if not process.name.isdecimal():
                continue
            try:
                for descriptor in (process / "fd").iterdir():
                    try:
                        target = os.readlink(descriptor)
                    except (FileNotFoundError, PermissionError):
                        continue
                    if target.startswith("socket:[") and target[8:-1] in inodes:
                        owners.add(int(process.name))
            except (FileNotFoundError, PermissionError):
                continue
        return owners
    raise HttpRejected("listener ownership is unsupported on this OS")


class LoopbackHttp:
    PATHS = re.compile(
        r"^/(?:global/health|doc|config|agent|provider|event|experimental/tool/ids|session"
        r"(?:/status|/ses_[A-Za-z0-9_-]+(?:/abort|/prompt_async|/message(?:/msg_[A-Za-z0-9_-]+)?)?)?)$"
    )

    def __init__(self, port, password, directory, verify_owner, *, username="opencode", timeout=10):
        if type(port) is not int or not 1 <= port <= 65535 or not callable(verify_owner):
            raise HttpRejected("a fixed loopback port and current ownership verifier are required")
        if not isinstance(password, str) or len(password) < 24 or username != "opencode":
            raise HttpRejected("a private bounded-server credential is required")
        self.port, self.directory, self.verify_owner = port, str(directory), verify_owner
        self.timeout = timeout
        self._event_connection = None
        self._event_socket = None
        self._authorization = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()

    @property
    def endpoint(self):
        return f"http://127.0.0.1:{self.port}"

    def request(
        self,
        method,
        path,
        payload=None,
        *,
        timeout=None,
        max_bytes=4 * 1024 * 1024,
        before_send=None,
        on_dispatch=None,
    ):
        started = time.monotonic()
        deadline = started + _duration(self.timeout if timeout is None else timeout)
        if method not in ("GET", "POST") or not self.PATHS.fullmatch(path):
            raise HttpRejected("HTTP method/path is outside the native Driver allowlist")
        if path == "/provider" and method != "GET":
            raise HttpRejected("provider auth inspection is read-only")
        if method == "GET" and payload is not None:
            raise HttpRejected("GET request cannot carry a mutation body")
        if not self.verify_owner():
            raise HttpRejected("current endpoint/process ownership is unverified")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=_remaining(deadline))
        connection.response_class = partial(_DeadlineResponse, deadline=deadline)
        try:
            connection.connect()
            active_socket = connection.sock
            _socket_budget(connection, deadline)
            # Check again before disclosing the per-capacity credential.
            if not self.verify_owner():
                raise HttpRejected("endpoint ownership changed before request")
            if before_send is not None:
                before_send()
            encoded = None if payload is None else json.dumps(
                payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
            if encoded is not None and len(encoded) > 2 * 1024 * 1024:
                raise HttpRejected("request body exceeds Driver bound")
            headers = {"Authorization": self._authorization, "Accept": "application/json"}
            if encoded is not None:
                headers["Content-Type"] = "application/json"
            target = path + "?" + urlencode({"directory": self.directory})
            _socket_budget(connection, deadline)
            if on_dispatch is not None:
                on_dispatch()
            _socket_budget(connection, deadline, dispatched=True)
            connection.request(method, target, body=encoded, headers=headers)
            _socket_budget(connection, deadline, dispatched=True, sock=active_socket)
            response = connection.getresponse()
            _socket_budget(connection, deadline, dispatched=True, sock=active_socket)
            body = response.read(max_bytes + 1)
            _remaining(deadline, dispatched=True)
            if len(body) > max_bytes:
                raise HttpRejected("native response exceeds Driver bound")
            if not 200 <= response.status < 300:
                raise HttpFailure(response.status, path)
            value = None if response.status == 204 or not body else json.loads(body)
            _remaining(deadline, dispatched=True)
            return response.status, value
        finally:
            connection.close()

    def events(self, stop, callback, *, before_send=None, opened=None):
        """Bounded SSE observation; events never establish an invocation ACK."""
        deadline = time.monotonic() + _duration(self.timeout)
        if stop.is_set():
            return
        if not self.verify_owner():
            raise HttpRejected("event endpoint ownership is unverified")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=_remaining(deadline))
        connection.response_class = partial(_DeadlineResponse, deadline=deadline)
        self._event_connection = connection
        try:
            connection.connect()
            self._event_socket = connection.sock
            _socket_budget(connection, deadline)
            if stop.is_set():
                return
            if not self.verify_owner():
                raise HttpRejected("event endpoint changed before authentication")
            if before_send is not None:
                before_send()
            if stop.is_set():
                return
            _socket_budget(connection, deadline)
            connection.request("GET", "/event?" + urlencode({"directory": self.directory}),
                               headers={"Authorization": self._authorization, "Accept": "text/event-stream"})
            _socket_budget(connection, deadline, dispatched=True, sock=self._event_socket)
            response = connection.getresponse()
            _remaining(deadline, dispatched=True)
            if stop.is_set():
                return
            if response.status != 200 or "text/event-stream" not in response.getheader("Content-Type", ""):
                raise HttpFailure(response.status, "/event")
            if isinstance(response, _DeadlineResponse):
                response.opened_stream()
            if opened is not None:
                opened()
            if self._event_socket is not None:
                self._event_socket.settimeout(None)
            data = []
            size = 0
            while not stop.is_set():
                line = response.readline(1024 * 1024 + 1)
                if not line:
                    return
                size += len(line)
                if size > 1024 * 1024:
                    raise HttpRejected("native event exceeds configured bound")
                if line.strip() == b"":
                    if data:
                        callback(json.loads(b"\n".join(data)))
                    data, size = [], 0
                elif line.startswith(b"data:"):
                    data.append(line[5:].strip())
        finally:
            connection.close()
            if self._event_connection is connection:
                self._event_connection = None
                self._event_socket = None

    def stop_events(self):
        if self._event_socket is not None:
            try:
                self._event_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self._event_connection is not None:
            self._event_connection.close()
