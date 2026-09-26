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
    _owner_directory,
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


def owner_file_sha256(path: Path) -> str:
    """Hash a small owner-only reference through its pinned POSIX parent."""
    parent_fd = _owner_directory(path.parent)
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
        try:
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_nlink != 1
                or before.st_size > 100_000
            ):
                raise RuntimeError("native scene owner reference is not a bounded 0600 file")
            data = bytearray()
            while chunk := os.read(descriptor, min(65536, 100_001 - len(data))):
                data.extend(chunk)
                if len(data) > 100_000:
                    break
            after = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if len(data) > 100_000 or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
                raise RuntimeError("native scene owner reference changed during read")
            return hashlib.sha256(data).hexdigest()
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_fd)


def provision(
    source_site: Path,
    destination: Path,
    profile: Path,
    *,
    codex_scene_profile: Path | None = None,
    budget_decision: Path | None = None,
    opencode_scene_profile: Path | None = None,
    opencode_budget_decision: Path | None = None,
) -> dict[str, object]:
    if os.name != "posix":
        raise RuntimeError("P1 runtime environment provisioning is POSIX-only")
    if not source_site.is_absolute() or not destination.is_absolute() or not profile.is_absolute():
        raise RuntimeError("provision paths must be absolute")
    if (codex_scene_profile is None) != (budget_decision is None):
        raise RuntimeError("Codex scene profile and budget decision must be paired")
    if (opencode_scene_profile is None) != (opencode_budget_decision is None):
        raise RuntimeError("OpenCode scene profile and budget decision must be paired")
    if any(
        path is not None and not path.is_absolute()
        for path in (
            codex_scene_profile, budget_decision,
            opencode_scene_profile, opencode_budget_decision,
        )
    ):
        raise RuntimeError("native scene owner file paths must be absolute")
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
        if codex_scene_profile is not None and budget_decision is not None:
            validation["codex_scene_profile"] = {
                "path": str(codex_scene_profile),
                "sha256": owner_file_sha256(codex_scene_profile),
            }
            validation["budget_decision"] = {
                "path": str(budget_decision),
                "sha256": owner_file_sha256(budget_decision),
            }
        if opencode_scene_profile is not None and opencode_budget_decision is not None:
            validation["opencode_scene_profile"] = {
                "path": str(opencode_scene_profile),
                "sha256": owner_file_sha256(opencode_scene_profile),
            }
            validation["opencode_budget_decision"] = {
                "path": str(opencode_budget_decision),
                "sha256": owner_file_sha256(opencode_budget_decision),
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
    for name in (
        "codex_scene_profile", "budget_decision",
        "opencode_scene_profile", "opencode_budget_decision",
    ):
        if name in provisioned:
            plan["runtime_profile"][name] = provisioned[name]
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
    parser.add_argument("--codex-scene-profile", type=Path)
    parser.add_argument("--budget-decision", type=Path)
    parser.add_argument("--opencode-scene-profile", type=Path)
    parser.add_argument("--opencode-budget-decision", type=Path)
    args = parser.parse_args(argv)
    try:
        result = provision(
            args.source_site,
            args.destination,
            args.profile,
            codex_scene_profile=args.codex_scene_profile,
            budget_decision=args.budget_decision,
            opencode_scene_profile=args.opencode_scene_profile,
            opencode_budget_decision=args.opencode_budget_decision,
        )
        if args.plan is not None:
            attach_plan(args.plan, result)
        print(json.dumps({"status": "provisioned", **result}, sort_keys=True))
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)[:300]}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
