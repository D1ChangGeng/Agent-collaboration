"""Personal-state service authorization over actual disposable PostgreSQL."""
from __future__ import annotations

from types import SimpleNamespace

import psycopg
import pytest

from runtime.client_contracts import ClientContracts, ClientContractViolation
from runtime.communication_client_queries import conversation_view_id
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_client_state import ClientStateService
from runtime.communication_client_storage import MAX_DRAFT_BYTES, adopt_client_storage
from runtime.communication_http import CommunicationHttpError
from runtime.errors import AuthorizationDenied, IdempotencyConflict, NotFound, RevisionConflict
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send

comm = comm_fixture
PROJECT = "project-alpha"
ADDRESSES = {"a": "collaborator:project-alpha:local-slot",
             "b": "collaborator:project-alpha:slot-b", "c": "collaborator:project-alpha:slot-c"}


def service(f, caller="a"):
    # The integration owner adds the mixin to the public service separately.
    service_type = (CommunicationClientService if issubclass(CommunicationClientService, ClientStateService)
                    else type("PrivateStateHarness", (ClientStateService, CommunicationClientService), {}))
    client = f.clients[caller]
    return service_type(client.service, client.credential_provider())


def conversation(f, first="a", second="b", project=PROJECT):
    return conversation_view_id(f.authority.tenant_id, project, ADDRESSES[first], ADDRESSES[second])


@pytest.fixture
def personal(comm):
    with psycopg.connect(comm.dsn) as connection:
        adopt_client_storage(connection)
    request = send(comm, activation="message_only")["data"]
    return SimpleNamespace(f=comm, request=request, view=conversation(comm))


class InputOnly(ClientStateService):
    _validate = staticmethod(ClientContracts().validate)

    def _transaction(self, *_args):
        raise AssertionError("malformed target DTO must fail before state access")


@pytest.mark.parametrize("method,body", [
    ("update_read_state", {"through_message_handle": "message:p:m", "actor_ref": "other"}),
    ("update_read_state", {"through_message_handle": "message:p:m", "unread_override": "false"}),
    ("update_preferences", {"revision": 0, "muted": True}),
    ("update_preferences", {}),
    ("update_draft", {"content": "x", "attachment_refs": [], "sender": "other"}),
    ("update_draft", {"content": "x", "attachment_refs": ["x"] * 9}),
])
def test_request_shapes_do_not_accept_caller_identity_or_write_metadata(method, body):
    with pytest.raises(ClientContractViolation):
        getattr(InputOnly(), method)("p", "conversation", body, expected_revision=0, client_request_id="key")


def test_actual_actor_defaults_and_independent_cas(personal):
    f, view = personal.f, personal.view
    own = service(f, "b")
    assert own.read_state(PROJECT, view) == {"conversation_id": view, "through_message_handle": None,
                                            "unread_override": False, "revision": 0}
    assert own.preferences(PROJECT, view) == {"archived": False, "muted": False, "revision": 0}
    assert own.draft(PROJECT, view) == {"content": "", "attachment_refs": [], "revision": 0, "updated_at": None}
    read = own.update_read_state(PROJECT, view, {"through_message_handle": personal.request["message_handle"]},
                                 expected_revision=0, client_request_id="read")
    prefs = own.update_preferences(PROJECT, view, {"muted": True}, expected_revision=0, client_request_id="prefs")
    draft = own.update_draft(PROJECT, view, {"content": "Unsent private context", "attachment_refs": []},
                             expected_revision=0, client_request_id="draft")
    assert read["revision"] == prefs["revision"] == draft["revision"] == 1
    assert service(f, "a").preferences(PROJECT, view)["revision"] == 0
    assert service(f, "a").draft(PROJECT, view)["revision"] == 0
    with psycopg.connect(f.dsn) as connection:
        draft_owners = connection.execute("SELECT DISTINCT actor_ref FROM communication_client_drafts").fetchall()
        read_owners = connection.execute("SELECT DISTINCT actor_ref FROM communication_client_read_state").fetchall()
        assert len(draft_owners) == 1 and draft_owners == read_owners
        assert draft_owners[0][0].startswith("viewer-") and draft_owners[0][0] != "agent:b"


def test_known_private_conversation_requires_actual_pair_even_for_manager(personal):
    f, view = personal.f, personal.view
    foreign = service(f, "c")
    for method in (foreign.read_state, foreign.preferences, foreign.draft):
        with pytest.raises(NotFound):
            method(PROJECT, view)
    for action in (
        lambda: foreign.update_preferences(PROJECT, view, {"muted": True}, expected_revision=0, client_request_id="foreign"),
        lambda: foreign.update_draft(PROJECT, view, {"content": "foreign", "attachment_refs": []}, expected_revision=0, client_request_id="foreign"),
        lambda: foreign.delete_draft(PROJECT, view, expected_revision=0, client_request_id="foreign"),
    ):
        with pytest.raises(NotFound):
            action()
    send(f, "b", "c", "Private b-c conversation", activation="message_only")
    b_c = conversation(f, "b", "c")
    manager = service(f, "a")
    assert manager.project_service.profile == "root_manager"
    for method in (manager.read_state, manager.preferences, manager.draft):
        with pytest.raises(NotFound):
            method(PROJECT, b_c)
    with psycopg.connect(f.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM communication_client_write_keys").fetchone()[0] == 0


def test_read_frontier_accepts_visible_pair_messages_without_covering_later_incoming(personal):
    f, view, request = personal.f, personal.view, personal.request
    own = service(f, "b")
    outgoing = send(f, "b", "a", "The last visible message can be my own send", activation="message_only")["data"]
    other = send(f, "c", "b", "Different own conversation", activation="message_only")["data"]
    private = send(f, "a", "c", "Foreign message", activation="message_only")["data"]
    for reference in (other["message_handle"], private["message_handle"]):
        with pytest.raises(NotFound):
            own.update_read_state(PROJECT, view, {"through_message_handle": reference},
                                  expected_revision=0, client_request_id="invalid-frontier")
    read = own.update_read_state(PROJECT, view, {"through_message_handle": outgoing["message_handle"]},
                                 expected_revision=0, client_request_id="valid-frontier")
    assert read["revision"] == 1 and read["through_message_handle"] == outgoing["message_handle"]
    previous = own.update_read_state(PROJECT, view, {"through_message_handle": request["message_handle"]},
                                     expected_revision=1, client_request_id="earlier-visible")
    assert previous["through_message_handle"] == outgoing["message_handle"]
    send(f, "a", "b", "Arrived after the selected frontier", activation="message_only")
    assert own.conversation(PROJECT, view)["unread_count"] == 1


def test_local_frontier_excludes_foreign_pairs_and_never_moves_backward(personal):
    f, view = personal.f, personal.view
    send(f, "a", "c", "Global sequence gap", activation="message_only")
    send(f, "b", "a", "Own outgoing counts in local order", activation="message_only")
    send(f, "c", "a", "Another global sequence gap", activation="message_only")
    newest = send(f, "a", "b", "Own next incoming", activation="message_only")["data"]
    own = service(f, "b")
    latest = own.update_read_state(PROJECT, view, {"through_message_handle": newest["message_handle"]},
                                   expected_revision=0, client_request_id="latest")
    assert own.read_message(PROJECT, newest["message_handle"])["message"]["conversation_sequence"] == "3"
    with psycopg.connect(f.dsn) as connection:
        assert connection.execute("SELECT through_sequence FROM communication_client_read_state").fetchone() == (3,)
        assert connection.execute("SELECT sequence FROM communication_messages WHERE message_id=%s", (newest["message_id"],)).fetchone()[0] > 3
    unread = own.update_read_state(PROJECT, view, {"through_message_handle": personal.request["message_handle"], "unread_override": True},
                                   expected_revision=1, client_request_id="unread")
    assert unread["through_message_handle"] == latest["through_message_handle"] and unread["unread_override"]
    still_unread = own.update_read_state(PROJECT, view, {"through_message_handle": newest["message_handle"]},
                                         expected_revision=2, client_request_id="preserve")
    assert still_unread["unread_override"] and still_unread["revision"] == 3


def test_replay_returns_original_result_before_stale_if_match_but_never_bypasses_revocation(personal):
    f, view = personal.f, personal.view
    own = service(f, "b")
    first = own.update_preferences(PROJECT, view, {"muted": True}, expected_revision=0, client_request_id="first")
    own.update_preferences(PROJECT, view, {"archived": True}, expected_revision=1, client_request_id="later")
    assert own.update_preferences(PROJECT, view, {"muted": True}, expected_revision=0, client_request_id="first") == first
    with pytest.raises(IdempotencyConflict):
        own.update_preferences(PROJECT, view, {"muted": False}, expected_revision=0, client_request_id="first")
    with pytest.raises(RevisionConflict):
        own.update_preferences(PROJECT, view, {"muted": False}, expected_revision=0, client_request_id="new")
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (own.project_service.context.grant_ref,))
    for action in (lambda: own.preferences(PROJECT, view),
                   lambda: own.update_preferences(PROJECT, view, {"muted": True}, expected_revision=0, client_request_id="first")):
        with pytest.raises(AuthorizationDenied):
            action()


def test_project_scope_and_binding_are_rechecked_before_personal_state(personal):
    f, view = personal.f, personal.view
    own = service(f, "b")
    with pytest.raises((AuthorizationDenied, NotFound)):
        own.draft("project-foreign", view)
    with psycopg.connect(f.dsn) as connection:
        connection.execute("DELETE FROM collaboration_memberships WHERE tenant_id=%s AND project_id=%s AND principal_ref=%s",
                           (f.authority.tenant_id, PROJECT, own.project_service.context.principal_ref))
    with pytest.raises(AuthorizationDenied):
        own.update_draft(PROJECT, view, {"content": "revoked membership", "attachment_refs": []},
                         expected_revision=0, client_request_id="revoked")


def test_draft_save_delete_replay_and_limits(personal):
    f, view = personal.f, personal.view
    own = service(f, "b")
    body = {"content": "A private unsent draft", "attachment_refs": []}
    saved = own.update_draft(PROJECT, view, body, expected_revision=0, client_request_id="saved")
    deleted = own.delete_draft(PROJECT, view, expected_revision=1, client_request_id="deleted")
    assert own.draft(PROJECT, view) == deleted
    assert deleted["revision"] == 2 and deleted["content"] == "" and deleted["updated_at"] is not None
    assert own.update_draft(PROJECT, view, body, expected_revision=0, client_request_id="saved") == saved
    assert own.delete_draft(PROJECT, view, expected_revision=1, client_request_id="deleted") == deleted
    with pytest.raises(CommunicationHttpError) as overflow:
        own.update_draft(PROJECT, view, {"content": "字" * (MAX_DRAFT_BYTES // 3 + 1), "attachment_refs": []},
                         expected_revision=2, client_request_id="oversized")
    assert overflow.value.status_code == 413
    with pytest.raises(CommunicationHttpError) as attachment:
        own.update_draft(PROJECT, view, {"content": "", "attachment_refs": ["unverified-attachment"]},
                         expected_revision=2, client_request_id="attachment")
    assert attachment.value.code == "capability_unsupported" and attachment.value.status_code == 409
    assert own.draft(PROJECT, view) == deleted


def test_authorized_empty_view_supports_draft_and_unknown_views_do_not_create_state(personal):
    f = personal.f
    no_history = conversation(f, "a", "c")
    own = service(f, "a")
    assert own.draft(PROJECT, no_history)["revision"] == 0
    saved = own.update_draft(PROJECT, no_history, {"content": "Before the first message", "attachment_refs": []},
                             expected_revision=0, client_request_id="empty")
    assert saved["revision"] == 1 and own.draft(PROJECT, no_history) == saved
    for unknown in ("conversation-" + "0" * 64, "arbitrary-view"):
        with pytest.raises(NotFound):
            own.update_draft(PROJECT, unknown, {"content": "Cannot guess membership", "attachment_refs": []},
                             expected_revision=0, client_request_id="empty")
    with psycopg.connect(f.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM communication_client_drafts").fetchone()[0] == 1


def test_read_and_private_write_never_dispatch_consume_reply_or_mutate_original(personal):
    f, view = personal.f, personal.view
    tables = ("communication_messages", "communication_replies", "delivery_receipts", "delivery_attempts", "domain_events", "outbox")
    with psycopg.connect(f.dsn) as connection:
        counts = {name: connection.execute("SELECT count(*) FROM " + name).fetchone()[0] for name in tables}
        packet = connection.execute("SELECT packet_json FROM delivery_messages WHERE message_id=%s", (personal.request["message_id"],)).fetchone()[0]
        inbox = connection.execute("SELECT to_jsonb(i) FROM inbox_messages i ORDER BY to_jsonb(i)::text").fetchall()
    own = service(f, "b")
    own.read_state(PROJECT, view)
    own.preferences(PROJECT, view)
    own.draft(PROJECT, view)
    own.update_read_state(PROJECT, view, {"through_message_handle": personal.request["message_handle"]},
                          expected_revision=0, client_request_id="read")
    own.update_preferences(PROJECT, view, {"archived": True}, expected_revision=0, client_request_id="archive")
    own.update_draft(PROJECT, view, {"content": "Unsent", "attachment_refs": []}, expected_revision=0, client_request_id="draft")
    with psycopg.connect(f.dsn) as connection:
        assert {name: connection.execute("SELECT count(*) FROM " + name).fetchone()[0] for name in tables} == counts
        assert connection.execute("SELECT packet_json FROM delivery_messages WHERE message_id=%s", (personal.request["message_id"],)).fetchone()[0] == packet
        assert connection.execute("SELECT to_jsonb(i) FROM inbox_messages i ORDER BY to_jsonb(i)::text").fetchall() == inbox
    assert all(not driver.calls for driver in f.drivers.values())


def test_post_write_authentication_failure_rolls_back_state_and_retry_receipt(personal, monkeypatch):
    f, view = personal.f, personal.view
    own = service(f, "b")
    original = own.project_service.service.authenticate
    calls = 0

    def expire_before_commit(credential):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise AuthorizationDenied("agent:b", "grant:b")
        return original(credential)

    monkeypatch.setattr(own.project_service.service, "authenticate", expire_before_commit)
    with pytest.raises(AuthorizationDenied):
        own.update_preferences(PROJECT, view, {"muted": True}, expected_revision=0, client_request_id="must-rollback")
    assert calls == 2
    with psycopg.connect(f.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM communication_client_preferences").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM communication_client_write_keys").fetchone()[0] == 0
