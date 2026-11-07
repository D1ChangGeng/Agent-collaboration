"""Actual OAuth/PG SSE and explicitly synthetic stalled-transport episodes.

One test uses a real local TCP listener. Controlled body_iterator pauses test
queue/backpressure boundaries without holding a network call inside a DB txn.
Neither path contacts a real issuer, Harness, model or production database.
"""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlencode

import httpx
import pytest
import uvicorn
from starlette.requests import Request

from runtime.client_contracts import ClientContracts
from runtime.communication_client_events import encode_event_cursor
from runtime.communication_client_notice_storage import adopt_notice_storage
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_client_storage import adopt_client_storage
from runtime.communication_client_viewer_storage import adopt_viewer_storage
from runtime.communication_event_http import EventStreamLimits
from runtime.communication_event_storage import (
    publish_event_intents,
    purge_event_records,
    record_event_intent,
    verify_event_storage,
)
from runtime.project_http import ProjectHttpSettings, TokenAuthorization, create_http_app
from runtime.project_schema_state import ProjectSchemaAdoptionRequired
from runtime_tests.test_communication import CATALOG, send
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_client_oauth import config, explicit_initialize, shared
from runtime_tests.test_project_http import IssuerFixture, claims

comm = comm_fixture
PROJECT = "project-alpha"
PREFIX = "/api/communication/v1/projects/" + PROJECT
TOKEN = "event-token"
CONTRACTS = ClientContracts()
FAST = EventStreamLimits(max_events=8, max_bytes=8192, heartbeat_seconds=0.03, poll_seconds=0.01, slow_consumer_seconds=0.3)


def settings(monkeypatch, f, *, enabled=True):
    data = config(monkeypatch, f, enabled=True).model_dump()
    data["bindings"][0].update(trusted_client=False, agent_slot_id="local-slot")
    data.update(communication_event_stream=enabled, authorization_refresh_seconds=5)
    return ProjectHttpSettings.model_validate(data)


def tuned_app(monkeypatch, f, issuer_client, *, enabled=True, budgets=FAST, port=8765):
    import runtime.communication_event_http as event_http

    actual = event_http.register_event_routes

    def register(app, **kwargs):
        return actual(app, **{**kwargs, "limits": budgets})

    with monkeypatch.context() as construction:
        construction.setattr(event_http, "register_event_routes", register)
        app = create_http_app(shared(f), CATALOG, settings(monkeypatch, f, enabled=enabled), port=port, client=issuer_client)
    facade = next(route.app for route in app.router.routes
                  if getattr(getattr(getattr(route, "app", None), "state", None), "oauth_provider", None) is not None)
    return app, facade


def publish(f):
    total = 0
    with f.authority._connect() as connection:
        while count := publish_event_intents(connection, f.authority.tenant_id, PROJECT, limit=1000):
            total += count
    return total


def business_state(f):
    tables = ("communication_messages", "communication_replies", "delivery_messages", "delivery_receipts",
              "delivery_attempts", "communication_client_read_state", "communication_client_drafts")
    with f.authority._connect() as connection:
        return {table: connection.execute("SELECT md5(COALESCE(string_agg(to_jsonb(t)::text,',' ORDER BY to_jsonb(t)::text),'')) "
                                         "FROM " + table + " t").fetchone()[0] for table in tables}


def request(*, after=None, kinds=None, disconnected=None):
    query = [] if after is None else [("after_cursor", after)]
    query.extend(("kinds", kind) for kind in kinds or [])

    async def receive():
        await (disconnected or asyncio.Event()).wait()
        return {"type": "http.disconnect"}

    scope = {"type": "http", "http_version": "1.1", "asgi": {"version": "3.0"}, "method": "GET", "scheme": "http",
        "path": PREFIX + "/events", "raw_path": (PREFIX + "/events").encode(), "root_path": "",
        "query_string": urlencode(query).encode(), "headers": [(b"authorization", ("Bearer " + TOKEN).encode())],
        "path_params": {"project_id": PROJECT}, "server": ("127.0.0.1", 8765), "client": ("127.0.0.1", 1)}
    value = Request(scope, receive)
    value.state.request_id = "synthetic-transport-request"
    value.state.effect_state, value.state.operation_ref = "none", None
    return value


async def service(facade):
    projects, credential = await facade.state.oauth_provider(request())
    return CommunicationClientService(projects, credential)


def anchor(own):
    return own._event_transaction(PROJECT, lambda bound, cursor, _root, _command, revision:
        encode_event_cursor(cursor, bound.tenant_id, PROJECT, revision, 0, anchor=True))


async def response(facade, req):
    endpoint = next(route.endpoint for route in facade.router.routes if getattr(route, "path", "") == PREFIX.replace(PROJECT, "{project_id}") + "/events")
    return await endpoint(PROJECT, req)


def decode_frame(raw):
    if raw.startswith(b":"):
        return None
    fields = {line.split(":", 1)[0]: line.split(":", 1)[1].lstrip(" ")
              for line in raw.decode().splitlines() if ":" in line}
    event = json.loads(fields["data"])
    CONTRACTS.validate("Event", event)
    assert fields["id"] == event["cursor"] and fields["event"] == event["kind"]
    return event


def tcp_event(lines):
    frame = []
    for line in lines:
        if not line:
            if frame and not frame[0].startswith(":"):
                return decode_frame(("\n".join(frame) + "\n\n").encode())
            frame = []
        else:
            frame.append(line)
    raise AssertionError("TCP stream ended before a complete domain event")


@contextmanager
def listener(monkeypatch, f, issuer):
    issuer_client = issuer.client()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]
        app, _facade = tuned_app(monkeypatch, f, issuer_client, port=port)
        explicit_initialize(f)
        server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False, proxy_headers=False, lifespan="on"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            end = time.monotonic() + 5
            while not server.started and thread.is_alive() and time.monotonic() < end:
                time.sleep(0.01)
            assert server.started, "the owned local SSE listener did not start"
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            thread.join(timeout=8)
            assert not thread.is_alive(), "the owned local SSE listener did not stop"
            asyncio.run(issuer_client.aclose())


def test_disabled_stream_returns_409_without_preparing_event_storage(comm, monkeypatch):
    f = comm
    monkeypatch.setattr(CommunicationClientService, "event_batch", lambda *_args, **_kwargs: pytest.fail("disabled stream read event storage"))

    async def exercise():
        async with IssuerFixture({TOKEN: claims()}).client() as issuer:
            app, _facade = tuned_app(monkeypatch, f, issuer, enabled=False)
            explicit_initialize(f)
            with f.authority._connect() as connection:
                assert connection.execute("SELECT to_regclass('communication_event_stream')").fetchone() == (None,)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as http:
                result = await http.get(PREFIX + "/events", headers={"Authorization": "Bearer " + TOKEN}, params={"after_cursor": "not-decoded"})
                assert result.status_code == 409 and result.json()["error"]["code"] == "capability_unsupported", result.text
            with f.authority._connect() as connection:
                assert connection.execute("SELECT to_regclass('communication_event_stream')").fetchone() == (None,)

    asyncio.run(exercise())


def test_enabled_startup_requires_explicit_event_adoption_and_event_flag_requires_client_api(comm, monkeypatch):
    f = comm
    bad = settings(monkeypatch, f).model_dump()
    bad["communication_client_api"] = False
    with pytest.raises(ValueError):
        ProjectHttpSettings.model_validate(bad)

    async def exercise():
        async with IssuerFixture({TOKEN: claims()}).client() as issuer:
            app, _facade = tuned_app(monkeypatch, f, issuer)
            with f.authority._connect() as connection:
                adopt_client_storage(connection)
                adopt_viewer_storage(connection)
                adopt_notice_storage(connection)
            with pytest.raises(ProjectSchemaAdoptionRequired):
                async with app.router.lifespan_context(app):
                    pytest.fail("enabled event startup admitted unadopted storage")
            with f.authority._connect() as connection:
                assert connection.execute("SELECT to_regclass('communication_event_stream')").fetchone() == (None,)
            explicit_initialize(f)
            with f.authority._connect() as connection:
                verify_event_storage(connection)
            async with app.router.lifespan_context(app):
                pass

    asyncio.run(exercise())


def test_actual_tcp_snapshot_anchor_replay_last_event_id_and_kind_filter_are_readonly(comm, monkeypatch):
    f = comm
    f.authority._receiver_evidence_enabled = False
    f.authority._communication_maintenance_mode = "external"
    issuer = IssuerFixture({TOKEN: claims()})
    with listener(monkeypatch, f, issuer) as url, httpx.Client(base_url=url, trust_env=False, timeout=5,
        headers={"Authorization": "Bearer " + TOKEN}) as http:
        metadata = http.get("/api/communication/v1/meta")
        assert metadata.status_code == 200 and {"snapshot", "events"} <= set(metadata.json()["features"])
        snapshot = http.get(PREFIX + "/snapshot")
        assert snapshot.status_code == 200, snapshot.text
        CONTRACTS.validate("Snapshot", snapshot.json())
        start = snapshot.json()["after_cursor"]
        first = send(f, content="PRIVATE_FIRST_BODY_NOT_IN_SSE", activation="message_only")["data"]
        publish(f)
        before = business_state(f)
        with http.stream("GET", PREFIX + "/events", params=[("after_cursor", start), ("kinds", "message.committed")],
                         headers={"Last-Event-ID": start}) as stream:
            assert stream.status_code == 200 and stream.headers["content-type"].startswith("text/event-stream")
            observed = tcp_event(stream.iter_lines())
        assert observed["kind"] == "message.committed" and observed["resource_ref"] == first["message_handle"]
        assert observed["auth_revision"] == snapshot.json()["auth_revision"]
        assert "PRIVATE_FIRST_BODY" not in json.dumps(observed)
        second = send(f, content="PRIVATE_SECOND_BODY_NOT_IN_SSE", activation="message_only")["data"]
        publish(f)
        before_second = business_state(f)
        with http.stream("GET", PREFIX + "/events", params={"kinds": "message.committed"}, headers={"Last-Event-ID": observed["cursor"]}) as stream:
            assert stream.status_code == 200
            resumed = tcp_event(stream.iter_lines())
        assert resumed["resource_ref"] == second["message_handle"] and resumed["event_id"] != observed["event_id"]
        assert business_state(f) == before_second
        assert before["communication_replies"] == before_second["communication_replies"]
        mismatch = http.get(PREFIX + "/events", params={"after_cursor": start}, headers={"Last-Event-ID": resumed["cursor"]})
        assert mismatch.status_code == 400 and mismatch.headers["content-type"].startswith("application/json")
    assert not any(driver.calls for driver in f.drivers.values())


def test_expired_replay_returns_http_410_before_sse_headers_and_bad_filters_are_400(comm, monkeypatch):
    f = comm

    async def exercise():
        async with IssuerFixture({TOKEN: claims()}).client() as issuer:
            app, facade = tuned_app(monkeypatch, f, issuer)
            explicit_initialize(f)
            own = await service(facade)
            start = anchor(own)
            send(f, activation="message_only")
            publish(f)
            with f.authority._connect() as connection:
                removed, floor = purge_event_records(connection, f.authority.tenant_id, PROJECT, before=datetime.now(UTC) + timedelta(minutes=1))
            assert removed > 0 and floor > 0
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765",
                                        headers={"Authorization": "Bearer " + TOKEN}) as http:
                expired = await http.get(PREFIX + "/events", params={"after_cursor": start})
                assert expired.status_code == 410 and expired.headers["content-type"].startswith("application/json"), expired.text
                assert expired.json()["error"]["code"] == "cursor_expired" and "data:" not in expired.text
                for params in ([('after_cursor', start), ('kinds', 'unknown.kind')],
                               [('after_cursor', start), ('kinds', 'message.committed'), ('kinds', 'message.committed')]):
                    invalid = await http.get(PREFIX + "/events", params=params)
                    assert invalid.status_code == 400, invalid.text
                duplicate = await http.get(PREFIX + "/events", headers=[("Last-Event-ID", start), ("Last-Event-ID", start)])
                assert duplicate.status_code == 400, duplicate.text

    asyncio.run(exercise())


@pytest.mark.parametrize("loss", ["grant", "scope", "oauth_scope", "oauth_revoked"])
def test_queued_frames_are_cleared_on_current_authority_loss_before_next_emit(comm, monkeypatch, loss):
    f = comm

    async def exercise():
        issuer = IssuerFixture({TOKEN: claims()})
        async with issuer.client() as issuer_client:
            _app, facade = tuned_app(monkeypatch, f, issuer_client)
            explicit_initialize(f)
            own = await service(facade)
            start = anchor(own)
            for index in range(3):
                send(f, content="PRIVATE_QUEUED_MESSAGE_BODY_" + str(index), activation="message_only")
            view = own.resolve_conversation(PROJECT, peer="collaborator:project-alpha:slot-b")["conversation_id"]
            own.update_draft(PROJECT, view, {"content": "PRIVATE_DRAFT_TEXT_NOT_IN_EVENT", "attachment_refs": []},
                             expected_revision=0, client_request_id="queued-private-draft")
            publish(f)
            before = business_state(f)
            req = request(after=start)
            stream = await response(facade, req)
            iterator = stream.body_iterator
            first = decode_frame(await asyncio.wait_for(anext(iterator), 5))
            assert first is not None and "PRIVATE_" not in json.dumps(first)
            if loss == "grant":
                with f.authority._connect() as connection:
                    connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (f.authority.context.grant_ref,))
            elif loss == "scope":
                with f.authority._connect() as connection:
                    connection.execute("UPDATE scopes SET status='revoked' WHERE tenant_id=%s AND scope_id='local-scope'", (f.authority.tenant_id,))
            else:
                issuer.tokens[TOKEN] = ({"active": False} if loss == "oauth_revoked" else claims(scope=" ".join(
                    scope for scope in claims()["scope"].split() if scope != "runtime.read")))
                req.state.project_service.token_authorization.checked_at -= 10
            control = decode_frame(await asyncio.wait_for(anext(iterator), 5))
            assert control["kind"] == "permission.changed" and control["resource_ref"] is None, control
            assert control["cursor"] == first["cursor"]
            assert control["payload"] == {"reason_code": "authorization_changed", "reset_required": True}
            assert "PRIVATE_" not in json.dumps(control) and "message_handle" not in control["payload"]
            with pytest.raises(StopAsyncIteration):
                await anext(iterator)
            assert business_state(f) == before

    asyncio.run(exercise())
    assert not any(driver.calls for driver in f.drivers.values())


def test_heartbeats_have_no_effect_and_disconnect_cancels_producer_and_refresh(comm, monkeypatch):
    f = comm
    counts = SimpleNamespace(refresh=0)
    original = TokenAuthorization.refresh

    async def refresh(self):
        counts.refresh += 1
        return await original(self)

    monkeypatch.setattr(TokenAuthorization, "refresh", refresh)

    async def exercise():
        async with IssuerFixture({TOKEN: claims()}).client() as issuer:
            _app, facade = tuned_app(monkeypatch, f, issuer)
            explicit_initialize(f)
            start = anchor(await service(facade))
            disconnected = asyncio.Event()
            stream = await response(facade, request(after=start, disconnected=disconnected))
            iterator = stream.body_iterator
            before = business_state(f)
            for _index in range(2):
                assert (await asyncio.wait_for(anext(iterator), 5)).startswith(b": heartbeat")
            disconnected.set()
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(anext(iterator), 5)
            stopped = counts.refresh
            await asyncio.sleep(0.1)
            assert counts.refresh == stopped
            assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task() and
                        getattr(task.get_coro(), "__qualname__", "").endswith("produce")]
            assert business_state(f) == before

    asyncio.run(exercise())


def test_stalled_synthetic_transport_resyncs_from_last_yielded_cursor_not_queued_producer_position(comm, monkeypatch):
    f = comm

    async def exercise():
        async with IssuerFixture({TOKEN: claims()}).client() as issuer:
            budgets = EventStreamLimits(max_events=2, max_bytes=4096, heartbeat_seconds=0.03, poll_seconds=0.01, slow_consumer_seconds=2)
            _app, facade = tuned_app(monkeypatch, f, issuer, budgets=budgets)
            explicit_initialize(f)
            start = anchor(await service(facade))
            for index in range(4):
                send(f, content="PRIVATE_SLOW_CONSUMER_BODY_" + str(index), activation="message_only")
            publish(f)
            before = business_state(f)
            first_yielded, capacity_observed, control_queued = threading.Event(), asyncio.Event(), asyncio.Event()
            loop = asyncio.get_running_loop()
            current = CommunicationClientService.event_current
            queue_type = asyncio.Queue
            peaks = {"events": 0, "bytes": 0}

            def observe_current(self, *args, **kwargs):
                result = current(self, *args, **kwargs)
                # Only the producer capacity monitor runs without event_id
                # while the consumer remains paused at its first network yield.
                if first_yielded.is_set() and kwargs.get("event_id") is None:
                    loop.call_soon_threadsafe(capacity_observed.set)
                return result

            class ObservedQueue(queue_type):
                def put_nowait(self, item):
                    super().put_nowait(item)
                    peaks["events"] = max(peaks["events"], self.qsize())
                    peaks["bytes"] = max(peaks["bytes"], sum(len(value[0]) for value in self._queue if value[0] is not None))
                    if item[0] is None:
                        control_queued.set()

            monkeypatch.setattr(CommunicationClientService, "event_current", observe_current)
            monkeypatch.setattr(asyncio, "Queue", ObservedQueue)
            stream = await response(facade, request(after=start))
            iterator = stream.body_iterator
            first = decode_frame(await asyncio.wait_for(anext(iterator), 5))
            assert first is not None
            first_yielded.set()
            await asyncio.wait_for(capacity_observed.wait(), 5)
            # Wait for the real bounded queue to close under backpressure;
            # a fixed wall-clock sleep could finish before PG polling starts.
            await asyncio.wait_for(control_queued.wait(), budgets.slow_consumer_seconds + 5)
            control = decode_frame(await asyncio.wait_for(anext(iterator), 5))
            assert control["kind"] == "resync.required" and control["payload"]["reason_code"] == "slow_consumer", control
            assert control["cursor"] == first["cursor"] and control["resource_ref"] is None
            assert control["payload"]["reset_required"] is True and "PRIVATE_" not in json.dumps(control)
            assert peaks["events"] <= budgets.max_events and peaks["bytes"] <= budgets.max_bytes
            with pytest.raises(StopAsyncIteration):
                await anext(iterator)
            assert business_state(f) == before

    asyncio.run(exercise())
    assert not any(driver.calls for driver in f.drivers.values())


@pytest.mark.parametrize("kind", ["receiver.observed", "capability.changed"])
def test_queued_target_visibility_is_rechecked_even_when_caller_authorization_hash_does_not_change(comm, monkeypatch, kind):
    f = comm

    async def exercise():
        async with IssuerFixture({TOKEN: claims()}).client() as issuer:
            _app, facade = tuned_app(monkeypatch, f, issuer)
            explicit_initialize(f)
            own = await service(facade)
            start = anchor(own)
            sent = send(f, content="PRIVATE_MESSAGE_BEFORE_TARGET_MOVE", activation="message_only")["data"]
            with f.authority._connect() as connection, connection.cursor() as cursor:
                # A real committed source invalidation, not an invented Receiver
                # DTO or Native observation, names the actual registered target.
                record_event_intent(cursor, f.authority.tenant_id, PROJECT, source_key="target-visibility:" + kind,
                    kind=kind, resource_ref="endpoint-b", resource_revision=1, audience_kind="receiver", scope_id="local-scope")
            publish(f)
            req = request(after=start, kinds=["message.committed", kind])
            stream = await response(facade, req)
            iterator = stream.body_iterator
            first = decode_frame(await asyncio.wait_for(anext(iterator), 5))
            assert first["kind"] == "message.committed" and first["resource_ref"] == sent["message_handle"]
            live_projects = req.state.project_service
            live = CommunicationClientService(live_projects, TOKEN)
            authorization = live.event_current(PROJECT)["auth_revision"]
            with f.authority._connect() as connection:
                connection.execute("INSERT INTO scopes(scope_id,tenant_id,status) VALUES ('outside-event-project',%s,'active')", (f.authority.tenant_id,))
                connection.execute("UPDATE agent_slots SET scope_id='outside-event-project' WHERE tenant_id=%s AND agent_slot_id='slot-b'", (f.authority.tenant_id,))
                connection.execute("UPDATE delivery_endpoints SET scope_id='outside-event-project',revision=revision+1 "
                                   "WHERE tenant_id=%s AND endpoint_id='endpoint-b'", (f.authority.tenant_id,))
            assert live.event_current(PROJECT)["auth_revision"] == authorization
            control = decode_frame(await asyncio.wait_for(anext(iterator), 5))
            assert control["kind"] == "permission.changed" and control["resource_ref"] is None, control
            assert control["cursor"] == first["cursor"] and control["payload"]["reset_required"] is True
            assert "endpoint-b" not in json.dumps(control)
            with pytest.raises(StopAsyncIteration):
                await anext(iterator)

    asyncio.run(exercise())
    assert not any(driver.calls for driver in f.drivers.values())
