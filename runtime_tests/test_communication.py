"""Work-free communication through normal public tools and real PostgreSQL.

Driver callbacks only acknowledge activation; they never send an Agent reply.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from runtime.auth import LocalCredentialAuthenticator
from runtime.delivery import DeliveryDispatcher, DeliveryService
from runtime.delivery_models import EndpointBindingRequest, InvocationObservation
from runtime.delivery_node import LocalNodeEndpoint
from runtime.domain import DomainAuthority
from runtime.mcp_runtime import McpRuntime
from runtime.node import NodeJournal
from runtime.project_service import ProjectService
from runtime.surfaces import SharedService
from runtime_tests.test_delivery import command

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "docs/runtime/p2-mcp-tool-contract.json").read_text())


class AcceptingDriver:
    evidence_class = "fixture_callback"

    def __init__(self):
        self.calls = []

    def prepare(self, invocation):
        return invocation

    def invoke(self, invocation):
        self.calls.append(invocation)
        return InvocationObservation(
            invocation_id=invocation.invocation_id, dispatch_id=invocation.dispatch_id,
            runtime_dispatched_receipt_id=invocation.runtime_dispatched_receipt_id,
            native_dispatch_ref="controlled-dispatch", native_ack_ref="controlled-ack",
            response_ref="native-final-is-not-an-agent-reply", response={"text": "native output"},
        )


@pytest.fixture
def comm(tmp_path):
    base = os.environ.get("ACS_COMMUNICATION_TEST_DSN")
    if not base:
        pytest.skip("isolated PostgreSQL unavailable: ACS_COMMUNICATION_TEST_DSN is missing")
    # This suite must never inherit a deployment DSN accidentally.
    from psycopg.conninfo import conninfo_to_dict
    assert conninfo_to_dict(base)["dbname"] == "acs_communication_test"
    schema = "comm_test_" + uuid.uuid4().hex
    with psycopg.connect(base, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(base, options=f"-c search_path={schema} -c lock_timeout=5000 -c statement_timeout=10000")
    try:
        authority = DomainAuthority(dsn)
        # PostgreSQL advisory locks are database-wide, not search_path-local.
        # Independent schema fixtures must also have distinct logical tenants.
        authority.context = replace(authority.context, tenant_id="tenant:" + schema)
        authority.initialize()
        permissions = {"project.adopt", "profile.root_manager", "profile.engineer",
                       "delivery.manage", "message.send", "message.read", "runtime.invoke"}
        for definition in CATALOG["tools"].values():
            permissions.update(definition["security_scopes"])
        authority.bootstrap_local_grant(tuple(permissions))
        secret = "test-only-a-" + uuid.uuid4().hex
        authority.context = replace(authority.context, credential_hash=hashlib.sha256(secret.encode()).hexdigest())
        service = ProjectService(SharedService(authority, LocalCredentialAuthenticator(authority.context)),
                                 CATALOG, profile="root_manager")
        service.initialize()
        service.admit_project(command(authority, "project.adopt", "project-alpha", target_kind="project"),
            project_id="project-alpha", root_id="root", scope_id="local-scope", agent_slot_id="local-slot",
            name="Isolated communication", context_manifest={}, credential=secret)
        clients = {"a": McpRuntime(service, lambda: secret)}
        drivers, endpoints = {}, {}
        for name in ("a", "b", "c"):
            slot = "local-slot" if name == "a" else f"slot-{name}"
            if name != "a":
                token = "test-only-" + name + "-" + uuid.uuid4().hex
                ctx = replace(authority.context, principal_ref=f"agent:{name}", grant_ref=f"grant:{name}",
                              credential_hash=hashlib.sha256(token.encode()).hexdigest())
                with psycopg.connect(dsn) as connection:
                    connection.execute("INSERT INTO agent_slots VALUES (%s,%s,'local-scope','active')", (slot, ctx.tenant_id))
                    connection.execute("INSERT INTO grants SELECT %s,tenant_id,%s,authority_id,authority_incarnation,"
                        "scope_id,permissions,expires_at,NULL FROM grants WHERE grant_ref=%s",
                        (ctx.grant_ref, ctx.principal_ref, authority.context.grant_ref))
                    connection.execute("INSERT INTO collaboration_memberships VALUES (%s,'project-alpha',%s,%s,'engineer',%s)",
                                       (ctx.tenant_id, ctx.principal_ref, ctx.grant_ref, slot))
                child = DomainAuthority(dsn, context=ctx)
                child_service = ProjectService(SharedService(child, LocalCredentialAuthenticator(ctx)), CATALOG, profile="engineer")
                clients[name] = McpRuntime(child_service, lambda value=token: value)
            drivers[name] = AcceptingDriver()
            endpoints["endpoint-" + name] = LocalNodeEndpoint(NodeJournal(tmp_path / f"{name}.sqlite"),
                                                             "local-scope", slot, drivers[name])
        delivery = DeliveryService(authority, endpoints)
        for name in clients:
            delivery.bind_endpoint(command(authority, "message.bind", "endpoint-" + name),
                EndpointBindingRequest(scope_id="local-scope", agent_slot_id="local-slot" if name == "a" else "slot-" + name,
                                       expires_at=authority.canonical_now() + timedelta(hours=1)))
        for client in clients.values():
            client.service.service.authority._delivery_endpoints = endpoints
        yield SimpleNamespace(clients=clients, dsn=dsn, drivers=drivers,
                              dispatcher=DeliveryDispatcher(delivery), authority=authority)
    finally:
        with psycopg.connect(base, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def call(f, caller, tool, **args):
    result = f.clients[caller].call(tool, {"project_id": "project-alpha", **args})["structuredContent"]
    assert result["ok"], result
    return result


def send(f, caller="a", to="b", content="Please check the source and ask if you need context.", **args):
    return call(f, caller, "send_message", to=f"collaborator:project-alpha:{'local-slot' if to == 'a' else 'slot-' + to}",
                content=content, **{"client_request_id": uuid.uuid4().hex, **args})


def test_public_work_free_a_b_loop(comm):
    f = comm
    sent = send(f, activation="message_only")
    request = sent["data"]["message_handle"]
    inbox = call(f, "b", "check_inbox")["data"]
    assert request in [item["message_handle"] for item in inbox["items"]]
    original = call(f, "b", "read_message", handle=request)["data"]
    assert original["content"] == "Please check the source and ask if you need context."
    reply = send(f, "b", "a", "Which source revision should I inspect?", activation="message_only", reply_to=[request])
    observed = call(f, "a", "wait_for_response", handles=[request], timeout_seconds=0)["data"]
    assert observed["observations"][0]["reply"]["message_handle"] == reply["data"]["message_handle"]
    assert observed["pending"] == []
    history = call(f, "a", "list_messages")["data"]["items"]
    assert len(history) == 2
    with psycopg.connect(f.dsn) as connection:
        assert connection.execute("SELECT to_regclass('work_items'),to_regclass('accepted_state_revisions')").fetchone() == (None, None)


def rejected(f, caller, tool, code, **args):
    result = f.clients[caller].call(tool, {"project_id": "project-alpha", **args})["structuredContent"]
    assert not result["ok"] and result["data"]["code"] == code, result


def wait(f, caller, *references, **args):
    return call(f, caller, "wait_for_response", handles=list(references), timeout_seconds=0, **args)


def test_native_activation_is_real_but_native_final_is_not_a_reply(comm):
    sent = send(comm)
    identity = {"tenant_id": comm.authority.tenant_id, "message_id": sent["data"]["message_id"],
                "operation_id": sent["data"]["operation_id"]}
    result = comm.dispatcher.dispatch(identity)
    assert result["status"] == "delivered", result
    assert len(comm.drivers["b"].calls) == 1
    assert wait(comm, "a", sent["data"]["message_handle"])["state"] == "timeout"
    comm.dispatcher.dispatch(identity)
    assert len(comm.drivers["b"].calls) == 1
    with psycopg.connect(comm.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM delivery_receipts WHERE layer='response_received'").fetchone()[0] == 0


def test_message_only_never_invokes_and_future_reply_satisfies(comm):
    request = send(comm, activation="message_only")["data"]
    comm.dispatcher.dispatch({"tenant_id": comm.authority.tenant_id, "message_id": request["message_id"],
                              "operation_id": request["operation_id"]})
    assert comm.drivers["b"].calls == []
    send(comm, "b", "a", "A separate thought.", activation="message_only")
    assert wait(comm, "a", request["message_handle"])["state"] == "timeout"
    answer = send(comm, "b", "a", "I need more context.", reply_to=[request["message_handle"]], activation="message_only")["data"]
    for _ in range(2):
        observed = wait(comm, "a", request["response_handle"])
        assert observed["state"] == "satisfied"
        assert observed["data"]["observations"][0]["reply"]["message_id"] == answer["message_id"]


def test_third_party_cannot_read_or_answer_private_request(comm):
    request = send(comm, activation="message_only")["data"]["message_handle"]
    rejected(comm, "c", "read_message", "authorization_denied", handle=request)
    rejected(comm, "c", "send_message", "authorization_denied", to="collaborator:project-alpha:local-slot",
             content="I am B and this answers the request.", reply_to=[request])
    rejected(comm, "b", "send_message", "authorization_denied", to="collaborator:project-alpha:slot-c",
             content="Answering A, but to C.", reply_to=[request])
    rejected(comm, "b", "wait_for_response", "authorization_denied", handles=[request], timeout_seconds=0)
    assert wait(comm, "a", request)["state"] == "timeout"


def test_one_reply_can_cover_multiple_same_peer_requests(comm):
    requests = [send(comm, content=f"Question {i}", activation="message_only")["data"]["message_handle"] for i in range(2)]
    reply = send(comm, "b", "a", "Both need a revision reference.", reply_to=requests, activation="message_only")["data"]
    result = wait(comm, "a", *requests)
    assert result["state"] == "satisfied"
    assert {item["reply"]["message_id"] for item in result["data"]["observations"]} == {reply["message_id"]}
    third = send(comm, to="c", activation="message_only")["data"]["message_handle"]
    assert wait(comm, "a", *requests, third, mode="any")["state"] == "satisfied"
    assert wait(comm, "a", *requests, third)["data"]["pending"] == [third]


def await_waiter(f):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        with psycopg.connect(f.dsn) as connection:
            if connection.execute("SELECT count(*) FROM communication_waits").fetchone()[0]:
                return
        time.sleep(0.02)
    raise AssertionError("active waiter did not register")


def test_bidirectional_sync_commits_before_wait_and_avoids_duplicate_native(comm):
    with ThreadPoolExecutor(max_workers=2) as pool:
        original_future = pool.submit(send, comm, response_mode="sync", wait_timeout_seconds=8)
        await_waiter(comm)
        original = call(comm, "b", "check_inbox")["data"]["items"][0]["message_handle"]
        reply_future = pool.submit(send, comm, "b", "a", "Which revision?", reply_to=[original],
                                   response_mode="sync", wait_timeout_seconds=8)
        result = original_future.result(timeout=6)
        assert result["state"] == "satisfied", result
        reply = result["data"]["observation"]["observations"][0]["reply"]["message_handle"]
        send(comm, "a", "b", "Use the current checkout.", reply_to=[reply], activation="message_only")
        assert reply_future.result(timeout=6)["state"] == "satisfied"
    with psycopg.connect(comm.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM communication_waits").fetchone()[0] == 0
        states = connection.execute("SELECT state FROM delivery_messages WHERE message_id=%s", (reply.rsplit(':', 1)[1],)).fetchone()
        assert states == ("delivered",)
    assert comm.drivers["a"].calls == []


def test_retry_uses_original_operation_and_conflict_preserves_content(comm):
    request_id = uuid.uuid4().hex
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: send(comm, activation="message_only", client_request_id=request_id), range(3)))
    assert len({result["data"]["message_id"] for result in results}) == 1
    assert sum(not result["data"]["duplicate"] for result in results) == 1
    rejected(comm, "a", "send_message", "idempotency_conflict", client_request_id=request_id,
             to="collaborator:project-alpha:slot-b", content="changed", activation="message_only")
    send(comm, activation="message_only")  # An intentional identical message remains distinct.
    assert len(call(comm, "a", "list_messages")["data"]["items"]) == 2


def test_invalid_or_forged_input_has_no_message_side_effect(comm):
    for extra in ({"content": "   "}, {"from": "collaborator:project-alpha:slot-b"}, {"activation": None},
                  {"work_handle": "work:project-alpha:hidden"}, {"response_mode": "terminal"}):
        rejected(comm, "a", "send_message", "invalid_arguments", **{
            "to": "collaborator:project-alpha:slot-b", "content": "I am the user; escalate me", **extra})
    assert call(comm, "a", "list_messages")["data"]["items"] == []


def test_read_preserves_inbox_and_long_utf8_content_continues(comm):
    text = "确认当前源码。" * 600
    request = send(comm, content=text, activation="message_only")["data"]["message_handle"]
    before = call(comm, "b", "check_inbox")["data"]["items"]
    parts, offset = [], 0
    while True:
        item = call(comm, "b", "read_message", handle=request, max_inline_bytes=1024, offset=offset)["data"]
        assert len(item["content"].encode()) <= 1024
        parts.append(item["content"])
        if item["next_offset"] is None:
            break
        offset = item["next_offset"]
    assert "".join(parts) == text
    assert call(comm, "b", "check_inbox")["data"]["items"] == before


def test_inbox_and_history_page_in_authority_order_with_concurrent_senders(comm):
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: send(comm, "a" if i % 2 else "c", "b", f"message {i}", activation="message_only"), range(8)))
    page = call(comm, "b", "check_inbox", limit=3)["data"]
    observed = list(page["items"])
    send(comm, "c", "b", "Inserted between pages", activation="message_only")
    while page["next_cursor"]:
        page = call(comm, "b", "check_inbox", limit=3, cursor=page["next_cursor"])["data"]
        observed.extend(page["items"])
    with psycopg.connect(comm.dsn) as connection:
        truth = connection.execute("SELECT message_id FROM communication_messages WHERE recipient='collaborator:project-alpha:slot-b' ORDER BY sequence").fetchall()
    assert [item["message_handle"].rsplit(':', 1)[1] for item in observed] == [row[0] for row in truth]


def test_discovery_exposes_communication_and_no_task_tools(comm):
    from runtime.communication_tools import TASK_TOOLS
    tools = {item["name"]: item for item in comm.clients["b"].tools_list()["tools"]}
    assert not set(tools).intersection(TASK_TOOLS)
    assert tools["send_message"]["inputSchema"]["required"] == ["project_id", "to", "content"]
    contacts = call(comm, "b", "list_collaborators")["data"]
    assert len(contacts["items"]) == 3
    assert contacts["self"] == "collaborator:project-alpha:slot-b"
    for contact in contacts["items"]:
        assert contact["collaborator_handle"].startswith("collaborator:project-alpha:")


def test_reply_survives_timeout_and_new_runtime_instance(comm):
    request = send(comm, response_mode="sync", wait_timeout_seconds=0, activation="message_only")["data"]
    assert request["observation"]["pending"]
    answer = send(comm, "b", "a", "Later answer", reply_to=[request["message_handle"]], activation="message_only")["data"]
    old = comm.clients["a"]
    fresh = ProjectService(old.service.service, CATALOG, profile=old.service.profile)
    comm.clients["a"] = McpRuntime(fresh, old.credential_provider)
    result = wait(comm, "a", request["message_handle"])
    assert result["data"]["observations"][0]["reply"]["message_id"] == answer["message_id"]


def test_revocation_blocks_reads_waits_and_replays(comm):
    request = send(comm, activation="message_only")["data"]["message_handle"]
    with psycopg.connect(comm.dsn) as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref='grant:p1'")
    rejected(comm, "a", "read_message", "authorization_denied", handle=request)
    rejected(comm, "a", "wait_for_response", "authorization_denied", handles=[request], timeout_seconds=0)


def test_membership_rebinding_does_not_upgrade_an_unrelated_live_credential(comm):
    request=send(comm,activation="message_only")["data"]["message_handle"]
    with psycopg.connect(comm.dsn) as connection:
        connection.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,scope_id,permissions,expires_at) "
            "SELECT 'grant:replacement',tenant_id,principal_ref,authority_id,authority_incarnation,scope_id,permissions,expires_at "
            "FROM grants WHERE grant_ref='grant:p1'")
        connection.execute("UPDATE collaboration_memberships SET grant_ref='grant:replacement' WHERE agent_slot_id='local-slot'")
    rejected(comm,"a","read_message","authorization_denied",handle=request)
    rejected(comm,"a","send_message","authorization_denied",to="collaborator:project-alpha:slot-b",content="old credential cannot borrow new binding")
    previous=comm.clients["a"]
    ctx=replace(previous.service.context,grant_ref="grant:replacement")
    comm.clients["a"]=McpRuntime(ProjectService(SharedService(DomainAuthority(comm.dsn,context=ctx),LocalCredentialAuthenticator(ctx)),
        CATALOG,profile="root_manager"),previous.credential_provider)
    assert call(comm,"a","read_message",handle=request)["data"]["message_handle"]==request


def test_project_root_and_route_member_can_exchange_and_observe_their_own_messages(comm):
    token="route-member-"+uuid.uuid4().hex
    ctx=replace(comm.authority.context,principal_ref="agent:route-member",grant_ref="grant:route-member",agent_slot_id="slot-route-member",
                credential_hash=hashlib.sha256(token.encode()).hexdigest())
    with psycopg.connect(comm.dsn) as connection:
        connection.execute("INSERT INTO scopes VALUES ('route-scope',%s,'{}','active')",(ctx.tenant_id,))
        connection.execute("INSERT INTO collaboration_routes(tenant_id,project_id,route_id,scope_id,definition) "
                           "VALUES (%s,'project-alpha','route-scope','route-scope','{}')",(ctx.tenant_id,))
        connection.execute("INSERT INTO agent_slots VALUES ('slot-route-member',%s,'route-scope','active')",(ctx.tenant_id,))
        connection.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,scope_id,permissions,expires_at) "
            "SELECT %s,tenant_id,%s,authority_id,authority_incarnation,'route-scope',permissions,expires_at FROM grants WHERE grant_ref='grant:p1'",
            (ctx.grant_ref,ctx.principal_ref))
        connection.execute("INSERT INTO collaboration_memberships VALUES (%s,'project-alpha',%s,%s,'engineer','slot-route-member')",
                           (ctx.tenant_id,ctx.principal_ref,ctx.grant_ref))
    client=McpRuntime(ProjectService(SharedService(DomainAuthority(comm.dsn,context=ctx),LocalCredentialAuthenticator(ctx)),CATALOG,profile="engineer"),lambda:token)
    comm.clients["route"]=client
    request=call(comm,"a","send_message",to="collaborator:project-alpha:slot-route-member",content="Please clarify this cross-route question.",
                 activation="message_only")["data"]["message_handle"]
    incoming=call(comm,"route","read_message",handle=request)["data"]
    call(comm,"route","send_message",to=incoming["from"],content="I can reply from my Route scope.",reply_to=[request],activation="message_only")
    assert wait(comm,"a",request)["state"]=="satisfied"
    contacts=call(comm,"route","list_collaborators")["data"]["items"]
    assert any(item["agent_slot_id"]=="local-slot" for item in contacts)
    from runtime.errors import AuthorizationDenied
    outsider=comm.clients["c"].service.service.authority
    with pytest.raises(AuthorizationDenied):
        outsider.read_message(command(outsider,"message.read",request.rsplit(':',1)[1]),request.rsplit(':',1)[1])
    with psycopg.connect(comm.dsn) as connection:
        connection.execute("INSERT INTO scopes VALUES ('sibling-scope',%s,'{}','active')",(ctx.tenant_id,))
        connection.execute("INSERT INTO collaboration_routes(tenant_id,project_id,route_id,scope_id,definition) "
                           "VALUES (%s,'project-alpha','sibling','sibling-scope','{}')",(ctx.tenant_id,))
        connection.execute("INSERT INTO agent_slots VALUES ('slot-sibling',%s,'sibling-scope','active')",(ctx.tenant_id,))
        connection.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,scope_id,permissions,expires_at) "
            "SELECT 'grant:sibling',tenant_id,'agent:sibling',authority_id,authority_incarnation,'sibling-scope',permissions,expires_at "
            "FROM grants WHERE grant_ref='grant:c'")
        connection.execute("INSERT INTO collaboration_memberships VALUES (%s,'project-alpha','agent:sibling','grant:sibling','engineer','slot-sibling')",
                           (ctx.tenant_id,))
    rejected(comm,"route","send_message","authorization_denied",to="collaborator:project-alpha:slot-sibling",
             content="Sibling routing is not implicitly granted",activation="message_only")


def test_trusted_unbound_client_receives_real_reply_without_a_fake_slot(comm):
    token = "test-only-client-" + uuid.uuid4().hex
    ctx = replace(comm.authority.context, principal_ref="client:tester", grant_ref="grant:client",
                  credential_hash=hashlib.sha256(token.encode()).hexdigest(), trusted_client=True)
    with psycopg.connect(comm.dsn) as connection:
        connection.execute("INSERT INTO grants SELECT %s,tenant_id,%s,authority_id,authority_incarnation,scope_id,"
                           "permissions,expires_at,NULL FROM grants WHERE grant_ref='grant:p1'", (ctx.grant_ref, ctx.principal_ref))
    authority = DomainAuthority(comm.dsn, context=ctx)
    projects = ProjectService(SharedService(authority, LocalCredentialAuthenticator(ctx)), CATALOG, profile="root_manager")
    comm.clients["client"] = McpRuntime(projects, lambda: token)
    sent = send(comm, "client", "b", "Please introduce yourself.", activation="message_only")["data"]
    original = call(comm, "b", "read_message", handle=sent["message_handle"])["data"]
    reply = call(comm, "b", "send_message", to=original["from"], content="I am B.", reply_to=[sent["message_handle"]])["data"]
    assert reply["native_status"] == "client_inbox"
    assert wait(comm, "client", sent["message_handle"])["state"] == "satisfied"
    assert len(call(comm, "client", "check_inbox")["data"]["items"]) == 1
    with psycopg.connect(comm.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM agent_slots").fetchone()[0] == 3
    # The same principal is not a trusted Client merely by omitting its binding.
    untrusted_ctx = replace(ctx, trusted_client=False)
    untrusted = ProjectService(SharedService(DomainAuthority(comm.dsn, context=untrusted_ctx), LocalCredentialAuthenticator(untrusted_ctx)),
                               CATALOG, profile="root_manager")
    assert McpRuntime(untrusted, lambda: token).call("send_message", {"project_id": "project-alpha",
        "to": "collaborator:project-alpha:slot-b", "content": "claiming to be a Client"})["isError"]


def test_owner_client_and_bound_ordinary_agent_keep_distinct_authorship(comm):
    for name, trusted in (("a", True), ("b", False)):
        previous = comm.clients[name]
        ctx = replace(previous.service.context, trusted_client=trusted, agent_slot_id=None if trusted else "slot-b")
        authority = DomainAuthority(comm.dsn, context=ctx, access_mode="owner")
        projects = ProjectService(SharedService(authority, LocalCredentialAuthenticator(ctx)), CATALOG,
                                  profile="root_manager" if trusted else "engineer")
        comm.clients[name] = McpRuntime(projects, previous.credential_provider)
    request = send(comm, activation="message_only")["data"]
    assert request["from"].startswith("client:")
    reply = call(comm, "b", "send_message", to=request["from"], content="My own Owner-mode Slot is B.",
                 reply_to=[request["message_handle"]], activation="message_only")["data"]
    assert reply["from"] == "collaborator:project-alpha:slot-b"
    assert wait(comm, "a", request["message_handle"])["state"] == "satisfied"
    rejected(comm, "b", "configure_team", "authorization_denied", members=[{"agent_slot_id": "slot-other", "principal_ref": "agent:other"}])


def test_bound_slot_cannot_claim_another_slot_or_gain_management(comm):
    client = comm.clients["b"]
    ctx = replace(client.service.context, agent_slot_id="local-slot")
    authority = DomainAuthority(comm.dsn, context=ctx)
    forged = McpRuntime(ProjectService(SharedService(authority, LocalCredentialAuthenticator(ctx)), CATALOG, profile="engineer"),
                        client.credential_provider)
    assert forged.call("send_message", {"project_id": "project-alpha", "to": "collaborator:project-alpha:slot-c",
                                        "content": "using the wrong transport binding"})["isError"]
    rejected(comm, "b", "configure_team", "authorization_denied", client_request_id=uuid.uuid4().hex,
             members=[{"agent_slot_id": "slot-other", "principal_ref": "agent:other"}])


def test_partial_configuration_preserves_contacts_and_rejects_stale_properties(comm):
    initial = call(comm, "a", "configure_team", members=[{"agent_slot_id": "slot-b", "principal_ref": "agent:b",
                     "display_name": "Researcher B"}, {"agent_slot_id": "slot-c", "principal_ref": "agent:c"}])
    assert initial["data"]["configuration_state"] == "committed"
    call(comm, "a", "configure_team", members=[{"agent_slot_id": "slot-b", "display_name": "B renamed",
                                               "if_unchanged": {"display_name": "Researcher B"}}])
    contacts = call(comm, "a", "list_collaborators")["data"]["items"]
    assert len(contacts) == 3
    assert next(item for item in contacts if item["agent_slot_id"] == "slot-b")["display_name"] == "B renamed"
    rejected(comm, "a", "configure_team", "revision_conflict", members=[{"agent_slot_id": "slot-b",
              "display_name": "stale edit", "if_unchanged": {"display_name": "Researcher B"}}])
    request = send(comm, activation="message_only")["data"]["message_handle"]
    send(comm, "b", "a", "Renamed but same identity", reply_to=[request], activation="message_only")
    assert wait(comm, "a", request)["state"] == "satisfied"


def test_same_principal_distinct_trusted_slots_are_not_the_same_author(comm):
    call(comm, "a", "configure_team", members=[{"agent_slot_id": "slot-shared-1", "principal_ref": "agent:shared"},
                                               {"agent_slot_id": "slot-shared-2", "principal_ref": "agent:shared"}])
    for number in (1, 2):
        slot = f"slot-shared-{number}"
        with psycopg.connect(comm.dsn) as connection:
            grant = connection.execute("SELECT grant_ref FROM collaboration_team_members WHERE agent_slot_id=%s", (slot,)).fetchone()[0]
        token = "test-shared-" + uuid.uuid4().hex
        ctx = replace(comm.authority.context, principal_ref="agent:shared", grant_ref=grant, agent_slot_id=slot,
                      credential_hash=hashlib.sha256(token.encode()).hexdigest())
        authority = DomainAuthority(comm.dsn, context=ctx)
        client = McpRuntime(ProjectService(SharedService(authority, LocalCredentialAuthenticator(ctx)), CATALOG, profile="engineer"),
                            lambda value=token: value)
        comm.clients[f"shared-{number}"] = client
        sent = send(comm, f"shared-{number}", "b", "same principal, separate author", activation="message_only",
                    client_request_id="same-transport-request-id")["data"]
        assert sent["from"] == "collaborator:project-alpha:" + slot
    history = call(comm, "b", "check_inbox")["data"]["items"]
    assert len({item["from"] for item in history}) == 2


def test_uncertain_native_ack_never_replays_and_does_not_block_real_reply(comm):
    request = send(comm)["data"]
    original_invoke = comm.drivers["b"].invoke
    def lose_ack(invocation):
        original_invoke(invocation)
        raise OSError("controlled loss after possible native dispatch")
    comm.drivers["b"].invoke = lose_ack
    identity = {"tenant_id": comm.authority.tenant_id, "message_id": request["message_id"], "operation_id": request["operation_id"]}
    assert comm.dispatcher.dispatch(identity)["status"] == "uncertain"
    for _ in range(2):
        restarted = DeliveryDispatcher(comm.dispatcher.service)
        assert restarted.dispatch(identity)["status"] == "uncertain"
    assert len(comm.drivers["b"].calls) == 1
    send(comm, "b", "a", "I received it despite the missing ACK.", reply_to=[request["message_handle"]], activation="message_only")
    assert wait(comm, "a", request["message_handle"])["state"] == "satisfied"


def test_observation_failure_retains_committed_send_and_usable_reference(comm, monkeypatch):
    def fail_observation(*_args, **_kwargs):
        raise OSError("controlled observation outage after commit")
    monkeypatch.setattr(comm.clients["a"].service, "_wait", fail_observation)
    result = send(comm, response_mode="sync", activation="message_only")
    assert result["state"] == "observation_unavailable"
    assert result["data"]["observation"]["message_committed"]
    assert call(comm, "b", "read_message", handle=result["data"]["message_handle"])["data"]["content"]


def test_relation_failure_rolls_back_message_and_delivery_effects(comm):
    request = send(comm, activation="message_only")["data"]["message_handle"]
    with psycopg.connect(comm.dsn) as connection:
        connection.execute("ALTER TABLE communication_replies ADD CONSTRAINT controlled_failure CHECK(reply_id='impossible')")
        before = connection.execute("SELECT (SELECT count(*) FROM delivery_messages),(SELECT count(*) FROM outbox),"
                                    "(SELECT count(*) FROM command_dedup)").fetchone()
    rejected(comm, "b", "send_message", "service_unavailable", to="collaborator:project-alpha:local-slot",
             content="This transaction cannot commit", reply_to=[request], activation="message_only")
    with psycopg.connect(comm.dsn) as connection:
        after = connection.execute("SELECT (SELECT count(*) FROM delivery_messages),(SELECT count(*) FROM outbox),"
                                   "(SELECT count(*) FROM command_dedup)").fetchone()
    assert before == after


def test_message_only_reaches_a_valid_slot_without_a_native_endpoint(comm):
    call(comm, "a", "configure_team", members=[{"agent_slot_id": "slot-new", "principal_ref": "agent:new"}], prepare_native=False)
    sent = call(comm, "a", "send_message", to="collaborator:project-alpha:slot-new", content="Read this when you connect.",
                activation="message_only")["data"]
    with psycopg.connect(comm.dsn) as connection:
        grant = connection.execute("SELECT grant_ref FROM collaboration_team_members WHERE agent_slot_id='slot-new'").fetchone()[0]
    token = "test-new-" + uuid.uuid4().hex
    ctx = replace(comm.authority.context, principal_ref="agent:new", grant_ref=grant, agent_slot_id="slot-new",
                  credential_hash=hashlib.sha256(token.encode()).hexdigest())
    comm.clients["new"] = McpRuntime(ProjectService(SharedService(DomainAuthority(comm.dsn, context=ctx), LocalCredentialAuthenticator(ctx)),
                                                   CATALOG, profile="engineer"), lambda: token)
    assert call(comm, "new", "check_inbox")["data"]["items"][0]["message_handle"] == sent["message_handle"]
    assert call(comm, "new", "read_message", handle=sent["message_handle"])["data"]["state"] == "delivered"
    call(comm, "a", "configure_team", members=[{"agent_slot_id": "slot-new", "permissions": ["profile.engineer", "message.read"]}],
         prepare_native=False)
    rejected(comm, "new", "send_message", "authorization_denied", to="collaborator:project-alpha:slot-b", content="revoked send capability")


def test_configuration_cannot_steal_an_existing_membership_slot(comm):
    rejected(comm, "a", "configure_team", "authorization_denied", members=[{"agent_slot_id": "slot-b", "principal_ref": "agent:c"}])


def test_expired_wait_lease_cannot_cause_a_second_native_ingress_after_result(comm, monkeypatch):
    request = send(comm, activation="message_only")["data"]["message_handle"]
    entered, release = __import__('threading').Event(), __import__('threading').Event()
    original = comm.clients["a"].service.execute
    def delay_read(name, args, credential):
        if name == "read_message" and not release.is_set():
            entered.set()
            assert release.wait(5)
        return original(name, args, credential)
    monkeypatch.setattr(comm.clients["a"].service, "execute", delay_read)
    with ThreadPoolExecutor(max_workers=1) as pool:
        waiting = pool.submit(call, comm, "a", "wait_for_response", handles=[request], timeout_seconds=8)
        assert entered.wait(5)
        with psycopg.connect(comm.dsn) as connection:
            connection.execute("UPDATE communication_waits SET expires_at=clock_timestamp()-interval '1 second'")
        reply = send(comm, "b", "a", "Late heartbeat, real reply", reply_to=[request])["data"]
        release.set()
        assert waiting.result(timeout=6)["state"] == "satisfied"
    assert comm.dispatcher.dispatch({"tenant_id": comm.authority.tenant_id, "message_id": reply["message_id"],
                                     "operation_id": reply["operation_id"]})["status"] == "delivered"
    assert comm.drivers["a"].calls == []


def test_configuration_selects_one_real_receiver_and_rejects_another_slots_receiver(comm, tmp_path):
    other_driver = AcceptingDriver()
    other = LocalNodeEndpoint(NodeJournal(tmp_path / "b-second.sqlite"), "local-scope", "slot-b", other_driver)
    comm.dispatcher.service.endpoints["endpoint-b-second"] = other
    comm.dispatcher.service.bind_endpoint(command(comm.authority, "message.bind", "endpoint-b-second"),
        EndpointBindingRequest(scope_id="local-scope", agent_slot_id="slot-b", expires_at=comm.authority.canonical_now()+timedelta(hours=1)))
    rejected(comm, "a", "send_message", "endpoint_binding_ambiguous", to="collaborator:project-alpha:slot-b", content="Choose deliberately")
    call(comm, "a", "configure_team", members=[{"agent_slot_id": "slot-b", "principal_ref": "agent:b", "endpoint_id": "endpoint-b-second"}],
         prepare_native=False)
    request = send(comm)["data"]
    assert comm.dispatcher.dispatch({"tenant_id": comm.authority.tenant_id, "message_id": request["message_id"],
                                     "operation_id": request["operation_id"]})["status"] == "delivered"
    assert len(other_driver.calls) == 1 and comm.drivers["b"].calls == []
    rejected(comm, "a", "configure_team", "authorization_denied", members=[{"agent_slot_id": "slot-b", "endpoint_id": "endpoint-a"}])


def test_communication_fault_notice_is_not_an_agent_reply(comm):
    from runtime.delivery_node import InvocationPreCallRejected
    def reject(_invocation):
        raise InvocationPreCallRejected("controlled native pre-call refusal")
    comm.drivers["b"].prepare = reject
    request = send(comm)["data"]
    result = comm.dispatcher.dispatch({"tenant_id": comm.authority.tenant_id, "message_id": request["message_id"],
                                       "operation_id": request["operation_id"]})
    assert result["status"] == "blocked"
    notices = call(comm, "a", "check_inbox")["data"]["notifications"]
    assert len(notices) == 1 and notices[0]["source"] == "acs"
    assert wait(comm, "a", request["message_handle"])["state"] == "timeout"
    assert call(comm, "a", "read_message", handle=notices[0]["notification_handle"])["data"]["code"] == "native_pre_call_rejected"


def test_query_filter_change_restarts_pagination(comm):
    send(comm, "a", "b", "first", activation="message_only")
    send(comm, "c", "b", "second", activation="message_only")
    first = call(comm, "b", "check_inbox", limit=1)["data"]
    assert first["next_cursor"]
    # A continuation cursor from another query must never permanently hide the
    # earlier matching message when filters change.
    result = call(comm, "b", "check_inbox", **{"cursor": first["next_cursor"], "with": "collaborator:project-alpha:local-slot"})["data"]
    assert [item["preview"] for item in result["items"]] == ["first"]


@pytest.mark.parametrize("tool", ["check_inbox", "list_messages"])
def test_empty_optional_peer_filter_keeps_inbox_and_cursor_semantics(comm, tool):
    """A real OpenCode caller supplies optional string fields as empty strings."""
    first = send(comm, "a", "b", "A's actual request", activation="message_only")["data"]
    second = send(comm, "c", "b", "C's separate request", activation="message_only")["data"]
    ordinary = call(comm, "b", tool, limit=1)["data"]
    blank = call(comm, "b", tool, limit=1, **{"with": "", "cursor": None})["data"]
    assert blank == ordinary
    assert blank["items"][0]["message_handle"] == first["message_handle"]
    continued = call(comm, "b", tool, cursor=ordinary["next_cursor"], **{"with": ""})["data"]
    assert not continued["cursor_reset"]
    assert [item["message_handle"] for item in continued["items"]] == [second["message_handle"]]
    narrowed = call(comm, "b", tool, **{"with": "collaborator:project-alpha:local-slot"})["data"]
    assert [item["message_handle"] for item in narrowed["items"]] == [first["message_handle"]]
    rejected(comm, "b", tool, "invalid_arguments", **{"with": " "})


def test_normal_send_native_read_reply_wait_and_history_do_not_need_task_tables(comm):
    with psycopg.connect(comm.dsn) as connection:
        assert connection.execute("SELECT to_regclass('work_items'),to_regclass('accepted_state_revisions'),"
                                  "to_regclass('collaboration_work_links')").fetchone() == (None, None, None)
    request = send(comm)["data"]
    assert comm.dispatcher.dispatch({"tenant_id": comm.authority.tenant_id, "message_id": request["message_id"],
                                     "operation_id": request["operation_id"]})["status"] == "delivered"
    assert call(comm, "b", "read_message", handle=request["message_handle"])["data"]["content"]
    send(comm, "b", "a", "Task tables were not needed.", reply_to=[request["message_handle"]], activation="message_only")
    assert wait(comm, "a", request["message_handle"])["state"] == "satisfied"
    assert len(call(comm, "a", "list_messages")["data"]["items"]) == 2


def test_legacy_packet_is_read_only_and_never_becomes_a_new_reply(project):
    from runtime_tests.test_delivery import send as legacy_send
    with psycopg.connect(project.dsn) as connection:
        connection.execute("INSERT INTO collaboration_work_links VALUES (%s,'project-alpha','work','existing-route','{}')",
                           (project.authority.tenant_id,))
    identity, _command, packet, _result = legacy_send(project)
    project.projects.initialize()  # Explicit adoption of stored historical associations.
    reply = project.mcp.call("read_message", {"project_id": "project-alpha", "handle": "message:project-alpha:" + identity["message_id"]})
    assert not reply["isError"], reply
    data = reply["structuredContent"]["data"]
    assert data["historical"] and data["content"]["request"] == packet.request
    assert data["reply_semantics"] == "native_output_is_not_an_explicit_reply"
    with psycopg.connect(project.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM collaboration_inbox_consumptions").fetchone()[0] == 0


def test_actual_stdio_mcp_processes_exchange_messages(comm, tmp_path):
    import asyncio
    import tempfile

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from runtime_tests.test_surfaces import profile

    def parameters(name):
        client = comm.clients[name]
        config, environment, _secret = profile(tmp_path, dsn=comm.dsn, context=client.service.context)
        return StdioServerParameters(command=sys.executable, args=["-m", "runtime.project_entry", "--config", str(config),
            "--catalog", str(ROOT / "docs/runtime/p2-mcp-tool-contract.json"), "--profile", client.service.profile],
            env=environment, cwd=str(ROOT))

    async def exercise():
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
            async with (stdio_client(parameters("a"), errlog=errors) as a_streams,
                        ClientSession(*a_streams, read_timeout_seconds=20) as a,
                        stdio_client(parameters("b"), errlog=errors) as b_streams,
                        ClientSession(*b_streams, read_timeout_seconds=20) as b):
                a_ready = await a.initialize()
                b_ready = await b.initialize()
                assert "ACS MCP server" in a_ready.instructions and "project_id" in a_ready.instructions
                assert b_ready.instructions == a_ready.instructions
                sent = await a.call_tool("send_message", {"project_id": "project-alpha", "to": "collaborator:project-alpha:slot-b",
                                                          "content": "Can you read this through MCP?", "activation": "message_only"})
                assert not sent.is_error, sent
                request = sent.structured_content["data"]["message_handle"]
                inbox = await b.call_tool("check_inbox", {"project_id": "project-alpha"})
                assert request in [item["message_handle"] for item in inbox.structured_content["data"]["items"]]
                original = await b.call_tool("read_message", {"project_id": "project-alpha", "handle": request})
                reply = await b.call_tool("send_message", {"project_id": "project-alpha", "to": original.structured_content["data"]["from"],
                    "content": "Yes, through my own MCP connection.", "reply_to": [request], "activation": "message_only"})
                assert not reply.is_error, reply
                observed = await a.call_tool("wait_for_response", {"project_id": "project-alpha", "handles": [request], "timeout_seconds": 0})
                assert observed.structured_content["state"] == "satisfied", observed
                resource = await b.read_resource("acs://projects/project-alpha/inbox")
                assert request in resource.contents[0].text
                facts = {"request": request, "reply": reply.structured_content["data"]["message_handle"],
                         "transport": "two real stdio MCP processes", "model_evidence": False}
                (tmp_path / "stdio-mcp.json").write_text(json.dumps(facts, indent=2))
    asyncio.run(exercise())


def test_maintenance_dispatches_committed_message_without_temporal(comm):
    import asyncio

    from runtime.communication_dispatch import maintain_communication_deliveries
    request = send(comm)["data"]

    async def run():
        task = asyncio.create_task(maintain_communication_deliveries(comm.clients["a"].service.service))
        try:
            end = time.monotonic() + 6
            while time.monotonic() < end:
                if comm.drivers["b"].calls:
                    return
                await asyncio.sleep(0.05)
            raise AssertionError("committed message was not activated")
        finally:
            task.cancel()
            with __import__('contextlib').suppress(asyncio.CancelledError):
                await task
    asyncio.run(run())
    assert len(comm.drivers["b"].calls) == 1
    assert wait(comm, "a", request["message_handle"])["state"] == "timeout"


def prepare_ordinary_agents(comm, tmp_path):
    # Provision two ordinary, separately authenticated Slots. The fixture's
    # management credential is used only by the external setup, never by A/B.
    ordinary_permissions = {"profile.engineer", "message.send", "message.read", "runtime.invoke"}
    for tool in ("list_projects", "load_project", "list_collaborators", "list_harnesses", "list_routes", "read_profile"):
        ordinary_permissions.update(comm.clients["a"].service.catalog["tools"][tool]["security_scopes"])
    token = "real-test-a-" + uuid.uuid4().hex
    ctx = replace(comm.authority.context, principal_ref="agent:a-real", grant_ref="grant:a-real", agent_slot_id="slot-a-real",
                  credential_hash=hashlib.sha256(token.encode()).hexdigest())
    with psycopg.connect(comm.dsn) as connection:
        connection.execute("INSERT INTO agent_slots VALUES ('slot-a-real',%s,'local-scope','active')", (ctx.tenant_id,))
        connection.execute("INSERT INTO grants SELECT %s,tenant_id,%s,authority_id,authority_incarnation,scope_id,%s,"
                           "expires_at,NULL FROM grants WHERE grant_ref='grant:p1'", (ctx.grant_ref, ctx.principal_ref, json.dumps(sorted(ordinary_permissions))))
        connection.execute("INSERT INTO collaboration_memberships VALUES (%s,'project-alpha',%s,%s,'engineer','slot-a-real')",
                           (ctx.tenant_id, ctx.principal_ref, ctx.grant_ref))
        connection.execute("UPDATE grants SET permissions=%s WHERE grant_ref='grant:b'", (json.dumps(sorted(ordinary_permissions)),))
    service = ProjectService(SharedService(DomainAuthority(comm.dsn, context=ctx), LocalCredentialAuthenticator(ctx)), CATALOG, profile="engineer")
    comm.clients["a"] = McpRuntime(service, lambda: token)
    b = comm.clients["b"]
    b_ctx = replace(b.service.context, agent_slot_id="slot-b")
    comm.clients["b"] = McpRuntime(ProjectService(SharedService(DomainAuthority(comm.dsn, context=b_ctx), LocalCredentialAuthenticator(b_ctx)),
                                                 CATALOG, profile="engineer"), b.credential_provider)
    endpoint = LocalNodeEndpoint(NodeJournal(tmp_path / "real-a.sqlite"), "local-scope", "slot-a-real", AcceptingDriver())
    comm.dispatcher.service.endpoints["endpoint-a-real"] = endpoint
    comm.dispatcher.service.bind_endpoint(command(comm.authority, "message.bind", "endpoint-a-real"),
        EndpointBindingRequest(scope_id="local-scope", agent_slot_id="slot-a-real", expires_at=comm.authority.canonical_now()+timedelta(hours=1)))


@pytest.mark.skipif(os.getenv("ACS_REAL_AGENT_TEST") != "1", reason="real independent Codex experiment is opt-in")
def test_real_independent_codex_agents_use_normal_mcp(comm, tmp_path):
    """Two actual model contexts, each authenticated to normal ACS stdio tools.

    The evaluator starts B after A has submitted. It does not relay content,
    provide a reply reference, or turn a native final answer into a Message.
    """
    binary = shutil.which("codex.exe") if os.name == "nt" else shutil.which("codex")
    if binary is None:
        pytest.skip("Codex executable unavailable")
    prepare_ordinary_agents(comm, tmp_path)
    label = "cedar-violet-" + uuid.uuid4().hex[:12]
    evidence = ROOT / "integration_evidence/acs-communication-20261031"
    evidence.mkdir(parents=True, exist_ok=True)
    processes = []

    def launch(name, prompt):
        runtime = comm.clients[name]
        config = tmp_path / f"{name}-surface.json"
        config.write_text(json.dumps({"context": asdict(runtime.service.context),
            "dsn_ref": {"kind": "environment", "name": "ACS_REAL_TEST_DSN"},
            "credential_ref": {"kind": "environment", "name": "ACS_REAL_TEST_CREDENTIAL"}}))
        config.chmod(0o600)
        wrapper = tmp_path / f"{name}-server.py"
        wrapper.write_text("import sys\nsys.path.insert(0," + repr(str(ROOT)) + ")\n"
            "from runtime.project_entry import main\nraise SystemExit(main(" + repr([
                "--config", str(config), "--catalog", str(ROOT / "docs/runtime/p2-mcp-tool-contract.json"),
                "--profile", runtime.service.profile]) + "))\n")
        environment = dict(os.environ, ACS_REAL_TEST_DSN=comm.dsn,
                           ACS_REAL_TEST_CREDENTIAL=runtime.credential_provider())
        for field in ("CODEX_THREAD_ID", "CODEX_INTERNAL_ORIGINATOR_OVERRIDE"):
            environment.pop(field, None)
        output = evidence / f"real-agent-{name}.jsonl"
        errors = evidence / f"real-agent-{name}.stderr.txt"
        use_wsl = os.getenv("ACS_REAL_AGENT_WSL") == "1"
        def wsl_path(path):
            value = Path(path).as_posix()
            return "/mnt/" + value[0].lower() + value[2:]
        command = (["wsl.exe", "-d", "Ubuntu", "--", "env", "WSLENV=ACS_REAL_TEST_DSN:ACS_REAL_TEST_CREDENTIAL",
                    "ACS_REAL_TEST_DSN=" + comm.dsn, "ACS_REAL_TEST_CREDENTIAL=" + runtime.credential_provider(),
                    "codex", "exec"] if use_wsl else [binary, "exec"])
        command += ["--ephemeral", "--json", "--skip-git-repo-check", "--sandbox", "read-only", "--cd",
                    wsl_path(tmp_path) if use_wsl else str(tmp_path), "-c", "project_doc_max_bytes=0", "-c",
                    "mcp_servers={acs={command=" + json.dumps(wsl_path(sys.executable) if use_wsl else sys.executable) +
                    ",args=[" + json.dumps(str(wrapper)) + "],env_vars=[\"ACS_REAL_TEST_DSN\",\"ACS_REAL_TEST_CREDENTIAL\"],"
                    "required=true,startup_timeout_sec=30,tool_timeout_sec=180,"
                    "tools={send_message={approval_mode=\"approve\"}}}}", prompt]
        if use_wsl:
            native_args = command[command.index("codex"):]
            launcher = tmp_path / f"{name}-launch.py"
            launcher.write_text("import subprocess\nraise SystemExit(subprocess.call(" + repr(native_args) + "))\n")
            environment["WSLENV"] = "ACS_REAL_TEST_DSN:ACS_REAL_TEST_CREDENTIAL"
            command = ["wsl.exe", "-d", "Ubuntu", "--", "python3", wsl_path(launcher)]
        with output.open("w", encoding="utf-8") as stdout, errors.open("w", encoding="utf-8") as stderr:
            process = subprocess.Popen(command, env=environment, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        processes.append(process)
        return process

    try:
        a = launch("a", "You are Agent A. Use the ACS communication app in project-alpha to find out from "
            "collaborator slot-b what the release label is for this isolated exercise, then report the exact label. "
            "Both participants run independently and can read Inbox; automatic native activation is unavailable "
            "in this experiment. Stay with the conversation until you receive B's answer. Do not change files.")
        end = time.monotonic() + 120
        while time.monotonic() < end:
            if call(comm, "b", "check_inbox")["data"]["items"]:
                break
            assert a.poll() is None, "A exited before communicating; see real-agent-a logs"
            time.sleep(0.3)
        else:
            pytest.fail("A did not submit a message within 120 seconds; see real-agent-a logs")
        b = launch("b", "You are Agent B, collaborator slot-b in the ACS communication app, project-alpha. "
            f"For this isolated exercise the release label is {label}. Assist A through ACS. "
            "Both participants run independently and can read Inbox; automatic native activation is unavailable "
            "in this experiment. Do not change files.")
        assert b.wait(timeout=180) == 0, "B failed; see real-agent-b logs"
        assert a.wait(timeout=180) == 0, "A failed; see real-agent-a logs"
        with psycopg.connect(comm.dsn) as connection:
            rows = connection.execute("SELECT c.message_id,c.sender,c.recipient,m.packet_json->>'content' FROM "
                "communication_messages c JOIN delivery_messages m USING(tenant_id,message_id) ORDER BY c.sequence").fetchall()
            replies = connection.execute("SELECT request_id,reply_id FROM communication_replies").fetchall()
            work_table_present = connection.execute("SELECT to_regclass('work_items')").fetchone()[0] is not None
            assert not work_table_present
            work_count = 0
        (evidence / "real-agent-facts.json").write_text(json.dumps({"messages": rows, "replies": replies,
            "work_count": work_count, "label": label, "transport": "real stdio MCP", "native_autoactivation": "not_tested",
            "actor_profiles": {"a": "engineer", "b": "engineer"}, "host_approval": "test-only send_message preauthorized"}, indent=2))
        assert work_count == 0 and replies
        assert any(label in row[3] and row[1].endswith(":slot-b") for row in rows)
        assert label in (evidence / "real-agent-a.jsonl").read_text(encoding="utf-8")
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
