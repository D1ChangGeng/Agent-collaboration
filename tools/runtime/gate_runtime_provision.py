"""Provision an owner-private Python environment for the P1 Gate sandbox."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path

from tools.runtime.gate_runner import (
    remove_private_stage,
    strict_json,
    validate_runtime_profile,
    write_atomic,
)

MAX_FILES = 100_000
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def provision(source_site: Path, destination: Path, profile: Path) -> dict[str, object]:
    if os.name != "posix":
        raise RuntimeError("P1 runtime environment provisioning is POSIX-only")
    if not source_site.is_absolute() or not destination.is_absolute() or not profile.is_absolute():
        raise RuntimeError("provision paths must be absolute")
    if destination.exists():
        raise RuntimeError("runtime environment destination already exists")
    files = [path for path in source_site.rglob("*") if path.is_file()]
    directories = [path for path in source_site.rglob("*") if path.is_dir()]
    if (source_site.is_symlink() or any(path.is_symlink() for path in (*directories, *files))
            or len(files) > MAX_FILES or sum(path.stat().st_size for path in files) > MAX_TOTAL_BYTES):
        raise RuntimeError("runtime dependency source is unsafe or outside bounds")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.stage-", dir=destination.parent))
    stage.chmod(0o700)
    published = False
    try:
        site = stage / "site"
        shutil.copytree(source_site, site)
        probe = Path(__file__).with_name("p1_profile_probe.py")
        shutil.copyfile(probe, stage / "p1_profile_probe.py")
        binary = stage / "bin"
        binary.mkdir(mode=0o700)
        wrapper = binary / "python"
        wrapper.write_text(
            "#!/bin/sh\nPYTHONPATH=/run/acs-p1/runtime/site "
            "exec /usr/bin/python3 \"$@\"\n",
            encoding="utf-8",
        )
        for path in sorted(stage.rglob("*")):
            path.chmod(0o700 if path.is_dir() else 0o600)
        wrapper.chmod(0o700)
        installed: dict[str, dict[str, object]] = {}
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                installed[path.relative_to(stage).as_posix()] = {
                    "sha256": sha256(path), "mode": stat.S_IMODE(path.stat().st_mode),
                }
        manifest = {
            "schema_version": "acs-p1-runtime-environment/1",
            "files": installed,
        }
        manifest_path = stage / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8",
        )
        manifest_path.chmod(0o600)
        profile_sha256 = sha256(profile)
        manifest_sha256 = sha256(manifest_path)
        validation = {
            "profile_path": str(profile),
            "profile_sha256": profile_sha256,
            "runtime_environment_root": str(stage),
            "runtime_environment_manifest_sha256": manifest_sha256,
            "network_mode": "host_loopback_providers",
            "postgresql_endpoint": "127.0.0.1:54329",
            "temporal_endpoint": "127.0.0.1:7239",
        }
        validate_runtime_profile(validation)
        os.replace(stage, destination)
        published = True
        installed_validation = {
            **validation, "runtime_environment_root": str(destination),
        }
        validate_runtime_profile(installed_validation)
        parent_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        return {
            **installed_validation,
            "file_count": len(installed),
        }
    except BaseException:
        remove_private_stage(destination if published else stage)
        raise


def attach_plan(plan_path: Path, provisioned: dict[str, object]) -> None:
    plan = strict_json(plan_path.read_bytes())
    if not isinstance(plan, dict) or plan.get("runtime_profile") is not None:
        raise RuntimeError("runner plan already has a runtime profile")
    plan["runtime_profile"] = {
        key: provisioned[key] for key in (
            "profile_path", "profile_sha256", "runtime_environment_root",
            "runtime_environment_manifest_sha256", "network_mode",
            "postgresql_endpoint", "temporal_endpoint",
        )
    }
    write_atomic(
        plan_path,
        json.dumps(plan, indent=2, ensure_ascii=False).encode("utf-8") + b"\n",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-site", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
    args = parser.parse_args(argv)
    try:
        result = provision(args.source_site, args.destination, args.profile)
        if args.plan is not None:
            attach_plan(args.plan, result)
        print(json.dumps({"status": "provisioned", **result}, sort_keys=True))
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)[:300]}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
