"""Recovery audit/authorization on isolated PostgreSQL, with controlled providers.

These are actual operations/outbox/reader and revision checks. Receiver lifecycle
callbacks and Native ACKs are explicitly synthetic; no model or production
contact is used or qualified by this suite.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import timedelta

import pytest

from runtime.auth import LocalCredentialAuthenticator
from runtime.delivery import DeliveryDispatcher, DeliveryRejected
from runtime.domain import DomainAuthority
from runtime.errors import AuthorizationDenied, IdempotencyConflict, RevisionConflict
from runtime.project_service import ProjectService
from runtime.receiver_recovery_operations import ReceiverRecoveryOperations, RecoveryRequest
from runtime.surfaces import SharedService
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send
from runtime_tests.test_communication_delivery_observer import lose_outer_ack

comm = comm_fixture
PROJECT = "project-alpha"
RECEIVER = "endpoint-b"


def service(f, actor="a"):
    client = f.clients[actor]
    return ReceiverRecoveryOperations(client.service), client.credential_provider()


def request(action="prepare_receiver", *, revision=1, operation=None, **fields):
    value = {"action": action, "expected_revision": revision,
             "reason": "Explicit isolated engineering recovery request"}
    if operation is not None:
        value["operation_ref"] = operation
    return value | fields


def submit(f, body=None, *, actor="a", identity=None, receiver=RECEIVER):
    recovery, credential = service(f, actor)
    operation = recovery.submit(PROJECT, receiver, body or request(),
                                identity or "recovery-" + uuid.uuid4().hex, credential)
    return recovery, credential, operation


def counts(f):
    with f.authority._connect() as connection:
        return tuple(connection.execute("SELECT count(*) FROM " + table).fetchone()[0]
                     for table in ("operations", "outbox", "delivery_messages", "communication_replies"))


def test_submit_commits_separate_recovery_operation_before_provider_inspection(comm, monkeypatch):
    endpoint = comm.authority._delivery_endpoints[RECEIVER]
    entered = []
    queued = {}

    def observe():
        # A different real database connection must be able to lock the audit
        # and receiver while the external callback is executing. The command
        # must commit its marker before external I/O instead of holding writers.
        with comm.authority._connect() as connection:
            assert connection.execute("SELECT operation_id FROM operations WHERE operation_id=%s",
                                      (queued["operation_id"],)).fetchone() == (queued["operation_id"],)
            assert connection.execute("SELECT operation_id FROM outbox WHERE operation_id=%s FOR UPDATE NOWAIT",
                                      (queued["operation_id"],)).fetchone() == (queued["operation_id"],)
            assert connection.execute("SELECT revision FROM delivery_endpoints WHERE endpoint_id=%s FOR UPDATE NOWAIT",
                                      (RECEIVER,)).fetchone() == (1,)
        entered.append(True)
        return {"state": "idle", "session_ref": "controlled-existing-session",
                "observation": "native_driver_readback"}

    monkeypatch.setattr(endpoint, "inspect_runtime", observe)
    monkeypatch.setattr(endpoint, "prepare_runtime", lambda: pytest.fail("inspection invoked lifecycle mutation"))
    before = counts(comm)
    recovery, credential, operation = submit(comm, request("inspect"))
    queued.update(operation)
    assert operation["kind"] == "recovery" and operation["state"] == "queued"
    assert operation["receiver_ref"] == RECEIVER and operation["binding_epoch"] == 1
    assert operation["effect_state"] == "committed" and entered == []
    after = counts(comm)
    assert after == (before[0] + 1, before[1] + 1, before[2], before[3])
    done = recovery.advance(PROJECT, operation["operation_id"], credential)
    assert done["operation_id"] == operation["operation_id"]
    assert done["state"] in {"completed", "accepted"}
    assert done["effect_state"] != "none" and entered == [True]
    assert recovery.read(PROJECT, operation["operation_id"], credential) == done
    assert recovery.advance(PROJECT, operation["operation_id"], credential) == done
    assert entered == [True] and not comm.drivers["b"].calls


def test_idempotent_replay_precedes_receiving_revision_cas_but_not_authorization(comm):
    identity = "stable-recovery-request"
    body = request("inspect")
    recovery, credential, first = submit(comm, body, identity=identity)
    with comm.authority._connect() as connection:
        connection.execute("UPDATE delivery_endpoints SET revision=revision+1 WHERE endpoint_id=%s", (RECEIVER,))
    duplicate = recovery.submit(PROJECT, RECEIVER, body, identity, credential)
    assert duplicate["operation_id"] == first["operation_id"]
    with comm.authority._connect() as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                           (comm.authority.context.grant_ref,))
    with pytest.raises(AuthorizationDenied):
        recovery.submit(PROJECT, RECEIVER, body, identity, credential)


def test_changed_recovery_body_with_same_key_is_conflict_not_another_action(comm):
    identity = "same-key-different-reason"
    body = request()
    recovery, credential, first = submit(comm, body, identity=identity)
    before = counts(comm)
    with pytest.raises(IdempotencyConflict):
        recovery.submit(PROJECT, RECEIVER, body | {"reason": "Different canonical recovery intent"}, identity, credential)
    assert counts(comm) == before
    assert recovery.read(PROJECT, first["operation_id"], credential)["state"] == "queued"


@pytest.mark.parametrize("action", ["prepare_receiver", "resume_receiver", "rebind_receiver", "retry_delivery"])
def test_ordinary_participant_does_not_gain_receiver_management(comm, action):
    original = send(comm)["data"]
    body = request(action, operation=original["operation_id"] if action == "retry_delivery" else None)
    if action == "rebind_receiver":
        body["target_endpoint_ref"] = "endpoint-c"
    before = counts(comm)
    with pytest.raises(AuthorizationDenied):
        submit(comm, body, actor="b")
    assert counts(comm) == before


def test_expected_revision_is_receiver_binding_not_attempt_or_team_revision(comm):
    original = send(comm)["data"]
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT attempts FROM delivery_messages WHERE operation_id=%s",
                                  (original["operation_id"],)).fetchone() == (0,)
    before = counts(comm)
    with pytest.raises(RevisionConflict):
        submit(comm, request("prepare_receiver", revision=0))
    assert counts(comm) == before


def test_reconcile_has_its_own_audit_but_never_dispatches_or_infers_agent_reply(comm, monkeypatch):
    original, _endpoint = lose_outer_ack(comm, monkeypatch)
    monkeypatch.setattr(DeliveryDispatcher, "dispatch", lambda *_args, **_kwargs: pytest.fail("pure reconcile dispatched input"))
    recovery, credential, operation = submit(comm, request("reconcile", operation=original["operation_id"]), actor="b")
    assert operation["operation_id"] != original["operation_id"] and operation["kind"] == "recovery"
    done = recovery.advance(PROJECT, operation["operation_id"], credential)
    assert done["state"] in {"completed", "accepted"}
    assert len(comm.drivers["b"].calls) == 1
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM delivery_attempts").fetchone() == (1,)
        assert connection.execute("SELECT state FROM delivery_messages WHERE operation_id=%s",
                                  (original["operation_id"],)).fetchone() == ("delivered",)


def test_reconcile_private_operation_requires_actual_participant_acl(comm):
    original = send(comm)["data"]
    before = counts(comm)
    with pytest.raises(AuthorizationDenied):
        submit(comm, request("reconcile", operation=original["operation_id"]), actor="c")
    assert counts(comm) == before


def test_retry_advances_the_original_queued_delivery_at_most_once(comm):
    original = send(comm)["data"]
    recovery, credential, operation = submit(comm, request("retry_delivery", operation=original["operation_id"]))
    assert operation["operation_id"] != original["operation_id"]
    done = recovery.advance(PROJECT, operation["operation_id"], credential)
    assert done["state"] in {"completed", "accepted"}
    assert len(comm.drivers["b"].calls) == 1
    assert recovery.advance(PROJECT, operation["operation_id"], credential) == done
    assert len(comm.drivers["b"].calls) == 1
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM delivery_messages").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM delivery_attempts").fetchone() == (1,)


def test_unknown_original_input_cannot_be_retried_into_a_new_attempt(comm, monkeypatch):
    original, _endpoint = lose_outer_ack(comm, monkeypatch)
    try:
        recovery, credential, operation = submit(comm, request("retry_delivery", operation=original["operation_id"]))
    except DeliveryRejected:
        operation = None
    if operation is not None:
        done = recovery.advance(PROJECT, operation["operation_id"], credential)
        assert done["state"] in {"unknown", "definitively_rejected"}
    assert len(comm.drivers["b"].calls) == 1
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM delivery_attempts").fetchone() == (1,)
        assert connection.execute("SELECT state FROM delivery_messages WHERE operation_id=%s",
                                  (original["operation_id"],)).fetchone() == ("uncertain",)


def test_revoked_management_actor_cannot_execute_queued_provider_effect(comm, monkeypatch):
    endpoint = comm.authority._delivery_endpoints[RECEIVER]
    monkeypatch.setattr(endpoint, "prepare_runtime", lambda: pytest.fail("revoked management invoked provider"))
    recovery, credential, operation = submit(comm)
    with comm.authority._connect() as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                           (comm.authority.context.grant_ref,))
    with pytest.raises(AuthorizationDenied):
        recovery.advance(PROJECT, operation["operation_id"], credential)


def test_receiving_revision_change_after_queue_stops_provider_effect(comm, monkeypatch):
    endpoint = comm.authority._delivery_endpoints[RECEIVER]
    monkeypatch.setattr(endpoint, "prepare_runtime", lambda: pytest.fail("stale recovery selection invoked provider"))
    recovery, credential, operation = submit(comm)
    with comm.authority._connect() as connection:
        connection.execute("UPDATE delivery_endpoints SET revision=revision+1 WHERE endpoint_id=%s", (RECEIVER,))
    try:
        result = recovery.advance(PROJECT, operation["operation_id"], credential)
    except RevisionConflict:
        return
    assert result["state"] in {"superseded", "definitively_rejected"}


def test_previous_submitting_marker_is_preserved_and_provider_is_not_reentered(comm, monkeypatch):
    endpoint = comm.authority._delivery_endpoints[RECEIVER]
    calls = []

    def unexpected_reentry():
        calls.append(True)
        pytest.fail("durable in-flight lifecycle marker was reentered")

    monkeypatch.setattr(endpoint, "prepare_runtime", unexpected_reentry)
    recovery, credential, operation = submit(comm)
    # Explicit previous-executor fixture: its accepted effect boundary is no
    # longer observable. Resuming a client request must preserve this marker.
    marker = operation | {"state": "submitting", "effect_state": "native_possible", "revision": 2}
    with comm.authority._connect() as connection:
        connection.execute("UPDATE outbox SET payload=jsonb_set(payload,'{operation}',%s::jsonb) "
                           "WHERE operation_id=%s", (json.dumps(marker), operation["operation_id"]))
    first = recovery.advance(PROJECT, operation["operation_id"], credential)
    assert first == marker
    second = recovery.advance(PROJECT, operation["operation_id"], credential)
    assert recovery.read(PROJECT, operation["operation_id"], credential) == first
    assert second == first and calls == []


@pytest.mark.parametrize("action", ["prepare_receiver", "resume_receiver", "rebind_receiver"])
def test_legacy_lifecycle_callback_without_actual_fence_is_typed_unsupported(comm, monkeypatch, action):
    endpoint = comm.authority._delivery_endpoints[RECEIVER]
    monkeypatch.setattr(endpoint, "prepare_runtime", lambda: pytest.fail("unfenced lifecycle callback invoked"))
    fields = {}
    if action == "rebind_receiver":
        from runtime.delivery import DeliveryService
        from runtime.delivery_models import EndpointBindingRequest
        from runtime_tests.test_delivery import command

        # A valid same-Slot replacement still needs an installed fenced port.
        comm.authority._delivery_endpoints["endpoint-b-replacement"] = endpoint
        DeliveryService(comm.authority, comm.authority._delivery_endpoints).bind_endpoint(
            command(comm.authority, "message.bind", "endpoint-b-replacement"), EndpointBindingRequest(
                scope_id="local-scope", agent_slot_id="slot-b", expires_at=comm.authority.canonical_now() + timedelta(minutes=5)))
        fields["target_endpoint_ref"] = "endpoint-b-replacement"
    recovery, credential, operation = submit(comm, request(action, **fields))
    result = recovery.advance(PROJECT, operation["operation_id"], credential)
    assert result["state"] == "definitively_rejected"
    assert "unsupported" in result["reason_code"]
    assert result["effect_state"] == "committed"
    assert not comm.drivers["b"].calls


def test_refreshed_caller_grant_cannot_substitute_for_revoked_original_issuer(comm, monkeypatch):
    endpoint = comm.authority._delivery_endpoints[RECEIVER]
    monkeypatch.setattr(endpoint, "prepare_runtime", lambda: pytest.fail("new caller grant substituted original recovery issuer"))
    _original_service, credential, operation = submit(comm)
    original = comm.clients["a"].service
    replacement = "grant:recovery-replacement"
    with comm.authority._connect() as connection:
        connection.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,"
            "scope_id,permissions,expires_at) SELECT %s,tenant_id,principal_ref,authority_id,authority_incarnation,"
            "scope_id,permissions,expires_at FROM grants WHERE grant_ref=%s", (replacement, original.context.grant_ref))
        connection.execute("UPDATE collaboration_memberships SET grant_ref=%s WHERE agent_slot_id='local-slot'", (replacement,))
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (original.context.grant_ref,))
    context = replace(original.context, grant_ref=replacement)
    authority = DomainAuthority(comm.dsn, context=context)
    authority._delivery_endpoints = comm.authority._delivery_endpoints
    refreshed = ProjectService(SharedService(authority, LocalCredentialAuthenticator(context)),
                               original.catalog, profile=original.profile)
    recovery = ReceiverRecoveryOperations(refreshed)
    # The refreshed caller is valid for current receiver management; only the
    # already accepted command's issuer is revoked.
    assert recovery.read(PROJECT, operation["operation_id"], credential)["state"] == "queued"
    try:
        result = recovery.advance(PROJECT, operation["operation_id"], credential)
    except AuthorizationDenied:
        return
    assert result["state"] == "definitively_rejected"


@pytest.mark.parametrize("invalid", [
    {"action": "reconcile"}, {"action": "retry_delivery"}, {"action": "rebind_receiver"},
    {"expected_revision": True}, {"expected_revision": -1}, {"sender": "forged-root"},
    {"actor": "forged-root"}, {"reason": "   "}, {"action": "complete_task"},
])
def test_recovery_request_rejects_missing_effect_scope_and_forged_identity(invalid):
    with pytest.raises(ValueError):
        RecoveryRequest.model_validate(request() | invalid)
