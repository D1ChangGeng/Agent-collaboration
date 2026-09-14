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
