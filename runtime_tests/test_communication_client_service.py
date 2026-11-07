"""Target client DTOs over actual isolated PG/ProjectService communication.

Native ACK callbacks remain explicitly synthetic. These tests exercise owning
metadata, caller ACL, original message identity, UTF-8 continuation and commit
semantics; no production contact, model or HTTP deployment is used.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import datetime

import pytest

from runtime.client_contracts import ClientContracts
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_client_storage import adopt_client_storage, read_delivery_version
from runtime.communication_http import CommunicationHttpError
from runtime.errors import AuthorizationDenied, IdempotencyConflict
from runtime.project_service import ProjectService
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send
from runtime_tests.test_communication_delivery_observer import lose_outer_ack
from runtime_tests.test_identity_root_management import accepted, actor, member
from runtime_tests.test_identity_root_management import owner_client as owner_client_fixture

comm = comm_fixture
owner_client = owner_client_fixture
PROJECT = "project-alpha"
PEER_B = "collaborator:project-alpha:slot-b"
CONTRACTS = ClientContracts()


def client(f, actor="a", **kwargs):
    current = f.clients[actor]
    return CommunicationClientService(current.service, current.credential_provider(), **kwargs)


def adopt(f):
    with f.authority._connect() as connection:
        adopt_client_storage(connection)


@pytest.fixture(autouse=True)
def adopted_client_storage(comm):
    # Explicit isolated-fixture adoption mirrors enabled client-service startup.
    # Adoption remains an operator action; request handlers must never run DDL.
    adopt(comm)


def body(content="Client-facing natural message", **fields):
    return {"to": PEER_B, "content": content} | fields


def dispatch(f, sent):
    return f.dispatcher.dispatch({"tenant_id": f.authority.tenant_id,
        "message_id": sent["message_id"], "operation_id": sent["operation_id"]})


def test_global_profile_preserves_actual_client_null_slot_and_bound_agent_identity(comm, owner_client):
    trusted = CommunicationClientService(owner_client.service, owner_client.credential_provider()).profile()
    CONTRACTS.validate("Actor", trusted)
    assert trusted["level"] == "client" and trusted["agent_slot_id"] is None
    assert trusted["principal_ref"] == owner_client.service.context.principal_ref
    assert trusted["auth_revision"] and "configure_root" in trusted["allowed_actions"]
    ordinary = member(comm, owner_client, "client-test-engineer", "engineer", "engineer")
    actual = CommunicationClientService(ordinary.service, ordinary.credential_provider()).profile()
    CONTRACTS.validate("Actor", actual)
    assert actual["level"] == "agent" and actual["agent_slot_id"] == "client-test-engineer"
    assert actual["principal_ref"] == ordinary.service.context.principal_ref
    assert "configure_team" not in actual["allowed_actions"]


def test_projects_routes_and_contacts_are_target_dtos_from_owning_metadata(comm):
    service = client(comm)
    projects = service.projects()
    routes = service.routes(PROJECT)
    contacts = service.contacts(PROJECT)
    for kind, value in (("ProjectPage", projects), ("RoutePage", routes), ("ContactPage", contacts)):
        CONTRACTS.validate(kind, value)
    project = next(item for item in projects["items"] if item["project_id"] == PROJECT)
    assert project["name"] == "Isolated communication" and project["revision"] == 1
    assert "send_message" in project["allowed_actions"]
    own = next(item for item in contacts["items"] if item["is_self"])
    assert own["address"] == "collaborator:project-alpha:local-slot"
    assert own["agent_slot_id"] == "local-slot" and own["revision"] >= 0
    b = next(item for item in contacts["items"] if item["address"] == PEER_B)
    assert b["receiver_refs"] == ["endpoint-b"]
    assert not any(driver.calls for driver in comm.drivers.values())


def test_shared_engineer_default_profile_denies_projects_and_explicit_profile_tracks_narrowed_grant(comm):
    declared = member(comm, comm.clients["a"], "client-projects-engineer", "engineer", "engineer")
    permitted = {"load_project", "list_routes", "list_collaborators", "list_messages", "read_message", "send_message"}
    permissions = {"profile.engineer"}
    for name in {*permitted, "list_projects"}:
        permissions.update(declared.service.catalog["tools"][name]["security_scopes"])
    accepted(comm.clients["a"], "configure_team", project_id=PROJECT, client_request_id="client-projects-engineer-scopes",
             members=[{"agent_slot_id": "client-projects-engineer", "permissions": sorted(permissions)}], prepare_native=False)
    ordinary = actor(comm, declared.service.context, "engineer", declared.credential_provider(), access_mode="shared")
    default = CommunicationClientService(ordinary.service, ordinary.credential_provider())
    assert not {"list_projects", "list_routes"}.intersection(ordinary.service.catalog["profiles"]["engineer"])
    with pytest.raises(AuthorizationDenied):
        default.projects()

    # Explicit server-owned fixture variant: authorize namespace discovery in
    # this Profile, while retaining the same real Slot, identity and scoped Grant.
    # The shipped engineer Profile remains denied, as asserted above.
    catalog = deepcopy(ordinary.service.catalog)
    catalog["profiles"]["engineer"].extend(["list_projects", "list_routes"])
    configured = ProjectService(ordinary.service.service, catalog, profile="engineer")
    service = CommunicationClientService(configured, ordinary.credential_provider())
    baseline = service.projects()
    CONTRACTS.validate("ProjectPage", baseline)
    assert [item["project_id"] for item in baseline["items"]] == [PROJECT]
    assert set(baseline["items"][0]["allowed_actions"]) == permitted
    assert not {"configure_team", "create_route"}.intersection(baseline["items"][0]["allowed_actions"])

    # Keep actual project discovery rights while removing message-read scope.
    # Denied action discovery must not turn the whole project query into a 403.
    with comm.authority._connect() as connection:
        connection.execute("UPDATE grants SET permissions=permissions-'message.read' WHERE grant_ref=%s",
                           (ordinary.service.context.grant_ref,))
    narrowed = service.projects()
    CONTRACTS.validate("ProjectPage", narrowed)
    assert [item["project_id"] for item in narrowed["items"]] == [PROJECT]
    assert set(narrowed["items"][0]["allowed_actions"]) == permitted - {"list_messages", "read_message"}
    assert not {"configure_team", "create_route"}.intersection(narrowed["items"][0]["allowed_actions"])
    assert not any(driver.calls for driver in comm.drivers.values())


def test_original_and_embedded_reply_utf8_metadata_have_independent_continuations(comm):
    original_text = "A🧭汉" * 14
    original = send(comm, content=original_text, activation="message_only")["data"]
    reply_text = "🙂汉字" * 12
    reply = send(comm, "b", "a", reply_text, reply_to=[original["message_handle"]], activation="message_only")["data"]
    service = client(comm)
    result = service.read_message(PROJECT, original["message_handle"], max_inline_bytes=1)
    CONTRACTS.validate("ReadMessageResponse", result)
    message, first = result["message"], result["first_reply"]
    assert message["content"] == {"text": "A", "offset": 0, "next_offset": 1,
        "total_bytes": len(original_text.encode()), "digest": hashlib.sha256(original_text.encode()).hexdigest()}
    assert first["message_handle"] == reply["message_handle"]
    assert first["content"] == {"text": "", "offset": 0, "next_offset": 0,
        "total_bytes": len(reply_text.encode()), "digest": hashlib.sha256(reply_text.encode()).hexdigest()}
    assert message["first_reply_handle"] == reply["message_handle"] and message["revision"] == 2
    assert first["first_reply_handle"] is None and first["revision"] == 1
    assert {item["message_handle"] for item in result["continuations"]} == {original["message_handle"], reply["message_handle"]}
    continuation = next(item for item in result["continuations"] if item["message_handle"] == reply["message_handle"])
    assert continuation["offset"] == 0 and continuation["max_inline_bytes"] >= 4
    resumed = service.read_message(PROJECT, reply["message_handle"], offset=continuation["offset"],
                                   max_inline_bytes=continuation["max_inline_bytes"])
    assert resumed["message"]["content"]["text"] == "🙂"
    with comm.authority._connect() as connection:
        actual = connection.execute("SELECT created_at FROM delivery_messages WHERE message_id=%s", (original["message_id"],)).fetchone()[0]
    assert datetime.fromisoformat(message["committed_at"]) == actual
    assert not any(driver.calls for driver in comm.drivers.values())


def test_message_revision_tracks_explicit_reply_relation_but_immutable_body_stays_exact(comm):
    original = send(comm, activation="message_only")["data"]
    service = client(comm)
    initial = service.read_message(PROJECT, original["message_handle"])["message"]
    first = send(comm, "b", "a", "First explicit reply", reply_to=[original["message_handle"]], activation="message_only")["data"]
    updated = service.read_message(PROJECT, original["message_handle"])["message"]
    send(comm, "b", "a", "Second explicit reply", reply_to=[original["message_handle"]], activation="message_only")
    later = service.read_message(PROJECT, original["message_handle"])["message"]
    assert (initial["revision"], updated["revision"], later["revision"]) == (1, 2, 3)
    assert later["first_reply_handle"] == first["message_handle"]
    assert initial["content"] == updated["content"] == later["content"]


def test_delivery_metadata_accepts_emoji_first_body_without_reading_it_as_one_byte(comm):
    original = send(comm, content="🙂 delivery facts do not need body bytes", activation="message_only")["data"]
    observed = client(comm).delivery(PROJECT, original["message_handle"])
    CONTRACTS.validate("DeliveryFacts", observed)
    assert observed["native"]["state"] == "not_requested"
    assert observed["consumption"]["state"] == "unobservable" and not observed["response"]["present"]


def test_native_result_is_never_explicit_response_and_unknown_can_have_real_reply(comm, monkeypatch):
    original, _endpoint = lose_outer_ack(comm, monkeypatch)
    service = client(comm)
    before = service.delivery(PROJECT, original["message_handle"])
    assert before["accepted_by_authority"] and before["native"]["state"] == "unknown"
    assert before["response"] == {"present": False, "message_handle": None}
    reply = send(comm, "b", "a", "Clarification is an actual reply", reply_to=[original["message_handle"]], activation="message_only")["data"]
    after = service.delivery(PROJECT, original["message_handle"])
    assert after["native"]["state"] == "unknown"
    assert after["response"] == {"present": True, "message_handle": reply["message_handle"]}
    assert after["consumption"]["state"] == "unobservable" and len(comm.drivers["b"].calls) == 1


def test_client_send_defaults_and_duplicate_preserve_original_message_operation(comm):
    service = client(comm)
    first = service.send(PROJECT, body(), client_request_id="http-default-send")
    duplicate = service.send(PROJECT, body(), client_request_id="http-default-send")
    CONTRACTS.validate("SendResponse", first)
    CONTRACTS.validate("SendResponse", duplicate)
    assert not first["duplicate"] and duplicate["duplicate"]
    assert first["message"]["message_handle"] == duplicate["message"]["message_handle"]
    assert first["operation_ref"] == duplicate["operation_ref"]
    assert first["message"]["sender"] == "collaborator:project-alpha:local-slot"
    assert first["wait"]["state"] == "not_requested" and first["delivery"]["native"]["state"] == "pending"
    with pytest.raises(IdempotencyConflict):
        service.send(PROJECT, body("Changed canonical text"), client_request_id="http-default-send")
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT packet_json->>'activation',packet_json->>'response_mode' FROM delivery_messages").fetchone() == ("invoke", "async")
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone() == (1,)


def test_message_only_sync_timeout_is_a_committed_send_not_a_send_failure(comm):
    result = client(comm).send(PROJECT, body(activation="message_only", response_mode="sync", wait_timeout_seconds=0),
                               client_request_id="http-message-only-sync")
    CONTRACTS.validate("SendResponse", result)
    assert result["wait"]["state"] == "timed_out" and result["operation_ref"]
    assert result["delivery"]["native"]["state"] == "not_requested"
    assert not any(driver.calls for driver in comm.drivers.values())
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM delivery_messages").fetchone() == (1,)


def test_http_utf8_limit_is_256kib_without_enlarging_old_mcp_limit(comm):
    content = "A" + "🙂" * 65535 + "abc"
    assert len(content.encode()) == 262144
    result = client(comm).send(PROJECT, body(content, activation="message_only"), client_request_id="http-large-body")
    assert result["message"]["content"]["total_bytes"] == 262144
    assert result["message"]["content"]["digest"] == hashlib.sha256(content.encode()).hexdigest()
    assert not hasattr(comm.clients["a"].service, "_client_content_limit")
    legacy = comm.clients["a"].call("send_message", {"project_id": PROJECT, **body(content, activation="message_only"),
        "client_request_id": "mcp-large-rejected"})["structuredContent"]
    assert not legacy["ok"]
    with pytest.raises(ValueError):
        client(comm).send(PROJECT, body(content + "x", activation="message_only"), client_request_id="http-over-limit")
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone() == (1,)
    assert not any(driver.calls for driver in comm.drivers.values())


def test_post_commit_observation_failure_retains_effect_and_same_operation_on_retry(comm, monkeypatch):
    service = client(comm)
    read = service.read_message

    def unavailable(*_args, **_kwargs):
        raise OSError("controlled view failure after message commit")

    monkeypatch.setattr(service, "read_message", unavailable)
    with pytest.raises(CommunicationHttpError) as error:
        service.send(PROJECT, body(activation="message_only"), client_request_id="committed-before-view-loss")
    assert error.value.effect_state == "committed" and error.value.operation_ref
    assert not error.value.retryable
    with comm.authority._connect() as connection:
        stored = connection.execute("SELECT operation_id FROM delivery_messages").fetchone()[0]
    assert stored == error.value.operation_ref
    monkeypatch.setattr(service, "read_message", read)
    duplicate = service.send(PROJECT, body(activation="message_only"), client_request_id="committed-before-view-loss")
    assert duplicate["duplicate"] and duplicate["operation_ref"] == stored
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone() == (1,)


def test_private_message_delivery_and_operation_queries_recheck_acl_and_revocation(comm):
    original = send(comm, activation="message_only")["data"]
    third = client(comm, "c")
    for query in (lambda: third.read_message(PROJECT, original["message_handle"]),
                  lambda: third.delivery(PROJECT, original["message_handle"]),
                  lambda: third.operation(original["operation_id"], project_id=PROJECT)):
        with pytest.raises(AuthorizationDenied):
            query()
    own = client(comm)
    own.read_message(PROJECT, original["message_handle"])
    with comm.authority._connect() as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (comm.authority.context.grant_ref,))
    with pytest.raises(AuthorizationDenied):
        own.delivery(PROJECT, original["message_handle"])


def test_operation_versions_and_timestamps_come_from_owning_delivery_projection(comm):
    original = send(comm)["data"]
    service = client(comm)
    before = service.operation(original["operation_id"], project_id=PROJECT)
    assert dispatch(comm, original)["status"] == "delivered"
    after = service.operation(original["operation_id"], project_id=PROJECT)
    with comm.authority._connect() as connection, connection.cursor() as cursor:
        revision, updated = read_delivery_version(cursor, comm.authority.tenant_id, original["message_id"])
    CONTRACTS.validate("Operation", after)
    assert after["operation_id"] == original["operation_id"] and after["message_handle"] == original["message_handle"]
    assert after["state"] == "accepted" and after["effect_state"] == "native_possible"
    assert after["revision"] == revision and after["revision"] > before["revision"]
    assert datetime.fromisoformat(after["updated_at"]) == datetime.fromisoformat(updated)
    assert datetime.fromisoformat(after["updated_at"]) > datetime.fromisoformat(after["created_at"])


def test_message_snapshot_cursor_excludes_late_arrivals_and_is_actor_filter_bound(comm):
    first = send(comm, content="Pair message one", activation="message_only")["data"]
    send(comm, to="c", content="Other conversation secret", activation="message_only")
    second = send(comm, "b", "a", "Pair message two", activation="message_only")["data"]
    service = client(comm)
    page = service.messages(PROJECT, limit=1, peer=PEER_B)
    assert page["items"][0]["message_handle"] == first["message_handle"]
    assert page["items"][0]["conversation_sequence"] == "1"
    assert page["page"]["next_cursor"] and page["page"]["snapshot_id"]
    late = send(comm, content="After fixed boundary", activation="message_only")["data"]
    tail = service.messages(PROJECT, limit=1, peer=PEER_B, cursor=page["page"]["next_cursor"])
    CONTRACTS.validate("MessagePage", tail)
    assert [item["message_handle"] for item in tail["items"]] == [second["message_handle"]]
    assert tail["items"][0]["conversation_sequence"] == "2" and tail["page"]["next_cursor"] is None
    assert late["message_handle"] not in {item["message_handle"] for item in page["items"] + tail["items"]}
    anchored_tail = service.messages(PROJECT, limit=1, peer=PEER_B, cursor=page["page"]["next_cursor"],
                                     snapshot_id=page["page"]["snapshot_id"])
    assert anchored_tail["items"] == tail["items"]
    assert anchored_tail["page"]["snapshot_id"] == page["page"]["snapshot_id"]
    for query in (lambda: service.messages(PROJECT, peer="collaborator:project-alpha:slot-c", cursor=page["page"]["next_cursor"]),
                  lambda: client(comm, "b").messages(PROJECT, peer=PEER_B, cursor=page["page"]["next_cursor"]),
                  lambda: service.messages(PROJECT, peer=PEER_B, cursor=page["page"]["next_cursor"][:-2] + "xx"),
                  lambda: service.messages(PROJECT, peer=PEER_B, snapshot_id=page["page"]["next_cursor"]),
                  lambda: service.messages(PROJECT, peer=PEER_B, cursor=page["page"]["next_cursor"],
                                           snapshot_id=page["page"]["next_cursor"])):
        with pytest.raises(CommunicationHttpError) as error:
            query()
        assert error.value.code == "cursor_invalid"
