"""Pure participant observation/projection on isolated PostgreSQL and Node SQLite."""
from __future__ import annotations

import pytest

from runtime.communication_delivery_observer import CommunicationDeliveryObserver
from runtime.errors import AuthorizationDenied, RevisionConflict
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send

comm = comm_fixture


def lose_outer_ack(f, monkeypatch):
    result = send(f)["data"]
    endpoint = f.authority._delivery_endpoints["endpoint-b"]
    deliver = endpoint.deliver
    inspect = endpoint.inspect_delivery

    def lost(*args, **kwargs):
        deliver(*args, **kwargs)
        raise OSError("controlled lost outer ACK after a genuine Node commit")

    with monkeypatch.context() as failure:
        failure.setattr(endpoint, "deliver", lost)
        failure.setattr(endpoint, "inspect_delivery", lambda *_args: {"status": "uncertain", "receipts": []})
        status = f.dispatcher.dispatch({"tenant_id": f.authority.tenant_id, "message_id": result["message_id"],
                                       "operation_id": result["operation_id"]})
    assert status["status"] == "uncertain" and len(f.drivers["b"].calls) == 1
    assert inspect(result["operation_id"], "uncertain")["status"] == "delivered"
    return result, endpoint


def observe(f, name, result, **kwargs):
    client = f.clients[name]
    return CommunicationDeliveryObserver(client.service).observe("project-alpha", result["operation_id"],
                                                                client.credential_provider(), **kwargs)


def test_native_ack_backfill_is_pure_and_does_not_create_an_agent_reply(comm, monkeypatch):
    sent, _endpoint = lose_outer_ack(comm, monkeypatch)
    before = observe(comm, "a", sent)
    assert before["delivery_state"] == "uncertain" and not before["native_acknowledged"]
    recovered = observe(comm, "b", sent, reconcile=True, expected_revision=1)
    assert recovered["delivery_state"] == "delivered" and recovered["native_acknowledged"]
    assert recovered["operation_id"] == sent["operation_id"] and recovered["attempts"] == 1
    assert recovered["model_consumption"] == "unconfirmed"
    assert len(comm.drivers["b"].calls) == 1
    assert observe(comm, "a", sent, reconcile=True)["native_acknowledged"]
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM delivery_attempts").fetchone() == (1,)


def test_third_party_cannot_query_or_probe_someone_elses_delivery(comm, monkeypatch):
    sent, endpoint = lose_outer_ack(comm, monkeypatch)
    monkeypatch.setattr(endpoint, "reconcile_delivery", lambda *_args: pytest.fail("unauthorized provider query"))
    with pytest.raises(AuthorizationDenied):
        observe(comm, "c", sent, reconcile=True)


def test_receiving_revision_cas_is_not_message_attempt_count(comm, monkeypatch):
    sent, endpoint = lose_outer_ack(comm, monkeypatch)
    monkeypatch.setattr(endpoint, "reconcile_delivery", lambda *_args: pytest.fail("stale receiver revision queried"))
    with pytest.raises(RevisionConflict):
        observe(comm, "a", sent, reconcile=True, expected_revision=2)


def test_current_reader_revocation_after_provider_read_prevents_projection(comm, monkeypatch):
    sent, endpoint = lose_outer_ack(comm, monkeypatch)
    query = endpoint.reconcile_delivery

    def revoke(invocation):
        result = query(invocation)
        with comm.authority._connect() as connection:
            connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (comm.authority.context.grant_ref,))
        return result

    monkeypatch.setattr(endpoint, "reconcile_delivery", revoke)
    with pytest.raises(AuthorizationDenied):
        observe(comm, "a", sent, reconcile=True)
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT state FROM delivery_messages WHERE message_id=%s", (sent["message_id"],)).fetchone() == ("uncertain",)
    assert len(comm.drivers["b"].calls) == 1


def test_original_receiver_replacement_cannot_move_uncertain_input(comm, monkeypatch):
    sent, endpoint = lose_outer_ack(comm, monkeypatch)
    monkeypatch.setattr(endpoint, "reconcile_delivery", lambda *_args: pytest.fail("replacement receiver queried"))
    with comm.authority._connect() as connection:
        connection.execute("UPDATE delivery_endpoints SET revision=revision+1 WHERE endpoint_id='endpoint-b'")
    result = observe(comm, "a", sent, reconcile=True)
    assert result["delivery_state"] == "uncertain" and not result["native_acknowledged"]
    assert result["reason_code"] == "original_receiver_binding_unavailable"
    assert len(comm.drivers["b"].calls) == 1


def test_provider_status_string_is_never_native_ack_evidence(comm, monkeypatch):
    sent, endpoint = lose_outer_ack(comm, monkeypatch)
    monkeypatch.setattr(endpoint, "reconcile_delivery", lambda *_args: {"status": "delivered", "receipts": []})
    result = observe(comm, "a", sent, reconcile=True)
    assert result["delivery_state"] == "uncertain" and not result["native_acknowledged"]


@pytest.mark.parametrize("failure", ["exception", "mismatch"])
def test_descriptor_failures_still_reauthorize_current_private_reader(comm, monkeypatch, failure):
    sent, endpoint = lose_outer_ack(comm, monkeypatch)
    descriptor = endpoint.descriptor

    def revoke():
        original = descriptor()
        with comm.authority._connect() as connection:
            connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (comm.authority.context.grant_ref,))
        if failure == "exception":
            raise OSError("controlled unavailable peer after read revocation")
        return original | {"node_id": "wrong-node"}

    monkeypatch.setattr(endpoint, "descriptor", revoke)
    with pytest.raises(AuthorizationDenied):
        observe(comm, "a", sent, reconcile=True)
    assert len(comm.drivers["b"].calls) == 1
