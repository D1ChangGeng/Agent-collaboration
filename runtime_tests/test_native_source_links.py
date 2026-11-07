"""E1 projection over actual DriverJournal/handoff and a controlled in-process RPC.

The real Driver creates the original bound receipt from that protocol response.
No process, Host, socket, model, PG, transcript or prebuilt SourceLink is used.
"""
from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from runtime.codex_driver import (
    AuthorizedOperation,
    BindingIdentity,
    CodexAppServerDriver,
    DriverJournal,
    LaunchProfile,
    digest,
    file_digest,
)
from runtime.delivery_models import DeliveryEnvelope, MessagePacket
from runtime.delivery_node import invocation_for
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.native_source_links import NativeSourceLinkPort
from runtime.native_view_models import NativeSelection, ProviderAdmission
from runtime.opencode_driver import OpenCodeNativeDriver
from runtime.receiver_contract import ReceiverBinding
from runtime_tests.test_opencode_driver import profile as opencode_profile


class InProcessWire:
    """A named protocol fixture, not installed Native/model evidence."""

    def __init__(self):
        self.calls = []

    def request(self, method, params, *, timeout, request_id, before_send, on_dispatch):
        assert method == "turn/start" and params["threadId"] == "original-native-thread"
        before_send()
        on_dispatch()
        self.calls.append((method, params, request_id))
        return {"turn": {"id": "protocol-observed-turn", "status": "inProgress"}}

    def drain_events(self):
        return []

    def close(self):
        return None


@pytest.fixture
def original(tmp_path, monkeypatch):
    binary, schema, home = tmp_path / "controlled-profile", tmp_path / "schema.json", tmp_path / "home"
    binary.write_bytes(b"controlled profile file; never executed")
    schema.write_text("{}", encoding="utf-8")
    home.mkdir()
    config = home / "config.toml"
    config.write_text('default_permissions="fixture"\napproval_policy="never"\n', encoding="utf-8")
    profile = LaunchProfile(str(binary), file_digest(binary), "0.153.2", str(schema), file_digest(schema),
        str(tmp_path), str(home), file_digest(config), "fixture", {})
    journal = DriverJournal(tmp_path / "driver.sqlite")
    identity = BindingIdentity("original-node", "original-boot", "original-runtime", "native-capacity", "slot-b", 3)
    driver = CodexAppServerDriver("original-driver-binding", profile, journal, identity=identity,
                                 check_current=lambda *_args: None)
    wire = InProcessWire()
    driver.client, driver.thread_id, driver.session_id = wire, "original-native-thread", "original-native-connection"
    driver.ownership = "exclusive_owned"
    # Readiness is a controlled existing-session metadata fixture. The ACK below
    # still comes through the real invoke/_rpc/DriverJournal code, not a seeded ACK row.
    monkeypatch.setattr(driver, "_inspect", lambda *_args: {"thread": {"status": {"type": "idle"}}, "turns": []})
    packet = MessagePacket(project_id="project", sender="collaborator:project:a", recipient="collaborator:project:slot-b",
        content="Original input text", target_scope_id="scope", target_agent_slot_id="slot-b", activation="invoke")
    envelope = DeliveryEnvelope(tenant_id="tenant", authority_id="authority", authority_incarnation="incarnation",
        principal_ref="sender", grant_ref="core-grant", message_id="message-one", command_id="command-one",
        operation_id="original-core-operation", endpoint_id="original-endpoint", binding_revision=7,
        machine_id="original-host", node_id=identity.node_id, boot_incarnation=identity.node_boot_id,
        accepted_state_digest="a" * 64, packet=packet)
    invocation = invocation_for(envelope, "original-core-attempt")
    adapter = NativeDeliveryAdapter(driver, authorize_invocation=lambda inv, _identity:
        AuthorizedOperation(inv.invocation_id, inv.command_id, inv.message_id, "original-native-grant", None), record_handoff=True)
    observation = adapter.invoke(invocation, on_dispatch=lambda: None)
    assert observation.native_ack_ref and len(wire.calls) == 1
    binding = ReceiverBinding(receiver_id=envelope.endpoint_id, actor_address=packet.recipient,
        binding_epoch=envelope.binding_revision, provider_generation=None, native_session_ref=None,
        authority_id=envelope.authority_id, authority_incarnation=envelope.authority_incarnation,
        execution_host_ref=envelope.machine_id)
    admission = ProviderAdmission(provider_ref="server-owned-original-provider", native_authority="harness",
        selection=NativeSelection(tenant_id=envelope.tenant_id, project_id=packet.project_id, scope_id=packet.target_scope_id,
            agent_slot_id=packet.target_agent_slot_id, binding=binding, node_id=envelope.node_id,
            boot_incarnation=envelope.boot_incarnation, runtime_id=identity.runtime_id, runtime_binding_revision=identity.revision))
    checks = []

    def core_reader(message, operation):
        assert (message, operation) == ("message:project:message-one", invocation.operation_id)
        return invocation

    def authorize(actual):
        assert actual == invocation
        checks.append(True)

    values = {"read_original": core_reader, "original_provider": lambda _inv: admission,
              "journal_for": lambda _inv: journal, "authorize_original": authorize}
    yield SimpleNamespace(driver=driver, wire=wire, journal=journal, invocation=invocation, admission=admission,
                          checks=checks, values=values, port=NativeSourceLinkPort(**values))
    driver.detach_transport()


def project(f, **ports):
    return NativeSourceLinkPort(**(f.values | ports)).read("message:project:message-one", "original-core-operation")


def corrupt(f, transform):
    with f.journal._connect() as connection:
        row = connection.execute("SELECT input_json,result_json FROM driver_operations WHERE operation_id=?",
                                 (f.invocation.invocation_id,)).fetchone()
        body, receipt = json.loads(row[0]), json.loads(row[1])
        transform(body, receipt)
        connection.execute("UPDATE driver_operations SET input_json=?,input_hash=?,result_json=? WHERE operation_id=?",
            (json.dumps(body), digest(body), json.dumps(receipt), f.invocation.invocation_id))


def test_original_protocol_receipt_projects_core_operation_and_original_turn_without_new_io(original):
    result = project(original)
    assert result.available and result.reason_code is None and result.evidence_ref.startswith("driver-source:")
    assert result.value.as_client() == {"messageHandle": "message:project:message-one", "operationId": "original-core-operation",
        "bindingEpoch": 7, "nativeSession": {"providerRef": "server-owned-original-provider", "sessionRef": "original-native-thread",
        "hostRef": "original-host", "generation": original.journal.read(original.invocation.invocation_id)["input"]["payload"]["handoff_context"]["provider_generation"],
        "authority": "harness"}, "nativeTurnRef": "protocol-observed-turn"}
    assert result.value.operation_id != original.invocation.invocation_id
    assert result.value.native_input_ref is None
    assert len(original.checks) == 2 and len(original.wire.calls) == 1
    assert "Original input text" not in json.dumps(result.value.as_client())


def test_historical_ack_uses_original_thread_and_generation_after_current_session_changes(original):
    before = project(original).value
    original.driver.thread_id, original.driver.session_id = "new-thread", "new-connection"
    after = project(original).value
    assert after == before and after.native_session.session_ref == "original-native-thread"
    assert len(original.wire.calls) == 1


@pytest.mark.parametrize("change", ["message", "operation", "input_text", "generation", "epoch", "auth", "receipt_operation", "receipt_turn"])
def test_copied_or_changed_record_cannot_become_a_source_link(original, change):
    def mutate(body, receipt):
        context = body["payload"]["handoff_context"]
        if change == "message": context["message_id"] = "other-message"
        elif change == "operation": context["operation_id"] = "other-invocation"
        elif change == "input_text": body["payload"]["text"] = "Different text"
        elif change == "generation": context["provider_generation"] = "new-generation"
        elif change == "epoch": context["binding_epoch"] = 8
        elif change == "auth": context["auth_revision"] = "0" * 64
        elif change == "receipt_operation": receipt["operation_id"] = "other-operation"
        elif change == "receipt_turn": receipt["turn_id"] = "unobserved-turn"
    corrupt(original, mutate)
    assert not project(original).available
    assert len(original.wire.calls) == 1


def test_identical_text_without_original_handoff_context_is_unavailable(original):
    corrupt(original, lambda body, _receipt: body["payload"].pop("handoff_context"))
    result = project(original)
    assert not result.available and result.value is None


def test_ack_row_without_actual_protocol_response_is_unavailable(original):
    with original.journal._connect() as connection:
        connection.execute("DELETE FROM driver_events WHERE operation_id=? AND kind='rpc_response'",
                           (original.invocation.invocation_id,))
    assert not project(original).available


@pytest.mark.parametrize("kind", ["wrong_core", "copied_body", "message_only", "remote_locator"])
def test_public_entry_has_no_caller_invocation_or_dynamic_locator_escape(original, kind):
    actual = original.invocation
    if kind == "wrong_core":
        result = project(original, read_original=lambda *_args: actual.model_copy(update={"operation_id": "another-core-operation"}))
    elif kind == "copied_body":
        result = project(original, read_original=lambda *_args: actual.model_dump(mode="json"))
    elif kind == "remote_locator":
        result = project(original, journal_for=lambda *_args: None)
    else:
        packet = actual.envelope.packet.model_copy(update={"activation": "message_only"})
        envelope = actual.envelope.model_copy(update={"packet": packet})
        changed = invocation_for(envelope, actual.attempt_id)
        result = project(original, read_original=lambda *_args: changed,
                         authorize_original=lambda *_args: None,
                         journal_for=lambda *_args: pytest.fail("message_only read a private Driver journal"))
    assert not result.available and result.value is None


@pytest.mark.parametrize("where", ["before", "after", "non_authorizer"])
def test_current_core_authorization_fences_private_read_and_result(original, where):
    checks = []

    def authorize(_inv):
        checks.append(True)
        if where == "non_authorizer": return True
        if where == "before" or len(checks) == 2: raise PermissionError("current original message/Scope access revoked")

    with pytest.raises(PermissionError):
        project(original, authorize_original=authorize,
                journal_for=(lambda _inv: pytest.fail("denied read reached private journal")) if where in {"before", "non_authorizer"}
                else (lambda _inv: original.journal))
    assert len(checks) == (2 if where == "after" else 1)


def test_current_or_unrelated_provider_registration_cannot_retarget_original_ack(original):
    selected = original.admission.selection
    other = original.admission.model_copy(update={"selection": selected.model_copy(update={
        "binding": selected.binding.model_copy(update={"binding_epoch": 8, "execution_host_ref": "replacement-host"})})})
    assert not project(original, original_provider=lambda _inv: other).available


def test_constructor_requires_real_explicit_core_authorization_ports():
    with pytest.raises(TypeError):
        NativeSourceLinkPort(read_original=None, original_provider=None, journal_for=None, authorize_original=None)


class InProcessHttpWire:
    endpoint = "inprocess://controlled-opencode-wire"

    def __init__(self, *, complete):
        self.complete, self.calls, self.posted = complete, [], None

    def request(self, method, path, payload, *, timeout, max_bytes, before_send, on_dispatch):
        before_send()
        on_dispatch()
        self.calls.append((method, path))
        if method == "POST":
            assert path.endswith("/prompt_async")
            self.posted = payload
            return 204, None
        assert method == "GET" and "/message/" in path and self.posted is not None
        session = path.split("/")[2]
        message = self.posted["messageID"]
        return 200, {"info": {"id": message, "sessionID": session, "role": "user", "agent": "engineer",
                             "model": {"providerID": "provider", "modelID": "model"}},
                     "parts": [{"type": "text", "text": self.posted["parts"][0]["text"],
                                "sessionID": session, "messageID": message}] if self.complete else []}

    def close(self):
        return None


@pytest.mark.parametrize("complete", [True, False], ids=["exact-provider-readback", "204-only"])
def test_opencode_link_requires_real_driver_exact_readback_not_http204(original, tmp_path, monkeypatch, complete):
    folder = tmp_path / "opencode-controlled"
    folder.mkdir()
    profile = replace(opencode_profile.__wrapped__(folder), execution_mode="native")
    journal = DriverJournal(folder / "original-driver.sqlite")
    driver = OpenCodeNativeDriver("original-open-binding", profile, journal, identity=original.driver.identity,
        check_current=lambda *_args: None, readback_attempts=1, observe_events=False)
    driver.client = wire = InProcessHttpWire(complete=complete)
    driver.session_id, driver.ownership = "ses_originalsource", "shared_attached"
    monkeypatch.setattr(driver, "_inspect", lambda *_args: {"status": {"type": "idle"}, "messages": []})
    envelope = original.invocation.envelope.model_copy(update={"message_id": "open-message", "command_id": "open-command",
                                                               "operation_id": "open-core-operation"})
    invocation = invocation_for(envelope, "open-core-attempt")
    adapter = NativeDeliveryAdapter(driver, authorize_invocation=lambda inv, _identity:
        AuthorizedOperation(inv.invocation_id, inv.command_id, inv.message_id, "original-native-grant", None), record_handoff=True)
    try:
        observed = adapter.invoke(invocation, on_dispatch=lambda: None)
        assert bool(observed.native_ack_ref) is complete
        admission = original.admission.model_copy(update={"provider_ref": "server-admitted-open-source"})
        checks = []
        port = NativeSourceLinkPort(read_original=lambda *_refs: invocation, original_provider=lambda _inv: admission,
            journal_for=lambda _inv: journal, authorize_original=lambda _inv: checks.append(True))
        result = port.read("message:project:open-message", invocation.operation_id)
        assert result.available is complete
        assert len(checks) == 2 and len(wire.calls) == 2
        if complete:
            value = result.value.as_client()
            assert value["operationId"] == "open-core-operation" and value["nativeInputRef"] == wire.posted["messageID"]
            assert value["nativeSession"]["sessionRef"] == "ses_originalsource" and "nativeTurnRef" not in value
        else:
            assert result.value is None and result.reason_code == "native_source_ack_missing"
    finally:
        driver.detach_transport()


def test_input_checksum_failure_never_projects(original):
    with original.journal._connect() as connection:
        connection.execute("UPDATE driver_operations SET input_hash=? WHERE operation_id=?",
                           ("0" * 64, original.invocation.invocation_id))
    assert not project(original).available


def test_provider_brand_or_unknown_authority_is_not_a_source_authorization(original):
    other = original.admission.model_copy(update={"native_authority": "codex"})
    assert not project(original, original_provider=lambda _inv: other).available


def test_protocol_request_with_additional_uncorrelated_input_does_not_project(original):
    with original.journal._connect() as connection:
        row = connection.execute("SELECT sequence,body FROM driver_events WHERE operation_id=? AND kind='rpc_intent' "
            "AND json_extract(body,'$.method')='turn/start'", (original.invocation.invocation_id,)).fetchone()
        body = json.loads(row[1])
        body["params"]["input"].append({"type": "text", "text": "uncorrelated extra input", "text_elements": []})
        connection.execute("UPDATE driver_events SET body=? WHERE sequence=?", (json.dumps(body), row[0]))
    assert not project(original).available
