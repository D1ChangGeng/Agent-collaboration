"""Test-only host provisioning for owner-controlled deployment module files."""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import runtime_deployment
from runtime.receiver_deployment import FactoryBinding, inspect_factory
from runtime_deployment import receiver_p1


def source_factory_binding():
    for source in (runtime_deployment.__file__, receiver_p1.__file__):
        path = Path(source)
        path.chmod(stat.S_IMODE(path.stat().st_mode) & ~0o022)
    return inspect_factory("runtime_deployment.receiver_p1:callbacks")


def configured_factory_binding():
    installed = os.getenv("ACS_INSTALLED_RECEIVER")
    if not installed:
        return source_factory_binding()
    completed = subprocess.run(
        [installed, "--factory-binding"], cwd=Path(installed).parent,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1"},
        capture_output=True, text=True, check=True,
    )
    return FactoryBinding.model_validate_json(completed.stdout, strict=True), None, None, None
