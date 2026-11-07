"""Real Driver/socket protocols with synthetic peers; not installed-Harness qualification."""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from runtime.native_delivery import NativeDeliveryAdapter
from runtime.receiver_contract import ReceiverBinding, input_decision
from runtime.receiver_evidence import project_receiver
from runtime_tests import test_codex_driver as codex
from runtime_tests import test_opencode_driver as opencode


@pytest.fixture(params=("codex", "opencode"))
def receiver(request, tmp_path, monkeypatch):
    module = codex if request.param == "codex" else opencode
    profile = module.profile.__wrapped__(tmp_path)
    args = (tmp_path, profile, monkeypatch) if module is codex else (tmp_path, profile)
    with contextmanager(module.native.__wrapped__)(*args) as state:
        driver = state.driver
        driver.spawn(module.operation("receiver-contract-spawn"))
        adapter = NativeDeliveryAdapter(driver, authorize_invocation=lambda *_: None,
            inspect_runtime=lambda: driver.inspect(module.operation("receiver-contract-observe")))
        binding = ReceiverBinding(receiver_id="fixture-receiver", actor_address="collaborator:p:slot",
            binding_epoch=3, provider_generation=None, native_session_ref=None, authority_id="authority",
            authority_incarnation="incarnation", execution_host_ref="fixture-host")
        yield module, state, adapter, binding


def test_actual_driver_snapshot_is_read_only_and_does_not_invent_blocker_evidence(receiver):
    _module, state, adapter, binding = receiver
    before = _mutations(state.driver)
    item = adapter.receiver_snapshot(binding)
    assert item.capability_scope.harness_kind == state.driver.harness
    assert item.capability_scope.harness_version == state.driver.profile.version
    assert item.capability_scope.provider_generation
    observations = {o.axis: o for o in item.observations}
    assert observations["connection"].value == "connected"
    assert observations["session"].value == "present"
    assert observations["input"].value == "ready"
    assert observations["blocker"].knowledge == observations["process"].knowledge == "unknown"
    assert input_decision(item, now=datetime.now(UTC), scope=item.capability_scope) == "deferred"
    assert _mutations(state.driver) == before
    assert adapter.receiver_snapshot(binding).capability_scope == item.capability_scope
    assert _mutations(state.driver) == before


def _mutations(driver):
    with driver.journal._connect() as connection:
        return [(kind, json.loads(body)) for kind, body in connection.execute(
            "SELECT kind,body FROM driver_events WHERE kind IN ('rpc_dispatch','http_dispatch') ORDER BY sequence")
            if json.loads(body).get("method") in {"thread/start", "thread/resume", "turn/start", "POST"}]


def test_changed_files_or_receiving_generation_return_unknown_without_preparation(receiver):
    _module, state, adapter, binding = receiver
    before = _mutations(state.driver)
    bad_generation = binding.model_copy(update={"provider_generation": "retired-generation"})
    invalid = project_receiver(adapter, bad_generation, lambda: datetime.now(UTC))
    assert all(c.support == "unknown" for c in invalid.capabilities)
    assert all(o.knowledge == "unknown" for o in invalid.observations)
    profile = state.driver.profile
    path = (Path(profile.codex_home) / "config.toml"
             if hasattr(profile, "codex_home") else profile.config_path)
    previous = path.read_bytes()
    try:
        path.write_bytes(previous + b"\n ")
        invalid = project_receiver(adapter, binding, lambda: datetime.now(UTC))
        assert invalid.native_session_ref is None
        assert all(c.support == "unknown" for c in invalid.capabilities)
        assert all(o.reason_code == "receiver_observation_unavailable" for o in invalid.observations)
    finally:
        path.write_bytes(previous)
    assert _mutations(state.driver) == before
