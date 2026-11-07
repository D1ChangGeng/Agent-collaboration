"""New query routes on the actual OAuth app and disposable PostgreSQL.

Issuer/Native providers are explicit fixtures. All identities come from admitted
OAuth bindings and real ProjectService grants; no synthetic DTO/context resolver
is substituted for the production HTTP authentication path.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from urllib.parse import quote

import httpx
import pytest

from runtime.client_contracts import ClientContracts
from runtime.communication_client_notice_storage import verify_notice_storage
from runtime.communication_client_service import CommunicationClientService
from runtime.project_http import ProjectHttpSettings
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send
from runtime_tests.test_communication_client_oauth import app_for, config, explicit_initialize
from runtime_tests.test_communication_faults import fail_b, identity, refuse
from runtime_tests.test_project_http import IssuerFixture, claims

comm = comm_fixture
PROJECT = "project-alpha"
PREFIX = "/api/communication/v1"
BASE = PREFIX + "/projects/" + PROJECT
CONTRACTS = ClientContracts()


@asynccontextmanager
async def authenticated_http(f, monkeypatch):
    data = config(monkeypatch, f, enabled=True).model_dump()
    data["bindings"] = list(data["bindings"])
    data["bindings"][0].update(trusted_client=False, agent_slot_id="local-slot")
    data["bindings"].append({"subject": "bob", "client_id": "web-client", "profile": "engineer",
        "principal_ref": "agent:b", "grant_ref": "grant:b", "trusted_client": False, "agent_slot_id": "slot-b"})
    cfg = ProjectHttpSettings.model_validate(data)
    issuer = IssuerFixture({"valid": claims(), "other": claims(sub="bob"),
        "wrong-scope": claims(scope="acs:connect"), "unbound": claims(sub="not-an-admitted-subject")})
    async with issuer.client() as issuer_client:
        app = app_for(f, cfg, issuer_client)
        # Construction sets the real opt-in flag; explicit operator adoption
        # must follow that step so client AND notice storage are verified.
        assert f.authority._communication_client_api_enabled is True
        explicit_initialize(f)
        with f.authority._connect() as connection:
            verify_notice_storage(connection)
        async with (app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765",
                              headers={"Authorization": "Bearer valid"}) as http):
            yield http


def domain_counts(f):
    with f.authority._connect() as connection:
        return {name: connection.execute("SELECT count(*) FROM " + name).fetchone()[0] for name in (
            "communication_messages", "communication_replies", "delivery_messages", "delivery_attempts",
            "delivery_receipts", "operations", "outbox")}


def test_meta_advertises_real_query_routes_and_unbound_or_wrong_scope_tokens_never_inherit_context(comm, monkeypatch):
    f = comm

    async def exercise():
        async with authenticated_http(f, monkeypatch) as http:
            metadata = await http.get(PREFIX + "/meta", headers={"Authorization": "Bearer unbound"})
            assert metadata.status_code == 200
            CONTRACTS.validate("Meta", metadata.json())
            assert {"search", "receivers", "notices"} <= set(metadata.json()["features"])
            before = domain_counts(f)
            for token in ("wrong-scope", "unbound"):
                for path in (BASE + "/search?q=needle", BASE + "/receivers", BASE + "/receivers/endpoint-b", BASE + "/notices"):
                    denied = await http.get(path, headers={"Authorization": "Bearer " + token})
                    assert denied.status_code in {401, 403}, denied.text
                    assert denied.json()["error"]["effect_state"] == "none"
                denied = await http.put(BASE + "/notices/notification:project-alpha:communication-1/seen",
                    headers={"Authorization": "Bearer " + token, "If-Match": '"1"', "Idempotency-Key": "not-admitted"},
                    json={"seen": True})
                assert denied.status_code in {401, 403} and denied.json()["error"]["effect_state"] == "none"
            unauthenticated = await http.get(BASE + "/receivers", headers={"Authorization": ""})
            assert unauthenticated.status_code == 401
            assert domain_counts(f) == before
            with f.authority._connect() as connection:
                assert connection.execute("SELECT count(*) FROM communication_client_notice_write_keys").fetchone() == (0,)

    asyncio.run(exercise())
    assert not any(driver.calls for driver in f.drivers.values())


def test_http_search_accepts_1000_char_query_and_literal_unicode_with_bounded_readonly_hits(comm, monkeypatch):
    f = comm
    longest = "字" * 1000
    visible = send(f, content="前🙂" * 300 + longest + " %_\\ 🧭 literal tail", activation="message_only")["data"]
    send(f, "b", "c", "Foreign %_\\ 🧭 private result", activation="message_only")

    async def exercise():
        async with authenticated_http(f, monkeypatch) as http:
            before = domain_counts(f)
            result = await http.get(BASE + "/search", params={"q": longest})
            assert result.status_code == 200, result.text
            CONTRACTS.validate("SearchHitPage", result.json())
            assert [item["message_handle"] for item in result.json()["items"]] == [visible["message_handle"]]
            assert result.json()["items"][0]["content_truncated"]
            literal = await http.get(BASE + "/search", params={"q": "%_\\ 🧭"})
            assert literal.status_code == 200, literal.text
            hits = literal.json()["items"]
            assert len(hits) == 1 and hits[0]["message_handle"] == visible["message_handle"]
            assert "%_\\ 🧭" in hits[0]["snippet"] and len(hits[0]["snippet"].encode()) <= 512
            assert "Foreign" not in literal.text and hits[0]["matched_fields"] == ["content"]
            for parameters in ({"q": "字" * 1001}, [("q", "literal"), ("q", "literal")], {},
                               {"q": "literal", "sender": "forged-caller"}):
                invalid = await http.get(BASE + "/search", params=parameters)
                assert invalid.status_code == 400 and invalid.json()["error"]["effect_state"] == "none", invalid.text
            assert domain_counts(f) == before
            with f.authority._connect() as connection:
                assert connection.execute("SELECT count(*) FROM communication_client_read_state").fetchone() == (0,)

    asyncio.run(exercise())
    assert not any(driver.calls for driver in f.drivers.values())


def test_http_receivers_with_evidence_flag_off_preserve_unknown_without_any_provider_or_lifecycle_call(comm, monkeypatch):
    f = comm
    f.authority._receiver_evidence_enabled = False
    for endpoint in f.authority._delivery_endpoints.values():
        monkeypatch.setattr(endpoint, "prepare_runtime", lambda: pytest.fail("receiver GET prepared a runtime"))
        monkeypatch.setattr(endpoint, "inspect_runtime", lambda: pytest.fail("receiver GET used legacy readiness"))
        monkeypatch.setattr(endpoint, "receiver_snapshot", lambda _binding: pytest.fail("disabled evidence called a provider"))

    async def exercise():
        async with authenticated_http(f, monkeypatch) as http:
            before = domain_counts(f)
            page = await http.get(BASE + "/receivers")
            assert page.status_code == 200, page.text
            CONTRACTS.validate("ReceiverPage", page.json())
            assert {item["receiver_id"] for item in page.json()["items"]} == {"endpoint-a", "endpoint-b", "endpoint-c"}
            detail = await http.get(BASE + "/receivers/endpoint-b")
            assert detail.status_code == 200, detail.text
            CONTRACTS.validate("Receiver", detail.json())
            value = detail.json()
            assert value["receiver_id"] == "endpoint-b" and value["native_session_ref"] is None
            assert value["allowed_actions"] == ["inspect"] and value["binding_epoch"] == 1
            assert all(item["knowledge"] == "unknown" and item["value"] is None for item in value["observations"])
            assert all(item["support"] == "unknown" for item in value["capabilities"])
            assert domain_counts(f) == before

    asyncio.run(exercise())
    assert not any(driver.calls for driver in f.drivers.values())


def test_http_receiver_detail_preserves_legal_long_opaque_source_reference_including_encoded_slash(comm, monkeypatch):
    f = comm
    reference = "opaque/" + "r" * 505
    assert len(reference) == 512
    f.authority._receiver_evidence_enabled = False
    with f.authority._connect() as connection:
        connection.execute("UPDATE delivery_endpoints SET endpoint_id=%s WHERE tenant_id=%s AND endpoint_id='endpoint-b'",
                           (reference, f.authority.tenant_id))

    async def exercise():
        async with authenticated_http(f, monkeypatch) as http:
            # The real service and strict target DTO establish source validity
            # independently of the HTTP router's path parsing.
            current = f.clients["a"]
            expected = CommunicationClientService(current.service, current.credential_provider()).receiver(PROJECT, reference)
            CONTRACTS.validate("Receiver", expected)
            listed = await http.get(BASE + "/receivers")
            assert listed.status_code == 200 and reference in {item["receiver_id"] for item in listed.json()["items"]}
            detail = await http.get(BASE + "/receivers/" + quote(reference, safe=""))
            assert detail.status_code == 200, detail.text
            assert detail.json() == expected

    asyncio.run(exercise())


def test_http_notice_mailbox_recipient_acl_seen_hash_and_original_replay_after_source_changes(comm, monkeypatch):
    f = comm

    async def exercise():
        async with authenticated_http(f, monkeypatch) as http:
            own_message = fail_b(f)
            monkeypatch.setattr(f.drivers["c"], "prepare", refuse)
            foreign_message = send(f, "b", "c", "PRIVATE B-C notice source body")["data"]
            assert f.dispatcher.dispatch(identity(f, foreign_message))["status"] == "blocked"
            before = domain_counts(f)
            path = BASE + "/notices"
            response = await http.get(path)
            assert response.status_code == 200, response.text
            CONTRACTS.validate("NoticePage", response.json())
            assert len(response.json()["items"]) == 1
            original = response.json()["items"][0]
            assert original["message_ref"] == own_message["message_handle"] and not original["seen"]
            assert original["created_at"] is not None and "PRIVATE" not in response.text
            other = await http.get(path, headers={"Authorization": "Bearer other"})
            assert other.status_code == 200 and len(other.json()["items"]) == 1, other.text
            foreign_notice = other.json()["items"][0]
            assert foreign_notice["message_ref"] == foreign_message["message_handle"]
            forbidden = await http.put(path + "/" + foreign_notice["notice_handle"] + "/seen", json={"seen": True},
                headers={"If-Match": '"' + str(foreign_notice["revision"]) + '"', "Idempotency-Key": "wrong-recipient"})
            assert forbidden.status_code == 404 and forbidden.json()["error"]["effect_state"] == "none", forbidden.text
            with f.authority._connect() as connection:
                assert connection.execute("SELECT count(*) FROM communication_client_notice_seen").fetchone() == (0,)
            target = path + "/" + original["notice_handle"] + "/seen"
            headers = {"If-Match": '"' + str(original["revision"]) + '"', "Idempotency-Key": "exact-seen-key"}
            saved = await http.put(target, headers=headers, json={"seen": True})
            assert saved.status_code == 200 and saved.json()["seen"], saved.text
            changed_version = await http.put(target, headers={**headers, "If-Match": '"' + str(saved.json()["revision"]) + '"'},
                                             json={"seen": True})
            assert changed_version.status_code == 409 and changed_version.json()["error"]["code"] == "idempotency_conflict", changed_version.text
            assert changed_version.json()["error"]["effect_state"] == "none"
            with f.authority._connect() as connection:
                connection.execute("UPDATE communication_notices SET state='uncertain',code='native_outcome_uncertain' "
                    "WHERE tenant_id=%s AND project_id=%s AND message_id=%s AND recipient='collaborator:project-alpha:local-slot'",
                    (f.authority.tenant_id, PROJECT, own_message["message_id"]))
            fresh = await http.get(path)
            assert fresh.status_code == 200 and fresh.json()["items"][0]["revision"] > saved.json()["revision"]
            assert fresh.json()["items"][0]["reason_code"] == "native_outcome_uncertain"
            replay = await http.put(target, headers=headers, json={"seen": True})
            assert replay.status_code == 200 and replay.json() == saved.json(), replay.text
            stale = await http.put(target, headers={**headers, "Idempotency-Key": "stale-new-key"}, json={"seen": False})
            assert stale.status_code == 409 and stale.json()["error"]["effect_state"] == "none", stale.text
            forged = await http.put(target, headers=headers, json={"seen": True, "actor_ref": "other"})
            assert forged.status_code == 400 and forged.json()["error"]["effect_state"] == "none"
            assert domain_counts(f) == before
            with f.authority._connect() as connection:
                assert connection.execute("SELECT count(*) FROM communication_client_notice_seen").fetchone() == (1,)
                assert connection.execute("SELECT count(*) FROM communication_client_notice_write_keys").fetchone() == (1,)

    asyncio.run(exercise())
    assert not any(driver.calls for driver in f.drivers.values())


def test_http_legacy_notice_preserves_unknown_creation_and_missing_own_delivery_after_real_adoption(comm, monkeypatch):
    f = comm
    original = fail_b(f)
    # A retained pre-adoption notice may have neither a source timestamp nor a
    # separate Native route. Do not manufacture either during HTTP projection.
    with f.authority._connect() as connection:
        connection.execute("DELETE FROM communication_notice_routes WHERE tenant_id=%s", (f.authority.tenant_id,))

    async def exercise():
        async with authenticated_http(f, monkeypatch) as http:
            response = await http.get(BASE + "/notices")
            assert response.status_code == 200, response.text
            CONTRACTS.validate("NoticePage", response.json())
            assert len(response.json()["items"]) == 1
            notice = response.json()["items"][0]
            assert notice["message_ref"] == original["message_handle"]
            assert notice["created_at"] is None and notice["own_delivery"] is None and notice["receiver_ref"] is None
            assert not notice["seen"] and "PRIVATE" not in response.text

    asyncio.run(exercise())
