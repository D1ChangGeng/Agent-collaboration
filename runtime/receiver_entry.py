"""Fail-closed POSIX receiver process entrypoint."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from runtime.receiver_deployment import (
    ReceiverProcessConfig,
    callable_sha256,
    deployment_policy_sha256,
    inspect_factory,
    inspect_factory_files,
    parse_process_config,
)
from runtime.receiver_install import verify_installed_distribution
from runtime.receiver_paths import open_validated_file
from runtime.remote_endpoint import serve


@dataclass(frozen=True, slots=True)
class DeploymentCallbacks:
    deployment_policy_sha256: str
    endpoint_id: str
    runtime_id: str
    authorize_current: object
    native_invoke: object


def load_process_config(path: str | Path) -> ReceiverProcessConfig:
    descriptor, _ = open_validated_file(path, private=True)
    try:
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as source:
            raw = source.read(1_048_577)
    finally:
        os.close(descriptor)
    if len(raw.encode()) > 1_048_576:
        raise ValueError("receiver configuration exceeds bound")
    process = parse_process_config(raw)
    process.runtime.validate()
    observed = deployment_policy_sha256(process.runtime, process.factory)
    if (observed != process.deployment_policy_sha256
            or observed != process.runtime.binding.registration.config_sha256):
        raise ValueError("receiver deployment policy digest differs from registration")
    return process


def load_callbacks(process: ReceiverProcessConfig) -> DeploymentCallbacks:
    (origin, identity, module_sha, package_sha, origin_path_sha,
     manifest_sha, record_sha) = inspect_factory_files(process.factory.reference)
    if (module_sha, package_sha, origin_path_sha, manifest_sha, record_sha) != (
        process.factory.module_sha256, process.factory.package_sha256,
        process.factory.origin_path_sha256, process.factory.install_manifest_sha256,
        process.factory.distribution_record_sha256,
    ):
        raise ValueError("receiver deployment package file digest differs before import")
    observed, factory, origin, identity = inspect_factory(process.factory.reference)
    if observed != process.factory:
        raise ValueError("receiver deployment factory binding differs")
    callbacks = factory(process.runtime, process.deployment_policy_sha256)
    if (not isinstance(callbacks, DeploymentCallbacks)
            or callbacks.deployment_policy_sha256 != process.deployment_policy_sha256
            or callbacks.endpoint_id != process.runtime.binding.registration.endpoint_id
            or callbacks.runtime_id != process.runtime.binding.registration.runtime_id
            or not callable(callbacks.authorize_current) or not callable(callbacks.native_invoke)):
        raise TypeError("receiver deployment callbacks are not bound to configuration")
    info = origin.stat(follow_symlinks=False)
    after_identity = (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_nlink)
    module_name, function_name = process.factory.reference.split(":", 1)
    module = __import__(module_name, fromlist=[function_name])
    current = getattr(module, function_name, None)
    if (after_identity != identity
            or hashlib.sha256(origin.read_bytes()).hexdigest() != observed.module_sha256
            or current is not factory or callable_sha256(current) != observed.callable_sha256):
        raise ValueError("receiver deployment factory changed after construction")
    return callbacks


def main(argv=None):
    parser = argparse.ArgumentParser(prog="acs-receiver")
    parser.add_argument("--config")
    parser.add_argument("--verify-install", action="store_true")
    parser.add_argument("--factory-binding", action="store_true")
    arguments = parser.parse_args(argv)
    install = verify_installed_distribution()
    if arguments.verify_install:
        print(json.dumps(install, sort_keys=True))
        return 0
    if arguments.factory_binding:
        binding, _, _, _ = inspect_factory("runtime_deployment.receiver_p1:callbacks")
        print(binding.model_dump_json())
        return 0
    if not arguments.config:
        parser.error("--config is required")
    process = load_process_config(arguments.config)
    callbacks = load_callbacks(process)

    def ready_check():
        reloaded = load_process_config(arguments.config)
        current = load_callbacks(reloaded)
        return (
            reloaded == process
            and current.deployment_policy_sha256 == callbacks.deployment_policy_sha256
            and (current.endpoint_id, current.runtime_id)
            == (callbacks.endpoint_id, callbacks.runtime_id)
        )

    serve(
        process.runtime,
        authorize_current=callbacks.authorize_current,
        native_invoke=callbacks.native_invoke,
        ready_check=ready_check,
    )
