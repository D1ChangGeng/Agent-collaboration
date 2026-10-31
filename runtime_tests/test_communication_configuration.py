"""Concurrent public configuration on real PG; Native preparation is a labeled fixture."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Event

from runtime.auth import LocalCredentialAuthenticator
from runtime.delivery_models import EndpointBindingRequest
from runtime.delivery_node import LocalNodeEndpoint
from runtime.domain import DomainAuthority
from runtime.mcp_runtime import McpRuntime
from runtime.node import NodeJournal
from runtime.project_service import ProjectService
from runtime.surfaces import SharedService
from runtime_tests.test_communication import AcceptingDriver, call
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_delivery import command

comm = comm_fixture


def independent_manager(comm, *, owner=False, bound=False):
    original = comm.clients["a"]
    context = (
        replace(original.service.context, agent_slot_id="local-slot")
        if bound
        else original.service.context
    )
    authority = DomainAuthority(
        comm.dsn, context=context, access_mode="owner" if owner else "shared"
    )
    authority._delivery_endpoints = comm.authority._delivery_endpoints
    service = ProjectService(
        SharedService(authority, LocalCredentialAuthenticator(authority.context)),
        original.service.catalog,
        profile="root_manager",
    )
    return McpRuntime(service, original.credential_provider)


def receivers(comm, tmp_path):
    calls = []
    first = comm.authority._delivery_endpoints["endpoint-b"]
    first.driver.prepare_runtime = lambda: (
        calls.append("endpoint-b")
        or {
            "state": "idle",
            "session_ref": "fixture-session-first",
            "observation": "native_driver_readback",
        }
    )
    second = LocalNodeEndpoint(
        NodeJournal(tmp_path / "second.sqlite"), "local-scope", "slot-b", AcceptingDriver()
    )
    second.driver.prepare_runtime = lambda: (
        calls.append("endpoint-second")
        or {
            "state": "idle",
            "session_ref": "fixture-session-second",
            "observation": "native_driver_readback",
        }
    )
    comm.authority._delivery_endpoints["endpoint-second"] = second
    comm.dispatcher.service.endpoints["endpoint-second"] = second
    comm.dispatcher.service.bind_endpoint(
        command(comm.authority, "message.bind", "endpoint-second"),
        EndpointBindingRequest(
            scope_id="local-scope",
            agent_slot_id="slot-b",
            expires_at=comm.authority.canonical_now() + timedelta(minutes=5),
        ),
    )
    return calls


def paused_preparation(comm, monkeypatch):
    committed, release = Event(), Event()
    original = comm.clients["a"].service._prepare_communication_sessions

    def paused(result, args, credential):
        committed.set()
        assert release.wait(8), "test must release committed preparation"
        return original(result, args, credential)

    monkeypatch.setattr(comm.clients["a"].service, "_prepare_communication_sessions", paused)
    return committed, release


def test_later_receiver_change_cannot_prepare_a_different_target_for_an_older_call(
    comm, tmp_path, monkeypatch
):
    preparations = receivers(comm, tmp_path)
    other = independent_manager(comm)
    committed, release = paused_preparation(comm, monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(
            call,
            comm,
            "a",
            "configure_team",
            members=[
                {"agent_slot_id": "slot-b", "principal_ref": "agent:b", "endpoint_id": "endpoint-b"}
            ],
        )
        try:
            assert committed.wait(6)
            changed = other.call(
                "configure_team",
                {
                    "project_id": "project-alpha",
                    "prepare_native": False,
                    "members": [
                        {
                            "agent_slot_id": "slot-b",
                            "endpoint_id": "endpoint-second",
                            "if_unchanged": {"endpoint_id": "endpoint-b"},
                        }
                    ],
                },
            )["structuredContent"]
            assert changed["ok"], changed
        finally:
            release.set()
        observed = first.result(timeout=10)["data"]["native_sessions"][0]
    assert observed["state"] == "configuration_changed", observed
    assert observed["session_ref"] is None
    assert preparations == [], "neither receiver was authorized for this stale preparation"


def test_unrelated_property_change_merges_without_invalidating_receiver_preparation(
    comm, tmp_path, monkeypatch
):
    preparations = receivers(comm, tmp_path)
    other = independent_manager(comm)
    committed, release = paused_preparation(comm, monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(
            call,
            comm,
            "a",
            "configure_team",
            members=[
                {
                    "agent_slot_id": "slot-b",
                    "principal_ref": "agent:b",
                    "endpoint_id": "endpoint-b",
                    "display_name": "Initial",
                }
            ],
        )
        try:
            assert committed.wait(6)
            changed = other.call(
                "configure_team",
                {
                    "project_id": "project-alpha",
                    "prepare_native": False,
                    "members": [
                        {
                            "agent_slot_id": "slot-b",
                            "display_name": "Later name",
                            "if_unchanged": {"display_name": "Initial"},
                        }
                    ],
                },
            )["structuredContent"]
            assert changed["ok"], changed
        finally:
            release.set()
        observed = first.result(timeout=10)["data"]["native_sessions"][0]
    assert observed["state"] == "native_observed", observed
    assert observed["session_ref"] == "fixture-session-first" and preparations == ["endpoint-b"]
    contacts = call(comm, "a", "list_collaborators")["data"]["items"]
    assert (
        next(item for item in contacts if item["agent_slot_id"] == "slot-b")["display_name"]
        == "Later name"
    )


def test_concurrent_disjoint_property_edits_merge_without_a_global_revision(comm):
    call(
        comm,
        "a",
        "configure_team",
        prepare_native=False,
        members=[
            {
                "agent_slot_id": "slot-b",
                "principal_ref": "agent:b",
                "display_name": "Initial",
                "harness_requirements": [],
            },
            {"agent_slot_id": "slot-c", "principal_ref": "agent:c", "display_name": "Keep C"},
        ],
    )
    other = independent_manager(comm)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            call,
            comm,
            "a",
            "configure_team",
            prepare_native=False,
            members=[
                {
                    "agent_slot_id": "slot-b",
                    "display_name": "Changed",
                    "if_unchanged": {"display_name": "Initial"},
                }
            ],
        )
        second = pool.submit(
            other.call,
            "configure_team",
            {
                "project_id": "project-alpha",
                "prepare_native": False,
                "members": [
                    {
                        "agent_slot_id": "slot-b",
                        "harness_requirements": ["codex"],
                        "if_unchanged": {"harness_requirements": []},
                    }
                ],
            },
        )
        assert first.result(timeout=10)["ok"]
        assert second.result(timeout=10)["structuredContent"]["ok"]
    with comm.authority._connect() as connection:
        saved = connection.execute(
            "SELECT definition FROM collaboration_teams WHERE project_id='project-alpha'"
        ).fetchone()[0]
    members = {member["agent_slot_id"]: member for member in saved["members"]}
    assert members["slot-b"]["display_name"] == "Changed" and members["slot-b"][
        "harness_requirements"
    ] == ["codex"]
    assert members["slot-c"]["display_name"] == "Keep C"


def test_concurrent_same_property_expectation_rejects_one_without_overwriting(comm):
    call(
        comm,
        "a",
        "configure_team",
        prepare_native=False,
        members=[
            {"agent_slot_id": "slot-b", "principal_ref": "agent:b", "display_name": "Initial"}
        ],
    )
    other = independent_manager(comm)

    def update(client, name):
        return client.call(
            "configure_team",
            {
                "project_id": "project-alpha",
                "prepare_native": False,
                "members": [
                    {
                        "agent_slot_id": "slot-b",
                        "display_name": name,
                        "if_unchanged": {"display_name": "Initial"},
                    }
                ],
            },
        )["structuredContent"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(update, client, name)
            for client, name in ((comm.clients["a"], "First"), (other, "Second"))
        ]
        results = [future.result(timeout=10) for future in futures]
    assert sum(result["ok"] for result in results) == 1
    assert (
        next(result for result in results if not result["ok"])["data"]["code"]
        == "revision_conflict"
    )
    contacts = call(comm, "a", "list_collaborators")["data"]["items"]
    winner = "First" if results[0]["ok"] else "Second"
    assert (
        next(item for item in contacts if item["agent_slot_id"] == "slot-b")["display_name"]
        == winner
    )


def test_binding_revision_change_invalidates_a_preparation_snapshot(comm, tmp_path, monkeypatch):
    preparations = receivers(comm, tmp_path)
    committed, release = paused_preparation(comm, monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(
            call,
            comm,
            "a",
            "configure_team",
            members=[
                {"agent_slot_id": "slot-b", "principal_ref": "agent:b", "endpoint_id": "endpoint-b"}
            ],
        )
        try:
            assert committed.wait(6)
            comm.dispatcher.service.bind_endpoint(
                command(comm.authority, "message.bind", "endpoint-b", 1),
                EndpointBindingRequest(
                    scope_id="local-scope",
                    agent_slot_id="slot-b",
                    expires_at=comm.authority.canonical_now() + timedelta(minutes=5),
                ),
            )
        finally:
            release.set()
        observed = first.result(timeout=10)["data"]["native_sessions"][0]
    assert observed["state"] == "configuration_changed" and observed["session_ref"] is None
    assert observed["binding_revision"] == 1 and preparations == []


def test_change_during_preparation_does_not_present_the_old_session_as_current(comm, tmp_path):
    preparations = receivers(comm, tmp_path)
    comm.clients["a"] = independent_manager(comm, owner=True, bound=True)
    other = independent_manager(comm, owner=True, bound=True)
    entered, release = Event(), Event()
    endpoint = comm.authority._delivery_endpoints["endpoint-b"]
    original = endpoint.driver.prepare_runtime

    def held():
        entered.set()
        assert release.wait(8), "test must release actual fixture preparation"
        return original()

    endpoint.driver.prepare_runtime = held
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(
            call,
            comm,
            "a",
            "configure_team",
            members=[
                {"agent_slot_id": "slot-b", "principal_ref": "agent:b", "endpoint_id": "endpoint-b"}
            ],
        )
        try:
            assert entered.wait(6)
            changed = other.call(
                "configure_team",
                {
                    "project_id": "project-alpha",
                    "prepare_native": False,
                    "members": [
                        {
                            "agent_slot_id": "slot-b",
                            "endpoint_id": "endpoint-second",
                            "if_unchanged": {"endpoint_id": "endpoint-b"},
                        }
                    ],
                },
            )["structuredContent"]
            assert changed["ok"], changed
        finally:
            release.set()
        observed = first.result(timeout=10)["data"]["native_sessions"][0]
    assert observed["state"] == "configuration_changed" and observed["session_ref"] is None
    assert preparations == ["endpoint-b"]
    assert observed["preparation_observation"]["session_ref"] == "fixture-session-first"
