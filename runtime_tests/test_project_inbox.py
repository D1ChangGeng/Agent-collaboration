"""Durable delivered-message and explicit Review-assignment Inbox integration."""
from __future__ import annotations

import psycopg
import pytest

from runtime.delivery_models import DeliveryPacket
from runtime.project_service import ProjectService
from runtime_tests.test_delivery import command
from runtime_tests.test_project_service import CATALOG, ok, scalar, work_args
from runtime_tests.test_project_service import project as project_fixture
from runtime_tests.test_project_work import request_review
from runtime_tests.test_project_work import review_project as review_fixture


@pytest.fixture
def inbox_project(setup):
    f = project_fixture.__wrapped__(setup)
    ok(f, "create_work", work_args())
    return f


def deliver(f, identity="raw-incoming"):
    intent = command(f.authority, "message.send", identity)
    packet = DeliveryPacket(work_item_id="mcp-work", target_scope_id="local-scope", target_agent_slot_id="local-slot",
        accepted_revision=0, goal="Receive real committed Inbox bytes", accepted_state_summary="revision 0",
        request="INCOMING_CONTENT_MARKER", source_baseline="delivery-fixture-baseline", expected_response="message only",
        deadline=intent.deadline)
    f.service.send_message(intent, packet, endpoint_id="endpoint", binding_revision=1)
    pending = next(item for item in f.dispatcher.pending() if item["message_id"] == identity)
    f.dispatcher.dispatch(pending)
    return "message:project-alpha:" + identity


def test_incoming_domain_message_can_be_read_without_sender_mcp_tracking(inbox_project):
    f = inbox_project
    message = deliver(f)
    assert scalar(f, "SELECT count(*) FROM collaboration_response_tracking") == 0
    page = ok(f, "check_inbox", {"project_id": "project-alpha", "kinds": ["message"]})["data"]
    assert [item["handle"] for item in page["items"]] == [message]
    assert "INCOMING_CONTENT_MARKER" not in str(page)
    assert page["items"][0]["read"]["arguments"] == {"project_id": "project-alpha", "handle": message}
    observed = ok(f, "read_message", {"project_id": "project-alpha", "handle": message, "consume": False})["data"]
    assert observed["content"]["request"] == "INCOMING_CONTENT_MARKER"
    assert observed["consumed"] is False and "response_handle" not in observed
    too_small = f.mcp.call("read_message", {"project_id": "project-alpha", "handle": message, "max_inline_bytes": 1})
    assert too_small["isError"]
    assert scalar(f, "SELECT count(*) FROM collaboration_inbox_consumptions") == 0
    assert ok(f, "read_message", {"project_id": "project-alpha", "handle": message})["data"]["consumed"] is True
    assert ok(f, "read_message", {"project_id": "project-alpha", "handle": message, "consume": False})["data"]["consumed"] is True
    restarted = ProjectService(f.projects.service, CATALOG, profile="root_manager")
    assert restarted.execute("check_inbox", {"project_id": "project-alpha"}, f.credential)[1]["items"] == []
    assert scalar(f, "SELECT count(*) FROM inbox_messages") == 1


def test_incoming_pages_are_bounded_and_have_stable_followups(inbox_project):
    f = inbox_project
    a, b = deliver(f, "a-incoming"), deliver(f, "b-incoming")
    first = ok(f, "check_inbox", {"project_id": "project-alpha", "limit": 1})["data"]
    assert first["items"][0]["handle"] == a and first["next_cursor"] == a
    second = ok(f, "check_inbox", {"project_id": "project-alpha", "limit": 1, "cursor": a})["data"]
    assert second["items"][0]["handle"] == b and second["next_cursor"] is None
    assert not ok(f, "check_inbox", {"project_id": "project-alpha", "kinds": ["response"]})["data"]["items"]
    f.projects.bind_notification_session("project-alpha", "inbox-session", "connection", f.credential)
    keys = f.projects.pending_wake_keys("project-alpha", "inbox-session", "connection", f.credential)
    assert keys == [a+":content:1", b+":content:1"]


@pytest.fixture
def assigned_review(setup, tmp_path):
    fixture = review_fixture.__wrapped__(setup, tmp_path)
    f = next(fixture)
    try:
        with psycopg.connect(f.dsn) as connection:
            connection.execute("UPDATE grants SET permissions=permissions || '[\"messages.read\",\"message.read\"]'::jsonb "
                               "WHERE grant_ref='grant:typed-reviewer'")
        f.assigned = request_review(f)
        yield f
    finally:
        fixture.close()


def test_review_assignment_wakes_its_owner_and_consumption_is_not_a_review(assigned_review):
    f = assigned_review
    credential = f.reviewer.credential_provider()
    service = f.reviewer.service
    service.bind_notification_session("project-alpha", "review-session", "review-connection", credential)
    page = f.reviewer.call("check_inbox", {"project_id": "project-alpha"})
    assert not page["isError"], page
    assert [item["review_handle"] for item in page["structuredContent"]["data"]["items"]] == [f.assigned]
    assert service.pending_wake_keys("project-alpha", "review-session", "review-connection", credential) == [f.assigned+":content:1"]
    forbidden = f.mcp.call("read_message", {"project_id": "project-alpha", "handle": f.assigned})
    assert forbidden["structuredContent"]["data"]["code"] == "authorization_denied"
    read = f.reviewer.call("read_message", {"project_id": "project-alpha", "handle": f.assigned})
    assert not read["isError"] and read["structuredContent"]["data"]["consumed"] is True
    assert read["structuredContent"]["data"]["evidence_handles"] == f.evidence_handles
    assert scalar(f, "SELECT count(*) FROM reviews") == 0
    assert scalar(f, "SELECT state FROM collaboration_review_requests") == "pending"
    reread = f.reviewer.call("read_message", {"project_id": "project-alpha", "handle": f.assigned, "consume": False})
    assert reread["structuredContent"]["data"]["consumed"] is True
    assert service.pending_wake_keys("project-alpha", "review-session", "review-connection", credential) == []
