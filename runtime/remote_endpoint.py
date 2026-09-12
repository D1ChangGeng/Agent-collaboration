from __future__ import annotations

import http.client
import json
import socket
import ssl
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from nacl.signing import SigningKey

from runtime.receiver import ReceiverRejected, ReceiverService
from runtime.receiver_config import ReceiverRuntimeConfig
from runtime.receiver_crypto import load_owner_signing_key, sha256, tls_fingerprint, verify
from runtime.receiver_models import DeliveryAdmission, SignedReceipt, SignedRequest
from runtime.receiver_paths import PathSecurityRejected, validated_file_identity


class RemoteTransportRejected(RuntimeError):
    pass


class RemoteNodeTransport:
    def __init__(self, config: ReceiverRuntimeConfig, *, timeout: float = 5.0):
        config.validate()
        self.config = config
        self.timeout = timeout

    @staticmethod
    def _context():
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    def send(self, request: SignedRequest) -> SignedReceipt:
        registration = self.config.binding.registration
        connection = http.client.HTTPSConnection(
            self.config.binding.locator_host, self.config.binding.locator_port,
            context=self._context(), timeout=self.timeout,
        )
        try:
            connection.connect()
            certificate = connection.sock.getpeercert(binary_form=True)
            if tls_fingerprint(certificate) != registration.tls_certificate_sha256:
                raise RemoteTransportRejected("receiver TLS fingerprint rejected")
            encoded = request.model_dump_json().encode()
            if len(encoded) > self.config.maximum_body_bytes:
                raise RemoteTransportRejected("receiver request exceeds bound")
            connection.request(
                "POST", request.admission.path, body=encoded,
                headers={"Content-Type": "application/json", "Content-Length": str(len(encoded))},
            )
            response = connection.getresponse()
            raw = response.read(self.config.maximum_body_bytes + 1)
            if response.status != 200 or len(raw) > self.config.maximum_body_bytes:
                raise RemoteTransportRejected(f"receiver rejected request with status {response.status}")
            receipt = SignedReceipt.model_validate_json(raw, strict=True)
            self.validate_receipt(request, receipt)
            return receipt
        finally:
            connection.close()

    def validate_receipt(self, request: SignedRequest, receipt: SignedReceipt) -> None:
        verify(self.config.binding.node_public_key, receipt.signature, receipt.receipt)
        admission = request.admission
        observed = receipt.receipt
        expected_hash = sha256({
            "admission": admission.model_dump(mode="json"), "body": request.body,
        })
        expected = (
            self.config.binding.node_key_id,
            f"receiver:{admission.request_id}:{observed.state}",
            admission.request_id, admission.nonce,
            admission.purpose, admission.tenant_id, admission.authority_id,
            admission.authority_incarnation, admission.message_id, admission.command_id,
            admission.operation_id, admission.attempt_id, admission.dispatch_id,
            admission.endpoint_id, admission.endpoint_revision, admission.runtime_id,
            admission.runtime_revision, admission.node_id,
            self.config.binding.registration.node_binding_revision, admission.machine_id,
            admission.boot_incarnation, admission.scope_id, admission.agent_slot_id,
            admission.accepted_revision, admission.accepted_state_digest,
            admission.envelope_digest, admission.selection_digest, admission.invocation_digest,
            admission.journal_generation, expected_hash,
        )
        actual = (
            receipt.node_key_id, observed.receipt_id, observed.request_id,
            observed.challenge_nonce, observed.purpose,
            observed.tenant_id, observed.authority_id, observed.authority_incarnation,
            observed.message_id, observed.command_id, observed.operation_id, observed.attempt_id,
            observed.dispatch_id, observed.endpoint_id, observed.endpoint_revision,
            observed.runtime_id, observed.runtime_revision, observed.node_id,
            observed.node_binding_revision, observed.machine_id, observed.boot_incarnation,
            observed.scope_id, observed.agent_slot_id, observed.accepted_revision,
            observed.accepted_state_digest, observed.envelope_digest, observed.selection_digest,
            observed.invocation_digest, observed.journal_generation, observed.request_sha256,
        )
        states = {
            "delivery.prepare": {"prepared"},
            "delivery.dispatch": {"runtime_dispatched", "runtime_acknowledged", "uncertain", "blocked"},
            "delivery.recover": {"runtime_dispatched", "runtime_acknowledged", "uncertain", "blocked"},
            "delivery.readback": {"readback"},
        }
        skew = self.config.clock_skew_seconds
        links_ok = (
            observed.readback_request_id == admission.request_id
            and observed.target_request_id == observed.evidence.get("target_request_id")
            if admission.purpose == "delivery.readback"
            else observed.readback_request_id is None
            and observed.target_request_id == admission.request_id
        )
        if (actual != expected or observed.state not in states[admission.purpose]
                or not links_ok
                or observed.observed_at < admission.issued_at - timedelta(seconds=skew)
                or observed.observed_at > admission.deadline + timedelta(seconds=skew)):
            raise RemoteTransportRejected("receiver receipt identity rejected")


class ReceiverHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, config: ReceiverRuntimeConfig, node_signing_key: SigningKey,
                 authorize_current, native_invoke):
        if not callable(native_invoke):
            raise RemoteTransportRejected("receiver native adapter callback is required")
        config.validate()
        try:
            cert_identity = validated_file_identity(config.tls_cert_path, private=False)
            key_identity = validated_file_identity(config.tls_key_path, private=True)
        except PathSecurityRejected:
            raise RemoteTransportRejected("receiver TLS path admission rejected") from None
        self.config = config
        self._native_invoke = native_invoke
        self.service = ReceiverService(
            config, node_signing_key, authorize_current=authorize_current,
        )
        self.service.claim_boot(
            config.expected_boot_incarnation, config.journal_generation,
            old_boot_isolation_ref=config.old_boot_isolation_ref,
        )
        super().__init__((config.binding.locator_host, config.binding.locator_port), ReceiverHandler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.load_cert_chain(config.tls_cert_path, config.tls_key_path)
        try:
            if (validated_file_identity(config.tls_cert_path, private=False) != cert_identity
                    or validated_file_identity(config.tls_key_path, private=True) != key_identity):
                raise RemoteTransportRejected("receiver TLS identity changed while loading")
        except PathSecurityRejected:
            raise RemoteTransportRejected("receiver TLS path admission rejected") from None
        self.socket = context.wrap_socket(self.socket, server_side=True)

    def verify_presented_certificate(self):
        context = RemoteNodeTransport._context()
        with (socket.create_connection(self.server_address, timeout=5) as raw,
              context.wrap_socket(raw, server_hostname="receiver") as tls):
            observed = tls_fingerprint(tls.getpeercert(binary_form=True))
        if observed != self.config.binding.registration.tls_certificate_sha256:
            raise RemoteTransportRejected("receiver startup TLS fingerprint readback rejected")

    def native_invoke(self, admission: DeliveryAdmission) -> dict[str, Any]:
        return self._native_invoke(admission)


class ReceiverHandler(BaseHTTPRequestHandler):
    server: ReceiverHTTPServer

    def do_POST(self):
        try:
            if self.headers.get("Content-Type") != "application/json":
                raise ReceiverRejected("content type rejected")
            length = int(self.headers.get("Content-Length", "-1"))
            if not 0 <= length <= self.server.config.maximum_body_bytes:
                raise ReceiverRejected("body length rejected")
            raw = self.rfile.read(length)
            request = SignedRequest.model_validate_json(raw, strict=True)
            if request.admission.path != self.path:
                raise ReceiverRejected("request path rejected")
            receipt = self.server.service.handle(request, self.server.native_invoke)
            encoded = receipt.model_dump_json().encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        except (ReceiverRejected, ValueError, KeyError, json.JSONDecodeError):
            encoded = b'{"status":"rejected"}'
            self.send_response(409)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    def log_message(self, format, *args):
        return


def fixture_authority_current(_admission):
    """Explicit test callback; production startup must inject a Domain readback."""
    return True


def serve(config: ReceiverRuntimeConfig, ready=None, authorize_current=None, native_invoke=None,
          ready_check=None):
    if not callable(authorize_current):
        raise RemoteTransportRejected("receiver current-authority callback is required")
    server = ReceiverHTTPServer(
        config, load_owner_signing_key(config.node_signing_key_path), authorize_current, native_invoke,
    )
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
    worker.start()
    try:
        server.verify_presented_certificate()
        if ready_check is not None and ready_check() is not True:
            raise RemoteTransportRejected("receiver deployment policy readiness check rejected")
        if ready is not None:
            ready.set()
        worker.join()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
