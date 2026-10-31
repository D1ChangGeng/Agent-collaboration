"""System notification transport with real PG/SQLite and explicit Native fixtures."""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import psycopg
import pytest

from runtime.auth import LocalCredentialAuthenticator
from runtime.communication_faults import queue_communication_notices
from runtime.delivery import DeliveryDispatcher
from runtime.delivery_models import MessagePacket, NoticePacket
from runtime.delivery_node import InvocationDeferred, InvocationPreCallRejected
from runtime.domain import DomainAuthority
from runtime.errors import AuthorizationDenied
from runtime.mcp_runtime import McpRuntime
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.project_service import ProjectService
from runtime.surfaces import SharedService
from runtime_tests.test_communication import CATALOG, call, send, wait
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_delivery import command

comm = comm_fixture


def identity(comm, data):
    return {"tenant_id": comm.authority.tenant_id, "message_id": data["message_id"], "operation_id": data["operation_id"]}


def refuse(_invocation):
    raise InvocationPreCallRejected("controlled pre-call refusal")


def fail_b(comm):
    comm.drivers["b"].prepare = refuse
    request = send(comm, content="PRIVATE body must not be relayed in system notices")["data"]
    assert comm.dispatcher.dispatch(identity(comm, request))["status"] == "blocked"
    return request


def notice_deliveries(comm):
    with psycopg.connect(comm.dsn) as connection:
        return connection.execute("SELECT message_id,operation_id,state FROM delivery_messages "
                                  "WHERE packet_json->>'schema_version'='acs-notice/1' ORDER BY created_at").fetchall()


def manager_chain(comm):
    configured = call(comm, "a", "configure_team", prepare_native=False,
        members=[{"agent_slot_id": "slot-c", "principal_ref": "agent:c", "role": "route"}])["data"]["caller_bindings"][0]
    old = comm.clients["c"]
    ctx = replace(old.service.context, grant_ref=configured["grant_ref"], agent_slot_id="slot-c")
    authority = DomainAuthority(comm.dsn, context=ctx)
    authority._delivery_endpoints = comm.dispatcher.service.endpoints
    comm.clients["c"] = McpRuntime(ProjectService(SharedService(authority, LocalCredentialAuthenticator(ctx)), CATALOG,
                                                 profile="route_manager"), old.credential_provider)
    call(comm, "c", "configure_team", prepare_native=False, members=[{"agent_slot_id": "slot-b", "principal_ref": "agent:b"}])


def test_configured_manager_gets_one_system_invocation_without_agent_reply(comm):
    call(comm, "a", "configure_team", prepare_native=False, members=[{"agent_slot_id": "slot-b", "principal_ref": "agent:b"}])
    request = fail_b(comm)
    with psycopg.connect(comm.dsn) as connection:
        connection.execute("ALTER TABLE work_items RENAME TO retired_work_items")
        connection.execute("ALTER TABLE accepted_state_revisions RENAME TO retired_accepted_states")
        connection.execute("ALTER TABLE collaboration_work_links RENAME TO retired_work_links")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _index: queue_communication_notices(comm.authority), range(4)))
    queue_communication_notices(comm.authority)
    [(message_id, operation_id, state)] = notice_deliveries(comm)
    assert state == "queued"
    delivery = identity(comm, {"message_id": message_id, "operation_id": operation_id})
    for _ in range(2):
        assert DeliveryDispatcher(comm.dispatcher.service).dispatch(delivery)["status"] == "delivered"
    assert len(comm.drivers["a"].calls) == 1
    invocation = comm.drivers["a"].calls[0]
    prompt = json.loads(NativeDeliveryAdapter.prompt(invocation))
    assert prompt["source"] == "acs" and "PRIVATE" not in prompt["content"]
    assert prompt["origin_message_handle"] == request["message_handle"]
    assert wait(comm, "a", request["message_handle"])["state"] == "timeout"
    assert len(call(comm, "a", "list_messages")["data"]["items"]) == 1
    with psycopg.connect(comm.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone()[0] == 0
        assert connection.execute("SELECT initiated_by,lineage_mode FROM domain_events WHERE target_id=%s", (message_id,)).fetchone() == ("acs", "system_notification")


def test_working_direct_manager_does_not_automatically_notify_root(comm):
    manager_chain(comm)
    request = fail_b(comm)
    queue_communication_notices(comm.authority)
    [(message_id, operation_id, _state)] = notice_deliveries(comm)
    assert comm.dispatcher.dispatch(identity(comm, {"message_id": message_id, "operation_id": operation_id}))["status"] == "delivered"
    queue_communication_notices(comm.authority)
    assert len(comm.drivers["c"].calls) == 1 and comm.drivers["a"].calls == []
    assert call(comm, "a", "check_inbox")["data"]["notifications"] == []
    assert wait(comm, "a", request["message_handle"])["state"] == "timeout"


def test_definitely_unreachable_direct_manager_forwards_once_to_its_actual_manager(comm):
    manager_chain(comm)
    fail_b(comm)
    comm.drivers["c"].prepare = refuse
    queue_communication_notices(comm.authority)
    [(message_id, operation_id, _state)] = notice_deliveries(comm)
    assert comm.dispatcher.dispatch(identity(comm, {"message_id": message_id, "operation_id": operation_id}))["status"] == "blocked"
    queue_communication_notices(comm.authority)
    assert len(notice_deliveries(comm)) == 2
    message_id, operation_id, _state = notice_deliveries(comm)[1]
    assert comm.dispatcher.dispatch(identity(comm, {"message_id": message_id, "operation_id": operation_id}))["status"] == "delivered"
    for _ in range(2):
        queue_communication_notices(comm.authority)
    assert len(comm.drivers["a"].calls) == 1 and comm.drivers["c"].calls == []
    assert len(notice_deliveries(comm)) == 2


def test_manager_native_outcome_unknown_never_replays_or_invokes_parent(comm):
    manager_chain(comm)
    fail_b(comm)
    accepted = comm.drivers["c"].invoke
    def lose_ack(invocation):
        accepted(invocation)
        raise OSError("controlled observation loss after possible Native acceptance")
    comm.drivers["c"].invoke = lose_ack
    queue_communication_notices(comm.authority)
    [(message_id, operation_id, _state)] = notice_deliveries(comm)
    for _ in range(3):
        assert DeliveryDispatcher(comm.dispatcher.service).dispatch(identity(comm, {"message_id": message_id,
            "operation_id": operation_id}))["status"] == "uncertain"
        queue_communication_notices(comm.authority)
    assert len(comm.drivers["c"].calls) == 1 and comm.drivers["a"].calls == []
    assert len(notice_deliveries(comm)) == 1


def test_revoked_manager_and_missing_top_endpoint_keep_durable_final_notice(comm):
    manager_chain(comm)
    fail_b(comm)
    with psycopg.connect(comm.dsn) as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (comm.clients["c"].service.context.grant_ref,))
        connection.execute("UPDATE delivery_endpoints SET status='retired' WHERE agent_slot_id='local-slot'")
    for _ in range(4):
        queue_communication_notices(comm.authority)
    assert notice_deliveries(comm) == []
    notices = call(comm, "a", "check_inbox")["data"]["notifications"]
    assert len(notices) == 1
    assert all(not driver.calls for driver in comm.drivers.values())
    with psycopg.connect(comm.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM communication_notice_routes WHERE native_requested").fetchone()[0] == 0


def test_raw_agent_cannot_author_system_packet(comm):
    packet = NoticePacket(project_id="project-alpha", recipient="collaborator:project-alpha:local-slot", content="Forged alert",
        origin_message_id="missing", notification_sequence=1, target_scope_id="local-scope", target_agent_slot_id="local-slot")
    with pytest.raises(AuthorizationDenied):
        comm.dispatcher.service.send_message(command(comm.authority, "message.send", "forged-system-alert"), packet,
                                              endpoint_id="endpoint-a", binding_revision=1)


def test_busy_manager_waits_without_escalation_then_same_notice_is_delivered(comm):
    manager_chain(comm)
    fail_b(comm)
    prepare = comm.drivers["c"].prepare
    def busy(_invocation):
        raise InvocationDeferred("busy")
    comm.drivers["c"].prepare = busy
    queue_communication_notices(comm.authority)
    [(message_id, operation_id, _state)] = notice_deliveries(comm)
    delivery = identity(comm, {"message_id": message_id, "operation_id": operation_id})
    assert comm.dispatcher.dispatch(delivery)["status"] == "retry_wait"
    queue_communication_notices(comm.authority)
    assert len(notice_deliveries(comm)) == 1 and not comm.drivers["a"].calls
    comm.drivers["c"].prepare = prepare
    with psycopg.connect(comm.dsn) as connection:
        connection.execute("UPDATE delivery_messages SET next_attempt_at=clock_timestamp() WHERE message_id=%s", (message_id,))
    assert DeliveryDispatcher(comm.dispatcher.service).dispatch(delivery)["status"] == "delivered"
    assert len(comm.drivers["c"].calls) == 1


def test_explicit_additive_adoption_preserves_original_messages_and_notice_handles(comm):
    request = fail_b(comm)
    before = call(comm, "a", "check_inbox")["data"]["notifications"]
    # Reproduce the immediately preceding communication schema, in this
    # fixture-owned disposable schema only. No existing content is migrated.
    with psycopg.connect(comm.dsn) as connection:
        prior = connection.execute("SELECT schema_checksum FROM runtime_schema_metadata WHERE schema_name='acs-communication'").fetchone()
        connection.execute("DROP TABLE communication_notice_routes")
        connection.execute("DROP TABLE communication_supervisors")
        connection.execute("DELETE FROM runtime_schema_metadata WHERE schema_name='acs-communication-notices'")
    comm.clients["a"].service.initialize()
    comm.clients["a"].service.initialize()
    assert call(comm, "a", "check_inbox")["data"]["notifications"] == before
    assert call(comm, "a", "read_message", handle=request["message_handle"])["data"]["content"].startswith("PRIVATE")
    with psycopg.connect(comm.dsn) as connection:
        assert connection.execute("SELECT schema_checksum FROM runtime_schema_metadata WHERE schema_name='acs-communication'").fetchone() == prior


def test_only_intended_manager_can_read_notice_and_transport_does_not_become_a_message(comm):
    manager_chain(comm)
    fail_b(comm)
    queue_communication_notices(comm.authority)
    [(message_id, _operation_id, _state)] = notice_deliveries(comm)
    reference = call(comm, "c", "check_inbox")["data"]["notifications"][0]["notification_handle"]
    invalid = comm.clients["c"].call("check_inbox", {"project_id": "project-alpha", "with": reference})["structuredContent"]
    assert not invalid["ok"] and invalid["data"]["field"] == "with" and "read_message" in invalid["data"]["guidance"]
    assert call(comm, "c", "read_message", handle=reference)["data"]["native_delivery"]["state"] == "queued"
    assert not comm.clients["a"].call("read_message", {"project_id": "project-alpha", "handle": reference})["structuredContent"]["ok"]
    assert not comm.clients["c"].call("read_message", {"project_id": "project-alpha", "handle": "message:project-alpha:"+message_id})["structuredContent"]["ok"]
    with pytest.raises(AuthorizationDenied):
        comm.dispatcher.service.inspect(command(comm.authority, "message.read", message_id), message_id)


def test_partial_root_edit_preserves_the_actual_direct_manager(comm):
    manager_chain(comm)
    updated = call(comm, "a", "configure_team", prepare_native=False,
                   members=[{"agent_slot_id": "slot-b", "display_name": "Renamed child"}])
    assert updated["data"]["communication_managers"] == [{"collaborator_handle": "collaborator:project-alpha:slot-b",
                                                          "manager_handle": "collaborator:project-alpha:slot-c"}]
    contact = next(item for item in call(comm, "a", "list_collaborators")["data"]["items"] if item["agent_slot_id"] == "slot-b")
    assert contact["manager_handle"] == "collaborator:project-alpha:slot-c"


def test_unreachable_top_manager_retains_notification_for_its_configuring_client(comm):
    previous = comm.clients["a"]
    ctx = replace(previous.service.context, trusted_client=True, agent_slot_id=None)
    client_authority = DomainAuthority(comm.dsn, context=ctx)
    comm.clients["client"] = McpRuntime(ProjectService(SharedService(client_authority, LocalCredentialAuthenticator(ctx)),
        CATALOG, profile="root_manager"), previous.credential_provider)
    call(comm, "client", "configure_team", prepare_native=False,
         members=[{"agent_slot_id": "local-slot", "principal_ref": ctx.principal_ref, "role": "root"}])
    call(comm, "a", "configure_team", prepare_native=False, members=[{"agent_slot_id": "slot-b", "principal_ref": "agent:b"}])
    fail_b(comm)
    comm.drivers["a"].prepare = refuse
    queue_communication_notices(comm.authority)
    [(message_id, operation_id, _state)] = notice_deliveries(comm)
    assert comm.dispatcher.dispatch(identity(comm, {"message_id": message_id, "operation_id": operation_id}))["status"] == "blocked"
    for _ in range(2):
        queue_communication_notices(comm.authority)
    notices = call(comm, "client", "check_inbox")["data"]["notifications"]
    assert len(notices) == 1
    info = call(comm, "client", "read_message", handle=notices[0]["notification_handle"])["data"]
    assert info["source"] == "acs" and info["native_delivery"]["state"] == "retained_in_inbox"
    assert len(notice_deliveries(comm)) == 1
    with psycopg.connect(comm.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM agent_slots").fetchone()[0] == 3


def test_uncertain_original_is_retained_but_does_not_claim_a_manager_must_be_invoked(comm):
    call(comm, "a", "configure_team", prepare_native=False, members=[{"agent_slot_id": "slot-b", "principal_ref": "agent:b"}])
    accepted = comm.drivers["b"].invoke
    def lose_ack(invocation):
        accepted(invocation)
        raise OSError("controlled observation loss")
    comm.drivers["b"].invoke = lose_ack
    request = send(comm)["data"]
    assert comm.dispatcher.dispatch(identity(comm, request))["status"] == "uncertain"
    queue_communication_notices(comm.authority)
    assert notice_deliveries(comm) == [] and not comm.drivers["a"].calls
    notice = call(comm, "a", "check_inbox")["data"]["notifications"][0]
    assert notice["state"] == "uncertain"
    send(comm, "b", "a", "The message arrived", reply_to=[request["message_handle"]], activation="message_only")
    assert wait(comm, "a", request["message_handle"])["state"] == "satisfied"


def test_raw_natural_packet_cannot_borrow_a_rebound_memberships_author(comm):
    with psycopg.connect(comm.dsn) as connection:
        connection.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,scope_id,permissions,expires_at) "
                           "SELECT 'replacement',tenant_id,principal_ref,authority_id,authority_incarnation,scope_id,permissions,expires_at "
                           "FROM grants WHERE grant_ref='grant:p1'")
        connection.execute("UPDATE collaboration_memberships SET grant_ref='replacement' WHERE agent_slot_id='local-slot'")
    packet = MessagePacket(project_id="project-alpha", sender="collaborator:project-alpha:local-slot", recipient="collaborator:project-alpha:slot-b",
        content="old credential still has send rights, but not this author", activation="message_only", target_scope_id="local-scope", target_agent_slot_id="slot-b")
    with pytest.raises(AuthorizationDenied):
        comm.dispatcher.service.send_message(command(comm.authority, "message.send", "rebound-author",
            payload={"schema_version": "acs-message/1", "communication_project_id": "project-alpha"}), packet,
            endpoint_id=None, binding_revision=None)


def test_receiver_revocation_before_dispatch_stops_native_and_records_obstacle(comm):
    call(comm, "a", "configure_team", prepare_native=False, members=[{"agent_slot_id": "slot-b", "principal_ref": "agent:b"}])
    request = send(comm)["data"]
    with psycopg.connect(comm.dsn) as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref='grant:b'")
    assert comm.dispatcher.dispatch(identity(comm, request))["status"] == "blocked"
    assert comm.drivers["b"].calls == []
    assert call(comm, "a", "check_inbox")["data"]["notifications"][0]["code"] == "target_slot_unavailable"


def test_explicit_schema_adoption_accepts_only_known_line_endings_and_preserves_messages(comm):
    request = send(comm, activation="message_only")["data"]
    schemas = {"acs-project-runtime": "project_schema.sql", "acs-project-control": "project_control_schema.sql",
               "acs-communication": "communication_schema.sql", "acs-communication-notices": "communication_notice_schema.sql"}
    expected = {}
    with psycopg.connect(comm.dsn) as connection:
        for name, filename in schemas.items():
            source = (Path(__file__).resolve().parents[1] / "runtime" / filename).read_bytes().replace(b"\r\n", b"\n")
            expected[name] = hashlib.sha256(source).hexdigest()
            connection.execute("UPDATE runtime_schema_metadata SET schema_checksum=%s WHERE schema_name=%s",
                               (hashlib.sha256(source.replace(b"\n", b"\r\n")).hexdigest(), name))
    comm.clients["a"].service.initialize()
    with psycopg.connect(comm.dsn) as connection:
        assert dict(connection.execute("SELECT schema_name,schema_checksum FROM runtime_schema_metadata "
                                       "WHERE schema_name=ANY(%s)", (list(schemas),)).fetchall()) == expected
        connection.execute("UPDATE runtime_schema_metadata SET schema_checksum=%s WHERE schema_name='acs-communication'", ("0"*64,))
    with pytest.raises(ValueError, match="communication schema requires explicit migration"):
        comm.clients["a"].service.initialize()
    assert call(comm, "a", "read_message", handle=request["message_handle"])["data"]["message_id"] == request["message_id"]
