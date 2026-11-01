"""Four actual MCP connections exercise Root setup and scoped communication."""
import asyncio
import hashlib
import json
import os
import sys
from contextlib import AsyncExitStack
from dataclasses import asdict, replace
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from runtime_tests.test_communication import comm as comm_fixture

comm = comm_fixture
ROOT = Path(__file__).resolve().parents[1]


def test_client_root_route_and_collaborator_over_real_stdio(comm, tmp_path):
    async def exercise():
        with (tmp_path / "stdio.stderr.txt").open("w") as errors:
            async with AsyncExitStack() as stack:
                async def connection(label, context, profile, token):
                    config = tmp_path / (label + ".json")
                    config.write_text(json.dumps({"access_mode": "owner", "context": asdict(context),
                        "dsn_ref": {"kind": "environment", "name": "ACS_ROLE_DSN"},
                        "credential_ref": {"kind": "environment", "name": "ACS_ROLE_CREDENTIAL"},
                        "delivery_maintenance": "external"}))
                    config.chmod(0o600)
                    params = StdioServerParameters(command=sys.executable, args=["-m", "runtime.project_entry",
                        "--config", str(config), "--catalog", str(ROOT / "docs/runtime/p2-mcp-tool-contract.json"),
                        "--profile", profile], env=dict(os.environ, ACS_ROLE_DSN=comm.dsn, ACS_ROLE_CREDENTIAL=token), cwd=str(ROOT))
                    streams = await stack.enter_async_context(stdio_client(params, errlog=errors))
                    session = await stack.enter_async_context(ClientSession(*streams, read_timeout_seconds=30))
                    await session.initialize()
                    return session

                async def call(session, tool, **args):
                    value = (await session.call_tool(tool, args)).structured_content
                    assert value["ok"], value
                    return value["data"]

                base = comm.authority.context
                client = await connection("client", replace(base, trusted_client=True, agent_slot_id=None),
                                          "root_manager", comm.clients["a"].credential_provider())
                first = await call(client, "read_profile")
                assert first["actor"]["organization"]["level"] == "client"
                configured = await call(client, "configure_root", project_id="wire-root", client_request_id="wire-root-setup",
                    changes={"name": "Wire Root"}, manager={"agent_slot_id": "wire-root-agent", "principal_ref": "agent:wire-root"})
                root_binding = configured["manager_configuration"]["caller_bindings"][0]

                async def bound_session(label, binding):
                    token = "isolated-stdio-" + label
                    context = replace(base, principal_ref=binding["principal_ref"], grant_ref=binding["grant_ref"],
                        agent_slot_id=binding["agent_slot_id"], trusted_client=False,
                        credential_hash=hashlib.sha256(token.encode()).hexdigest())
                    return await connection(label, context, binding["profile"], token)

                manager = await bound_session("root", root_binding)
                root_profile = await call(manager, "read_profile")
                assert root_profile["actor"]["organization"]["level"] == "root"
                pack = await call(manager, "load_project", project_id="wire-root")
                route = await call(manager, "create_route", project_id="wire-root", client_request_id="wire-route",
                    root_handle=pack["root_handle"], expected_root_revision=pack["project_revision"], route_id="wire-route",
                    display_name="Wire Route", goal="Scoped communication")
                route_member = await call(manager, "configure_team", project_id="wire-root", client_request_id="wire-manager",
                    scope_handle=route["scope_handle"], members=[{"agent_slot_id": "wire-route-agent", "principal_ref": "agent:wire-route", "role": "route"}])
                route_manager = await bound_session("route", route_member["caller_bindings"][0])
                route_profile = await call(route_manager, "read_profile")
                assert route_profile["actor"]["organization"]["level"] == "route"
                assert "create_route" not in {tool.name for tool in (await route_manager.list_tools()).tools}
                worker_member = await call(route_manager, "configure_team", project_id="wire-root", client_request_id="wire-worker",
                    scope_handle=route["scope_handle"], members=[{"agent_slot_id": "wire-worker", "principal_ref": "agent:wire-worker", "role": "engineer"}])
                worker = await bound_session("worker", worker_member["caller_bindings"][0])
                worker_profile = await call(worker, "read_profile")
                assert worker_profile["actor"]["organization"]["level"] == "agent"
                assert "configure_team" not in {tool.name for tool in (await worker.list_tools()).tools}

                for sender, receiver, target in [
                    (client, manager, "wire-root-agent"), (manager, route_manager, "wire-route-agent"),
                    (route_manager, worker, "wire-worker"),
                ]:
                    sent = await call(sender, "send_message", project_id="wire-root", to="collaborator:wire-root:" + target,
                        content="Read and acknowledge " + target, activation="message_only", client_request_id="request-" + target)
                    original = await call(receiver, "read_message", project_id="wire-root", handle=sent["message_handle"])
                    await call(receiver, "send_message", project_id="wire-root", to=original["from"],
                        content="Acknowledged " + target, reply_to=[original["message_handle"]], activation="message_only",
                        client_request_id="reply-" + target)
                    observed = await sender.call_tool("wait_for_response", {"project_id": "wire-root", "handles": [sent["message_handle"]], "timeout_seconds": 0})
                    assert observed.structured_content["state"] == "satisfied"
                    assert observed.structured_content["data"]["observations"][0]["reply"]["from"] == original["to"]
    asyncio.run(exercise())
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM communication_messages WHERE project_id='wire-root'").fetchone() == (6,)
        assert connection.execute("SELECT count(*) FROM communication_replies WHERE project_id='wire-root'").fetchone() == (3,)
        assert connection.execute("SELECT to_regclass('work_items')").fetchone() == (None,)
