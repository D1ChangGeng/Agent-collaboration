"""Configured machine connections prepare and resolve current execution on demand."""
from __future__ import annotations

import subprocess
import threading
import time

from nacl.signing import SigningKey

from runtime.receiver_delivery import RemoteNodeEndpointAdapter, RemoteSenderDeployment


class ConfiguredRemoteEndpoint:
    def __init__(self, authority, settings):
        self.authority, self.settings = authority, settings
        self._lock = threading.RLock()
        self._bound = None
        self._fingerprint = None

    def _adapter(self):
        with self._lock:
            row = self.authority.receiver_transport.load_endpoint(self.settings.endpoint_id)["registration"]
            fingerprint = (row["endpoint_revision"], row["registration_sha256"])
            if self._bound is None or self._fingerprint != fingerprint:
                private = self.settings.authority_signing_key_ref.resolve()
                deployment = RemoteSenderDeployment(SigningKey(bytes.fromhex(private)), row["boot_incarnation"],
                    self.settings.journal_generation, self.settings.old_boot_isolation_ref)
                self._bound = RemoteNodeEndpointAdapter(self.authority, self.settings.endpoint_id, deployment)
                self._fingerprint = fingerprint
            return self._bound

    def _prepare(self):
        if self.settings.prepare_argv:
            completed = subprocess.run(list(self.settings.prepare_argv), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
            if completed.returncode:
                raise RuntimeError("machine execution preparation failed")
            self._bound = None

    def inspect_runtime(self):
        with self._lock:
            try:
                observed = self._adapter().transport.inspect_runtime()
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
                    observed = self._adapter().transport.inspect_runtime()
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
        if self.inspect_runtime()["state"] == "offline":
            raise RuntimeError("configured machine is offline")
        return self._adapter().deliver(*args, **kwargs)

    def fetch_response_artifact(self, *args, **kwargs):
        return self._adapter().fetch_response_artifact(*args, **kwargs)

    def inspect_delivery(self, *args, **kwargs):
        return self._adapter().inspect_delivery(*args, **kwargs)
