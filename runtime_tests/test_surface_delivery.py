"""Delivery through the same authenticated surface, with real PG/SQLite."""
import asyncio
import hashlib
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import psycopg
import pytest

from runtime.auth import LocalCredentialAuthenticator
from runtime.domain import DomainAuthority
from runtime.surfaces import SharedService
from runtime_tests.test_delivery import counts, query
from runtime_tests.test_surfaces import cli, http_process, request, sdk_call
from runtime_tests.test_surfaces import pg as pg  # noqa: PLC0414


@pytest.fixture
def delivery_setup(tmp_path):
    from runtime_tests.test_delivery import setup
    yield from setup.__wrapped__(tmp_path)


def message_payload(*, activation="message_only", revision=1):
    return {"endpoint_id": "endpoint", "binding_revision": revision, "packet": {
        "work_item_id": "work", "target_scope_id": "local-scope", "target_agent_slot_id": "local-slot",
        "accepted_revision": 0, "goal": "Surface delivery fixture", "accepted_state_summary": "caller context only",
        "request": "Bounded fixture request", "constraints": ["fixture"],
        "source_baseline": "delivery-fixture-baseline", "context_digests": [],
        "expected_response": "layered receipt", "required_evidence": ["actual SQLite Inbox"],
        "activation": activation, "deadline": (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
    }}


def call(service, token, kind, target, *, payload=None, revision=0):
    value = request(kind, target=target, payload=payload, revision=revision, target_kind="message")
    return value, service.handle(value, token).model_dump(mode="json")


def services(f):
    token = "surface-test-token-" + uuid.uuid4().hex
    context = replace(f.authority.context, credential_hash=hashlib.sha256(token.encode()).hexdigest())
    sender = DomainAuthority(f.dsn, context=context, delivery_endpoints=f.service.endpoints)
    sender_service = SharedService(sender, LocalCredentialAuthenticator(context))
    operator_context = replace(context, principal_ref="fixture:delivery-operator", grant_ref="grant:delivery-operator")
    operator = DomainAuthority(f.dsn, context=operator_context, delivery_endpoints=f.service.endpoints)
    operator.bootstrap_local_grant(("delivery.scan", "delivery.dispatch", "message.read"))
    return sender_service, SharedService(operator, LocalCredentialAuthenticator(operator_context)), token


def test_message_bind_send_read_and_operator_dedup_share_domain(delivery_setup):
    f = delivery_setup
    sender, operator, token = services(f)
    binding = {"scope_id": "local-scope", "agent_slot_id": "local-slot",
               "expires_at": (datetime.now(UTC) + timedelta(minutes=3)).isoformat()}
    bind, result = call(sender, token, "message.bind", "endpoint", payload=binding, revision=1)
    assert result["ok"] and result["result"]["revision"] == 2
    assert sender.handle(bind, token).result["duplicate"]
    submitted, result = call(sender, token, "message.send", "surface-message",
                             payload=message_payload(activation="invoke", revision=2))
    assert result["ok"] and result["result"]["state"] == "message_queued"
    original_operation = result["result"]["operation_id"]
    baseline = counts(f)
    assert sender.handle(submitted, token).result["duplicate"]
    changed = submitted | {"payload": submitted["payload"] | {"binding_revision": 1}}
    assert sender.handle(changed, token).error.code == "IDEMPOTENCY_CONFLICT"
    assert counts(f) == baseline
    _, denied = call(sender, token, "delivery.scan", "pending", payload={"scope_id": "local-scope"})
    assert denied["error"]["code"] == "AUTHORIZATION_DENIED"
    _, scan = call(operator, token, "delivery.scan", "pending", payload={"scope_id": "local-scope"})
    assert scan["result"]["pending"] == [{"tenant_id": f.authority.tenant_id, "message_id": "surface-message",
                                           "operation_id": original_operation}]
    assert counts(f) == baseline  # scan creates no command/operation/outbox.
    _, wrong_revision = call(operator, token, "delivery.dispatch", "surface-message",
                              payload={"operation_id": original_operation}, revision=9)
    assert wrong_revision["error"]["code"] == "REVISION_CONFLICT" and counts(f) == baseline
    dispatch, audit = call(operator, token, "delivery.dispatch", "surface-message",
                           payload={"operation_id": original_operation})
    assert audit["ok"] and audit["result"]["operator_audit"]["state"] == "delivery_dispatch_authorized"
    assert audit["result"]["operator_audit"]["operation_id"] != original_operation
    assert audit["result"]["delivery"]["state"] == "delivered" and audit["result"]["operator_pending"] is False
    assert f.driver.calls == [original_operation]
    after = counts(f)
    replay = operator.handle(dispatch, token)
    assert replay.ok and replay.result["operator_audit"]["duplicate"] and counts(f) == after
    assert f.driver.calls == [original_operation]
    changed = dispatch | {"payload": {"operation_id": "different-operation"}}
    assert operator.handle(changed, token).error.code == "IDEMPOTENCY_CONFLICT"
    _, observed = call(operator, token, "message.read", "surface-message")
    assert observed["result"]["message"]["state"] == "delivered"
    assert observed["result"]["message"]["receipt_high_water"] == "response_received"
    assert [row[0] for row in observed["result"]["receipts"]] == [
        "accepted_by_authority", "runtime_dispatched", "target_inbox_committed", "runtime_acknowledged", "response_received",
    ]
    assert query(f, "SELECT count(*) FROM outbox WHERE topic='delivery.dispatch.authorized'") == [(1,)]
    query(f, "UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref='grant:delivery-operator'")
    assert operator.handle(dispatch, token).error.code == "AUTHORIZATION_DENIED"


def test_operator_authorization_cannot_replace_revoked_sender(delivery_setup):
    f = delivery_setup
    sender, operator, token = services(f)
    _, sent = call(sender, token, "message.send", "revoked-sender", payload=message_payload(activation="invoke"))
    query(f, "UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (f.authority.context.grant_ref,))
    _, dispatched = call(operator, token, "delivery.dispatch", "revoked-sender",
                          payload={"operation_id": sent["result"]["operation_id"]})
    assert dispatched["ok"]  # Only the operator's own authorization was committed.
    _, read = call(operator, token, "message.read", "revoked-sender")
    assert read["result"]["message"]["state"] == "blocked" and f.driver.calls == []
    assert read["result"]["message"]["receipt_high_water"] == "accepted_by_authority"
    assert not sender.handle(request("message.read", target="revoked-sender", target_kind="message"), token).ok
    assert operator.handle(request("delivery.scan", target="pending", target_kind="message",
                                   payload={"scope_id": "other-scope"}), token).error.code == "AUTHORIZATION_DENIED"


def test_transport_payload_cannot_construct_endpoint(delivery_setup):
    sender, _, token = services(delivery_setup)
    value = request("message.bind", target="endpoint", target_kind="message", revision=1,
                    payload={"scope_id": "local-scope", "agent_slot_id": "local-slot",
                             "expires_at": (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
                             "endpoint": {"driver": "import arbitrary module"}})
    assert sender.handle(value, token).error.code == "INPUT_INVALID"
    assert sender.handle(value, None).error.code == "UNAUTHENTICATED"


@pytest.mark.parametrize("phase", ["after_authorize", "after_dispatch"])
def test_same_operator_command_recovers_unfinished_outbox(delivery_setup, monkeypatch, phase):
    f = delivery_setup
    sender, operator, token = services(f)
    _, sent = call(sender, token, "message.send", "operator-crash", payload=message_payload(activation="invoke"))
    command = request("delivery.dispatch", target="operator-crash", target_kind="message",
                      payload={"operation_id": sent["result"]["operation_id"]})

    class CoreInterrupted(BaseException):
        pass

    def interrupt(*_args):
        raise CoreInterrupted()

    with monkeypatch.context() as fault:
        fault.setattr(operator.delivery_operations, phase, interrupt)
        with pytest.raises(CoreInterrupted):
            operator.handle(command, token)
    assert query(f, "SELECT count(*) FROM outbox WHERE topic='delivery.dispatch.authorized' AND delivered_at IS NULL") == [(1,)]
    assert len(f.driver.calls) == (1 if phase == "after_dispatch" else 0)
    replay = operator.handle(command, token)
    assert replay.ok and replay.result["operator_audit"]["duplicate"]
    assert replay.result["delivery"]["state"] == "delivered" and replay.result["operator_pending"] is False
    assert len(f.driver.calls) == 1
    assert query(f, "SELECT count(*) FROM outbox WHERE topic='delivery.dispatch.authorized'") == [(1,)]
    operator.handle(command, token)
    assert len(f.driver.calls) == 1


def test_busy_operator_request_is_recoverable_without_new_audit(delivery_setup):
    f = delivery_setup
    sender, operator, token = services(f)
    _, sent = call(sender, token, "message.send", "operator-busy", payload=message_payload(activation="invoke"))
    identity = {"tenant_id": f.authority.tenant_id, "message_id": "operator-busy",
                "operation_id": sent["result"]["operation_id"]}
    import json
    lock = int.from_bytes(hashlib.sha256(json.dumps(["delivery-dispatch", identity], sort_keys=True).encode()).digest()[:8],
                          "big", signed=True)
    command = request("delivery.dispatch", target="operator-busy", target_kind="message",
                      payload={"operation_id": identity["operation_id"]})
    with psycopg.connect(f.dsn, autocommit=True) as blocker:
        blocker.execute("SELECT pg_advisory_lock(%s)", (lock,))
        try:
            pending = operator.handle(command, token)
            assert pending.ok and pending.result["operator_pending"] and f.driver.calls == []
        finally:
            blocker.execute("SELECT pg_advisory_unlock(%s)", (lock,))
    finished = operator.handle(command, token)
    assert finished.result["operator_audit"]["duplicate"] and not finished.result["operator_pending"]
    assert f.driver.calls == [identity["operation_id"]]
    assert query(f, "SELECT count(*) FROM outbox WHERE topic='delivery.dispatch.authorized'") == [(1,)]


def test_unknown_native_outcome_does_not_complete_operator_outbox(delivery_setup):
    f = delivery_setup
    sender, operator, token = services(f)
    f.driver.fail = True
    _, sent = call(sender, token, "message.send", "operator-unknown", payload=message_payload(activation="invoke"))
    command, reply = call(operator, token, "delivery.dispatch", "operator-unknown",
                          payload={"operation_id": sent["result"]["operation_id"]})
    assert reply["result"]["operator_pending"] and reply["result"]["delivery"]["state"] == "uncertain"
    assert len(f.driver.calls) == 1
    repeated = operator.handle(command, token)
    assert repeated.result["operator_pending"] and len(f.driver.calls) == 1
    assert query(f, "SELECT count(*) FROM outbox WHERE topic='delivery.dispatch.authorized' AND delivered_at IS NULL") == [(1,)]
    assert query(f, "SELECT count(*) FROM outbox WHERE topic='delivery.dispatch.authorized'") == [(1,)]


@pytest.mark.parametrize("change", ["grant_expired", "grant_revoked", "command_expired"])
def test_operator_current_auth_is_required_before_final_status_and_readback(delivery_setup, monkeypatch, change):
    f = delivery_setup
    sender, operator, token = services(f)
    _, sent = call(sender, token, "message.send", "operator-auth-lapse", payload=message_payload(activation="invoke"))
    command = request("delivery.dispatch", target="operator-auth-lapse", target_kind="message",
                      payload={"operation_id": sent["result"]["operation_id"]})
    if change == "command_expired":
        command["deadline"] = (datetime.now(UTC) + timedelta(seconds=1)).isoformat()
    original = operator.delivery_operations.dispatcher.dispatch

    def dispatch_then_revoke(identity):
        result = original(identity)
        if change == "grant_revoked":
            query(f, "UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref='grant:delivery-operator'")
        elif change == "grant_expired":
            query(f, "UPDATE grants SET expires_at=clock_timestamp()-interval '1 second' WHERE grant_ref='grant:delivery-operator'")
        else:
            time.sleep(max(0, (datetime.fromisoformat(command["deadline"]) - datetime.now(UTC)).total_seconds()) + 0.03)
        return result

    monkeypatch.setattr(operator.delivery_operations.dispatcher, "dispatch", dispatch_then_revoke)
    refused = operator.handle(command, token)
    assert not refused.ok and refused.error.code == "AUTHORIZATION_DENIED" and refused.result is None
    assert len(f.driver.calls) == 1
    assert query(f, "SELECT count(*) FROM outbox WHERE topic='delivery.dispatch.authorized' "
                   "AND delivered_at IS NULL AND NOT(payload ? 'delivery_readback')") == [(1,)]
    repeated = operator.handle(command, token)
    assert repeated.error.code == "AUTHORIZATION_DENIED" and repeated.result is None and len(f.driver.calls) == 1


def test_real_mcp_cli_http_delivery_with_only_http_endpoint_injection(pg, tmp_path):
    authority, (config, environment, secret) = pg
    authority.bootstrap_local_grant(("work_item.create", "message.send", "message.read", "delivery.manage",
                                     "delivery.scan", "delivery.dispatch"))
    assert cli(config, environment, request(target="work", payload={"source_baseline": "delivery-fixture-baseline"}))[1]["ok"]
    bootstrap = tmp_path / "trusted_surface_bootstrap.py"
    journal = tmp_path / "surface-node.sqlite"
    bootstrap.write_text(
        "from runtime.node import NodeJournal\nfrom runtime.delivery_node import LocalNodeEndpoint\n"
        "from runtime.surface_entry import main\n"
        f"endpoint=LocalNodeEndpoint(NodeJournal({str(journal)!r}),'local-scope','local-slot')\n"
        "raise SystemExit(main(delivery_endpoints={'endpoint':endpoint}))\n", encoding="utf-8",
    )
    http_environment = environment | {"ACS_TEST_SURFACE_BOOTSTRAP": str(bootstrap)}
    with http_process(config, http_environment) as url:
        headers = {"X-ACS-Credential": secret}
        bind = request("message.bind", target="endpoint", target_kind="message", payload={
            "scope_id": "local-scope", "agent_slot_id": "local-slot",
            "expires_at": (datetime.now(UTC) + timedelta(minutes=3)).isoformat()})
        assert httpx.post(url + "/v1/commands", json=bind, headers=headers).json()["ok"]
        message = request("message.send", target="process-message", target_kind="message", payload=message_payload())
        _, _, results, _ = asyncio.run(sdk_call(config, environment, [message]))
        assert results[0].structured_content["ok"]
        operation_id = results[0].structured_content["result"]["operation_id"]
        process, duplicate = cli(config, environment, message)
        assert process.returncode == 0 and duplicate["result"]["duplicate"]
        command = request("delivery.dispatch", target="process-message", target_kind="message",
                          payload={"operation_id": operation_id})
        assert httpx.post(url + "/v1/commands", json=command, headers=headers).json()["ok"]
        _, _, observed, _ = asyncio.run(sdk_call(config, environment, [
            request("message.read", target="process-message", target_kind="message")]))
        message_readback = observed[0].structured_content["result"]
        assert message_readback["message"]["state"] == "delivered"
        assert message_readback["message"]["receipt_high_water"] == "target_inbox_committed"
        assert [row[0] for row in message_readback["receipts"]] == ["accepted_by_authority", "target_inbox_committed"]
