"""Owner-local scheduling and compatible stable Release updates."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

INTERVAL = 86400
COMPATIBILITY = "acs-local-v1"
MARKER = "# ACS automatic updates"


def version_number(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", value):
        raise ValueError("stable_release_version_required")
    return tuple(int(item) for item in value[1:].split("."))


def latest_release(repository: str) -> dict:
    request = urllib.request.Request(f"https://api.github.com/repos/{repository}/releases/latest",
                                     headers={"Accept": "application/vnd.github+json", "User-Agent": "acs-update/1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    if not isinstance(result, dict) or result.get("draft") or result.get("prerelease"):
        raise ValueError("stable_published_release_required")
    version_number(result.get("tag_name"))
    return result


def compatible(previous: dict, candidate: dict) -> bool:
    if candidate.get("auto_update", {}).get("compatibility") != COMPATIBILITY:
        return False
    old, new = previous["files"], candidate["files"]
    protected = {"docker-compose.acs-local.yml", "docs/runtime/p2-mcp-tool-contract.json", "LICENSE"}
    protected.update(name for name in set(old) | set(new)
                     if name.startswith("runtime/") and (name.endswith(".sql") or
                        name in {"runtime/migrations.py", "runtime/schema_upgrade.py"}))
    return all(name in old and name in new and old[name]["sha256"] == new[name]["sha256"]
               for name in protected)


def configure_schedule(root: Path, enabled: bool, python: str) -> dict:
    """Register an owner timer, with new-connection checks on every installation."""
    result = {"enabled": enabled, "connection_checks": enabled, "backend": "connection",
              "state": "active" if enabled else "disabled", "interval_seconds": INTERVAL}
    if sys.platform != "linux":
        return result
    command = [python, str(root / "acs_bootstrap.py"), "--update", "--apply"]
    if any(ord(c) < 32 for item in [*command, str(root), os.environ.get("PATH", os.defpath)] for c in item):
        raise ValueError("invalid_scheduler_path")
    systemctl = shutil.which("systemctl")
    if systemctl:
        available = subprocess.run([systemctl, "--user", "show-environment"], capture_output=True,
                                   timeout=15, check=False)
        if available.returncode == 0:
            units = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "systemd/user"
            if any(part.is_symlink() for part in (units, *units.parents)):
                raise ValueError("automatic_update_unit_path_is_unsafe")
            units.mkdir(parents=True, exist_ok=True)
            service, timer = units / "acs-auto-update.service", units / "acs-auto-update.timer"
            def quote(value):
                if any(ord(c) < 32 for c in value):
                    raise ValueError("invalid_scheduler_path")
                return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'
            path_env = os.environ.get("PATH", os.defpath)
            service_content = (MARKER + "\n[Unit]\nDescription=ACS automatic Release update\n[Service]\nType=oneshot\n"
                               + "Environment=" + quote("ACS_UPDATE_ROOT=" + str(root)) + "\n"
                               + "Environment=" + quote("PATH=" + path_env) + "\nExecStart=:"
                               + " ".join(quote(item) for item in command) + "\nTimeoutStartSec=30min\n")
            timer_content = (MARKER + "\n[Unit]\nDescription=ACS Release checks\n[Timer]\nOnActiveSec=10min\n"
                             "OnUnitActiveSec=1h\nOnCalendar=daily\nPersistent=true\nRandomizedDelaySec=5min\n"
                             "[Install]\nWantedBy=timers.target\n")
            prior = json.loads((root / "state.json").read_text()).get("auto_update", {}).get("schedule", {})
            digests = {}
            for path, content in ((service, service_content), (timer, timer_content)):
                wanted = hashlib.sha256(content.encode()).hexdigest()
                if path.is_symlink() or (path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() not in
                        {wanted, prior.get("unit_sha256", {}).get(path.name)}):
                    raise ValueError("automatic_update_unit_requires_ownership_review")
                digests[path.name] = wanted
            for path, content in ((service, service_content), (timer, timer_content)):
                path.write_text(content, encoding="utf-8")
            subprocess.run([systemctl, "--user", "daemon-reload"], capture_output=True, timeout=15, check=True)
            subprocess.run([systemctl, "--user", "enable" if enabled else "disable", "--now", timer.name],
                           capture_output=True, timeout=15, check=True)
            active = subprocess.run([systemctl, "--user", "is-active", timer.name], capture_output=True,
                                    timeout=15, check=False).returncode == 0
            return {**result, "backend": "systemd_user", "state": "active" if active else "disabled",
                    "unit_sha256": digests}
    crontab = shutil.which("crontab")
    if crontab:
        existing = subprocess.run([crontab, "-l"], capture_output=True, text=True, timeout=15, check=False)
        if existing.returncode and "no crontab" not in existing.stderr.lower():
            return {**result, "schedule_issue": "crontab_unavailable"}
        prefix = "17 * * * * ACS_UPDATE_ROOT=" + shlex.quote(str(root)).replace("%", "\\%") + " PATH="
        lines = [line for line in existing.stdout.splitlines()
                 if not (line.startswith(prefix) and line.endswith(MARKER))]
        if enabled:
            shell = "ACS_UPDATE_ROOT=" + shlex.quote(str(root)) + " PATH=" + shlex.quote(os.environ.get("PATH", os.defpath))
            shell += " " + shlex.join(command) + " >/dev/null 2>&1"
            lines.append("17 * * * * " + shell.replace("%", "\\%") + " " + MARKER)
        subprocess.run([crontab, "-"], input="\n".join(lines) + "\n", text=True, capture_output=True,
                       timeout=15, check=True)
        return {**result, "backend": "cron", "state": "registered" if enabled else "disabled"}
    return {**result, "schedule_issue": "background_scheduler_unavailable"}


def schedule_status(root: Path, policy: dict) -> dict:
    result = {**policy.get("schedule", {}), "enabled": policy.get("enabled", True)}
    if result.get("backend") == "systemd_user":
        active = subprocess.run(["systemctl", "--user", "is-active", "acs-auto-update.timer"],
                                capture_output=True, timeout=15, check=False).returncode == 0
        result["state"] = "active" if active else "inactive"
    elif result.get("backend") == "cron":
        observed = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=15, check=False)
        prefix = "17 * * * * ACS_UPDATE_ROOT=" + shlex.quote(str(root)).replace("%", "\\%") + " PATH="
        result["state"] = "registered" if observed.returncode == 0 and any(
            line.endswith(MARKER) and line.startswith(prefix) for line in observed.stdout.splitlines()) else "unregistered"
    else:
        result.update(backend="connection", state="active" if result["enabled"] else "disabled")
    return result


def run_update(root: Path, *, apply: bool, force: bool = False) -> dict:
    import acs_bootstrap as bootstrap

    if (root.resolve() != bootstrap.install_root().resolve() or root.is_symlink()
            or (root / "state.json").is_symlink() or not (root / "state.json").is_file()):
        raise ValueError("existing_installation_required")
    if any(part.is_symlink() or getattr(part.lstat(), "st_file_attributes", 0) & 0x400
           for part in (root, *root.parents)):
        raise ValueError("installation_root_path_is_unsafe")
    if os.name == "posix" and (root.stat().st_uid != os.getuid() or stat.S_IMODE(root.stat().st_mode) & 0o077):
        raise ValueError("installation_root_permissions_are_unsafe")
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    machine = bootstrap.observe_machine()
    if bootstrap.machine_binding(machine) != bootstrap.machine_binding(state["machine"]):
        raise ValueError("installation_machine_binding_changed")
    policy = state.get("auto_update", {"enabled": True})
    if not isinstance(policy, dict) or not isinstance(policy.get("enabled", True), bool):
        raise TypeError("automatic_update_policy_requires_review")
    result = {"schema_version": "acs-auto-update/1", "current_version": state["version"], "enabled": policy.get("enabled", True)}
    if not policy.get("enabled", True):
        return {**result, "state": "disabled"}
    if apply and not force and policy.get("next_check", 0) > time.time():
        return {**result, "state": "not_due", "next_check": policy["next_check"]}
    try:
        with bootstrap.installation_lock(root):
            fresh = json.loads((root / "state.json").read_text(encoding="utf-8"))
            if fresh != state:
                return {**result, "state": "retry", "reason": "installation_changed"}
            metadata = latest_release(bootstrap.REPOSITORY)
            latest = metadata["tag_name"]
            old_version, new_version = version_number(state["version"]), version_number(latest)
            result["latest_version"] = latest
            status = "up_to_date"
            if new_version > old_version:
                status = "update_available"
                if new_version[0] != old_version[0] or latest == policy.get("held_version"):
                    status = "review_required"
                elif apply:
                    if "harnesses" not in state or "runtime_only" not in state:
                        status = "enrollment_required"
                    else:
                        # Timer updates preserve project registrations and owner authority.
                        bootstrap._install(latest, apply=True, project=None, project_id=None, runtime_host="local",
                            expected_machine_id=machine["machine_id"], expected_account=machine["account"],
                            expected_user_home=machine["user_home"], harnesses=state["harnesses"],
                            runtime_only=state["runtime_only"], chatgpt_web=state["chatgpt_web"],
                            tunnel_id=(state.get("web_setup") or {}).get("tunnel_id"),
                            automatic_updates=True, automatic=True)
                        status = "updated"
            if apply:
                current = json.loads((root / "state.json").read_text(encoding="utf-8"))
                current.setdefault("auto_update", {}).setdefault("enabled", True)
                current["auto_update"].update(last_check=time.time(), next_check=time.time() + INTERVAL,
                                                             last_result=status, last_error=None)
                bootstrap.write_state(root, current)
            return {**result, "state": status}
    except bootstrap.UpdateReviewRequired:
        if apply:
            try:
                with bootstrap.installation_lock(root):
                    current = json.loads((root / "state.json").read_text())
                    current.setdefault("auto_update", {}).setdefault("enabled", True)
                    current["auto_update"].update(last_check=time.time(), next_check=time.time() + INTERVAL,
                                                                 last_result="review_required")
                    bootstrap.write_state(root, current)
            except bootstrap.InstallationBusy:
                return {**result, "state": "busy"}
        return {**result, "state": "review_required", "reason": "installation_contract_changed"}
    except bootstrap.InstallationBusy:
        return {**result, "state": "busy"}
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        if apply:
            # Record only a fixed error category; backend errors may contain secrets.
            try:
                with bootstrap.installation_lock(root):
                    current = json.loads((root / "state.json").read_text(encoding="utf-8"))
                    current.setdefault("auto_update", {}).setdefault("enabled", True)
                    current["auto_update"].update(last_check=time.time(), next_check=time.time() + 3600,
                                                                 last_result="failed", last_error="update_failed")
                    bootstrap.write_state(root, current)
            except bootstrap.InstallationBusy:
                pass
        return {**result, "state": "failed", "reason": "update_failed"}
