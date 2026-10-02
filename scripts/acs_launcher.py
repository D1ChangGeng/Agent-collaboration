"""Start the verified active ACS Runtime through a stable stdio command."""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import platform
import re
import socket
import stat
import subprocess
import sys
from pathlib import Path


def observe_machine() -> dict:
    seed = ""
    for name in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        path = Path(name)
        if path.is_file():
            seed = path.read_text().strip()
            if seed:
                break
    if not seed:
        seed = socket.gethostname() + ":" + platform.node()
    return {"machine_id": hashlib.sha256((sys.platform + ":" + seed).encode()).hexdigest(),
            "account": getpass.getuser(), "user_home": str(Path.home()), "platform": sys.platform}


def exact_path(path: Path, *, private: bool = False, file: bool = False) -> Path:
    if not path.is_absolute():
        raise ValueError("an absolute installation path is required")
    for current in (path, *path.parents):
        if current.is_symlink():
            raise ValueError("installation paths must not traverse symlinks")
    if file and not path.is_file():
        raise ValueError("an installation file is unavailable")
    if private and os.name == "posix":
        observed = path.stat()
        if observed.st_uid != os.getuid() or stat.S_IMODE(observed.st_mode) & 0o077:
            raise ValueError("private installation permissions differ")
    return path.resolve(strict=True)


def verify_file(active: Path, manifest: dict, name: str) -> Path:
    record = manifest["files"].get(name)
    if not isinstance(record, dict):
        raise TypeError("active Runtime file is absent from the release manifest")
    path = exact_path(active / name, file=True)
    if (path.stat().st_size != record.get("bytes") or
            hashlib.sha256(path.read_bytes()).hexdigest() != record.get("sha256")):
        raise ValueError("active Runtime file digest differs")
    return path


def resolve_launch(installation_root: Path, profile: str = "root_manager") -> tuple[Path, list[str]]:
    root = exact_path(installation_root, private=True)
    if not root.is_dir():
        raise ValueError("installation root is unavailable")
    state = json.loads(exact_path(root / "state.json", private=True, file=True).read_bytes())
    if state.get("schema_version") != "acs-bootstrap-state/1":
        raise ValueError("installation state is unavailable")
    machine = observe_machine()
    if not machine["platform"].startswith("linux") or any(
        state.get("machine", {}).get(key) != machine[key]
        for key in ("machine_id", "account", "user_home")
    ):
        raise ValueError("installation machine or account differs")
    selected = state.get("current")
    if not isinstance(selected, str):
        raise TypeError("active version is unavailable")
    active = exact_path(Path(selected))
    versions = exact_path(root / "versions")
    if not active.is_dir() or active.parent != versions:
        raise ValueError("active version is outside the installation")
    manifest = json.loads(exact_path(active / "RELEASE-MANIFEST.json", file=True).read_bytes())
    version = state.get("version", "")
    if (not isinstance(version, str) or not re.fullmatch(r"v\d+\.\d+\.\d+", version)
            or active.name != version.removeprefix("v")
            or manifest.get("schema_version") != "acs-release-manifest/1"
            or manifest.get("version") != version.removeprefix("v")
            or not isinstance(manifest.get("files"), dict)
            or any(not re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", str(state.get(key, "")))
                   or manifest.get(key) != state.get(key) for key in ("commit", "tree"))):
        raise ValueError("active release identity differs")
    verify_file(active, manifest, "runtime/project_entry.py")
    catalog = verify_file(active, manifest, "docs/runtime/p2-mcp-tool-contract.json")
    contract = json.loads(catalog.read_bytes())
    if profile not in contract.get("profiles", {}):
        raise ValueError("selected Profile is unavailable")
    config_ref = state.get("runtime_config_ref")
    if not isinstance(config_ref, str):
        raise TypeError("private Runtime configuration is unavailable")
    config = exact_path(Path(config_ref), private=True, file=True)
    exact_path(active / ".venv/bin")
    python = active / ".venv/bin/python"
    # uv virtual environments normally link this final component to a managed
    # or system interpreter outside the version directory.
    interpreter = python.resolve(strict=True)
    if not interpreter.is_file() or (os.name == "posix" and not os.access(interpreter, os.X_OK)):
        raise ValueError("active Runtime interpreter is unavailable")
    # The immutable version selected by this atomic state snapshot remains
    # runnable while another connection activates the next version.
    return active, [str(python), "-m", "runtime.project_entry", "--config", str(config),
                    "--catalog", str(catalog), "--profile", profile]


def spawn_catchup(root: Path) -> None:
    """Let a waking host check its schedule without delaying MCP startup."""
    try:
        state = json.loads((root / "state.json").read_bytes())
        if not state.get("auto_update", {}).get("enabled", True) or not sys.platform.startswith("linux"):
            return
        bootstrap = root / "acs_bootstrap.py"
        exact_path(bootstrap, file=True)
        python = state.get("launcher_python") or sys.executable
        if not isinstance(python, str) or not Path(python).is_absolute() or not Path(python).is_file():
            return
        subprocess.Popen([python, str(bootstrap), "--update", "--apply"],
                         cwd=root, env=dict(os.environ, ACS_UPDATE_ROOT=str(root)),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        # Daily retry and update-status readback own the update result. Runtime
        # startup remains available when a background check cannot start.
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installation-root", type=Path, required=True)
    parser.add_argument("--profile", default="root_manager")
    args = parser.parse_args(argv)
    try:
        active, command = resolve_launch(args.installation_root, args.profile)
        spawn_catchup(args.installation_root)
        os.chdir(active)
        os.execv(command[0], command)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print('{"error":"active_runtime_unavailable"}', file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
