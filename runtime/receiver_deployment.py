"""Canonical deployment policy bound by the Node endpoint registration."""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import re
import stat
import types
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from runtime.receiver_config import ReceiverRuntimeConfig
from runtime.receiver_crypto import canonical, key_fingerprint, sign
from runtime.receiver_models import EndpointBinding

REFERENCE = re.compile(
    r"^runtime_deployment(?:\.[A-Za-z_][A-Za-z0-9_]*)+:[A-Za-z_][A-Za-z0-9_]*$"
)


class FactoryBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    reference: str
    module_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    package_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    callable_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    origin_path_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    install_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    distribution_record_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


@dataclass(frozen=True, slots=True)
class ReceiverProcessConfig:
    runtime: ReceiverRuntimeConfig
    factory: FactoryBinding
    deployment_policy_sha256: str


def _source_identity(path: Path) -> tuple[int, int, int, int, int, int]:
    absolute = path.absolute()
    if absolute.resolve() != absolute or path.is_symlink():
        raise ValueError("deployment package origin contains a symlink")
    info = path.stat(follow_symlinks=False)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) & 0o022):
        raise ValueError("deployment package origin is not owner-controlled")
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_nlink


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _code_value(value: types.CodeType) -> dict[str, Any]:
    constants = [
        {"code": _code_value(item)} if isinstance(item, types.CodeType) else repr(item)
        for item in value.co_consts
    ]
    return {
        "argcount": value.co_argcount,
        "posonlyargcount": value.co_posonlyargcount,
        "kwonlyargcount": value.co_kwonlyargcount,
        "flags": value.co_flags,
        "code": value.co_code.hex(),
        "consts": constants,
        "names": value.co_names,
        "varnames": value.co_varnames,
        "freevars": value.co_freevars,
        "cellvars": value.co_cellvars,
    }


def callable_sha256(function) -> str:
    code = getattr(function, "__code__", None)
    if not isinstance(code, types.CodeType):
        raise TypeError("deployment factory must be a Python function")
    return hashlib.sha256(canonical(_code_value(code))).hexdigest()


def _installation_evidence(origin: Path) -> tuple[str, str]:
    site_packages = origin.parents[1]
    install_root = site_packages.parents[2]
    manifest = install_root / "receiver-install-manifest.json"
    records = list(site_packages.glob("*.dist-info/RECORD"))
    if manifest.is_file() and len(records) == 1:
        return _file_sha256(manifest), _file_sha256(records[0])
    marker = hashlib.sha256(b"uninstalled-source").hexdigest()
    return marker, marker


def inspect_factory_files(reference: str) -> tuple[Path, tuple[int, ...], str, str, str, str, str]:
    if not REFERENCE.fullmatch(reference):
        raise ValueError("deployment factory reference is not allowlisted")
    module_name, _ = reference.split(":", 1)
    spec = importlib.util.find_spec(module_name)
    package_spec = importlib.util.find_spec("runtime_deployment")
    if spec is None or not spec.origin or package_spec is None or not package_spec.origin:
        raise ValueError("deployment package origin is unavailable")
    origin = Path(spec.origin)
    package_origin = Path(package_spec.origin)
    identity = _source_identity(origin)
    _source_identity(package_origin)
    manifest_sha, record_sha = _installation_evidence(origin)
    return (
        origin, identity, _file_sha256(origin), _file_sha256(package_origin),
        hashlib.sha256(str(origin.absolute()).encode()).hexdigest(), manifest_sha, record_sha,
    )


def inspect_factory(reference: str) -> tuple[FactoryBinding, Any, Path, tuple[int, ...]]:
    (origin, identity, module_sha, package_sha, origin_path_sha,
     manifest_sha, record_sha) = inspect_factory_files(reference)
    module_name, function_name = reference.split(":", 1)
    module = importlib.import_module(module_name)
    if Path(module.__file__).resolve() != origin.resolve():
        raise ValueError("deployment module import origin changed")
    factory = getattr(module, function_name, None)
    if (not callable(factory) or factory.__module__ != module_name
            or factory.__name__ != function_name
            or Path(factory.__code__.co_filename).resolve() != origin.resolve()
            or getattr(module, function_name) is not factory):
        raise ValueError("deployment factory callable identity changed")
    binding = FactoryBinding(
        reference=reference, module_sha256=module_sha, package_sha256=package_sha,
        callable_sha256=callable_sha256(factory), origin_path_sha256=origin_path_sha,
        install_manifest_sha256=manifest_sha, distribution_record_sha256=record_sha,
    )
    return binding, factory, origin, identity


def _reference(path: str, kind: str) -> dict[str, str]:
    return {
        "kind": kind,
        "path_sha256": hashlib.sha256(str(Path(path).absolute()).encode()).hexdigest(),
    }


def deployment_policy(config: ReceiverRuntimeConfig, factory: FactoryBinding) -> dict[str, Any]:
    registration = config.binding.registration.model_dump(mode="json")
    registration.pop("config_sha256")
    return {
        "schema_version": "acs-receiver-deployment-policy/1",
        "factory": factory.model_dump(mode="json"),
        "registration_without_config_digest": registration,
        "connection": {
            "connection_ref": config.binding.registration.connection_ref,
            "locator_host": config.binding.locator_host,
            "locator_port": config.binding.locator_port,
            "route_class": config.binding.route_class,
        },
        "authority_key": {
            "key_id": config.authority_key_id,
            "revision": config.authority_key_revision,
            "public_key_fingerprint": config.authority_public_key_fingerprint,
        },
        "node_key": {
            "key_id": config.binding.node_key_id,
            "public_key_fingerprint": key_fingerprint(config.binding.node_public_key),
        },
        "references": {
            "tls_certificate": _reference(config.tls_cert_path, "tls-certificate"),
            "tls_private_key": _reference(config.tls_key_path, "tls-private-key"),
            "node_signing_key": _reference(config.node_signing_key_path, "node-signing-key"),
            "ledger": _reference(config.ledger_path, "sqlite-journal"),
        },
        "journal_policy": "posix-owner-0700-parent-0600-file-single-link-witness",
        "maximum_body_bytes": config.maximum_body_bytes,
        "clock_skew_seconds": config.clock_skew_seconds,
        "expected_boot_incarnation": config.expected_boot_incarnation,
        "journal_generation": config.journal_generation,
        "old_boot_isolation_ref_sha256": (
            hashlib.sha256(config.old_boot_isolation_ref.encode()).hexdigest()
            if config.old_boot_isolation_ref else None
        ),
    }


def deployment_policy_sha256(config: ReceiverRuntimeConfig, factory: FactoryBinding) -> str:
    return hashlib.sha256(canonical(deployment_policy(config, factory))).hexdigest()


def bind_process_config(config: ReceiverRuntimeConfig, factory: FactoryBinding,
                        node_signing_key) -> ReceiverProcessConfig:
    digest = deployment_policy_sha256(config, factory)
    registration = config.binding.registration.model_copy(update={"config_sha256": digest})
    binding = config.binding.model_copy(update={
        "registration": registration,
        "registration_signature": sign(node_signing_key, registration),
    })
    bound = replace(config, binding=binding)
    if deployment_policy_sha256(bound, factory) != digest:
        raise ValueError("receiver deployment policy construction is not stable")
    return ReceiverProcessConfig(bound, factory, digest)


def dump_process_config(process: ReceiverProcessConfig) -> str:
    runtime = {field.name: getattr(process.runtime, field.name) for field in fields(process.runtime)}
    runtime["binding"] = process.runtime.binding.model_dump(mode="json")
    value = {
        "schema_version": "acs-receiver-process-config/1",
        "runtime": runtime,
        "factory": process.factory.model_dump(mode="json"),
        "deployment_policy_sha256": process.deployment_policy_sha256,
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def parse_process_config(raw: str) -> ReceiverProcessConfig:
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "runtime", "factory", "deployment_policy_sha256",
    } or value["schema_version"] != "acs-receiver-process-config/1":
        raise ValueError("receiver process configuration shape differs")
    runtime = value["runtime"]
    if not isinstance(runtime, dict):
        raise TypeError("receiver runtime configuration must be an object")
    expected = {field.name for field in fields(ReceiverRuntimeConfig)}
    if set(runtime) != expected:
        raise ValueError("receiver runtime configuration fields differ")
    binding = EndpointBinding.model_validate_json(json.dumps(runtime.pop("binding")), strict=True)
    config = ReceiverRuntimeConfig(binding=binding, **runtime)
    factory = FactoryBinding.model_validate(value["factory"], strict=True)
    digest = value["deployment_policy_sha256"]
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("receiver deployment policy digest is invalid")
    return ReceiverProcessConfig(config, factory, digest)
