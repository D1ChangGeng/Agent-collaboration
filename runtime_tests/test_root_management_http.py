"""Owner Client Root setup and scope narrowing over actual Streamable HTTP.

Token introspection is a named fixture; this does not qualify public TLS ingress.
"""
import asyncio

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from runtime.project_http import ProjectHttpSettings
from runtime_tests.test_communication import CATALOG
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_project_http import IssuerFixture, claims, listener, settings

comm = comm_fixture


def test_owner_http_client_root_entry_and_oauth_discovery_match_call_permissions(comm, monkeypatch):
    comm.authority.access_mode = "owner"
    config = settings(monkeypatch, comm.authority.context).model_dump(mode="json")
    config["bindings"][0]["trusted_client"] = True
    reader_scopes = {"acs:connect", *CATALOG["tools"]["read_profile"]["security_scopes"],
                     *CATALOG["tools"]["list_projects"]["security_scopes"]}
    issuer = IssuerFixture({"client-token": claims(), "reader-token": claims(scope=" ".join(sorted(reader_scopes)))})

    async def exercise(url):
        async with (httpx.AsyncClient(headers={"Authorization": "Bearer client-token"}, trust_env=False) as http,
                    streamable_http_client(url + "/mcp", http_client=http) as streams,
                    ClientSession(*streams, read_timeout_seconds=30) as client):
            await client.initialize()
            profile = (await client.call_tool("read_profile", {})).structured_content
            assert profile["data"]["actor"]["organization"]["level"] == "client"
            arguments = {"project_id": "http-root", "client_request_id": "http-root-setup",
                         "changes": {"name": "HTTP Root"}}
            configured = (await client.call_tool("configure_root", arguments)).structured_content
            assert configured["ok"], configured
            replay = (await client.call_tool("configure_root", arguments)).structured_content
            assert replay["data"] == configured["data"]
            http.headers["Authorization"] = "Bearer reader-token"
            tools = {tool.name for tool in (await client.list_tools()).tools}
            assert "read_profile" in tools and "configure_root" not in tools and "send_message" not in tools
            narrowed = (await client.call_tool("read_profile", {})).structured_content
            assert "configure_root" not in {action["tool"] for action in narrowed["data"]["actor"]["next_actions"]}
            denied = (await client.call_tool("configure_root", arguments)).structured_content
            assert not denied["ok"] and denied["data"]["code"] == "authorization_denied"
            assert "guidance" not in denied["data"]

    with listener(comm.clients["a"].service.service, ProjectHttpSettings.model_validate(config), issuer) as (url, _server):
        asyncio.run(exercise(url))
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM collaboration_projects WHERE project_id='http-root'").fetchone() == (1,)


def test_bound_http_role_context_does_not_recommend_oauth_forbidden_tools(comm, monkeypatch):
    comm.authority.access_mode = "owner"
    config = settings(monkeypatch, comm.authority.context).model_dump(mode="json")
    config["bindings"][0]["agent_slot_id"] = "local-slot"
    scopes = {"acs:connect", *CATALOG["tools"]["read_profile"]["security_scopes"],
              *CATALOG["tools"]["list_projects"]["security_scopes"]}
    issuer = IssuerFixture({"reader-token": claims(scope=" ".join(sorted(scopes)))})

    async def exercise(url):
        async with (httpx.AsyncClient(headers={"Authorization": "Bearer reader-token"}, trust_env=False) as http,
                    streamable_http_client(url + "/mcp", http_client=http) as streams,
                    ClientSession(*streams, read_timeout_seconds=30) as client):
            await client.initialize()
            tools = {tool.name for tool in (await client.list_tools()).tools}
            profile = (await client.call_tool("read_profile", {})).structured_content
            assert profile["ok"], profile
            for binding in profile["data"]["actor"]["bindings"]:
                for key, query in binding.items():
                    if key.endswith("_query"):
                        assert query["tool"] in tools
            assert all(action["tool"] in tools for action in profile["data"]["actor"]["next_actions"])

    with listener(comm.clients["a"].service.service, ProjectHttpSettings.model_validate(config), issuer) as (url, _server):
        asyncio.run(exercise(url))
