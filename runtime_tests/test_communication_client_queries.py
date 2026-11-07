"""Client read bridge: actual PostgreSQL authorization plus labeled serializer fixtures."""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from runtime.communication_client_queries import (
    ClientProjection,
    ClientQueryUnavailable,
    CommunicationClientQueries,
    conversation_view_id,
)
from runtime.errors import AuthorizationDenied, InvalidToolArgument
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send
from runtime_tests.test_identity_root_management import owner_client as owner_client_fixture

comm = comm_fixture
owner_client = owner_client_fixture


def bridge(f, name="a"):
    client = f.clients[name]
    return CommunicationClientQueries(client.service, client.credential_provider)


def test_pg_utf8_original_and_first_reply_have_independent_exact_body_metadata(comm):
    content = "A🧭汉字" * 12
    original = send(comm, content=content, activation="message_only")["data"]
    reply_content = "汉🧭"
    replied = send(comm, "b", "a", reply_content, reply_to=[original["message_handle"]], activation="message_only")["data"]
    queries = bridge(comm)
    observed = queries.read_message("project-alpha", original["message_handle"], max_inline_bytes=1)
    message, reply = observed.data["message"], observed.data["first_reply"]
    assert message["content"] == {"text": "A", "offset": 0, "next_offset": 1,
        "total_bytes": len(content.encode()), "digest": hashlib.sha256(content.encode()).hexdigest()}
    assert reply["message_handle"] == replied["message_handle"]
    assert reply["content"] == {"text": "", "offset": 0, "next_offset": 0,
        "total_bytes": len(reply_content.encode()), "digest": hashlib.sha256(reply_content.encode()).hexdigest()}
    assert {action["message_handle"] for action in observed.data["continuations"]} == {
        original["message_handle"], replied["message_handle"]}
    continued = next(action for action in observed.data["continuations"] if action["message_handle"] == replied["message_handle"])
    assert continued["offset"] == 0 and continued["max_inline_bytes"] >= 3
    resumed = queries.read_message("project-alpha", continued["message_handle"], offset=continued["offset"],
                                   max_inline_bytes=continued["max_inline_bytes"])
    assert resumed.data["message"]["content"]["text"] == "汉"
    assert "message.committed_at" in observed.missing_fields
    assert "message.conversation_sequence" in observed.missing_fields
    assert "message.revision" in observed.missing_fields
    with pytest.raises(ClientQueryUnavailable):
        observed.require_complete()
    assert all(not driver.calls for driver in comm.drivers.values())
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone() == (1,)


def test_pg_message_page_retains_cursor_peer_relation_and_does_not_publish_global_sequence(comm):
    originals = [send(comm, content="Message " + str(index), activation="message_only")["data"] for index in range(3)]
    send(comm, "a", "c", "Other peer is not part of this page", activation="message_only")
    queries = bridge(comm)
    first = queries.messages_page("project-alpha", peer="collaborator:project-alpha:slot-b", limit=2, max_inline_bytes=3)
    second = queries.messages_page("project-alpha", peer="collaborator:project-alpha:slot-b", limit=2,
                                   cursor=first.data["page"]["next_cursor"], max_inline_bytes=3)
    assert [item["message_handle"] for item in first.data["items"] + second.data["items"]] == [
        item["message_handle"] for item in originals]
    assert all("sequence" not in item and "conversation_sequence" not in item
               for item in first.data["items"] + second.data["items"])
    assert first.data["page"]["snapshot_id"] is None
    assert first.metadata["snapshot_consistency"] == "not_provided_by_legacy_query"
    assert first.metadata["resume_cursor"] and first.metadata["continuations"]
    assert all(not driver.calls for driver in comm.drivers.values())


def test_pg_private_message_delivery_and_operation_still_require_actual_participant(comm):
    original = send(comm, activation="message_only")["data"]
    outsider = bridge(comm, "c")
    for call in (
        lambda: outsider.read_message("project-alpha", original["message_handle"]),
        lambda: outsider.delivery("project-alpha", original["message_handle"]),
        lambda: outsider.operation("project-alpha", original["operation_id"], message_handle=original["message_handle"]),
    ):
        with pytest.raises(AuthorizationDenied):
            call()
    with pytest.raises(ClientQueryUnavailable, match="authorized_message_context"):
        bridge(comm).operation("project-alpha", original["operation_id"])
    with pytest.raises(InvalidToolArgument):
        bridge(comm).operation("project-alpha", "not-the-original-operation", message_handle=original["message_handle"])


def test_pg_delivery_facts_do_not_turn_native_ack_or_reads_into_peer_reply_or_consumption(comm):
    original = send(comm)["data"]
    comm.dispatcher.dispatch({"tenant_id": comm.authority.tenant_id, "message_id": original["message_id"],
                              "operation_id": original["operation_id"]})
    queries = bridge(comm)
    observed = queries.delivery("project-alpha", original["message_handle"])
    assert observed.data["native"]["state"] == "accepted"  # Actual Authority ACK high-water.
    assert observed.data["response"] == {"present": False, "message_handle": None}
    assert observed.data["consumption"] == {"state": "not_observed", "semantics": "provider_input_consumed", "evidence_ref": None}
    assert {"native.operation_ref", "native.evidence_ref", "revision"} <= set(observed.missing_fields)
    assert observed.data["native"]["operation_ref"] is None  # Do not conflate Core and Native IDs.
    with pytest.raises(ClientQueryUnavailable):
        observed.require_complete()
    waited = queries.wait_for_response("project-alpha", [original["response_handle"]], timeout_seconds=0)
    assert waited.data["wait"] == {"state": "timed_out", "satisfied_handles": [], "pending_handles": [original["response_handle"]]}
    assert waited.data["items"][0]["response"]["present"] is False
    assert len(comm.drivers["b"].calls) == 1


def test_pg_wait_uses_explicit_reply_and_retains_continuations_without_resending(comm):
    original = send(comm, activation="message_only")["data"]
    reply = send(comm, "b", "a", "汉" * 8000, reply_to=[original["message_handle"]], activation="message_only")["data"]
    observed = bridge(comm).wait_for_response("project-alpha", [original["message_handle"]], timeout_seconds=0)
    assert observed.data["wait"]["state"] == "satisfied"
    assert observed.data["wait"]["satisfied_handles"] == [original["message_handle"]]
    assert observed.data["items"][0]["response"] == {"present": True, "message_handle": reply["message_handle"]}
    assert any(action["message_handle"] == reply["message_handle"] and action["offset"] > 0
               for action in observed.data["continuations"])
    assert all(not driver.calls for driver in comm.drivers.values())
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone() == (2,)


def test_pg_trusted_client_profile_keeps_actual_null_slot_without_synthetic_root(owner_client):
    queries = CommunicationClientQueries(owner_client.service, owner_client.credential_provider)
    profile = queries.profile("project-alpha")
    assert profile.data["level"] == "client" and profile.data["agent_slot_id"] is None
    assert profile.data["address"].startswith("client:project-alpha:")
    assert "auth_revision" in profile.missing_fields
    assert "allowed_actions" not in profile.data
    contacts = queries.contacts_page("project-alpha")
    assert contacts.metadata["self_address"] == profile.data["address"]
    assert not any(contact["is_self"] for contact in contacts.data["items"])


def test_pg_project_and_contact_metadata_gaps_are_explicit_not_fabricated(comm):
    queries = bridge(comm)
    projects = queries.projects_page(limit=1)
    assert projects.data["items"][0]["project_id"] == "project-alpha"
    assert projects.data["items"][0]["revision"] == 1
    assert "items[0].name" in projects.missing_fields and "name" not in projects.data["items"][0]
    contacts = queries.contacts_page("project-alpha")
    assert all(item["role"] is None for item in contacts.data["items"])
    assert all("revision" not in item and "receiver_refs" not in item for item in contacts.data["items"])
    assert any(name.endswith("receiver_refs") for name in contacts.missing_fields)


def test_pg_revocation_is_rechecked_by_each_query(comm):
    original = send(comm, activation="message_only")["data"]
    queries = bridge(comm)
    queries.read_message("project-alpha", original["message_handle"])
    with comm.authority._connect() as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (comm.authority.context.grant_ref,))
    with pytest.raises(AuthorizationDenied):
        queries.read_message("project-alpha", original["message_handle"])
    with pytest.raises(AuthorizationDenied):
        queries.delivery("project-alpha", original["message_handle"])


def test_view_identity_is_unordered_tenant_project_and_stable_address_scoped():
    a, b = "collaborator:p:a", "collaborator:p:b"
    assert conversation_view_id("tenant", "p", a, b) == conversation_view_id("tenant", "p", b, a)
    assert conversation_view_id("other-tenant", "p", a, b) != conversation_view_id("tenant", "p", a, b)
    with pytest.raises(ValueError):
        conversation_view_id("tenant", "p", "native-session-id", b)
    with pytest.raises(ValueError):
        conversation_view_id("tenant", "p", "collaborator:another-project:a", b)


def test_partial_projection_requires_explicit_completion_and_returns_copies():
    projection = ClientProjection("Actor", {"address": "collaborator:p:a"}, ("auth_revision",))
    assert not projection.complete
    with pytest.raises(ClientQueryUnavailable) as raised:
        projection.require_complete()
    assert raised.value.code == "unsupported_projection" and raised.value.missing_fields == ("auth_revision",)
    complete = ClientProjection("PageInfo", {"next_cursor": None, "snapshot_id": None})
    copied = complete.require_complete()
    copied["next_cursor"] = "mutated"
    assert complete.data["next_cursor"] is None


def test_serializer_fixture_never_infers_client_from_null_slot_or_profile_name():
    class Source:
        context = SimpleNamespace(tenant_id="tenant")

        def execute(self, name, _args, credential):
            assert credential == "synthetic-current-credential"
            if name == "read_profile":
                return "observed", {"subject": "synthetic-agent", "profile": "root_manager", "connection_state": "authorized",
                    "actor": {"organization": {"level": "agent"}, "agent_slot_id": None,
                              "binding_source": "trusted_collaborator_binding"}}, []
            assert name == "list_collaborators"
            return "observed", {"self": "collaborator:p:actual", "items": [], "next_cursor": None}, []

    result = CommunicationClientQueries(Source(), lambda: "synthetic-current-credential").profile("p")
    assert result.data["level"] == "agent" and result.data["agent_slot_id"] is None
    assert result.metadata["binding_source"] == "trusted_collaborator_binding"


def test_serializer_fixture_each_metadata_fetch_reauthorizes_with_current_credential():
    content = "A汉"
    current = ["valid"]
    calls = []

    class Source:
        context = SimpleNamespace(tenant_id="tenant")

        def execute(self, name, args, credential):
            calls.append((name, args, credential))
            if credential != "valid":
                raise AuthorizationDenied("synthetic-agent", "synthetic-grant")
            current[0] = "revoked"
            return "observed", {"message_handle": "message:p:m", "project_id": "p", "from": "collaborator:p:a",
                "to": "collaborator:p:b", "reply_to": [], "activation": "message_only", "operation_id": "core-operation",
                "content": content[0], "next_offset": 1, "reply": None}, []

    queries = CommunicationClientQueries(Source(), lambda: current[0])
    with pytest.raises(AuthorizationDenied):
        queries.read_message("p", "message:p:m", max_inline_bytes=1)
    assert [call[2] for call in calls] == ["valid", "revoked"]


def test_serializer_fixture_archived_task_packets_remain_explicitly_unsupported():
    class Source:
        def execute(self, *_args):
            return "observed", {"historical": True, "content": {"request": "retired task packet"}}, []

    with pytest.raises(ClientQueryUnavailable, match="natural_message_body"):
        CommunicationClientQueries(Source(), lambda: "fixture").read_message("p", "message:p:archive")


def test_serializer_fixture_route_projection_uses_actual_definition_and_revision():
    class Source:
        def execute(self, name, args, credential):
            assert (name, args, credential) == ("list_routes", {"project_id": "p", "cursor": None, "limit": 50}, "fixture")
            return "observed", {"items": [{"route_handle": "route:p:r", "scope_id": "actual-scope", "state": "active",
                "revision": 7, "definition": {"display_name": "Actual route name", "goal": "Actual route goal"}}],
                "next_cursor": "route:p:r"}, []

    result = CommunicationClientQueries(Source(), lambda: "fixture").routes_page("p")
    assert result.require_complete() == {"items": [{"route_handle": "route:p:r", "project_id": "p",
        "scope_handle": "scope:p:actual-scope", "display_name": "Actual route name", "goal": "Actual route goal",
        "state": "active", "revision": 7}], "page": {"next_cursor": "route:p:r", "snapshot_id": None}}


def test_serializer_fixture_offset_body_and_missing_continuation_metadata_are_distinct():
    class Source:
        context = SimpleNamespace(tenant_id="tenant")

        def __init__(self):
            self.omit_boundary = False

        def execute(self, _name, args, _credential):
            content = "A汉"
            value = {"message_handle": "message:p:m", "project_id": "p", "from": "collaborator:p:a",
                "to": "collaborator:p:b", "reply_to": [], "activation": "message_only", "operation_id": "core-operation",
                "content": content if args["offset"] == 0 else "汉", "reply": None}
            if not self.omit_boundary:
                value["next_offset"] = None
            return "observed", value, []

    source = Source()
    queries = CommunicationClientQueries(source, lambda: "fixture")
    result = queries.read_message("p", "message:p:m", offset=1, max_inline_bytes=3)
    assert result.data["message"]["content"] == {"text": "汉", "offset": 1, "next_offset": None,
        "total_bytes": 4, "digest": hashlib.sha256("A汉".encode()).hexdigest()}
    source.omit_boundary = True
    with pytest.raises(ClientQueryUnavailable, match="body_continuation_metadata"):
        queries.read_message("p", "message:p:m", max_inline_bytes=3)


def test_serializer_fixture_later_metadata_probe_does_not_fabricate_an_earlier_reply():
    original = {"message_handle": "message:p:m", "project_id": "p", "from": "collaborator:p:a",
        "to": "collaborator:p:b", "reply_to": [], "activation": "message_only", "operation_id": "core-operation"}

    class Source:
        context = SimpleNamespace(tenant_id="tenant")

        def execute(self, _name, args, _credential):
            if args["max_inline_bytes"] == 1:
                return "observed", {**original, "content": "A", "next_offset": 1, "reply": None}, []
            reply = {"message_handle": "message:p:late", "project_id": "p", "from": "collaborator:p:b",
                "to": "collaborator:p:a", "reply_to": ["message:p:m"], "activation": "message_only",
                "operation_id": "another-operation", "content": "Late reply", "next_offset": None}
            return "observed", {**original, "content": "A汉", "next_offset": None, "reply": reply}, []

    result = CommunicationClientQueries(Source(), lambda: "fixture").read_message("p", "message:p:m", max_inline_bytes=1)
    assert result.data["first_reply"] is None and result.data["message"]["first_reply_handle"] is None
    assert result.data["message"]["content"]["digest"] == hashlib.sha256("A汉".encode()).hexdigest()
