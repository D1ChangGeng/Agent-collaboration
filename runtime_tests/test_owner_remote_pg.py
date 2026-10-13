"""Owner project delivery crosses real PostgreSQL and pinned TLS exactly once.

The native completion callback is a fixture. Actual Harness evidence is separate.
"""
import base64
import hashlib
import json
import threading

import pytest
from datetime import UTC, datetime, timedelta

import psycopg
from nacl.signing import SigningKey

from runtime.delivery import DeliveryDispatcher
from runtime.delivery_models import EndpointBindingRequest
from runtime.enrollment_models import NodeEnrollment, RuntimeRegistration
from runtime.receiver_config import ReceiverRuntimeConfig
from runtime.receiver_crypto import key_fingerprint, public_key, sign
from runtime.receiver_delivery import RemoteNodeEndpointAdapter, RemoteSenderDeployment
from runtime.receiver_domain import (
    AuthorityTransportKeyRegistration,
    ConnectionReferenceRegistration,
    EndpointRegistrationCommand,
)
from runtime.receiver_models import EndpointBinding, EndpointRegistration
from runtime.remote_endpoint import ReceiverHTTPServer
from runtime_tests.test_project_service import send_args, work_args
from runtime_tests.test_receiver_domain_delivery import command, free_port
from runtime_tests.test_receiver_protocol import certificate

pytest_plugins = ("runtime_tests.test_project_service",)


@pytest.mark.parametrize("tamper", [False, True])
def test_owner_project_dispatch_uses_persistent_signed_receiver_after_old_expiry(project, tmp_path, tamper):
    f = project
    authority = f.authority
    authority.access_mode = "owner"
    node_key, authority_key = SigningKey.generate(), SigningKey.generate()
    private = tmp_path/"receiver"
    private.mkdir(mode=0o700)
    node_path = private/"node.seed"
    node_path.write_text(node_key.encode().hex())
    node_path.chmod(0o600)
    cert, tls_key, cert_digest = certificate(private)
    port = free_port()
    authority.enroll_node(command(authority, "node.enroll", "node", "owner-node"), NodeEnrollment(
        scope_id="local-scope", agent_slot_id="local-slot", observer_grant_ref=authority.context.grant_ref,
        machine_id="owner-machine", boot_incarnation="owner-boot", public_key=public_key(node_key)))
    authority.register_runtime(command(authority, "runtime.register", "runtime", "owner-runtime"),
        RuntimeRegistration(node_id="owner-node", node_binding_revision=1, provider="fixture-native",
                            producer_grant_ref=authority.context.grant_ref))
    authority.receiver_transport.register_authority_key(command(authority,"receiver.key.register","authority_transport_key","owner-key"),
        AuthorityTransportKeyRegistration(key_id="owner-key",revision=1,public_key=public_key(authority_key)))
    authority.receiver_transport.register_connection(command(authority,"receiver.connection.register","connection","owner-connection"),
        ConnectionReferenceRegistration(connection_ref="owner-connection",revision=1,locator_host="127.0.0.1",
                                        locator_port=port,route_class="loopback",policy_digest="a"*64))
    with authority._connect() as conn:
        node_key_id = conn.execute("SELECT key_id FROM enrolled_node_keys WHERE node_id='owner-node'").fetchone()[0]
    context = authority.context
    registration = EndpointRegistration(registration_id="owner-registration",endpoint_id="owner-endpoint",endpoint_revision=1,
        connection_ref="owner-connection",tenant_id=context.tenant_id,authority_id=context.authority_id,
        authority_incarnation=context.authority_incarnation,node_id="owner-node",node_binding_revision=1,
        runtime_id="owner-runtime",runtime_revision=1,machine_id="owner-machine",boot_incarnation="owner-boot",
        scope_id="local-scope",agent_slot_id="local-slot",tls_certificate_sha256=cert_digest,config_sha256="c"*64)
    signature = sign(node_key,registration)
    authority.receiver_transport.register_endpoint(command(authority,"endpoint.register","endpoint","owner-endpoint"),
        EndpointRegistrationCommand(registration=registration,registration_signature=signature))
    binding = EndpointBinding(registration=registration,locator_host="127.0.0.1",locator_port=port,route_class="loopback",
                             node_key_id=node_key_id,node_public_key=public_key(node_key),registration_signature=signature)
    config = ReceiverRuntimeConfig(binding=binding,authority_key_id="owner-key",authority_key_revision=1,
        authority_public_key=public_key(authority_key),authority_public_key_fingerprint=key_fingerprint(public_key(authority_key)),
        expected_boot_incarnation="owner-boot",journal_generation=1,access_mode="owner",tls_cert_path=str(cert),
        tls_key_path=str(tls_key),node_signing_key_path=str(node_path),ledger_path=str(private/"receiver.sqlite"))
    calls = []
    def invoke(admission):
        calls.append(admission.dispatch_id)
        return {"native_ack_ref":"fixture-native-ack"}
    def readiness(admission):
        return {"activity":"idle","observed_at":datetime.now(UTC).isoformat(),"expires_at":None}
    server = ReceiverHTTPServer(config,node_key,authority.receiver_transport.current_authority,invoke,native_readiness=readiness)
    worker = threading.Thread(target=server.serve_forever,daemon=True)
    worker.start()
    try:
        adapter = RemoteNodeEndpointAdapter(authority,"owner-endpoint",RemoteSenderDeployment(authority_key,"owner-boot"))
        f.service.endpoints["owner-endpoint"] = adapter
        authority._delivery_endpoints["owner-endpoint"] = adapter
        with psycopg.connect(f.dsn) as conn:
            conn.execute("UPDATE delivery_endpoints SET status='retired'")
        authority.bind_message_endpoint(command(authority,"message.bind","message","owner-endpoint"),
            EndpointBindingRequest(scope_id="local-scope",agent_slot_id="local-slot"))
        with psycopg.connect(f.dsn) as conn:
            for table in ("grants","enrolled_node_bindings","enrolled_runtimes","delivery_endpoint_registrations",
                          "authority_transport_keys","deployment_connection_refs","delivery_endpoints"):
                conn.execute("UPDATE "+table+" SET expires_at=%s",(datetime.now(UTC)-timedelta(days=1),))
        args = work_args()
        args.pop("deadline")
        assert f.projects.execute("create_work",args,f.credential)[0] == "created"
        sending = dict(send_args(),activation="invoke")
        sending.pop("deadline")
        sent = f.projects.execute("send_message",sending,f.credential)[1]
        with psycopg.connect(f.dsn) as conn:
            row = conn.execute("SELECT tenant_id,message_id,operation_id FROM delivery_messages").fetchone()
        outcome = DeliveryDispatcher(f.service).dispatch(dict(zip(("tenant_id","message_id","operation_id"),row, strict=True)))
        assert outcome["status"] == "delivered", outcome
        assert len(calls) == 1
        assert f.projects.execute("send_message",sending,f.credential)[1]["message_id"] == sent["message_id"]
        assert len(calls) == 1
        assert adapter.transport.inspect_runtime()["state"] == "online"
        # The fixture supplies terminal bytes. Real signatures, PG admission,
        # TLS, SQLite dedup and multi-chunk transfer run across this boundary.
        expected_bytes = json.dumps({"result":"fixture-terminal-response", "detail":"x"*70000}).encode()
        response_digest = hashlib.sha256(expected_bytes).hexdigest()
        operation_id = sent["operation_id"]
        read_calls = []
        class FixtureResponse:
            def invoke(self, admission):
                raise AssertionError("reading a result must not reinvoke native work")
            def read_response_artifact(self, admission, body):
                assert admission.operation_id == operation_id
                assert body.response_digest == response_digest
                read_calls.append(body.offset)
                data = expected_bytes[body.offset:body.offset+body.max_bytes]
                if tamper and body.offset == 0:
                    data = b"!" + data[1:]
                return {"sha256":response_digest,"offset":body.offset,"size_bytes":len(expected_bytes),
                        "data_base64":base64.b64encode(data).decode()}
        server._native_invoke = FixtureResponse().invoke
        if tamper:
            from runtime.delivery_node import DeliveryTransportError
            with pytest.raises(DeliveryTransportError, match="bytes differ"):
                adapter.fetch_response_artifact(operation_id,response_digest,max_bytes=100000)
        else:
            assert adapter.fetch_response_artifact(operation_id,response_digest,max_bytes=100000) == expected_bytes
            assert adapter.fetch_response_artifact(operation_id,response_digest,max_bytes=100000) == expected_bytes
            assert read_calls == [0,32768,65536]
        assert len(calls) == 1
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
