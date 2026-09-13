"""Admission checks for the production Codex receiver factory."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from runtime.receiver_deployment import inspect_factory
from runtime_deployment.receiver_codex import (
    CodexReceiverCapacity,
    CodexReceiverRejected,
    SCHEMA,
    validate_settings,
)


def settings(tmp_path: Path):
    root = tmp_path / "capacity"
    root.mkdir(mode=0o700)
    values = {
        "schema_version": SCHEMA,
        "binding_id": "binding",
        "capacity_attempt_id": "capacity-attempt",
        "executable": str(root / "codex"),
        "executable_sha256": "a" * 64,
        "codex_version": "0.153.2",
        "protocol_schema": str(root / "schema.json"),
        "protocol_schema_sha256": "b" * 64,
        "cwd": str(root / "cwd"),
        "codex_home": str(root / "codex-home"),
        "config_sha256": "c" * 64,
        "permission_profile": "achp-engineer",
        "model": "gpt-5.6-sol",
        "driver_journal": str(root / "driver.sqlite"),
        "node_journal": str(root / "node.sqlite"),
        "systemd_environment_dir": str(root / "systemd-env"),
        "artifact_root": str(root / "artifacts"),
        "runtime_id": "runtime",
        "spawn_operation_id": "spawn-operation",
        "spawn_command_id": "spawn-command",
        "spawn_message_id": "spawn-message",
        "close_operation_id": "close-operation",
        "close_command_id": "close-command",
        "close_message_id": "close-message",
        "collector_max_reads": 20,
        "collector_interval_seconds": 0.5,
    }
    return values


def test_codex_receiver_settings_are_exact_and_bounded(tmp_path):
    value = settings(tmp_path)
    assert validate_settings(value) == value
    for field, replacement in (
        ("schema_version", "changed"),
        ("executable", "relative"),
        ("executable_sha256", "bad"),
        ("codex_version", "latest"),
        ("collector_max_reads", 0),
        ("collector_interval_seconds", 0),
    ):
        changed = dict(value, **{field: replacement})
        with pytest.raises(CodexReceiverRejected):
            validate_settings(changed)


def test_codex_receiver_capacity_uses_pinned_executable_directory_for_path(tmp_path, monkeypatch):
    value = settings(tmp_path)
    executable = Path(value["executable"])
    executable.write_bytes(b"codex")
    value["executable_sha256"] = hashlib.sha256(b"codex").hexdigest()
    schema = Path(value["protocol_schema"])
    schema.write_bytes(b"schema")
    value["protocol_schema_sha256"] = hashlib.sha256(b"schema").hexdigest()
    cwd = Path(value["cwd"])
    cwd.mkdir()
    codex_home = Path(value["codex_home"])
    codex_home.mkdir()
    config = codex_home / "config.toml"
    config.write_text('approval_policy = "never"\ndefault_permissions = "achp-engineer"\n')
    value["config_sha256"] = hashlib.sha256(config.read_bytes()).hexdigest()

    observed = {}

    class Profile:
        def __init__(self, *args):
            observed["environment"] = args[9]

    class StopConstruction(Exception):
        pass

    monkeypatch.setattr(
        "runtime_deployment.receiver_codex.DomainAuthority",
        lambda dsn: type("Authority", (), {"_dsn": dsn})(),
    )
    monkeypatch.setenv("ACS_RECEIVER_DSN", "postgresql://redacted")
    # Stop immediately after the profile is constructed; the remaining
    # collaborators are covered by the production-factory integration tests.
    monkeypatch.setattr("runtime_deployment.receiver_codex.LaunchProfile", Profile)
    monkeypatch.setattr(
        "runtime_deployment.receiver_codex.SystemdUserSupervisor",
        lambda **_kwargs: (_ for _ in ()).throw(StopConstruction()),
    )
    config_object = type("Config", (), {"binding": type("Binding", (), {
        "registration": type("Registration", (), {
            "config_sha256": "policy", "runtime_id": "runtime",
            "node_id": "node", "boot_incarnation": "boot", "agent_slot_id": "slot",
            "node_binding_revision": 1, "machine_id": "machine", "scope_id": "scope",
        })()
    })()})()
    with pytest.raises(StopConstruction):
        CodexReceiverCapacity(config_object, "policy", value)
    assert observed["environment"]["PATH"].split(":", 1)[0] == str(executable.parent)


@pytest.mark.skipif(os.name != "posix", reason="deployment factory binding is POSIX-owned")
def test_factory_binding_digest_includes_settings(tmp_path):
    value = settings(tmp_path)
    import runtime_deployment
    import runtime_deployment.receiver_codex as deployment
    for source in (runtime_deployment.__file__, deployment.__file__):
        path = Path(source)
        path.chmod(path.stat().st_mode & ~0o022)
    first, _, _, _ = inspect_factory(
        "runtime_deployment.receiver_codex:callbacks", settings=value,
    )
    changed = dict(value, collector_max_reads=21)
    second, _, _, _ = inspect_factory(
        "runtime_deployment.receiver_codex:callbacks", settings=changed,
    )
    assert first.settings == value and second.settings == changed
    assert hashlib.sha256(
        json.dumps(first.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest() != hashlib.sha256(
        json.dumps(second.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
