"""Actual PG queue policy for an explicitly installed Host attachment port.

The endpoint declaration here is a controlled fixture, not Native/model proof.
The real Host callback and model/file evidence are collected by Porpita itself.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import psycopg

from runtime.communication_wait_ingress import adopt_wait_ingress
from runtime_tests.test_communication import call, comm as comm_fixture
from runtime_tests.test_communication_attachment_send import body, sending as sending_fixture
from runtime_tests.test_communication_client_attachments import attached as attached_fixture, client, ready

comm, attached, sending = comm_fixture, attached_fixture, sending_fixture


def install_fixture_port(fixture, own):
    with psycopg.connect(fixture.dsn) as connection:
        rows = connection.execute("SELECT endpoint_id FROM delivery_endpoints WHERE tenant_id=%s "
            "AND agent_slot_id='slot-b' AND status='active'", (fixture.authority.tenant_id,)).fetchall()
    assert len(rows) == 1
    installed = {rows[0][0]}
    for authority in [fixture.authority, own.project_service.service.authority,
            *(source.service.service.authority for source in fixture.clients.values())]:
        authority._native_attachment_delivery_endpoints = installed


def test_host_attachment_port_queues_original_manifest_without_claiming_native_ack(sending):
    f, own = sending, client(sending)
    install_fixture_port(f, own)
    artifact = ready(own, b"actual stored attachment bytes")
    result = own.send("project-alpha", body([artifact["attachment_id"]], activation="invoke"),
        client_request_id="installed-host-attachment")
    assert result["delivery"]["accepted_by_authority"]
    assert not result["delivery"]["target_inbox_committed"]
    assert result["delivery"]["native"]["state"] == "pending"
    with psycopg.connect(f.dsn) as connection:
        row = connection.execute("SELECT state,last_error,packet_json->'attachment_refs' FROM delivery_messages "
            "WHERE message_id=%s", (result["message"]["message_handle"].split(":")[-1],)).fetchone()
    assert row[0:2] == ("queued", None)
    assert row[2] == result["message"]["attachment_refs"]
    assert not any(driver.calls for driver in f.drivers.values())


def test_active_reply_wait_does_not_replace_the_host_attachment_handover(sending):
    f, own = sending, client(sending)
    install_fixture_port(f, own)
    with psycopg.connect(f.dsn) as connection:
        adopt_wait_ingress(connection)
    for source in f.clients.values():
        source.service.service.authority._wait_ingress_recovery_enabled = True
    request = call(f, "b", "send_message", to="collaborator:project-alpha:local-slot",
        content="Explicit file request", activation="message_only", client_request_id="host-file-request")["data"]
    artifact = ready(own, b"actual attachment reply bytes")
    with ThreadPoolExecutor(max_workers=1) as pool:
        waiting = pool.submit(call, f, "b", "wait_for_response", handles=[request["message_handle"]], timeout_seconds=4)
        deadline = time.monotonic() + 3
        active = None
        while time.monotonic() < deadline:
            with psycopg.connect(f.dsn) as connection:
                active = connection.execute("SELECT 1 FROM communication_waits WHERE request_id=%s "
                    "AND expires_at>clock_timestamp()", (request["message_id"],)).fetchone()
            if active:
                break
            time.sleep(.01)
        assert active
        reply = own.send("project-alpha", body([artifact["attachment_id"]], activation="invoke",
            reply_to=[request["message_handle"]]), client_request_id="host-file-reply")
        assert waiting.result(timeout=5)["state"] == "satisfied"
    assert reply["delivery"]["native"]["state"] == "pending"
    with psycopg.connect(f.dsn) as connection:
        identifier = reply["message"]["message_handle"].split(":")[-1]
        assert connection.execute("SELECT state,last_error FROM delivery_messages WHERE message_id=%s",
            (identifier,)).fetchone() == ("queued", None)
        assert connection.execute("SELECT 1 FROM communication_wait_ingress WHERE message_id=%s", (identifier,)).fetchone() is None
    assert not any(driver.calls for driver in f.drivers.values())
