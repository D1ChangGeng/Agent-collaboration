"""Factory wiring against actual enrolled Core and retained signed lifecycle plans.

Native-origin loading/profile capture are spied here; their actual journal and
transport regressions run separately. No Native process or model is started.
"""
from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import fields
from types import SimpleNamespace

import pytest

from runtime.receiver_config import ReceiverClientConfig
from runtime.receiver_crypto import key_fingerprint, sha256
from runtime.receiver_lifecycle_capacity import CapacityEvidenceUnavailable
from runtime_deployment import receiver_lifecycle as factory
from runtime_tests.probe_receiver_windows_backend import private_root
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_receiver_lifecycle_issuance_pg import (
    PROJECT,
    allow,
    payload,
    plan,
    setup_graph,
    snapshot,
    submit,
)

comm = comm_fixture


@pytest.mark.parametrize("archived", [False, True])
@pytest.mark.parametrize("damaged_signature", [False, True])
def test_factory_reattests_current_enrollment_and_original_core_profile_before_restoration(
        comm, tmp_path, monkeypatch, archived, damaged_signature):
    f = setup_graph(comm, mode="owner")
    operation = submit(f)
    plan(f, operation)
    permit = allow(f, operation).permit
    stored = payload(f, operation)
    original = deepcopy(stored["lifecycle"])
    native_plan = permit.permit.plan
    if damaged_signature:
        original["permit"]["signature"] = "0" * 128
    if archived:
        stored["lifecycle"] = {"schema_version": original["schema_version"], "target": original["target"],
            "plan": None, "first_plan_digest": None, "permit": None, "observation": None,
            "driver_binding_id": native_plan.capacity.driver_binding_id,
            "original_capacity_digest": sha256(original), "history": [original]}
    else:
        stored["lifecycle"] = original
    with f.authority._connect() as connection:
        connection.execute("UPDATE outbox SET payload=%s WHERE operation_id=%s",
                           (json.dumps(stored), operation["operation_id"]))
        selected = snapshot(f, connection)
    config = ReceiverClientConfig(selected.binding, selected.authority_key.key_id, selected.authority_key.revision,
        selected.authority_key.public_key, key_fingerprint(selected.authority_key.public_key),
        f.registration.boot_incarnation, 1, access_mode="owner")
    private = tmp_path / "capacity-private"
    if os.name == "nt":
        private_root(private)
    else:
        private.mkdir(mode=0o700)
    catalog = private / "catalog.json"
    catalog.write_text(json.dumps(f.recovery.projects.catalog), encoding="utf-8")
    driver = SimpleNamespace(identity=native_plan.capacity.binding, binding_id=native_plan.capacity.driver_binding_id,
                             journal=SimpleNamespace(path=str(private / "driver.sqlite")))
    capacity = SimpleNamespace(driver=driver, binding=driver.identity, config=config, authority=f.authority,
        clock=None, settings={"driver_journal": str(private / "driver.sqlite"), "binding_id": driver.binding_id,
            "lifecycle_catalog": str(catalog), "lifecycle_catalog_sha256": sha256(catalog.read_bytes()),
            "lifecycle_account_ref": {"kind": "environment", "name": "ACS_CONTROLLED_RESTORE_ACCOUNT"}})
    origin = SimpleNamespace(source_ref=operation["operation_id"], command_id=native_plan.source.command_id,
                             creation_operation_id=native_plan.driver_operation_id)
    seal = {"profile_fingerprint": native_plan.capacity.profile_fingerprint}
    witness = object()
    checks = []

    def unavailable(*_args, **_options):
        raise CapacityEvidenceUnavailable("retained_journal_requires_original_profile")

    def recover(actual, *, authorize_current, account_fingerprint, authorize_original):
        assert actual is driver
        authorize_current(driver)  # Real current enrolled Runtime/Node/key/registration.
        monkeypatch.setenv("ACS_CONTROLLED_RESTORE_ACCOUNT", "synthetic-selected-account")
        assert account_fingerprint(driver) == sha256({"selected_account_binding": "synthetic-selected-account"})
        authorize_original(origin, seal)  # Actual original Outbox plan and Ed25519 verification.
        checks.append(True)
        return witness

    monkeypatch.setattr(factory, "capture_capacity_profile", unavailable)
    monkeypatch.setattr(factory, "recover_capacity_profile", recover)
    monkeypatch.setattr(factory, "load_owner_signing_key", lambda *_args: f.node_key)
    monkeypatch.setattr(factory, "ReceiverLifecycleNode", lambda *_args, **options: SimpleNamespace(**options))
    # RuntimeConfig normally owns this path; the constructor is intercepted so
    # this test never opens or invents a private Node signing-key file.
    config = SimpleNamespace(**{item.name: getattr(config, item.name) for item in fields(ReceiverClientConfig)},
                             node_signing_key_path="unused-test-key")
    capacity.config = config
    controller = factory.attach_lifecycle_controller(capacity)
    assert controller.profile_witness is (None if damaged_signature else witness)
    assert bool(checks) is not damaged_signature
    # Both current and archived startup facts forbid resetting the namespace.
    with pytest.raises(PermissionError, match="history forbids namespace recreation"):
        factory._namespace_authority(capacity, private, driver.binding_id, driver.identity, for_provision=True)
    assert all(not value.calls for value in comm.drivers.values())
    assert PROJECT == native_plan.source.project_id
