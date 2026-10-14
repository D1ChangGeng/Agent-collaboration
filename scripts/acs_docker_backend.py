"""Inspect an existing Docker data backend and preview a shared-runtime repair."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


def output(*args: str) -> str:
    return subprocess.check_output(args, text=True, timeout=12).strip()


def docker_backend() -> dict:
    info = json.loads(output("docker", "info", "--format", "{{json .}}"))
    return {
        "data_root": info["DockerRootDir"],
        "containerd_address": info.get("Containerd", {}).get("Address"),
        "storage_driver": info.get("Driver"),
        "server_version": info.get("ServerVersion"),
    }


def readable_services(project: str) -> dict:
    if not re.fullmatch(r"acs-[a-zA-Z0-9-]+", project):
        raise ValueError("provider_project_invalid")
    lines = output(
        "docker",
        "ps",
        "-a",
        "--filter",
        "label=com.docker.compose.project=" + project,
        "--format",
        "{{json .}}",
    )
    items = [json.loads(line) for line in lines.splitlines() if line]
    return {"count": len(items), "named": bool(items) and all(item.get("Names") for item in items)}


def _regular(path: Path) -> None:
    if (
        path.is_symlink()
        or not path.is_file()
        or any(parent.is_symlink() for parent in path.parents)
    ):
        raise ValueError("backend_reference_requires_regular_file")


def repair_plan(
    provider_config: Path, *, config: Path = Path("/etc/containerd/config.toml")
) -> dict:
    _regular(provider_config)
    provider = json.loads(provider_config.read_text(encoding="utf-8"))
    project = provider.get("compose_project", "")
    backend = docker_backend()
    root = Path(backend["data_root"])
    if not root.is_absolute() or root.is_symlink() or any(p.is_symlink() for p in root.parents):
        raise ValueError("backend_data_root_requires_absolute_directory")
    services = readable_services(project)
    if services["named"]:
        return {
            "schema_version": "acs-docker-backend-repair/1",
            "state": "ready",
            "project": project,
            "backend": backend,
            "provider_container_count": services["count"],
            "changes": [],
        }
    store = root / "containerd/daemon"
    metadata = store / "io.containerd.metadata.v1.bolt/meta.db"
    _regular(metadata)
    snapshots = store / "io.containerd.snapshotter.v1.overlayfs/snapshots"
    if not snapshots.is_dir() or snapshots.is_symlink() or not any(snapshots.iterdir()):
        raise ValueError("existing_containerd_snapshots_unavailable")
    if not re.fullmatch(r"acs-[a-zA-Z0-9-]+", project):
        raise ValueError("provider_project_invalid")
    owned = []
    for item in (root / "containers").glob("*/config.v2.json"):
        _regular(item)
        data = json.loads(item.read_text(encoding="utf-8"))
        labels = data.get("Config", {}).get("Labels", {})
        if labels.get("com.docker.compose.project") == project:
            owned.append(data.get("ID", item.parent.name))
    if not owned:
        raise ValueError("existing_provider_containers_unavailable")
    namespaces = output("ctr", "namespaces", "list", "--quiet").splitlines()
    running = sum(
        len(output("ctr", "--namespace", ns, "tasks", "list", "--quiet").splitlines())
        for ns in namespaces
    )
    before = None
    if config.exists():
        _regular(config)
        before = config.read_bytes()
    daemon = json.loads(output("docker", "context", "inspect"))[0]
    daemon_host = os.environ.get("DOCKER_HOST") or daemon.get("Endpoints", {}).get(
        "docker", {}
    ).get("Host", "")
    reasons = []
    if not daemon_host.startswith("unix://"):
        reasons.append("selected_docker_context_is_remote")
    if running:
        reasons.append("shared_runtime_has_running_tasks")
    if before is not None:
        reasons.append("existing_containerd_configuration_requires_merge")
    if backend["containerd_address"] != "/run/containerd/containerd.sock":
        reasons.append("containerd_address_requires_review")
    plan = {
        "schema_version": "acs-docker-backend-repair/1",
        "state": "review_required" if reasons else "planned",
        "provider_config": str(provider_config.absolute()),
        "project": project,
        "backend": backend,
        "existing_root": str(store),
        "config": str(config),
        "existing_config_sha256": hashlib.sha256(before).hexdigest() if before else None,
        "existing_provider_container_count": len(owned),
        "running_tasks": running,
        "shared_services": ["docker", "containerd"],
        "reasons": reasons,
    }
    plan["plan_digest"] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    return plan


def apply_repair(provider_config: Path, expected: str, backup: Path, *, confirmed: bool) -> dict:
    if not confirmed:
        raise ValueError("confirm_shared_runtime_changes_before_apply")
    if os.geteuid() != 0:
        raise ValueError("shared_runtime_repair_requires_os_administrator")
    plan = repair_plan(provider_config)
    if plan["state"] != "planned" or plan["plan_digest"] != expected:
        raise ValueError("backend_repair_plan_changed")
    config = Path(plan["config"])
    if not backup.is_absolute() or backup.exists() or any(p.is_symlink() for p in backup.parents):
        raise ValueError("select_new_absolute_backup_directory")
    backup.mkdir(mode=0o700, parents=True)
    record = backup / "repair-plan.json"
    record.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    record.chmod(0o600)
    for name, service in (("docker-unit.txt", "docker"), ("containerd-unit.txt", "containerd")):
        target = backup / name
        target.write_text(output("systemctl", "cat", service) + "\n", encoding="utf-8")
        target.chmod(0o600)
    config.parent.mkdir(parents=True, exist_ok=True)
    if config.parent.is_symlink():
        raise ValueError("containerd_config_directory_requires_review")
    config_created = False
    services_changed = False
    try:
        with config.open("x", encoding="utf-8") as target:
            config_created = True
            target.write(
                "version = 3\nroot = "
                + json.dumps(plan["existing_root"])
                + '\nstate = "/run/containerd"\n'
            )
        config.chmod(0o644)
        subprocess.run(
            ["containerd", "--config", str(config), "config", "dump"],
            check=True,
            stdout=subprocess.DEVNULL,
            timeout=10,
        )
        services_changed = True
        for args in (
            ("stop", "docker.socket"),
            ("stop", "docker"),
            ("restart", "containerd"),
            ("start", "docker.socket"),
            ("start", "docker"),
        ):
            subprocess.run(["systemctl", *args], check=True, timeout=55)
        services = readable_services(plan["project"])
        if services["count"] != plan["existing_provider_container_count"] or not services["named"]:
            raise ValueError("existing_provider_container_readback_failed")
    except BaseException:
        if config_created:
            config.unlink(missing_ok=True)
        for args in (
            ("stop", "docker.socket"),
            ("stop", "docker"),
            ("restart", "containerd"),
            ("start", "docker.socket"),
            ("start", "docker"),
        ):
            if services_changed:
                subprocess.run(["systemctl", *args], check=True, timeout=55)
        raise
    return {
        "schema_version": plan["schema_version"],
        "state": "repaired",
        "existing_root": plan["existing_root"],
        "provider_containers": services["count"],
        "backup": str(backup),
        "data_kept_in_place": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-config", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--shared-runtime-confirmed", action="store_true")
    parser.add_argument("--plan-digest")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    try:
        if args.apply:
            if not args.plan_digest or args.backup is None:
                raise ValueError("supply_reviewed_plan_digest_and_backup")
            result = apply_repair(
                args.provider_config,
                args.plan_digest,
                args.backup,
                confirmed=args.shared_runtime_confirmed,
            )
        else:
            result = repair_plan(args.provider_config)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        print(
            json.dumps({"state": "unavailable", "reason": "docker_backend_repair_requires_review"})
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
