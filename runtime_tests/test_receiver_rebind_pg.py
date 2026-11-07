"""Real isolated Core PG rebind; signed capacity/Native protocol are controlled.

No model, production endpoint or installed Host is qualified by these tests.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from runtime.delivery import DeliveryService
from runtime.delivery_models import EndpointBindingRequest
from runtime.delivery_node import LocalNodeEndpoint
from runtime.errors import (
    AcceptanceGuardFailed,
    AuthorizationDenied,
    IdempotencyConflict,
    RevisionConflict,
)
from runtime.node import NodeJournal
from runtime.receiver_config import ReceiverClientConfig
from runtime.receiver_contract import native_generation
from runtime.receiver_crypto import key_fingerprint, sha256, sign
from runtime.receiver_domain import EndpointRegistrationCommand
from runtime.receiver_lifecycle_contract import CapacityObservation, sign_observation
from runtime.receiver_lifecycle_domain import current_lifecycle_endpoint
from runtime.receiver_rebind import lifecycle_receiver
from runtime_tests.test_communication import AcceptingDriver, call, send
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_delivery_observer import lose_outer_ack
from runtime_tests.test_communication_delivery_observer import observe as observe_message
from runtime_tests.test_receiver_lifecycle_issuance_pg import (
    PROJECT,
    RECEIVER,
    command,
    fact,
    payload,
    proof,
)
from runtime_tests.test_receiver_lifecycle_issuance_pg import registered as registered_fixture

comm = comm_fixture
registered = registered_fixture
TARGET = "endpoint-b-ready-target"


def add_target(f, tmp_path):
    driver = AcceptingDriver()
    identity = f.endpoint.identity
    endpoint = LocalNodeEndpoint(NodeJournal(tmp_path / "target.sqlite", machine_id=identity.machine_id,
        node_id=identity.node_id, boot_incarnation=identity.boot_incarnation), "local-scope", "slot-b", driver)
    # One actual enrolled Node may own several private receiving endpoints.
    f.authority._delivery_endpoints[TARGET] = endpoint
    DeliveryService(f.authority, f.authority._delivery_endpoints).bind_endpoint(
        command(f.authority, "message.bind", "message", TARGET), EndpointBindingRequest(
            scope_id="local-scope", agent_slot_id="slot-b", expires_at=f.authority.canonical_now() + timedelta(minutes=5)))
    registration = f.registration.model_copy(update={"registration_id": "registered-target", "endpoint_id": TARGET,
        "endpoint_revision": 1})
    signature = sign(f.node_key, registration)
    cmd = command(f.node, "endpoint.register", "endpoint", TARGET)
    f.node.register_receiver_endpoint(cmd, EndpointRegistrationCommand(registration=registration, registration_signature=signature,
        proof=proof(f, cmd, {"registration": registration.model_dump(mode="json"), "registration_signature": signature})))
    return driver


def submit_rebind(f, *, key=None, target=TARGET):
    return f.recovery.submit(PROJECT, RECEIVER, {"action": "rebind_receiver", "expected_revision": 1,
        "target_endpoint_ref": target, "reason": "Explicit isolated receiving replacement"}, key or uuid4().hex, f.secret)


def endpoints(f):
    with f.authority._connect() as connection:
        return connection.execute("SELECT endpoint_id,revision,status FROM delivery_endpoints ORDER BY endpoint_id").fetchall()


def install(f, *, state="existing", blocker="none", input_state=None, after_observe=None, wrong_signature=False):
    with f.authority._connect() as connection:
        selected = current_lifecycle_endpoint(f.authority, connection.cursor(), TARGET, 1, journal_generation=1)
    config = ReceiverClientConfig(selected.binding, selected.authority_key.key_id, selected.authority_key.revision,
        selected.authority_key.public_key, key_fingerprint(selected.authority_key.public_key),
        selected.binding.registration.boot_incarnation, 1)
    calls = []

    def observe(challenge):
        source = challenge.challenge.source
        # The committed exact target challenge is independently visible.
        with f.authority._connect() as connection:
            row = connection.execute("SELECT payload FROM outbox WHERE operation_id=%s FOR UPDATE NOWAIT",
                (source.operation_ref,)).fetchone()[0]
            assert lifecycle_receiver(row) == (TARGET, 1)
            assert row["lifecycle"]["phase"] == "observing"
        calls.append("observe")
        capacity = fact(f, state=state)
        updates = {"blocker": blocker}
        if input_state is not None:
            updates["input_state"] = input_state
        if state == "existing":
            session = "controlled-prepared-target-session"
            updates.update(native_session_ref=session, provider_generation=native_generation(
                capacity.driver_binding_id, asdict(capacity.binding), session))
        capacity = capacity.model_copy(update=updates)
        observed = CapacityObservation(challenge_digest=sha256(challenge.challenge), request_id=challenge.challenge.request_id,
            nonce=challenge.challenge.nonce, source_digest=sha256(source), target=challenge.challenge.target,
            node_key_id=challenge.challenge.target.node_key_id, capacity=capacity)
        if after_observe:
            after_observe()
        from nacl.signing import SigningKey

        return sign_observation(observed, SigningKey.generate() if wrong_signature else f.node_key)

    def forbidden(*_args, **_kwargs):
        pytest.fail("rebind crossed a Native execute/readback boundary")

    transport = SimpleNamespace(config=config, signing_key=f.authority_key, observe=observe, execute=forbidden, readback=forbidden)
    f.recovery.authority._receiver_lifecycle_transports = {TARGET: transport}
    return calls


@pytest.mark.parametrize("target", ["endpoint-c", RECEIVER])
def test_rebind_rejects_different_slot_and_self_without_ledger_writes(registered, target):
    f = registered
    with f.authority._connect() as connection:
        before = connection.execute("SELECT count(*) FROM operations").fetchone()
    with pytest.raises((AuthorizationDenied, ValueError)):
        submit_rebind(f, target=target)
    with f.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM operations").fetchone() == before


@pytest.mark.parametrize("configured", [False, True])
def test_ready_target_rebind_retains_unknown_input_and_only_new_messages_use_new_epoch(registered, tmp_path, monkeypatch, configured):
    f = registered
    original, _old = lose_outer_ack(f.comm, monkeypatch)
    if configured:
        call(f.comm, "a", "configure_team", members=[{"agent_slot_id": "slot-b", "principal_ref": "agent:b",
            "role": "specialist", "display_name": "Stable B", "endpoint_id": RECEIVER}], prepare_native=False)
    driver = add_target(f, tmp_path)
    key = "stable-rebind"
    operation = submit_rebind(f, key=key)
    accepted = payload(f, operation)
    assert accepted["command"]["payload"]["receiver_rebind"] == accepted["rebind_selection"]
    calls = install(f)
    with f.authority._connect() as connection:
        old_message = connection.execute("SELECT to_jsonb(m) FROM delivery_messages m WHERE operation_id=%s",
            (original["operation_id"],)).fetchone()[0]
        old_attempts = connection.execute("SELECT to_jsonb(a) FROM delivery_attempts a ORDER BY attempt_id").fetchall()
        members = connection.execute("SELECT to_jsonb(m) FROM collaboration_team_members m").fetchall()
        grants = connection.execute("SELECT to_jsonb(g) FROM grants g ORDER BY grant_ref").fetchall()
        team = connection.execute("SELECT revision,definition FROM collaboration_teams").fetchone()
    result = f.recovery.advance(PROJECT, operation["operation_id"], f.secret)
    assert result["state"] == "completed" and result["effect_state"] == "committed"
    assert result["receiver_ref"] == RECEIVER and result["binding_epoch"] == 1
    assert calls == ["observe"] and driver.calls == [] and len(f.comm.drivers["b"].calls) == 1
    assert (RECEIVER, 2, "retired") in endpoints(f) and (TARGET, 2, "active") in endpoints(f)
    assert f.recovery.advance(PROJECT, operation["operation_id"], f.secret) == result
    assert submit_rebind(f, key=key) == result and calls == ["observe"]
    with pytest.raises(IdempotencyConflict):
        f.recovery.submit(PROJECT, RECEIVER, accepted["request"] | {"reason": "Changed intent"}, key, f.secret)
    with f.authority._connect() as connection:
        assert connection.execute("SELECT to_jsonb(m) FROM delivery_messages m WHERE operation_id=%s",
            (original["operation_id"],)).fetchone()[0] == old_message
        assert connection.execute("SELECT to_jsonb(a) FROM delivery_attempts a ORDER BY attempt_id").fetchall() == old_attempts
        assert connection.execute("SELECT to_jsonb(m) FROM collaboration_team_members m").fetchall() == members
        assert connection.execute("SELECT to_jsonb(g) FROM grants g ORDER BY grant_ref").fetchall() == grants
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone() == (0,)
        if configured:
            updated = connection.execute("SELECT revision,definition FROM collaboration_teams").fetchone()
            expected = json.loads(json.dumps(team[1]))
            next(member for member in expected["members"] if member["agent_slot_id"] == "slot-b")["endpoint_id"] = TARGET
            assert updated == (team[0] + 1, expected)
    # Pure old-result observation stays unknown; it cannot query the replacement.
    observed = observe_message(f.comm, "a", original, reconcile=True)
    assert observed["delivery_state"] == "uncertain" and observed["reason_code"] == "original_receiver_binding_unavailable"
    new = send(f.comm, content="New explicit input after receiving replacement")["data"]
    with f.authority._connect() as connection:
        assert connection.execute("SELECT endpoint_id,binding_revision,state FROM delivery_messages WHERE operation_id=%s",
            (new["operation_id"],)).fetchone() == (TARGET, 2, "queued")
        assert connection.execute("SELECT count(*) FROM delivery_attempts WHERE operation_id=%s", (new["operation_id"],)).fetchone() == (0,)


@pytest.mark.parametrize(("state", "blocker", "input_state", "reason"), [
    ("fresh", "none", None, "lifecycle_rebind_prepare_target_first"),
    ("existing", "none", "busy", "lifecycle_input_busy"),
    ("existing", "approval", "unknown", "lifecycle_blocker_approval"),
    ("existing", "draft", "unknown", "lifecycle_blocker_draft"),
])
def test_rebind_never_prepares_fresh_or_blocked_target(registered, tmp_path, state, blocker, input_state, reason):
    f = registered
    add_target(f, tmp_path)
    operation = submit_rebind(f)
    before = endpoints(f)
    calls = install(f, state=state, blocker=blocker, input_state=input_state)
    result = f.recovery.advance(PROJECT, operation["operation_id"], f.secret)
    assert result["state"] == "deferred" and result["reason_code"] == reason
    assert endpoints(f) == before and calls == ["observe"]
    assert payload(f, operation)["lifecycle"]["permit"] is None


@pytest.mark.parametrize("drift", ["source", "target", "registration", "connection", "team", "revoke"])
def test_rebind_current_selection_and_original_authority_are_rechecked_after_host_read(registered, tmp_path, drift):
    f = registered
    if drift == "team":
        call(f.comm, "a", "configure_team", members=[{"agent_slot_id": "slot-b", "principal_ref": "agent:b",
            "endpoint_id": RECEIVER}], prepare_native=False)
    add_target(f, tmp_path)
    operation = submit_rebind(f)

    def change():
        with f.authority._connect() as connection:
            if drift in {"source", "target"}:
                connection.execute("UPDATE delivery_endpoints SET revision=revision+1 WHERE endpoint_id=%s",
                    (RECEIVER if drift == "source" else TARGET,))
            elif drift == "registration":
                connection.execute("UPDATE delivery_endpoint_registrations SET status='retired' WHERE endpoint_id=%s", (TARGET,))
            elif drift == "connection":
                connection.execute("UPDATE deployment_connection_refs SET revision=revision+1")
            elif drift == "team":
                connection.execute("UPDATE collaboration_teams SET revision=revision+1")
            else:
                connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                    (f.recovery.projects.context.grant_ref,))

    calls = install(f, after_observe=change)
    try:
        result = f.recovery.advance(PROJECT, operation["operation_id"], f.secret)
    except (AcceptanceGuardFailed, AuthorizationDenied, RevisionConflict):
        result = None
    if result:
        assert result["state"] == "deferred"
    assert calls == ["observe"]
    assert all(status == "active" for _endpoint, _revision, status in endpoints(f))
    assert payload(f, operation)["operation"]["state"] != "completed"
    assert payload(f, operation)["lifecycle"]["permit"] is None


def test_rebind_bad_signature_cannot_publish_or_create_native_permit(registered, tmp_path):
    f = registered
    add_target(f, tmp_path)
    operation = submit_rebind(f)
    before = endpoints(f)
    install(f, wrong_signature=True)
    result = f.recovery.advance(PROJECT, operation["operation_id"], f.secret)
    assert result["state"] == "deferred" and endpoints(f) == before


def test_accepted_rebind_continues_without_bearer_using_frozen_target(registered, tmp_path):
    from runtime.receiver_lifecycle_maintenance import (
        advance_lifecycle_work,
        claim_lifecycle_work,
        finish_lifecycle_work,
    )

    f = registered
    add_target(f, tmp_path)
    operation = submit_rebind(f)
    calls = install(f)
    f.recovery.authority._receiver_lifecycle_catalog = f.recovery.projects.catalog
    work, = claim_lifecycle_work(f.recovery.authority)
    assert work.receiver_id == RECEIVER and work.operation_ref == operation["operation_id"]
    result = advance_lifecycle_work(f.recovery.projects.service, work)
    finish_lifecycle_work(f.recovery.authority, work)
    assert result["state"] == "completed" and calls == ["observe"]
    assert claim_lifecycle_work(f.recovery.authority) == []


def test_publication_holds_slot_fence_and_rolls_back_all_receiving_writes(registered, tmp_path, monkeypatch):
    import psycopg

    f = registered
    call(f.comm, "a", "configure_team", members=[{"agent_slot_id": "slot-b", "principal_ref": "agent:b",
        "endpoint_id": RECEIVER}], prepare_native=False)
    add_target(f, tmp_path)
    operation = submit_rebind(f)
    calls = install(f)
    before = endpoints(f)
    with f.authority._connect() as connection:
        team = connection.execute("SELECT revision,definition FROM collaboration_teams").fetchone()
    original_save = f.recovery._save
    fenced = []

    def fail_publication(cursor, payload, result, *, done=False):
        if result["reason_code"] == "receiver_rebound":
            with pytest.raises(psycopg.errors.LockNotAvailable), f.authority._connect() as writer:
                writer.execute("SELECT 1 FROM agent_slots WHERE agent_slot_id='slot-b' FOR UPDATE NOWAIT")
            fenced.append(True)
            raise RuntimeError("controlled failure after receiving writes before Outbox commit")
        return original_save(cursor, payload, result, done=done)

    with monkeypatch.context() as failure:
        failure.setattr(f.recovery, "_save", fail_publication)
        with pytest.raises(RuntimeError, match="controlled failure"):
            f.recovery.advance(PROJECT, operation["operation_id"], f.secret)
    assert endpoints(f) == before and fenced == [True]
    with f.authority._connect() as connection:
        assert connection.execute("SELECT revision,definition FROM collaboration_teams").fetchone() == team
        assert connection.execute("SELECT count(*) FROM domain_events WHERE to_state='receiver.rebound'").fetchone() == (0,)
    assert f.recovery.advance(PROJECT, operation["operation_id"], f.secret)["state"] == "completed"
    assert calls == ["observe", "observe"]  # Read-only observations can repeat; no Native action exists.


def test_old_lifecycle_execution_fails_after_rebind_but_original_history_read_remains_authorized(registered, tmp_path):
    from runtime.receiver_lifecycle_issuance import require_current_execution
    from runtime.receiver_lifecycle_readback import resolve_original_lifecycle_read
    from runtime_tests.test_receiver_lifecycle_issuance_pg import allow, plan
    from runtime_tests.test_receiver_lifecycle_issuance_pg import submit as submit_prepare

    f = registered
    old = submit_prepare(f)
    plan(f, old)
    permit = allow(f, old).permit
    possible = payload(f, old)
    add_target(f, tmp_path)
    operation = submit_rebind(f)
    install(f)
    assert f.recovery.advance(PROJECT, operation["operation_id"], f.secret)["state"] == "completed"
    with pytest.raises((AcceptanceGuardFailed, RevisionConflict)), f.authority._connect() as connection:
        require_current_execution(f.recovery, connection.cursor(), PROJECT, old["operation_id"], permit, journal_generation=1)
    assert resolve_original_lifecycle_read(f.recovery, permit) == permit.permit.plan.source
    assert payload(f, old) == possible  # Retirement cannot settle or rewrite an old possible effect.
