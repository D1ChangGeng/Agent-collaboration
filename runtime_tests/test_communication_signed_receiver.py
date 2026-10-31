"""Real PG/TLS/SQLite for natural packets; Native ACK is an explicit fixture."""

from __future__ import annotations

import json
import os
import threading

import pytest
from nacl.signing import SigningKey

from runtime.connection_clock import ClockUncertain, ConnectionClock
from runtime.delivery_models import EndpointBindingRequest
from runtime.enrollment_models import NodeEnrollment, RuntimeRegistration
from runtime.machine_connections import ConfiguredRemoteEndpoint
from runtime.receiver_config import ReceiverRuntimeConfig, receiver_clock_identity
from runtime.receiver_crypto import key_fingerprint, public_key, sign
from runtime.receiver_domain import (
    AuthorityTransportKeyRegistration,
    ConnectionReferenceRegistration,
    EndpointRegistrationCommand,
)
from runtime.receiver_models import EndpointBinding, EndpointRegistration, SignedRequest
from runtime.remote_endpoint import ReceiverHTTPServer, RemoteTransportRejected
from runtime.surface_config import PrivateReference, RemoteEndpointSettings
from runtime_tests.test_communication import call, send, wait
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_delivery import command as bind_command
from runtime_tests.test_receiver_domain_delivery import command, free_port
from runtime_tests.test_receiver_protocol import certificate

comm = comm_fixture


@pytest.mark.skipif(
    os.name != "posix", reason="this signed Receiver fixture uses POSIX private paths"
)
@pytest.mark.parametrize("ack_mode", ["immediate", "held", "offline"])
def test_natural_packet_round_trips_signed_admission_and_receipt_without_a_task_revision(
    comm, tmp_path, monkeypatch, ack_mode
):
    authority = comm.authority
    authority.access_mode = "owner"
    for client in comm.clients.values():
        client.service.service.authority.access_mode = "owner"
    node_key, authority_key = SigningKey.generate(), SigningKey.generate()
    private = tmp_path / "receiver"
    private.mkdir(mode=0o700)
    node_path = private / "node.seed"
    node_path.write_text(node_key.encode().hex())
    node_path.chmod(0o600)
    cert, tls_key, cert_digest = certificate(private)
    port = free_port()
    authority.enroll_node(
        command(authority, "node.enroll", "node", "signed-node"),
        NodeEnrollment(
            scope_id="local-scope",
            agent_slot_id="slot-b",
            observer_grant_ref=authority.context.grant_ref,
            machine_id="fixture-machine",
            boot_incarnation="fixture-boot",
            public_key=public_key(node_key),
        ),
    )
    authority.register_runtime(
        command(authority, "runtime.register", "runtime", "signed-runtime"),
        RuntimeRegistration(
            node_id="signed-node",
            node_binding_revision=1,
            provider="fixture-native-ack",
            producer_grant_ref=authority.context.grant_ref,
        ),
    )
    authority.register_authority_transport_key(
        command(authority, "receiver.key.register", "authority_transport_key", "signed-key"),
        AuthorityTransportKeyRegistration(
            key_id="signed-key", revision=1, public_key=public_key(authority_key)
        ),
    )
    authority.register_receiver_connection(
        command(authority, "receiver.connection.register", "connection", "signed-connection"),
        ConnectionReferenceRegistration(
            connection_ref="signed-connection",
            revision=1,
            locator_host="127.0.0.1",
            locator_port=port,
            route_class="loopback",
            policy_digest="a" * 64,
        ),
    )
    with authority._connect() as connection:
        node_key_id = connection.execute(
            "SELECT key_id FROM enrolled_node_keys WHERE node_id='signed-node'"
        ).fetchone()[0]
    context = authority.context
    registration = EndpointRegistration(
        registration_id="signed-registration",
        endpoint_id="signed-endpoint",
        endpoint_revision=1,
        connection_ref="signed-connection",
        tenant_id=context.tenant_id,
        authority_id=context.authority_id,
        authority_incarnation=context.authority_incarnation,
        node_id="signed-node",
        node_binding_revision=1,
        runtime_id="signed-runtime",
        runtime_revision=1,
        machine_id="fixture-machine",
        boot_incarnation="fixture-boot",
        scope_id="local-scope",
        agent_slot_id="slot-b",
        tls_certificate_sha256=cert_digest,
        config_sha256="c" * 64,
    )
    signature = sign(node_key, registration)
    authority.register_receiver_endpoint(
        command(authority, "endpoint.register", "endpoint", "signed-endpoint"),
        EndpointRegistrationCommand(registration=registration, registration_signature=signature),
    )
    binding = EndpointBinding(
        registration=registration,
        locator_host="127.0.0.1",
        locator_port=port,
        route_class="loopback",
        node_key_id=node_key_id,
        node_public_key=public_key(node_key),
        registration_signature=signature,
    )
    config = ReceiverRuntimeConfig(
        binding=binding,
        authority_key_id="signed-key",
        authority_key_revision=1,
        authority_public_key=public_key(authority_key),
        authority_public_key_fingerprint=key_fingerprint(public_key(authority_key)),
        expected_boot_incarnation="fixture-boot",
        journal_generation=1,
        access_mode="owner",
        tls_cert_path=str(cert),
        tls_key_path=str(tls_key),
        node_signing_key_path=str(node_path),
        ledger_path=str(private / "receiver.sqlite"),
    )
    calls = []
    release_ack = threading.Event()

    def native_ack_fixture(admission):
        calls.append(admission.dispatch_id)
        assert admission.accepted_revision is None
        if ack_mode == "held":
            assert release_ack.wait(20), "test must release its held Native ACK"
        return {"native_ack_ref": "fixture-ack"}

    clock = ConnectionClock.from_authority(authority, identity=receiver_clock_identity(config))

    def idle_fixture(_admission):
        return {
            "activity": "idle",
            "observed_at": authority.canonical_now().isoformat(),
            "expires_at": None,
        }

    class NativeAckFixture:
        def invoke(self, admission):
            return native_ack_fixture(admission)

        def health(self):
            raise ClockUncertain("controlled unavailable Native observation")

    server = ReceiverHTTPServer(
        config,
        node_key,
        authority.receiver_transport.current_authority,
        NativeAckFixture().invoke,
        native_readiness=idle_fixture,
        clock=clock,
    )
    server.daemon_threads = False  # Join test request workers before closing their ledger.
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        server.verify_presented_certificate()
        monkeypatch.setenv("ACS_SIGNED_FIXTURE_KEY", authority_key.encode().hex())
        adapter = ConfiguredRemoteEndpoint(
            authority,
            RemoteEndpointSettings(
                endpoint_id="signed-endpoint",
                authority_signing_key_ref=PrivateReference(
                    kind="environment", name="ACS_SIGNED_FIXTURE_KEY"
                ),
                request_timeout_seconds=1,
            ),
        )
        comm.dispatcher.service.endpoints["signed-endpoint"] = adapter
        authority._delivery_endpoints["signed-endpoint"] = adapter
        assert adapter.inspect_runtime()["state"] == "unknown"
        assert calls == [], "status cannot invoke Native"
        authority.bind_message_endpoint(
            bind_command(authority, "message.bind", "signed-endpoint"),
            EndpointBindingRequest(scope_id="local-scope", agent_slot_id="slot-b"),
        )
        call(
            comm,
            "a",
            "configure_team",
            prepare_native=False,
            members=[
                {
                    "agent_slot_id": "slot-b",
                    "principal_ref": "agent:b",
                    "endpoint_id": "signed-endpoint",
                }
            ],
        )
        sent = send(comm)["data"]
        if ack_mode == "offline":
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
            identity = {
                "tenant_id": context.tenant_id,
                "message_id": sent["message_id"],
                "operation_id": sent["operation_id"],
            }
            outcomes = []
            for _attempt in range(3):
                with authority._connect() as connection:
                    connection.execute(
                        "UPDATE delivery_messages SET next_attempt_at=clock_timestamp() WHERE message_id=%s",
                        (sent["message_id"],),
                    )
                outcomes.append(comm.dispatcher.dispatch(identity)["status"])
            assert outcomes[:2] == ["retry_wait", "retry_wait"] and outcomes[-1] in {
                "blocked",
                "budget_exhausted",
            }, outcomes
            assert calls == []
            with authority._connect() as connection:
                assert connection.execute(
                    "SELECT count(*) FROM delivery_attempts WHERE message_id=%s",
                    (sent["message_id"],),
                ).fetchone() == (3,)
                assert connection.execute(
                    "SELECT count(*) FROM delivery_transport_admissions"
                ).fetchone() == (0,)
            assert call(comm, "b", "read_message", handle=sent["message_handle"])["data"]["content"]
            return
        result = comm.dispatcher.dispatch(
            {
                "tenant_id": context.tenant_id,
                "message_id": sent["message_id"],
                "operation_id": sent["operation_id"],
            }
        )
        assert result["status"] == ("uncertain" if ack_mode == "held" else "delivered"), result
        assert len(calls) == 1
        with authority._connect() as connection:
            admissions = connection.execute(
                "SELECT accepted_revision,signed_request_json FROM delivery_transport_admissions "
                "WHERE operation_id=%s ORDER BY purpose",
                (sent["operation_id"],),
            ).fetchall()
            assert len(admissions) == (4 if ack_mode == "held" else 3) and all(
                row[0] is None for row in admissions
            )
            assert connection.execute("SELECT to_regclass('work_items')").fetchone() == (None,)
        for _revision, value in admissions:
            request = SignedRequest.model_validate_json(json.dumps(value), strict=True)
            receipt = adapter._adapter().transport.send(request)
            assert receipt.receipt.accepted_revision is None
            forged = receipt.receipt.model_copy(update={"accepted_revision": 0})
            with pytest.raises(RemoteTransportRejected, match="identity"):
                adapter._adapter().transport.validate_receipt(
                    request,
                    receipt.model_copy(
                        update={"receipt": forged, "signature": sign(node_key, forged)}
                    ),
                )
        assert len(calls) == 1, "replaying persisted signed requests must not invoke twice"
        assert (
            comm.dispatcher.dispatch(
                {
                    "tenant_id": context.tenant_id,
                    "message_id": sent["message_id"],
                    "operation_id": sent["operation_id"],
                }
            )["status"]
            == result["status"]
        )
        reply = send(
            comm,
            "b",
            "a",
            "Fixture peer replies explicitly",
            reply_to=[sent["message_handle"]],
            activation="message_only",
        )["data"]
        assert (
            wait(comm, "a", sent["message_handle"])["data"]["observations"][0]["reply"][
                "message_handle"
            ]
            == reply["message_handle"]
        )
    finally:
        release_ack.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        server.service.ledger.close()
