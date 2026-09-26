"""Verify the complete installed receiver distribution and review wheel contents."""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import stat
import sys
import zipfile
from importlib import metadata
from pathlib import Path

REQUIRED = (
    "runtime/receiver_entry.py",
    "runtime/receiver_install.py",
    "runtime/receiver.py",
    "runtime/receiver_config.py",
    "runtime/receiver_crypto.py",
    "runtime/receiver_delivery.py",
    "runtime/receiver_deployment.py",
    "runtime/receiver_domain.py",
    "runtime/receiver_models.py",
    "runtime/receiver_paths.py",
    "runtime/receiver_provision.py",
    "runtime/remote_endpoint.py",
    "runtime/sender.py",
    "runtime_deployment/__init__.py",
    "runtime_deployment/receiver_p1.py",
)
INSTALL_MANIFEST = "receiver-install-manifest.json"


def record_hash(data: bytes) -> str:
    value = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return "sha256=" + value


def _expected_hash(encoded: str) -> str:
    algorithm, separator, value = encoded.partition("=")
    if algorithm != "sha256" or not separator:
        raise ValueError("receiver distribution RECORD hash is unsupported")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).hex()


def _safe_installed_file(path: Path) -> None:
    absolute = path.absolute()
    normalized = Path(os.path.normpath(absolute))
    if normalized.resolve() != normalized or path.is_symlink():
        raise ValueError("receiver distribution path contains a symlink")
    info = path.stat(follow_symlinks=False)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) & 0o022):
        raise ValueError("receiver distribution file is not owner-controlled")


def _record_rows(raw: str) -> list[list[str]]:
    rows = list(csv.reader(io.StringIO(raw)))
    if any(len(row) != 3 for row in rows) or len({row[0] for row in rows}) != len(rows):
        raise ValueError("receiver distribution RECORD is malformed")
    return rows


def _record_map(raw: str) -> dict[str, tuple[str, str]]:
    return {row[0]: (row[1], row[2]) for row in _record_rows(raw)}


def _code_paths(names) -> set[str]:
    return {name for name in names if name.endswith(".py")
            and name.startswith(("runtime/", "runtime_deployment/"))}


def verify_installed_distribution() -> dict[str, object]:
    distribution = metadata.distribution("agent-collaboration-runtime")
    files = tuple(distribution.files or ())
    records = [item for item in files if str(item).endswith(".dist-info/RECORD")]
    if len(records) != 1:
        raise ValueError("receiver distribution has no unique RECORD")
    record_relative = str(records[0])
    record_path = Path(distribution.locate_file(records[0]))
    _safe_installed_file(record_path)
    recorded = _record_map(record_path.read_text(encoding="utf-8"))
    if record_relative not in recorded or recorded[record_relative] != ("", ""):
        raise ValueError("receiver distribution RECORD self-entry differs")
    code_paths = _code_paths(recorded)
    if any(relative not in code_paths for relative in REQUIRED):
        raise ValueError("receiver distribution RECORD omits required package content")
    evidence: dict[str, str] = {}
    installed_paths: set[Path] = {record_path.resolve()}
    for relative, (encoded, size) in recorded.items():
        if relative == record_relative:
            continue
        if not encoded or not size.isdigit():
            raise ValueError("receiver distribution RECORD has an unhashed installed file")
        path = Path(distribution.locate_file(relative))
        _safe_installed_file(path)
        data = path.read_bytes()
        if len(data) != int(size) or hashlib.sha256(data).hexdigest() != _expected_hash(encoded):
            raise ValueError("receiver distribution file differs from RECORD")
        evidence[relative] = hashlib.sha256(data).hexdigest()
        installed_paths.add(path.resolve())
    site_packages = Path(distribution.locate_file(".")).resolve()
    install_root = site_packages.parents[2]
    manifest_path = install_root / INSTALL_MANIFEST
    _safe_installed_file(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict)
            or manifest.get("schema_version") != "acs-receiver-install/1"
            or manifest.get("record_sha256") != hashlib.sha256(record_path.read_bytes()).hexdigest()
            or manifest.get("files") != evidence
            or manifest.get("site_packages") != str(site_packages.relative_to(install_root))):
        raise ValueError("receiver installation manifest differs from installed distribution")
    launcher = install_root / "bin" / "acs-receiver"
    provisioner = install_root / "bin" / "acs-receiver-provision"
    _safe_installed_file(launcher)
    _safe_installed_file(provisioner)
    interpreter = Path(sys.executable).absolute()
    if (manifest.get("interpreter_path") != str(interpreter)
            or manifest.get("interpreter_path_sha256")
            != hashlib.sha256(str(interpreter).encode()).hexdigest()
            or manifest.get("interpreter_sha256") != hashlib.sha256(interpreter.read_bytes()).hexdigest()
            or not launcher.read_bytes().startswith(f"#!{interpreter}\n".encode())
            or not provisioner.read_bytes().startswith(f"#!{interpreter}\n".encode())
            or hashlib.sha256(launcher.read_bytes()).hexdigest() != manifest.get("launcher_sha256")
            or hashlib.sha256(provisioner.read_bytes()).hexdigest()
            != manifest.get("provisioner_sha256")):
        raise ValueError("receiver interpreter or launcher differs from installation manifest")
    actual_paths = {path.resolve() for path in install_root.rglob("*") if path.is_file()}
    installed_paths.add(manifest_path.resolve())
    if actual_paths != installed_paths:
        raise ValueError("receiver installation contains extra or missing files")
    return {
        "files": evidence,
        "record": hashlib.sha256(record_path.read_bytes()).hexdigest(),
        "install_manifest": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "install_root": str(install_root),
    }


def verify_wheel_archive(path: str | Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        records = [name for name in names if name.endswith(".dist-info/RECORD")]
        if len(records) != 1:
            raise ValueError("receiver wheel has no unique RECORD")
        recorded = _record_map(archive.read(records[0]).decode("utf-8"))
        code_paths = _code_paths(names)
        if any(relative not in code_paths for relative in REQUIRED):
            raise ValueError("receiver wheel omits required package content")
        if _code_paths(recorded) != code_paths:
            raise ValueError("receiver wheel code and RECORD inventory differ")
        evidence: dict[str, str] = {}
        for relative in sorted(code_paths):
            encoded, size = recorded.get(relative, ("", ""))
            data = archive.read(relative)
            if (not encoded or size != str(len(data))
                    or hashlib.sha256(data).hexdigest() != _expected_hash(encoded)):
                raise ValueError("receiver wheel content differs from RECORD")
            evidence[relative] = hashlib.sha256(data).hexdigest()
        return evidence
