"""Durable subscription and PostgreSQL commit-order regressions."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import tempfile
import uuid

import psycopg
import pytest

from runtime.project_service import ProjectService
from runtime_tests.test_project_service import CATALOG, deadline, ok, send_args, work_args
from runtime_tests.test_project_service import project as project_fixture


@pytest.fixture
def continuation(setup):
    value = project_fixture.__wrapped__(setup)
    ok(value, "create_work", work_args())
    return value


def watch_args(*, identity="watch-1", kinds=None):
    return {"client_request_id": identity, "project_id": "project-alpha",
            "target_handles": ["project:project-alpha:existing-root"],
            "event_kinds": ["fixture.changed"] if kinds is None else kinds,
            "delivery_policy": "notify_current_session", "expected_revision": 0,
            "deadline": deadline()}


def insert_event(connection, identity):
    return connection.execute("INSERT INTO domain_events(tenant_id,target_kind,target_id,to_state,"
        "initiated_by,lineage_mode,command_id,resulting_revision,evidence_refs) VALUES "
        "('local-tenant','project','project-alpha','fixture.changed','fixture:commit-order',"
        "'external_command',%s,1,'[]') RETURNING event_id", (identity,)).fetchone()[0]


def test_watch_catches_late_lower_id_commit_and_deduplicates(continuation):
    f = continuation
    late = psycopg.connect(f.dsn)
    try:
        lower = insert_event(late, "late-" + uuid.uuid4().hex)
        watched = ok(f, "watch_changes", watch_args())
        with psycopg.connect(f.dsn) as early:
            higher = insert_event(early, "early-" + uuid.uuid4().hex)
        assert lower < higher
        first = ok(f, "check_inbox", {"project_id": "project-alpha"})
        assert [item["payload"]["event_id"] for item in first["data"]["notifications"]] == [higher]
        late.commit()
        both = ok(f, "check_inbox", {"project_id": "project-alpha"})
        assert {item["payload"]["event_id"] for item in both["data"]["notifications"]} == {lower, higher}
        again = ok(f, "check_inbox", {"project_id": "project-alpha"})
        assert again["data"]["notifications"] == both["data"]["notifications"]
        assert watched["data"]["revision"] == 1
    finally:
        late.close()


def test_pre_subscription_history_is_excluded_and_consumption_survives_reconnect(continuation):
    f = continuation
    with psycopg.connect(f.dsn) as connection:
        insert_event(connection, "before-watch")
    ok(f, "watch_changes", watch_args())
    assert ok(f, "check_inbox", {"project_id": "project-alpha"})["data"]["notifications"] == []
    with psycopg.connect(f.dsn) as connection:
        insert_event(connection, "after-watch")
    inbox = ok(f, "check_inbox", {"project_id": "project-alpha"})["data"]["notifications"]
    assert len(inbox) == 1
    handle = inbox[0]["notification_handle"]
    consumed = ok(f, "read_message", {"project_id": "project-alpha", "handle": handle})
    assert consumed["data"]["consumed"] is True
    rebuilt = ProjectService(f.projects.service, CATALOG, profile="root_manager")
    assert rebuilt.execute("check_inbox", {"project_id": "project-alpha"}, f.credential)[1]["notifications"] == []


def test_disabled_wake_keeps_durable_inbox_and_checks_subscription_revision(continuation):
    f = continuation
    watch = ok(f, "watch_changes", watch_args())["data"]
    changed = {"client_request_id": "disable-watch", "project_id": "project-alpha",
               "target_handle": watch["subscription_handle"], "enabled": False, "expected_revision": 1,
               "reason": "Inbox only", "deadline": deadline()}
    assert ok(f, "set_notification", changed)["data"]["revision"] == 2
    assert f.mcp.call("set_notification", dict(changed, client_request_id="stale-watch"))["structuredContent"]["data"]["code"] == "revision_conflict"
    with psycopg.connect(f.dsn) as connection:
        insert_event(connection, "disabled-wake")
    inbox = ok(f, "check_inbox", {"project_id": "project-alpha"})["data"]["notifications"]
    assert len(inbox) == 1 and inbox[0]["notification_enabled"] is False


def test_response_notification_control_keeps_tracking(continuation):
    f = continuation
    sent = ok(f, "send_message", send_args())["data"]
    ok(f, "set_notification", {"client_request_id": "disable-response", "project_id": "project-alpha",
        "target_handle": sent["response_handle"], "enabled": False, "expected_revision": 1,
        "reason": "wait explicitly", "deadline": deadline()})
    inbox = ok(f, "check_inbox", {"project_id": "project-alpha"})
    assert inbox["data"]["items"][0]["response_handle"] == sent["response_handle"]
    with psycopg.connect(f.dsn) as connection:
        assert connection.execute("SELECT enabled,revision FROM collaboration_response_subscriptions").fetchone() == (False, 2)


def test_pg_wake_signal_occurs_only_after_commit(continuation):
    f = continuation
    with psycopg.connect(f.dsn, autocommit=True) as listener, psycopg.connect(f.dsn) as writer:
        listener.execute("LISTEN acs_domain_change")
        schema = writer.execute("SELECT current_schema()").fetchone()[0]
        def scoped_notifications(timeout):
            # LISTEN channels are database-wide, not search_path-local. Other
            # tests/tenants may commit while this transaction is still open.
            return [notice for notice in listener.notifies(timeout=timeout)
                    if json.loads(notice.payload).get("schema") == schema]
        listener.execute("SELECT pg_notify('acs_domain_change',%s)",
                         (json.dumps({"schema": "unrelated-scope", "event_id": 1}),))
        event_id = insert_event(writer, "commit-wake")
        assert scoped_notifications(0.02) == []
        writer.commit()
        received = scoped_notifications(1)
        assert len(received) == 1
        assert json.loads(received[0].payload)["event_id"] == event_id
        insert_event(writer, "rollback-no-wake")
        writer.rollback()
        assert scoped_notifications(0.02) == []


def sdk_parameters(f, tmp_path):
    from mcp import StdioServerParameters

    from runtime_tests.test_project_service import ROOT
    from runtime_tests.test_surfaces import profile

    config, environment, _secret = profile(tmp_path, dsn=f.dsn, context=f.authority.context)
    return StdioServerParameters(command=sys.executable, args=["-m", "runtime.project_entry",
        "--config", str(config), "--catalog", str(ROOT / "docs/runtime/p2-mcp-tool-contract.json"),
        "--profile", "root_manager"], env=environment, cwd=str(ROOT))


def complete_response(f, message_id):
    response = {"text": "fixture completion"}
    response_digest = hashlib.sha256(json.dumps(
        response, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    with psycopg.connect(f.dsn) as connection:
        connection.execute("INSERT INTO delivery_receipts(tenant_id,message_id,receipt_id,layer,evidence_json) "
            "VALUES ('local-tenant',%s,%s,'response_received',%s) ON CONFLICT DO NOTHING",
            (message_id, "fixture-response:" + message_id, json.dumps({"source": "fixture-completion",
                "response_artifact_ref": "artifact:" + response_digest,
                "response_digest": response_digest})))
        connection.execute("UPDATE delivery_messages SET receipt_high_water='response_received',state='delivered' "
                           "WHERE message_id=%s", (message_id,))


def test_sdk_receives_proactive_completion_and_reconnect_recovers_inbox(continuation, tmp_path):
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    f = continuation
    sent = ok(f, "send_message", send_args())["data"]
    uri = "acs://projects/project-alpha/inbox"
    parameters = sdk_parameters(f, tmp_path)

    async def exercise():
        observed = []
        wake = asyncio.Event()
        async def receive(message):
            if getattr(message, "method", None) == "notifications/resources/updated":
                observed.append(str(message.params.uri))
                wake.set()
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
            async with (stdio_client(parameters, errlog=errors) as streams,
                        ClientSession(*streams, message_handler=receive, read_timeout_seconds=15) as session):
                initialized = await session.initialize()
                assert initialized.capabilities.resources.subscribe is True
                await session.subscribe_resource(uri)
                await asyncio.to_thread(complete_response, f, sent["message_id"])
                await asyncio.wait_for(wake.wait(), timeout=5)
                assert observed == [uri]
                await asyncio.sleep(0.7)
                assert observed == [uri]
                resource = await session.read_resource(uri)
                assert json.loads(resource.contents[0].text)["items"][0]["response_handle"] == sent["response_handle"]
            # New process and MCP Session, same durable owner and response handle.
            wake.clear()
            async with (stdio_client(parameters, errlog=errors) as streams,
                        ClientSession(*streams, message_handler=receive, read_timeout_seconds=15) as replacement):
                await replacement.initialize()
                await replacement.subscribe_resource(uri)
                await asyncio.wait_for(wake.wait(), timeout=5)
                inbox = await replacement.read_resource(uri)
                assert json.loads(inbox.contents[0].text)["items"][0]["response_handle"] == sent["response_handle"]
        assert observed == [uri, uri]

    asyncio.run(exercise())
    with psycopg.connect(f.dsn) as connection:
        states = connection.execute("SELECT state FROM collaboration_notification_sessions ORDER BY revision").fetchall()
    assert states == [("retired",), ("active",)]


def test_superseded_sdk_session_cannot_reclaim_notification_delivery(continuation, tmp_path):
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    f = continuation
    sent = ok(f, "send_message", send_args())["data"]
    uri = "acs://projects/project-alpha/inbox"
    parameters = sdk_parameters(f, tmp_path)

    async def exercise():
        old_messages, new_messages = [], []
        wake = asyncio.Event()
        async def old_receive(message):
            if getattr(message, "method", None) == "notifications/resources/updated":
                old_messages.append(message)
        async def new_receive(message):
            if getattr(message, "method", None) == "notifications/resources/updated":
                new_messages.append(message)
                wake.set()
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
            async with (stdio_client(parameters, errlog=errors) as a,
                        ClientSession(*a, message_handler=old_receive, read_timeout_seconds=15) as old,
                        stdio_client(parameters, errlog=errors) as b,
                        ClientSession(*b, message_handler=new_receive, read_timeout_seconds=15) as new):
                await old.initialize()
                await new.initialize()
                await old.subscribe_resource(uri)
                await new.subscribe_resource(uri)
                await asyncio.to_thread(complete_response, f, sent["message_id"])
                await asyncio.wait_for(wake.wait(), timeout=5)
                await asyncio.sleep(0.7)
                assert not old_messages and len(new_messages) == 1
                with pytest.raises(Exception, match="Session subscription unavailable"):
                    await old.subscribe_resource(uri)

    asyncio.run(exercise())


@pytest.mark.parametrize("completed_before_listen", [False, True])
def test_modern_sdk_listen_delivers_live_and_recovered_completion(continuation, tmp_path, completed_before_listen):
    from mcp import Client
    from mcp.shared.subscriptions import ResourceUpdated

    f = continuation
    sent = ok(f, "send_message", send_args())["data"]
    uri = "acs://projects/project-alpha/inbox"
    parameters = sdk_parameters(f, tmp_path)
    if completed_before_listen:
        complete_response(f, sent["message_id"])

    async def exercise():
        async with (Client(parameters, mode="2026-07-28", read_timeout_seconds=10, cache=None) as client,
                    client.listen(resource_subscriptions=[uri]) as subscription):
            assert subscription.honored.resource_subscriptions == [uri]
            if not completed_before_listen:
                await asyncio.to_thread(complete_response, f, sent["message_id"])
            event = await asyncio.wait_for(anext(subscription), timeout=5)
            assert isinstance(event, ResourceUpdated) and event.uri == uri
            resource = await client.read_resource(uri)
            assert json.loads(resource.contents[0].text)["items"][0]["response_handle"] == sent["response_handle"]

    asyncio.run(exercise())
