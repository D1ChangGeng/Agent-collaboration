"""Recipient-scoped notices over disposable PostgreSQL and local OAuth HTTP.

The Native drivers and issuer are explicit fixtures. Positive ACKs below come
from the notice's real delivery ledger in this isolated schema, not a model.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from runtime.auth import LocalCredentialAuthenticator
from runtime.client_contracts import ClientContracts
from runtime.communication_client_notices import (
    NoticeQueryService,
    _created_at,
    _notice_sequence,
    _reason,
)
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_client_storage import adopt_client_storage
from runtime.communication_faults import queue_communication_notices
from runtime.communication_http import CommunicationHttpError
from runtime.delivery import DeliveryDispatcher, DeliveryService
from runtime.delivery_models import EndpointBindingRequest
from runtime.delivery_node import LocalNodeEndpoint
from runtime.domain import DomainAuthority
from runtime.errors import (
    AuthorizationDenied,
    IdempotencyConflict,
    InvalidToolArgument,
    NotFound,
    RevisionConflict,
)
from runtime.node import NodeJournal
from runtime.project_http import ProjectHttpSettings
from runtime.project_service import ProjectService
from runtime.surfaces import SharedService
from runtime_tests.test_communication import AcceptingDriver, call, send, wait
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_client_oauth import app_for, config
from runtime_tests.test_communication_delivery_observer import lose_outer_ack, observe
from runtime_tests.test_communication_faults import (
    fail_b,
    identity,
    manager_chain,
    notice_deliveries,
    refuse,
)
from runtime_tests.test_delivery import command
from runtime_tests.test_identity_root_management import owner_client as owner_client_fixture
from runtime_tests.test_project_http import IssuerFixture, claims

comm = comm_fixture
owner_client = owner_client_fixture
PROJECT = "project-alpha"
PREFIX = "/api/communication/v1"
CONTRACTS = ClientContracts()


class NoticeClient(CommunicationClientService, NoticeQueryService):
    pass


def client(f, name="a"):
    current = f.clients[name]
    return NoticeClient(current.service, current.credential_provider())


def adopt(f):
    from runtime.communication_client_notice_storage import adopt_notice_storage
    from runtime.communication_client_viewer_storage import adopt_viewer_storage

    with f.authority._connect() as connection:
        adopt_client_storage(connection)
        adopt_viewer_storage(connection)
        adopt_notice_storage(connection)


@pytest.fixture
def notices(comm):
    adopt(comm)
    return comm


def own_notice(f, name="a"):
    page = client(f, name).notices(PROJECT)
    assert len(page["items"]) == 1, page
    return page["items"][0]


def counts(f):
    with f.authority._connect() as connection:
        return tuple(connection.execute("SELECT count(*) FROM " + table).fetchone()[0]
            for table in ("communication_messages", "communication_replies", "delivery_attempts", "delivery_receipts"))


def foreign_project_notice(f, tmp_path):
    """A separate real namespace creates an interleaved internal notice ordinal."""
    project, scope = "project-notice-foreign", "notice-foreign-scope"
    tenant = f.authority.tenant_id
    with f.authority._connect() as connection:
        connection.execute("INSERT INTO scopes(scope_id,tenant_id,status) VALUES (%s,%s,'active')", (scope, tenant))
        connection.execute("INSERT INTO collaboration_projects(tenant_id,project_id,root_id,scope_id,name,context_manifest) "
            "VALUES (%s,%s,'notice-foreign-root',%s,'Foreign fixture namespace','{}')", (tenant, project, scope))
        for name in ("sender", "target"):
            slot, principal, grant = "notice-foreign-" + name, "agent:notice-foreign-" + name, "grant:notice-foreign-" + name
            connection.execute("INSERT INTO agent_slots(agent_slot_id,tenant_id,scope_id,status) VALUES (%s,%s,%s,'active')",
                               (slot, tenant, scope))
            connection.execute("INSERT INTO grants SELECT %s,tenant_id,%s,authority_id,authority_incarnation,%s,permissions,expires_at,NULL "
                "FROM grants WHERE grant_ref=%s", (grant, principal, scope, f.authority.context.grant_ref))
            connection.execute("INSERT INTO collaboration_memberships VALUES (%s,%s,%s,%s,'engineer',%s)",
                               (tenant, project, principal, grant, slot))
    token = "fixture-foreign-notice-" + uuid.uuid4().hex
    context = replace(f.authority.context, principal_ref="agent:notice-foreign-sender", grant_ref="grant:notice-foreign-sender",
        agent_slot_id="notice-foreign-sender", trusted_client=False, credential_hash=hashlib.sha256(token.encode()).hexdigest())
    authority = DomainAuthority(f.dsn, context=context)
    driver = AcceptingDriver()
    driver.prepare = refuse
    endpoint = LocalNodeEndpoint(NodeJournal(tmp_path / "foreign-notice.sqlite"), scope, "notice-foreign-target", driver)
    authority._delivery_endpoints = {"notice-foreign-endpoint": endpoint}
    delivery = DeliveryService(authority, authority._delivery_endpoints)
    delivery.bind_endpoint(command(authority, "message.bind", "notice-foreign-endpoint"),
        EndpointBindingRequest(scope_id=scope, agent_slot_id="notice-foreign-target",
                               expires_at=authority.canonical_now() + timedelta(hours=1)))
    projects = ProjectService(SharedService(authority, LocalCredentialAuthenticator(context)), f.clients["a"].service.catalog, profile="engineer")
    state, sent, _actions = projects.execute("send_message", {"project_id": project,
        "to": "collaborator:" + project + ":notice-foreign-target", "content": "PRIVATE foreign namespace body",
        "activation": "invoke", "client_request_id": "foreign-notice-message"}, token)
    assert state == "accepted"
    assert DeliveryDispatcher(delivery).dispatch(identity(f, sent))["status"] == "blocked"
    with f.authority._connect() as connection:
        sequence, code = connection.execute("SELECT sequence,code FROM communication_notices WHERE tenant_id=%s AND project_id=%s",
                                            (tenant, project)).fetchone()
    assert code == "native_pre_call_rejected"
    assert not driver.calls
    return project, sequence


@pytest.mark.parametrize("reference", [None, "", "message:project-alpha:a", "notification:project-other:communication-1",
    "notification:project-alpha:communication-0", "notification:project-alpha:communication-01",
    "notification:project-alpha:communication--1", "notification:project-alpha:communication-9223372036854775808"])
def test_notice_handle_requires_current_project_positive_sequence(reference):
    with pytest.raises(InvalidToolArgument):
        _notice_sequence(PROJECT, reference)


def test_notice_source_timestamp_and_reason_are_not_fabricated_or_echoed():
    assert _notice_sequence(PROJECT, "notification:project-alpha:communication-17") == 17
    assert _created_at(None) is None
    assert _created_at(datetime(2026, 11, 6, tzinfo=UTC)) == "2026-11-06T00:00:00+00:00"
    with pytest.raises(ValueError):
        _created_at(datetime(2026, 11, 6, tzinfo=UTC).replace(tzinfo=None))
    assert _reason("private-session-details") == "delivery_unconfirmed"
    assert _reason("native_pre_call_rejected") == "native_pre_call_rejected"


def test_notice_list_and_detail_are_recipient_only_and_have_no_read_side_effect(notices):
    f = notices
    sent = fail_b(f)
    before = counts(f)
    value = own_notice(f)
    CONTRACTS.validate("Notice", value)
    assert value["source"] == "acs_system" and value["kind"] == "communication_obstacle"
    assert value["message_ref"] == sent["message_handle"] and value["receiver_ref"] is None
    assert value["created_at"] is not None and datetime.fromisoformat(value["created_at"]).utcoffset() is not None
    assert not value["seen"] and value["revision"] >= 1
    assert "PRIVATE" not in str(value) and value["own_delivery"]["state"] == "not_requested"
    assert re.fullmatch(r"notification:project-alpha:notice-[a-f0-9]{32}", value["notice_handle"])
    with f.authority._connect() as connection:
        sequence = connection.execute("SELECT sequence FROM communication_notices WHERE tenant_id=%s AND message_id=%s",
                                      (f.authority.tenant_id, sent["message_id"])).fetchone()[0]
    legacy = f"notification:{PROJECT}:communication-{sequence}"
    assert client(f).notice(PROJECT, legacy) == value
    assert value["notice_handle"] != legacy
    assert client(f).notice(PROJECT, value["notice_handle"]) == value
    assert client(f, "b").notices(PROJECT)["items"] == []
    assert client(f, "c").notices(PROJECT)["items"] == []
    with pytest.raises(NotFound):
        client(f, "c").notice(PROJECT, value["notice_handle"])
    assert counts(f) == before and not any(driver.calls for driver in f.drivers.values())


def test_forwarded_manager_notice_does_not_grant_original_private_message(notices):
    f = notices
    call(f, "a", "configure_team", prepare_native=False,
         members=[{"agent_slot_id": "slot-c", "principal_ref": "agent:c"}])
    f.drivers["c"].prepare = refuse
    sent = send(f, "b", "c", "PRIVATE B-to-C body must stay private")["data"]
    assert f.dispatcher.dispatch(identity(f, sent))["status"] == "blocked"
    notice = own_notice(f)
    assert notice["message_ref"] == sent["message_handle"]
    assert notice["own_delivery"]["state"] == "pending"
    assert "PRIVATE" not in str(notice) and notice["receiver_ref"] is None
    with pytest.raises(AuthorizationDenied):
        client(f).read_message(PROJECT, sent["message_handle"])
    assert client(f, "b").notices(PROJECT)["items"] == []
    assert counts(f)[1] == 0 and not any(driver.calls for driver in f.drivers.values())


def test_reconciled_original_ack_never_becomes_notice_own_native_ack(notices, monkeypatch):
    f = notices
    sent, _endpoint = lose_outer_ack(f, monkeypatch)
    before = own_notice(f)
    assert before["own_delivery"]["state"] == "not_requested"
    reconciled = observe(f, "a", sent, reconcile=True, expected_revision=1)
    assert reconciled["native_acknowledged"]
    after = client(f).notice(PROJECT, before["notice_handle"])
    assert after["own_delivery"]["state"] == "not_requested"
    assert after["own_delivery"]["operation_ref"] is None and after["own_delivery"]["evidence_ref"] is None
    assert counts(f)[1] == 0 and len(f.drivers["b"].calls) == 1 and not f.drivers["a"].calls


def test_notice_own_delivery_ack_is_exact_and_does_not_answer_original(notices):
    f = notices
    call(f, "a", "configure_team", prepare_native=False,
         members=[{"agent_slot_id": "slot-b", "principal_ref": "agent:b"}])
    sent = fail_b(f)
    first = own_notice(f)
    queue_communication_notices(f.authority)
    [(notice_id, operation, _state)] = notice_deliveries(f)
    queued = client(f).notice(PROJECT, first["notice_handle"])
    assert queued["own_delivery"]["state"] == "pending" and queued["own_delivery"]["operation_ref"] == operation
    assert operation != sent["operation_id"]
    assert f.dispatcher.dispatch(identity(f, {"message_id": notice_id, "operation_id": operation}))["status"] == "delivered"
    delivered = client(f).notice(PROJECT, first["notice_handle"])
    assert delivered["own_delivery"]["state"] == "accepted"
    assert delivered["own_delivery"]["operation_ref"] == operation and delivered["own_delivery"]["evidence_ref"]
    assert delivered["revision"] > queued["revision"]
    assert not delivered["seen"] and counts(f)[1] == 0
    assert wait(f, "a", sent["message_handle"])["state"] == "timeout"
    assert len(f.drivers["a"].calls) == 1


def test_notice_seen_replays_original_full_result_before_stale_cas(notices):
    f, own = notices, client(notices)
    call(f, "a", "configure_team", prepare_native=False,
         members=[{"agent_slot_id": "slot-b", "principal_ref": "agent:b"}])
    fail_b(f)
    queue_communication_notices(f.authority)
    original = own_notice(f)
    request = {"seen": True}
    saved = own.mark_notice_seen(PROJECT, original["notice_handle"], request,
                                expected_revision=original["revision"], client_request_id="seen-original")
    assert saved["seen"] and saved["revision"] > original["revision"]
    [(notice_id, operation, _state)] = notice_deliveries(f)
    assert f.dispatcher.dispatch(identity(f, {"message_id": notice_id, "operation_id": operation}))["status"] == "delivered"
    assert own.notice(PROJECT, original["notice_handle"])["own_delivery"]["state"] == "accepted"
    assert own.mark_notice_seen(PROJECT, original["notice_handle"], request,
        expected_revision=original["revision"], client_request_id="seen-original") == saved
    with pytest.raises(IdempotencyConflict):
        own.mark_notice_seen(PROJECT, original["notice_handle"], {"seen": False},
            expected_revision=original["revision"], client_request_id="seen-original")
    with pytest.raises(RevisionConflict):
        own.mark_notice_seen(PROJECT, original["notice_handle"], request,
            expected_revision=original["revision"], client_request_id="seen-stale")
    current = own.notice(PROJECT, original["notice_handle"])
    unseen = own.mark_notice_seen(PROJECT, original["notice_handle"], {"seen": False},
        expected_revision=current["revision"], client_request_id="seen-reset")
    assert not unseen["seen"] and unseen["revision"] > current["revision"] and counts(f)[1] == 0


def test_notice_pages_are_bounded_identity_bound_and_invalidate_on_seen_change(notices):
    f, own = notices, client(notices)
    first_sent, second_sent = fail_b(f), fail_b(f)
    first = own.notices(PROJECT, limit=1)
    assert first["page"]["next_cursor"] and len(first["page"]["next_cursor"]) <= 2048
    assert len(first["page"]["snapshot_id"]) <= 512
    second = own.notices(PROJECT, limit=1, cursor=first["page"]["next_cursor"], snapshot_id=first["page"]["snapshot_id"])
    assert second["page"]["snapshot_id"] == first["page"]["snapshot_id"]
    assert [first["items"][0]["message_ref"], second["items"][0]["message_ref"]] == [first_sent["message_handle"], second_sent["message_handle"]]
    for args in ({"snapshot_id": first["page"]["next_cursor"]},
                 {"cursor": first["page"]["next_cursor"], "snapshot_id": first["page"]["next_cursor"]}):
        with pytest.raises(CommunicationHttpError) as invalid:
            own.notices(PROJECT, limit=1, **args)
        assert invalid.value.code == "cursor_invalid"
    with pytest.raises(CommunicationHttpError, match="Restart"):
        client(f, "b").notices(PROJECT, cursor=first["page"]["next_cursor"])
    item = first["items"][0]
    own.mark_notice_seen(PROJECT, item["notice_handle"], {"seen": True}, expected_revision=item["revision"], client_request_id="page-seen")
    with pytest.raises(CommunicationHttpError) as conflict:
        own.notices(PROJECT, cursor=first["page"]["next_cursor"])
    assert conflict.value.code == "cursor_invalid"
    assert [item["message_ref"] for item in own.notices(PROJECT, seen=False)["items"]] == [second_sent["message_handle"]]
    assert counts(f)[1] == 0 and not any(driver.calls for driver in f.drivers.values())


def test_public_notice_ids_are_stable_opaque_and_do_not_expose_interleaved_foreign_ordinals(notices, tmp_path):
    f, own = notices, client(notices)
    first_sent = fail_b(f)
    hidden_project, hidden_sequence = foreign_project_notice(f, tmp_path)
    second_sent = fail_b(f)
    with f.authority._connect() as connection:
        rows = connection.execute("SELECT n.message_id,n.sequence,v.notice_ref FROM communication_notices n "
            "JOIN communication_client_notice_versions v USING(tenant_id,project_id,message_id,recipient) "
            "WHERE n.tenant_id=%s AND n.project_id=%s ORDER BY n.sequence", (f.authority.tenant_id, PROJECT)).fetchall()
    assert [row[0] for row in rows] == [first_sent["message_id"], second_sent["message_id"]]
    assert rows[0][1] < hidden_sequence < rows[1][1]
    first = own.notices(PROJECT, limit=1)
    second = own.notices(PROJECT, limit=1, cursor=first["page"]["next_cursor"], snapshot_id=first["page"]["snapshot_id"])
    values = [first["items"][0], second["items"][0]]
    assert [value["message_ref"] for value in values] == [first_sent["message_handle"], second_sent["message_handle"]]
    refs = [value["notice_handle"] for value in values]
    assert len(set(refs)) == 2
    for value, (_message, sequence, public) in zip(values, rows, strict=True):
        assert re.fullmatch(r"notification:project-alpha:notice-[a-f0-9]{32}", value["notice_handle"])
        assert value["notice_handle"] == f"notification:{PROJECT}:{public}"
        assert "sequence" not in value and "high" not in value and "after" not in value
        legacy = f"notification:{PROJECT}:communication-{sequence}"
        assert own.notice(PROJECT, legacy) == value
        assert own.notice(PROJECT, value["notice_handle"]) == value
    for token, maximum in ((first["page"]["snapshot_id"], 512), (first["page"]["next_cursor"], 2048)):
        assert token and len(token) <= maximum
        assert token not in {str(row[1]) for row in rows} and str(hidden_sequence) != token
        # Public continuation is an authenticated ciphertext, not readable
        # JSON/base64 carrying the database-wide sequence/high-water values.
        with pytest.raises((UnicodeDecodeError, json.JSONDecodeError)):
            json.loads(base64.urlsafe_b64decode(token))
    assert hidden_project not in json.dumps(first | {"next": second}) and "PRIVATE foreign" not in str(values)
    original = values[0]
    legacy = f"notification:{PROJECT}:communication-{rows[0][1]}"
    seen = own.mark_notice_seen(PROJECT, legacy, {"seen": True},
        expected_revision=original["revision"], client_request_id="opaque-legacy-seen")
    assert seen["notice_handle"] == original["notice_handle"] and seen["seen"]
    assert own.mark_notice_seen(PROJECT, original["notice_handle"], {"seen": True},
        expected_revision=original["revision"], client_request_id="opaque-legacy-seen") == seen
    adopt(f)
    assert [value["notice_handle"] for value in own.notices(PROJECT)["items"]] == refs
    assert counts(f)[1] == 0 and not any(driver.calls for driver in f.drivers.values())


def test_legacy_notice_creation_time_remains_unknown_after_adoption(comm):
    f = comm
    fail_b(f)
    adopt(f)
    value = own_notice(f)
    assert value["created_at"] is None
    CONTRACTS.validate("Notice", value)


def test_legacy_notice_without_route_does_not_invent_native_status(comm):
    f = comm
    fail_b(f)
    with f.authority._connect() as connection:
        connection.execute("DELETE FROM communication_notice_routes WHERE tenant_id=%s", (f.authority.tenant_id,))
    adopt(f)
    value = own_notice(f)
    assert value["created_at"] is None and value["own_delivery"] is None
    CONTRACTS.validate("Notice", value)


def test_forwarded_notices_keep_principals_seen_private_and_stable_slot_owner_immutable(notices, owner_client):
    f = notices
    manager_chain(f)
    fail_b(f)
    direct = own_notice(f, "c")
    route_owner = client(f, "c")
    saved = route_owner.mark_notice_seen(PROJECT, direct["notice_handle"], {"seen": True},
        expected_revision=direct["revision"], client_request_id="direct-manager-seen")
    assert saved["seen"]
    f.drivers["c"].prepare = refuse
    queue_communication_notices(f.authority)
    [(notice_id, operation, _state)] = notice_deliveries(f)
    assert f.dispatcher.dispatch(identity(f, {"message_id": notice_id, "operation_id": operation}))["status"] == "blocked"
    forwarded = own_notice(f)
    assert forwarded["message_ref"] == direct["message_ref"]
    assert forwarded["notice_handle"] != direct["notice_handle"] and not forwarded["seen"]
    assert route_owner.notice(PROJECT, direct["notice_handle"])["seen"]
    assert client(f).mark_notice_seen(PROJECT, forwarded["notice_handle"], {"seen": True},
        expected_revision=forwarded["revision"], client_request_id="parent-manager-seen")["seen"]
    # Existing Slot author identity is immutable even to the configuring Client.
    # Distinct viewers are real admitted principals, not a fabricated transfer.
    rejected = owner_client.call("configure_team", {"project_id": PROJECT, "prepare_native": False,
        "members": [{"agent_slot_id": "slot-c", "principal_ref": "agent:replacement-notice-owner"}]})["structuredContent"]
    assert not rejected["ok"] and rejected["data"]["code"] == "invalid_arguments"
    with f.authority._connect() as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (route_owner.project_service.context.grant_ref,))
    with pytest.raises(AuthorizationDenied):
        route_owner.mark_notice_seen(PROJECT, direct["notice_handle"], {"seen": True},
            expected_revision=direct["revision"], client_request_id="direct-manager-seen")
    assert client(f).notice(PROJECT, forwarded["notice_handle"])["seen"]


def test_current_revocation_blocks_notice_list_detail_and_idempotent_seen(notices):
    f, own = notices, client(notices)
    fail_b(f)
    original = own_notice(f)
    own.mark_notice_seen(PROJECT, original["notice_handle"], {"seen": True},
        expected_revision=original["revision"], client_request_id="revoked-seen")
    with f.authority._connect() as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (own.project_service.context.grant_ref,))
    for method in (lambda: own.notices(PROJECT), lambda: own.notice(PROJECT, original["notice_handle"]),
        lambda: own.mark_notice_seen(PROJECT, original["notice_handle"], {"seen": True},
            expected_revision=original["revision"], client_request_id="revoked-seen")):
        with pytest.raises(AuthorizationDenied):
            method()


def test_arbitrary_diagnostic_text_never_enters_notice_payload(notices):
    f = notices
    fail_b(f)
    before = own_notice(f)
    with f.authority._connect() as connection:
        connection.execute("UPDATE communication_notices SET code='PRIVATE session output with token' WHERE tenant_id=%s",
                           (f.authority.tenant_id,))
    value = client(f).notice(PROJECT, before["notice_handle"])
    assert value["reason_code"] == "delivery_unconfirmed" and "PRIVATE" not in str(value)


def test_real_oauth_notice_routes_read_without_seen_and_explicit_seen_returns_200_409(notices, monkeypatch):
    f = notices
    fail_b(f)
    original = own_notice(f)
    data = config(monkeypatch, f, enabled=True).model_dump()
    data["bindings"][0].update(trusted_client=False, agent_slot_id="local-slot")
    cfg = ProjectHttpSettings.model_validate(data)

    async def exercise():
        async with IssuerFixture({"valid": claims()}).client() as issuer_client:
            app = app_for(f, cfg, issuer_client)
            async with (app.router.lifespan_context(app),
                httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765",
                                  headers={"Authorization": "Bearer valid"}) as http):
                path = PREFIX + f"/projects/{PROJECT}/notices"
                response = await http.get(path)
                assert response.status_code == 200, response.text
                CONTRACTS.validate("NoticePage", response.json())
                value = response.json()["items"][0]
                assert not value["seen"] and value["notice_handle"] == original["notice_handle"]
                target = path + "/" + value["notice_handle"] + "/seen"
                headers = {"If-Match": '"' + str(value["revision"]) + '"', "Idempotency-Key": "http-notice-seen"}
                saved = await http.put(target, headers=headers, json={"seen": True})
                assert saved.status_code == 200 and saved.json()["seen"], saved.text
                replay = await http.put(target, headers=headers, json={"seen": True})
                assert replay.status_code == 200 and replay.json() == saved.json()
                stale = await http.put(target, headers={**headers, "Idempotency-Key": "http-notice-stale"}, json={"seen": False})
                assert stale.status_code == 409 and stale.json()["error"]["effect_state"] == "none", stale.text
                unknown = await http.put(target, headers=headers, json={"seen": True, "sender": "forged"})
                assert unknown.status_code == 400 and unknown.json()["error"]["effect_state"] == "none"
                assert (await http.get(path)).json()["items"][0]["seen"]

    asyncio.run(exercise())
    assert counts(f)[1] == 0 and not any(driver.calls for driver in f.drivers.values())
