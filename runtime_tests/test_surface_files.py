"""Operator file admission uses real descriptors and synthetic private bytes."""
import json
import os
from types import SimpleNamespace

import pytest

from runtime.operator_files import OperatorFileError, _identity, read_operator_file
from runtime.surface_config import ConfigurationError, PrivateReference, load_settings


def write_config(path):
    data = {"context": {"tenant_id": "t", "authority_id": "a", "authority_incarnation": "i",
                         "principal_ref": "p", "grant_ref": "g", "credential_hash": "a" * 64},
            "dsn_ref": {"kind": "environment", "name": "FIXTURE_DSN"},
            "credential_ref": {"kind": "environment", "name": "FIXTURE_TOKEN"}}
    payload = json.dumps(data).encode()
    path.write_bytes(payload)
    path.chmod(0o600)
    return payload


def test_operator_config_roundtrip_uses_regular_file_identity(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "config.json"
    expected = write_config(path)
    assert read_operator_file(path) == expected
    assert load_settings(path).context.principal_ref == "p"


@pytest.mark.skipif(os.name != "nt", reason="Windows path/handle ctime semantics")
def test_windows_identity_uses_shared_birthtime_instead_of_different_ctime_semantics():
    values = {"st_dev": 1, "st_ino": 2, "st_mode": 0o100666, "st_uid": 0, "st_gid": 0,
              "st_size": 8, "st_mtime_ns": 5, "st_birthtime_ns": 3}
    assert _identity(SimpleNamespace(**values, st_ctime_ns=3)) == _identity(SimpleNamespace(**values, st_ctime_ns=7))


@pytest.mark.parametrize("change", ["replace", "grow", "rewrite_same_size"])
def test_operator_file_change_during_read_is_rejected_without_reflection(tmp_path, monkeypatch, change):
    tmp_path.chmod(0o700)
    path = tmp_path / "private-config.json"
    payload = write_config(path)
    original = os.read
    changed = False

    def mutate_after_read(descriptor, maximum):
        nonlocal changed
        data = original(descriptor, maximum)
        if not changed:
            changed = True
            if change == "replace":
                replacement = tmp_path / "replacement.json"
                replacement.write_bytes(payload)
                replacement.chmod(0o600)
                os.replace(replacement, path)
            elif change == "grow":
                path.write_bytes(payload + b"synthetic-private-tail")
            else:
                path.write_bytes(b"x" * len(payload))
        return data

    monkeypatch.setattr(os, "read", mutate_after_read)
    with pytest.raises(ConfigurationError) as error:
        load_settings(path)
    assert str(path) not in str(error.value) and "synthetic-private-tail" not in str(error.value)


@pytest.mark.skipif(os.name != "posix", reason="POSIX private-directory policy")
def test_private_references_require_owner_controlled_parent_and_file(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "credential"
    path.write_text("synthetic-private-reference")
    path.chmod(0o600)
    reference = PrivateReference(kind="file", name=str(path))
    assert reference.resolve() == "synthetic-private-reference"
    tmp_path.chmod(0o777)
    try:
        with pytest.raises(ConfigurationError):
            reference.resolve()
    finally:
        tmp_path.chmod(0o700)
    path.chmod(0o644)
    with pytest.raises(ConfigurationError):
        reference.resolve()


@pytest.mark.skipif(os.name != "posix", reason="Linux symlink/FIFO boundary")
@pytest.mark.parametrize("kind", ["fifo", "symlink", "parent_symlink"])
def test_configuration_and_private_ref_refuse_special_paths(tmp_path, kind):
    tmp_path.chmod(0o700)
    path = tmp_path / "special"
    if kind == "fifo":
        os.mkfifo(path, 0o600)
    elif kind == "symlink":
        target = tmp_path / "target"
        write_config(target)
        path.symlink_to(target)
    else:
        real_parent = tmp_path / "real-parent"
        real_parent.mkdir(mode=0o700)
        write_config(real_parent / "config.json")
        path.symlink_to(real_parent, target_is_directory=True)
        path = path / "config.json"
    for read in (lambda: load_settings(path), lambda: PrivateReference(kind="file", name=str(path)).resolve()):
        with pytest.raises(ConfigurationError) as error:
            read()
        assert str(path) not in str(error.value)


def test_oversized_operator_file_fails_before_content_decode(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "large"
    path.write_bytes(b"x" * 65537)
    path.chmod(0o600)
    with pytest.raises(OperatorFileError):
        read_operator_file(path)
