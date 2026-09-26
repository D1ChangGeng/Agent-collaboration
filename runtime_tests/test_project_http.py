"""OAuth fixtures + actual Streamable HTTP/SDK and PostgreSQL integration.

These tests do not establish public TLS ingress, user consent, or live Harness
workflow support. The Authorization Server's introspection is a named fixture.
"""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import psycopg
import pytest
import uvicorn
from mcp import Client, ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import ValidationError

from runtime.models import AuthenticatedContext
from runtime.project_http import (
    IntrospectionVerifier,
    ProjectHttpSettings,
    TokenAuthorization,
    create_http_app,
)
from runtime_tests.test_project_continuation import complete_response
from runtime_tests.test_project_service import CATALOG, ok, send_args, work_args
from runtime_tests.test_project_service import project as project_fixture


@pytest.fixture
def project(setup):
    return project_fixture.__wrapped__(setup)


def settings(monkeypatch, context=None):
    monkeypatch.setenv("ACS_TEST_INTROSPECTION_SECRET", "fixture-introspection-secret")
    return ProjectHttpSettings.model_validate({
        "issuer_url": "https://issuer.example.test", "resource_url": "https://acs.example.test/mcp",
        "introspection_url": "https://issuer.example.test/introspect",
        "introspection_client_id": "acs-resource",
        "introspection_secret_ref": {"kind": "environment", "name": "ACS_TEST_INTROSPECTION_SECRET"},
        "bindings": [
            {"subject": "alice", "client_id": "web-client", "profile": "root_manager",
             "principal_ref": context.principal_ref if context else "principal:alice",
             "grant_ref": context.grant_ref if context else "grant:alice"},
            {"subject": "bob", "client_id": "web-client", "profile": "root_manager",
             "principal_ref": "principal:bob", "grant_ref": "grant:bob"}],
        "allowed_origins": ["https://web.example.test"], "authorization_refresh_seconds": 1})


def claims(**changes):
    scopes = {scope for tool in CATALOG["tools"].values() for scope in tool["security_scopes"]}
    return {"active": True, "iss": "https://issuer.example.test", "aud": "https://acs.example.test/mcp",
            "sub": "alice", "client_id": "web-client", "exp": int(time.time()) + 120,
            "scope": " ".join(sorted(scopes | {"acs:connect"})), **changes}


class IssuerFixture:
    def __init__(self, tokens):
        self.tokens = tokens
        self.calls = []

    def handle(self, request):
        assert str(request.url) == "https://issuer.example.test/introspect"
        assert request.headers["authorization"].startswith("Basic ")
        token = parse_qs(request.content.decode())["token"][0]
        self.calls.append(token)
        value = self.tokens.get(token, {"active": False})
        if isinstance(value, int):
            return httpx.Response(value, headers={"location": "https://untrusted.example.test/"})
        return httpx.Response(200, json=value)

    def client(self):
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle), trust_env=False)


@pytest.mark.parametrize("change", [
    {"active": False}, {"active": "true"}, {"aud": "https://other.example.test/mcp"},
    {"iss": "https://other-issuer.example.test"}, {"exp": 0}, {"exp": True},
    {"exp": None}, {"nbf": 99999999999}, {"iat": 99999999999}, {"sub": "unadmitted"},
    {"client_id": "unadmitted"}, {"scope": "project.read"}, {"scope": ["acs:connect"]},
    {"token_type": "ID"}, {"aud": None}, {"sub": {"invalid": "subject"}},
])
def test_introspection_rejects_invalid_claims(monkeypatch, change):
    config = settings(monkeypatch)
    async def exercise():
        async with IssuerFixture({"bad": claims(**change)}).client() as client:
            assert await IntrospectionVerifier(config, client).verify_token("bad") is None
    asyncio.run(exercise())


def test_introspection_does_not_follow_redirect_and_rechecks_revocation(monkeypatch):
    config = settings(monkeypatch)
    issuer = IssuerFixture({"valid": claims(aud=["another-resource", config.resource_url]), "redirect": 307})
    async def exercise():
        async with issuer.client() as client:
            verifier = IntrospectionVerifier(config, client)
            assert await verifier.verify_token("redirect") is None
            access = await verifier.verify_token("valid")
            assert access.subject == "alice" and access.resource == config.resource_url
            authorization = TokenAuthorization(access, "fixture-context", verifier)
            assert authorization.authenticate("valid") == "fixture-context"
            with pytest.raises(PermissionError):
                authorization.authenticate("different")
            issuer.tokens["valid"] = {"active": False}
            authorization.checked_at -= 2
            with pytest.raises(PermissionError):
                await authorization.refresh()
            with pytest.raises(PermissionError):
                authorization.credential()
    asyncio.run(exercise())
    assert issuer.calls == ["redirect", "valid", "valid"]


@pytest.mark.parametrize("loss", ["expiry", "observation_age", "identity_changed"])
def test_authorization_snapshot_cannot_outlive_token_or_change_identity(monkeypatch, loss):
    config = settings(monkeypatch)
    issuer = IssuerFixture({"valid": claims()})
    async def exercise():
        async with issuer.client() as client:
            verifier = IntrospectionVerifier(config, client)
            access = await verifier.verify_token("valid")
            authorization = TokenAuthorization(access, "alice-context", verifier)
            if loss == "expiry":
                access.expires_at = int(time.time()) - 1
            elif loss == "observation_age":
                authorization.checked_at -= 2
            else:
                issuer.tokens["valid"]["sub"] = "bob"
                authorization.checked_at -= 2
                with pytest.raises(PermissionError):
                    await authorization.refresh()
            with pytest.raises(PermissionError):
                authorization.authenticate("valid")
    asyncio.run(exercise())


@pytest.mark.parametrize("field,value", [
    ("issuer_url", "http://issuer.example.test"),
    ("introspection_url", "https://user:secret@issuer.example.test/"),
    ("resource_url", "https://acs.example.test/mcp?token=secret"),
    ("resource_url", "https://acs.example.test/other"),
    ("allowed_origins", ["https://*.example.test"]),
    ("allowed_origins", ["https://web.example.test/path"]),
])
def test_http_configuration_rejects_ambiguous_or_insecure_urls(monkeypatch, field, value):
    data = settings(monkeypatch).model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        ProjectHttpSettings.model_validate(data)


@contextmanager
def listener(service, config, issuer):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]
        app = create_http_app(service, CATALOG, config, port=port, client=issuer.client())
        server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False,
                                             proxy_headers=False, lifespan="on"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            yield f"http://127.0.0.1:{port}", server
        finally:
            server.should_exit = True
            thread.join(timeout=8)
            assert not thread.is_alive(), "owned HTTP fixture did not stop"


def test_http_metadata_challenge_and_origin_controls(monkeypatch):
    config = settings(monkeypatch)
    context = AuthenticatedContext("tenant", "authority", "incarnation", "principal", "grant")
    service = SimpleNamespace(authority=SimpleNamespace(context=context))
    issuer = IssuerFixture({"valid": claims()})
    with listener(service, config, issuer) as (url, _server), httpx.Client(trust_env=False) as client:
        response = client.post(url + "/mcp", json={})
        assert response.status_code == 401
        assert 'resource_metadata="https://acs.example.test/.well-known/oauth-protected-resource/mcp"' in response.headers["www-authenticate"]
        metadata = client.get(url + "/.well-known/oauth-protected-resource/mcp").json()
        assert metadata["resource"] == config.resource_url
        assert metadata["authorization_servers"] == [config.issuer_url]
        assert "fixture-introspection-secret" not in json.dumps(metadata)
        denied = client.post(url + "/mcp", headers={"Authorization": "Bearer valid", "Origin": "https://evil.test"}, json={})
        assert denied.status_code == 403
        bad_host = client.post(url + "/mcp", headers={"Authorization": "Bearer valid", "Host": "evil.test"}, json={})
        assert bad_host.status_code == 421
        cors = client.options(url + "/mcp", headers={"Origin": "https://web.example.test",
            "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,mcp-session-id"})
        assert cors.status_code == 200 and cors.headers["access-control-allow-origin"] == "https://web.example.test"


def test_http_sdk_filters_scopes_isolates_identity_and_rechecks_grant(project, monkeypatch):
    f = project
    config = settings(monkeypatch, f.authority.context)
    read_scopes = {"acs:connect", *CATALOG["tools"]["list_projects"]["security_scopes"],
                   *CATALOG["tools"]["load_project"]["security_scopes"]}
    issuer = IssuerFixture({"alice-token": claims(), "reader-token": claims(scope=" ".join(read_scopes)),
                            "bob-token": claims(sub="bob")})
    async def exercise(url):
        session_ids = []
        async def observe_response(response):
            if "mcp-session-id" in response.headers:
                session_ids.append(response.headers["mcp-session-id"])
        async with (httpx.AsyncClient(headers={"Authorization": "Bearer alice-token"}, trust_env=False,
                    event_hooks={"response": [observe_response]}) as http,
                    streamable_http_client(url + "/mcp", http_client=http) as streams,
                    ClientSession(*streams, read_timeout_seconds=10) as client):
            await client.initialize()
            tools = await client.list_tools()
            assert "create_work" in {t.name for t in tools.tools}
            result = await client.call_tool("list_projects", {})
            assert result.structured_content["data"]["items"][0]["project_id"] == "project-alpha"
            http.headers["Authorization"] = "Bearer reader-token"
            tools = await client.list_tools()
            assert "create_work" not in {t.name for t in tools.tools}
            denied = await client.call_tool("create_work", work_args())
            assert denied.is_error and denied.structured_content["data"]["code"] == "authorization_denied"
            # The exact same MCP Session cannot be borrowed by another OAuth subject.
            assert session_ids
            borrowed = await http.post(url + "/mcp", headers={"Authorization": "Bearer bob-token",
                "Mcp-Session-Id": session_ids[0], "MCP-Protocol-Version": "2025-11-25",
                "Accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": "borrowed", "method": "tools/list", "params": {}})
            assert borrowed.status_code == 404
            http.headers["Authorization"] = "Bearer alice-token"
            with psycopg.connect(f.dsn) as connection:
                connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref='grant:p1'")
            result = await client.call_tool("list_projects", {})
            assert result.structured_content["data"]["items"] == []
            denied = await client.call_tool("load_project", {"project_id": "project-alpha"})
            assert denied.is_error
    with listener(f.projects.service, config, issuer) as (url, _server):
        asyncio.run(exercise(url))


@pytest.mark.parametrize("loss", ["token_revoked", "token_expired", "grant_revoked"])
def test_http_subscription_stops_after_auth_loss_and_reconnect_recovers(project, monkeypatch, loss):
    f = project
    ok(f, "create_work", work_args())
    sent = ok(f, "send_message", send_args())["data"]
    config = settings(monkeypatch, f.authority.context)
    issuer = IssuerFixture({"alice-token": claims(), "replacement-token": claims()})
    uri = "acs://projects/project-alpha/inbox"
    async def exercise(url):
        messages = []
        wake = asyncio.Event()
        async def receive(message):
            if getattr(message, "method", None) == "notifications/resources/updated":
                messages.append(str(message.params.uri))
                wake.set()
        async with (httpx.AsyncClient(headers={"Authorization": "Bearer alice-token"}, trust_env=False) as http,
                    streamable_http_client(url + "/mcp", http_client=http) as streams,
                    ClientSession(*streams, message_handler=receive, read_timeout_seconds=10) as client):
            await client.initialize()
            await client.subscribe_resource(uri)
            if loss == "grant_revoked":
                with psycopg.connect(f.dsn) as connection:
                    connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref='grant:p1'")
            elif loss == "token_expired":
                issuer.tokens["alice-token"]["exp"] = int(time.time()) - 1
            else:
                issuer.tokens["alice-token"]["active"] = False
            await asyncio.sleep(1.5)
            await asyncio.to_thread(complete_response, f, sent["message_id"])
            await asyncio.sleep(1)
            assert messages == []
            # Renew OAuth authorization and the existing Domain grant explicitly.
            if loss == "grant_revoked":
                with psycopg.connect(f.dsn) as connection:
                    connection.execute("UPDATE grants SET revoked_at=NULL WHERE grant_ref='grant:p1'")
        async with (httpx.AsyncClient(headers={"Authorization": "Bearer replacement-token"}, trust_env=False) as http,
                    streamable_http_client(url + "/mcp", http_client=http) as streams,
                    ClientSession(*streams, message_handler=receive, read_timeout_seconds=10) as client):
            await client.initialize()
            await client.subscribe_resource(uri)
            await asyncio.wait_for(wake.wait(), timeout=5)
            result = await client.read_resource(uri)
            assert json.loads(result.contents[0].text)["items"][0]["response_handle"] == sent["response_handle"]
            assert messages == [uri]
    with listener(f.projects.service, config, issuer) as (url, _server):
        asyncio.run(exercise(url))


def test_modern_http_listen_delivers_live_notification(project, monkeypatch):
    f = project
    ok(f, "create_work", work_args())
    sent = ok(f, "send_message", send_args())["data"]
    config = settings(monkeypatch, f.authority.context)
    issuer = IssuerFixture({"alice-token": claims()})
    uri = "acs://projects/project-alpha/inbox"
    async def exercise(url):
        async with (httpx.AsyncClient(headers={"Authorization": "Bearer alice-token"}, trust_env=False) as http,
                    Client(streamable_http_client(url + "/mcp", http_client=http), mode="2026-07-28",
                           read_timeout_seconds=10, cache=None) as client,
                    client.listen(resource_subscriptions=[uri]) as subscription):
            assert subscription.honored.resource_subscriptions == [uri]
            await asyncio.to_thread(complete_response, f, sent["message_id"])
            event = await asyncio.wait_for(anext(subscription), timeout=5)
            assert event.uri == uri
            result = await client.read_resource(uri)
            assert json.loads(result.contents[0].text)["items"][0]["response_handle"] == sent["response_handle"]
    with listener(f.projects.service, config, issuer) as (url, _server):
        asyncio.run(exercise(url))
