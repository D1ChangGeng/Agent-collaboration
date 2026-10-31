"""Native observation and input-context invariants, independent of model output."""
from __future__ import annotations

import threading
from types import SimpleNamespace

from runtime.machine_connections import ConfiguredRemoteEndpoint


def test_offline_status_never_prepares_or_invokes():
    endpoint = object.__new__(ConfiguredRemoteEndpoint)
    endpoint._lock = threading.RLock()
    calls = []
    endpoint._adapter = lambda: SimpleNamespace(transport=SimpleNamespace(inspect_runtime=lambda: {"state": "offline"}))
    endpoint._prepare = lambda: calls.append("prepare")
    for _ in range(3):
        assert endpoint.inspect_runtime()["state"] == "offline"
    assert calls == []


def test_status_read_failure_is_unknown_transport_without_prepare():
    endpoint = object.__new__(ConfiguredRemoteEndpoint)
    endpoint._lock = threading.RLock()
    calls = []
    def unavailable():
        raise OSError("controlled transport unavailable")
    endpoint._adapter = unavailable
    endpoint._prepare = lambda: calls.append("prepare")
    assert endpoint.inspect_runtime()["state"] == "offline"
    assert calls == []


def test_natural_native_dispatch_does_not_start_a_terminal_collector():
    from runtime_deployment.receiver_codex import CodexReceiverCapacity
    capacity = object.__new__(CodexReceiverCapacity)
    invocation = SimpleNamespace(envelope=SimpleNamespace(packet=SimpleNamespace(schema_version="acs-message/1")))
    class Bridge:
        def _invocation(self, _admission):
            return invocation

        def __call__(self, _admission):
            return {"native_dispatch": "accepted"}
    capacity.bridge = Bridge()
    calls = []
    capacity._start_collector = lambda value: calls.append(value)
    assert capacity.native_invoke(object()) == {"native_dispatch": "accepted"}
    assert calls == []
