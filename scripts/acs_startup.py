"""Restore owner-bound ACS dependencies and supervise configured SSH transport."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:
    fcntl = None


class StartupUnavailable(RuntimeError):
    pass


def owner_path(path: Path, *, directory=False) -> Path:
    if not path.is_absolute():
        raise StartupUnavailable("startup_path_requires_absolute_identity")
    for item in (path, *path.parents):
        if item.is_symlink():
            raise StartupUnavailable("startup_path_symlink_rejected")
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise StartupUnavailable("startup_owner_permissions_differ")
    if (directory and not path.is_dir()) or (not directory and not path.is_file()):
        raise StartupUnavailable("startup_owner_file_unavailable")
    return path


@contextmanager
def locked(path: Path, *, timeout=60):
    if fcntl is None:
        raise StartupUnavailable("startup_requires_linux_owner_host")
    owner_path(path.parent, directory=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise StartupUnavailable("startup_lock_owner_differ")
        end = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= end:
                    raise StartupUnavailable("startup_lock_busy") from None
                time.sleep(0.1)
        yield
    finally:
        os.close(descriptor)


def command(*args, env=None, timeout=60):
    try:
        result = subprocess.run(args, env=env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise StartupUnavailable("startup_command_unavailable") from error
    if result.returncode:
        raise StartupUnavailable("startup_command_failed")


def ensure_core(installation: Path, active: Path) -> dict:
    """Recover only an existing provider identity; provisioning is installer-owned."""
    state = json.loads(owner_path(installation / "state.json").read_bytes())
    private = owner_path(Path(state["runtime_config_ref"]).parent, directory=True)
    providers = json.loads(owner_path(private / "local-providers.json").read_bytes())
    project = providers.get("compose_project", "")
    if (providers.get("schema_version") != "acs-local-providers/2"
            or not re.fullmatch(r"acs-[a-zA-Z0-9-]+", project)
            or not isinstance(providers.get("password"), str) or len(providers["password"]) < 48
            or any(type(providers.get(key)) is not int or not 1024 <= providers[key] <= 65535
                   for key in ("postgres_port", "temporal_port"))):
        raise StartupUnavailable("startup_provider_identity_requires_review")
    if state.get("startup", {}).get("enabled", True) is False:
        return {"core": "owner_disabled"}
    compose = active / "docker-compose.acs-local.yml"
    manifest = json.loads((active / "RELEASE-MANIFEST.json").read_bytes())
    digest = manifest["files"].get("docker-compose.acs-local.yml", {})
    if (compose.is_symlink() or not compose.is_file()
            or hashlib.sha256(compose.read_bytes()).hexdigest() != digest.get("sha256")):
        raise StartupUnavailable("startup_compose_digest_differs")
    env = dict(os.environ, COMPOSE_PROJECT_NAME=project,
               ACS_POSTGRES_PASSWORD=providers["password"],
               ACS_POSTGRES_PORT=str(providers["postgres_port"]),
               ACS_TEMPORAL_PORT=str(providers["temporal_port"]))
    with locked(private / "startup-core.lock", timeout=90):
        command("docker", "compose", "-p", project, "-f", str(compose),
                "up", "-d", "--wait", "--wait-timeout", "60", env=env, timeout=90)
    # Normal Runtime entry authenticates the preserved Grant. Startup never
    # initializes the schema or bootstraps/re-enables a revoked identity.
    return {"core": "services_ready", "compose_project": project}


def ssh_profile(path: Path) -> dict:
    data = json.loads(owner_path(path).read_bytes())
    if data.get("schema_version") != "acs-private-ssh-startup/1":
        raise StartupUnavailable("ssh_startup_contract_unknown")
    target = data.get("target", "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}", target):
        raise StartupUnavailable("ssh_target_invalid")
    root = owner_path(Path(data["root"]), directory=True)
    if path.parent != root:
        raise StartupUnavailable("ssh_profile_root_differs")
    for name in ("control_socket", "supervisor_lock", "launch_lock"):
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", data.get(name, "")):
            raise StartupUnavailable("ssh_owned_filename_invalid")
    for direction in ("local_forwards", "remote_forwards"):
        values = data.get(direction, [])
        if not isinstance(values, list) or len(values) > 8:
            raise StartupUnavailable("ssh_forward_count_invalid")
        for item in values:
            if (set(item) != {"bind_port", "target_port"}
                    or any(type(value) is not int or not 1024 <= value <= 65535 for value in item.values())):
                raise StartupUnavailable("ssh_loopback_forward_invalid")
    return data


def ssh_command(data: dict) -> list[str]:
    root = Path(data["root"])
    args = ["ssh", "-M", "-S", str(root / data["control_socket"]), "-N",
            "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
            "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3"]
    for key, flag in (("local_forwards", "-L"), ("remote_forwards", "-R")):
        for item in data.get(key, []):
            args += [flag, f"127.0.0.1:{item['bind_port']}:127.0.0.1:{item['target_port']}"]
    return [*args, data["target"]]


def ssh_ready(data: dict) -> bool:
    root = Path(data["root"])
    sock = root / data["control_socket"]
    if sock.is_symlink():
        raise StartupUnavailable("ssh_control_symlink_rejected")
    try:
        result = subprocess.run(["ssh", "-S", str(sock), "-O", "check", data["target"]],
                                capture_output=True, timeout=3, check=False)
        if result.returncode == 0:
            match = re.search(rb"pid=(\d+)", result.stderr + result.stdout)
            if not match:
                raise StartupUnavailable("ssh_control_process_identity_unknown")
            process = Path("/proc") / match[1].decode()
            if process.stat().st_uid != os.getuid():
                raise StartupUnavailable("ssh_control_process_owner_differs")
            argv = (process / "cmdline").read_bytes().decode().split("\0")
            expected = ssh_command(data)
            required = [data["target"], str(sock), "-M"]
            for key in ("local_forwards", "remote_forwards"):
                required.extend(f"127.0.0.1:{item['bind_port']}:127.0.0.1:{item['target_port']}" for item in data.get(key, []))
            if any(value not in argv for value in required) or Path(argv[0]).name != Path(expected[0]).name:
                raise StartupUnavailable("ssh_control_binding_differs")
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def supervisor_running(data: dict) -> bool:
    try:
        with locked(Path(data["root"]) / data["supervisor_lock"], timeout=0):
            return False
    except StartupUnavailable as error:
        if str(error) == "startup_lock_busy":
            return True
        raise


def ensure_ssh(path: Path, *, timeout=20) -> dict:
    data = ssh_profile(path)
    root = Path(data["root"])
    with locked(root / data["launch_lock"], timeout=timeout):
        if not supervisor_running(data):
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--supervise-ssh", str(path)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
        end = time.monotonic() + timeout
        while not (supervisor_running(data) and ssh_ready(data)):
            if time.monotonic() >= end:
                raise StartupUnavailable("ssh_startup_pending")
            time.sleep(0.2)
    return {"private_ssh": "supervised", "target": data["target"]}


def supervise_ssh(path: Path) -> None:
    data = ssh_profile(path)
    root = Path(data["root"])
    try:
        with locked(root / data["supervisor_lock"], timeout=0):
            delay = 1
            while True:
                if ssh_ready(data):
                    delay = 1
                    time.sleep(2)
                    continue
                sock = root / data["control_socket"]
                if sock.exists():
                    if sock.is_symlink() or sock.stat().st_uid != os.getuid() or not stat.S_ISSOCK(sock.stat().st_mode):
                        raise StartupUnavailable("ssh_stale_control_identity_differs")
                    sock.unlink()
                process = subprocess.Popen(ssh_command(data), stdin=subprocess.DEVNULL,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                process.wait()
                time.sleep(delay)
                delay = min(delay * 2, 30)
    except StartupUnavailable as error:
        if str(error) != "startup_lock_busy":
            raise


def web_profile(path: Path) -> dict:
    data = json.loads(owner_path(path).read_bytes())
    if data.get("schema_version") != "acs-secure-tunnel-startup/1":
        raise StartupUnavailable("web_startup_contract_unknown")
    root = owner_path(Path(data["root"]), directory=True)
    if path.parent != root:
        raise StartupUnavailable("web_startup_root_differs")
    owner_path(Path(data["profile_file"]))
    binary = Path(data["binary"])
    for item in (binary, *binary.parents):
        if not item.is_absolute() or item.is_symlink():
            raise StartupUnavailable("web_binary_path_invalid")
    info = binary.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o022
            or hashlib.sha256(binary.read_bytes()).hexdigest() != data["binary_sha256"]):
        raise StartupUnavailable("web_binary_requires_review")
    for key in ("pid_file", "health_url_file"):
        value = Path(data[key])
        if not value.is_absolute() or not value.parent.is_dir():
            raise StartupUnavailable("web_state_path_invalid")
        owner_path(value.parent, directory=True)
        if value.is_symlink():
            raise StartupUnavailable("web_state_path_symlink_rejected")
    return data


def web_pid(data: dict) -> int | None:
    path = Path(data["pid_file"])
    try:
        if path.is_symlink():
            raise StartupUnavailable("web_pid_symlink_rejected")
        info = path.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
            raise StartupUnavailable("web_pid_owner_differ")
        pid = int(path.read_text().strip())
        process = Path("/proc") / str(pid)
        if process.stat().st_uid != os.getuid():
            return None
        if (process / "exe").resolve() != Path(data["binary"]):
            return None
        args = (process / "cmdline").read_bytes().decode().split("\0")
        index = args.index("--profile-file")
        if args[index + 1] != data["profile_file"] or "run" not in args:
            return None
        return pid
    except (OSError, ValueError, IndexError, StartupUnavailable):
        return None


def ensure_web(path: Path) -> dict:
    data = web_profile(path)
    root = Path(data["root"])
    with locked(root / "web-launch.lock", timeout=10):
        lock_data = {"root": str(root), "supervisor_lock": "web-supervisor.lock"}
        if not supervisor_running(lock_data):
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--supervise-web", str(path)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
    # Web readiness is an independent channel. Waiting here can recursively
    # block the stdio process the Tunnel itself is trying to initialize.
    return {"web_tunnel": "supervision_requested"}


def supervise_web(path: Path) -> None:
    data = web_profile(path)
    root = Path(data["root"])
    try:
        with locked(root / "web-supervisor.lock", timeout=0):
            delay = 1
            while True:
                if web_pid(data) is not None:
                    delay = 1
                    time.sleep(2)
                    continue
                data = web_profile(path)
                args = [data["binary"], "run", "--profile-file", data["profile_file"],
                        "--health.listen-addr", "127.0.0.1:0", "--health.url-file", data["health_url_file"],
                        "--pid.file", data["pid_file"], "--allow-remote-ui=false", "--open-web-ui=false",
                        "--health.show-details=false", "--log.level", "warn", "--admin-ui.log-buffer-events", "200"]
                process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, cwd=root)
                process.wait()
                time.sleep(delay)
                delay = min(delay * 2, 30)
    except StartupUnavailable as error:
        if str(error) != "startup_lock_busy":
            raise


def restore_configured(installation: Path, active: Path) -> dict:
    """Recover each configured component independently, including during outages."""
    state = json.loads(owner_path(installation / "state.json").read_bytes())
    if state.get("startup", {}).get("enabled", True) is False:
        return {"core": "owner_disabled"}
    result = {}
    components = [("core", lambda: ensure_core(installation, active))]
    for name, field, restore in (("web_tunnel", "web_profile_ref", ensure_web),
                                 ("ssh_tunnel", "ssh_profile_ref", ensure_ssh)):
        reference = state.get("startup", {}).get(field)
        if reference:
            components.append((name, lambda reference=reference, restore=restore: restore(Path(reference))))
    for name, restore in components:
        try:
            result.update(restore())
        except (StartupUnavailable, OSError, ValueError, KeyError):
            result[name] = "owner_repair_required"
    return result


def maintain(installation: Path) -> None:
    """Keep owner startup recovery active under an OS login/service manager."""
    state = json.loads(owner_path(installation / "state.json").read_bytes())
    private = owner_path(Path(state["runtime_config_ref"]).parent, directory=True)
    try:
        with locked(private / "login-recovery.lock", timeout=0):
            while True:
                try:
                    state = json.loads(owner_path(installation / "state.json").read_bytes())
                    if state.get("startup", {}).get("enabled", True) is False:
                        return
                    restore_configured(installation, Path(state["current"]))
                except (StartupUnavailable, OSError, ValueError, KeyError):
                    pass
                time.sleep(30)
    except StartupUnavailable as error:
        if str(error) != "startup_lock_busy":
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--supervise-ssh", type=Path)
    mode.add_argument("--supervise-web", type=Path)
    mode.add_argument("--maintain", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.supervise_ssh:
            supervise_ssh(args.supervise_ssh)
        elif args.supervise_web:
            supervise_web(args.supervise_web)
        else:
            maintain(args.maintain)
    except (OSError, ValueError, KeyError, StartupUnavailable):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
