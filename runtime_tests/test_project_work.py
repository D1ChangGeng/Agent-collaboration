"""Work/Review integration; enrolled execution observations remain fixture scope."""
from __future__ import annotations

import hashlib
import json
import sys
import uuid
from dataclasses import replace
from datetime import UTC, datetime

import psycopg
import pytest

from runtime.auth import LocalCredentialAuthenticator
from runtime.domain import DomainAuthority
from runtime.mcp_runtime import McpRuntime
from runtime.models import EvidenceBundle, EvidenceRecord, ExecutionReceipt
from runtime.project_service import ProjectService
from runtime.surfaces import SharedService
from runtime_tests.enrollment_fixture import enrollment_command, register_execution_fixture
from runtime_tests.test_project_management import managed as managed_fixture
from runtime_tests.test_project_management import team_args
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


def test_handoff_records_source_sync_scope_and_new_owner(managed_work):
    f = managed_work
    ok(f, "configure_team", team_args())
    args = {"client_request_id": "handoff-1", "project_id": "project-alpha",
        "work_handle": "work:project-alpha:mcp-work", "expected_revision": 0,
        "from_agent_slot": "local-slot", "to_agent_slot": "team-worker",
        "source_state": {"branch": "fixture", "commit": "delivery-fixture-baseline",
                         "tree": "fixture-tree", "working_tree": "clean", "push": "not_pushed",
                         "receiver_sync": "pull-required"}, "context_handles": [],
        "evidence_handles": [], "unresolved_items": ["receiver needs source sync"],
        "require_ack": True, "deadline": deadline()}
    result = ok(f, "handoff_work", args)
    assert result["data"]["source_state"]["receiver_sync"] == "pull-required"
    assert result["data"]["source_observation_class"] == "sender_reported"
    assert result["data"]["acknowledgement"] == "pending"
    assert scalar(f, "SELECT agent_slot_id FROM work_items WHERE work_item_id='mcp-work'") == "team-worker"
    wrong = dict(args, client_request_id="wrong-project", project_id="project-other")
    assert f.mcp.call("handoff_work", wrong)["isError"]


def test_known_transport_credential_is_never_persisted_as_intent(managed_work):
    f = managed_work
    assert f.mcp.call("revise_work", dict(revise_args(), changes={"goal": f.credential}))["isError"]
    assert scalar(f, "SELECT count(*) FROM work_item_revisions") == 0


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
                                    "acceptance.finalize", "source.read", "artifact.read"))
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
        "require_ack": True, "deadline": deadline()})
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
