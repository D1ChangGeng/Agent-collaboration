"""Bounded bidirectional Codex App Server JSONL transport (no jsonrpc header).

Wire source: https://learn.chatgpt.com/docs/app-server#protocol
Every request is sent at most once. Timeout/disconnection is an uncertain
outcome, not permission to repeat an application operation.
"""

from __future__ import annotations

import hashlib
import json
import queue
import threading
import uuid
from concurrent.futures import Future, TimeoutError


class RpcDisconnected(ConnectionError):
    pass


class RpcTimeout(TimeoutError):
    pass


class RpcError(RuntimeError):
    def __init__(self, error):
        self.error = error
        super().__init__(f"App Server RPC error {error.get('code')}: {error.get('message')}")


class JsonRpcClient:
    """One reader demultiplexes responses, notifications, and server requests.

    Reader/writer are binary streams. A supplied server_request_handler may
    answer only independently authorized operations; default is explicit error.
    Transport close does not assert process or descendant termination.
    """

    def __init__(
        self,
        reader,
        writer,
        *,
        stderr=None,
        server_request_handler=None,
        max_line_bytes=8 * 1024 * 1024,
        max_events=512,
        max_pending=32,
        max_requests=65536,
    ):
        if type(max_requests) is not int or max_requests < 1:
            raise ValueError("max_requests must be a positive integer")
        self.reader, self.writer = reader, writer
        self.max_line_bytes, self.max_pending = max_line_bytes, max_pending
        self.max_requests = max_requests
        self._issued_ids = set()
        self.events = queue.Queue(maxsize=max_events)
        self._handler = server_request_handler
        self._pending = {}
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._closed = None
        self._server_slots = threading.BoundedSemaphore(4)
        self._stderr_hash = hashlib.sha256()
        self._stderr_bytes = 0
        self._reader_thread = threading.Thread(target=self._receive, daemon=True)
        self._reader_thread.start()
        if stderr is not None:
            threading.Thread(target=self._drain_stderr, args=(stderr,), daemon=True).start()

    @property
    def connected(self):
        with self._lock:
            return self._closed is None

    def _drain_stderr(self, stream):
        try:
            while chunk := stream.read(4096):
                with self._lock:
                    self._stderr_bytes += len(chunk)
                    self._stderr_hash.update(chunk)
        except OSError:
            pass

    def diagnostics(self):
        with self._lock:
            return {
                "connected": self._closed is None,
                "stderr_bytes": self._stderr_bytes,
                "stderr_sha256": self._stderr_hash.hexdigest(),
            }

    def _fail(self, reason):
        with self._lock:
            if self._closed is None:
                self._closed = reason
                pending, self._pending = self._pending, {}
                for future in pending.values():
                    future.set_exception(RpcDisconnected(reason))

    def _send(self, message):
        encoded = (
            json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
            + b"\n"
        )
        if len(encoded) > self.max_line_bytes:
            raise ValueError("outgoing JSONL frame exceeds configured bound")
        with self._write_lock:
            if not self.connected:
                raise RpcDisconnected("transport is disconnected")
            try:
                view = memoryview(encoded)
                while view:
                    count = self.writer.write(view)
                    if not isinstance(count, int) or count <= 0:
                        raise OSError("stream write made no progress")
                    view = view[count:]
                self.writer.flush()
            except (OSError, ValueError) as exc:
                self._fail("transport write failed")
                raise RpcDisconnected("transport write failed") from exc

    def request(self, method, params, *, timeout=30, request_id=None):
        request_id = request_id or uuid.uuid4().hex
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("request_id must be a nonempty string")
        future = Future()
        with self._lock:
            if self._closed is not None:
                raise RpcDisconnected(self._closed)
            if request_id in self._issued_ids or len(self._pending) >= self.max_pending:
                raise ValueError("duplicate request id or pending request limit")
            if len(self._issued_ids) >= self.max_requests:
                raise ValueError("connection request identity budget exhausted")
            self._issued_ids.add(request_id)
            self._pending[request_id] = future
        try:
            self._send({"id": request_id, "method": method, "params": params})
            try:
                return future.result(timeout)
            except TimeoutError as exc:
                raise RpcTimeout(f"RPC acknowledgement deadline elapsed: {method}") from exc
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

    def notify(self, method, params):
        self._send({"method": method, "params": params})

    def _event(self, event):
        try:
            self.events.put_nowait(event)
        except queue.Full as exc:
            raise RpcDisconnected("notification evidence queue overflow") from exc

    def _answer_server(self, message):
        try:
            if self._handler is None:
                response = {"error": {"code": -32601, "message": "No authorized client handler"}}
            else:
                result = self._handler(message)
                response = {"result": result}
            self._send({"id": message["id"], **response})
        except Exception:  # noqa: BLE001 - handler boundary fails pending requests closed.
            self._fail("server request handler failed")
        finally:
            self._server_slots.release()

    def _receive(self):
        try:
            while True:
                line = self.reader.readline(self.max_line_bytes + 1)
                if not line:
                    raise RpcDisconnected("EOF from App Server")
                if len(line) > self.max_line_bytes or not line.endswith(b"\n"):
                    raise RpcDisconnected("invalid or oversized JSONL frame")
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise RpcDisconnected("JSON-RPC message must be an object")
                if "method" in message:
                    if not isinstance(message["method"], str) or not isinstance(
                        message.get("params", {}), dict
                    ):
                        raise RpcDisconnected("malformed JSON-RPC method/params")
                    if "id" in message:
                        self._event({"kind": "server_request", "message": message})
                        if not self._server_slots.acquire(blocking=False):
                            self._send(
                                {
                                    "id": message["id"],
                                    "error": {
                                        "code": -32001,
                                        "message": "Client request capacity exhausted",
                                    },
                                }
                            )
                        else:
                            threading.Thread(
                                target=self._answer_server, args=(message,), daemon=True
                            ).start()
                    else:
                        self._event({"kind": "notification", "message": message})
                elif "id" in message and (("result" in message) != ("error" in message)):
                    if "error" in message and not isinstance(message["error"], dict):
                        raise RpcDisconnected("malformed JSON-RPC error")
                    with self._lock:
                        future = self._pending.pop(message["id"], None)
                        if future is not None:
                            if "error" in message:
                                future.set_exception(RpcError(message["error"]))
                            else:
                                future.set_result(message["result"])
                    if future is None:
                        self._event({"kind": "late_response", "message": message})
                else:
                    raise RpcDisconnected("unrecognized JSON-RPC envelope")
        except Exception as exc:  # noqa: BLE001 - reader boundary must wake every pending waiter.
            self._fail(f"App Server read failed: {type(exc).__name__}")

    def drain_events(self):
        result = []
        while True:
            try:
                result.append(self.events.get_nowait())
            except queue.Empty:
                return result

    def close(self):
        self._fail("transport explicitly detached")
        try:
            self.writer.close()
        except OSError:
            pass
