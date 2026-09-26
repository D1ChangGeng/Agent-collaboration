"""Distinct Route Scope/Grant and narrow-member isolation on PostgreSQL."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from runtime.mcp_runtime import McpRuntime
from runtime.project_service import ProjectService
from runtime_tests.test_project_management import managed as managed_fixture
from runtime_tests.test_project_management import team_args, worker_client
from runtime_tests.test_project_service import CATALOG, deadline, ok, scalar, work_args


@pytest.fixture
def routed(setup, tmp_path):
    return managed_fixture.__wrapped__(setup, tmp_path)


def route_args(route="next-route", revision=1):
    return {"client_request_id": "create-" + route, "project_id": "project-alpha",
        "root_handle": "project:project-alpha:existing-root", "expected_root_revision": revision,
        "route_id": route, "display_name": route, "goal": "independent durable development Scope",
        "source_binding_ids": [], "deadline": deadline()}


def work_for(route="next-route", work="new-work"):
    return dict(work_args("create-" + work), route_handle="route:project-alpha:" + route, work_item_id=work)


def test_route_creates_distinct_scope_and_delegated_authority_atomically(routed):
    f = routed
    args = route_args()
    created = ok(f, "create_route", args)["data"]
    assert created["root_revision"] == 2 and created["revision"] == 1
    assert created["scope_handle"] != "scope:project-alpha:local-scope"
    scope = created["scope_handle"].split(":")[-1]
    with psycopg.connect(f.dsn) as connection:
        grant, slot, parent = connection.execute("SELECT g.grant_ref,g.agent_slot_id,d.parent_grant_ref "
            "FROM collaboration_route_grants g JOIN grant_delegations d USING(grant_ref)").fetchone()
        assert parent == "grant:p1" and slot != "local-slot"
        assert connection.execute("SELECT scope_id FROM grants WHERE grant_ref=%s", (grant,)).fetchone() == (scope,)
        assert connection.execute("SELECT scope_id FROM agent_slots WHERE agent_slot_id=%s", (slot,)).fetchone() == (scope,)
    assert ok(f, "create_route", args)["data"] == created
    assert scalar(f, "SELECT count(*) FROM collaboration_route_grants") == 1
    work = ok(f, "create_work", work_for())["data"]
    assert work["revision"] == 0
    with psycopg.connect(f.dsn) as connection:
        assert connection.execute("SELECT scope_id,agent_slot_id FROM work_items WHERE work_item_id='new-work'").fetchone() == (scope, slot)
    changed = f.mcp.call("create_route", dict(args, goal="different"))
    assert changed["structuredContent"]["data"]["code"] == "idempotency_conflict"


def test_route_creation_rolls_back_scope_slot_grant_on_failed_projection(routed):
    f = routed
    with psycopg.connect(f.dsn) as connection:
        before = {name: connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
                  for name in ("scopes", "agent_slots", "grants", "grant_delegations", "operations")}
        connection.execute("ALTER TABLE collaboration_route_grants ADD CONSTRAINT injected_failure CHECK (profile='impossible')")
    assert f.mcp.call("create_route", route_args())["isError"]
    with psycopg.connect(f.dsn) as connection:
        assert {name: connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in before} == before
        assert connection.execute("SELECT revision FROM collaboration_projects").fetchone() == (1,)


def test_concurrent_route_replay_does_not_create_extra_scopes(routed):
    f = routed
    args = route_args()
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: f.mcp.call("create_route", args), range(3)))
    assert all(not result["isError"] for result in results), results
    assert len({result["structuredContent"]["data"]["scope_handle"] for result in results}) == 1
    assert scalar(f, "SELECT count(*) FROM collaboration_route_grants") == 1


def test_route_lifecycle_is_versioned_metadata_and_blocks_new_work(routed):
    f = routed
    created = ok(f, "create_route", route_args())["data"]
    update = {"client_request_id": "pause-route", "project_id": "project-alpha",
        "route_handle": created["route_handle"], "expected_revision": 1,
        "changes": {"state": "paused", "display_name": "Paused line"},
        "reason": "explicit management decision", "deadline": deadline()}
    changed = ok(f, "update_route", update)["data"]
    assert changed["revision"] == 2 and changed["scope_handle"] == created["scope_handle"]
    assert ok(f, "update_route", update)["data"] == changed
    assert f.mcp.call("create_work", dict(work_for(), expected_route_revision=2))["isError"]
    assert f.mcp.call("update_route", dict(update, client_request_id="stale"))["structuredContent"]["data"]["code"] == "revision_conflict"
    assert f.mcp.call("update_route", dict(update, client_request_id="move", expected_revision=2,
                                          changes={"scope_id": "local-scope"}))["isError"]
    ok(f, "update_route", dict(update, client_request_id="resume", expected_revision=2, changes={"state": "active"}))
    ok(f, "create_work", dict(work_for(), expected_route_revision=3))


def test_parent_revocation_or_policy_change_invalidates_route_grants(routed):
    f = routed
    ok(f, "create_route", route_args())
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE scopes SET policy=policy || '{\"new_boundary\":true}'::jsonb WHERE scope_id='local-scope'")
    assert f.mcp.call("create_work", work_for())["structuredContent"]["data"]["code"] == "authorization_denied"
    assert scalar(f, "SELECT count(*) FROM work_items WHERE work_item_id='new-work'") == 0


def test_route_and_work_pages_apply_named_filters(routed):
    f = routed
    ok(f, "create_route", route_args())
    ok(f, "create_work", work_args())
    ok(f, "create_work", work_for(work="a-work"))
    ok(f, "create_work", work_for(work="z-work"))
    first = ok(f, "list_routes", {"project_id": "project-alpha", "limit": 1})["data"]
    assert len(first["items"]) == 1 and first["next_cursor"]
    second = ok(f, "list_routes", {"project_id": "project-alpha", "limit": 1, "cursor": first["next_cursor"]})["data"]
    assert second["items"][0]["route_handle"] != first["items"][0]["route_handle"]
    args = {"project_id": "project-alpha", "route_handle": "route:project-alpha:next-route", "limit": 1}
    page = ok(f, "list_work", args)["data"]
    assert [item["work_handle"] for item in page["items"]] == ["work:project-alpha:a-work"]
    page = ok(f, "list_work", dict(args, cursor=page["next_cursor"]))["data"]
    assert [item["work_handle"] for item in page["items"]] == ["work:project-alpha:z-work"]
    assert not ok(f, "list_work", dict(args, assigned_to="local-slot"))["data"]["items"]
    assert not ok(f, "list_work", dict(args, states=["accepted"]))["data"]["items"]
    assert not ok(f, "list_work", dict(args, blocked=True))["data"]["items"]
    assert not ok(f, "list_work", dict(args, updated_since="2099-01-01T00:00:00+00:00"))["data"]["items"]
    assert f.mcp.call("list_work", dict(args, updated_since="2026-01-01"))["isError"]


def prepare_worker(f):
    ok(f, "create_work", work_args())
    created = ok(f, "create_route", route_args())["data"]
    ok(f, "create_route", route_args("sibling-route", revision=2))
    ok(f, "create_work", work_for())
    ok(f, "create_work", work_for("sibling-route", "sibling-work"))
    team = dict(team_args(), scope_handle=created["scope_handle"])
    team["members"][0].update(profile="route_manager", role="route")
    team["members"][0]["permissions"].extend([
        "routes.read", "resources.read", "reviews.read", "activity.read", "subscriptions.manage",
        "collaborators.read", "work.manage", "work_item.create", "changes.read", "profile.route_manager"])
    # Profile/permission selection is an explicit test operator fixture.
    with psycopg.connect(f.dsn) as connection:
        for grant in ("grant:p1",):
            connection.execute("UPDATE grants SET permissions=permissions || %s::jsonb WHERE grant_ref=%s",
                               (json.dumps(team["members"][0]["permissions"]), grant))
        connection.execute("UPDATE grants SET permissions=permissions || %s::jsonb WHERE grant_ref IN "
                           "(SELECT grant_ref FROM collaboration_route_grants)",
                           (json.dumps(team["members"][0]["permissions"]),))
    ok(f, "configure_team", team)
    mcp, authority = worker_client(f)
    mcp = McpRuntime(ProjectService(mcp.service.service, CATALOG, profile="route_manager"), mcp.credential_provider)
    return mcp, authority, created


def test_route_member_cannot_read_sibling_scope_or_watch_whole_project(routed):
    f = routed
    client, _, created = prepare_worker(f)
    def call(name, args):
        value = client.call(name, args)
        assert not value["isError"], value
        return value["structuredContent"]["data"]
    routes = call("list_routes", {"project_id": "project-alpha"})
    assert [item["route_handle"] for item in routes["items"]] == [created["route_handle"]]
    works = call("list_work", {"project_id": "project-alpha"})
    assert [item["work_handle"] for item in works["items"]] == ["work:project-alpha:new-work"]
    for resource in ("work:project-alpha:mcp-work", "work:project-alpha:sibling-work", "route:project-alpha:sibling-route"):
        denied = client.call("read_resource", {"project_id": "project-alpha", "handle": resource})
        assert denied["structuredContent"]["data"]["code"] == "authorization_denied", denied
    own = call("read_resource", {"project_id": "project-alpha", "handle": "work:project-alpha:new-work"})
    assert own["source_baseline"] == "delivery-fixture-baseline"
    context = call("load_project", {"project_id": "project-alpha"})
    assert "sibling-route" not in json.dumps(context)
    assert context["missing_context"] == ["route_scoped_source_hydration"]
    for targets in ([], ["project:project-alpha:existing-root"], ["work:project-alpha:sibling-work"]):
        denied = client.call("watch_changes", {"project_id": "project-alpha", "client_request_id": "watch-narrow",
            "target_handles": targets, "event_kinds": [], "delivery_policy": "inbox_only",
            "expected_revision": 0, "deadline": deadline()})
        assert denied["isError"]
    own_watch = call("watch_changes", {"project_id": "project-alpha", "client_request_id": "watch-own",
        "target_handles": ["work:project-alpha:new-work"], "event_kinds": [], "delivery_policy": "inbox_only",
        "expected_revision": 0, "deadline": deadline()})
    assert own_watch["revision"] == 1
    activity = call("list_activity", {"project_id": "project-alpha"})
    assert all(item["target_id"] not in {"sibling-work", "sibling-route", "mcp-work"} for item in activity["items"])
    assert call("list_reviews", {"project_id": "project-alpha"})["items"] == []
    assert {item["agent_slot_id"] for item in call("list_collaborators", {"project_id": "project-alpha"})["items"]} == {"team-worker"}
    assert client.call("create_work", work_for("sibling-route", "stolen-work"))["isError"]
    denied = client.call("list_work", {"project_id": "project-alpha", "route_handle": "route:project-alpha:sibling-route"})
    assert denied["structuredContent"]["data"]["code"] == "authorization_denied"
