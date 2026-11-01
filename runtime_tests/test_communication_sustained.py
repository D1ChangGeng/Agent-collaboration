"""Opt-in sustained real MCP/PostgreSQL traffic; peers are scripted, not models."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
import uuid

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from runtime_tests.test_communication import ROOT, prepare_ordinary_agents
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_surfaces import profile

comm = comm_fixture


@pytest.mark.skipif(os.getenv("ACS_SUSTAINED_TEST") != "1", reason="sustained isolated PostgreSQL/MCP load is opt-in")
def test_sustained_real_mcp_with_reconnect_and_independent_readback(comm, tmp_path):
    seconds = int(os.getenv("ACS_SUSTAINED_SECONDS", "600"))
    workers = int(os.getenv("ACS_SUSTAINED_WORKERS", "4"))
    assert 20 <= seconds <= 1800 and 1 <= workers <= 8
    prepare_ordinary_agents(comm, tmp_path)
    records, latencies, phases, failures = [], [], [], []
    retries = 0
    denied = 0
    independently_verified = False
    source_files = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                    for folder in (ROOT / "runtime", ROOT / "runtime_deployment")
                    for path in folder.glob("*") if path.suffix in {".py", ".sql"}}

    def unchanged_source():
        return source_files == {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                for folder in (ROOT / "runtime", ROOT / "runtime_deployment")
                                for path in folder.glob("*") if path.suffix in {".py", ".sql"}}

    def parameters(name):
        client = comm.clients[name]
        config, environment, _ = profile(tmp_path, dsn=comm.dsn, context=client.service.context,
                                          extra={"delivery_maintenance": "external"})
        prefix = ["-m", "runtime.project_entry"]
        if os.getenv("ACS_LOAD_DIAGNOSTICS") == "1":
            diagnostic = tmp_path / f"load_diagnostic_{name}.py"
            diagnostic.write_text("import sys,traceback,faulthandler\nsys.path.insert(0," + repr(str(ROOT)) + ")\n"
                "from runtime.mcp_runtime import McpRuntime\noriginal=McpRuntime._problem\n"
                "def observed(*a,**kw):\n if sys.exception() is not None: traceback.print_exc(file=sys.stderr)\n return original(*a,**kw)\n"
                "McpRuntime._problem=staticmethod(observed)\ncall=McpRuntime.call\nimport time,os\n"
                "faulthandler.dump_traceback_later(15,repeat=True,file=sys.stderr)\n"
                "def traced(self,*a,**kw):\n print('CALL_BEGIN',os.getpid(),time.monotonic(),a[0],kw.get('request_id'),file=sys.stderr,flush=True)\n"
                " try: return call(self,*a,**kw)\n finally: print('CALL_END',os.getpid(),time.monotonic(),a[0],kw.get('request_id'),file=sys.stderr,flush=True)\n"
                "McpRuntime.call=traced\nfrom runtime.project_entry import main\nraise SystemExit(main())\n")
            prefix = [str(diagnostic)]
        return StdioServerParameters(command=sys.executable, args=[*prefix, "--config", str(config),
            "--catalog", str(ROOT / "docs/runtime/p2-mcp-tool-contract.json"), "--profile", "engineer"],
            env=environment, cwd=str(ROOT))

    async def invoke(session, tool, **args):
        if os.getenv("ACS_LOAD_DIAGNOSTICS") == "1":
            with (tmp_path / "client-trace.private.jsonl").open("a") as trace:
                trace.write(json.dumps({"time": time.monotonic(), "event": "begin", "tool": tool,
                                       "request_key": args.get("client_request_id")}) + "\n")
        result = await session.call_tool(tool, {"project_id": "project-alpha", **args})
        if os.getenv("ACS_LOAD_DIAGNOSTICS") == "1":
            with (tmp_path / "client-trace.private.jsonl").open("a") as trace:
                trace.write(json.dumps({"time": time.monotonic(), "event": "end", "tool": tool,
                                       "request_key": args.get("client_request_id")}) + "\n")
        assert not result.is_error and result.structured_content["ok"], result.structured_content
        return result.structured_content

    async def phase(index, duration):
        nonlocal retries, denied
        assert unchanged_source(), "Runtime bytes changed between load phases"
        with (tmp_path / f"stdio-phase-{index}.stderr.txt").open("w+", encoding="utf-8") as errors:
            async with (stdio_client(parameters("a"), errlog=errors) as sa,
                        ClientSession(*sa, read_timeout_seconds=30) as a,
                        stdio_client(parameters("b"), errlog=errors) as sb,
                        ClientSession(*sb, read_timeout_seconds=30) as b,
                        stdio_client(parameters("c"), errlog=errors) as sc,
                        ClientSession(*sc, read_timeout_seconds=30) as c):
                await a.initialize(); await b.initialize(); await c.initialize()
                if records:
                    # New actual server processes recover the old identity and reply.
                    previous = records[0]
                    value = await invoke(a, "send_message", **previous["arguments"])
                    assert value["data"]["message_handle"] == previous["request"]
                    observed = await invoke(a, "wait_for_response", handles=[previous["request"]], timeout_seconds=0)
                    assert observed["state"] == "satisfied"
                    retries += 1
                start = time.monotonic()
                end = start + duration
                async def worker(number):
                    nonlocal retries, denied
                    sequence = 0
                    while time.monotonic() < end:
                        sequence += 1
                        identity = f"{index}-{number}-{sequence}"
                        # Repeated body with distinct request IDs must remain distinct.
                        content = "same body 中文🙂" if sequence % 7 == 0 else f"load {identity} 中文🙂 " + "x" * (2048 if sequence % 11 == 0 else 16)
                        arguments = {"to": "collaborator:project-alpha:slot-b", "content": content,
                                     "activation": "message_only", "client_request_id": uuid.uuid4().hex}
                        record = {"arguments": arguments, "content_sha256": hashlib.sha256(content.encode()).hexdigest()}
                        records.append(record)  # Expected identity is recorded before sending.
                        started = time.monotonic()
                        try:
                            sent = (await invoke(a, "send_message", **arguments))["data"]
                            handle = sent["message_handle"]
                            record.update(request=handle, message_id=sent["message_id"])
                            if sequence % 10 == 0:
                                duplicate = (await invoke(a, "send_message", **arguments))["data"]
                                assert duplicate["message_handle"] == handle
                                retries += 1
                            original = (await invoke(b, "read_message", handle=handle))["data"]
                            assert original["content"] == content
                            reply = (await invoke(b, "send_message", to=original["from"], content="reply:" + identity,
                                reply_to=[handle], activation="message_only", client_request_id="reply-" + arguments["client_request_id"]))["data"]
                            record.update(reply=reply["message_handle"], reply_id=reply["message_id"])
                            observed = await invoke(a, "wait_for_response", handles=[handle], timeout_seconds=0)
                            assert observed["state"] == "satisfied"
                            assert observed["data"]["observations"][0]["reply"]["message_handle"] == record["reply"]
                            if sequence % 25 == 0:
                                forbidden = await c.call_tool("read_message", {"project_id": "project-alpha", "handle": handle})
                                assert forbidden.structured_content["ok"] is False
                                denied += 1
                            latencies.append(time.monotonic() - started)
                        except Exception as error:
                            failures.append({"identity": identity, "error": type(error).__name__})
                            raise
                        # Four bounded workers, at most four new exchanges per second.
                        await asyncio.sleep(max(0, 1 - (time.monotonic() - started)))
                await asyncio.gather(*(worker(n) for n in range(workers)))
                phases.append({"phase": index, "active_seconds": time.monotonic() - start,
                               "completed_exchanges": len(latencies)})

    started = time.monotonic()
    try:
        asyncio.run(phase(0, seconds / 2))
        asyncio.run(phase(1, seconds / 2))
        assert unchanged_source(), "Runtime bytes changed during sustained qualification"
        # Independent authority readback must match the external expected manifest.
        with comm.authority._connect() as connection:
            rows = connection.execute("SELECT m.message_id,d.packet_json->>'content' "
                "FROM communication_messages m JOIN delivery_messages d USING(tenant_id,message_id)").fetchall()
            replies = connection.execute("SELECT count(*) FROM communication_replies").fetchone()[0]
            assert connection.execute("SELECT to_regclass('work_items')").fetchone()[0] is None
        expected = {r[k] for r in records for k in ("message_id", "reply_id")}
        assert {row[0] for row in rows} == expected
        assert len(rows) == 2 * len(records) and replies == len(records)
        assert len({r["request"] for r in records}) == len(records)
        by_id = dict(rows)
        for record in records:
            assert hashlib.sha256(by_id[record["message_id"]].encode()).hexdigest() == record["content_sha256"]
        independently_verified = True
    finally:
        ordered = sorted(latencies)
        def percentile(p):
            return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * p))] if ordered else None
        facts = {"evidence_class": "scripted ordinary peers over real stdio MCP and PostgreSQL", "model_load": False,
                 "runtime_files_sha256": source_files, "source_unchanged": unchanged_source(),
                 "configured_active_seconds": seconds, "wall_seconds": time.monotonic() - started,
                 "workers": workers, "phases": phases, "exchanges": len(latencies), "request_retries": retries,
                 "third_party_denials": denied, "failures": failures,
                 "round_trip_seconds": {"p50": percentile(.5), "p95": percentile(.95), "p99": percentile(.99)},
                 "independent_readback_passed": independently_verified}
        (tmp_path / "sustained.json").write_text(json.dumps(facts, indent=2))
        (tmp_path / "expected-private.json").write_text(json.dumps(records))
