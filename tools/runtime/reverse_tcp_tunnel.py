"""One-use-at-a-time raw TCP reverse tunnel with owner-provided token auth."""
from __future__ import annotations

import argparse
import os
import socket
import threading
from pathlib import Path

from runtime.operator_files import read_operator_file


def token(path: Path) -> bytes:
    value = read_operator_file(path, maximum=128).strip()
    if len(value) != 64 or any(byte not in b"0123456789abcdef" for byte in value):
        raise ValueError("reverse tunnel token reference is invalid")
    return value


def pipe(left: socket.socket, right: socket.socket) -> None:
    def copy(source, target):
        try:
            while True:
                data = source.recv(65536)
                if not data:
                    break
                target.sendall(data)
        except OSError:
            pass
        finally:
            try:
                target.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    first = threading.Thread(target=copy, args=(left, right), daemon=True)
    second = threading.Thread(target=copy, args=(right, left), daemon=True)
    first.start(); second.start(); first.join(); second.join()


def listen(host: str, worker_port: int, client_port: int, token_path: Path) -> None:
    secret = token(token_path)
    workers: list[socket.socket] = []
    lock = threading.Condition()

    def accept_workers(server):
        while True:
            connection, _ = server.accept()
            try:
                received = b""
                while not received.endswith(b"\n") and len(received) <= 65:
                    received += connection.recv(66 - len(received))
                if received.rstrip(b"\n") != secret:
                    connection.close(); continue
                connection.sendall(b"READY\n")
                with lock:
                    workers.append(connection); lock.notify()
            except OSError:
                connection.close()

    with (
        socket.create_server((host, worker_port), reuse_port=False) as worker_server,
        socket.create_server((host, client_port), reuse_port=False) as client_server,
    ):
        threading.Thread(target=accept_workers, args=(worker_server,), daemon=True).start()
        while True:
            client, _ = client_server.accept()
            with lock:
                while not workers:
                    lock.wait()
                worker = workers.pop(0)
            try:
                worker.sendall(b"CONNECT\n")
                pipe(client, worker)
            finally:
                client.close(); worker.close()


def connect(relay_host: str, relay_port: int, local_host: str, local_port: int,
            token_path: Path) -> None:
    secret = token(token_path)
    while True:
        with socket.create_connection((relay_host, relay_port), timeout=10) as relay:
            relay.settimeout(None)
            relay.sendall(secret + b"\n")
            if relay.recv(6) != b"READY\n":
                raise RuntimeError("reverse tunnel relay authentication failed")
            command = b""
            while not command.endswith(b"\n"):
                command += relay.recv(16)
            if command != b"CONNECT\n":
                raise RuntimeError("reverse tunnel relay command differs")
            with socket.create_connection((local_host, local_port), timeout=10) as local:
                pipe(relay, local)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    server = sub.add_parser("listen")
    server.add_argument("--host", required=True); server.add_argument("--worker-port", type=int, required=True)
    server.add_argument("--client-port", type=int, required=True); server.add_argument("--token", type=Path, required=True)
    agent = sub.add_parser("connect")
    agent.add_argument("--relay-host", required=True); agent.add_argument("--relay-port", type=int, required=True)
    agent.add_argument("--local-host", required=True); agent.add_argument("--local-port", type=int, required=True)
    agent.add_argument("--token", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "listen":
        listen(args.host, args.worker_port, args.client_port, args.token)
    else:
        connect(args.relay_host, args.relay_port, args.local_host, args.local_port, args.token)


if __name__ == "__main__":
    main()
