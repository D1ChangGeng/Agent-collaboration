"""Real per-viewer projection invalidations from committed Authority sources.

Manager Native ACKs are explicit local driver fixtures. They do not establish a
physical Harness, model, production service or automatic Agent reply.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg
import pytest

from runtime.client_contracts import ClientContracts
from runtime.communication_client_events import encode_event_cursor
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_client_storage import ClientStateIdentity, write_preferences
from runtime.communication_conversation_storage import prepare_conversation_write
from runtime.communication_event_storage import (
    publish_event_intents,
    read_event_records,
    stream_high_water,
)
from runtime.communication_faults import queue_communication_notices
from runtime.errors import RevisionConflict
from runtime_tests.test_communication import call, send
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_faults import fail_b
from runtime_tests.test_notification_continuity import shared_principal_clients

comm = comm_fixture
PROJECT = "project-alpha"
ADDRESSES = {"a": "collaborator:project-alpha:local-slot", "b": "collaborator:project-alpha:slot-b", "c": "collaborator:project-alpha:slot-c"}
CONTRACTS = ClientContracts()


def flags(f):
    for source in f.clients.values():
        source.service.service.authority._communication_events_enabled = True


@pytest.fixture
def projected(comm):
    flags(comm)
    comm.clients["a"].service.initialize()
    return comm


def client(f, name="a"):
    source = f.clients[name]
    return CommunicationClientService(source.service, source.credential_provider())


def publish(f):
    total = 0
    with psycopg.connect(f.dsn) as connection:
        while count := publish_event_intents(connection, f.authority.tenant_id, PROJECT, limit=1000):
            total += count
    return total


def anchor(service):
    return service._event_transaction(PROJECT, lambda bound, cursor, _root, _command, revision:
        encode_event_cursor(cursor, bound.tenant_id, PROJECT, revision,
                            stream_high_water(cursor, bound.tenant_id, PROJECT), anchor=True))


def replay(service, start, kind):
    page = service.event_batch(PROJECT, after_cursor=start, kinds=[kind], limit=256)
    for event in page.events:
        CONTRACTS.validate("Event", event)
        assert not {"content", "text", "draft", "transcript"}.intersection(event["payload"])
    return list(page.events)


def raw_events(f):
    with psycopg.connect(f.dsn) as connection:
        return read_event_records(connection.cursor(), f.authority.tenant_id, PROJECT, after=0, limit=1000)


def test_core_message_and_private_changes_emit_matching_viewer_dto_revisions(projected):
    f, a, b, c = projected, client(projected), client(projected, "b"), client(projected, "c")
    starts = {name: anchor(service) for name, service in (("a", a), ("b", b), ("c", c))}
    request = send(f, "b", "a", "PROJECTION_PRIVATE_MESSAGE_BODY", activation="message_only")["data"]
    view = a.resolve_conversation(PROJECT, peer=ADDRESSES["b"])["conversation_id"]
    first_a, first_b = a.conversation(PROJECT, view), b.conversation(PROJECT, view)
    publish(f)
    for name, service, dto in (("a", a, first_a), ("b", b, first_b)):
        events = replay(service, starts[name], "conversation.updated")
        assert max(event["resource_revision"] for event in events if event["resource_ref"] == view) == dto["revision"]
    assert replay(c, starts["c"], "conversation.updated") == []
    own_start, peer_start = anchor(a), anchor(b)
    a.update_preferences(PROJECT, view, {"muted": True}, expected_revision=0, client_request_id="projection-prefs")
    after_pref = a.conversation(PROJECT, view)
    publish(f)
    own = replay(a, own_start, "conversation.updated")
    assert len(own) == 1 and own[0]["resource_revision"] == after_pref["revision"] > first_a["revision"]
    assert replay(b, peer_start, "conversation.updated") == []
    assert b.conversation(PROJECT, view)["revision"] == first_b["revision"]
    before_read = anchor(a)
    a.update_read_state(PROJECT, view, {"through_message_handle": request["message_handle"]},
                         expected_revision=0, client_request_id="projection-read")
    after_read = a.conversation(PROJECT, view)
    publish(f)
    read_events = replay(a, before_read, "conversation.updated")
    assert len(read_events) == 1 and read_events[0]["resource_revision"] == after_read["revision"] > after_pref["revision"]
    assert "PROJECTION_PRIVATE_MESSAGE_BODY" not in str(raw_events(f))
    assert all(not driver.calls for driver in f.drivers.values())


def test_same_principal_opposite_slots_do_not_observe_each_others_private_projection_events(projected):
    f = projected
    shared_principal_clients(f)
    flags(f)
    first, second = client(f, "shared-1"), client(f, "shared-2")
    addresses = {number: f"collaborator:{PROJECT}:shared-slot-{number}" for number in (1, 2)}
    call(f, "shared-1", "send_message", to=addresses[2], content="Shared principal direct pair",
         activation="message_only", client_request_id="shared-principal-projection-message")
    view = first.resolve_conversation(PROJECT, peer=addresses[2])["conversation_id"]
    first.conversation(PROJECT, view)
    baseline_second = second.conversation(PROJECT, view)
    publish(f)
    first_start, second_start = anchor(first), anchor(second)
    first.update_preferences(PROJECT, view, {"archived": True}, expected_revision=0, client_request_id="same-raw-projection-key")
    current = first.conversation(PROJECT, view)
    publish(f)
    own = replay(first, first_start, "conversation.updated")
    assert len(own) == 1 and own[0]["resource_revision"] == current["revision"]
    assert replay(second, second_start, "conversation.updated") == []
    assert second.conversation(PROJECT, view)["revision"] == baseline_second["revision"]
    matched = [record for record in raw_events(f) if record["kind"] == "conversation.updated" and record["resource_revision"] == current["revision"]]
    assert len(matched) == 1 and matched[0]["recipient"] == addresses[1]
    assert matched[0]["actor_ref"] == first._viewer_actor_ref(PROJECT, addresses[1])


def test_concurrent_private_read_preferences_and_peer_message_never_reuse_version_for_different_dtos(projected):
    f, a, b = projected, client(projected), client(projected, "b")
    incoming = send(f, "b", "a", "Concurrent projection baseline", activation="message_only")["data"]
    view = a.resolve_conversation(PROJECT, peer=ADDRESSES["b"])["conversation_id"]
    baseline_a, baseline_b = a.conversation(PROJECT, view), b.conversation(PROJECT, view)
    publish(f)
    start_a, start_b = anchor(a), anchor(b)
    ready = Barrier(3)

    def operation(kind):
        ready.wait(timeout=5)
        if kind == "prefs":
            a.update_preferences(PROJECT, view, {"muted": True}, expected_revision=0, client_request_id="concurrent-pref")
        elif kind == "read":
            a.update_read_state(PROJECT, view, {"through_message_handle": incoming["message_handle"]},
                                expected_revision=0, client_request_id="concurrent-read")
        else:
            send(f, "b", "a", "PRIVATE_CONCURRENT_PROJECTION_MESSAGE", activation="message_only")
        return a.conversation(PROJECT, view)

    with ThreadPoolExecutor(max_workers=3) as pool:
        observed = list(pool.map(operation, ("prefs", "read", "message")))
    final_a, final_b = a.conversation(PROJECT, view), b.conversation(PROJECT, view)
    by_revision = {}
    for dto in [baseline_a, *observed, final_a]:
        assert by_revision.setdefault(dto["revision"], dto) == dto
    assert final_a["muted"] and final_a["unread_count"] == 1
    assert final_a["revision"] >= baseline_a["revision"] + 3
    assert final_b["revision"] == baseline_b["revision"] + 1
    publish(f)
    a_events = replay(a, start_a, "conversation.updated")
    b_events = replay(b, start_b, "conversation.updated")
    assert len(a_events) == 3 and len({event["resource_revision"] for event in a_events}) == 3
    assert max(event["resource_revision"] for event in a_events) == final_a["revision"]
    assert len(b_events) == 1 and b_events[0]["resource_revision"] == final_b["revision"]
    assert "PRIVATE_CONCURRENT_PROJECTION_MESSAGE" not in str(raw_events(f))


def test_exact_private_retry_noop_and_rolled_back_sources_do_not_duplicate_events(projected):
    f, own = projected, client(projected)
    send(f, "b", "a", "Rollback source baseline", activation="message_only")
    view = own.resolve_conversation(PROJECT, peer=ADDRESSES["b"])["conversation_id"]
    first = own.update_preferences(PROJECT, view, {"muted": True}, expected_revision=0, client_request_id="projection-retry")
    publish(f)
    before, start = raw_events(f), anchor(own)
    assert own.update_preferences(PROJECT, view, {"muted": True}, expected_revision=0, client_request_id="projection-retry") == first
    identity = ClientStateIdentity(f.authority.tenant_id, PROJECT, own._viewer_actor_ref(PROJECT, ADDRESSES["a"]), view)
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE communication_client_preferences SET muted=muted WHERE tenant_id=%s AND project_id=%s AND actor_ref=%s AND conversation_id=%s", identity.values())
    with psycopg.connect(f.dsn) as connection, connection.cursor() as cursor:
        prepare_conversation_write(cursor, identity, ADDRESSES["a"], ADDRESSES["b"])
        write_preferences(cursor, identity, {"archived": True}, expected_revision=1, client_request_id="projection-rollback")
        connection.rollback()
    assert publish(f) == 0 and raw_events(f) == before
    assert replay(own, start, "conversation.updated") == []
    assert own.preferences(PROJECT, view) == {"muted": True, "archived": False, "revision": 1}


def configured_notice(f):
    call(f, "a", "configure_team", prepare_native=False, members=[{"agent_slot_id": "slot-b", "principal_ref": "agent:b"}])
    failed = fail_b(f)
    queue_communication_notices(f.authority)
    own = client(f)
    dto = own.notices(PROJECT)["items"][0]
    with psycopg.connect(f.dsn) as connection:
        row = connection.execute("SELECT r.delivery_message_id,m.operation_id FROM communication_notice_routes r "
            "JOIN delivery_messages m ON m.tenant_id=r.tenant_id AND m.message_id=r.delivery_message_id "
            "WHERE r.tenant_id=%s AND r.project_id=%s AND r.message_id=%s AND r.recipient=%s",
            (f.authority.tenant_id, PROJECT, failed["message_id"], ADDRESSES["a"])).fetchone()
    assert row is not None
    return failed, dto, row


def test_genuine_notice_created_updates_seen_and_own_ack_emit_only_recipient_projection(projected):
    f, own, outsider = projected, client(projected), client(projected, "c")
    call(f, "a", "configure_team", prepare_native=False, members=[{"agent_slot_id": "slot-b", "principal_ref": "agent:b"}])
    start, outside_start = anchor(own), anchor(outsider)
    failed = fail_b(f)
    queue_communication_notices(f.authority)
    notice = own.notices(PROJECT)["items"][0]
    with psycopg.connect(f.dsn) as connection:
        delivery, operation = connection.execute("SELECT r.delivery_message_id,m.operation_id FROM communication_notice_routes r "
            "JOIN delivery_messages m ON m.tenant_id=r.tenant_id AND m.message_id=r.delivery_message_id "
            "WHERE r.tenant_id=%s AND r.project_id=%s AND r.message_id=%s AND r.recipient=%s",
            (f.authority.tenant_id, PROJECT, failed["message_id"], ADDRESSES["a"])).fetchone()
    publish(f)
    created = replay(own, start, "notice.created")
    updated = replay(own, start, "notice.updated")
    assert len(created) == 1 and created[0]["resource_ref"] == notice["notice_handle"]
    assert max(event["resource_revision"] for event in updated) == notice["revision"]
    assert replay(outsider, outside_start, "notice.created") == replay(outsider, outside_start, "notice.updated") == []
    seen_start = anchor(own)
    marked = own.mark_notice_seen(PROJECT, notice["notice_handle"], {"seen": True},
                                   expected_revision=notice["revision"], client_request_id="projection-seen")
    publish(f)
    seen_events = replay(own, seen_start, "notice.updated")
    assert len(seen_events) == 1 and seen_events[0]["resource_revision"] == marked["revision"]
    ack_start = anchor(own)
    assert f.dispatcher.dispatch({"tenant_id": f.authority.tenant_id, "message_id": delivery, "operation_id": operation})["status"] == "delivered"
    accepted = own.notice(PROJECT, notice["notice_handle"])
    assert accepted["seen"] is True and accepted["own_delivery"]["state"] == "accepted"
    assert accepted["revision"] > marked["revision"]
    publish(f)
    ack_events = replay(own, ack_start, "notice.updated")
    assert max(event["resource_revision"] for event in ack_events) == accepted["revision"]
    before = raw_events(f)
    assert own.mark_notice_seen(PROJECT, notice["notice_handle"], {"seen": True},
        expected_revision=notice["revision"], client_request_id="projection-seen") == marked
    assert publish(f) == 0 and raw_events(f) == before
    for event in [record for record in before if record["kind"] in {"notice.created", "notice.updated"}]:
        assert event["audience_kind"] == "notice" and event["recipient"] == ADDRESSES["a"]
        assert event["actor_ref"] == own.project_service.context.principal_ref
        assert event["payload_json"] == {}
    assert len(f.drivers["a"].calls) == 1
    assert "PRIVATE body must not be relayed" not in str(before)


def test_original_message_ack_cannot_become_notice_own_ack_or_revision_fact(projected):
    f, own = projected, client(projected)
    original = send(f, "a", "c", "PRIVATE_ORIGINAL_ACK_MESSAGE", activation="invoke")["data"]
    assert f.dispatcher.dispatch({"tenant_id": f.authority.tenant_id, "message_id": original["message_id"],
                                  "operation_id": original["operation_id"]})["status"] == "delivered"
    failed, notice, _delivery = configured_notice(f)
    assert notice["own_delivery"]["state"] == "pending" and notice["own_delivery"]["evidence_ref"] is None
    with psycopg.connect(f.dsn) as connection:
        assert connection.execute("SELECT 1 FROM delivery_receipts WHERE tenant_id=%s AND message_id=%s AND layer='runtime_acknowledged'", (f.authority.tenant_id, original["message_id"])).fetchone()
        connection.execute("UPDATE communication_notice_routes SET delivery_message_id=%s WHERE tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s",
                           (original["message_id"], f.authority.tenant_id, PROJECT, failed["message_id"], ADDRESSES["a"]))
    fenced = own.notice(PROJECT, notice["notice_handle"])
    assert fenced["own_delivery"]["state"] == "unknown" and fenced["own_delivery"]["evidence_ref"] is None
    assert fenced["revision"] > notice["revision"]
    publish(f)
    latest = [record for record in raw_events(f) if record["kind"] == "notice.updated" and record["resource_ref"] == notice["notice_handle"]]
    assert max(record["resource_revision"] for record in latest) == fenced["revision"]
    assert "PRIVATE_ORIGINAL_ACK_MESSAGE" not in str(latest)


def test_seen_and_own_native_ack_race_never_reuse_a_notice_revision_for_different_dtos(projected):
    f, own = projected, client(projected)
    _failed, notice, (delivery, operation) = configured_notice(f)
    publish(f)
    start = anchor(own)
    ready = Barrier(2)

    def mark():
        ready.wait(timeout=5)
        expected = notice["revision"]
        for _attempt in range(3):
            try:
                return own.mark_notice_seen(PROJECT, notice["notice_handle"], {"seen": True},
                    expected_revision=expected, client_request_id="raced-seen")
            except RevisionConflict:
                expected = own.notice(PROJECT, notice["notice_handle"])["revision"]
        pytest.fail("bounded seen retry did not reach the committed source version")

    def ack():
        ready.wait(timeout=5)
        assert f.dispatcher.dispatch({"tenant_id": f.authority.tenant_id, "message_id": delivery, "operation_id": operation})["status"] == "delivered"
        return own.notice(PROJECT, notice["notice_handle"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        seen_future, ack_future = pool.submit(mark), pool.submit(ack)
        observations = [notice, seen_future.result(), ack_future.result(), own.notice(PROJECT, notice["notice_handle"])]
    versions = {}
    for dto in observations:
        assert versions.setdefault(dto["revision"], dto) == dto
    final = observations[-1]
    assert final["seen"] and final["own_delivery"]["state"] == "accepted"
    publish(f)
    events = replay(own, start, "notice.updated")
    assert len({event["resource_revision"] for event in events}) == len(events)
    assert max(event["resource_revision"] for event in events) == final["revision"]


def test_legacy_initialization_seeds_versions_without_fabricating_notice_creation(comm):
    f = comm
    _failed, legacy, _delivery = configured_notice_before_projection(f)
    flags(f)
    f.clients["a"].service.initialize()
    own = client(f)
    materialized = own.notices(PROJECT)["items"][0]
    assert materialized["message_ref"] == legacy["message_handle"] and materialized["created_at"] is None
    assert publish(f) == 0 and raw_events(f) == []
    later = fail_b(f)
    queue_communication_notices(f.authority)
    fresh = next(item for item in own.notices(PROJECT)["items"] if item["message_ref"] == later["message_handle"])
    publish(f)
    creations = [record for record in raw_events(f) if record["kind"] == "notice.created"]
    assert len(creations) == 1 and creations[0]["resource_ref"] == fresh["notice_handle"]
    assert creations[0]["resource_ref"] != materialized["notice_handle"]


def configured_notice_before_projection(f):
    call(f, "a", "configure_team", prepare_native=False, members=[{"agent_slot_id": "slot-b", "principal_ref": "agent:b"}])
    failed = fail_b(f)
    queue_communication_notices(f.authority)
    legacy = call(f, "a", "check_inbox")["data"]["notifications"][0]
    return failed, legacy, None
