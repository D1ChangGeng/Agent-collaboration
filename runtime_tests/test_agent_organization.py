"""Organization declarations describe scope/duties and preserve live authority."""
from __future__ import annotations

import json

import psycopg
import pytest
from pydantic import ValidationError

from runtime.agent_organization import organization_model, organization_projection
from runtime.project_management import TeamMember
from runtime_tests.test_project_management import managed as managed_fixture
from runtime_tests.test_project_management import team_args, worker_client
from runtime_tests.test_project_service import ok, scalar
from runtime_tests.test_project_work import request_review, submit_args
from runtime_tests.test_project_work import review_project as review_fixture

managed = managed_fixture
review_project = review_fixture


def test_organization_and_duties_are_orthogonal():
    value = organization_projection("engineer", level="root", responsibilities=["engineer", "specialist"])
    assert value["level"] == "root" and value["responsibilities"] == ["engineer", "specialist"]
    assert value["permission_effect"] == "descriptive_only"
    assert organization_projection("reviewer")["terminology_status"] == "proposed"
    assert organization_projection(None)["level"] == "unknown"


def test_model_readbacks_do_not_share_mutable_global_vocabulary():
    first = organization_model()
    first["responsibility_roles"].clear()
    assert "reviewer" in organization_model()["responsibility_roles"]


def test_team_member_keeps_legacy_role_and_validates_separate_declarations():
    data = team_args()["members"][0]
    member = TeamMember.model_validate_json(json.dumps(data), strict=True)
    assert member.role == "engineer" and member.organization_level is None
    extended = dict(data, organization_level="route", responsibilities=["engineer", "specialist"])
    assert TeamMember.model_validate_json(json.dumps(extended), strict=True).profile == data["profile"]
    for mutation in ({"role": "task"}, {"responsibilities": ["reviewer"]},
                     {"responsibilities": ["engineer", "engineer"]}):
        with pytest.raises(ValidationError):
            TeamMember.model_validate_json(json.dumps(dict(extended, **mutation)), strict=True)


def test_context_and_collaborators_expose_the_same_binding_without_escalation(managed):
    args = team_args()
    args["members"][0].update(organization_level="root", responsibilities=["engineer", "specialist", "finalizer"])
    ok(managed, "configure_team", args)
    observed = ok(managed, "list_collaborators", {"project_id": "project-alpha"})["data"]["items"][0]
    child, _authority = worker_client(managed)
    pack = child.call("load_project", {"project_id": "project-alpha"})["structuredContent"]["data"]
    assert observed["organization"] == pack["actor_binding"]["organization"]
    assert pack["actor_binding"]["scope_handle"] == observed["scope_handle"]
    assert pack["agent_organization_model"]["task_agent_status"] == "proposed_terminology"
    assert "acceptance.finalize" not in observed["authorization"]["declared_permissions"]
    assert "configure_team" not in {item["name"] for item in child.tools_list()["tools"]}
    assert child.call("accept_work", {})["isError"]
    assert observed["work_query"]["arguments"]["assigned_to"].endswith(":team-worker")
    assert observed["session_query"]["arguments"]["required_capabilities"] == []
    assert observed["review_query"]["match_observations"]["reviewer_ref"] == observed["principal_ref"]
    for entry in (observed["work_query"], observed["session_query"], observed["review_query"]):
        managed.mcp._validate(entry["tool"], entry["arguments"])
    assert scalar(managed, "SELECT count(*) FROM accepted_state_revisions") == 0
    filtered = ok(managed, "list_collaborators", {"project_id": "project-alpha", "roles": ["specialist"]})
    assert filtered["data"]["items"][0]["agent_slot_id"] == "team-worker"


def test_legacy_team_readback_marks_task_as_proposed(managed):
    ok(managed, "configure_team", team_args())
    item = ok(managed, "list_collaborators", {"project_id": "project-alpha"})["data"]["items"][0]
    assert item["role"] == "engineer" and item["organization"]["level"] == "task"
    assert item["organization"]["level_source"] == "legacy_projection"


def test_explicit_reviewer_duty_uses_existing_authority_and_independence(review_project):
    f = review_project
    with psycopg.connect(f.dsn) as connection:
        definition = connection.execute("SELECT definition FROM collaboration_teams").fetchone()[0]
        definition["members"][0].update(role="engineer", organization_level="task",
                                          responsibilities=["engineer", "reviewer"])
        connection.execute("UPDATE collaboration_teams SET definition=%s::jsonb", (json.dumps(definition),))
        connection.execute("UPDATE collaboration_team_members SET role='engineer'")
    review = request_review(f)
    assert not f.reviewer.call("submit_review", submit_args(f, review))["isError"]
    assert f.mcp.call("submit_review", submit_args(f, review))["isError"]
    assert scalar(f, "SELECT count(*) FROM accepted_state_revisions") == 0


def test_reviewer_label_cannot_replace_its_required_grant(review_project):
    f = review_project
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE grants SET permissions=permissions - 'review.record' "
                           "WHERE grant_ref='grant:typed-reviewer'")
    with pytest.raises(AssertionError):
        request_review(f)
    assert scalar(f, "SELECT count(*) FROM reviews") == 0
