"""Configured machine connections prepare and resolve current execution on demand."""
from __future__ import annotations

import json
import subprocess
import threading
import time
from datetime import datetime

from nacl.signing import SigningKey

from runtime.delivery_node import DeliveryTransportError
from runtime.receiver_config import ReceiverClientConfig
from runtime.receiver_crypto import sha256
from runtime.receiver_delivery import RemoteNodeEndpointAdapter, RemoteSenderDeployment
from runtime.receiver_models import EndpointRegistration
from runtime.remote_endpoint import RemotePeerChanged


class ConfiguredRemoteEndpoint:
    def __init__(self, authority, settings, *, settings_provider=None):
        self.authority, self.settings = authority, settings
        self._settings_provider = settings_provider
        self._lock = threading.RLock()
        self._bound = None
        self._fingerprint = None

    def _refresh_settings(self):
        if self._settings_provider is None:
            return
        current = self._settings_provider(self.settings.endpoint_id)
        if current.endpoint_id != self.settings.endpoint_id:
            raise ValueError("configured endpoint identity changed")
        if current != self.settings:
            self.settings = current
            self._bound = None
            self._fingerprint = None

    def _adapter(self):
        with self._lock:
            try:
                self._refresh_settings()
                fingerprint, committed, key, signing = self._peer_snapshot()
                if (self._bound is not None and self._fingerprint == fingerprint
                        and self._matches_peer(self._bound, committed, key)):
                    return self._bound
                self._bound = self._fingerprint = None
                row = committed["registration"]
                deployment = RemoteSenderDeployment(signing, row["boot_incarnation"],
                    self.settings.journal_generation, self.settings.old_boot_isolation_ref)
                candidate = RemoteNodeEndpointAdapter(self.authority, self.settings.endpoint_id, deployment,
                    timeout=self.settings.request_timeout_seconds)
                current, _committed, _key, _signing = self._peer_snapshot()
                if current != fingerprint or not self._matches_peer(candidate, committed, key):
                    raise RemotePeerChanged("receiver peer changed during binding")
                self._bound, self._fingerprint = candidate, fingerprint
                return candidate
            except Exception:
                # A failed refresh cannot fall back to an older authenticated
                # connection. Other endpoints have independent locks/caches.
                self._bound = self._fingerprint = None
                raise

    def _peer_snapshot(self):
        store = self.authority.receiver_transport
        committed = store.load_endpoint(self.settings.endpoint_id)
        load_key = getattr(store, "load_authority_key", None)
        key = load_key() if callable(load_key) else None
        if not isinstance(key, dict):
            raise RemotePeerChanged("current receiver Authority key is unavailable")
        signing = SigningKey(bytes.fromhex(self.settings.authority_signing_key_ref.resolve()))
        public = signing.verify_key.encode().hex()
        if key.get("public_key") != public:
            raise RemotePeerChanged("configured receiver signing key differs from current Authority key")
        material = {"committed": committed, "authority_key": key, "sender_public_key": public,
            "settings": {name: getattr(self.settings, name) for name in (
                "endpoint_id", "journal_generation", "old_boot_isolation_ref", "request_timeout_seconds", "prepare_argv", "lifecycle_control")},
            "access_mode": getattr(self.authority, "access_mode", "unknown")}

        def encode(value):
            if isinstance(value, datetime):
                return value.isoformat()
            raise TypeError("receiver peer metadata is not serializable")

        fingerprint = sha256(json.dumps(material, sort_keys=True, separators=(",", ":"),
                                         default=encode, allow_nan=False).encode())
        return fingerprint, committed, key, signing

    def _matches_peer(self, adapter, committed, key):
        config = getattr(adapter, "config", None)
        if not isinstance(config, ReceiverClientConfig):
            return False
        if config.access_mode != getattr(self.authority, "access_mode", config.access_mode):
            return False
        row, connection = committed["registration"], committed["connection"]
        binding = config.binding
        registration = EndpointRegistration.model_validate_json(json.dumps(row["registration_json"]), strict=True)
        expected = (registration.model_dump(mode="json"), connection["locator_host"], connection["locator_port"],
            connection["route_class"], row["node_key_id"], committed["node_public_key"], row["registration_signature"],
            row["boot_incarnation"], self.settings.journal_generation, self.settings.old_boot_isolation_ref)
        actual = (binding.registration.model_dump(mode="json"), binding.locator_host, binding.locator_port,
            binding.route_class, binding.node_key_id, binding.node_public_key, binding.registration_signature,
            config.expected_boot_incarnation, config.journal_generation, config.old_boot_isolation_ref)
        if actual != expected:
            return False
        return (config.authority_key_id, config.authority_key_revision,
            config.authority_public_key, config.authority_public_key_fingerprint) == (
                key["key_id"], key["revision"], key["public_key"], key["fingerprint"])

    def _prepare(self):
        self._refresh_settings()
        if self.settings.prepare_argv:
            completed = subprocess.run(list(self.settings.prepare_argv), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
            if completed.returncode:
                raise RuntimeError("machine execution preparation failed")
            self._bound = None
            self._fingerprint = None

    def inspect_runtime(self):
        """Observe only: a status query cannot prepare a service or native turn."""
        with self._lock:
            try:
                return self._inspect_current()
            except RemotePeerChanged:
                return {"state": "unknown", "harness": "unknown", "version": "unknown",
                        "session_ref": None, "peer_verification": "changed"}
            except (OSError, ValueError, RuntimeError):
                return {"state": "offline", "harness": "unknown", "version": "unknown"}

    def _inspect_current(self):
        adapter = self._adapter()
        expected = getattr(self, "_fingerprint", None)
        observed = adapter.transport.inspect_runtime()
        if expected is not None:
            try:
                self._refresh_settings()
                current, _committed, _key, _signing = self._peer_snapshot()
                if current != expected:
                    raise RemotePeerChanged("receiver peer changed during readback")
            except Exception:
                self._bound = self._fingerprint = None
                raise
        return observed

    def prepare_runtime(self):
        """Explicitly prepare a configured receiver before authorized delivery."""
        with self._lock:
            try:
                observed = self._inspect_current()
                if observed.get("state") != "offline":
                    return observed
            except (OSError, ValueError, RuntimeError):
                pass
            self._prepare()
            # Service-manager acknowledgement can precede native initialization.
            # This is an internal preparation budget measured by local duration.
            end = time.monotonic() + (10 if self.settings.prepare_argv else 0)
            while True:
                try:
                    observed = self._inspect_current()
                    if observed.get("state") != "offline":
                        return observed
                except (OSError, ValueError, RuntimeError):
                    pass
                if time.monotonic() >= end:
                    return {"state":"offline", "harness":"unknown", "version":"unknown"}
                time.sleep(min(0.25,max(0,end-time.monotonic())))

    def descriptor(self):
        return self._adapter().descriptor()

    def deliver(self, *args, **kwargs):
        if self.prepare_runtime()["state"] == "offline":
            raise DeliveryTransportError("configured_machine_offline")
        return self._adapter().deliver(*args, **kwargs)

    def filesystem(self, context, operation, arguments):
        from runtime.filesystem_transport import node_request
        try:
            return node_request(self._adapter(), context, operation, arguments)
        except Exception as error:
            from runtime.machine_filesystem import FilesystemError
            if not isinstance(error, FilesystemError) or error.code != "machine_offline":
                raise
            # File service preparation is independent of native Session busy/idle.
            self._prepare()
            return node_request(self._adapter(), context, operation, arguments)

    def fetch_response_artifact(self, *args, **kwargs):
        return self._adapter().fetch_response_artifact(*args, **kwargs)

    def inspect_delivery(self, *args, **kwargs):
        return self._adapter().inspect_delivery(*args, **kwargs)
