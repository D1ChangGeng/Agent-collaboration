"""Actual Message/Authority/Outbox PG, with controlled signed Native capacity.

No real Native process/model/Host is contacted. Startup ACK and input ACK are
independent; only ordinary Delivery may admit the actual original Message input.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
from types import SimpleNamespace

import pytest

from runtime.receiver_config import ReceiverClientConfig
from runtime.receiver_contract import native_generation
from runtime.receiver_crypto import key_fingerprint, sha256
from runtime.receiver_lifecycle_contract import (
    CapacityObservation,
    LifecycleReceipt,
    sign_observation,
    sign_receipt,
)
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send
from runtime_tests.test_communication_delivery_observer import lose_outer_ack
from runtime_tests.test_receiver_lifecycle_issuance_pg import PROJECT, RECEIVER, fact, snapshot
from runtime_tests.test_receiver_lifecycle_issuance_pg import registered as registered_fixture

comm = comm_fixture
registered = registered_fixture


def identity(f, message):
    return {"tenant_id": f.authority.tenant_id, "message_id": message["message_id"], "operation_id": message["operation_id"]}


def saved(f, message):
    with f.authority._connect() as connection:
        return connection.execute("SELECT payload FROM outbox WHERE tenant_id=%s AND operation_id=%s AND topic='message.delivery'",
            (f.authority.tenant_id, message["operation_id"])).fetchone()[0]


def due(f, message):
    with f.authority._connect() as connection:
        connection.execute("UPDATE delivery_messages SET next_attempt_at=clock_timestamp()-interval '1 second' WHERE operation_id=%s",
            (message["operation_id"],))


def install(f, *, initial="fresh", blocker="none", lose_ack=False, after_observe=None, after_execute=None):
    with f.authority._connect() as connection:
        selected = snapshot(f, connection)
    config = ReceiverClientConfig(selected.binding, selected.authority_key.key_id, selected.authority_key.revision,
        selected.authority_key.public_key, key_fingerprint(selected.authority_key.public_key),
        selected.binding.registration.boot_incarnation, 1)
    calls, permits = [], []
    state = SimpleNamespace(capacity=initial, enabled=True)

    def visible(source, phase):
        with f.authority._connect() as connection:
            row = connection.execute("SELECT payload FROM outbox WHERE operation_id=%s FOR UPDATE NOWAIT",
                (source.operation_ref,)).fetchone()[0]
            assert row["operation_id"] == source.operation_ref
            assert row["receiver_wake"]["lifecycle"]["phase"] == phase
            assert connection.execute("SELECT count(*) FROM delivery_receipts WHERE message_id=%s AND layer='runtime_dispatched'",
                (row["message_id"],)).fetchone() == (0,)
            return row

    def observe(challenge):
        c = challenge.challenge
        visible(c.source, "observing")
        calls.append("observe")
        capacity = fact(f, state=state.capacity)
        changes = {"blocker": blocker}
        if state.capacity == "existing":
            session = "controlled-message-wake-session"
            changes.update(native_session_ref=session, provider_generation=native_generation(
                capacity.driver_binding_id, asdict(capacity.binding), session))
        capacity = capacity.model_copy(update=changes)
        value = sign_observation(CapacityObservation(challenge_digest=sha256(c), request_id=c.request_id, nonce=c.nonce,
            source_digest=sha256(c.source), target=c.target, node_key_id=c.target.node_key_id, capacity=capacity), f.node_key)
        if after_observe:
            after_observe()
        return value

    def receipt(permit):
        p = permit.permit
        session, now = "controlled-message-wake-session", f.authority.canonical_now()
        return sign_receipt(LifecycleReceipt(source=p.plan.source, target=p.plan.target,
            driver_operation_id=p.plan.driver_operation_id, action=p.plan.action, permit_digest=sha256(p),
            semantic_digest=p.semantic_digest, request_id=p.request_id, nonce=p.nonce, node_key_id=p.plan.target.node_key_id,
            outcome="acknowledged", effect_possible=True, evidence_refs=("controlled-original-startup-only-ack",),
            native_session_ref=session, provider_generation=native_generation(p.plan.capacity.driver_binding_id,
                asdict(p.plan.capacity.binding), session), reason_code=None, observed_at=now, issued_at=now,
            deadline=now+timedelta(seconds=10)), f.node_key)

    def execute(permit, **_kwargs):
        visible(permit.permit.plan.source, "executing")
        calls.append("execute")
        permits.append(permit)
        state.capacity = "existing"
        if after_execute:
            after_execute()
        if lose_ack:
            raise OSError("controlled lost startup ACK; actual message input has not been submitted")
        return receipt(permit)

    def readback(permit, **_kwargs):
        visible(permit.permit.plan.source, "executing")
        calls.append("readback")
        assert permit == permits[0]
        return receipt(permit)

    f.authority._receiver_message_wake_policy = lambda receiver: receiver == RECEIVER and state.enabled
    f.authority._receiver_lifecycle_catalog = f.recovery.projects.catalog
    f.authority._receiver_lifecycle_transports = {RECEIVER: SimpleNamespace(config=config, signing_key=f.authority_key,
        observe=observe, execute=execute, readback=readback)}
    return calls, state


def test_message_bootstrap_reuses_actual_issuer_operation_and_does_not_create_recovery_or_reply(registered):
    f = registered
    calls, _state = install(f)
    message = send(f.comm)["data"]
    with f.authority._connect() as connection:
        before = connection.execute("SELECT count(*) FROM operations").fetchone()[0]
        command = connection.execute("SELECT command_json FROM delivery_messages WHERE operation_id=%s",
            (message["operation_id"],)).fetchone()[0]
    result = f.comm.dispatcher.dispatch(identity(f, message))
    assert result["status"] == "delivered" and calls == ["observe", "execute"]
    wake = saved(f, message)["receiver_wake"]
    assert wake["operation"]["operation_id"] == message["operation_id"] and wake["operation"]["kind"] == "message_wake"
    source = wake["lifecycle"]["plan"]["source"]
    assert source["command_id"] == command["command_id"] and source["command_digest"] == sha256(command)
    assert source["actor_address"] == message["from"] and source["profile"] == "root_manager"
    assert len(f.comm.drivers["b"].calls) == 1
    assert f.comm.dispatcher.dispatch(identity(f, message))["status"] == "delivered" and calls == ["observe", "execute"]
    with f.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM operations").fetchone()[0] == before
        assert connection.execute("SELECT count(*) FROM outbox WHERE topic='communication.receiver.recovery'").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM delivery_attempts WHERE operation_id=%s", (message["operation_id"],)).fetchone() == (1,)


def test_lost_startup_ack_reconciles_original_message_before_admitting_input(registered):
    f = registered
    calls, state = install(f, lose_ack=True)
    message = send(f.comm)["data"]
    assert f.comm.dispatcher.dispatch(identity(f, message))["status"] == "retry_wait"
    assert calls == ["observe", "execute"] and f.comm.drivers["b"].calls == []
    with f.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM delivery_receipts WHERE layer='runtime_acknowledged'").fetchone() == (0,)
    # A reconstructed executor and disabled new-wake policy can still read the
    # original fact. They cannot execute another preparation.
    state.enabled = False
    due(f, message)
    assert f.comm.dispatcher.dispatch(identity(f, message))["status"] == "delivered"
    assert calls == ["observe", "execute", "readback"] and len(f.comm.drivers["b"].calls) == 1
    assert saved(f, message)["receiver_wake"]["lifecycle"]["receipt"]["receipt"]["source"]["operation_ref"] == message["operation_id"]


def test_original_startup_read_survives_runtime_invoke_removal_but_message_input_does_not(registered):
    import json

    f = registered
    calls, _state = install(f, lose_ack=True)
    message = send(f.comm)["data"]
    assert f.comm.dispatcher.dispatch(identity(f, message))["status"] == "retry_wait"
    with f.authority._connect() as connection:
        permissions = connection.execute("SELECT permissions FROM grants WHERE grant_ref=%s", (f.recovery.projects.context.grant_ref,)).fetchone()[0]
        connection.execute("UPDATE grants SET permissions=%s WHERE grant_ref=%s",
            (json.dumps([permission for permission in permissions if permission != 'runtime.invoke']), f.recovery.projects.context.grant_ref))
    due(f, message)
    assert f.comm.dispatcher.dispatch(identity(f, message))["status"] == "blocked"
    assert calls == ["observe", "execute", "readback"] and f.comm.drivers["b"].calls == []
    assert saved(f, message)["receiver_wake"]["operation"]["state"] == "completed"


@pytest.mark.parametrize("blocker", ["approval", "draft", "question"])
def test_blockers_defer_the_original_prepared_attempt_without_preparing_or_input(registered, blocker):
    f = registered
    calls, _state = install(f, initial="existing", blocker=blocker)
    message = send(f.comm)["data"]
    for _ in range(2):
        due(f, message)
        assert f.comm.dispatcher.dispatch(identity(f, message))["status"] == "retry_wait"
    assert calls == ["observe", "observe"] and f.comm.drivers["b"].calls == []
    with f.authority._connect() as connection:
        assert connection.execute("SELECT attempts FROM delivery_messages WHERE operation_id=%s", (message["operation_id"],)).fetchone() == (1,)


@pytest.mark.parametrize("activation", ["message_only", "invoke"])
def test_message_only_and_disabled_policy_do_not_enter_lifecycle(registered, activation):
    f = registered
    calls, state = install(f)
    state.enabled = activation == "message_only"
    message = send(f.comm, activation=activation)["data"]
    assert f.comm.dispatcher.dispatch(identity(f, message))["status"] == "delivered"
    assert calls == [] and "receiver_wake" not in saved(f, message)
    assert len(f.comm.drivers["b"].calls) == (0 if activation == "message_only" else 1)


def test_old_unknown_native_input_blocks_new_session_creation_and_preserves_both_messages(registered, monkeypatch):
    f = registered
    old, _endpoint = lose_outer_ack(f.comm, monkeypatch)
    calls, _state = install(f)
    new = send(f.comm, content="A distinct accepted message after unknown input")["data"]
    assert f.comm.dispatcher.dispatch(identity(f, new))["status"] == "retry_wait"
    assert calls == [] and len(f.comm.drivers["b"].calls) == 1
    with f.authority._connect() as connection:
        assert connection.execute("SELECT state FROM delivery_messages WHERE operation_id=%s", (old["operation_id"],)).fetchone() == ("uncertain",)
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone() == (2,)


def test_reauthorization_after_capacity_read_stops_creation_and_input(registered):
    f = registered
    def revoke():
        with f.authority._connect() as connection:
            connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (f.recovery.projects.context.grant_ref,))
    calls, _state = install(f, after_observe=revoke)
    message = send(f.comm)["data"]
    assert f.comm.dispatcher.dispatch(identity(f, message))["status"] == "blocked"
    assert calls == ["observe"] and f.comm.drivers["b"].calls == []


def test_first_message_wake_does_not_coalesce_distinct_durable_message_bodies(registered):
    f = registered
    calls, _state = install(f)
    messages = [send(f.comm, content="Distinct durable body "+str(index))["data"] for index in range(20)]
    assert f.comm.dispatcher.dispatch(identity(f, messages[0]))["status"] == "delivered"
    assert calls == ["observe", "execute"]
    # Ready capacity on subsequent messages produces no second preparation.
    assert f.comm.dispatcher.dispatch(identity(f, messages[1]))["status"] == "delivered"
    assert calls == ["observe", "execute", "observe"]
    with f.authority._connect() as connection:
        rows = connection.execute("SELECT packet_json->>'content' FROM delivery_messages ORDER BY created_at,message_id").fetchall()
        assert {row[0] for row in rows} == {"Distinct durable body "+str(index) for index in range(20)}
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone() == (20,)
        assert connection.execute("SELECT count(*) FROM outbox WHERE topic='communication.receiver.recovery'").fetchone() == (0,)


def test_ordinary_agent_needs_message_permissions_and_opt_in_not_synthetic_management_authority(registered):
    import json

    f = registered
    actor = f.comm.clients["c"].service.context
    with f.authority._connect() as connection:
        connection.execute("UPDATE grants SET permissions=%s WHERE grant_ref=%s", (json.dumps([
            "profile.engineer", "message.send", "message.read", "runtime.invoke", "runtime.read",
            "collaborators.read", "project.read", "projects.read"]), actor.grant_ref))
    calls, _state = install(f)
    message = send(f.comm, caller="c")["data"]
    assert f.comm.dispatcher.dispatch(identity(f, message))["status"] == "delivered"
    source = saved(f, message)["receiver_wake"]["lifecycle"]["plan"]["source"]
    assert source["profile"] == "engineer" and source["grant_ref"] == actor.grant_ref and source["actor_address"] == message["from"]
    assert calls == ["observe", "execute"]
    with f.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM outbox WHERE topic='communication.receiver.recovery'").fetchone() == (0,)


def test_unresolved_original_management_startup_is_not_replaced_by_message_startup(registered):
    from runtime_tests.test_receiver_lifecycle_issuance_pg import allow, plan
    from runtime_tests.test_receiver_lifecycle_issuance_pg import submit as submit_prepare

    f = registered
    original = submit_prepare(f)
    plan(f, original)
    allow(f, original)  # A committed possible-effect permit, no reliable result.
    calls, _state = install(f)
    message = send(f.comm)["data"]
    assert f.comm.dispatcher.dispatch(identity(f, message))["status"] == "retry_wait"
    assert calls == [] and f.comm.drivers["b"].calls == []
    assert "receiver_wake" not in saved(f, message)


def test_active_reply_wait_precedes_message_wake_and_expiry_preserves_the_same_reply(registered):
    from runtime.communication_wait_ingress import reclaim_wait_ingress
    from runtime_tests.test_wait_ingress_recovery import enable, expire

    f = registered
    enable(f.comm)
    calls, _state = install(f)
    original = send(f.comm, caller="b", to="a", activation="message_only")["data"]
    with f.authority._connect() as connection:
        connection.execute("INSERT INTO communication_waits VALUES (%s,%s,'live-wake-wait',%s,%s,clock_timestamp()+interval '30 seconds')",
            (f.authority.tenant_id, PROJECT, original["from"], original["message_id"]))
    reply = send(f.comm, reply_to=[original["message_handle"]])["data"]
    assert f.comm.dispatcher.dispatch(identity(f, reply))["status"] == "retry_wait"
    assert calls == [] and "receiver_wake" not in saved(f, reply) and f.comm.drivers["b"].calls == []
    expire(f.comm)
    assert reclaim_wait_ingress(f.authority) == 1
    assert f.comm.dispatcher.dispatch(identity(f, reply))["status"] == "delivered"
    assert calls == ["observe", "execute"] and len(f.comm.drivers["b"].calls) == 1
    with f.authority._connect() as connection:
        assert connection.execute("SELECT reply_id FROM communication_replies WHERE request_id=%s", (original["message_id"],)).fetchall() == [(reply["message_id"],)]


def test_expired_message_still_reads_original_startup_without_admitting_expired_input(registered):
    import time

    f = registered
    calls, _state = install(f, lose_ack=True)
    deadline = f.authority.canonical_now() + timedelta(seconds=20)
    message = send(f.comm, deadline=deadline.isoformat())["data"]
    assert f.comm.dispatcher.dispatch(identity(f, message))["status"] == "retry_wait"
    time.sleep(max(0, (deadline-f.authority.canonical_now()).total_seconds()) + 0.05)
    due(f, message)
    assert f.comm.dispatcher.dispatch(identity(f, message))["status"] == "expired"
    assert calls == ["observe", "execute", "readback"] and f.comm.drivers["b"].calls == []
    assert saved(f, message)["receiver_wake"]["operation"]["state"] == "completed"


def test_core_message_plan_history_forbids_recreating_a_lost_native_namespace(registered, tmp_path):
    import json
    import os

    from runtime.receiver_lifecycle_contract import SignedLifecyclePermit
    from runtime_deployment.receiver_lifecycle import _namespace_authority
    from runtime_tests.probe_receiver_windows_backend import private_root

    f = registered
    install(f, lose_ack=True)
    message = send(f.comm)["data"]
    assert f.comm.dispatcher.dispatch(identity(f, message))["status"] == "retry_wait"
    signed = SignedLifecyclePermit.model_validate_json(json.dumps(saved(f, message)["receiver_wake"]["lifecycle"]["permit"]), strict=True)
    root = tmp_path / "private-node-capacity"
    if os.name == "nt":
        private_root(root)
    else:
        root.mkdir(mode=0o700)
    namespace = root / "lost-and-recreated"
    capacity = SimpleNamespace(authority=f.authority, binding=signed.permit.plan.capacity.binding,
        config=SimpleNamespace(binding=f.authority._receiver_lifecycle_transports[RECEIVER].config.binding),
        settings={"driver_journal":str(namespace / "driver.sqlite"), "binding_id":signed.permit.plan.capacity.driver_binding_id})
    with pytest.raises(PermissionError, match="history"):
        _namespace_authority(capacity, namespace, capacity.settings["binding_id"], capacity.binding, for_provision=True)
    assert not namespace.exists()


def test_policy_change_during_observation_defers_without_losing_the_original_message(registered):
    f = registered
    holder = {}
    def disable():
        holder["state"].enabled = False
    calls, state = install(f, after_observe=disable)
    holder["state"] = state
    message = send(f.comm)["data"]
    assert f.comm.dispatcher.dispatch(identity(f, message))["status"] == "retry_wait"
    assert calls == ["observe"] and f.comm.drivers["b"].calls == []
    assert saved(f, message)["receiver_wake"]["lifecycle"]["permit"] is None


def test_oauth_invoke_scope_is_required_before_accepting_a_native_message_but_not_message_only(registered, monkeypatch):
    import asyncio

    import httpx

    from runtime_tests.test_communication_client_oauth import (
        PREFIX,
        app_for,
        config,
        explicit_initialize,
    )
    from runtime_tests.test_project_http import IssuerFixture, claims

    f = registered
    cfg = config(monkeypatch, f.comm, enabled=True)
    calls, _state = install(f)
    all_claims = claims()
    limited = all_claims | {"scope": " ".join(scope for scope in all_claims["scope"].split() if scope != "runtime.invoke")}
    with f.authority._connect() as connection:
        before = connection.execute("SELECT count(*) FROM operations").fetchone()[0]

    async def exercise():
        async with IssuerFixture({"limited": limited}).client() as issuer:
            app = app_for(f.comm, cfg, issuer)
            explicit_initialize(f.comm)
            # Actual mounted OAuth service/PG; no background lifespan is needed
            # to establish that denied ingress committed no message/operation.
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as http:
                target = PREFIX+f"/projects/{PROJECT}/messages"
                headers = {"Authorization":"Bearer limited","Idempotency-Key":"no-invoke-message"}
                body = {"to":"collaborator:project-alpha:slot-b", "content":"Explicit permission-bound message", "activation":"invoke"}
                denied = await http.post(target,headers=headers,json=body)
                assert denied.status_code == 403,denied.text
                assert denied.json()["error"]["effect_state"] == "none"
                with f.authority._connect() as connection:
                    assert connection.execute("SELECT count(*) FROM operations").fetchone()[0] == before
                    assert connection.execute("SELECT count(*) FROM communication_messages").fetchone() == (0,)
                inbox = await http.post(target,headers=headers | {"Idempotency-Key":"message-only-without-invoke"},
                    json=body | {"activation":"message_only"})
                assert inbox.status_code == 201,inbox.text
    asyncio.run(exercise())
    assert calls == [] and f.comm.drivers["b"].calls == []


def test_enabled_wake_without_installed_catalog_is_explicitly_deferred(registered):
    f = registered
    calls, _state = install(f)
    del f.authority._receiver_lifecycle_catalog
    message = send(f.comm)["data"]
    assert f.comm.dispatcher.dispatch(identity(f, message))["status"] == "retry_wait"
    assert calls == [] and f.comm.drivers["b"].calls == []
    with f.authority._connect() as connection:
        assert connection.execute("SELECT last_error FROM delivery_messages WHERE operation_id=%s", (message["operation_id"],)).fetchone() == ("message_wake_project_catalog_unavailable",)


@pytest.mark.parametrize("external", [False, True])
def test_actual_maintenance_advances_original_message_wake_only_in_its_own_mode(registered, external):
    import asyncio
    from time import monotonic

    from runtime.communication_dispatch import maintain_communication_deliveries

    f = registered
    calls, _state = install(f)
    message = send(f.comm)["data"]
    f.authority._communication_maintenance_mode = "external" if external else "auto"

    async def exercise():
        if external:
            await maintain_communication_deliveries(f.recovery.projects.service)
            return
        task = asyncio.create_task(maintain_communication_deliveries(f.recovery.projects.service))
        end = monotonic()+25
        try:
            while True:
                with f.authority._connect() as connection:
                    status = connection.execute("SELECT state FROM delivery_messages WHERE operation_id=%s", (message["operation_id"],)).fetchone()[0]
                if status == "delivered":
                    break
                assert not task.done() and monotonic()<end
                await asyncio.sleep(0.1)
        finally:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
    asyncio.run(exercise())
    assert calls == ([] if external else ["observe","execute"])
    assert len(f.comm.drivers["b"].calls) == (0 if external else 1)


def test_expiry_does_not_drop_pending_original_startup_readback_work(registered):
    import time

    from runtime.communication_dispatch import _pending

    f = registered
    calls, _state = install(f, lose_ack=True)
    transport = f.authority._receiver_lifecycle_transports[RECEIVER]
    actual_read = transport.readback
    def unavailable(*_args, **_kwargs):
        raise OSError("controlled original journal read is temporarily unavailable")
    transport.readback = unavailable
    deadline = f.authority.canonical_now()+timedelta(seconds=20)
    message = send(f.comm,deadline=deadline.isoformat())["data"]
    assert f.comm.dispatcher.dispatch(identity(f,message))["status"] == "retry_wait"
    time.sleep(max(0,(deadline-f.authority.canonical_now()).total_seconds())+0.05)
    due(f,message)
    assert f.comm.dispatcher.dispatch(identity(f,message))["status"] == "expired"
    assert saved(f,message)["receiver_wake"]["operation"]["state"] == "unknown"
    due(f,message)
    assert identity(f,message) in _pending(f.authority,[],4)
    transport.readback = actual_read
    assert f.comm.dispatcher.dispatch(identity(f,message))["status"] == "expired"
    assert calls == ["observe","execute","readback"] and f.comm.drivers["b"].calls == []
    assert saved(f,message)["receiver_wake"]["operation"]["state"] == "completed"
