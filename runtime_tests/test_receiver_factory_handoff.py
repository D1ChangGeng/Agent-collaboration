"""Opt-in handoff policy in production factories; Native construction is a labeled fixture."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime_deployment import receiver_codex as codex
from runtime_deployment import receiver_opencode as opencode
from runtime_tests.test_receiver_codex_factory import settings as codex_settings
from runtime_tests.test_receiver_opencode_factory import settings as opencode_settings

ABSENT = object()


def codex_supplied(tmp_path):
    supplied = codex_settings(tmp_path)
    catalog = Path(supplied["model_catalog"])
    catalog.write_text("{}", encoding="utf-8")
    supplied["model_catalog_sha256"] = hashlib.sha256(b"{}").hexdigest()
    return supplied


def shared_opencode_supplied(tmp_path):
    return {**opencode_settings(tmp_path), "executable_sha256": "a" * 64,
        "opencode_version": "1.18.34", "schema_sha256": "b" * 64,
        "config_sha256": "c" * 64, "agent": "engineer", "provider_id": "provider",
        "model_id": "model", "collaboration_server": "acs",
        "systemd_environment_dir": str(tmp_path / "systemd-env")}


@pytest.mark.parametrize("flag", [ABSENT, False, True], ids=["legacy", "off", "on"])
@pytest.mark.parametrize("mode", ["native", "restricted"])
def test_codex_accepts_optional_bool_without_changing_legacy_config(tmp_path, monkeypatch, mode, flag):
    supplied = codex_supplied(tmp_path)
    if flag is not ABSENT:
        supplied["record_handoff"] = flag
    probes = []
    monkeypatch.setattr(codex.subprocess, "run", lambda *_args, **_kwargs:
        probes.append("version") or SimpleNamespace(stdout="codex-cli 0.166.0\n"))
    observed = codex.validate_settings(supplied, execution_mode=mode)
    assert observed.get("record_handoff", False) is (False if flag is ABSENT else flag)
    assert ("record_handoff" in observed) is (flag is not ABSENT)
    assert probes == (["version"] if mode == "native" else [])
    if mode == "restricted":
        assert observed == supplied


@pytest.mark.parametrize("flag", [None, 0, 1, "false", "true", [], {}])
@pytest.mark.parametrize("mode", ["native", "restricted"])
def test_codex_rejects_non_bool_before_version_probe_or_preparation(tmp_path, monkeypatch, mode, flag):
    supplied = {**codex_supplied(tmp_path), "record_handoff": flag}
    monkeypatch.setattr(codex.subprocess, "run", lambda *_args, **_kwargs:
        pytest.fail("invalid policy must be rejected before executing the binary"))
    with pytest.raises(codex.CodexReceiverRejected, match="record_handoff"):
        codex.validate_settings(supplied, execution_mode=mode)
    assert not Path(supplied["codex_home"]).exists()


@pytest.mark.parametrize("flag", [ABSENT, False, True], ids=["legacy", "off", "on"])
@pytest.mark.parametrize("shared", [False, True], ids=["owner", "shared"])
def test_opencode_policy_validates_without_preparing_selected_home(tmp_path, shared, flag):
    supplied = shared_opencode_supplied(tmp_path) if shared else opencode_settings(tmp_path)
    if flag is not ABSENT:
        supplied["record_handoff"] = flag
    validate = opencode.shared_settings if shared else opencode.validate_settings
    observed = validate(supplied)
    assert observed.get("record_handoff", False) is (False if flag is ABSENT else flag)
    assert ("record_handoff" in observed) is (flag is not ABSENT)
    assert not Path(observed["home"]).exists()


@pytest.mark.parametrize("flag", [None, 0, 1, "false", "true", [], {}])
@pytest.mark.parametrize("shared", [False, True], ids=["owner", "shared"])
def test_opencode_rejects_non_bool_without_native_actions(tmp_path, monkeypatch, shared, flag):
    supplied = shared_opencode_supplied(tmp_path) if shared else opencode_settings(tmp_path)
    supplied["record_handoff"] = flag
    monkeypatch.setattr(opencode.subprocess, "run", lambda *_args, **_kwargs:
        pytest.fail("validation cannot execute a Native binary"))
    validate = opencode.shared_settings if shared else opencode.validate_settings
    with pytest.raises(opencode.NativeReceiverRejected, match="record_handoff"):
        validate(supplied)
    assert not Path(supplied["home"]).exists()


def configure_fixture(module, monkeypatch):
    """Only replace external collaborators; run the actual factory and validator."""
    captured = {"spawns": 0, "observations": [], "lifecycle_actions": []}
    authority = SimpleNamespace(_dsn="isolated-fixture", receiver_transport=SimpleNamespace(
        dispatch_marker_current=lambda *_args: pytest.fail("constructor cannot dispatch input")))
    monkeypatch.setenv("ACS_RECEIVER_DSN", "isolated-fixture")
    monkeypatch.setattr(module, "DomainAuthority", lambda *_args, **_kwargs: authority)
    monkeypatch.setattr(module, "bind_registered_receiver", lambda *_args: SimpleNamespace())
    monkeypatch.setattr(module, "NodeJournal", lambda *_args, **_kwargs: SimpleNamespace())
    monkeypatch.setattr(module, "DriverJournal", lambda *_args, **_kwargs: SimpleNamespace())
    monkeypatch.setattr(module, "receiver_clock_identity", lambda _config: {})
    monkeypatch.setattr(module, "ConnectionClock", SimpleNamespace(from_authority=lambda *_args, **_kwargs: object()))
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(stdout="fixture-version\n"))
    supervisor = SimpleNamespace(close=lambda: None)
    for name in ("WindowsJobSupervisor", "SystemdUserSupervisor", "PosixProcessSupervisor"):
        monkeypatch.setattr(module, name, lambda **_kwargs: supervisor)

    class NativeFixture:
        owned = None

        def __init__(self, *_args, **_kwargs):
            pass

        def spawn(self, _operation):
            captured["spawns"] += 1

    def adapter(driver, **kwargs):
        captured.update(driver=driver, adapter_kwargs=kwargs)
        return SimpleNamespace()

    capacity = module.CodexReceiverCapacity if module is codex else module.OpenCodeReceiverCapacity
    operation = object()

    def lifecycle(_self, action):
        captured["lifecycle_actions"].append(action)
        return operation

    def observe(driver, current):
        assert current is operation
        captured["observations"].append((driver, current))
        return {"source": "synthetic-observation"}

    monkeypatch.setattr(capacity, "_lifecycle_operation", lifecycle)
    monkeypatch.setattr("runtime.native_input_observations.observe_native_input", observe)
    monkeypatch.setattr(module, "NativeDeliveryAdapter", adapter)
    monkeypatch.setattr(module, "ReceiverNativeDeliveryBridge", lambda *_args, **_kwargs: object())
    profile_name = "LaunchProfile" if module is codex else "OpenCodeLaunchProfile"
    monkeypatch.setattr(module, profile_name, lambda *_args, **_kwargs: SimpleNamespace())
    driver_name = "CodexAppServerDriver" if module is codex else "OpenCodeNativeDriver"
    monkeypatch.setattr(module, driver_name, NativeFixture)
    return captured


@pytest.mark.parametrize("flag", [ABSENT, False, True], ids=["legacy", "off", "on"])
@pytest.mark.parametrize("shared", [False, True], ids=["owner", "shared"])
@pytest.mark.parametrize("module", [codex, opencode], ids=["codex", "opencode"])
def test_actual_factory_forwards_recording_option_to_native_adapter(tmp_path, monkeypatch, module, shared, flag):
    if module is opencode and shared and os.name != "posix":
        pytest.skip("Shared OpenCode capacity requires the qualified POSIX supervisor")
    supplied = (codex_supplied(tmp_path) if module is codex else
                shared_opencode_supplied(tmp_path) if shared else opencode_settings(tmp_path))
    if flag is not ABSENT:
        supplied["record_handoff"] = flag
    # The selected executable is a fixture, read for its fingerprint only.
    Path(supplied["executable"]).write_bytes(b"synthetic factory executable; never launched")
    captured = configure_fixture(module, monkeypatch)
    config = SimpleNamespace(access_mode="shared" if shared else "owner", ledger_path=str(tmp_path / "receiver.sqlite"),
        binding=SimpleNamespace(registration=SimpleNamespace(machine_id="machine", node_id="node", boot_incarnation="boot")))
    capacity_type = module.CodexReceiverCapacity if module is codex else module.OpenCodeReceiverCapacity
    capacity = capacity_type(config, "fixture-policy", supplied)
    assert captured["adapter_kwargs"]["record_handoff"] is (False if flag is ABSENT else flag)
    assert captured["adapter_kwargs"]["authorize_invocation"] == capacity._authorize_invocation
    assert captured["adapter_kwargs"]["inspect_runtime"] == capacity.health
    assert captured["adapter_kwargs"]["configure_runtime"] == capacity._prepare_runtime
    assert captured["spawns"] == 1
    assert captured["observations"] == [] and captured["lifecycle_actions"] == ["spawn"]
    if flag is True:
        callback = captured["adapter_kwargs"]["observe_input"]
        assert callback == capacity._observe_input
        assert callback() == {"source": "synthetic-observation"}
        assert len(captured["observations"]) == 1 and captured["lifecycle_actions"] == ["spawn", "spawn"]
    else:
        assert captured["adapter_kwargs"]["observe_input"] is None
