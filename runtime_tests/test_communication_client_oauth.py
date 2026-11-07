"""Opt-in client REST on the actual OAuth/MCP app over isolated PostgreSQL.

The issuer's introspection is an explicit fixture. These are local ingress and
authority tests; they establish no public TLS, real consent, model or production
workflow qualification.
"""
from __future__ import annotations

import asyncio
import hashlib
import json

import httpx
import pytest

from runtime.client_contracts import ClientContracts
from runtime.communication_client_storage import verify_client_storage
from runtime.project_http import ProjectHttpSettings, create_http_app
from runtime.project_schema_state import ProjectSchemaAdoptionRequired, verify_project_schema
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_project_http import IssuerFixture, claims, settings
from runtime_tests.test_project_service import CATALOG

comm = comm_fixture
PREFIX = "/api/communication/v1"
PROJECT = "project-alpha"
PEER = "collaborator:project-alpha:slot-b"
CONTRACTS = ClientContracts()


def config(monkeypatch, comm, *, enabled=False):
    data = settings(monkeypatch, comm.authority.context).model_dump()
    # This operator-established binding is a real trusted Client, without a Slot.
    data["bindings"] = [{"subject": "alice", "client_id": "web-client", "profile": "root_manager",
        "principal_ref": comm.authority.context.principal_ref, "grant_ref": comm.authority.context.grant_ref,
        "trusted_client": True, "agent_slot_id": None}]
    data["communication_client_api"] = enabled
    return ProjectHttpSettings.model_validate(data)


def shared(comm):
    return comm.clients["a"].service.service


def app_for(comm, cfg, issuer_client):
    return create_http_app(shared(comm), CATALOG, cfg, client=issuer_client)


def explicit_initialize(comm):
    comm.clients["a"].service.initialize()
    assert verify_project_schema(comm.authority)
    with comm.authority._connect() as connection:
        verify_client_storage(connection)


def schema_snapshot(comm):
    with comm.authority._connect() as connection:
        return connection.execute("SELECT schema_name,schema_version,schema_checksum "
                                  "FROM runtime_schema_metadata ORDER BY schema_name").fetchall()


def rpc_json(response):
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert len(events) == 1
    return events[0]


def test_client_api_default_disabled_and_existing_mcp_challenge_remains(comm, monkeypatch):
    cfg = config(monkeypatch, comm)
    assert not cfg.communication_client_api
    before = schema_snapshot(comm)

    async def exercise():
        async with IssuerFixture({"valid": claims()}).client() as issuer_client:
            app = app_for(comm, cfg, issuer_client)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as http:
                assert (await http.get(PREFIX + "/meta")).status_code == 404
                assert (await http.get(PREFIX + "/profile", headers={"Authorization": "Bearer valid"})).status_code == 404
                challenge = await http.post("/mcp", json={})
                assert challenge.status_code == 401
                assert "oauth-protected-resource/mcp" in challenge.headers["www-authenticate"]

    asyncio.run(exercise())
    assert schema_snapshot(comm) == before
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT to_regclass('communication_client_read_state')").fetchone() == (None,)


def test_enabled_startup_requires_explicit_client_schema_adoption_and_does_not_auto_ddl(comm, monkeypatch):
    cfg = config(monkeypatch, comm, enabled=True)
    before = schema_snapshot(comm)

    async def exercise():
        async with IssuerFixture({"valid": claims()}).client() as issuer_client:
            app = app_for(comm, cfg, issuer_client)
            assert schema_snapshot(comm) == before
            with pytest.raises(ProjectSchemaAdoptionRequired):
                async with app.router.lifespan_context(app):
                    pytest.fail("unadopted client storage must fail startup")
            assert schema_snapshot(comm) == before
            explicit_initialize(comm)
            adopted = schema_snapshot(comm)
            async with (app.router.lifespan_context(app),
                httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as http):
                    assert (await http.get(PREFIX + "/meta")).status_code == 200
                    assert (await http.get(PREFIX + "/profile", headers={"Authorization": "Bearer valid"})).status_code == 200
            assert schema_snapshot(comm) == adopted

    asyncio.run(exercise())


def test_enabled_oauth_client_serves_actual_dtos_and_large_send_alongside_mcp(comm, monkeypatch):
    cfg = config(monkeypatch, comm, enabled=True)
    content = "A" + "🧭" * 35000
    assert 131072 < len(content.encode()) < 262144
    issuer = IssuerFixture({"valid": claims()})

    async def exercise():
        async with issuer.client() as issuer_client:
            app = app_for(comm, cfg, issuer_client)
            explicit_initialize(comm)
            async with (app.router.lifespan_context(app),
                httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as http):
                    meta = await http.get(PREFIX + "/meta")
                    assert meta.status_code == 200
                    CONTRACTS.validate("Meta", meta.json())
                    assert meta.json()["limits"]["message_bytes"] == 262144
                    http.headers["Authorization"] = "Bearer valid"
                    for suffix, model in (("/profile", "Actor"), ("/projects", "ProjectPage"),
                        (f"/projects/{PROJECT}/contacts", "ContactPage"), (f"/projects/{PROJECT}/routes", "RoutePage")):
                        response = await http.get(PREFIX + suffix)
                        assert response.status_code == 200, response.text
                        CONTRACTS.validate(model, response.json())
                    actor = (await http.get(PREFIX + "/profile")).json()
                    assert actor["level"] == "client" and actor["agent_slot_id"] is None
                    assert actor["principal_ref"] == comm.authority.context.principal_ref
                    request = {"to": PEER, "content": content, "activation": "message_only"}
                    sent = await http.post(PREFIX + f"/projects/{PROJECT}/messages", headers={"Idempotency-Key": "oauth-large-message"}, json=request)
                    assert sent.status_code == 201, sent.text
                    value = sent.json()
                    CONTRACTS.validate("SendResponse", value)
                    message = value["message"]
                    assert message["sender"].startswith("client:") and message["source"] == "acs_client"
                    assert message["content"]["total_bytes"] == len(content.encode())
                    assert message["content"]["digest"] == hashlib.sha256(content.encode()).hexdigest()
                    duplicate = await http.post(PREFIX + f"/projects/{PROJECT}/messages", headers={"Idempotency-Key": "oauth-large-message"}, json=request)
                    assert duplicate.status_code == 200 and duplicate.json()["duplicate"]
                    assert duplicate.json()["operation_ref"] == value["operation_ref"]
                    reference = message["message_handle"]
                    for suffix, model in ((f"/messages/{reference}", "ReadMessageResponse"),
                        (f"/messages/{reference}/delivery", "DeliveryFacts"), (f"/operations/{value['operation_ref']}", "Operation"),
                        ("/messages", "MessagePage")):
                        response = await http.get(PREFIX + f"/projects/{PROJECT}" + suffix)
                        assert response.status_code == 200, response.text
                        CONTRACTS.validate(model, response.json())
                    rpc_headers = {"Accept": "application/json, text/event-stream"}
                    initialized = await http.post("/mcp", headers=rpc_headers, json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "isolated-client-test", "version": "1"}}})
                    assert initialized.status_code == 200, initialized.text
                    assert "result" in rpc_json(initialized)
                    rpc_headers["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
                    rpc_headers["MCP-Protocol-Version"] = "2025-11-25"
                    assert (await http.post("/mcp", headers=rpc_headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})).status_code == 202
                    tools = await http.post("/mcp", headers=rpc_headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
                    assert tools.status_code == 200
                    assert "send_message" in {item["name"] for item in rpc_json(tools)["result"]["tools"]}
                    await http.delete("/mcp", headers=rpc_headers)

    asyncio.run(exercise())
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone() == (1,)
    assert not any(driver.calls for driver in comm.drivers.values())


def test_oauth_scope_revocation_and_identity_spoofing_never_mutate_a_message(comm, monkeypatch):
    cfg = config(monkeypatch, comm, enabled=True)
    read_scopes = {"acs:connect", *CATALOG["tools"]["list_projects"]["security_scopes"]}
    issuer = IssuerFixture({"valid": claims(), "reader": claims(scope=" ".join(sorted(read_scopes)))})

    async def exercise():
        async with issuer.client() as issuer_client:
            app = app_for(comm, cfg, issuer_client)
            explicit_initialize(comm)
            async with (app.router.lifespan_context(app),
                httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as http):
                    target = PREFIX + f"/projects/{PROJECT}/messages"
                    request = {"to": PEER, "content": "No body identity may select the caller", "activation": "message_only"}
                    headers = {"Authorization": "Bearer reader", "Idempotency-Key": "scope-rejected"}
                    denied = await http.post(target, headers=headers, json=request)
                    assert denied.status_code in {401, 403}
                    headers["Authorization"] = "Bearer valid"
                    for field in ("sender", "principal_ref", "agent_slot_id", "actor_ref"):
                        denied = await http.post(target, headers=headers, json=request | {field: "forged-caller"})
                        assert denied.status_code == 400, denied.text
                        assert denied.json()["error"]["effect_state"] == "none"
                    issuer.tokens["valid"] = {"active": False}
                    revoked = await http.get(PREFIX + "/projects", headers={"Authorization": "Bearer valid"})
                    assert revoked.status_code == 401
                    issuer.tokens["valid"] = claims()
                    with comm.authority._connect() as connection:
                        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (comm.authority.context.grant_ref,))
                    denied = await http.post(target, headers=headers, json=request)
                    assert denied.status_code in {401, 403}

    asyncio.run(exercise())
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone() == (0,)
    assert not any(driver.calls for driver in comm.drivers.values())
