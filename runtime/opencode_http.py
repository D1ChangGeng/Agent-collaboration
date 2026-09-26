"""Bounded OpenCode loopback HTTP transport: no proxy, redirect, or credential log."""
from __future__ import annotations

import base64
import ctypes
import http.client
import json
import os
import re
import socket
import struct
from pathlib import Path
from urllib.parse import urlencode


class HttpRejected(ValueError):
    pass


class HttpFailure(RuntimeError):
    def __init__(self, status, path):
        self.status, self.path = status, path
        super().__init__(f"OpenCode HTTP {status} at {path}")


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
        r"^/(?:global/health|doc|config|agent|event|experimental/tool/ids|session"
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
        if method not in ("GET", "POST") or not self.PATHS.fullmatch(path):
            raise HttpRejected("HTTP method/path is outside the native Driver allowlist")
        if method == "GET" and payload is not None:
            raise HttpRejected("GET request cannot carry a mutation body")
        if not self.verify_owner():
            raise HttpRejected("current endpoint/process ownership is unverified")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout or self.timeout)
        try:
            connection.connect()
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
            if on_dispatch is not None:
                on_dispatch()
            connection.request(method, target, body=encoded, headers=headers)
            response = connection.getresponse()
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise HttpRejected("native response exceeds Driver bound")
            if not 200 <= response.status < 300:
                raise HttpFailure(response.status, path)
            value = None if response.status == 204 or not body else json.loads(body)
            return response.status, value
        finally:
            connection.close()

    def events(self, stop, callback, *, before_send=None, opened=None):
        """Bounded SSE observation; events never establish an invocation ACK."""
        if stop.is_set():
            return
        if not self.verify_owner():
            raise HttpRejected("event endpoint ownership is unverified")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self.timeout)
        self._event_connection = connection
        try:
            connection.connect()
            self._event_socket = connection.sock
            if stop.is_set():
                return
            if not self.verify_owner():
                raise HttpRejected("event endpoint changed before authentication")
            if before_send is not None:
                before_send()
            if stop.is_set():
                return
            connection.request("GET", "/event?" + urlencode({"directory": self.directory}),
                               headers={"Authorization": self._authorization, "Accept": "text/event-stream"})
            response = connection.getresponse()
            if stop.is_set():
                return
            if response.status != 200 or "text/event-stream" not in response.getheader("Content-Type", ""):
                raise HttpFailure(response.status, "/event")
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
