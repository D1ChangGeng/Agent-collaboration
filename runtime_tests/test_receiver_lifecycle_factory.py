"""Actual factory branch/settings and private journal setup; Native is controlled."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.codex_driver import BindingIdentity, DriverJournal
from runtime.receiver_crypto import sha256
from runtime_deployment import receiver_codex as codex
from runtime_deployment import receiver_lifecycle as lifecycle
from runtime_deployment import receiver_opencode as opencode
from runtime_deployment.receiver_authority import NativeReceiverRejected
from runtime_tests.test_receiver_factory_handoff import codex_supplied, configure_fixture
from runtime_tests.test_receiver_opencode_factory import settings as opencode_settings


def options(tmp_path):
    path = tmp_path / "project-catalog.json"
    path.write_text(json.dumps({"selected": "operator-catalog"}), encoding="utf-8")
    return {"lifecycle_control": True, "lifecycle_catalog": str(path),
        "lifecycle_catalog_sha256": sha256(path.read_bytes()),
        "lifecycle_account_ref": {"kind": "environment", "name": "LIFECYCLE_TEST_ACCOUNT"}}


@pytest.mark.parametrize("module", [codex, opencode], ids=["codex", "opencode"])
def test_concrete_factory_control_plane_never_bootstraps_native_or_unfenced_preparation(tmp_path, monkeypatch, module):
    supplied = codex_supplied(tmp_path) if module is codex else opencode_settings(tmp_path)
    supplied.update(options(tmp_path))
    Path(supplied["executable"]).write_bytes(b"controlled executable; never executed")
    captured = configure_fixture(module, monkeypatch)
    controller = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(module, "lifecycle_journal", lambda *_args, **_kwargs: SimpleNamespace())
    monkeypatch.setattr(module, "attach_lifecycle_controller", lambda _capacity: controller)
    config = SimpleNamespace(access_mode="owner", ledger_path=str(tmp_path / "receiver.sqlite"),
        binding=SimpleNamespace(registration=SimpleNamespace(machine_id="machine", node_id="node", boot_incarnation="boot")))
    kind = module.CodexReceiverCapacity if module is codex else module.OpenCodeReceiverCapacity
    capacity = kind(config, "controlled-policy", supplied)
    assert captured["spawns"] == 0 and captured["lifecycle_actions"] == []
    assert capacity.lifecycle_node is controller and captured["adapter_kwargs"]["inspect_runtime"] is None
    with pytest.raises(NativeReceiverRejected, match="signed lifecycle"):
        capacity._prepare_runtime()


@pytest.mark.parametrize("field,value", [("lifecycle_control", "true"), ("lifecycle_initialize_journal", 1),
    ("lifecycle_catalog", "relative"), ("lifecycle_catalog_sha256", "z" * 64), ("lifecycle_account_ref", {})])
def test_lifecycle_settings_require_explicit_bounded_operator_configuration(tmp_path, field, value):
    supplied = options(tmp_path) | {field: value}
    with pytest.raises(ValueError):
        lifecycle.validate_lifecycle_settings(supplied)


def test_initialization_switch_cannot_enable_itself_without_control_mode():
    with pytest.raises(ValueError):
        lifecycle.validate_lifecycle_settings({"lifecycle_initialize_journal": True})


@pytest.mark.parametrize("value", [0, 31, True, "15"])
def test_private_capacity_window_is_operator_selected_and_strictly_bounded(tmp_path, value):
    with pytest.raises(ValueError):
        lifecycle.validate_lifecycle_settings(options(tmp_path) | {"lifecycle_fresh_capacity_seconds": value})


def configured(tmp_path, *, initialize=False):
    return SimpleNamespace(settings={"lifecycle_control": True, "lifecycle_initialize_journal": initialize,
        "driver_journal": str(tmp_path / "new-capacity" / "driver.sqlite"), "binding_id": "driver-binding"},
        binding=BindingIdentity("node", "boot", "runtime", "capacity", "slot", 1))


def test_explicit_new_namespace_initializes_and_adopts_before_any_driver_claim(tmp_path, monkeypatch):
    capacity = configured(tmp_path, initialize=True)
    calls = []
    monkeypatch.setattr(lifecycle, "_namespace_authority", lambda *_args, **kwargs: calls.append(kwargs["for_provision"]))
    journal = lifecycle.lifecycle_journal(capacity)
    assert journal.preview_lifecycle_adoption() == {"schema_version": 2,
        "legacy_digest": journal.preview_lifecycle_adoption()["legacy_digest"], "operation_count": 0, "event_count": 0}
    assert capacity._lifecycle_reservation.journal_path == journal.path and calls
    assert all(calls)
    capacity._lifecycle_reservation._authorize_namespace(Path(journal.path).parent, "driver-binding", capacity.binding)
    assert calls[-1] is False
    Path(journal.path).unlink()  # Simulated loss inside this test's unique namespace.
    with pytest.raises(FileExistsError):
        lifecycle.lifecycle_journal(capacity)
    assert not Path(journal.path).exists()


def test_normal_control_start_cannot_create_missing_storage_or_silently_migrate_legacy(tmp_path):
    capacity = configured(tmp_path)
    path = Path(capacity.settings["driver_journal"])
    with pytest.raises(sqlite3.OperationalError):
        lifecycle.lifecycle_journal(capacity)
    assert not path.parent.exists()
    path.parent.mkdir()
    legacy = DriverJournal(path)
    before = legacy.preview_lifecycle_adoption()
    with pytest.raises(ValueError, match="adoption"):
        lifecycle.lifecycle_journal(capacity)
    assert legacy.preview_lifecycle_adoption() == before


def test_normal_control_start_verifies_existing_explicit_adoption_without_rewriting_it(tmp_path):
    capacity = configured(tmp_path)
    path = Path(capacity.settings["driver_journal"])
    path.parent.mkdir()
    journal = DriverJournal(path)
    journal.adopt_lifecycle_schema()
    before = journal.preview_lifecycle_adoption()
    checked = lifecycle.lifecycle_journal(capacity)
    assert checked.preview_lifecycle_adoption() == before and capacity._lifecycle_reservation is None
