"""Receiver journal to actual NativeDeliveryAdapter no-model composition."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import zipfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from runtime.codex_driver import AuthorizedOperation
from runtime.delivery_models import DeliveryEnvelope, DeliveryPacket
from runtime.delivery_node import invocation_for
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.receiver import ReceiverService
from runtime.receiver_crypto import sha256, sign
from runtime.receiver_delivery import ReceiverNativeDeliveryBridge
from runtime.receiver_deployment import (
    FactoryBinding,
    bind_process_config,
    dump_process_config,
)
from runtime.receiver_entry import load_callbacks, load_process_config
from runtime.receiver_install import REQUIRED, verify_wheel_archive
from runtime.receiver_models import DispatchBody, PrepareBody
from runtime.receiver_provision import provision
from runtime.sender import AdmissionFactory, DeliveryIdentity
from runtime_tests import test_codex_driver as codex_fixture
from runtime_tests import test_receiver_protocol as receiver_fixture
from runtime_tests.receiver_deployment_fixture import source_factory_binding


def test_installed_provisioner_forces_fresh_stage_without_source_pythonpath(tmp_path):
    wheel = os.getenv("ACS_RECEIVER_WHEEL")
    provisioner = os.getenv("ACS_BOOTSTRAP_RECEIVER_PROVISIONER")
    bootstrap_python = os.getenv("ACS_BOOTSTRAP_RECEIVER_PYTHON")
    pip_python = os.getenv("ACS_PIP_PYTHON")
    if (os.name != "posix" or not wheel or not provisioner
            or not bootstrap_python or not pip_python):
        pytest.skip("installed bootstrap provisioner evidence is unavailable")
    parent = tmp_path / "provisioned"
    parent.mkdir(mode=0o700)
    environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1"}

    def install(name):
        destination = parent / name
        previous = os.umask(0o002)
        try:
            completed = subprocess.run(
                [provisioner, "--wheel", wheel, "--destination", destination,
                 "--python", bootstrap_python, "--pip-python", pip_python],
                cwd=tmp_path, env=environment, capture_output=True, text=True, check=True,
            )
        finally:
            os.umask(previous)
        evidence = json.loads(completed.stdout)
        assert evidence["destination"] == str(destination)
        assert not list(parent.glob(".receiver-stage-*"))
        receiver = destination / "bin" / "acs-receiver"
        verified = subprocess.run(
            [receiver, "--verify-install"], cwd=tmp_path, env=environment,
            capture_output=True, text=True, check=True,
        )
        assert json.loads(verified.stdout)["install_root"] == str(destination)
        assert subprocess.run(
            [receiver, "--factory-binding"], cwd=tmp_path, env=environment,
            capture_output=True, text=True, check=True,
        ).returncode == 0
        return destination

    first = install("first")
    second = install("second")
    before = hashlib.sha256((first / "receiver-install-manifest.json").read_bytes()).hexdigest()
    repeated = subprocess.run(
        [provisioner, "--wheel", wheel, "--destination", first,
         "--python", bootstrap_python, "--pip-python", pip_python],
        cwd=tmp_path, env=environment, capture_output=True, text=True, check=False,
    )
    assert repeated.returncode != 0
    assert hashlib.sha256((first / "receiver-install-manifest.json").read_bytes()).hexdigest() == before
    assert second.is_dir()


def test_fresh_wheel_is_self_contained_and_installed_origin_is_enforced(tmp_path):
    wheel = os.getenv("ACS_RECEIVER_WHEEL")
    installed = os.getenv("ACS_INSTALLED_RECEIVER")
    if os.name != "posix" or not wheel or not installed:
        pytest.skip("fresh receiver wheel and provisioned console script are required")
    assert set(REQUIRED) <= set(verify_wheel_archive(wheel))
    missing = tmp_path / "missing-deployment-package.whl"
    with zipfile.ZipFile(wheel) as source, zipfile.ZipFile(missing, "w") as target:
        for item in source.infolist():
            if item.filename != "runtime_deployment/receiver_p1.py":
                target.writestr(item, source.read(item.filename))
    with pytest.raises(ValueError, match="omits required package"):
        verify_wheel_archive(missing)
    environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1"}
    completed = subprocess.run(
        [installed, "--verify-install"], cwd=tmp_path, env=environment,
        capture_output=True, text=True, check=True,
    )
    evidence = json.loads(completed.stdout)
    installed_root = Path(evidence["install_root"]).resolve()
    assert str(Path(__file__).resolve().parents[1]) not in str(installed_root)
    provisioner = installed_root / "bin" / "acs-receiver-provision"
    assert subprocess.run(
        [provisioner, "--help"], cwd=tmp_path, env=environment,
        capture_output=True, text=True, check=False,
    ).returncode == 0
    factories = list(installed_root.glob("lib/python*/site-packages/runtime_deployment/receiver_p1.py"))
    assert len(factories) == 1
    factory_path = factories[0]
    original_mode = stat.S_IMODE(factory_path.stat().st_mode)
    launcher = Path(installed)
    receiver_module = next(installed_root.glob("lib/python*/site-packages/runtime/receiver.py"))
    record = next(installed_root.glob("lib/python*/site-packages/*.dist-info/RECORD"))
    manifest = installed_root / "receiver-install-manifest.json"

    def verify():
        return subprocess.run(
            [installed, "--verify-install"], cwd=tmp_path, env=environment,
            capture_output=True, text=True, check=False,
        )

    try:
        factory_path.chmod(0o664)
        rejected = verify()
        assert rejected.returncode != 0 and "owner-controlled" in rejected.stderr
    finally:
        factory_path.chmod(original_mode)
    original = receiver_module.read_bytes()
    try:
        receiver_module.write_bytes(original + b"\n# replaced\n")
        assert verify().returncode != 0
    finally:
        receiver_module.write_bytes(original)
        receiver_module.chmod(0o600)
    extra = receiver_module.with_name("receiver_extra.py")
    try:
        extra.write_text("raise RuntimeError('extra code')\n", encoding="utf-8")
        extra.chmod(0o600)
        assert verify().returncode != 0
    finally:
        extra.unlink()
    for path, suffix in ((launcher, b"\n# changed launcher\n"),
                         (record, b"\nmalformed\n")):
        original = path.read_bytes()
        mode = stat.S_IMODE(path.stat().st_mode)
        try:
            path.write_bytes(original + suffix)
            path.chmod(mode)
            assert verify().returncode != 0
        finally:
            path.write_bytes(original)
            path.chmod(mode)
    original = manifest.read_bytes()
    try:
        value = json.loads(original)
        value["interpreter_sha256"] = "0" * 64
        manifest.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        manifest.chmod(0o600)
        assert verify().returncode != 0
    finally:
        manifest.write_bytes(original)
        manifest.chmod(0o600)
    assert verify().returncode == 0


def test_provision_postflight_failure_quarantines_destination(tmp_path):
    wheel = os.getenv("ACS_RECEIVER_WHEEL")
    if os.name != "posix" or not wheel:
        pytest.skip("fresh receiver wheel is required")
    parent = tmp_path / "install-parent"
    parent.mkdir(mode=0o700)
    wrapper = tmp_path / "python-wrapper"
    wrapper.write_text(
        f"#!{sys.executable}\nimport os,sys\nos.execv({sys.executable!r},"
        f"[{sys.executable!r},*sys.argv[1:]])\n",
        encoding="utf-8", newline="\n",
    )
    wrapper.chmod(0o700)
    destination = parent / "receiver"
    with pytest.raises(subprocess.CalledProcessError):
        provision(wheel, destination, python=str(wrapper), pip_python=sys.executable)
    assert not destination.exists()
    quarantined = list(parent.glob(".receiver-failed-*"))
    assert len(quarantined) == 1
    assert (quarantined[0] / "receiver-install-manifest.json").is_file()


def test_receiver_entry_config_is_owner_only_and_factory_allowlisted(tmp_path):
    if os.name != "posix":
        pytest.skip("receiver runtime is POSIX-only")
    receiver_env = receiver_fixture.env.__wrapped__(tmp_path)
    factory, _, _, _ = source_factory_binding()
    process = bind_process_config(receiver_env.config, factory, receiver_env.node_key)
    config_path = tmp_path / "receiver-config.json"
    config_path.write_text(dump_process_config(process), encoding="utf-8")
    config_path.chmod(0o600)
    assert load_process_config(config_path) == process
    invalid = replace(process, factory=FactoryBinding(
        reference="os:path", module_sha256=factory.module_sha256,
        package_sha256=factory.package_sha256, callable_sha256=factory.callable_sha256,
        origin_path_sha256=factory.origin_path_sha256,
        install_manifest_sha256=factory.install_manifest_sha256,
        distribution_record_sha256=factory.distribution_record_sha256,
    ))
    config_path.write_text(dump_process_config(invalid), encoding="utf-8")
    with pytest.raises(ValueError, match="digest differs"):
        load_process_config(config_path)
    config_path.chmod(0o644)
    with pytest.raises(ValueError, match="mode 0600"):
        load_process_config(config_path)


def test_receiver_process_config_rejects_each_policy_field_change(tmp_path):
    if os.name != "posix":
        pytest.skip("receiver runtime is POSIX-only")
    receiver_env = receiver_fixture.env.__wrapped__(tmp_path)
    factory, _, _, _ = source_factory_binding()
    process = bind_process_config(receiver_env.config, factory, receiver_env.node_key)
    original = json.loads(dump_process_config(process))
    mutations = [
        ("runtime", "maximum_body_bytes", process.runtime.maximum_body_bytes + 1),
        ("runtime", "clock_skew_seconds", process.runtime.clock_skew_seconds + 1),
        ("runtime", "journal_generation", 2),
        ("runtime", "ledger_path", str(tmp_path / "other.sqlite")),
        ("factory", "module_sha256", "f" * 64),
        ("factory", "callable_sha256", "e" * 64),
        ("factory", "reference", "runtime_deployment.receiver_p1:replacement"),
    ]
    for section, field, value in mutations:
        changed = json.loads(json.dumps(original))
        changed[section][field] = value
        path = tmp_path / f"changed-{field}.json"
        path.write_text(json.dumps(changed), encoding="utf-8")
        path.chmod(0o600)
        with pytest.raises((ValueError, RuntimeError)):
            load_process_config(path)
    registration = process.runtime.binding.registration.model_copy(
        update={"config_sha256": "f" * 64},
    )
    binding = process.runtime.binding.model_copy(update={
        "registration": registration,
        "registration_signature": sign(receiver_env.node_key, registration),
    })
    wrong_registration_digest = replace(
        process, runtime=replace(process.runtime, binding=binding),
    )
    path = tmp_path / "changed-registration-digest.json"
    path.write_text(dump_process_config(wrong_registration_digest), encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(ValueError, match="digest differs"):
        load_process_config(path)


def test_receiver_factory_attribute_substitution_is_rejected(tmp_path, monkeypatch):
    if os.name != "posix":
        pytest.skip("receiver runtime is POSIX-only")
    receiver_env = receiver_fixture.env.__wrapped__(tmp_path)
    factory, _, _, _ = source_factory_binding()
    process = bind_process_config(receiver_env.config, factory, receiver_env.node_key)
    import runtime_deployment.receiver_p1 as deployment

    monkeypatch.setattr(deployment, "callbacks", lambda *_args: ())
    with pytest.raises(ValueError, match="callable identity"):
        load_callbacks(process)


def test_receiver_dispatch_enters_native_adapter_once(tmp_path, monkeypatch):
    if os.name != "posix":
        pytest.skip("receiver runtime is POSIX-only")
    receiver_env = receiver_fixture.env.__wrapped__(tmp_path)
    native_root = tmp_path / "native"
    native_root.mkdir(mode=0o700)
    profile = codex_fixture.profile.__wrapped__(native_root)
    fixture = codex_fixture.native.__wrapped__(native_root, profile, monkeypatch)
    native = next(fixture)
    try:
        native.driver.spawn(codex_fixture.operation("receiver-native-spawn"))
        envelope = DeliveryEnvelope(
            tenant_id="tenant", authority_id="authority",
            authority_incarnation="authority-incarnation",
            principal_ref="sender", grant_ref="grant", message_id="message",
            command_id="command", operation_id="operation", endpoint_id="endpoint",
            binding_revision=1, machine_id="machine", node_id="node",
            boot_incarnation="boot-1", accepted_state_digest="a" * 64,
            packet=DeliveryPacket(
                work_item_id="work", target_scope_id="scope", target_agent_slot_id="slot",
                accepted_revision=0, goal="No-model native bridge",
                accepted_state_summary="fixture", request="synthetic JSONL only",
                source_baseline="fixture", expected_response="native ACK", activation="invoke",
                deadline=datetime.now(UTC) + timedelta(seconds=30),
            ),
        )
        invocation = invocation_for(envelope, "attempt")
        selection = {
            "endpoint_id": envelope.endpoint_id, "binding_revision": envelope.binding_revision,
            "machine_id": envelope.machine_id, "node_id": envelope.node_id,
            "boot_incarnation": envelope.boot_incarnation,
            "target_scope_id": envelope.packet.target_scope_id,
            "target_agent_slot_id": envelope.packet.target_agent_slot_id,
        }
        identity = DeliveryIdentity(
            message_id=invocation.message_id, command_id=invocation.command_id,
            operation_id=invocation.operation_id, attempt_id=invocation.attempt_id,
            dispatch_id=invocation.dispatch_id, accepted_revision=invocation.accepted_revision,
            accepted_state_digest=invocation.accepted_state_digest,
            envelope_digest=invocation.envelope_digest, selection_digest=invocation.selection_digest,
            invocation_digest=sha256(invocation.model_dump(mode="json")),
            deadline=envelope.packet.deadline,
        )
        factory = AdmissionFactory(receiver_env.config, receiver_env.authority_key, identity)
        service = ReceiverService(
            receiver_env.config, receiver_env.node_key,
            authorize_current=receiver_fixture.fixture_authority_current,
        )
        service.claim_boot("boot-1", 1)
        prepare = factory.request(
            "delivery.prepare",
            PrepareBody(
                envelope=envelope.model_dump(mode="json"),
                invocation=invocation.model_dump(mode="json"), selection=selection,
            ),
        )
        service.prepare(prepare)

        def authorize_native(value, binding):
            assert binding == native.driver.identity
            return AuthorizedOperation(
                value.invocation_id, value.command_id, value.message_id,
                "receiver-native-fixture", value.envelope.packet.deadline,
            )

        adapter = NativeDeliveryAdapter(native.driver, authorize_invocation=authorize_native)
        bridge = ReceiverNativeDeliveryBridge(
            receiver_env.config.ledger_path, adapter, read_domain_marker=lambda _value: True,
        )
        dispatch = factory.request(
            "delivery.dispatch",
            DispatchBody(
                prepare_request_id=prepare.admission.request_id,
                marker_receipt_id=invocation.runtime_dispatched_receipt_id,
            ),
        )
        receipt = service.dispatch(dispatch, bridge)
        assert receipt.receipt.state == "runtime_acknowledged"
        assert native.state["turn_calls"] == 1
        assert receipt.receipt.evidence["native_observation"]["native_ack_ref"]
        assert service.dispatch(dispatch, lambda _admission: {"forbidden": True}) == receipt
        assert native.state["turn_calls"] == 1
    finally:
        fixture.close()
