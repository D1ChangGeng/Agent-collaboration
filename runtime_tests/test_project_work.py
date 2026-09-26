"""Work/Review integration; enrolled execution observations remain fixture scope."""
from __future__ import annotations

import hashlib
import json
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from runtime.auth import LocalCredentialAuthenticator
from runtime.codex_driver import BindingIdentity, DriverJournal, DriverRejected, OutcomeUncertain
from runtime.delivery import DeliveryDispatcher, DeliveryService
from runtime.delivery_models import EndpointBindingRequest
from runtime.delivery_node import LocalNodeEndpoint
from runtime.domain import DomainAuthority
from runtime.errors import AcceptanceGuardFailed
from runtime.mcp_runtime import McpRuntime
from runtime.models import EvidenceBundle, EvidenceRecord, ExecutionReceipt, TransitionRequest, WorkItemState
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.node import NodeJournal
from runtime.project_service import ProjectService
from runtime.surfaces import SharedService
from runtime_tests.enrollment_fixture import enrollment_command, register_execution_fixture
from runtime_tests.test_project_management import managed as managed_fixture
from runtime_tests.test_project_management import bind_worker, team_args, worker_client
from runtime_tests.test_project_service import CATALOG, deadline, ok, scalar, send_args, work_args
from runtime_tests.test_project_source import source_project as source_fixture


@pytest.fixture
def managed_work(setup, tmp_path):
    value = managed_fixture.__wrapped__(setup, tmp_path)
    ok(value, "create_work", work_args())
    return value


def revise_args():
    return {"client_request_id": "revise-1", "project_id": "project-alpha",
        "work_handle": "work:project-alpha:mcp-work", "expected_revision": 0,
        "changes": {"goal": "updated goal"}, "reason": "clarify intent", "deadline": deadline()}


def test_revise_preserves_history_and_rejects_old_revision(managed_work):
    f = managed_work
    args = revise_args()
    result = ok(f, "revise_work", args)
    assert result["data"]["revision"] == 1
    assert ok(f, "revise_work", args)["data"] == result["data"]
    assert f.mcp.call("revise_work", dict(args, client_request_id="old-revision"))["structuredContent"]["data"]["code"] == "revision_conflict"
    history = ok(f, "read_resource", {"project_id": "project-alpha", "handle": args["work_handle"], "view": "history"})
    assert history["data"]["history"][0]["definition"]["goal"] == "verify shared authority"
    current = ok(f, "read_resource", {"project_id": "project-alpha", "handle": args["work_handle"], "view": "detail"})
    assert current["data"]["definition"]["goal"] == "updated goal"
    activity = ok(f, "list_activity", {"project_id": "project-alpha", "target_handle": args["work_handle"]})
    assert "work.revised" in {item["kind"] for item in activity["data"]["items"]}


def test_revise_cannot_change_intent_during_pending_delivery(managed_work):
    f = managed_work
    ok(f, "send_message", send_args())
    assert f.mcp.call("revise_work", revise_args())["structuredContent"]["data"]["code"] == "guard_rejected"
    assert scalar(f, "SELECT revision FROM work_items WHERE work_item_id='mcp-work'") == 0


def handoff_args(**changes):
    args = {"client_request_id": "handoff-1", "project_id": "project-alpha",
        "work_handle": "work:project-alpha:mcp-work", "expected_revision": 0,
        "from_agent_slot": "local-slot", "to_agent_slot": "team-worker",
        "source_state": {"branch": "fixture", "commit": "delivery-fixture-baseline",
                         "tree": "fixture-tree", "working_tree": "clean", "push": "not_pushed",
                         "receiver_sync": "pull-required"}, "context_handles": [],
        "evidence_handles": [], "unresolved_items": ["receiver needs source sync"],
        "require_ack": True,
        "deadline": (datetime.now(UTC) + timedelta(minutes=2)).isoformat()}
    args.update(changes)
    return args


def prepared_handoff(f):
    ok(f, "configure_team", team_args())
    f.handoff_delivery = bind_worker(f)
    child, _ = worker_client(f)
    child.service.bind_notification_session("project-alpha", "worker-session-1",
                                            "worker-connection-1", child.credential_provider())
    return child


def deliver_handoff(delivery_service, sent):
    delivery = DeliveryDispatcher(delivery_service)
    queued = next(item for item in delivery.pending()
                  if item["message_id"] == sent["message_handle"].split(":")[-1])
    return delivery.dispatch(queued)


def test_handoff_records_source_sync_scope_and_new_owner(managed_work):
    f = managed_work
    child = prepared_handoff(f)
    args = handoff_args()
    result = ok(f, "handoff_work", args)
    assert result["state"] == "pending"
    assert result["data"]["source_state"]["receiver_sync"] == "pull-required"
    assert result["data"]["source_observation_class"] == "sender_reported"
    assert result["data"]["acknowledgement"] == "pending"
    assert scalar(f, "SELECT agent_slot_id FROM work_items WHERE work_item_id='mcp-work'") == "team-worker"
    assert scalar(f, "SELECT execution_status FROM work_items WHERE work_item_id='mcp-work'") == "blocked"
    assert scalar(f, "SELECT count(*) FROM delivery_messages") == 1
    assert scalar(f, "SELECT count(*) FROM outbox WHERE topic='message.delivery'") == 1
    assert ok(f, "handoff_work", args)["data"] == result["data"]
    assert scalar(f, "SELECT count(*) FROM collaboration_handoffs") == 1
    handoff = result["data"]["handoff_handle"]
    deliver_handoff(f.handoff_delivery, result["data"])
    inbox = child.call("check_inbox", {"project_id": "project-alpha", "kinds": ["message"]})
    assert not inbox["isError"], inbox
    assert result["data"]["message_handle"] in [item["handle"] for item in inbox["structuredContent"]["data"]["items"]]
    assert scalar(f, "SELECT state FROM collaboration_handoffs") == "pending"
    detail = ok(f, "read_resource", {"project_id": "project-alpha", "handle": handoff,
                                     "view": "detail"})["data"]
    assert detail["state"] == "pending" and detail["source_digest"] == result["data"]["source_digest"]
    assert child.call("read_resource", {"project_id": "project-alpha", "handle": handoff})["isError"] is False
    assert f.mcp.call("send_message", dict(send_args(), client_request_id="blocked-send",
        expected_work_revision=1, target={"scope_id": "local-scope", "agent_slot_id": "team-worker"}))["isError"]
    ack = {"client_request_id": "worker-ack", "project_id": "project-alpha",
           "handoff_handle": handoff, "expected_handoff_revision": 1,
           "expected_work_revision": 1, "source_digest": result["data"]["source_digest"],
           "decision": "accepted", "reason": "source and unresolved items reviewed", "deadline": deadline()}
    assert f.mcp.call("acknowledge_handoff", ack)["structuredContent"]["data"]["code"] == "authorization_denied"
    child.service.bind_notification_session("project-alpha", "worker-session-2",
                                            "worker-connection-2", child.credential_provider())
    accepted = child.call("acknowledge_handoff", ack)
    assert not accepted["isError"], accepted
    assert accepted["structuredContent"]["data"]["acknowledgement"] == "accepted"
    assert child.call("acknowledge_handoff", ack)["structuredContent"]["data"] == accepted["structuredContent"]["data"]
    assert scalar(f, "SELECT execution_status FROM work_items WHERE work_item_id='mcp-work'") == "ready"
    assert ok(f, "read_resource", {"project_id": "project-alpha", "handle": handoff})["data"]["state"] == "accepted"
    wrong = dict(args, client_request_id="wrong-project", project_id="project-other")
    assert f.mcp.call("handoff_work", wrong)["isError"]


def test_rejected_handoff_keeps_assignment_blocked(managed_work):
    f = managed_work
    child = prepared_handoff(f)
    sent = ok(f, "handoff_work", handoff_args())["data"]
    deliver_handoff(f.handoff_delivery, sent)
    ack = {"client_request_id": "worker-reject", "project_id": "project-alpha",
           "handoff_handle": sent["handoff_handle"], "expected_handoff_revision": 1,
           "expected_work_revision": 1, "source_digest": sent["source_digest"],
           "decision": "rejected", "reason": "source not synchronized", "deadline": deadline()}
    wrong = child.call("acknowledge_handoff", dict(ack, client_request_id="wrong-source",
        source_digest="0" * 64))
    assert wrong["isError"]
    rejected = child.call("acknowledge_handoff", ack)
    assert not rejected["isError"], rejected
    work = ok(f, "read_resource", {"project_id": "project-alpha",
        "handle": "work:project-alpha:mcp-work"})["data"]
    assert work["agent_slot_id"] == "team-worker" and work["execution_status"] == "blocked"
    assert work["acknowledgement"] == "rejected" and work["revision"] == 2
    assert f.mcp.call("send_message", dict(send_args(), client_request_id="rejected-send",
        expected_work_revision=2, target={"scope_id": "local-scope", "agent_slot_id": "team-worker"}))["isError"]


def test_handoff_delivery_failure_rolls_back_assignment(managed_work):
    f = managed_work
    prepared_handoff(f)
    with psycopg.connect(f.dsn) as connection:
        connection.execute("ALTER TABLE delivery_messages ADD CONSTRAINT injected_handoff_failure "
                           "CHECK (message_id='impossible-test-value')")
    assert f.mcp.call("handoff_work", handoff_args())["isError"]
    assert scalar(f, "SELECT revision FROM work_items WHERE work_item_id='mcp-work'") == 0
    assert scalar(f, "SELECT agent_slot_id FROM work_items WHERE work_item_id='mcp-work'") == "local-slot"
    assert scalar(f, "SELECT count(*) FROM collaboration_handoffs") == 0
    assert scalar(f, "SELECT count(*) FROM delivery_messages") == 0


def test_expired_receiving_session_blocks_ack_handoff(managed_work):
    f = managed_work
    prepared_handoff(f)
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE collaboration_notification_sessions "
                           "SET expires_at=clock_timestamp()-interval '1 second' "
                           "WHERE owner_ref='agent:team-worker'")
    response = f.mcp.call("handoff_work", handoff_args())
    assert response["structuredContent"]["data"]["code"] == "guard_rejected"
    assert scalar(f, "SELECT revision FROM work_items WHERE work_item_id='mcp-work'") == 0
    assert scalar(f, "SELECT count(*) FROM collaboration_handoffs") == 0


def test_handoff_requires_recipient_ack_grant(managed_work):
    f = managed_work
    prepared_handoff(f)
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE grants SET permissions=permissions - 'handoff.ack' "
                           "WHERE grant_ref='grant:team-worker'")
    response = f.mcp.call("handoff_work", handoff_args())
    assert response["structuredContent"]["data"]["code"] == "authorization_denied"
    assert scalar(f, "SELECT revision FROM work_items WHERE work_item_id='mcp-work'") == 0
    assert scalar(f, "SELECT count(*) FROM collaboration_handoffs") == 0


def test_pending_handoff_blocks_signed_attempt_and_raw_acceptance(managed_work):
    f = managed_work
    prepared_handoff(f)
    ok(f, "handoff_work", handoff_args())
    with pytest.raises(AcceptanceGuardFailed, match="handoff acknowledgement"):
        register_execution_fixture(f.authority, work_item_id="mcp-work",
            runtime_id="pending-runtime", attempt_id="pending-attempt")
    assert scalar(f, "SELECT count(*) FROM attempts") == 0
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE grants SET permissions=permissions || '[\"work_item.transition\"]'::jsonb "
                           "WHERE grant_ref='grant:p1'")
    with pytest.raises(AcceptanceGuardFailed, match="handoff acknowledgement"):
        f.authority.transition_work_item(
            enrollment_command(f.authority, "work_item.transition", "work_item", "mcp-work", revision=1),
            TransitionRequest(to_state=WorkItemState.ACCEPTANCE_READY))
    assert scalar(f, "SELECT count(*) FROM accepted_state_revisions") == 0


def test_root_reassignment_after_rejection_replaces_latest_ack_state(managed_work):
    f = managed_work
    child = prepared_handoff(f)
    sent = ok(f, "handoff_work", handoff_args())["data"]
    deliver_handoff(f.handoff_delivery, sent)
    ack = {"client_request_id": "reject-before-reassign", "project_id": "project-alpha",
           "handoff_handle": sent["handoff_handle"], "expected_handoff_revision": 1,
           "expected_work_revision": 1, "source_digest": sent["source_digest"],
           "decision": "rejected", "reason": "receiver cannot take ownership", "deadline": deadline()}
    assert not child.call("acknowledge_handoff", ack)["isError"]
    team = team_args(revision=1, identity="replace-b")
    team["members"][0].update(agent_slot_id="replacement-worker", principal_ref="agent:replacement",
                              grant_ref="grant:replacement")
    ok(f, "configure_team", team)
    reassigned = ok(f, "handoff_work", handoff_args(client_request_id="reassign-after-reject",
        expected_revision=2, from_agent_slot="team-worker", to_agent_slot="replacement-worker",
        require_ack=False))["data"]
    assert reassigned["acknowledgement"] == "not_required" and reassigned["revision"] == 3
    work = ok(f, "read_resource", {"project_id": "project-alpha",
        "handle": "work:project-alpha:mcp-work"})["data"]
    assert work["agent_slot_id"] == "replacement-worker"
    assert work["execution_status"] == "ready"
    assert work["acknowledgement"] == "not_required"
    assert work["handoff_handle"] == reassigned["handoff_handle"]
    with psycopg.connect(f.dsn) as connection, connection.cursor() as cursor:
        f.authority._require_confirmed_project_handoff(cursor, "mcp-work")


def test_rejected_handoff_then_revised_work_can_be_reassigned(managed_work):
    f = managed_work
    child = prepared_handoff(f)
    sent = ok(f, "handoff_work", handoff_args())["data"]
    deliver_handoff(f.handoff_delivery, sent)
    rejected = {"client_request_id": "reject-before-revision", "project_id": "project-alpha",
        "handoff_handle": sent["handoff_handle"], "expected_handoff_revision": 1,
        "expected_work_revision": 1, "source_digest": sent["source_digest"],
        "decision": "rejected", "reason": "need a revised goal", "deadline": deadline()}
    assert not child.call("acknowledge_handoff", rejected)["isError"]
    ok(f, "revise_work", dict(revise_args(), client_request_id="revise-after-rejection",
        expected_revision=2))
    team = team_args(revision=1, identity="replace-after-revision")
    team["members"][0].update(agent_slot_id="replacement-worker", principal_ref="agent:replacement",
                              grant_ref="grant:replacement")
    ok(f, "configure_team", team)
    reassigned = ok(f, "handoff_work", handoff_args(client_request_id="reassign-revision",
        expected_revision=3, from_agent_slot="team-worker", to_agent_slot="replacement-worker",
        require_ack=False))["data"]
    assert reassigned["revision"] == 4
    assert scalar(f, "SELECT execution_status FROM work_items WHERE work_item_id='mcp-work'") == "ready"


def test_receiving_slot_can_ack_after_current_grant_rotation(managed_work):
    f = managed_work
    prepared_handoff(f)
    sent = ok(f, "handoff_work", handoff_args())["data"]
    deliver_handoff(f.handoff_delivery, sent)
    with psycopg.connect(f.dsn) as connection:
        connection.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,"
                           "authority_incarnation,scope_id,permissions,expires_at) "
                           "SELECT 'grant:team-worker-rotated',tenant_id,principal_ref,authority_id,"
                           "authority_incarnation,scope_id,permissions,expires_at FROM grants "
                           "WHERE grant_ref='grant:team-worker'")
        connection.execute("INSERT INTO grant_delegations(grant_ref,parent_grant_ref,tenant_id,"
                           "command_id,parent_policy_digest) SELECT 'grant:team-worker-rotated',"
                           "parent_grant_ref,tenant_id,command_id,parent_policy_digest "
                           "FROM grant_delegations WHERE grant_ref='grant:team-worker'")
        connection.execute("UPDATE collaboration_team_members SET grant_ref='grant:team-worker-rotated' "
                           "WHERE agent_slot_id='team-worker'")
        connection.execute("UPDATE collaboration_memberships SET grant_ref='grant:team-worker-rotated' "
                           "WHERE agent_slot_id='team-worker'")
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() "
                           "WHERE grant_ref='grant:team-worker'")
    secret = "rotated-private-" + uuid.uuid4().hex
    context = replace(f.authority.context, principal_ref="agent:team-worker",
                      grant_ref="grant:team-worker-rotated",
                      credential_hash=hashlib.sha256(secret.encode()).hexdigest())
    rotated_authority = DomainAuthority(f.dsn, context=context)
    rotated = McpRuntime(ProjectService(SharedService(rotated_authority,
        LocalCredentialAuthenticator(context)), CATALOG, profile="engineer"), lambda: secret)
    rotated.service.bind_notification_session("project-alpha", "worker-rotated-session",
                                               "worker-rotated-connection", secret)
    ack = {"client_request_id": "rotated-ack", "project_id": "project-alpha",
           "handoff_handle": sent["handoff_handle"], "expected_handoff_revision": 1,
           "expected_work_revision": 1, "source_digest": sent["source_digest"],
           "decision": "accepted", "reason": "current Grant verified", "deadline": deadline()}
    response = rotated.call("acknowledge_handoff", ack)
    assert not response["isError"], response
    assert response["structuredContent"]["data"]["acknowledgement"] == "accepted"
    assert scalar(f, "SELECT decided_grant_ref FROM collaboration_handoffs") == "grant:team-worker-rotated"


def test_running_attempt_prevents_handoff(managed_work):
    f = managed_work
    prepared_handoff(f)
    with psycopg.connect(f.dsn) as connection:
        connection.execute("INSERT INTO attempts(attempt_id,tenant_id,work_item_id,agent_slot_id,status) "
                           "VALUES ('active-attempt','local-tenant','mcp-work','local-slot','running')")
    assert scalar(f, "SELECT execution_status FROM work_items WHERE work_item_id='mcp-work'") == "ready"
    response = f.mcp.call("handoff_work", handoff_args())
    assert response["structuredContent"]["data"]["code"] == "guard_rejected"
    assert scalar(f, "SELECT revision FROM work_items WHERE work_item_id='mcp-work'") == 0


def test_root_withdraws_pending_handoff_before_reassignment(managed_work):
    f = managed_work
    child = prepared_handoff(f)
    sent = ok(f, "handoff_work", handoff_args())["data"]
    withdrawal = {"client_request_id": "withdraw-unanswered", "project_id": "project-alpha",
        "handoff_handle": sent["handoff_handle"], "expected_handoff_revision": 1,
        "expected_work_revision": 1, "reason": "recipient Session cannot continue", "deadline": deadline()}
    result = ok(f, "withdraw_handoff", withdrawal)
    assert result["data"]["acknowledgement"] == "withdrawn"
    assert ok(f, "withdraw_handoff", withdrawal)["data"] == result["data"]
    late = child.call("acknowledge_handoff", {"client_request_id": "late-ack",
        "project_id": "project-alpha", "handoff_handle": sent["handoff_handle"],
        "expected_handoff_revision": 1, "expected_work_revision": 1,
        "source_digest": sent["source_digest"], "decision": "accepted",
        "reason": "late response", "deadline": deadline()})
    assert late["isError"]
    team = team_args(revision=1, identity="replace-after-withdraw")
    team["members"][0].update(agent_slot_id="replacement-worker", principal_ref="agent:replacement",
                              grant_ref="grant:replacement")
    ok(f, "configure_team", team)
    reassigned = ok(f, "handoff_work", handoff_args(client_request_id="reassign-withdrawn",
        expected_revision=2, from_agent_slot="team-worker", to_agent_slot="replacement-worker",
        require_ack=False))["data"]
    assert reassigned["acknowledgement"] == "not_required"
    assert scalar(f, "SELECT execution_status FROM work_items WHERE work_item_id='mcp-work'") == "ready"


def test_ack_waits_for_committed_recipient_inbox(managed_work):
    f = managed_work
    child = prepared_handoff(f)
    sent = ok(f, "handoff_work", handoff_args())["data"]
    ack = {"client_request_id": "ack-after-delivery", "project_id": "project-alpha",
        "handoff_handle": sent["handoff_handle"], "expected_handoff_revision": 1,
        "expected_work_revision": 1, "source_digest": sent["source_digest"],
        "decision": "accepted", "reason": "inbox received", "deadline": deadline()}
    early = child.call("acknowledge_handoff", ack)
    assert early["structuredContent"]["data"]["code"] == "guard_rejected"
    assert scalar(f, "SELECT state FROM collaboration_handoffs") == "pending"
    deliver_handoff(f.handoff_delivery, sent)
    accepted = child.call("acknowledge_handoff", ack)
    assert not accepted["isError"], accepted
    assert scalar(f, "SELECT count(*) FROM delivery_receipts WHERE layer='target_inbox_committed'") == 1


def test_rejected_handoff_then_new_receiver_accepts_and_unfreezes(managed_work):
    f = managed_work
    child = prepared_handoff(f)
    sent = ok(f, "handoff_work", handoff_args())["data"]
    deliver_handoff(f.handoff_delivery, sent)
    rejected = {"client_request_id": "first-rejected", "project_id": "project-alpha",
        "handoff_handle": sent["handoff_handle"], "expected_handoff_revision": 1,
        "expected_work_revision": 1, "source_digest": sent["source_digest"],
        "decision": "rejected", "reason": "cannot receive", "deadline": deadline()}
    assert not child.call("acknowledge_handoff", rejected)["isError"]
    team = team_args(revision=1, identity="replace-for-ack")
    team["members"][0].update(agent_slot_id="replacement-worker", principal_ref="agent:replacement",
                              grant_ref="grant:replacement")
    ok(f, "configure_team", team)
    endpoint = LocalNodeEndpoint(f.team_journal, "local-scope", "replacement-worker", f.driver)
    replacement_delivery = DeliveryService(f.authority, {"replacement-endpoint": endpoint})
    replacement_delivery.bind_endpoint(
        enrollment_command(f.authority, "message.bind", "message", "replacement-endpoint"),
        EndpointBindingRequest(scope_id="local-scope", agent_slot_id="replacement-worker",
                               expires_at=datetime.now(UTC)+timedelta(minutes=5)))
    secret = "replacement-private-" + uuid.uuid4().hex
    context = replace(f.authority.context, principal_ref="agent:replacement",
                      grant_ref="grant:replacement",
                      credential_hash=hashlib.sha256(secret.encode()).hexdigest())
    recipient = McpRuntime(ProjectService(SharedService(DomainAuthority(f.dsn, context=context),
        LocalCredentialAuthenticator(context)), CATALOG, profile="engineer"), lambda: secret)
    recipient.service.bind_notification_session("project-alpha", "replacement-session",
                                                "replacement-connection", secret)
    second = ok(f, "handoff_work", handoff_args(client_request_id="second-handoff",
        expected_revision=2, from_agent_slot="team-worker", to_agent_slot="replacement-worker"))["data"]
    deliver_handoff(replacement_delivery, second)
    assert scalar(f, "SELECT execution_status FROM work_items WHERE work_item_id='mcp-work'") == "blocked"
    accepted = recipient.call("acknowledge_handoff", {"client_request_id": "replacement-ack",
        "project_id": "project-alpha", "handoff_handle": second["handoff_handle"],
        "expected_handoff_revision": 1, "expected_work_revision": 3,
        "source_digest": second["source_digest"], "decision": "accepted",
        "reason": "source synchronized", "deadline": deadline()})
    assert not accepted["isError"], accepted
    assert scalar(f, "SELECT execution_status FROM work_items WHERE work_item_id='mcp-work'") == "ready"
    assert scalar(f, "SELECT count(*) FROM collaboration_handoffs") == 2


def test_ack_and_root_cancel_do_not_deadlock(managed_work):
    f = managed_work
    child = prepared_handoff(f)
    sent = ok(f, "handoff_work", handoff_args())["data"]
    deliver_handoff(f.handoff_delivery, sent)
    ack = {"client_request_id": "racing-ack", "project_id": "project-alpha",
        "handoff_handle": sent["handoff_handle"], "expected_handoff_revision": 1,
        "expected_work_revision": 1, "source_digest": sent["source_digest"],
        "decision": "accepted", "reason": "ready", "deadline": deadline()}
    cancel = cancel_args(client_request_id="racing-cancel", expected_revision=1)
    ready = Barrier(2)
    def run_ack():
        ready.wait(timeout=5)
        return child.call("acknowledge_handoff", ack)
    def run_cancel():
        ready.wait(timeout=5)
        return f.mcp.call("cancel_work", cancel)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(run_ack)
        b = pool.submit(run_cancel)
        responses = [a.result(timeout=20), b.result(timeout=20)]
    assert sum(not item["isError"] for item in responses) == 1
    assert all(item["structuredContent"]["data"].get("code") != "service_unavailable"
               for item in responses)


def test_handoff_rejects_unresolved_context_handle(managed_work):
    f = managed_work
    prepared_handoff(f)
    response = f.mcp.call("handoff_work", handoff_args(
        context_handles=["route:project-alpha:missing-route"]))
    assert response["structuredContent"]["data"]["code"] == "not_found"
    assert scalar(f, "SELECT revision FROM work_items WHERE work_item_id='mcp-work'") == 0


def test_known_transport_credential_is_never_persisted_as_intent(managed_work):
    f = managed_work
    assert f.mcp.call("revise_work", dict(revise_args(), changes={"goal": f.credential}))["isError"]
    assert scalar(f, "SELECT count(*) FROM work_item_revisions") == 0


def cancel_args(**changes):
    value = {"client_request_id": "cancel-1", "project_id": "project-alpha",
        "work_handle": "work:project-alpha:mcp-work", "expected_revision": 0,
        "reason": "the durable objective is no longer required", "deadline": deadline()}
    value.update(changes)
    return value


class AttemptControlDriver:
    evidence_class = "fixture_callback"

    def __init__(self, path, identity, *, outcome="stopped"):
        self.binding_id = "attempt-control-binding"
        self.identity = identity
        self.journal = DriverJournal(path)
        self.outcome = outcome
        self.calls = 0

    def terminate(self, operation):
        record = self.journal.begin(operation, self.binding_id, "terminate",
                                    {"binding": asdict(self.identity)})
        if record["state"] == "acknowledged":
            return record["result"]
        self.calls += 1
        if self.outcome == "rejected":
            self.journal.finish(operation.operation_id, "rejected",
                                {"error_type": "DriverRejected"})
            raise DriverRejected("fixture rejects before control mutation")
        if self.outcome == "uncertain":
            self.journal.event(operation.operation_id, "process_dispatch", {"fixture": True})
            self.journal.finish(operation.operation_id, "uncertain",
                                {"error_type": "OutcomeUncertain"})
            raise OutcomeUncertain("fixture control acknowledgement lost")
        result = {"binding_id": self.binding_id, "binding": asdict(self.identity),
                  "receipt_layer": "process_tree_terminated",
                  "supervisor_proof": {"verified": True, "fixture_scope": True}}
        self.journal.finish(operation.operation_id, "acknowledged", result)
        return result


def install_attempt_control(f, *, outcome="stopped", wrapped=False):
    enrolled = register_execution_fixture(f.authority, work_item_id="mcp-work",
        runtime_id="control-runtime", attempt_id="control-attempt", provider="fixture-node")
    attempt = enrolled.attempt
    with psycopg.connect(f.dsn) as connection:
        machine_id = connection.execute("SELECT machine_id FROM enrolled_node_bindings "
                                        "WHERE tenant_id=%s AND node_id=%s AND binding_revision=%s",
                                        (f.authority.tenant_id, attempt["enrollment_node_id"],
                                         attempt["enrollment_node_binding_revision"])).fetchone()[0]
    identity = BindingIdentity(node_id=attempt["enrollment_node_id"],
        node_boot_id=attempt["enrollment_boot_incarnation"],
        runtime_id=attempt["enrollment_runtime_id"], attempt_id="control-attempt",
        agent_slot_id=attempt["agent_slot_id"],
        revision=attempt["enrollment_node_binding_revision"])
    driver = AttemptControlDriver(f.path.parent / ("control-driver-" + outcome + ".sqlite"),
                                  identity, outcome=outcome)
    node = NodeJournal(f.path.parent / ("control-node-" + outcome + ".sqlite"),
        machine_id=machine_id, node_id=identity.node_id,
        boot_incarnation=identity.node_boot_id)
    provider = driver
    if wrapped:
        provider = object.__new__(NativeDeliveryAdapter)
        provider.evidence_class = "native_driver_observation"
        provider.driver = driver
        provider._check_binding = lambda: None
    endpoint = LocalNodeEndpoint(node, attempt["scope_id"], attempt["agent_slot_id"], provider)
    f.authority._delivery_endpoints["attempt-control"] = endpoint
    return driver


def test_cancel_work_preserves_running_attempt_and_returns_separate_control(managed_work):
    f = managed_work
    with psycopg.connect(f.dsn) as connection:
        connection.execute("INSERT INTO attempts(attempt_id,tenant_id,work_item_id,agent_slot_id,status) "
                           "VALUES ('active-attempt','local-tenant','mcp-work','local-slot','running')")
        connection.execute("UPDATE work_items SET execution_status='running' "
                           "WHERE work_item_id='mcp-work'")
    args = cancel_args()
    result = ok(f, "cancel_work", args)
    assert result["state"] == "cancelled"
    assert result["data"]["execution_status"] == "cancelled"
    assert result["data"]["accepted_state_changed"] is False
    assert result["data"]["attempts"] == [{
        "attempt_handle": "attempt:project-alpha:active-attempt", "revision": 1,
        "state": "running", "runtime_id": None, "node_id": None,
        "control_required": True,
    }]
    assert result["follow_ups"][0]["tool"] == "stop_attempt"
    assert scalar(f, "SELECT status FROM attempts WHERE attempt_id='active-attempt'") == "running"
    assert scalar(f, "SELECT execution_status FROM work_items WHERE work_item_id='mcp-work'") == "cancelled"
    assert scalar(f, "SELECT count(*) FROM accepted_state_revisions") == 0
    assert ok(f, "cancel_work", args)["data"] == result["data"]
    detail = ok(f, "read_resource", {"project_id": "project-alpha",
        "handle": "work:project-alpha:mcp-work", "view": "detail"})["data"]
    assert detail["definition"]["cancellation"]["reason"] == cancel_args()["reason"]
    after_cancel = f.mcp.call("send_message", dict(send_args(),
        client_request_id="send-after-cancel", expected_work_revision=1))
    assert after_cancel["structuredContent"]["data"]["code"] == "guard_rejected"
    assert scalar(f, "SELECT count(*) FROM delivery_messages") == 0


def test_cancel_work_rejects_stale_revision_and_sealed_state(managed_work):
    f = managed_work
    stale = f.mcp.call("cancel_work", cancel_args(expected_revision=1))
    assert stale["structuredContent"]["data"]["code"] == "revision_conflict"
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE work_items SET state='acceptance_ready' WHERE work_item_id='mcp-work'")
    sealed = f.mcp.call("cancel_work", cancel_args(client_request_id="cancel-sealed"))
    assert sealed["structuredContent"]["data"]["code"] == "guard_rejected"
    assert scalar(f, "SELECT execution_status FROM work_items WHERE work_item_id='mcp-work'") == "ready"


def stop_args(**changes):
    value = {"client_request_id": "stop-1", "project_id": "project-alpha",
        "attempt_handle": "attempt:project-alpha:control-attempt", "expected_revision": 1,
        "reason": "the cancelled Work still owns native capacity", "deadline": deadline()}
    value.update(changes)
    return value


def test_stop_attempt_requires_cancelled_work_and_persists_driver_ack(managed_work):
    f = managed_work
    driver = install_attempt_control(f, wrapped=True)
    before_cancel = f.mcp.call("stop_attempt", stop_args(client_request_id="stop-before-cancel"))
    assert before_cancel["structuredContent"]["data"]["code"] == "guard_rejected"
    ok(f, "cancel_work", cancel_args())
    with psycopg.connect(f.dsn) as connection:
        connection.execute("INSERT INTO effects(effect_id,tenant_id,work_item_id,resource_id,"
                           "baseline_ref,lease_id,fencing_token,status,readback_ref,grant_ref) VALUES "
                           "('control-effect','local-tenant','mcp-work','fixture-resource',"
                           "'fixture-baseline','fixture-lease','fixture-fence','uncertain',"
                           "'readback:fixture','grant:p1')")
    args = stop_args()
    stopped = ok(f, "stop_attempt", args)
    assert stopped["state"] == "stopped"
    assert stopped["data"]["driver_acknowledgement"] == "acknowledged"
    assert stopped["data"]["attempt_state"] == "cancelled"
    assert stopped["data"]["revision"] == 2
    assert stopped["data"]["effect_uncertainty"] == "requires_readback"
    assert stopped["data"]["unresolved_effects"] == [{
        "effect_handle": "effect:project-alpha:control-effect",
        "state": "uncertain", "readback_ref": "readback:fixture",
    }]
    assert stopped["data"]["control_observation"]["receipt_layer"] == "process_tree_terminated"
    assert driver.calls == 1
    assert scalar(f, "SELECT status FROM attempts WHERE attempt_id='control-attempt'") == "cancelled"
    assert ok(f, "stop_attempt", args)["data"] == stopped["data"]
    assert driver.calls == 1
    stale = f.mcp.call("stop_attempt", stop_args(client_request_id="stop-stale"))
    assert stale["structuredContent"]["data"]["code"] == "revision_conflict"
    assert scalar(f, "SELECT count(*) FROM domain_events WHERE to_state='attempt.stopped'") == 1


def test_stop_attempt_rejects_stale_enrollment_before_control_intent(managed_work):
    f = managed_work
    driver = install_attempt_control(f)
    ok(f, "cancel_work", cancel_args())
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE enrolled_runtimes SET status='retired',"
                           "retired_at=clock_timestamp() WHERE runtime_id='control-runtime'")
    result = f.mcp.call("stop_attempt", stop_args())
    assert result["structuredContent"]["data"]["code"] == "guard_rejected"
    assert driver.calls == 0
    assert scalar(f, "SELECT count(*) FROM collaboration_commands "
                     "WHERE tool_name='stop_attempt'") == 0


def test_stop_attempt_recovers_committed_intent_as_uncertain_without_provider(
        managed_work, monkeypatch):
    f = managed_work
    driver = install_attempt_control(f)
    ok(f, "cancel_work", cancel_args())
    args = stop_args()
    original_read = driver.journal.read

    def interrupt_after_domain_commit(_operation_id):
        raise KeyboardInterrupt

    monkeypatch.setattr(driver.journal, "read", interrupt_after_domain_commit)
    with pytest.raises(KeyboardInterrupt):
        f.projects.execute("stop_attempt", args, f.credential)
    assert scalar(f, "SELECT result_json->>0 FROM collaboration_commands "
                     "WHERE tool_name='stop_attempt'") == "stop_requested"
    monkeypatch.setattr(driver.journal, "read", original_read)
    f.authority._delivery_endpoints.clear()
    recovered = ok(f, "stop_attempt", args)
    assert recovered["state"] == "uncertain"
    assert recovered["data"]["attempt_state"] == "running"
    assert recovered["data"]["control_observation"] == {
        "evidence_class": "authority_observation",
        "state": "control_provider_unavailable",
    }
    assert driver.calls == 0


@pytest.mark.parametrize("outcome", ["rejected", "uncertain"])
def test_stop_attempt_preserves_non_acknowledged_attempt_and_replays(managed_work, outcome):
    f = managed_work
    driver = install_attempt_control(f, outcome=outcome)
    ok(f, "cancel_work", cancel_args())
    args = stop_args()
    result = ok(f, "stop_attempt", args)
    assert result["state"] == outcome
    assert result["data"]["driver_acknowledgement"] == outcome
    assert result["data"]["attempt_state"] == "running"
    expected_uncertainty = "control_outcome_uncertain" if outcome == "uncertain" else "none_observed"
    assert result["data"]["effect_uncertainty"] == expected_uncertainty
    assert scalar(f, "SELECT status FROM attempts WHERE attempt_id='control-attempt'") == "running"
    assert ok(f, "stop_attempt", args)["data"] == result["data"]
    assert driver.calls == 1
    if outcome == "uncertain":
        repeated = f.mcp.call("stop_attempt", stop_args(client_request_id="stop-new-intent"))
        assert repeated["structuredContent"]["data"]["code"] == "guard_rejected"
        assert driver.calls == 1


@pytest.fixture
def review_project(setup, tmp_path):
    if not sys.platform.startswith("linux"):
        pytest.skip("real Source/CAS Review integration requires Linux")
    source = source_fixture.__wrapped__(setup, tmp_path)
    f = next(source)
    try:
        store = f.projects.sources.store
        f.authority._artifact_store = store
        with psycopg.connect(f.dsn) as connection:
            connection.execute("UPDATE grants SET permissions=permissions || %s::jsonb WHERE grant_ref='grant:p1'",
                               (json.dumps(["review.assign", "review.record", "profile.reviewer", "evidence.record"]),))
        args = team_args()
        args["members"][0].update(agent_slot_id="typed-reviewer", principal_ref="agent:typed-reviewer",
            role="reviewer", profile="reviewer", grant_ref="grant:typed-reviewer", permissions=[
                "profile.reviewer", "projects.read", "context.read", "resources.read", "reviews.read",
                "reviews.submit", "review.record", "source.read", "artifact.read", "evidence.read"])
        ok(f, "configure_team", args)
        ok(f, "create_work", dict(work_args(), source_baseline=f.commit))
        candidate = "candidate-" + f.commit
        enrolled = register_execution_fixture(f.authority, work_item_id="mcp-work", runtime_id="review-runtime",
            attempt_id="review-attempt", source_commit=f.commit, source_tree=f.tree, candidate_ref=candidate)
        output = store.put_bytes(b"reviewed fixture output", kind="output")
        readback = store.put_bytes(b"independent fixture artifact readback", kind="readback")
        observed = datetime.now(UTC)
        receipt = ExecutionReceipt(receipt_id="review-receipt", work_item_id="mcp-work", attempt_id="review-attempt",
            runtime_id="review-runtime", provider="fixture-node", command_id=enrolled.attempt["execution_command_id"],
            operation_id=enrolled.attempt["execution_operation_id"], event_id=enrolled.attempt["execution_event_id"],
            source_baseline=f.commit, source_commit=f.commit, source_tree=f.tree, candidate_ref=candidate,
            test_commands=("fixture-test",), test_exit_codes=(0,), test_exit_code=0, os="linux", toolchain="fixture",
            artifact_refs=(output,), readback_refs=(readback,), source_sync="fixture-source", status="succeeded",
            observed_at=observed)
        command = enrollment_command(enrolled.node, "execution.record", "work_item", "mcp-work")
        enrolled.node.record_execution_receipt(command, receipt, node_proof=enrolled.receipt_proof(command, receipt))
        f.evidence_handles = []
        for number in (1, 2):
            evidence_id = "typed-evidence-" + str(number)
            bundle = EvidenceBundle(evidence_id=evidence_id, work_item_id="mcp-work", source_baseline=f.commit,
                candidate_ref=candidate, producer_ref=f.authority.context.principal_ref,
                observer_ref=enrolled.node.context.principal_ref, source_class="directly_verified",
                evidence_state="complete", execution_receipt=receipt, artifact_refs=(output,), readback_refs=(readback,),
                command_id=receipt.command_id, operation_id=receipt.operation_id, event_id=receipt.event_id,
                observed_at=observed)
            evidence = EvidenceRecord(evidence_id=evidence_id, work_item_id="mcp-work",
                observer_ref=enrolled.node.context.principal_ref, source_class="directly_verified", baseline_ref=f.commit,
                artifact_sha256=output.sha256, summary="Signed fixture observation, not Harness conformance",
                bundle_ref=evidence_id, candidate_ref=candidate, execution_receipt_ref=receipt.receipt_id,
                evidence_state="complete", producer_ref=f.authority.context.principal_ref, attempt_id="review-attempt",
                test_exit_code=0, artifact_refs=(output,), readback_refs=(readback,))
            f.authority.record_evidence(enrollment_command(f.authority, "evidence.record", "work_item", "mcp-work"), evidence, bundle)
            f.evidence_handles.append("evidence:project-alpha:" + evidence_id)
        secret = "reviewer-private-" + uuid.uuid4().hex
        context = replace(f.authority.context, principal_ref="agent:typed-reviewer", grant_ref="grant:typed-reviewer",
                          credential_hash=hashlib.sha256(secret.encode()).hexdigest())
        f.reviewer_authority = DomainAuthority(f.dsn, context=context, artifact_store=store)
        reviewer_service = SharedService(f.reviewer_authority, LocalCredentialAuthenticator(context))
        f.reviewer = McpRuntime(ProjectService(reviewer_service, CATALOG, profile="reviewer", sources=f.projects.sources), lambda: secret)
        f.candidate, f.output = candidate, output
        yield f
    finally:
        source.close()


def request_review(f, revision=0, **optional):
    return ok(f, "request_review", {"client_request_id": "request-review", "project_id": "project-alpha",
        "work_handle": "work:project-alpha:mcp-work", "expected_work_revision": revision, "review_type": "candidate",
        "candidate_ref": f.candidate, "source_baseline": f.commit, "criteria": ["direct Source and CAS readback"],
        "required_evidence": ["complete bundles"], "reviewer_requirements": ["collaborator:project-alpha:typed-reviewer"],
        "deadline": deadline(), **optional})["data"]["review_handle"]


def submit_args(f, review):
    return {"client_request_id": "submit-review", "project_id": "project-alpha", "review_handle": review,
        "expected_revision": 1, "decision": "pass", "findings": [], "evidence_handles": f.evidence_handles,
        "source_readback": {"source_id": "source-main", "commit": f.commit, "tree": f.tree},
        "unresolved_items": [], "deadline": deadline()}


def test_independent_review_seals_complete_set_without_accepting_work(review_project):
    f = review_project
    review = request_review(f)
    args = submit_args(f, review)
    reply = f.reviewer.call("submit_review", args)
    assert not reply["isError"], reply
    assert reply["structuredContent"]["data"]["accepted_state_changed"] is False
    assert not f.reviewer.call("submit_review", args)["isError"]
    assert scalar(f, "SELECT count(*) FROM reviews") == 1
    assert scalar(f, "SELECT jsonb_array_length(evidence_refs) FROM reviews") == 2
    assert scalar(f, "SELECT count(*) FROM accepted_state_revisions") == 0
    listed = ok(f, "list_reviews", {"project_id": "project-alpha", "states": ["submitted"]})
    assert listed["data"]["items"][0]["review_handle"] == review
    resources = ok(f, "read_resource", {"project_id": "project-alpha", "handle": review, "view": "detail"})
    assert resources["data"]["submission"]["decision"] == "pass"
    evidence = ok(f, "list_evidence", {"project_id": "project-alpha",
        "target_handle": "work:project-alpha:mcp-work"})
    assert evidence["data"]["items"][0]["artifact_handles"]
    assert all(item.startswith("artifact:project-alpha:local-scope.")
               for item in evidence["data"]["items"][0]["artifact_handles"])


@pytest.mark.parametrize("fault", ["source", "evidence_set", "findings", "artifact", "revision", "parent_revoke"])
def test_review_pass_rejects_stale_or_incomplete_evidence(review_project, fault):
    f = review_project
    args = submit_args(f, request_review(f))
    if fault == "source":
        (f.repo / "README.md").write_text("changed Source")
    elif fault == "evidence_set":
        args["evidence_handles"] = args["evidence_handles"][:1]
    elif fault == "findings":
        args["findings"] = ["unresolved failure"]
    elif fault == "artifact":
        (f.projects.sources.store.root / f.output.path).chmod(0o600)
        (f.projects.sources.store.root / f.output.path).write_bytes(b"corrupted")
    elif fault == "revision":
        args["expected_revision"] = 2
    else:
        with psycopg.connect(f.dsn) as connection:
            connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref='grant:p1'")
    assert f.reviewer.call("submit_review", args)["isError"]
    assert scalar(f, "SELECT count(*) FROM reviews") == 0


def test_producer_cannot_submit_review_or_change_scope(review_project):
    f = review_project
    args = submit_args(f, request_review(f))
    assert f.mcp.call("submit_review", args)["isError"]
    assert f.reviewer.call("submit_review", dict(args, project_id="another-project"))["isError"]


def finalizer_client(f):
    """Explicit private-test finalization authority, never the actual project owner."""
    secret = "fixture-finalizer-" + uuid.uuid4().hex
    context = replace(f.authority.context, principal_ref="fixture:authorized-finalizer",
        grant_ref="grant:fixture-finalizer", credential_hash=hashlib.sha256(secret.encode()).hexdigest())
    authority = DomainAuthority(f.dsn, context=context, artifact_store=f.projects.sources.store)
    authority.bootstrap_local_grant(("profile.root_manager", "acceptance.commit", "work_item.transition",
                                    "acceptance.finalize", "source.read", "artifact.read",
                                    "resources.read"))
    with psycopg.connect(f.dsn) as connection:
        connection.execute("INSERT INTO agent_slots VALUES ('fixture-finalizer-slot','local-tenant','local-scope','active')")
        connection.execute("INSERT INTO collaboration_memberships VALUES ('local-tenant','project-alpha',"
                           "'fixture:authorized-finalizer','grant:fixture-finalizer','root_manager','fixture-finalizer-slot')")
    service = SharedService(authority, LocalCredentialAuthenticator(context))
    return McpRuntime(ProjectService(service, CATALOG, profile="root_manager", sources=f.projects.sources), lambda: secret)


def acceptance_args(f, review):
    return {"client_request_id": "fixture-ready", "project_id": "project-alpha",
        "work_handle": "work:project-alpha:mcp-work", "expected_revision": 0,
        "candidate_ref": f.candidate, "review_handles": [review],
        "evidence_bundle_handles": [item.replace("evidence:", "bundle:", 1) for item in f.evidence_handles],
        "source_readback": {"source_id": "source-main", "commit": f.commit, "tree": f.tree},
        "effect_readback": {"effect_refs": [], "readback_refs": []},
        "decision": "acceptance_ready", "deadline": deadline()}


def test_multi_evidence_finalization_uses_explicit_authority_and_core_guards(review_project):
    f = review_project
    review = request_review(f)
    assert not f.reviewer.call("submit_review", submit_args(f, review))["isError"]
    args = acceptance_args(f, review)
    assert f.mcp.call("accept_work", args)["isError"]
    assert scalar(f, "SELECT count(*) FROM accepted_state_revisions") == 0
    finalizer = finalizer_client(f)
    ready = finalizer.call("accept_work", args)
    assert not ready["isError"], ready
    assert ready["structuredContent"]["state"] == "acceptance_ready"
    accepted = finalizer.call("accept_work", dict(args, client_request_id="fixture-accept",
                                                 expected_revision=1, decision="accepted"))
    assert not accepted["isError"], accepted
    assert accepted["structuredContent"]["data"]["accepted_by"] == "fixture:authorized-finalizer"
    assert scalar(f, "SELECT count(*) FROM accepted_state_revisions WHERE readiness_snapshot=FALSE") == 1
    accepted_handle = accepted["structuredContent"]["data"]["accepted_state_handle"]
    readback = finalizer.call("read_resource", {"project_id": "project-alpha",
        "handle": accepted_handle, "view": "detail",
        "at_revision": accepted["structuredContent"]["data"]["revision"]})
    assert not readback["isError"], readback
    assert readback["structuredContent"]["data"]["accepted_state"]["accepted_by"] == \
        "fixture:authorized-finalizer"


def test_acceptance_rejects_evidence_subset_even_with_explicit_authority(review_project):
    f = review_project
    review = request_review(f)
    assert not f.reviewer.call("submit_review", submit_args(f, review))["isError"]
    finalizer = finalizer_client(f)
    args = acceptance_args(f, review)
    args["evidence_bundle_handles"] = args["evidence_bundle_handles"][:1]
    assert finalizer.call("accept_work", args)["isError"]
    assert scalar(f, "SELECT count(*) FROM accepted_state_revisions") == 0


def test_handoff_preserves_verified_historical_execution_for_review(review_project):
    f = review_project
    handed = ok(f, "handoff_work", {"client_request_id": "handoff-review", "project_id": "project-alpha",
        "work_handle": "work:project-alpha:mcp-work", "expected_revision": 0,
        "from_agent_slot": "local-slot", "to_agent_slot": "typed-reviewer",
        "source_state": {"branch": "fixture", "commit": f.commit, "tree": f.tree,
                         "working_tree": "clean", "push": "not-measured", "receiver_sync": "not-measured"},
        "context_handles": [], "evidence_handles": f.evidence_handles, "unresolved_items": [],
        "require_ack": False, "deadline": deadline()})
    assert handed["data"]["revision"] == 1
    review = request_review(f, revision=1)
    result = f.reviewer.call("submit_review", submit_args(f, review))
    assert not result["isError"], result
    assert scalar(f, "SELECT count(*) FROM work_item_revisions") == 1
    assert scalar(f, "SELECT count(*) FROM execution_receipts") == 1


def add_component_summary(f, *, identity="component-summary", failed=False):
    record = EvidenceRecord(evidence_id=identity, work_item_id="mcp-work",
        observer_ref=f.authority.context.principal_ref, producer_ref=f.authority.context.principal_ref,
        source_class="mocked", evidence_state="incomplete", baseline_ref=f.commit,
        candidate_ref=f.candidate, artifact_sha256="a" * 64,
        summary="Retained component-scope observation", test_exit_code=1 if failed else 0)
    f.authority.record_evidence(enrollment_command(f.authority, "evidence.record", "work_item", "mcp-work"), record)
    return "evidence:project-alpha:" + identity


def test_explicit_review_selection_preserves_component_scope(review_project):
    f = review_project
    component = add_component_summary(f)
    review = request_review(f, evidence_handles=f.evidence_handles)
    detail = ok(f, "read_resource", {"project_id": "project-alpha", "handle": review, "view": "detail"})
    assert detail["data"]["definition"]["excluded_evidence"][0]["source_class"] == "mocked"
    args = submit_args(f, review)
    assert f.reviewer.call("submit_review", args)["isError"]
    args["evidence_dispositions"] = [{"evidence_handle": component, "disposition": "out_of_scope",
        "reason": "Component behavior only; signed execution bundles establish this requested runtime Review.",
        "replacement_handles": []}]
    assert not f.reviewer.call("submit_review", args)["isError"]
    with psycopg.connect(f.dsn) as connection:
        assert connection.execute("SELECT source_class,evidence_state,test_exit_code FROM evidence "
                                  "WHERE evidence_id='component-summary'").fetchone() == ("mocked", "incomplete", 0)
    finalizer = finalizer_client(f)
    assert not finalizer.call("accept_work", acceptance_args(f, review))["isError"]


def test_excluded_failure_requires_explicit_supported_resolution(review_project):
    f = review_project
    component = add_component_summary(f, failed=True)
    review = request_review(f, evidence_handles=f.evidence_handles)
    args = submit_args(f, review)
    args["evidence_dispositions"] = [{"evidence_handle": component, "disposition": "out_of_scope",
        "reason": "Exclude this failure", "replacement_handles": []}]
    assert f.reviewer.call("submit_review", args)["isError"]
    args["evidence_dispositions"][0].update(disposition="superseded",
        reason="The selected verified rerun resolves this component observation; retain its original failed record.",
        replacement_handles=[f.evidence_handles[0]])
    result = f.reviewer.call("submit_review", args)
    assert not result["isError"], result
    assert scalar(f, "SELECT test_exit_code FROM evidence WHERE evidence_id='component-summary'") == 1


@pytest.mark.parametrize("after_review", [False, True])
def test_new_candidate_evidence_invalidates_sealed_review_inventory(review_project, after_review):
    f = review_project
    review = request_review(f, evidence_handles=f.evidence_handles)
    if after_review:
        assert not f.reviewer.call("submit_review", submit_args(f, review))["isError"]
    add_component_summary(f, identity="late-failure", failed=True)
    if after_review:
        assert finalizer_client(f).call("accept_work", acceptance_args(f, review))["isError"]
        assert scalar(f, "SELECT count(*) FROM accepted_state_revisions") == 0
    else:
        assert f.reviewer.call("submit_review", submit_args(f, review))["isError"]
        assert scalar(f, "SELECT count(*) FROM reviews") == 0


def test_review_selection_rejects_foreign_or_unknown_handles(review_project):
    f = review_project
    for value in ("evidence:another-project:typed-evidence-1", "evidence:project-alpha:missing"):
        with pytest.raises(AssertionError):
            request_review(f, evidence_handles=[value])
