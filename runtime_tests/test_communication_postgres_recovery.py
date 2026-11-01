"""Real TCP startup disconnects followed by ordinary stdio MCP communication."""
from __future__ import annotations

import asyncio
import json
import socket
import sys
import threading
from contextlib import contextmanager

import psycopg
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from runtime_tests.test_communication import ROOT, prepare_ordinary_agents
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_surfaces import profile

comm = comm_fixture


def test_lost_post_commit_observation_preserves_original_request(comm, monkeypatch):
    client = comm.clients["a"]
    original = client.service.execute
    arguments = {"project_id": "project-alpha", "to": "collaborator:project-alpha:slot-b",
                 "content": "committed before observation loss", "activation": "message_only",
                 "client_request_id": "post-commit-original"}
    def lose_observation(*args, **kwargs):
        original(*args, **kwargs)
        raise psycopg.OperationalError("connection lost " + client.credential_provider())
    monkeypatch.setattr(client.service, "execute", lose_observation)
    unknown = client.call("send_message", arguments)["structuredContent"]
    assert not unknown["ok"] and unknown["state"] == "unknown"
    assert unknown["metadata"]["evidence_class"] == "authority_unavailable"
    assert unknown["data"]["client_request_id"] == arguments["client_request_id"]
    assert unknown["data"]["recovery"] == "retry_with_same_client_request_id"
    assert client.credential_provider() not in json.dumps(unknown)
    monkeypatch.setattr(client.service, "execute", original)
    recovered = client.call("send_message", arguments)["structuredContent"]
    assert recovered["ok"]
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone() == (1,)


@contextmanager
def startup_disconnects(dsn):
    values = conninfo_to_dict(dsn)
    assert values["host"] == "127.0.0.1" and values["dbname"] == "acs_communication_test"
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.2)
    state = {"remaining": 0, "dropped": 0, "accepted": 0}
    stopped, lock, sockets, workers = threading.Event(), threading.Lock(), set(), []

    def copy(source, destination):
        try:
            while data := source.recv(65536):
                destination.sendall(data)
        except OSError:
            pass
        finally:
            for stream in (source, destination):
                try: stream.shutdown(socket.SHUT_RDWR)
                except OSError: pass

    def serve():
        while not stopped.is_set():
            try: client, _ = listener.accept()
            except TimeoutError: continue
            except OSError: break
            with lock:
                state["accepted"] += 1
                reject = state["remaining"] > 0
                if reject:
                    state["remaining"] -= 1
                    state["dropped"] += 1
            if reject:
                client.close()  # No upstream connection or application query.
                continue
            upstream = socket.create_connection((values["host"], int(values["port"])), timeout=5)
            upstream.settimeout(None)
            sockets.update((client, upstream))
            for source, destination in ((client, upstream), (upstream, client)):
                thread = threading.Thread(target=copy, args=(source, destination), daemon=True)
                thread.start(); workers.append(thread)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield make_conninfo(dsn, port=listener.getsockname()[1]), state
    finally:
        stopped.set(); listener.close(); thread.join(timeout=2)
        for stream in sockets: stream.close()
        for worker in workers: worker.join(timeout=2)


def test_startup_disconnect_recovers_without_replaying_messages(comm, tmp_path):
    prepare_ordinary_agents(comm, tmp_path)
    with startup_disconnects(comm.dsn) as (dsn, proxy):
        def parameters(name):
            config, env, _ = profile(tmp_path, dsn=dsn, context=comm.clients[name].service.context,
                                     extra={"delivery_maintenance": "external"})
            return StdioServerParameters(command=sys.executable, args=["-m", "runtime.project_entry",
                "--config", str(config), "--catalog", str(ROOT / "docs/runtime/p2-mcp-tool-contract.json"),
                "--profile", "engineer"], env=env, cwd=str(ROOT))

        async def exercise():
            with (tmp_path / "stdio.stderr.txt").open("w") as stderr:
                async with (stdio_client(parameters("a"), errlog=stderr) as sa, ClientSession(*sa, read_timeout_seconds=30) as a,
                            stdio_client(parameters("b"), errlog=stderr) as sb, ClientSession(*sb, read_timeout_seconds=30) as b):
                    await a.initialize(); await b.initialize()
                    async def call(client, tool, **args):
                        result = await client.call_tool(tool, {**({} if tool == "read_profile" else {"project_id": "project-alpha"}), **args})
                        assert not result.is_error, result.structured_content
                        return result.structured_content
                    await call(a, "read_profile"); await call(b, "read_profile")
                    await asyncio.sleep(0.6)  # Both long-lived LISTEN connections are established.
                    proxy["remaining"] = 2
                    arguments = {"to": "collaborator:project-alpha:slot-b", "content": "startup disconnect recovery 中文",
                                 "activation": "message_only", "client_request_id": "startup-recovery"}
                    sent = (await call(a, "send_message", **arguments))["data"]
                    duplicate = (await call(a, "send_message", **arguments))["data"]
                    assert duplicate["message_handle"] == sent["message_handle"]
                    message = (await call(b, "read_message", handle=sent["message_handle"]))["data"]
                    reply = (await call(b, "send_message", to=message["from"], content="recovered reply",
                        reply_to=[sent["message_handle"]], activation="message_only", client_request_id="recovery-reply"))["data"]
                    observed = await call(a, "wait_for_response", handles=[sent["message_handle"]], timeout_seconds=0)
                    assert observed["state"] == "satisfied"
                    assert observed["data"]["observations"][0]["reply"]["message_handle"] == reply["message_handle"]

        asyncio.run(exercise())
        assert proxy["dropped"] == 2 and proxy["remaining"] == 0
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone() == (1,)
        assert connection.execute("SELECT to_regclass('work_items')").fetchone() == (None,)
