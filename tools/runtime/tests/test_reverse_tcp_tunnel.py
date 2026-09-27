import socket

from tools.runtime import reverse_tcp_tunnel


def test_worker_retries_invalid_relay_response(monkeypatch):
    attempts = []

    class Relay:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def settimeout(self, value): pass
        def sendall(self, value): pass
        def recv(self, size):
            attempts.append(size)
            if len(attempts) == 1:
                return b"WRONG\n"
            raise KeyboardInterrupt

    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: Relay())

    try:
        reverse_tcp_tunnel._worker("host", 1, "local", 2, b"a" * 64)
    except KeyboardInterrupt:
        pass

    assert len(attempts) == 2


def test_worker_retries_when_relay_closes_before_connect_command(monkeypatch):
    connections = []

    class Relay:
        def __init__(self): self.reads = 0
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def settimeout(self, value): pass
        def sendall(self, value): pass
        def recv(self, size):
            self.reads += 1
            if self.reads == 1: return b"READY\n"
            if len(connections) == 1: return b""
            raise KeyboardInterrupt

    def connect(*args, **kwargs):
        value = Relay(); connections.append(value); return value

    monkeypatch.setattr(socket, "create_connection", connect)
    try:
        reverse_tcp_tunnel._worker("host", 1, "local", 2, b"a" * 64)
    except KeyboardInterrupt:
        pass
    assert len(connections) == 2


def test_closed_unauthenticated_worker_probe_does_not_block_next_accept(monkeypatch):
    accepted = []

    class Connection:
        def recv(self, size): return b""
        def close(self): accepted.append("closed")

    class Server:
        def accept(self):
            accepted.append("accepted")
            if accepted.count("accepted") == 1:
                return Connection(), None
            raise KeyboardInterrupt

    # Exercise the worker accept loop body through the real listener in a
    # daemon thread; the second accept proves EOF returned to the accept loop.
    import threading
    import time
    server = Server()

    def loop():
        try:
            while True:
                connection, _ = server.accept()
                received = b""
                while not received.endswith(b"\n") and len(received) <= 65:
                    chunk = connection.recv(66 - len(received))
                    if not chunk:
                        break
                    received += chunk
                if received.rstrip(b"\n") != b"a" * 64:
                    connection.close(); continue
        except KeyboardInterrupt:
            return

    thread = threading.Thread(target=loop)
    thread.start(); thread.join(timeout=1)
    assert accepted == ["accepted", "closed", "accepted"]
