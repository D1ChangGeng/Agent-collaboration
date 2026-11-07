"""Real Core PG/ACL/dispatch and DriverJournal; Native protocols are controlled.

No process, model or Native Host is contacted. The receiver's final authorizer
is an explicit fixture; the provenance reader uses actual Core permissions.
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from runtime.codex_driver import (
    AuthorizedOperation,
    BindingIdentity,
    CodexAppServerDriver,
    DriverJournal,
    LaunchProfile,
    file_digest,
)
from runtime.communication_client_native_source import _original_selection
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_client_storage import adopt_client_storage
from runtime.delivery_models import EndpointBindingRequest
from runtime.delivery_node import LocalNodeEndpoint
from runtime.errors import AuthorizationDenied
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.native_provider_registry import (
    LocalExistingSessionProvider,
    NativeProviderRegistry,
    NativeProviderRejected,
)
from runtime.native_view_models import ProviderAdmission
from runtime.opencode_driver import OpenCodeNativeDriver
from runtime.supervisor import OwnedProcess
from runtime.surface_config import CommunicationNativeLinkSettings
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send
from runtime_tests.test_delivery import command
from runtime_tests.test_native_source_links import InProcessHttpWire, InProcessWire
from runtime_tests.test_opencode_driver import profile as open_profile

comm = comm_fixture
PROJECT, RECEIVER = "project-alpha", "endpoint-b"


def client(f, who="a"):
    c = f.clients[who]
    return CommunicationClientService(c.service, c.credential_provider())


@pytest.fixture(params=["codex", "opencode"])
def source(comm, tmp_path, request, monkeypatch):
    f = comm
    with f.authority._connect() as connection:
        adopt_client_storage(connection)
    old = f.authority._delivery_endpoints[RECEIVER]
    identity = BindingIdentity(old.identity.node_id, old.identity.boot_incarnation, "controlled-source-runtime",
        "configured-source-capacity", "slot-b", 3)
    journal = DriverJournal(tmp_path / "source-driver.sqlite")
    if request.param == "codex":
        binary, schema, home = tmp_path / "controlled-profile", tmp_path / "schema.json", tmp_path / "home"
        binary.write_bytes(b"controlled source profile; never executed")
        schema.write_text("{}", encoding="utf-8")
        home.mkdir()
        config = home / "config.toml"
        config.write_text('approval_policy="never"\n', encoding="utf-8")
        profile = LaunchProfile(str(binary), file_digest(binary), "0.153.2", str(schema), file_digest(schema),
            str(tmp_path), str(home), file_digest(config), "fixture", {})
        driver = CodexAppServerDriver("actual-original-source-binding", profile, journal, identity=identity, check_current=lambda *_args: None)
        driver.client = wire = InProcessWire()
        driver.thread_id, driver.session_id = "original-native-thread", "original-native-connection"
        monkeypatch.setattr(driver, "_inspect", lambda *_args: {"thread": {"status": {"type": "idle"}}, "turns": []})
    else:
        folder = tmp_path / "controlled-open"
        folder.mkdir()
        profile = open_profile.__wrapped__(folder)
        driver = OpenCodeNativeDriver("actual-original-source-binding", profile, journal, identity=identity,
            check_current=lambda *_args: None, readback_attempts=1, observe_events=False)
        driver.client = wire = InProcessHttpWire(complete=True)
        driver.session_id = "ses_originalsource"
        monkeypatch.setattr(driver, "_inspect", lambda *_args: {"status": {"type": "idle"}, "messages": []})
    driver.ownership = "exclusive_owned"
    driver.owned = OwnedProcess(SimpleNamespace(pid=49152, poll=lambda: 0), "controlled-no-process", "controlled-birth")

    def ready(operation, *, before_status):
        driver.check_current(operation, identity)
        before_status()
        return ({"thread": {"status": {"type": "idle"}}, "turns": []} if request.param == "codex"
            else {"status": {"type": "idle"}, "messages": []})

    monkeypatch.setattr(driver, "inspect_readiness", ready)
    adapter = NativeDeliveryAdapter(driver, authorize_invocation=lambda inv, _identity:
        AuthorizedOperation(inv.invocation_id, inv.command_id, inv.message_id, inv.envelope.grant_ref, None), record_handoff=True)
    endpoint = LocalNodeEndpoint(old.journal, old.scope_id, old.agent_slot_id, adapter)
    f.dispatcher.service.endpoints[RECEIVER] = endpoint
    for c in f.clients.values():
        c.service.service.authority._delivery_endpoints[RECEIVER] = endpoint
    f.dispatcher.service.bind_endpoint(command(f.authority, "message.bind", RECEIVER, 1),
        EndpointBindingRequest(scope_id=old.scope_id, agent_slot_id=old.agent_slot_id,
            expires_at=f.authority.canonical_now() + timedelta(hours=1)))
    submitted = send(f, activation="invoke")["data"]
    dispatched = f.dispatcher.dispatch({"tenant_id": f.authority.tenant_id, "message_id": submitted["message_id"],
        "operation_id": submitted["operation_id"]})
    facade = client(f)
    invocation, reason = facade._native_source_original(PROJECT, submitted["message_handle"])
    assert invocation is not None, (reason, dispatched, len(wire.calls))
    registry = NativeProviderRegistry()
    provider = LocalExistingSessionProvider(endpoint)
    admission = ProviderAdmission(provider_ref="trusted-original-provider", native_authority="harness",
        selection=_original_selection(invocation))
    registry.register(admission, provider)
    for c in f.clients.values():
        a = c.service.service.authority
        a._native_provider_registry = registry
        a._communication_native_links_enabled = True
        a._communication_native_link_settings = CommunicationNativeLinkSettings()
    monkeypatch.setattr(provider, "existing_session", lambda *_args: pytest.fail("provenance read contacted Native"))
    try:
        yield SimpleNamespace(f=f, facade=facade, registry=registry, admission=admission, journal=journal,
            driver=driver, wire=wire, provider=provider, submitted=submitted, invocation=invocation, protocol=request.param)
    finally:
        driver.owned = None  # No process was started; release only this fixture's claim/transport.
        driver.ownership = "shared_attached"
        driver.detach_transport()


def read(n, who="a"):
    return client(n.f, who).read_message(PROJECT, n.submitted["message_handle"], include_native_source=True)


def test_exact_original_source_is_readable_by_both_participants_without_native_call_or_inbox_consumption(source):
    n = source
    before = len(n.wire.calls)
    first = read(n)
    lookup = first["native_source"]
    assert lookup["available"], lookup
    link = lookup["value"]
    assert link["messageHandle"] == n.submitted["message_handle"]
    assert link["operationId"] == n.submitted["operation_id"]
    assert link["bindingEpoch"] == n.invocation.envelope.binding_revision == 2
    assert link["nativeSession"]["providerRef"] == "trusted-original-provider"
    assert ("nativeTurnRef" in link) == (n.protocol == "codex")
    assert ("nativeInputRef" in link) == (n.protocol == "opencode")
    assert read(n, "b")["native_source"] == lookup
    assert len(n.wire.calls) == before
    assert "native_source" not in n.facade.read_message(PROJECT, n.submitted["message_handle"])
    assert n.facade.project_service.execute("read_message", {"project_id": PROJECT,
        "handle": n.submitted["message_handle"]}, n.facade.credential)[1]["consumed"] is False


def test_unrelated_reader_is_denied_before_journal_or_registry_lookup(source, monkeypatch):
    monkeypatch.setattr(source.registry, "original_source", lambda *_args: pytest.fail("unauthorized registry read"))
    with pytest.raises(AuthorizationDenied):
        read(source, "c")


def test_missing_journal_is_unavailable_and_never_created_by_the_read(source):
    path = source.journal.path
    from pathlib import Path
    Path(path).unlink()
    result = read(source)["native_source"]
    assert not result["available"] and not Path(path).exists()


def test_registry_replacement_during_original_read_cannot_publish_prior_provider(source, monkeypatch):
    import runtime.native_source_links as module

    actual = module._read

    def replaced(journal, operation):
        value = actual(journal, operation)
        source.registry.unregister(source.admission.provider_ref, "harness")
        source.registry.register(source.admission, source.provider)
        return value

    monkeypatch.setattr(module, "_read", replaced)
    assert not read(source)["native_source"]["available"]


def test_grant_revocation_after_journal_read_withholds_body_and_source(source, monkeypatch):
    import runtime.native_source_links as module

    actual = module._read

    def revoked(journal, operation):
        value = actual(journal, operation)
        with source.f.authority._connect() as connection:
            connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                (source.facade.project_service.context.grant_ref,))
        return value

    monkeypatch.setattr(module, "_read", revoked)
    with pytest.raises(AuthorizationDenied):
        read(source)


def test_same_text_message_only_has_no_native_association_and_never_reads_a_journal(source, monkeypatch):
    import runtime.native_source_links as module

    body = source.facade.read_message(PROJECT, source.submitted["message_handle"])["message"]["content"]["text"]
    another = send(source.f, content=body, activation="message_only")["data"]
    monkeypatch.setattr(module, "_read", lambda *_args: pytest.fail("message_only read Native journal"))
    result = source.facade.read_message(PROJECT, another["message_handle"], include_native_source=True)
    assert result["native_source"] == {"available": False, "value": None,
        "reason_code": "native_source_not_requested", "evidence_ref": None}


def test_current_native_session_change_cannot_retarget_original_input(source):
    before = read(source)["native_source"]
    if source.protocol == "codex":
        source.driver.thread_id = "different-current-thread"
    else:
        source.driver.session_id = "ses_differentcurrent"
    assert read(source)["native_source"] == before


def test_provenance_does_not_take_a_delivery_writer_lock(source):
    # A concurrent delivery writer may hold the mutable technical status row.
    # Immutable accepted/dispatch evidence is readable without waiting for that
    # writer or holding the reader Grant against a writer's later checks.
    with source.f.authority._connect() as writer:
        writer.execute("SELECT 1 FROM delivery_messages WHERE tenant_id=%s AND message_id=%s FOR UPDATE",
            (source.f.authority.tenant_id, source.submitted["message_id"]))
        assert read(source)["native_source"]["available"] is True


def test_ambiguous_provider_registration_is_unavailable_without_native_inspection(source):
    source.registry.register(source.admission.model_copy(update={"provider_ref": "second-server-provider"}), source.provider)
    result = read(source)["native_source"]
    assert not result["available"] and result["reason_code"] == "native_source_provider_ambiguous"


def test_revocation_during_unavailable_registry_lookup_withholds_the_previously_read_body(source, monkeypatch):
    def unavailable(_selection):
        with source.f.authority._connect() as connection:
            connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                (source.facade.project_service.context.grant_ref,))
        raise NativeProviderRejected("native_source_provider_unavailable")

    monkeypatch.setattr(source.registry, "original_source", unavailable)
    with pytest.raises(AuthorizationDenied):
        read(source)
