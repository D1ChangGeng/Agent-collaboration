"""Actual Core PG/ACL, signed TLS Receiver and original Host source composition.

The Host's serialized input/lookup callbacks are explicit doubles. No Native
Driver, process, model, actual Orca installation or production source is used.
"""
from __future__ import annotations

import os
import threading
import traceback
from dataclasses import fields
from datetime import timedelta

import pytest

from runtime.communication_client_native_source import _original_selection
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_client_storage import adopt_client_storage
from runtime.delivery_models import EndpointBindingRequest
from runtime.errors import AuthorizationDenied
from runtime.native_provider_registry import NativeProviderRegistry
from runtime.native_view_models import ProviderAdmission
from runtime.orca_receiver_backend import ExistingOrcaReceiverBackend, OrcaReceiverRouter
from runtime.receiver_config import ReceiverClientConfig, ReceiverRuntimeConfig
from runtime.receiver_delivery import RemoteNodeEndpointAdapter, RemoteSenderDeployment
from runtime.remote_endpoint import ReceiverHTTPServer
from runtime.remote_native_source import RemoteNativeSourceReader
from runtime.surface_config import CommunicationNativeLinkSettings
from runtime_tests.probe_receiver_windows_backend import private_root
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send
from runtime_tests.test_delivery import command
from runtime_tests.test_receiver_lifecycle_issuance_pg import PROJECT, RECEIVER, setup_graph
from runtime_tests.test_receiver_protocol import certificate, free_port

comm = comm_fixture


@pytest.mark.parametrize("lost_host_ack", [False, True])
def test_actual_core_remote_provenance_and_original_host_reconcile(comm, tmp_path, lost_host_ack):
    private = tmp_path / "host-private"
    if os.name == "nt":
        private_root(private)
    else:
        private.mkdir(mode=0o700)
    cert, tls_key, fingerprint = certificate(private)
    f = setup_graph(comm, mode="owner", locator_port=free_port(), tls_certificate_sha256=fingerprint)
    endpoint = RemoteNodeEndpointAdapter(f.authority, RECEIVER,
        RemoteSenderDeployment(f.authority_key, f.registration.boot_incarnation, 1))
    for client in comm.clients.values():
        client.service.service.authority._delivery_endpoints[RECEIVER] = endpoint
    comm.dispatcher.service.endpoints[RECEIVER] = endpoint
    comm.dispatcher.service.bind_endpoint(command(f.authority, "message.bind", RECEIVER, 1),
        EndpointBindingRequest(scope_id="local-scope", agent_slot_id="slot-b",
                               expires_at=f.authority.canonical_now() + timedelta(minutes=5)))
    with f.authority._connect() as connection:
        adopt_client_storage(connection)
        epoch = connection.execute("SELECT revision FROM delivery_endpoints WHERE tenant_id=%s AND endpoint_id=%s",
            (f.authority.tenant_id, RECEIVER)).fetchone()[0]
    seed = private / "node.seed"
    seed.write_text(f.node_key.encode().hex(), encoding="ascii")
    if os.name != "nt":
        seed.chmod(0o600)
    values = {item.name: getattr(endpoint.config, item.name) for item in fields(ReceiverClientConfig)}
    config = ReceiverRuntimeConfig(**values, tls_cert_path=str(cert), tls_key_path=str(tls_key),
        node_signing_key_path=str(seed), ledger_path=str(private / "receiver.sqlite"))
    owner = {"receiverRef": RECEIVER, "address": "collaborator:project-alpha:slot-b", "bindingEpoch": epoch,
        "hostPrincipalRef": "controlled-independent-orca-host", "authorityId": f.registration.authority_id,
        "authorityIncarnation": f.registration.authority_incarnation, "scopeRef": f.registration.scope_id,
        "ownerToken": object(), "inputOwner": "orca", "session": {"providerRef": "enrolled-host-provider",
            "sessionRef": "original-host-session", "hostRef": f.registration.machine_id,
            "generation": "original-host-generation", "authority": "orca"}}
    calls, original_results = [], {}
    installed = []

    def install(service):
        backend = ExistingOrcaReceiverBackend(service, current_ownership=lambda: owner)
        installed.append(backend)

        def admit(value):
            backend.assert_current(value)
            command = value["command"]
            calls.append(("admit", command["operation_id"]))
            result = {"schema_version": "acs-adapter/1", "operation_id": command["operation_id"], "outcome": "accepted",
                "effect_possible": True, "evidence_ref": "controlled-original-host-receipt", "native_input_ref": "original-host-input",
                "binding_epoch": command["binding_epoch"], "provider_generation": command["provider_generation"], "reason_code": None}
            original_results[command["operation_id"]] = result
            if lost_host_ack:
                raise OSError("Host ACK lost after original admission")
            return result

        def observe(_admission):
            now = f.authority.canonical_now()
            return {"activity": "idle", "observed_at": now.isoformat(), "expires_at": (now + timedelta(seconds=2)).isoformat(),
                    "source": "controlled-host-native-observation"}

        def original(value):
            calls.append(("read_original", value["command"]["operation_id"]))
            assert value["session"]["sessionRef"] == "original-host-session"
            return original_results[value["command"]["operation_id"]]

        return OrcaReceiverRouter(backend, admit_original=admit, observe_readiness=observe, reconcile_original=original)

    forbidden = lambda *_args: pytest.fail("Orca-owned input cannot enter an ACS Native Driver")
    server = ReceiverHTTPServer(config, f.node_key, f.authority.receiver_transport.current_authority,
        forbidden, clock=endpoint.clock, receiver_router_factory=install)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    worker.start()
    try:
        failures = []
        failed = comm.dispatcher._failure

        def capture(cursor, row, error):
            failures.append((type(error).__name__, getattr(error, "code", None),
                [(os.path.basename(frame.filename), frame.lineno) for frame in traceback.extract_tb(error.__traceback__)]))
            return failed(cursor, row, error)

        comm.dispatcher._failure = capture
        submitted = send(comm, activation="invoke")["data"]
        result = comm.dispatcher.dispatch({"tenant_id": f.authority.tenant_id, "message_id": submitted["message_id"],
                                          "operation_id": submitted["operation_id"]})
        with f.authority._connect() as connection:
            state = connection.execute("SELECT last_error FROM delivery_messages WHERE message_id=%s", (submitted["message_id"],)).fetchone()
        assert result["status"] == ("uncertain" if lost_host_ack else "delivered"), (result, state, failures, calls)
        facades = {name: CommunicationClientService(client.service, client.credential_provider())
                   for name, client in comm.clients.items()}
        invocation, reason = facades["a"]._native_source_original(PROJECT, submitted["message_handle"])
        assert invocation is not None, reason
        registry = NativeProviderRegistry()
        admission = ProviderAdmission(provider_ref="enrolled-host-provider", native_authority="orca",
                                      selection=_original_selection(invocation))
        registry.register(admission, None, source_reader=RemoteNativeSourceReader(endpoint))
        for client in comm.clients.values():
            authority = client.service.service.authority
            authority._native_provider_registry = registry
            authority._communication_native_links_enabled = True
            authority._communication_native_link_settings = CommunicationNativeLinkSettings()
        owner["session"] = owner["session"] | {"sessionRef": "later-current-session", "generation": "later-generation"}
        owner["ownerToken"] = object()
        for name in ("a", "b"):
            read = facades[name].read_message(PROJECT, submitted["message_handle"], include_native_source=True)
            source = read["native_source"]
            assert source["available"], source
            assert source["value"]["messageHandle"] == submitted["message_handle"]
            assert source["value"]["operationId"] == submitted["operation_id"]
            assert source["value"]["nativeSession"]["sessionRef"] == "original-host-session"
            assert source["value"]["nativeInputRef"] == "original-host-input"
        assert [kind for kind, _operation in calls].count("admit") == 1
        assert [kind for kind, _operation in calls].count("read_original") == int(lost_host_ack)
        with pytest.raises(AuthorizationDenied):
            facades["c"].read_message(PROJECT, submitted["message_handle"], include_native_source=True)
        with f.authority._connect() as connection:
            assert connection.execute("SELECT count(*) FROM communication_replies").fetchone() == (0,)
            assert connection.execute("SELECT count(*) FROM delivery_attempts WHERE message_id=%s", (submitted["message_id"],)).fetchone() == (1,)
            connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                (facades["a"].project_service.context.grant_ref,))
        with pytest.raises(AuthorizationDenied):
            facades["a"].read_message(PROJECT, submitted["message_handle"], include_native_source=True)
        assert all(not driver.calls for driver in comm.drivers.values())
    finally:
        server.shutdown()
        worker.join(timeout=4)
        server.server_close()
        server.service.ledger.close()
        assert not worker.is_alive()
