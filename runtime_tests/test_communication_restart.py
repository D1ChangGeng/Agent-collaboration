"""Abrupt real MCP process loss; observations recover from durable messages."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

import psycopg
from mcp import ClientSession, StdioServerParameters
from mcp.client import stdio as stdio_module
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import MCPError

from runtime.communication_dispatch import maintain_communication_deliveries, prune_expired_waits
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import prepare_ordinary_agents
from runtime_tests.test_surfaces import profile

comm = comm_fixture
ROOT = Path(__file__).resolve().parents[1]


def test_abrupt_waiter_loss_and_new_mcp_sessions_keep_the_original_reply(comm, tmp_path, monkeypatch):
    prepare_ordinary_agents(comm, tmp_path)
    processes = []
    original_spawn = stdio_module._create_platform_compatible_process

    async def capture_spawn(**kwargs):
        process = await original_spawn(**kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(stdio_module, "_create_platform_compatible_process", capture_spawn)

    def parameters(name):
        client = comm.clients[name]
        path, env, _secret = profile(tmp_path, dsn=comm.dsn, context=client.service.context,
                                      extra={"delivery_maintenance": "external"})
        return StdioServerParameters(command=sys.executable, args=["-m", "runtime.project_entry", "--config", str(path),
            "--catalog", str(ROOT/"docs/runtime/p2-mcp-tool-contract.json"), "--profile", "engineer"], env=env, cwd=str(ROOT))

    async def exercise():
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
            async with (stdio_client(parameters("b"), errlog=errors) as b_streams,
                        ClientSession(*b_streams, read_timeout_seconds=20) as b):
                await b.initialize()
                async with (stdio_client(parameters("a"), errlog=errors) as a_streams,
                            ClientSession(*a_streams, read_timeout_seconds=20) as a):
                    await a.initialize()
                    process = processes[-1]  # The actual process handle issued by the SDK.
                    submitted = await a.call_tool("send_message", {"project_id":"project-alpha",
                        "to":"collaborator:project-alpha:slot-b", "content":"Keep this exchange across a process crash",
                        "activation":"message_only", "client_request_id":"restart-original"})
                    assert not submitted.is_error
                    sent = submitted.structured_content["data"]

                    async def observe():
                        try:
                            return await a.call_tool("wait_for_response", {"project_id":"project-alpha",
                                "handles":[sent["message_handle"]], "timeout_seconds":120})
                        except MCPError as error:
                            return type(error).__name__
                    waiting = asyncio.create_task(observe())
                    deadline = time.monotonic()+10
                    while True:
                        with psycopg.connect(comm.dsn) as connection:
                            lease = connection.execute("SELECT waiter_id FROM communication_waits WHERE request_id=%s "
                                "AND expires_at>clock_timestamp()", (sent["message_id"],)).fetchone()
                        if lease:
                            break
                        assert not waiting.done() and time.monotonic()<deadline
                        await asyncio.sleep(0.05)
                    process.kill()
                    exit_code = await process.wait()
                    assert exit_code is not None and process.returncode is not None
                    with psycopg.connect(comm.dsn) as connection:
                        assert connection.execute("SELECT 1 FROM communication_waits WHERE waiter_id=%s", lease).fetchone()
                    inbox = await b.call_tool("check_inbox", {"project_id":"project-alpha"})
                    assert sent["message_handle"] in [item["message_handle"] for item in inbox.structured_content["data"]["items"]]
                    original = await b.call_tool("read_message", {"project_id":"project-alpha", "handle":sent["message_handle"]})
                    reply_args = {"project_id":"project-alpha", "to":original.structured_content["data"]["from"],
                        "content":"Actual B reply after the sender process was killed", "reply_to":[sent["message_handle"]],
                        "activation":"invoke", "client_request_id":"restart-reply"}
                    replied = await b.call_tool("send_message", reply_args)
                    assert not replied.is_error
                    reply = replied.structured_content["data"]
                    assert reply["native_status"] == "active_wait_ingress"
                    assert isinstance(await waiting, str), "The killed result channel cannot deliver a successful Tool Result"

                async with (stdio_client(parameters("a"), errlog=errors) as resumed_streams,
                            ClientSession(*resumed_streams, read_timeout_seconds=20) as resumed):
                    await resumed.initialize()
                    inbox = await resumed.call_tool("check_inbox", {"project_id":"project-alpha"})
                    assert reply["message_handle"] in [item["message_handle"] for item in inbox.structured_content["data"]["items"]]
                    for _ in range(2):
                        result = await resumed.call_tool("wait_for_response", {"project_id":"project-alpha",
                            "handles":[sent["message_handle"]], "timeout_seconds":0})
                        assert result.structured_content["state"] == "satisfied"
                        assert result.structured_content["data"]["observations"][0]["reply"]["message_id"] == reply["message_id"]
                async with (stdio_client(parameters("b"), errlog=errors) as retry_streams,
                            ClientSession(*retry_streams, read_timeout_seconds=20) as retry):
                    await retry.initialize()
                    repeated = await retry.call_tool("send_message", reply_args)
                    assert not repeated.is_error and repeated.structured_content["data"]["duplicate"]
                    assert repeated.structured_content["data"]["message_id"] == reply["message_id"]
            return {"request":sent["message_handle"], "reply":reply["message_handle"], "killed_process_exit":exit_code,
                    "orphan_waiter":lease[0], "mcp_processes":len(processes), "model_requested":False}

    facts = asyncio.run(exercise())
    # Let the actual five-second crash lease expire; the default maintainer
    # must reclaim it without deleting history or issuing Native.
    async def reclaim():
        task = asyncio.create_task(maintain_communication_deliveries(comm.clients["a"].service.service))
        try:
            deadline = time.monotonic()+8
            while True:
                with psycopg.connect(comm.dsn) as connection:
                    if not connection.execute("SELECT 1 FROM communication_waits WHERE waiter_id=%s", (facts["orphan_waiter"],)).fetchone():
                        break
                assert time.monotonic()<deadline, "default maintenance did not reclaim the expired crash lease"
                await asyncio.sleep(0.1)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    asyncio.run(reclaim())
    with psycopg.connect(comm.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone()[0] == 1
        receipt = connection.execute("SELECT evidence_json FROM delivery_receipts WHERE message_id=%s "
            "AND layer='target_inbox_committed'", (facts["reply"].split(":",2)[2],)).fetchone()[0]
        assert receipt["ingress"] == "active_wait" and receipt["model_consumption"] == "unconfirmed"
    assert not any(driver.calls for driver in comm.drivers.values())
    assert all(process.returncode is not None for process in processes)
    (tmp_path/"restart-facts.json").write_text(json.dumps(facts,indent=2),encoding="utf-8")


def test_wait_cleanup_is_bounded_and_preserves_live_leases_and_messages(comm):
    from runtime_tests.test_communication import send
    sent = send(comm, activation="message_only")["data"]
    with psycopg.connect(comm.dsn) as connection:
        for index in range(5):
            connection.execute("INSERT INTO communication_waits VALUES (%s,'project-alpha',%s,%s,%s,clock_timestamp()-interval '1 second')",
                (comm.authority.tenant_id,"expired-"+str(index),sent["from"],sent["message_id"]))
        connection.execute("INSERT INTO communication_waits VALUES (%s,'project-alpha','alive',%s,%s,clock_timestamp()+interval '1 minute')",
            (comm.authority.tenant_id,sent["from"],sent["message_id"]))
    assert prune_expired_waits(comm.authority,limit=2) == 2
    with psycopg.connect(comm.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM communication_waits").fetchone()[0] == 4
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone()[0] == 1
        assert connection.execute("SELECT 1 FROM communication_waits WHERE waiter_id='alive'").fetchone()
