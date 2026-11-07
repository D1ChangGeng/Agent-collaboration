"""Actor-scoped MCP hints on isolated PG; publication is not message consumption."""
from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import replace

import httpx
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from runtime.auth import LocalCredentialAuthenticator
from runtime.communication_notifications import (
    adopt_notification_frontiers,
    advance_publication_boundary,
    due_publication_keys,
    publication_boundary,
    publish_wake_hint,
    verify_notification_frontiers,
)
from runtime.domain import DomainAuthority
from runtime.errors import AuthorizationDenied, SchemaAdoptionError
from runtime.mcp_runtime import McpRuntime
from runtime.project_service import ProjectService
from runtime.surfaces import SharedService
from runtime_tests.test_communication import CATALOG, call, send
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_identity_root_management import owner_client as owner_client_fixture
from runtime_tests.test_project_http import IssuerFixture, claims, listener, settings

comm = comm_fixture
owner_client = owner_client_fixture
PROJECT = "project-alpha"


def project_client(comm, name="b"):
    client = comm.clients[name]
    return client.service, client.credential_provider()


def enable(comm):
    with comm.authority._connect() as connection:
        adopt_notification_frontiers(connection)
    for client in comm.clients.values():
        client.service.service.authority._notification_frontiers_enabled = True


def bind(comm, name="b", session="session", connection="connection"):
    projects, credential = project_client(comm, name)
    return projects.bind_notification_session(PROJECT, session, connection, credential)


def pending(comm, name="b", session="session", connection="connection"):
    projects, credential = project_client(comm, name)
    return projects.pending_wake_keys(PROJECT, session, connection, credential)


def acknowledge(comm, keys, name="b", session="session", connection="connection"):
    projects, credential = project_client(comm, name)
    return projects.acknowledge_wake_publication(PROJECT, session, connection, keys, credential)


def frontier(comm, session="session"):
    with comm.authority._connect() as connection:
        return connection.execute("SELECT message_sequence,notice_sequence FROM communication_notification_frontiers "
            "WHERE session_ref=%s ORDER BY binding_revision DESC LIMIT 1", (session,)).fetchone()


@pytest.mark.parametrize("keys", [["message:1", "message:2"], ["other:1"], ["message:0"],
    ["message:-1"], ["message:１２"], ["notice:9223372036854775808"], "message:1", [1],
    ["message:1", "notice:1", "notice:2"]])
def test_publication_keys_are_bounded_and_typed(keys):
    with pytest.raises(ValueError):
        publication_boundary(keys)


def test_hint_memory_keeps_only_two_monotonic_frontiers():
    seen = {}
    for sequence in range(1, 1001):
        keys = [f"message:{sequence}", f"notice:{sequence * 2}"]
        assert due_publication_keys(keys, seen) == keys
        seen = advance_publication_boundary(seen, keys)
        assert len(seen) == 2
    assert seen == {"message": 1000, "notice": 2000}
    assert due_publication_keys(["message:999", "notice:1999"], seen) == []


def test_optional_frontier_storage_requires_explicit_idempotent_adoption(comm):
    with comm.authority._connect() as connection:
        with pytest.raises(SchemaAdoptionError):
            verify_notification_frontiers(connection)
        assert connection.execute("SELECT to_regclass('communication_notification_frontiers')").fetchone() == (None,)
        adopt_notification_frontiers(connection)
        verify_notification_frontiers(connection)
        adopt_notification_frontiers(connection)
        verify_notification_frontiers(connection)


def shared_principal_clients(comm):
    call(comm, "a", "configure_team", prepare_native=False, members=[
        {"agent_slot_id": "shared-slot-1", "principal_ref": "agent:shared"},
        {"agent_slot_id": "shared-slot-2", "principal_ref": "agent:shared"}])
    for number in (1, 2):
        slot = f"shared-slot-{number}"
        with comm.authority._connect() as connection:
            grant = connection.execute("SELECT grant_ref FROM collaboration_team_members WHERE agent_slot_id=%s", (slot,)).fetchone()[0]
        token = "synthetic-notification-" + uuid.uuid4().hex
        context = replace(comm.authority.context, principal_ref="agent:shared", grant_ref=grant,
            agent_slot_id=slot, credential_hash=hashlib.sha256(token.encode()).hexdigest())
        authority = DomainAuthority(comm.dsn, context=context)
        projects = ProjectService(SharedService(authority, LocalCredentialAuthenticator(context)), CATALOG, profile="engineer")
        comm.clients[f"shared-{number}"] = McpRuntime(projects, lambda value=token: value)


def test_same_principal_slots_do_not_retire_or_observe_each_others_subscriptions(comm):
    shared_principal_clients(comm)
    enable(comm)
    for number in (1, 2):
        call(comm, "a", "send_message", to=f"collaborator:{PROJECT}:shared-slot-{number}",
             content=f"Private notification target {number}", activation="message_only")
        bind(comm, f"shared-{number}", session="same-session", connection="same-connection")
    first = pending(comm, "shared-1", "same-session", "same-connection")
    second = pending(comm, "shared-2", "same-session", "same-connection")
    assert len(first) == len(second) == 1 and first != second
    with comm.authority._connect() as connection:
        rows = connection.execute("SELECT owner_ref,state FROM collaboration_notification_sessions ORDER BY owner_ref").fetchall()
    assert len(rows) == 2 and len({row[0] for row in rows}) == 2
    assert all(row[1] == "active" for row in rows)
    with pytest.raises(AuthorizationDenied):
        acknowledge(comm, second, "shared-1", "same-session", "same-connection")
    assert frontier(comm, "same-session") is None


def test_trusted_client_and_bound_slot_share_no_synthetic_notification_owner(comm, owner_client):
    projects, credential = project_client(comm, "a")
    projects.bind_notification_session(PROJECT, "slot-session", "slot-connection", credential)
    owner_client.service.bind_notification_session(PROJECT, "client-session", "client-connection",
                                                  owner_client.credential_provider())
    with comm.authority._connect() as connection:
        owners = connection.execute("SELECT owner_ref,state FROM collaboration_notification_sessions").fetchall()
        slots = connection.execute("SELECT count(*) FROM agent_slots").fetchone()[0]
    assert len({row[0] for row in owners}) == 2 and all(row[1] == "active" for row in owners)
    assert slots == 3 and owner_client.service.context.agent_slot_id is None


def test_matching_shared_connection_renews_expired_lease_but_wrong_or_retired_cannot(comm):
    bind(comm)
    sent = send(comm, "a", "b", "Still queued after the observation lease", activation="message_only")["data"]
    with comm.authority._connect() as connection:
        connection.execute("UPDATE collaboration_notification_sessions SET expires_at=clock_timestamp()-interval '1 day'")
    assert pending(comm, connection="wrong-connection") == []
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT expires_at<clock_timestamp() FROM collaboration_notification_sessions").fetchone() == (True,)
    assert pending(comm) == ["message:" + str(sent["sequence"])]
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT expires_at>clock_timestamp() FROM collaboration_notification_sessions").fetchone() == (True,)
    bind(comm, session="replacement", connection="replacement-connection")
    assert pending(comm) == []
    assert acknowledge(comm, ["message:" + str(sent["sequence"])]) is False
    assert pending(comm, session="replacement", connection="replacement-connection")
    with pytest.raises(AuthorizationDenied):
        bind(comm)


def test_revoked_caller_cannot_renew_publish_or_observe_a_session(comm):
    bind(comm)
    send(comm, "a", "b", "Message stays private after revoke", activation="message_only")
    with comm.authority._connect() as connection:
        connection.execute("UPDATE collaboration_notification_sessions SET expires_at=clock_timestamp()-interval '1 day'")
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                           (comm.clients["b"].service.context.grant_ref,))
    with pytest.raises(AuthorizationDenied):
        pending(comm)
    with pytest.raises(AuthorizationDenied):
        acknowledge(comm, [])
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT expires_at<clock_timestamp() FROM collaboration_notification_sessions").fetchone() == (True,)


def test_failed_publication_retains_frontier_and_burst_preserves_complete_history(comm):
    enable(comm)
    bind(comm)
    sent = [send(comm, "a", "b", f"Burst message {number}", activation="message_only")["data"] for number in range(20)]
    keys = pending(comm)
    assert keys == ["message:" + str(sent[-1]["sequence"])]
    projects, credential = project_client(comm)
    seen = {}
    publications = []

    async def fail():
        raise OSError("synthetic transport failure before publication")

    with pytest.raises(OSError):
        asyncio.run(publish_wake_hint(projects, PROJECT, "session", "connection", credential, keys, seen, fail))
    assert seen == {} and frontier(comm) is None and pending(comm) == keys

    async def publish():
        publications.append("resource-hint")

    seen = asyncio.run(publish_wake_hint(projects, PROJECT, "session", "connection", credential, keys, seen, publish))
    assert publications == ["resource-hint"] and len(seen) == 2
    assert pending(comm) == [] and frontier(comm) == (sent[-1]["sequence"], 0)
    history = call(comm, "b", "check_inbox", limit=100)["data"]["items"]
    assert len(history) == 20 and {item["message_handle"] for item in history} == {item["message_handle"] for item in sent}
    assert all(driver.calls == [] for driver in comm.drivers.values())


def test_publication_ack_uses_its_original_boundary_and_never_skips_concurrent_arrival(comm):
    enable(comm)
    bind(comm)
    first = send(comm, "a", "b", "First boundary", activation="message_only")["data"]
    keys = pending(comm)
    projects, credential = project_client(comm)
    later = []

    async def publish():
        later.append(send(comm, "a", "b", "Committed during publication", activation="message_only")["data"])

    seen = asyncio.run(publish_wake_hint(projects, PROJECT, "session", "connection", credential, keys, {}, publish))
    assert seen["message"] == first["sequence"]
    assert pending(comm) == ["message:" + str(later[0]["sequence"])]
    assert acknowledge(comm, keys)
    assert frontier(comm) == (first["sequence"], 0)
    bind(comm, session="new-session", connection="new-connection")
    assert pending(comm, session="new-session", connection="new-connection") == ["message:" + str(later[0]["sequence"])]


def test_message_and_notice_hint_frontiers_advance_independently(comm):
    enable(comm)
    bind(comm)
    sent = send(comm, "a", "b", "Message with an independent notice", activation="message_only")["data"]
    with comm.authority._connect() as connection:
        notice = connection.execute("INSERT INTO communication_notices(tenant_id,project_id,message_id,recipient,state,code) "
            "VALUES (%s,%s,%s,%s,'open','synthetic-obstacle') RETURNING sequence",
            (comm.authority.tenant_id, PROJECT, sent["message_id"], "collaborator:project-alpha:slot-b")).fetchone()[0]
    assert pending(comm) == ["message:" + str(sent["sequence"]), "notice:" + str(notice)]
    assert acknowledge(comm, ["message:" + str(sent["sequence"])])
    assert pending(comm) == ["notice:" + str(notice)]
    assert acknowledge(comm, ["notice:" + str(notice)])
    assert pending(comm) == [] and frontier(comm) == (sent["sequence"], notice)


def test_publication_ack_failure_after_send_is_replayable_without_skipping(comm, monkeypatch):
    from runtime import communication_notifications as notifications

    enable(comm)
    bind(comm)
    send(comm, "a", "b", "Committed but publication receipt is unavailable", activation="message_only")
    keys = pending(comm)
    projects, credential = project_client(comm)
    seen, sent = {}, []
    original = notifications.record_publication_boundary

    async def publish():
        sent.append("hint")

    def unavailable(*_args):
        raise OSError("synthetic post-publication database fault")

    monkeypatch.setattr(notifications, "record_publication_boundary", unavailable)
    with pytest.raises(OSError):
        asyncio.run(publish_wake_hint(projects, PROJECT, "session", "connection", credential, keys, seen, publish))
    assert seen == {} and frontier(comm) is None and pending(comm) == keys
    monkeypatch.setattr(notifications, "record_publication_boundary", original)
    assert asyncio.run(publish_wake_hint(projects, PROJECT, "session", "connection", credential, keys, seen, publish))
    assert sent == ["hint", "hint"] and pending(comm) == []


@pytest.mark.parametrize("change", ["replaced", "revoked"])
def test_stale_polled_keys_are_reauthorized_before_transport_publication(comm, change):
    enable(comm)
    bind(comm)
    send(comm, "a", "b", "Hint must not escape after binding change", activation="message_only")
    keys = pending(comm)
    projects, credential = project_client(comm)
    if change == "replaced":
        bind(comm, session="replacement", connection="replacement")
    else:
        with comm.authority._connect() as connection:
            connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (projects.context.grant_ref,))
    sent = []

    async def emit():
        sent.append(True)

    with pytest.raises((RuntimeError, AuthorizationDenied)):
        asyncio.run(publish_wake_hint(projects, PROJECT, "session", "connection", credential, keys, {}, emit))
    assert sent == [] and frontier(comm) is None


def test_default_schema_remains_usable_without_frontier_table(comm):
    bind(comm)
    send(comm, "a", "b", "Legacy schema hint", activation="message_only")
    keys = pending(comm)
    assert acknowledge(comm, keys) and pending(comm) == keys
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT to_regclass('communication_notification_frontiers')").fetchone() == (None,)


def test_real_modern_mcp_hint_records_publication_without_consuming_messages(comm, monkeypatch):
    enable(comm)
    sent = send(comm, "b", "a", "Actual MCP hint for authoritative history", activation="message_only")["data"]
    config = settings(monkeypatch, comm.authority.context)
    issuer = IssuerFixture({"notification-reader": claims()})
    uri = "acs://projects/project-alpha/inbox"

    async def exercise(url):
        async with (httpx.AsyncClient(headers={"Authorization": "Bearer notification-reader"}, trust_env=False) as http,
                    Client(streamable_http_client(url + "/mcp", http_client=http), mode="2026-07-28",
                           read_timeout_seconds=10, cache=None) as client,
                    client.listen(resource_subscriptions=[uri]) as subscription):
            event = await asyncio.wait_for(anext(subscription), timeout=8)
            assert event.uri == uri
            response = await client.read_resource(uri)
            assert sent["message_handle"] in {item["message_handle"] for item in json.loads(response.contents[0].text)["items"]}
            for _ in range(40):
                with comm.authority._connect() as connection:
                    published = connection.execute("SELECT max(message_sequence) FROM communication_notification_frontiers").fetchone()[0]
                if published == sent["sequence"]:
                    break
                await asyncio.sleep(0.05)
            assert published == sent["sequence"]
    with listener(comm.clients["a"].service.service, config, issuer) as (url, _server):
        asyncio.run(exercise(url))
    assert len(call(comm, "a", "check_inbox")["data"]["items"]) == 1
    assert all(driver.calls == [] for driver in comm.drivers.values())
