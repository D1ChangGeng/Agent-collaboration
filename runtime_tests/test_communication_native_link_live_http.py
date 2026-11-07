"""Mounted OAuth metadata API, actual PG and a real Node/fetch TCP consumer.

Issuer introspection and existing Native readback are controlled fixtures. No
server DTO/event is injected; this is not installed-host or model qualification.
"""
from __future__ import annotations

import asyncio
import json
import os
import queue
import shutil
import socket
import subprocess
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from copy import copy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import uvicorn

from runtime.client_contracts import ClientContracts
from runtime.communication_event_storage import publish_event_intents
from runtime.delivery import DeliveryService
from runtime.delivery_models import EndpointBindingRequest
from runtime.delivery_node import LocalNodeEndpoint
from runtime.native_provider_registry import LocalExistingSessionProvider
from runtime.project_http import ProjectHttpSettings, create_http_app
from runtime_tests.test_communication import CATALOG
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_client_native_links import (
    PROJECT,
    PROVIDER,
    RECEIVER,
    client,
    count,
    deny_permission,
)
from runtime_tests.test_communication_client_native_links import native as native_fixture
from runtime_tests.test_communication_client_oauth import explicit_initialize, shared
from runtime_tests.test_delivery import command
from runtime_tests.test_project_http import IssuerFixture, claims, settings

comm, native = comm_fixture, native_fixture
ROOT = Path(__file__).resolve().parents[1]
PREFIX = "/api/communication/v1"
BASE = PREFIX + f"/projects/{PROJECT}/native-links"
CONTRACTS = ClientContracts()


def bearer(actor="b", key="http-write"):
    return {"Authorization": "Bearer link-" + actor, "Idempotency-Key": key}


def configuration(n, monkeypatch, *, enabled=True, events=False):
    data = settings(monkeypatch, n.f.authority.context).model_dump()
    data.update(communication_client_api=True, communication_native_links=enabled,
                communication_event_stream=events, authorization_refresh_seconds=5)
    data["bindings"] = []
    tokens = {}
    permissions = set(claims()["scope"].split()) | {"runtime.invoke", "delivery.manage"}
    for name, source in n.f.clients.items():
        context = source.service.context
        subject = "native-link-subject-" + name
        data["bindings"].append({"subject": subject, "client_id": "web-client", "profile": source.service.profile,
            "principal_ref": context.principal_ref, "grant_ref": context.grant_ref,
            "agent_slot_id": context.agent_slot_id, "trusted_client": False})
        tokens["link-" + name] = claims(sub=subject, scope=" ".join(sorted(permissions)))
    root = n.f.clients["a"].service.context
    data["bindings"].append({"subject": "native-link-trusted", "client_id": "web-client", "profile": "root_manager",
        "principal_ref": root.principal_ref, "grant_ref": root.grant_ref, "agent_slot_id": None, "trusted_client": True})
    tokens["link-trusted"] = claims(sub="native-link-trusted", scope=" ".join(sorted(permissions)))
    tokens["link-b-read"] = claims(sub="native-link-subject-b", scope="acs:connect runtime.read")
    tokens["link-a-no-delivery"] = claims(sub="native-link-subject-a", scope=" ".join(sorted(permissions - {"delivery.manage"})))
    n.f.authority._receiver_evidence_enabled = False
    n.f.authority._communication_events_enabled = events
    n.f.authority._communication_maintenance_mode = "external"
    return ProjectHttpSettings.model_validate(data), IssuerFixture(tokens)


@asynccontextmanager
async def mounted(n, monkeypatch, *, enabled=True, events=False):
    cfg, issuer = configuration(n, monkeypatch, enabled=enabled, events=events)
    async with issuer.client() as issuer_client:
        app = create_http_app(shared(n.f), CATALOG, cfg, client=issuer_client, native_provider_registry=n.registry)
        explicit_initialize(n.f)
        async with (app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as http):
            yield SimpleNamespace(http=http, app=app, issuer=issuer)


def quotas(n):
    limits = n.f.authority._communication_native_link_settings
    return {"native_link_count": limits.links_per_scope, "native_link_history_revisions": limits.history_per_link,
        "native_link_write_receipts": limits.requests_per_viewer, "native_link_metadata_bytes": limits.metadata_bytes}


def test_default_off_and_invalid_bearer_are_checked_before_request_body(native, monkeypatch):
    async def exercise():
        async with mounted(native, monkeypatch, enabled=False) as m:
            meta = (await m.http.get(PREFIX + "/meta")).json()
            assert "native_links" not in meta["features"]
            assert all(meta["limits"][key] == 0 for key in quotas(native))
            disabled = await m.http.put(BASE + "/disabled", headers=bearer(), json=native.body)
            assert disabled.status_code == 409 and disabled.json()["error"]["code"] == "capability_unsupported"
            touched = []

            async def hostile_body():
                touched.append(True)
                raise AssertionError("unauthorized request body consumed")
                yield b""

            denied = await m.http.put(BASE + "/unauthorized", headers={"Content-Type": "application/json"}, content=hostile_body())
            assert denied.status_code == 401 and touched == []
    asyncio.run(exercise())
    assert native.reads == [] and count(native) == 0


def test_actual_meta_and_legacy_self_write_return_twelve_fields_without_host_view_authority(native, monkeypatch):
    monkeypatch.setattr(native.registry, "authorize_host", lambda *_args, **_kwargs: pytest.fail("metadata granted Host permission"))
    async def exercise():
        async with mounted(native, monkeypatch) as m:
            meta = CONTRACTS.validate("Meta", (await m.http.get(PREFIX + "/meta")).json())
            assert "native_links" in meta["features"]
            assert {key: meta["limits"][key] for key in quotas(native)} == quotas(native)
            first = await m.http.put(BASE + "/实际-🧭", headers=bearer(), json=native.body)
            assert first.status_code == 200, first.text
            link = CONTRACTS.validate("NativeLink", first.json())
            assert len(link) == 12 and link["host_ref"] == native.body["expected_host_ref"]
            assert link["provider_generation"] == native.body["expected_provider_generation"] and len(native.reads) == 1
            assert (await m.http.put(BASE + "/实际-🧭", headers=bearer(), json=native.body)).json() == link
            assert (await m.http.get(BASE, headers=bearer("a"))).json()["items"] == [link]
            readonly = await m.http.put(BASE + "/实际-🧭", headers=bearer("b-read"), json=native.body)
            assert readonly.status_code == 403 and readonly.json()["error"]["effect_state"] == "none"
            assert (await m.http.get(BASE, headers=bearer("b-read"))).json()["items"] == [link]
            assert len(native.reads) == 1
            unsupported = await m.http.get(BASE + "/实际-🧭/transcript", headers=bearer("a"))
            assert unsupported.status_code in {404, 405}
    asyncio.run(exercise())
    assert count(native, "communication_messages") == count(native, "communication_replies") == 0
    assert not any(driver.calls for driver in native.f.drivers.values())


@pytest.mark.parametrize("actor,permission", [("b-read", "runtime.invoke"), ("a-no-delivery", "delivery.manage")])
def test_current_oauth_write_permission_is_required_even_when_core_grant_retains_it(native, monkeypatch, actor, permission):
    async def exercise():
        async with mounted(native, monkeypatch) as m:
            response = await m.http.put(BASE + "/scope-denied", headers=bearer(actor), json=native.body)
            assert response.status_code == 403, response.text
            assert response.json()["error"]["effect_state"] == "none"
            context = native.f.clients["b" if actor.startswith("b") else "a"].service.context
            with native.f.authority._connect() as connection:
                assert permission in connection.execute("SELECT permissions FROM grants WHERE grant_ref=%s", (context.grant_ref,)).fetchone()[0]
    asyncio.run(exercise())
    assert native.reads == [] and count(native) == 0


@pytest.mark.parametrize("actor", ["c", "trusted"])
def test_foreign_slot_and_shared_trusted_client_cannot_bypass_metadata_management_grant(native, monkeypatch, actor):
    if actor == "trusted":
        deny_permission(native, "a", "delivery.manage")

    async def exercise():
        async with mounted(native, monkeypatch) as m:
            response = await m.http.put(BASE + "/actor-denied", headers=bearer(actor), json=native.body)
            assert response.status_code == 403, response.text
            assert response.json()["error"]["effect_state"] == "none"
    asyncio.run(exercise())
    assert native.reads == [] and count(native) == 0


def test_actual_provider_proof_runs_without_sql_lock_and_registry_replacement_is_atomic_noneffect(native, monkeypatch):
    prove = native.registry.prove

    def interleave(*args):
        with native.f.authority._connect() as connection:
            connection.execute("SELECT 1 FROM delivery_endpoints WHERE endpoint_id=%s FOR UPDATE NOWAIT", (RECEIVER,))
        result = prove(*args)
        native.registry.unregister(PROVIDER, "harness")
        native.registry.register(native.admission, LocalExistingSessionProvider(native.endpoint))
        return result

    monkeypatch.setattr(native.registry, "prove", interleave)

    async def exercise():
        async with mounted(native, monkeypatch) as m:
            result = await m.http.put(BASE + "/replaced", headers=bearer(), json=native.body)
            assert result.status_code == 409, result.text
            assert result.json()["error"]["code"] == "native_provider_registration_changed"
            assert result.json()["error"]["effect_state"] == "none"
    asyncio.run(exercise())
    assert count(native) == count(native, "communication_native_link_history") == count(native, "communication_native_link_requests") == 0


def test_current_core_grant_revocation_after_real_proof_prevents_http_commit(native, monkeypatch):
    prove = native.registry.prove

    def revoke(*args):
        result = prove(*args)
        with native.f.authority._connect() as connection:
            connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                               (native.f.clients["b"].service.context.grant_ref,))
        return result

    monkeypatch.setattr(native.registry, "prove", revoke)

    async def exercise():
        async with mounted(native, monkeypatch) as m:
            result = await m.http.put(BASE + "/revoked", headers=bearer(), json=native.body)
            assert result.status_code == 403 and result.json()["error"]["effect_state"] == "none", result.text
    asyncio.run(exercise())
    assert count(native) == count(native, "communication_native_link_requests") == 0


def test_route_grant_metadata_is_filtered_while_root_grant_retains_project_visibility(native, monkeypatch):
    async def exercise():
        async with mounted(native, monkeypatch) as m:
            written = await m.http.put(BASE + "/visible", headers=bearer(), json=native.body)
            assert written.status_code == 200, written.text
            with native.f.authority._connect() as connection:
                connection.execute("INSERT INTO scopes(scope_id,tenant_id,status) VALUES ('other-route',%s,'active')", (native.f.authority.tenant_id,))
                connection.execute("INSERT INTO collaboration_routes(tenant_id,project_id,route_id,scope_id,definition) "
                    "VALUES (%s,%s,'other-route','other-route','{}')", (native.f.authority.tenant_id, PROJECT))
                connection.execute("UPDATE agent_slots SET scope_id='other-route' WHERE agent_slot_id='slot-c'")
                connection.execute("UPDATE grants SET scope_id='other-route' WHERE grant_ref=%s", (native.f.clients["c"].service.context.grant_ref,))
            root = await m.http.get(BASE, headers=bearer("a"))
            route = await m.http.get(BASE, headers=bearer("c"))
            assert root.status_code == route.status_code == 200
            assert root.json()["items"] == [written.json()] and route.json()["items"] == []
    asyncio.run(exercise())


def publish(n):
    with n.f.authority._connect() as connection:
        while publish_event_intents(connection, n.f.authority.tenant_id, PROJECT, limit=100):
            pass


def test_actual_http_write_projects_minimal_link_event_with_current_metadata_acl(native, monkeypatch):
    async def exercise():
        async with mounted(native, monkeypatch, events=True) as m:
            reader = client(native.f, "a")
            snapshot = reader.snapshot(PROJECT, limit=1)
            written = await m.http.put(BASE + "/event-link", headers=bearer(), json=native.body)
            assert written.status_code == 200, written.text
            publish(native)
            batch = reader.event_batch(PROJECT, after_cursor=snapshot["after_cursor"])
            events = [event for event in batch.events if event["kind"] == "native_link.changed"]
            assert len(events) == 1 and events[0]["resource_ref"] == "event-link" and events[0]["payload"] == {}
            deny_permission(native, "a", "runtime.read")
            denied = await m.http.get(BASE, headers=bearer("a"))
            assert denied.status_code == 403
            from runtime.communication_http import CommunicationHttpError
            with pytest.raises(CommunicationHttpError):
                reader.event_current(PROJECT, event_id=events[0]["event_id"])
    asyncio.run(exercise())


def reassign(n):
    scope = "sdk-reassigned-scope"
    with n.f.authority._connect() as connection:
        connection.execute("INSERT INTO scopes(scope_id,tenant_id,status) VALUES (%s,%s,'active')", (scope, n.f.authority.tenant_id))
        connection.execute("INSERT INTO collaboration_routes(tenant_id,project_id,route_id,scope_id,definition) "
                           "VALUES (%s,%s,%s,%s,'{}')", (n.f.authority.tenant_id, PROJECT, scope, scope))
        connection.execute("UPDATE agent_slots SET scope_id=%s WHERE agent_slot_id='slot-c'", (scope,))
    endpoints = n.f.authority._delivery_endpoints
    endpoints[RECEIVER] = LocalNodeEndpoint(n.endpoint.journal, scope, "slot-c", n.f.drivers["c"])
    owner = copy(n.f.authority)
    owner.access_mode = "owner"
    DeliveryService(owner, endpoints).bind_endpoint(command(owner, "message.bind", RECEIVER,
        revision=n.body["expected_binding_epoch"]), EndpointBindingRequest(scope_id=scope, agent_slot_id="slot-c",
        expires_at=n.f.authority.canonical_now() + timedelta(hours=1)))


@contextmanager
def tcp_listener(n, monkeypatch):
    cfg, issuer = configuration(n, monkeypatch, events=True)
    issuer_client = issuer.client()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]
        app = create_http_app(shared(n.f), CATALOG, cfg, port=port, client=issuer_client, native_provider_registry=n.registry)
        explicit_initialize(n.f)
        server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False, proxy_headers=False, lifespan="on"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 8
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            thread.join(timeout=8)
            assert not thread.is_alive()
            asyncio.run(issuer_client.aclose())


def test_production_sdk_real_tcp_oauth_metadata_paging_events_and_original_replay(native, monkeypatch):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable for production SDK TCP consumer")
    with tcp_listener(native, monkeypatch) as url:
        environment = {key: value for key, value in os.environ.items() if not any(
            part in key.upper() for part in ("DSN", "PGPASSWORD", "DATABASE_URL", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"))}
        environment.update(ACS_NATIVE_LINK_TEST_URL=url, ACS_NATIVE_LINK_TEST_BEARER="link-a", NODE_USE_ENV_PROXY="0", NO_PROXY="127.0.0.1,localhost")
        process = subprocess.Popen([node, str(ROOT / "sdk/tests/native-link-live-consumer.mjs")], cwd=ROOT,
            env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        messages, errors = queue.Queue(maxsize=32), []

        def output():
            for line in process.stdout:
                messages.put(line)
            messages.put(None)

        def stderr():
            for line in process.stderr:
                if sum(map(len, errors)) < 16384:
                    errors.append(line[:2048])

        readers = [threading.Thread(target=output, daemon=True), threading.Thread(target=stderr, daemon=True)]
        for reader in readers:
            reader.start()
        process.stdin.write(json.dumps({"type": "configuration", "project": PROJECT, "body": native.body, "quotas": quotas(native)}) + "\n")
        process.stdin.flush()
        evidence, changed = None, False
        try:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                try:
                    line = messages.get(timeout=1)
                except queue.Empty:
                    continue
                assert line is not None, "Node consumer exited before evidence: " + "".join(errors)
                value = json.loads(line)
                assert value.get("type") != "failure", value
                if value["type"] == "result":
                    evidence = value["evidence"]
                    break
                assert value["type"] == "request"
                if value["action"] == "publish":
                    publish(native)
                else:
                    assert value["action"] == "reassign" and not changed
                    assert len(native.reads) == 3
                    reassign(native)
                    changed = True
                process.stdin.write(json.dumps({"id": value["id"], "result": {"done": True}}) + "\n")
                process.stdin.flush()
            assert evidence is not None and changed
            assert process.wait(timeout=8) == 0
            assert evidence["stable_snapshot_pages"] == evidence["native_link_events"] == 3
            assert evidence["host_read_action_permission_granted"] is False
            assert evidence["live_host_qualified"] is evidence["model_qualified"] is False
            assert evidence["writes_attempted"] == 6 and len(native.reads) == 3
            assert count(native) == count(native, "communication_native_link_history") == count(native, "communication_native_link_requests") == 3
            assert count(native, "communication_messages") == count(native, "communication_replies") == 0
            assert not any(driver.calls for driver in native.f.drivers.values())
            (ROOT / ".tmp/native-link-live-sdk-evidence-20261106.json").write_text(json.dumps(evidence, sort_keys=True) + "\n", encoding="utf-8")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            for pipe in (process.stdin, process.stdout, process.stderr):
                pipe.close()
            for reader in readers:
                reader.join(timeout=2)
