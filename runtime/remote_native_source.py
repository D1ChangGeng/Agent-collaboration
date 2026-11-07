"""Trusted original-Receiver provenance reader; no filesystem locator or Host grant."""
from __future__ import annotations

from runtime.receiver_delivery import RemoteNodeEndpointAdapter


class RemoteNativeSourceReader:
    def __init__(self, endpoint):
        if not isinstance(endpoint, RemoteNodeEndpointAdapter):
            raise TypeError("an installed authenticated remote Receiver endpoint is required")
        self.endpoint = endpoint

    def read(self, invocation, provider):
        return self.endpoint.read_native_source(invocation, provider)
