"""Real attachment source transactions, private invalidations and message ACLs.

These cases use disposable PostgreSQL and the admitted temporary platform CAS.
Local receiver fixtures provide no physical Harness/model qualification and
never manufacture an Agent reply from a host capability observation.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from types import SimpleNamespace

import psycopg
import pytest

from runtime import communication_attachment_storage as attachment_storage
from runtime import communication_dispatch as maintenance
from runtime.client_contracts import ClientContracts
from runtime.communication_attachment_event_storage import (
    NAME,
    adopt_attachment_event_storage,
    verify_attachment_event_storage,
)
from runtime.communication_client_events import encode_event_cursor
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_client_storage import adopt_client_storage
from runtime.communication_client_viewer_storage import adopt_viewer_storage
from runtime.communication_event_storage import adopt_event_storage, publish_event_intents
from runtime.communication_http import CommunicationHttpError
from runtime.delivery import DeliveryDispatcher
from runtime.errors import AuthorizationDenied, SchemaAdoptionError
from runtime.project_schema_state import ProjectSchemaAdoptionRequired, verify_project_schema
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_client_attachments import (
    PROJECT,
    bind,
    client,
    ready,
    reserve,
    row,
    upload,
)
from runtime_tests.test_communication_client_attachments import (
    attached as attached_fixture,
)
from runtime_tests.test_notification_continuity import shared_principal_clients

comm, attached = comm_fixture, attached_fixture
CONTRACTS = ClientContracts()
PEER_B = "collaborator:project-alpha:slot-b"


def flags(f, *, enabled=True):
    for source in f.clients.values():
        source.service.service.authority._communication_events_enabled = enabled


@pytest.fixture
def evented(attached):
    flags(attached)
    attached.clients["a"].service.initialize()
    assert verify_project_schema(attached.authority)
    return attached


def anchor(service):
    return service._event_transaction(PROJECT, lambda bound, cur, _root, _cmd, revision:
        encode_event_cursor(cur, bound.tenant_id, PROJECT, revision, 0, anchor=True))


def snapshot(service):
    captured = service.snapshot(PROJECT, limit=1)
    CONTRACTS.validate("Snapshot", captured)
    return captured


def intents(f):
    with psycopg.connect(f.dsn) as connection:
        return [value[0] for value in connection.execute("SELECT to_jsonb(e) FROM communication_event_intents e "
            "WHERE tenant_id=%s AND project_id=%s AND kind='attachment.ready' ORDER BY intent_id",
            (f.authority.tenant_id, PROJECT)).fetchall()]


def publish(f):
    total = 0
    with psycopg.connect(f.dsn) as connection:
        while count := publish_event_intents(connection, f.authority.tenant_id, PROJECT, limit=1000):
            total += count
    return total


def attachment_events(service, start):
    batch = service.event_batch(PROJECT, after_cursor=start, kinds=["attachment.ready"], limit=256)
    for event in batch.events:
        CONTRACTS.validate("Event", event)
        assert event["kind"] == "attachment.ready" and event["payload"] == {}
    return batch


def send(service, refs, *, key="attachment-event-message", content="Message body stays outside event payload"):
    return service.send(PROJECT, {"to": PEER_B, "content": content, "activation": "message_only", "attachment_refs": refs},
                        client_request_id=key)


def test_ready_source_and_result_receipt_are_atomic_and_exact_retry_never_refires(evented, monkeypatch):
    f, own = evented, client(evented)
    captured = snapshot(own)
    data = b"PRIVATE_ATTACHMENT_CONTENT_SENTINEL"
    value = reserve(own, data, name="PRIVATE_FILENAME_SENTINEL.txt")
    upload(own, value, data)
    assert intents(f) == []
    original = attachment_storage._receipt
    def fail_final_result(cur, owner, namespace, kind, body, identifier, result):
        if kind == "finalize_result":
            raise RuntimeError("controlled post-ready receipt failure")
        return original(cur, owner, namespace, kind, body, identifier, result)
    monkeypatch.setattr(attachment_storage, "_receipt", fail_final_result)
    final_body = {"bytes": value["bytes"], "sha256": value["sha256"]}
    with pytest.raises(CommunicationHttpError) as rolled_back:
        own.finalize_attachment(PROJECT, value["attachment_id"], final_body, client_request_id="stable-finalize")
    assert rolled_back.value.status_code == 503
    assert row(f, value["attachment_id"])["state"] == "uploaded" and intents(f) == []
    monkeypatch.setattr(attachment_storage, "_receipt", original)
    finalized = own.finalize_attachment(PROJECT, value["attachment_id"], final_body, client_request_id="stable-finalize")
    records = intents(f)
    assert len(records) == 1 and records[0]["resource_revision"] == finalized["revision"]
    assert records[0]["audience_kind"] == "private" and records[0]["sender"] is None
    assert records[0]["recipient"] == "collaborator:project-alpha:local-slot"
    assert records[0]["actor_ref"] == own._viewer_actor_ref(PROJECT, records[0]["recipient"])
    assert records[0]["scope_id"] == "local-scope" and records[0]["payload_json"] == {}
    publish(f)
    first = attachment_events(own, captured["after_cursor"])
    assert len(first.events) == 1 and first.events[0]["resource_ref"] == value["attachment_id"]
    assert own.finalize_attachment(PROJECT, value["attachment_id"], final_body, client_request_id="stable-finalize") == finalized
    assert publish(f) == 0 and intents(f) == [{**records[0], "published_sequence": intents(f)[0]["published_sequence"]}]
    assert attachment_events(own, first.after_cursor).events == ()
    encoded = json.dumps([*intents(f), *first.events])
    for secret in (data.decode(), value["name"], value["sha256"], value["media_type"]):
        assert secret not in encoded
    assert not any(driver.calls for driver in f.drivers.values())


def test_pin_revision_matches_getter_and_recipient_hydrates_refs_from_actual_message(evented):
    f, own, recipient = evented, client(evented), client(evented, "b")
    value = ready(own, b"shared through message", name="visible-message-attachment.txt")
    publish(f)
    own_cut, recipient_cut = snapshot(own), snapshot(recipient)
    accepted = send(own, [value["attachment_id"]])
    current = own.attachment(PROJECT, value["attachment_id"])
    assert current["revision"] == value["revision"] + 1 and current["expires_at"] is None
    publish(f)
    owner_batch = attachment_events(own, own_cut["after_cursor"])
    assert len(owner_batch.events) == 1 and owner_batch.events[0]["resource_revision"] == current["revision"]
    assert intents(f)[-1]["resource_revision"] == current["revision"]
    incoming = recipient.event_batch(PROJECT, after_cursor=recipient_cut["after_cursor"], limit=256)
    assert all(event["kind"] != "attachment.ready" for event in incoming.events)
    committed = [event for event in incoming.events if event["kind"] == "message.committed"]
    assert len(committed) == 1 and committed[0]["resource_ref"] == accepted["message"]["message_handle"]
    hydrated = recipient.read_message(PROJECT, committed[0]["resource_ref"])
    assert hydrated["message"]["attachment_refs"] == accepted["message"]["attachment_refs"]
    assert hydrated["message"]["attachment_refs"][0]["attachment_id"] == value["attachment_id"]
    assert recipient.download_attachment(PROJECT, value["attachment_id"]).data == b"shared through message"
    assert hydrated["first_reply"] is None and accepted["delivery"]["native"]["state"] == "not_requested"
    assert not any(driver.calls for driver in f.drivers.values())


def test_ordinary_legacy_slots_keep_core_unknown_management_level_but_get_actual_agent_profile_and_snapshot(evented):
    f = evented
    for name in ("b", "c"):
        source, service = f.clients[name], client(f, name)
        core = source.call("read_profile", {})["structuredContent"]
        assert core["ok"]
        actor = core["data"]["actor"]
        assert actor["binding_source"] == "trusted_collaborator_binding"
        assert actor["organization"]["level"] == "unknown" and actor["agent_slot_id"] == f"slot-{name}"
        assert actor["bindings"] and all(binding["agent_slot_id"] == actor["agent_slot_id"]
            and binding["principal_ref"] == source.service.context.principal_ref for binding in actor["bindings"])
        mapped = service.profile()
        assert mapped["level"] == "agent" and mapped["agent_slot_id"] == actor["agent_slot_id"]
        assert mapped["principal_ref"] == source.service.context.principal_ref
        assert mapped["allowed_actions"] == source.service.available_tools(source.credential_provider())
        assert "configure_team" not in mapped["allowed_actions"]
        captured = snapshot(service)
        assert captured["actor"]["level"] == "agent" and captured["actor"]["agent_slot_id"] == actor["agent_slot_id"]
        assert source.call("read_profile", {})["structuredContent"]["data"]["actor"]["organization"]["level"] == "unknown"
    assert not any(driver.calls for driver in f.drivers.values())


def profile_fixture(actor, *, tools):
    """Pure DTO boundary fixture; no authentication or PG evidence is claimed."""
    facade = CommunicationClientService.__new__(CommunicationClientService)
    facade.project_service = SimpleNamespace(context=SimpleNamespace(principal_ref="agent:actual"), available_tools=tools)
    facade.credential = "synthetic-not-a-credential"
    facade._execute = lambda _name, _args: ("observed", {"actor": actor}, [])
    return facade


def bound_unknown_actor():
    return {"organization": {"level": "unknown"}, "binding_source": "trusted_collaborator_binding",
            "agent_slot_id": "actual-slot", "profile": "root_manager", "bindings": [
                {"agent_slot_id": "actual-slot", "principal_ref": "agent:actual", "organization": {"level": "unknown"}}]}


@pytest.mark.parametrize("invalid", ["untrusted_source", "missing_slot", "empty_bindings", "different_slot", "different_principal", "mixed_management"])
def test_unknown_actor_mapping_rejects_unbound_or_mismatched_source_evidence_before_exposing_actions(invalid):
    actor = bound_unknown_actor()
    if invalid == "untrusted_source":
        actor["binding_source"] = "payload_claim"
    elif invalid == "missing_slot":
        actor["agent_slot_id"] = None
    elif invalid == "empty_bindings":
        actor["bindings"] = []
    elif invalid == "different_slot":
        actor["bindings"][0]["agent_slot_id"] = "another-slot"
    elif invalid == "different_principal":
        actor["bindings"][0]["principal_ref"] = "agent:someone-else"
    else:
        actor["bindings"].append({"agent_slot_id": "actual-slot", "principal_ref": "agent:actual", "organization": {"level": "root"}})
    def forbidden(_credential):
        pytest.fail("unbound or mismatched Actor evidence exposed actions")
    with pytest.raises(CommunicationHttpError) as rejected:
        profile_fixture(actor, tools=forbidden).profile()
    assert rejected.value.code == "authorization_unavailable" and rejected.value.status_code == 403


def test_unknown_bound_actor_mapping_preserves_actual_actions_and_never_infers_management_from_profile_name():
    actor = bound_unknown_actor()
    mapped = profile_fixture(actor, tools=lambda _credential: ["read_profile"]).profile()
    assert actor["profile"] == "root_manager" and actor["organization"]["level"] == "unknown"
    assert mapped["level"] == "agent" and mapped["agent_slot_id"] == "actual-slot"
    assert mapped["allowed_actions"] == ["read_profile"]


def test_private_event_isolated_from_same_principal_slot_ordinary_peer_and_root_manager(evented):
    f = evented
    shared_principal_clients(f)
    bind(f)
    flags(f)
    first, second, peer, manager = (client(f, name) for name in ("shared-1", "shared-2", "b", "a"))
    starts = [anchor(service) for service in (first, second, peer, manager)]
    value = ready(first, b"same-principal private upload", key="private-owner")
    publish(f)
    assert len(attachment_events(first, starts[0]).events) == 1
    for outsider, start in zip((second, peer, manager), starts[1:], strict=True):
        assert attachment_events(outsider, start).events == ()
        with pytest.raises(CommunicationHttpError) as denied:
            outsider.attachment(PROJECT, value["attachment_id"])
        assert denied.value.status_code == 404
    assert intents(f)[0]["recipient"] == f"collaborator:{PROJECT}:shared-slot-1"
    assert intents(f)[0]["actor_ref"] != second._viewer_actor_ref(PROJECT, f"collaborator:{PROJECT}:shared-slot-2")


def test_current_read_message_permission_filters_private_event_even_when_other_event_tools_remain(evented):
    f, own = evented, client(evented)
    ready(own, b"authorization boundary")
    publish(f)
    before = attachment_events(own, anchor(own))
    assert len(before.events) == 1
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE grants SET permissions=permissions-'message.read' WHERE grant_ref=%s", (own.project_service.context.grant_ref,))
    assert attachment_events(own, anchor(own)).events == ()
    with pytest.raises(CommunicationHttpError) as changed:
        own.event_current(PROJECT, expected_auth_revision=before.auth_revision, event_id=before.events[0]["event_id"])
    assert changed.value.code == "permission_changed"


@pytest.mark.parametrize("revoke", ["grant", "scope"])
def test_revoked_current_grant_or_caller_scope_prevents_saved_event_emission(evented, revoke):
    f, own = evented, client(evented)
    ready(own, b"current authority is mandatory")
    publish(f)
    batch = attachment_events(own, anchor(own))
    with psycopg.connect(f.dsn) as connection:
        if revoke == "grant":
            connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (own.project_service.context.grant_ref,))
        else:
            connection.execute("UPDATE scopes SET status='revoked' WHERE tenant_id=%s AND scope_id='local-scope'", (f.authority.tenant_id,))
    with pytest.raises(AuthorizationDenied):
        own.event_current(PROJECT, expected_auth_revision=batch.auth_revision, event_id=batch.events[0]["event_id"])


@pytest.mark.parametrize("change", ["feature_off", "missing_object"])
def test_jit_event_current_rechecks_feature_and_actual_private_object_after_batch(evented, change):
    f, own = evented, client(evented)
    value = ready(own, b"just-in-time metadata visibility")
    publish(f)
    start = anchor(own)
    batch = attachment_events(own, start)
    event = batch.events[0]
    assert own.event_current(PROJECT, expected_auth_revision=batch.auth_revision, event_id=event["event_id"])
    if change == "feature_off":
        own.authority._communication_attachments_enabled = False
    else:
        # Explicit disposable-fixture source damage: no accepted message refers
        # to this unpinned upload. A stale selected event must not bypass lookup.
        with psycopg.connect(f.dsn) as connection:
            connection.execute("DELETE FROM communication_attachment_requests WHERE attachment_id=%s", (value["attachment_id"],))
            connection.execute("DELETE FROM communication_attachments WHERE attachment_id=%s", (value["attachment_id"],))
    with pytest.raises(CommunicationHttpError) as changed:
        own.event_current(PROJECT, expected_auth_revision=batch.auth_revision, event_id=event["event_id"])
    assert changed.value.code == "permission_changed"
    assert attachment_events(own, start).events == ()


def test_initialize_adopts_optional_source_with_existing_event_metadata_without_backfilling_ready_history(attached):
    f, own = attached, client(attached)
    old = ready(own, b"predates optional event source", key="pre-adoption")
    original = row(f, old["attachment_id"])
    with psycopg.connect(f.dsn) as connection:
        adopt_client_storage(connection)
        adopt_viewer_storage(connection)
        adopt_event_storage(connection)
        assert connection.execute("SELECT 1 FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone() is None
    flags(f, enabled=False)
    with pytest.raises(ProjectSchemaAdoptionRequired):
        verify_project_schema(f.authority)
    with psycopg.connect(f.dsn) as connection:
        assert connection.execute("SELECT 1 FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone() is None
    f.clients["a"].service.initialize()
    with psycopg.connect(f.dsn) as connection:
        verify_attachment_event_storage(connection)
    assert intents(f) == [] and row(f, old["attachment_id"]) == original
    flags(f)
    f.clients["a"].service.initialize()
    start = anchor(own)
    new = ready(own, b"actual post-adoption transition", key="post-adoption")
    publish(f)
    batch = attachment_events(own, start)
    assert [event["resource_ref"] for event in batch.events] == [new["attachment_id"]]
    assert len(intents(f)) == 1


@pytest.mark.parametrize("damage", ["function", "trigger"])
def test_damaged_attachment_source_fails_read_only_startup_and_explicit_readoption(evented, damage):
    f = evented
    commands = {"function": "ALTER FUNCTION acs_attachment_ready_event() STABLE",
                "trigger": "ALTER TABLE communication_attachments DISABLE TRIGGER acs_attachment_ready_event"}
    with psycopg.connect(f.dsn) as connection:
        connection.execute(commands[damage])
    for operation in (verify_attachment_event_storage, adopt_attachment_event_storage):
        with psycopg.connect(f.dsn) as connection, pytest.raises(SchemaAdoptionError):
            operation(connection)
    with pytest.raises(ProjectSchemaAdoptionRequired):
        verify_project_schema(f.authority)
    with psycopg.connect(f.dsn) as connection:
        state = connection.execute("SELECT p.provolatile,t.tgenabled FROM pg_proc p JOIN pg_trigger t ON t.tgfoid=p.oid "
            "WHERE t.tgname='acs_attachment_ready_event' AND t.tgrelid=to_regclass('communication_attachments')").fetchone()
    assert state == (("s", "O") if damage == "function" else ("v", "D"))


def test_external_maintenance_publishes_and_expires_staging_with_ui_off_preserving_pinned_content(evented, monkeypatch):
    f, own = evented, client(evented)
    pinned = ready(own, b"accepted pinned bytes", key="pinned")
    accepted = send(own, [pinned["attachment_id"]])
    staged = reserve(own, b"temporary staged bytes", key="staged")
    upload(own, staged, b"temporary staged bytes", key="staged-upload")
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE communication_attachments SET expires_at=created_at+interval '1 microsecond',revision=revision+1 "
                           "WHERE attachment_id=%s", (staged["attachment_id"],))
    assert verify_project_schema(f.authority)
    flags(f, enabled=False)
    for source in f.clients.values():
        source.service.service.authority._communication_attachments_enabled = False
    f.authority._communication_maintenance_mode = "external"
    def forbidden(*_args, **_kwargs):
        pytest.fail("external attachment maintenance touched delivery or Native")
    monkeypatch.setattr(maintenance, "_pending", forbidden)
    monkeypatch.setattr(DeliveryDispatcher, "dispatch", forbidden)
    for endpoint in f.authority._delivery_endpoints.values():
        for method in ("prepare_runtime", "inspect_runtime", "receiver_snapshot"):
            monkeypatch.setattr(endpoint, method, forbidden)
    def maintained():
        with psycopg.connect(f.dsn) as connection:
            pending = connection.execute("SELECT count(*) FROM communication_event_intents WHERE published_sequence IS NULL").fetchone()[0]
            state = connection.execute("SELECT state FROM communication_attachments WHERE attachment_id=%s", (staged["attachment_id"],)).fetchone()[0]
            return pending == 0 and state == "expired"
    async def exercise():
        task = asyncio.create_task(maintenance.maintain_communication_deliveries(f.clients["a"].service.service))
        try:
            stop = asyncio.get_running_loop().time() + 6
            while asyncio.get_running_loop().time() < stop:
                if task.done():
                    await task
                    pytest.fail("external maintenance stopped before completing durable work")
                if await asyncio.to_thread(maintained):
                    assert f.authority._communication_event_maintenance_running
                    assert not f.authority._communication_maintenance_running
                    return
                await asyncio.sleep(0.025)
            pytest.fail("external maintenance did not publish/expire within its bounded budget")
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    asyncio.run(exercise())
    assert not f.authority._communication_event_maintenance_running
    preserved = row(f, pinned["attachment_id"])
    assert preserved["pinned"] and preserved["state"] == "ready" and preserved["expires_at"] is None
    with psycopg.connect(f.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM communication_attachment_chunks WHERE attachment_id=%s", (staged["attachment_id"],)).fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone()[0] == 0
        packet = connection.execute("SELECT packet_json FROM delivery_messages WHERE operation_id=%s", (accepted["operation_ref"],)).fetchone()[0]
    assert packet["attachment_refs"] == accepted["message"]["attachment_refs"]
    recipient = client(f, "b")
    recipient.authority._communication_attachments_enabled = True
    assert recipient.download_attachment(PROJECT, pinned["attachment_id"]).data == b"accepted pinned bytes"
    assert not any(driver.calls for driver in f.drivers.values())
