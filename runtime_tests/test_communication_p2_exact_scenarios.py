"""P2 acceptance through current service and real loopback OAuth/HTTP boundaries.

Each device uses its own connection. PostgreSQL, CAS and authorization are real;
the local issuer and Native callbacks are fixtures, with no model invocation.
"""
from __future__ import annotations

import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import httpx

from runtime.auth import LocalCredentialAuthenticator
from runtime.communication_client_queries import conversation_view_id
from runtime.communication_client_service import CommunicationClientService
from runtime.domain import DomainAuthority
from runtime.errors import RevisionConflict
from runtime.project_service import ProjectService
from runtime.surfaces import SharedService
from runtime_tests.test_communication import CATALOG, send
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_client_attachments import attached as attached_fixture
from runtime_tests.test_communication_client_state import personal as personal_fixture
from runtime_tests.test_communication_headless_live import TOKEN, resource_listener

comm = comm_fixture
attached = attached_fixture
personal = personal_fixture
PROJECT = "project-alpha"
BASE = "/api/communication/v1/projects/" + PROJECT
ADDRESS_A = "collaborator:" + PROJECT + ":local-slot"
ADDRESS_B = "collaborator:" + PROJECT + ":slot-b"
P2_OPERATIONS = {
    "getReadState", "markConversationRead", "getPreferences", "setConversationPreferences",
    "getDraft", "saveDraft", "markNoticeSeen", "searchMessages", "reserveAttachment",
    "getAttachment", "uploadAttachment", "downloadAttachment", "finalizeAttachment",
}


def second_device(f, actor):
    source = f.clients[actor]
    token = "synthetic-device-" + uuid.uuid4().hex
    context = replace(source.service.context, credential_hash=hashlib.sha256(token.encode()).hexdigest())
    authority = DomainAuthority(f.dsn, context=context)
    projects = ProjectService(SharedService(authority, LocalCredentialAuthenticator(context)),
                              CATALOG, profile=source.service.profile)
    return CommunicationClientService(projects, token)


def communication_facts(f):
    with f.authority._connect() as connection:
        return {table: connection.execute("SELECT to_jsonb(t) FROM " + table +
            " t ORDER BY to_jsonb(t)::text").fetchall() for table in (
                "delivery_messages", "communication_messages", "communication_replies", "delivery_receipts")}


def test_t043_two_device_service_cas_never_regresses_frontier_or_consumes_messages(personal):
    f, view = personal.f, personal.view
    newest = send(f, "a", "b", "Newest observed by both devices", activation="message_only")["data"]
    devices = [second_device(f, "b"), second_device(f, "b")]
    assert devices[0].credential != devices[1].credential
    assert devices[0].read_state(PROJECT, view) == devices[1].read_state(PROJECT, view)
    before = communication_facts(f)
    ready = Barrier(2)
    references = [personal.request["message_handle"], newest["message_handle"]]

    def contender(number):
        ready.wait(timeout=10)
        try:
            return devices[number].update_read_state(PROJECT, view,
                {"through_message_handle": references[number]}, expected_revision=0,
                client_request_id="t043-device-" + str(number))
        except RevisionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(contender, (0, 1)))
    assert results.count("conflict") == 1
    assert sum(isinstance(value, dict) and value["revision"] == 1 for value in results) == 1
    current = devices[0].read_state(PROJECT, view)
    advanced = devices[1].update_read_state(PROJECT, view,
        {"through_message_handle": newest["message_handle"]}, expected_revision=current["revision"],
        client_request_id="t043-advance")
    retained = devices[0].update_read_state(PROJECT, view,
        {"through_message_handle": personal.request["message_handle"]}, expected_revision=advanced["revision"],
        client_request_id="t043-older-device")
    assert retained["through_message_handle"] == newest["message_handle"]
    assert devices[1].read_state(PROJECT, view) == retained
    assert communication_facts(f) == before
    send(f, "a", "b", "Late arrival stays unread", activation="message_only")
    assert devices[0].conversation(PROJECT, view)["unread_count"] == 1
    assert not any(driver.calls for driver in f.drivers.values())


def test_all_thirteen_p2_apis_and_t084_draft_conflict_across_real_http_connections(attached, monkeypatch, record_property):
    f = attached
    operations = set()
    view = conversation_view_id(f.authority.tenant_id, PROJECT, ADDRESS_A, ADDRESS_B)
    personal_path = BASE + "/conversations/" + view
    headers = {"Authorization": "Bearer " + TOKEN}

    with resource_listener(f, monkeypatch) as listener, httpx.Client(
            base_url=listener.url, headers=headers, trust_env=False, timeout=20) as http:
        def request(operation, method, path, *, expected=200, **kwargs):
            response = http.request(method, path, **kwargs)
            assert response.status_code == expected, response.text
            operations.add(operation)
            return response

        # A real interrupted upload/retry has separate ASGI fault tests. This
        # episode proves the complete external service with a nontrivial binary.
        content = bytes(range(256)) * 512 + "汉字🧭".encode()
        declaration = {"name": "p2-complete.bin", "media_type": "application/octet-stream",
                       "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        reserved = request("reserveAttachment", "POST", BASE + "/attachments", expected=201,
            headers={"Idempotency-Key": "p2-reserve"}, json=declaration).json()
        attachment_path = BASE + "/attachments/" + reserved["attachment_id"]
        assert request("getAttachment", "GET", attachment_path).json() == reserved
        request("uploadAttachment", "PUT", attachment_path + "/content",
            headers={"Idempotency-Key": "p2-upload", "Content-Type": "application/octet-stream"}, content=content)
        ready = request("finalizeAttachment", "POST", attachment_path + "/finalize",
            headers={"Idempotency-Key": "p2-finalize"},
            json={"bytes": declaration["bytes"], "sha256": declaration["sha256"]}).json()
        assert ready["state"] == "ready"
        downloaded = request("downloadAttachment", "GET", attachment_path + "/content")
        assert downloaded.content == content
        assert hashlib.sha256(downloaded.content).hexdigest() == declaration["sha256"]

        sent = http.post(BASE + "/messages", headers={"Idempotency-Key": "p2-message"},
            json={"to": ADDRESS_B, "content": "P2_FULL_BODY_SEARCH_汉字🧭", "activation": "message_only",
                  "attachment_refs": [reserved["attachment_id"]]})
        assert sent.status_code == 201, sent.text
        handle = sent.json()["message"]["message_handle"]
        delivery_path = BASE + "/messages/" + handle + "/delivery"
        before = http.get(delivery_path).json()
        original = request("getReadState", "GET", personal_path + "/read-state").json()
        request("markConversationRead", "PUT", personal_path + "/read-state",
            headers={"Idempotency-Key": "p2-read", "If-Match": '"' + str(original["revision"]) + '"'},
            json={"through_message_handle": handle})
        assert http.get(delivery_path).json() == before

        preferences = request("getPreferences", "GET", personal_path + "/preferences").json()
        changed = request("setConversationPreferences", "PUT", personal_path + "/preferences",
            headers={"Idempotency-Key": "p2-prefs", "If-Match": '"' + str(preferences["revision"]) + '"'},
            json={"muted": True, "archived": True}).json()
        assert changed["muted"] and changed["archived"]
        peer = second_device(f, "b")
        assert peer.preferences(PROJECT, view) == {"muted": False, "archived": False, "revision": 0}
        assert http.get(BASE + "/messages/" + handle).status_code == 200
        assert http.get(delivery_path).json() == before
        assert request("getDraft", "GET", personal_path + "/draft").json()["revision"] == 0

        barrier = Barrier(2)
        texts = ["Left private draft 汉字", "Right private draft 🧭"]

        def edit(number):
            with httpx.Client(base_url=listener.url, headers=headers, trust_env=False, timeout=20) as device:
                barrier.wait(timeout=10)
                return number, device.put(personal_path + "/draft",
                    headers={"Idempotency-Key": "p2-draft-" + str(number), "If-Match": '"0"'},
                    json={"content": texts[number], "attachment_refs": [reserved["attachment_id"]]})

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(edit, (0, 1)))
        assert sorted(response.status_code for _, response in outcomes) == [200, 409]
        winner, accepted = next(value for value in outcomes if value[1].status_code == 200)
        refused = next(response for _, response in outcomes if response.status_code == 409)
        assert refused.json()["error"]["code"] == "revision_conflict"
        assert refused.json()["error"]["effect_state"] == "none"
        current = request("getDraft", "GET", personal_path + "/draft").json()
        assert current == accepted.json() and current["content"] == texts[winner] and current["revision"] == 1
        assert request("saveDraft", "PUT", personal_path + "/draft",
            headers={"Idempotency-Key": "p2-draft-" + str(winner), "If-Match": '"0"'},
            json={"content": texts[winner], "attachment_refs": [reserved["attachment_id"]]}).json() == current

        hits = request("searchMessages", "GET", BASE + "/search", params={"q": "FULL_BODY_SEARCH_汉字🧭"}).json()
        assert [hit["message_handle"] for hit in hits["items"]] == [handle]
        notice_page = http.get(BASE + "/notices")
        assert notice_page.status_code == 200 and notice_page.json()["items"]
        notice = notice_page.json()["items"][0]
        seen_path = BASE + "/notices/" + notice["notice_handle"] + "/seen"
        seen_headers = {"Idempotency-Key": "p2-seen", "If-Match": '"' + str(notice["revision"]) + '"'}
        seen = request("markNoticeSeen", "PUT", seen_path, headers=seen_headers, json={"seen": True}).json()
        with httpx.Client(base_url=listener.url, headers=headers, trust_env=False, timeout=20) as reconnected:
            replayed = reconnected.put(seen_path, headers=seen_headers, json={"seen": True})
            assert replayed.status_code == 200 and replayed.json() == seen
            assert reconnected.get(personal_path + "/draft").json() == current
            assert reconnected.get(personal_path + "/preferences").json() == changed
        assert seen["seen"] and seen["revision"] > notice["revision"]
        assert http.get(delivery_path).json() == before
        assert operations == P2_OPERATIONS
        assert not any(driver.calls for driver in f.drivers.values())
        record_property("p2_operation_ids", ",".join(sorted(operations)))
        record_property("evidence_class", "E2_real_OAuth_TCP_PostgreSQL_CAS_controlled_issuer_no_Native")
