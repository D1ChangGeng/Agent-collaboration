"""Project/MCP authorization and receiving-selection races on isolated PostgreSQL."""
from __future__ import annotations

import asyncio
import json

import httpx
import psycopg
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from runtime.receiver_contract import ReceiverSnapshot
from runtime_tests.test_communication import call
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_project_http import IssuerFixture, claims, listener, settings
from runtime_tests.test_receiver_contract import snapshot

comm = comm_fixture


def test_feature_is_off_by_default_and_does_not_change_legacy_harness_results(comm):
    items = call(comm, "a", "list_harnesses")["data"]["items"]
    assert items and all("receiver" not in item for item in items)
    assert all(driver.calls == [] for driver in comm.drivers.values())


def test_unupgraded_receivers_are_unknown_without_fake_sessions_or_activation(comm):
    comm.authority._receiver_evidence_enabled = True
    before = call(comm, "a", "check_inbox")["data"]
    items = call(comm, "a", "list_harnesses")["data"]["items"]
    for item in items:
        receiver = ReceiverSnapshot.model_validate_json(json.dumps(item["receiver"]))
        assert receiver.binding_epoch == item["binding_revision"]
        assert receiver.address == item["collaborator_handle"]
        assert receiver.native_session_ref is None and receiver.allowed_actions == ()
        assert all(c.support == c.availability == "unknown" for c in receiver.capabilities)
        assert all(o.value is None for o in receiver.observations)
    assert call(comm, "a", "check_inbox")["data"] == before
    assert all(driver.calls == [] for driver in comm.drivers.values())


def _bound_snapshot(binding):
    item = snapshot()
    generation = item.capability_scope.provider_generation
    return ReceiverSnapshot(receiver_id=binding.receiver_id, address=binding.actor_address,
        binding_epoch=binding.binding_epoch, revision=binding.binding_epoch,
        native_session_ref="synthetic-session", capability_scope=item.capability_scope.model_copy(update={
            "execution_host_ref": binding.execution_host_ref, "connection_epoch": binding.binding_epoch}),
        capabilities=item.capabilities, observations=tuple(o.model_copy(update={
            "binding_epoch": binding.binding_epoch, "provider_generation": generation}) for o in item.observations),
        allowed_actions=())


def test_binding_change_during_readback_invalidates_observation_without_repair(comm, monkeypatch):
    comm.authority._receiver_evidence_enabled = True
    endpoint = comm.authority._delivery_endpoints["endpoint-b"]
    calls = []

    def changed(binding):
        calls.append(binding)
        with psycopg.connect(comm.dsn) as connection:
            connection.execute("UPDATE delivery_endpoints SET revision=revision+1 WHERE endpoint_id='endpoint-b'")
        return _bound_snapshot(binding)

    monkeypatch.setattr(endpoint, "receiver_snapshot", changed)
    items = call(comm, "a", "list_harnesses")["data"]["items"]
    projected = next(item["receiver"] for item in items if item["endpoint_id"] == "endpoint-b")
    assert len(calls) == 1
    assert projected["native_session_ref"] is None
    assert all(o["reason_code"] == "receiver_binding_changed" for o in projected["observations"])
    assert all(driver.calls == [] for driver in comm.drivers.values())


def test_provider_cannot_replace_the_authorized_address(comm, monkeypatch):
    comm.authority._receiver_evidence_enabled = True
    endpoint = comm.authority._delivery_endpoints["endpoint-b"]
    monkeypatch.setattr(endpoint, "receiver_snapshot", lambda binding: _bound_snapshot(binding).model_copy(
        update={"address": "collaborator:private-project:secret"}))
    items = call(comm, "a", "list_harnesses")["data"]["items"]
    item = next(item["receiver"] for item in items if item["endpoint_id"] == "endpoint-b")
    assert item["address"] == "collaborator:project-alpha:slot-b"
    assert all(o["reason_code"] == "receiver_binding_changed" for o in item["observations"])
    assert "private-project" not in str(item)


def test_reconnected_node_cannot_reuse_the_previous_peers_evidence(comm, monkeypatch):
    comm.authority._receiver_evidence_enabled = True
    endpoint = comm.authority._delivery_endpoints["endpoint-b"]
    probes = []
    monkeypatch.setattr(endpoint, "receiver_snapshot", lambda binding: probes.append(binding))
    with psycopg.connect(comm.dsn) as connection:
        connection.execute("UPDATE delivery_endpoints SET node_id='replacement-node' WHERE endpoint_id='endpoint-b'")
    items = call(comm, "a", "list_harnesses")["data"]["items"]
    item = next(item["receiver"] for item in items if item["endpoint_id"] == "endpoint-b")
    assert probes == []
    assert all(o["reason_code"] == "receiver_binding_changed" for o in item["observations"])


def test_revoked_caller_cannot_probe_receiver_capabilities(comm, monkeypatch):
    comm.authority._receiver_evidence_enabled = True
    probes = []
    for endpoint in comm.authority._delivery_endpoints.values():
        monkeypatch.setattr(endpoint, "receiver_snapshot", lambda binding: probes.append(binding))
    with psycopg.connect(comm.dsn) as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                           (comm.authority.context.grant_ref,))
    result = comm.clients["a"].call("list_harnesses", {"project_id": "project-alpha"})["structuredContent"]
    assert result["ok"] is False and result["data"]["code"] == "authorization_denied"
    assert probes == []


def test_receiver_evidence_io_is_bounded_to_the_returned_page(comm, monkeypatch):
    comm.authority._receiver_evidence_enabled = True
    probes = []
    for endpoint in comm.authority._delivery_endpoints.values():
        def observe(binding):
            probes.append(binding.receiver_id)
            return _bound_snapshot(binding)
        monkeypatch.setattr(endpoint, "receiver_snapshot", observe)
    first = call(comm, "a", "list_harnesses", limit=1)["data"]
    assert len(first["items"]) == len(probes) == 1
    assert probes == [first["items"][0]["endpoint_id"]]
    probes.clear()
    second = call(comm, "a", "list_harnesses", limit=1, cursor=first["next_cursor"])["data"]
    assert len(second["items"]) == len(probes) == 1
    assert probes == [second["items"][0]["endpoint_id"]]
    assert first["items"][0]["endpoint_id"] != second["items"][0]["endpoint_id"]


def test_http_and_mcp_share_the_receiver_serializer_and_live_permissions(comm, monkeypatch):
    comm.authority._receiver_evidence_enabled = True
    config = settings(monkeypatch, comm.authority.context)
    issuer = IssuerFixture({"isolated-reader": claims()})

    async def exercise(url):
        async with (httpx.AsyncClient(headers={"Authorization": "Bearer isolated-reader"}, trust_env=False) as http,
                    streamable_http_client(url + "/mcp", http_client=http) as streams,
                    ClientSession(*streams, read_timeout_seconds=10) as client):
            await client.initialize()
            response = await client.call_tool("list_harnesses", {"project_id": "project-alpha"})
            assert not response.is_error
            receivers = response.structured_content["data"]["items"]
            assert receivers and all(item["receiver"]["address"] == item["collaborator_handle"] for item in receivers)
            assert all(item["receiver"]["native_session_ref"] is None for item in receivers)
            with psycopg.connect(comm.dsn) as connection:
                connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                                   (comm.authority.context.grant_ref,))
            denied = await client.call_tool("list_harnesses", {"project_id": "project-alpha"})
            assert denied.is_error

    with listener(comm.clients["a"].service.service, config, issuer) as (url, _server):
        asyncio.run(exercise(url))
