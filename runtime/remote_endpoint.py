from __future__ import annotations

import http.client
import json
import math
import signal
import socket
import ssl
import threading
import time
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from nacl.signing import SigningKey

from runtime.connection_clock import ClockUnavailable, ConnectionClock
from runtime.lifetimes import earliest
from runtime.opencode_http import _DeadlineResponse
from runtime.receiver import ReceiverRejected, ReceiverService
from runtime.receiver_config import (
    ReceiverClientConfig,
    ReceiverRuntimeConfig,
    resolve_connection_clock,
)
from runtime.receiver_crypto import load_owner_signing_key, sha256, tls_fingerprint, verify
from runtime.receiver_models import DeliveryAdmission, SignedReceipt, SignedRequest
from runtime.receiver_paths import PathSecurityRejected, validated_file_identity


class RemoteTransportRejected(RuntimeError):
    pass


class RemotePeerChanged(RemoteTransportRejected):
    """The reachable peer/configuration cannot establish the expected identity."""


PEER_PROTOCOL = "acs-receiver-peer/1"


def receiver_peer_identity(config: ReceiverClientConfig) -> str:
    """Opaque common receiver context; no local paths, private keys or messages."""
    return sha256({"protocol": PEER_PROTOCOL, "binding": config.binding.model_dump(mode="json"),
        "authority_key_id": config.authority_key_id, "authority_key_revision": config.authority_key_revision,
        "authority_public_key": config.authority_public_key,
        "authority_public_key_fingerprint": config.authority_public_key_fingerprint,
        "expected_boot_incarnation": config.expected_boot_incarnation,
        "journal_generation": config.journal_generation, "old_boot_isolation_ref": config.old_boot_isolation_ref,
        "access_mode": config.access_mode})


def _request_budget(connection, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("receiver transport request duration expired")
    connection.timeout = remaining
    if connection.sock is not None:
        connection.sock.settimeout(remaining)


class RemoteNodeTransport:
    def __init__(self, config: ReceiverClientConfig, *, timeout: float = 5.0,
                 clock: ConnectionClock | None = None):
        config.validate()
        self.config = config
        self.clock = resolve_connection_clock(config, clock)
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or not 0 < timeout <= 120):
            raise ValueError("receiver request timeout must be finite and within 120 seconds")
        self.timeout = timeout
        self._peer_identity = receiver_peer_identity(config)
        self._bound_clock = self.clock
        self._clock_identity = dict(self.clock.identity)
        self._limits = (config.maximum_body_bytes, config.clock_skew_seconds)

    def _assert_peer(self):
        if (receiver_peer_identity(self.config) != self._peer_identity or self.clock is not self._bound_clock
                or self.clock.identity != self._clock_identity
                or (self.config.maximum_body_bytes, self.config.clock_skew_seconds) != self._limits
                or isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float))
                or not math.isfinite(self.timeout) or not 0 < self.timeout <= 120):
            raise RemotePeerChanged("receiver transport binding changed; reconnect explicitly")

    @staticmethod
    def _context():
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    def send(self, request: SignedRequest) -> SignedReceipt:
        self._assert_peer()
        registration = self.config.binding.registration
        try:
            self.clock.require_before(earliest(request.admission.deadline, None if self.config.access_mode == "owner" else registration.expires_at))
        except ClockUnavailable as error:
            raise RemoteTransportRejected("receiver transport Authority time is unavailable or expired") from error
        connection = http.client.HTTPSConnection(
            self.config.binding.locator_host, self.config.binding.locator_port,
            context=self._context(), timeout=self.timeout,
        )
        deadline = time.monotonic() + self.timeout
        connection.response_class = partial(_DeadlineResponse, deadline=deadline)
        try:
            _request_budget(connection, deadline)
            connection.connect()
            certificate = connection.sock.getpeercert(binary_form=True)
            if tls_fingerprint(certificate) != registration.tls_certificate_sha256:
                raise RemotePeerChanged("receiver TLS fingerprint rejected")
            encoded = request.model_dump_json().encode()
            if len(encoded) > self.config.maximum_body_bytes:
                raise RemoteTransportRejected("receiver request exceeds bound")
            self._assert_peer()
            _request_budget(connection, deadline)
            connection.request(
                "POST", request.admission.path, body=encoded,
                headers={"Content-Type": "application/json", "Content-Length": str(len(encoded))},
            )
            _request_budget(connection, deadline)
            response = connection.getresponse()
            raw = response.read(self.config.maximum_body_bytes + 1)
            _request_budget(connection, deadline)
            if response.status != 200 or len(raw) > self.config.maximum_body_bytes:
                raise RemoteTransportRejected(f"receiver rejected request with status {response.status}")
            receipt = SignedReceipt.model_validate_json(raw, strict=True)
            self.validate_receipt(request, receipt)
            return receipt
        except (
            OSError, TimeoutError, ssl.SSLError, http.client.HTTPException,
            ValueError,
        ) as error:
            raise RemoteTransportRejected("receiver transport acknowledgement unavailable") from error
        finally:
            connection.close()

    def inspect_runtime(self):
        self._assert_peer()
        try:
            self.clock.require_before(None if self.config.access_mode == "owner" else self.config.binding.registration.expires_at)
        except ClockUnavailable as error:
            raise RemoteTransportRejected("receiver health Authority time unavailable or expired") from error
        connection = http.client.HTTPSConnection(self.config.binding.locator_host,
            self.config.binding.locator_port, context=self._context(), timeout=self.timeout)
        deadline = time.monotonic() + self.timeout
        connection.response_class = partial(_DeadlineResponse, deadline=deadline)
        try:
            _request_budget(connection, deadline)
            connection.connect()
            if tls_fingerprint(connection.sock.getpeercert(binary_form=True)) != self.config.binding.registration.tls_certificate_sha256:
                raise RemotePeerChanged("receiver TLS fingerprint rejected")
            self._assert_peer()
            _request_budget(connection, deadline)
            connection.request("GET", "/healthz")
            _request_budget(connection, deadline)
            response = connection.getresponse()
            data = response.read(16385)
            _request_budget(connection, deadline)
            if response.status != 200 or len(data) > 16384:
                raise RemoteTransportRejected("receiver health readback unavailable")
            value = json.loads(data)
            if not isinstance(value, dict) or value.get("state") not in {"idle", "busy", "online", "unknown", "offline"}:
                raise RemoteTransportRejected("receiver health state rejected")
            self._assert_peer()
            if "peer_identity" not in value:
                return {"state": "unknown", "harness": "unknown", "version": "unknown",
                        "session_ref": None, "peer_verification": "unavailable"}
            if value.get("peer_protocol") != PEER_PROTOCOL or value["peer_identity"] != self._peer_identity:
                raise RemotePeerChanged("receiver health belongs to a different peer generation")
            value["peer_verification"] = "current"
            return value
        finally:
            connection.close()

    def exchange_lifecycle(self, path, encoded, valid_until):
        """Bounded lifecycle bytes over this same registered TLS-pinned peer."""
        from runtime.receiver_lifecycle_transport import PATHS

        self._assert_peer()
        if path not in PATHS or type(encoded) is not bytes or len(encoded) > self.config.maximum_body_bytes:
            raise RemoteTransportRejected("lifecycle wire bounds rejected")
        registration = self.config.binding.registration
        self.clock.require_before(earliest(valid_until,
            None if self.config.access_mode == "owner" else registration.expires_at))
        connection = http.client.HTTPSConnection(self.config.binding.locator_host, self.config.binding.locator_port,
            context=self._context(), timeout=self.timeout)
        deadline = time.monotonic() + self.timeout
        connection.response_class = partial(_DeadlineResponse, deadline=deadline)
        try:
            _request_budget(connection, deadline)
            connection.connect()
            if tls_fingerprint(connection.sock.getpeercert(binary_form=True)) != registration.tls_certificate_sha256:
                raise RemotePeerChanged("receiver lifecycle TLS fingerprint rejected")
            self._assert_peer()
            self.clock.require_before(valid_until)
            _request_budget(connection, deadline)
            connection.request("POST", path, body=encoded,
                headers={"Content-Type": "application/json", "Content-Length": str(len(encoded))})
            _request_budget(connection, deadline)
            response = connection.getresponse()
            raw = response.read(self.config.maximum_body_bytes + 1)
            _request_budget(connection, deadline)
            self._assert_peer()
            if response.status != 200 or len(raw) > self.config.maximum_body_bytes:
                raise RemoteTransportRejected("receiver lifecycle response rejected")
            return raw
        except (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException, ValueError) as error:
            raise RemoteTransportRejected("receiver lifecycle observation unavailable") from error
        finally:
            connection.close()

    def validate_receipt(self, request: SignedRequest, receipt: SignedReceipt) -> None:
        self._assert_peer()
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
            "delivery.readiness": {"readiness"},
        }
        links_ok = (
            observed.readback_request_id == admission.request_id
            and observed.target_request_id == observed.evidence.get("target_request_id")
            if admission.purpose == "delivery.readback"
            else observed.readback_request_id is None
            and observed.target_request_id == admission.request_id
        )
        if (actual != expected or observed.state not in states[admission.purpose]
                or not links_ok
                or not self.clock.fresh(observed.observed_at, None if self.config.access_mode == "owner" else admission.deadline)):
            raise RemoteTransportRejected("receiver receipt identity rejected")


class ReceiverHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, config: ReceiverRuntimeConfig, node_signing_key: SigningKey,
                 authorize_current, native_invoke, shutdown_callback=None, native_readiness=None,
                 clock: ConnectionClock | None = None, lifecycle_node=None, *, receiver_router_factory=None,
                 authorize_source_read=None):
        if not callable(native_invoke):
            raise RemoteTransportRejected("receiver native adapter callback is required")
        if authorize_source_read is not None and not callable(authorize_source_read):
            raise TypeError("current technical-source read authority must be a trusted callback")
        config.validate()
        try:
            cert_identity = validated_file_identity(config.tls_cert_path, private=False)
            key_identity = validated_file_identity(config.tls_key_path, private=True)
        except PathSecurityRejected:
            raise RemoteTransportRejected("receiver TLS path admission rejected") from None
        self.config = config
        from runtime.receiver_lifecycle_transport import LifecycleReceiverRouter

        self.lifecycle = LifecycleReceiverRouter(config, lifecycle_node) if lifecycle_node is not None else None
        self._native_invoke = native_invoke
        self.native_readiness = native_readiness
        self._shutdown_callback = shutdown_callback
        self._fault_lock = threading.Lock()
        self._response_fault_used = False
        self.service = ReceiverService(
            config, node_signing_key, authorize_current=authorize_current, clock=clock,
            authorize_source_read=(authorize_source_read if authorize_source_read is not None else
                getattr(getattr(native_invoke, "__self__", None), "authorize_native_source_read", None)),
        )
        from runtime.filesystem_transport import NodeFilesystemService
        provider = getattr(native_invoke, "__self__", None)
        authority = getattr(provider, "authority", None)
        file_authority = (authority.receiver_transport.current_filesystem_authority
                          if authority is not None else None)
        self.filesystem = (NodeFilesystemService(config, node_signing_key, file_authority)
                           if config.access_mode == "owner" and callable(file_authority) else None)
        self.service.claim_boot(
            config.expected_boot_incarnation, config.journal_generation,
            old_boot_isolation_ref=config.old_boot_isolation_ref,
        )
        self.receiver_router = None
        if receiver_router_factory is not None:
            from runtime.orca_receiver_backend import OrcaReceiverRouter

            if not callable(receiver_router_factory):
                raise TypeError("a trusted Host Receiver router factory is required")
            router = receiver_router_factory(self.service)
            if not isinstance(router, OrcaReceiverRouter) or router.backend.service is not self.service:
                raise TypeError("the Host router must use this existing Receiver service and ledger")
            self.receiver_router = router
        listen = (
            config.listen_host or config.binding.locator_host,
            config.listen_port or config.binding.locator_port,
        )
        super().__init__(listen, ReceiverHandler)
        # A disconnected peer can disappear after selector readiness.
        self.socket.settimeout(0.5)
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
        self._tls_context = context

    def get_request(self):
        raw, address = self.socket.accept()
        raw.settimeout(2)
        try:
            secured = self._tls_context.wrap_socket(raw, server_side=True)
            secured.settimeout(5)
            return secured, address
        except BaseException:
            raw.close()
            raise

    def verify_presented_certificate(self):
        context = RemoteNodeTransport._context()
        with (socket.create_connection(self.server_address, timeout=5) as raw,
              context.wrap_socket(raw, server_hostname="receiver") as tls):
            observed = tls_fingerprint(tls.getpeercert(binary_form=True))
        if observed != self.config.binding.registration.tls_certificate_sha256:
            raise RemoteTransportRejected("receiver startup TLS fingerprint readback rejected")

    def native_invoke(self, admission: DeliveryAdmission) -> dict[str, Any]:
        return self._native_invoke(admission)

    def close_runtime(self) -> None:
        if self._shutdown_callback is not None:
            self._shutdown_callback()

    def drop_response(self, purpose: str) -> bool:
        with self._fault_lock:
            if (
                self._response_fault_used
                or self.config.drop_response_after_commit_once != purpose
            ):
                return False
            self._response_fault_used = True
            return True


class ReceiverHandler(BaseHTTPRequestHandler):
    server: ReceiverHTTPServer

    def do_GET(self):
        if self.path != "/healthz":
            self.send_error(404)
            return
        provider = getattr(getattr(self.server._native_invoke, "__self__", None), "health", None)
        try:
            value = provider() if callable(provider) else {"state": "online", "harness": "unknown", "version": "unknown"}
        except Exception:  # noqa: BLE001 -- health output never contains private errors
            value = {"state": "unknown", "harness": "unknown", "version": "unknown"}
        if not isinstance(value, dict):
            value = {"state": "unknown", "harness": "unknown", "version": "unknown"}
        value = {**value, "peer_protocol": PEER_PROTOCOL, "peer_identity": receiver_peer_identity(self.server.config)}
        encoded = json.dumps(value).encode()
        if len(encoded) > 16384:
            encoded = json.dumps({"state": "unknown", "harness": "unknown", "version": "unknown",
                "peer_protocol": PEER_PROTOCOL, "peer_identity": value["peer_identity"]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self):
        try:
            if self.headers.get("Content-Type") != "application/json":
                raise ReceiverRejected("content type rejected")
            length = int(self.headers.get("Content-Length", "-1"))
            if not 0 <= length <= self.server.config.maximum_body_bytes:
                raise ReceiverRejected("body length rejected")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ReceiverRejected("request body incomplete")
            if self.path.startswith("/v1/lifecycle/"):
                if self.server.lifecycle is None:
                    raise ReceiverRejected("lifecycle port is unavailable")
                try:
                    result = self.server.lifecycle.handle(self.path, raw)
                except Exception:  # noqa: BLE001 - do not expose private Core/Node failures on the wire.
                    raise ReceiverRejected("lifecycle request rejected") from None
                encoded = result.model_dump_json().encode()
                if len(encoded) > self.server.config.maximum_body_bytes:
                    raise ReceiverRejected("lifecycle response exceeds bound")
                if self.server.drop_response(self.path):
                    self.close_connection = True
                    self.connection.close()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                return
            if self.path == "/v1/filesystem":
                from runtime.machine_filesystem import FilesystemError
                if self.server.filesystem is None:
                    raise ReceiverRejected("machine file service is unavailable")
                try:
                    value = self.server.filesystem.handle(json.loads(raw))
                except FilesystemError as error:
                    encoded = json.dumps({"status": "rejected", "code": error.code}).encode()
                    self.send_response(409)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                    return
                encoded = json.dumps(value).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                return
            request = SignedRequest.model_validate_json(raw, strict=True)
            if request.admission.path != self.path:
                raise ReceiverRejected("request path rejected")
            receipt = (self.server.receiver_router.handle(request) if self.server.receiver_router is not None else
                       self.server.service.handle(request, self.server.native_invoke,
                                                 native_readiness=self.server.native_readiness,
                                                 response_reader=getattr(getattr(self.server._native_invoke, "__self__", None), "read_response_artifact", None),
                                                 native_source_reader=getattr(getattr(self.server._native_invoke, "__self__", None), "read_native_source", None)))
            if self.server.drop_response(request.admission.purpose):
                self.close_connection = True
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.connection.close()
                return
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
          ready_check=None, shutdown_callback=None, native_readiness=None, clock: ConnectionClock | None = None,
          lifecycle_node=None):
    if not callable(authorize_current):
        raise RemoteTransportRejected("receiver current-authority callback is required")
    server = ReceiverHTTPServer(
        config, load_owner_signing_key(config.node_signing_key_path), authorize_current,
        native_invoke, shutdown_callback, native_readiness, clock=clock, lifecycle_node=lifecycle_node,
    )
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
    worker.start()
    previous_handlers = {}
    stop_requested = False
    if threading.current_thread() is threading.main_thread():
        def stop(_signum, _frame):
            nonlocal stop_requested
            stop_requested = True

        for name in ("SIGTERM", "SIGINT"):
            number = getattr(signal, name, None)
            if number is not None:
                previous_handlers[number] = signal.signal(number, stop)
    try:
        server.verify_presented_certificate()
        if ready_check is not None and ready_check() is not True:
            raise RemoteTransportRejected("receiver deployment policy readiness check rejected")
        if ready is not None:
            ready.set()
        while worker.is_alive() and not stop_requested:
            worker.join(timeout=0.1)
    finally:
        try:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
            server.close_runtime()
        finally:
            for number, previous in previous_handlers.items():
                signal.signal(number, previous)
