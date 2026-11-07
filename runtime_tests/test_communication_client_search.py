"""Literal search/ACL/continuation tests on actual disposable PostgreSQL.

All messages are committed through the real authenticated ProjectService.
Driver callbacks are controlled fixtures; this suite invokes no Native input.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from runtime.auth import LocalCredentialAuthenticator
from runtime.client_contracts import ClientContracts
from runtime.communication_client_queries import conversation_view_id
from runtime.communication_client_search import SNIPPET_BYTES
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_client_storage import adopt_client_storage
from runtime.communication_http import CommunicationHttpError
from runtime.domain import DomainAuthority
from runtime.errors import AuthorizationDenied, InvalidToolArgument, NotFound
from runtime.project_service import ProjectService
from runtime.surfaces import SharedService
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send

comm = comm_fixture
PROJECT = "project-alpha"
ADDRESS_A = "collaborator:project-alpha:local-slot"
ADDRESS_B = "collaborator:project-alpha:slot-b"
ADDRESS_C = "collaborator:project-alpha:slot-c"


def client(f, actor="a"):
    current = f.clients[actor]
    return CommunicationClientService(current.service, current.credential_provider())


@pytest.fixture
def searchable(comm):
    with comm.authority._connect() as connection:
        adopt_client_storage(connection)
    return comm


def test_search_only_returns_actual_participant_text_without_private_content_or_counts(searchable):
    f, own = searchable, client(searchable)
    visible = send(f, "a", "b", "needle visible to this pair", activation="message_only")["data"]
    send(f, "b", "c", "needle foreign-private-only", activation="message_only")
    page = own.search(PROJECT, q="needle")
    ClientContracts().validate("SearchHitPage", page)
    assert [item["message_handle"] for item in page["items"]] == [visible["message_handle"]]
    assert set(page) == {"items", "page"} and "foreign-private-only" not in json.dumps(page)
    assert own.search(PROJECT, q="foreign-private-only")["items"] == []
    assert client(f, "c").search(PROJECT, q="visible to this pair")["items"] == []
    assert own.search(PROJECT, q="collaborator:project-alpha")["items"] == []
    foreign = conversation_view_id(f.authority.tenant_id, PROJECT, ADDRESS_B, ADDRESS_C)
    with pytest.raises(NotFound):
        own.search(PROJECT, q="needle", conversation_id=foreign)
    assert not any(driver.calls for driver in f.drivers.values())


def test_search_wildcards_backslashes_and_sql_punctuation_are_literal_terms(searchable):
    f, own = searchable, client(searchable)
    symbols = send(f, content="Literal %_\\ marker", activation="message_only")["data"]
    send(f, content="Ordinary plain alpha beta", activation="message_only")
    quoted = send(f, content="Quoted ' OR TRUE-- token", activation="message_only")["data"]
    for term in ("%", "_", "\\", "%_\\"):
        result = own.search(PROJECT, q=term)
        assert [item["message_handle"] for item in result["items"]] == [symbols["message_handle"]]
    assert [item["message_handle"] for item in own.search(PROJECT, q="' OR TRUE--")["items"]] == [quoted["message_handle"]]
    assert own.search(PROJECT, q="MARKER")["items"] == []


def test_search_unicode_snippet_is_exact_utf8_reader_slice_with_original_digest_and_continuation(searchable, monkeypatch):
    f, own = searchable, client(searchable)
    needle = "检索🧭e\u0301"
    content = "前🙂" * 1000 + needle + "尾🙂" * 1000
    original = send(f, content=content, activation="message_only")["data"]
    reader = own.read_message
    observations = []

    def observe_read(*args, **kwargs):
        result = reader(*args, **kwargs)
        observations.append((kwargs, result["message"]["content"]))
        return result

    monkeypatch.setattr(own, "read_message", observe_read)
    page = own.search(PROJECT, q=needle)
    assert len(page["items"]) == len(observations) == 1
    hit, (arguments, body) = page["items"][0], observations[0]
    raw = content.encode("utf-8")
    assert hit["message_handle"] == original["message_handle"] and hit["matched_fields"] == ["content"]
    assert hit["snippet"] == raw[body["offset"]:body["next_offset"]].decode("utf-8")
    assert needle in hit["snippet"] and hit["content_truncated"]
    assert body["offset"] > 0 and arguments["max_inline_bytes"] == SNIPPET_BYTES
    assert len(hit["snippet"].encode()) <= SNIPPET_BYTES
    assert body["total_bytes"] == len(raw) and body["digest"] == hashlib.sha256(raw).hexdigest()
    continued = reader(PROJECT, original["message_handle"], offset=body["next_offset"], max_inline_bytes=SNIPPET_BYTES)["message"]["content"]
    assert continued["offset"] == body["next_offset"] and continued["digest"] == body["digest"]
    assert (body["text"] + continued["text"]).encode() == raw[body["offset"]:continued["next_offset"]]


def test_search_returns_a_bounded_page_instead_of_full_matching_bodies(searchable, monkeypatch):
    f, own = searchable, client(searchable)
    for index in range(3):
        send(f, content="前" * 4000 + "needle " + str(index) + "尾" * 4000, activation="message_only")
    reader, budgets = own.read_message, []

    def observe_read(*args, **kwargs):
        budgets.append(kwargs["max_inline_bytes"])
        return reader(*args, **kwargs)

    monkeypatch.setattr(own, "read_message", observe_read)
    page = own.search(PROJECT, q="needle", limit=2)
    assert len(page["items"]) == 2 and page["page"]["next_cursor"]
    assert budgets == [SNIPPET_BYTES, SNIPPET_BYTES]
    assert all(item["content_truncated"] and len(item["snippet"].encode()) <= SNIPPET_BYTES for item in page["items"])
    assert len(json.dumps(page, ensure_ascii=False).encode()) < 4000


def test_search_snapshot_and_keyset_exclude_late_matches_and_bind_actor_query_and_filters(searchable):
    f, own = searchable, client(searchable)
    first = send(f, content="needle one", activation="message_only")["data"]
    second = send(f, "b", "a", "needle two", activation="message_only")["data"]
    page = own.search(PROJECT, q="needle", limit=1)
    assert [item["message_handle"] for item in page["items"]] == [first["message_handle"]]
    assert len(page["page"]["snapshot_id"]) <= 512 and len(page["page"]["next_cursor"]) <= 2048
    late = send(f, content="needle late", activation="message_only")["data"]
    tail = own.search(PROJECT, q="needle", limit=1, cursor=page["page"]["next_cursor"], snapshot_id=page["page"]["snapshot_id"])
    assert [item["message_handle"] for item in tail["items"]] == [second["message_handle"]]
    assert tail["page"]["next_cursor"] is None
    assert [item["message_handle"] for item in own.search(PROJECT, q="needle", snapshot_id=page["page"]["snapshot_id"])["items"]] == [first["message_handle"], second["message_handle"]]
    assert late["message_handle"] in {item["message_handle"] for item in own.search(PROJECT, q="needle")["items"]}
    for action in (
        lambda: own.search(PROJECT, q="one", cursor=page["page"]["next_cursor"]),
        lambda: own.search(PROJECT, q="needle", peer=ADDRESS_B, cursor=page["page"]["next_cursor"]),
        lambda: client(f, "b").search(PROJECT, q="needle", cursor=page["page"]["next_cursor"]),
        lambda: own.search(PROJECT, q="needle", cursor=page["page"]["next_cursor"][:-2] + "xx"),
    ):
        with pytest.raises(CommunicationHttpError) as rejected:
            action()
        assert rejected.value.status_code == 409 and rejected.value.code == "cursor_invalid"


def test_search_query_and_filter_validation_do_not_relax_scope_or_write_state(searchable):
    f, own = searchable, client(searchable)
    original = send(f, content="needle filter checks", activation="message_only")["data"]
    view = conversation_view_id(f.authority.tenant_id, PROJECT, ADDRESS_A, ADDRESS_B)
    assert own.search(PROJECT, q="needle", conversation_id=view, **{"with": ADDRESS_B})["items"][0]["message_handle"] == original["message_handle"]
    for parameters in ({"q": ""}, {"q": "x" * 1001}, {"q": None}, {"q": "bad\x00query"}, {"q": "\ud800"},
        {"q": "needle", "limit": True}, {"q": "needle", "limit": 101}, {"q": "needle", "sender": ADDRESS_A},
        {"q": "needle", "peer": ADDRESS_A}, {"q": "needle", "peer": "collaborator:foreign-project:slot-b"},
        {"q": "needle", "peer": ADDRESS_B, "with": ADDRESS_C},
        {"q": "needle", "conversation_id": view, "peer": ADDRESS_C}):
        with pytest.raises(InvalidToolArgument):
            own.search(PROJECT, **parameters)
    longest = "语" * 1000
    send(f, content=longest, activation="message_only")
    bounded = own.search(PROJECT, q=longest)
    assert len(bounded["items"]) == 1 and bounded["items"][0]["content_truncated"]
    assert len(bounded["page"]["snapshot_id"]) <= 512
    with f.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM communication_client_write_keys").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM communication_client_read_state").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone() == (0,)


def test_search_revocation_denies_old_cursor_before_any_result(searchable):
    f, own = searchable, client(searchable)
    send(f, content="needle one", activation="message_only")
    send(f, content="needle two", activation="message_only")
    page = own.search(PROJECT, q="needle", limit=1)
    with f.authority._connect() as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (own.project_service.context.grant_ref,))
    with pytest.raises(AuthorizationDenied):
        own.search(PROJECT, q="needle", cursor=page["page"]["next_cursor"])


def test_search_profile_policy_is_required_even_when_grant_still_allows_message_reads(searchable, monkeypatch):
    f = searchable
    send(f, content="needle profile", activation="message_only")
    own = client(f, "b")
    profile = own.project_service.profile
    current = own.project_service.catalog["profiles"][profile]
    monkeypatch.setitem(own.project_service.catalog["profiles"], profile, [name for name in current if name != "list_messages"])
    with pytest.raises(AuthorizationDenied):
        own.search(PROJECT, q="needle")


def test_search_cursor_cannot_move_to_new_grant_for_same_actor_address(searchable):
    f, own = searchable, client(searchable)
    send(f, content="needle one", activation="message_only")
    send(f, content="needle two", activation="message_only")
    first = own.search(PROJECT, q="needle", limit=1)
    original = own.project_service
    replacement = "grant:search-replacement"
    with f.authority._connect() as connection:
        connection.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,scope_id,permissions,expires_at) "
            "SELECT %s,tenant_id,principal_ref,authority_id,authority_incarnation,scope_id,permissions,expires_at FROM grants WHERE grant_ref=%s",
            (replacement, original.context.grant_ref))
        connection.execute("UPDATE collaboration_memberships SET grant_ref=%s WHERE tenant_id=%s AND project_id=%s AND principal_ref=%s",
                           (replacement, f.authority.tenant_id, PROJECT, original.context.principal_ref))
    context = replace(original.context, grant_ref=replacement)
    authority = DomainAuthority(f.dsn, context=context)
    authority._delivery_endpoints = f.authority._delivery_endpoints
    rebound = ProjectService(SharedService(authority, LocalCredentialAuthenticator(context)), original.catalog, profile=original.profile)
    current = CommunicationClientService(rebound, f.clients["a"].credential_provider())
    assert len(current.search(PROJECT, q="needle")["items"]) == 2
    with pytest.raises(CommunicationHttpError) as rejected:
        current.search(PROJECT, q="needle", cursor=first["page"]["next_cursor"])
    assert rejected.value.status_code == 409 and rejected.value.code == "cursor_invalid"
