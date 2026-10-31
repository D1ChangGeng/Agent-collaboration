"""Admission checks for the production Codex receiver factory."""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.receiver_deployment import inspect_factory
from runtime_deployment.receiver_codex import (
    SCHEMA,
    CodexReceiverCapacity,
    CodexReceiverRejected,
    validate_settings,
)


@contextmanager
def _registered_node_connection():
    yield SimpleNamespace(execute=lambda *_args, **_kwargs: SimpleNamespace(
        fetchone=lambda: ("registered-observer", "registered-observer-grant")))


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
        "model_catalog": str(root / "models.json"),
        "model_catalog_sha256": "d" * 64,
        "cwd": str(root / "cwd"),
        "codex_home": str(root / "codex-home"),
        "config_sha256": "c" * 64,
        "permission_profile": "achp-engineer",
        "model": "gpt-5.6-sol",
        "source_commit": "a" * 40,
        "source_tree": "b" * 40,
        "driver_journal": str(root / "driver.sqlite"),
        "node_journal": str(root / "node.sqlite"),
        "systemd_environment_dir": str(
            root / ("windows-job" if os.name == "nt" else "systemd-env")
        ),
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
    Path(value["model_catalog"]).write_text("{}", encoding="utf-8")
    value["model_catalog_sha256"] = hashlib.sha256(b"{}").hexdigest()
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
    catalog = Path(value["model_catalog"])
    catalog.write_text("{}", encoding="utf-8")
    value["model_catalog_sha256"] = hashlib.sha256(b"{}").hexdigest()
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
        lambda dsn: SimpleNamespace(_dsn=dsn, access_mode="shared", _connect=lambda: _registered_node_connection()),
    )
    monkeypatch.setenv("ACS_RECEIVER_DSN", "postgresql://redacted")
    # Stop immediately after the profile is constructed; the remaining
    # collaborators are covered by the production-factory integration tests.
    monkeypatch.setattr("runtime_deployment.receiver_codex.LaunchProfile", Profile)
    monkeypatch.setattr(
        "runtime_deployment.receiver_codex.SystemdUserSupervisor",
        lambda **_kwargs: (_ for _ in ()).throw(StopConstruction()),
    )
    monkeypatch.setattr(
        "runtime_deployment.receiver_codex.WindowsJobSupervisor",
        lambda **_kwargs: (_ for _ in ()).throw(StopConstruction()),
    )
    config_object = type("Config", (), {"binding": type("Binding", (), {
        "registration": type("Registration", (), {
            "config_sha256": "policy", "runtime_id": "runtime",
            "node_id": "node", "boot_incarnation": "boot", "agent_slot_id": "slot",
            "node_binding_revision": 1, "machine_id": "machine", "scope_id": "scope",
            "tenant_id": "tenant", "authority_id": "authority", "authority_incarnation": "incarnation",
        })()
    })(), "ledger_path": str(Path(value["node_journal"]).with_name("receiver.sqlite"))})()
    with pytest.raises(StopConstruction):
        CodexReceiverCapacity(config_object, "policy", value)
    path = observed["environment"]["PATH"].split(os.pathsep)
    if os.name == "nt":
        assert path[0] == str(executable.parent)
    else:
        assert path[:2] == [str(executable.parent), "/opt/acs/codex-sandbox/bin"]


def test_codex_receiver_current_authority_uses_configured_clock_skew():
    observed = {}

    class Transport:
        def current_authority(self, admission, *, clock_skew_seconds):
            observed.update(admission=admission, clock_skew_seconds=clock_skew_seconds)
            return True

    capacity = object.__new__(CodexReceiverCapacity)
    capacity.config = SimpleNamespace(clock_skew_seconds=5)
    capacity.authority = SimpleNamespace(
        receiver_transport=Transport(),
    )
    admission = object()
    assert capacity.authorize_current(admission) is True
    assert observed == {"admission": admission, "clock_skew_seconds": 5}


def test_codex_receiver_native_domain_recheck_uses_same_clock_skew():
    observed = {}

    class Authority:
        def _authorize(
            self, command, cursor, permission, scope_id, *, clock_skew_seconds,
        ):
            observed.update(
                command=command,
                cursor=cursor,
                permission=permission,
                scope_id=scope_id,
                clock_skew_seconds=clock_skew_seconds,
            )

    capacity = object.__new__(CodexReceiverCapacity)
    capacity.config = SimpleNamespace(clock_skew_seconds=5)
    capacity.authority = Authority()
    values = [SimpleNamespace(tenant_id="tenant", authority_id="authority", authority_incarnation="incarnation",
                              principal_ref="sender", grant_ref="sender-grant"), object(), "runtime.invoke", "scope",
              SimpleNamespace(schema_version="acs-message/1", sender="collaborator:project:sender")]
    capacity._authorize_domain_command(*values)
    assert observed == {
        "command": values[0],
        "cursor": values[1],
        "permission": "runtime.invoke",
        "scope_id": "scope",
        "clock_skew_seconds": 5,
    }


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
