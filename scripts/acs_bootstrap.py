"""Install ACS from a verified GitHub Release asset.

The bootstrapper owns distribution acquisition and versioned installation. It
does not modify a project checkout until the selected release is verified.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import functools
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

REPOSITORY = "D1ChangGeng/Agent-collaboration"
DEFAULT_VERSION = "v1.4.0"
SCHEMA = "acs-bootstrap-state/1"
WEB_CHOICES = ("enable", "skip", "later")
WEB_DOCS = {
    "tunnel": "https://developers.openai.com/api/docs/guides/secure-mcp-tunnels",
    "connect": "https://developers.openai.com/plugins/deploy/connect-chatgpt",
    "auth": "https://developers.openai.com/plugins/build/auth",
    "index": "https://developers.openai.com/llms.txt",
}


class InstallationBusy(ValueError):
    pass


class UpdateReviewRequired(ValueError):
    pass


@contextlib.contextmanager
def installation_lock(root: Path):
    if any(part.is_symlink() or (part.exists() and getattr(part.lstat(), "st_file_attributes", 0) & 0x400)
           for part in (root, *root.parents)):
        raise ValueError("installation_lock_path_is_unsafe")
    path = root / ".installation.lock"
    if path.is_symlink():
        raise ValueError("installation_lock_path_is_unsafe")
    with path.open("a+b") as handle:
        if os.name == "posix":
            os.fchmod(handle.fileno(), 0o600)
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise InstallationBusy("installation_busy") from error
        else:
            import msvcrt
            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise InstallationBusy("installation_busy") from error
        try:
            yield
        finally:
            if os.name == "posix":
                fcntl.flock(handle, fcntl.LOCK_UN)
            else:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def serialized(function):
    @functools.wraps(function)
    def guarded(*args, **kwargs):
        if function.__name__ == "rollback":
            root = ensure_install_root()
        elif kwargs.get("apply") and kwargs.get("runtime_host") == "local":
            machine = observe_machine()
            check_machine(machine, kwargs.get("expected_machine_id"), kwargs.get("expected_account"),
                          kwargs.get("expected_user_home"))
            if kwargs.get("chatgpt_web") is None:
                raise ValueError("confirm --chatgpt-web enable, skip or later before installation")
            root = ensure_install_root()
        else:
            return function(*args, **kwargs)
        with installation_lock(root):
            return function(*args, **kwargs)
    return guarded


def chatgpt_setup(choice: str | None, runtime_root: str | None = None,
                  config: str | None = None, tunnel_id: str | None = None) -> dict:
    """Describe optional web setup; a plan never grants Platform or ACS access."""
    if choice is not None and choice not in WEB_CHOICES:
        raise ValueError("choose ChatGPT web setup: enable, skip or later")
    if tunnel_id and not re.fullmatch(r"tunnel_[A-Za-z0-9_-]{1,128}", tunnel_id):
        raise ValueError("supply the public Tunnel identifier, not a runtime key")
    result = {"schema_version": "acs-chatgpt-setup/1", "choice": choice,
              "official_documentation": WEB_DOCS,
              "question": "Would you like ACS in ChatGPT on the web: configure now, skip, or later?"}
    if choice is None:
        return {**result, "state": "needs_web_choice", "choices": list(WEB_CHOICES)}
    if choice in {"skip", "later"}:
        return {**result, "state": "skipped" if choice == "skip" else "deferred",
                "next_action": "Invoke the setup Skill to configure ChatGPT web access when needed."}
    runtime = None
    if runtime_root and config:
        if (not PurePosixPath(runtime_root).is_absolute() or not PurePosixPath(config).is_absolute()
                or any(ord(c) < 32 for c in runtime_root + config)):
            raise ValueError("web setup requires absolute paths on the selected Linux Runtime host")
        root = runtime_root.rstrip("/")
        argv = [root + "/.venv/bin/python", "-m", "runtime.project_entry", "--config", config,
                "--catalog", root + "/docs/runtime/p2-mcp-tool-contract.json", "--profile", "root_manager"]
        shell = "cd " + shlex.quote(root) + " && exec " + shlex.join(argv)
        runtime = {"host": "selected_runtime_machine", "cwd": root,
                   "command": "sh", "args": ["-c", shell], "config_ref": config}
    profile = "acs-private"
    initialize = (["tunnel-client", "init", "--sample", "sample_mcp_stdio_local",
                   "--profile", profile, "--tunnel-id", tunnel_id,
                   "--mcp-command", shlex.join([runtime["command"], *runtime["args"]])]
                  if runtime and tunnel_id else None)
    return {**result, "state": "awaiting_owner_actions", "profile": profile,
            "tunnel_id": tunnel_id, "runtime_process": runtime,
            "account_browser": {
                "context": "owner_external_browser", "host": "owner_client_host",
                "allowed_routes": ["external_browser_control", "user_guided_steps"],
                "capability_rule": "Verify external browser control on the owner client before choosing it; Harness name or embedded browser availability is insufficient.",
                "fallback": "user_guided_steps",
                "forbidden_account_contexts": ["harness_embedded_browser", "runtime_browser_outside_owner_client"],
                "owner_actions": ["login", "secret_entry", "permission_approval", "connection_consent"],
                "guidance_fields": ["official_url", "page_location", "action", "expected_result", "next_step"],
                "completion_rule": "Wait for owner completion and verify the chosen account/workspace and actual MCP connection.",
                "documentation_access": "Public official documentation may be fetched or searched read-only.",
            },
            "ai_actions": [
                "Check current official guidance and validate the owner ACS Profile and Grant.",
                "Use the owner's external browser for account setup when external control is verified; otherwise provide the owner page steps and await completion.",
                "Install the official tunnel-client on the selected Runtime host and verify its binary.",
                "Initialize the returned stdio profile after owner permissions and private key input.",
                "Run doctor, keep the client running, and verify tools from the selected ChatGPT workspace.",
            ],
            "owner_actions": [
                {"action": "In the owner's external browser, select or create a Tunnel; associate the owner organization and ChatGPT workspace.",
                 "url": "https://platform.openai.com/settings/organization/tunnels",
                 "permissions": {"create": "Tunnels Read + Manage", "run_and_select": "Tunnels Read + Use"}},
                {"action": "Supply the runtime key privately on the Runtime host.",
                 "secret_environment": "CONTROL_PLANE_API_KEY"},
                {"action": "In the owner's external browser, enable Developer mode in Settings > Security and login if the workspace permits it."},
                {"action": "In the owner's external browser at ChatGPT Plugins, use + and Connection > Tunnel; select the id and review tools.",
                 "url": "https://chatgpt.com/plugins"},
            ],
            "commands": {"init": initialize,
                         "doctor": ["tunnel-client", "doctor", "--profile", profile, "--explain"],
                         "run": ["tunnel-client", "run", "--profile", profile]},
            "verification": {"initial": ["tools/list", "read_profile", "list_projects"],
                             "after_project_adoption": ["load_project", "authorized_write_readback",
                                                        "denied_access", "reconnect", "grant_revocation"]},
            "next_action": "Complete the owner actions, execute the AI commands and verify the web connection.",
            "readiness_rule": "Report connected only after actual ChatGPT MCP readback; zero projects is valid."}

# The same read-only probe runs in the caller or through the selected transport.
# Raw OS identity bytes remain on the observed host.
HOST_PROBE = """
import getpass, hashlib, json, os, platform, socket, sys
from pathlib import Path
seed = ''
for name in ('/etc/machine-id', '/var/lib/dbus/machine-id'):
    if Path(name).is_file():
        seed = Path(name).read_text().strip()
        if seed:
            break
if not seed:
    seed = socket.gethostname() + ':' + platform.node()
machine = hashlib.sha256((sys.platform + ':' + seed).encode()).hexdigest()
print(json.dumps({'schema_version': 'acs-install-machine/1',
    'machine_id': machine, 'hostname': socket.gethostname(), 'platform': sys.platform,
    'account': getpass.getuser(), 'user_home': str(Path.home()),
    'python': platform.python_version()}))
"""

REMOTE_INSTALL = """
import base64, hashlib, importlib.util, json, tempfile
from pathlib import Path
import sys
request = json.load(sys.stdin)
source = base64.b64decode(request['bootstrap'], validate=True)
if hashlib.sha256(source).hexdigest() != request['sha256']:
    raise ValueError('Bootstrap transfer digest differs')
with tempfile.TemporaryDirectory(prefix='acs-bootstrap-') as directory:
    path = Path(directory) / 'acs_bootstrap.py'
    path.write_bytes(source)
    spec = importlib.util.spec_from_file_location('acs_remote_bootstrap', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.machine_binding(module.observe_machine()) != request['machine_binding']:
        raise ValueError('selected Runtime machine or account changed before installation')
    result = module.install(request['version'], apply=True,
        project=Path(request['project']) if request['project'] else None,
        project_id=request['project_id'], runtime_host='local',
        expected_machine_id=request['machine_id'], harnesses=request['harnesses'],
        expected_account=request['machine_binding']['account'],
        expected_user_home=request['machine_binding']['user_home'],
        chatgpt_web=request['chatgpt_web'], tunnel_id=request['tunnel_id'],
        runtime_only=True, automatic_updates=request['automatic_updates'])
    print('ACS_INSTALL_RECEIPT=' + json.dumps(result))
"""


def transport_command(kind: str, locator: str | None, code: str) -> list[str]:
    if kind == "ssh":
        if not locator or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._@:-]{0,254}", locator):
            raise ValueError("supply the selected SSH alias or user@host")
        return ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                "-o", "ConnectTimeout=10", locator, "python3 -c " + shlex.quote(code)]
    if kind == "wsl":
        if not locator or locator.startswith("-") or any(ord(c) < 32 for c in locator):
            raise ValueError("supply the selected WSL distribution")
        return ["wsl.exe", "--distribution", locator, "--exec", "python3", "-c", code]
    raise ValueError("unsupported installation transport")


def observe_machine(kind: str = "local", locator: str | None = None) -> dict:
    command = ([sys.executable, "-c", HOST_PROBE] if kind == "local" else
               transport_command(kind, locator, HOST_PROBE))
    result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
    value = json.loads(result.stdout)
    if (value.get("schema_version") != "acs-install-machine/1" or
            not re.fullmatch(r"[a-f0-9]{64}", value.get("machine_id", "")) or
            not all(isinstance(value.get(key), str) and value[key]
                    for key in ("account", "hostname", "user_home", "platform", "python"))):
        raise ValueError("installation machine observation is invalid")
    return {**value, "transport": kind, "locator": locator}


def machine_binding(machine: dict) -> dict:
    return {key: machine[key] for key in ("machine_id", "account", "user_home")}


def check_machine(machine: dict, expected: str | None = None,
                  account: str | None = None, user_home: str | None = None) -> None:
    if expected and machine["machine_id"] != expected:
        raise ValueError("selected Runtime machine identity changed")
    if account and machine["account"] != account:
        raise ValueError("selected Runtime login account changed since the installation plan")
    if user_home and machine["user_home"] != user_home:
        raise ValueError("selected Runtime home directory changed since the installation plan")
    if not machine["platform"].startswith("linux"):
        raise ValueError("select a Linux Runtime host, a named SSH host, or a named WSL distribution")


def runtime_command(target: Path, project: Path | None, project_id: str | None,
                    harnesses: list[str], runtime_only: bool = False) -> list[str]:
    command = ["uv", "run", "--frozen", "python", "scripts/acs_install.py",
               "--apply", "--harness", *harnesses]
    if project is not None:
        command.extend(["--project", str(project), "--project-id", project_id])
    if runtime_only:
        command.append("--runtime-only")
    return command


def client_connection(kind: str, locator: str, receipt: dict) -> dict:
    target = receipt["current"]
    python = target + "/.venv/bin/python"
    arguments = [python, "-m", "runtime.project_entry", "--config",
                 receipt["runtime"]["runtime_config_ref"], "--catalog",
                 target + "/docs/runtime/p2-mcp-tool-contract.json", "--profile", "root_manager"]
    if receipt.get("install_root") and receipt.get("launcher_python"):
        arguments = [receipt["launcher_python"], receipt["install_root"] + "/acs_launcher.py",
                     "--installation-root", receipt["install_root"]]
        remote = "exec " + shlex.join(arguments)
    else:
        remote = "cd " + shlex.quote(target) + " && exec " + shlex.join(arguments)
    command = (transport_command(kind, locator, "")[:-1] + [remote] if kind == "ssh" else
               ["wsl.exe", "--distribution", locator, "--exec", "sh", "-c", remote])
    return {"transport": "stdio", "command": command[0], "args": command[1:],
            "state": "requires_client_configuration_and_handshake"}


def install_root() -> Path:
    if os.environ.get("ACS_UPDATE_ROOT"):
        return Path(os.environ["ACS_UPDATE_ROOT"]).expanduser().absolute()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AgentCollaboration"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "agent-collaboration"


def ensure_install_root() -> Path:
    root = install_root()
    for part in (root, *root.parents):
        if part.is_symlink() or (part.exists() and getattr(part.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("installation root must not traverse a symlink or reparse point")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix" and stat.S_IMODE(root.stat().st_mode) & 0o077:
        raise ValueError("installation root permissions are too broad")
    return root


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def fetch(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "acs-bootstrap/1"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("xb") as stream:
        shutil.copyfileobj(response, stream, length=1024 * 1024)


def release_metadata(version: str) -> dict:
    url = f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{version}"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "acs-bootstrap/1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        value = json.load(response)
    if not isinstance(value, dict) or not isinstance(value.get("assets"), list):
        raise TypeError("release metadata is invalid")
    if value.get("tag_name") != version or value.get("draft") or value.get("prerelease"):
        raise ValueError("release tag or publication state differs")
    return value


def verify_archive(archive: Path, version: str, expected: str, staging: Path) -> tuple[Path, dict]:
    if digest(archive) != expected:
        raise ValueError("release asset digest differs from published SHA-256")
    prefix = f"agent-collaboration-{version}/"
    unpack = staging / "unpack"
    staging.mkdir(parents=True, exist_ok=True)
    unpack.mkdir()
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as source:
            names = source.namelist()
            if any(not name.startswith(prefix) or name.endswith("/") or
                   PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
                   or "\\" in name for name in names):
                raise ValueError("release archive contains an invalid path")
            if len(names) != len(set(names)):
                raise ValueError("release archive contains duplicate paths")
            for item in source.infolist():
                mode = item.external_attr >> 16
                if mode and not stat.S_ISREG(mode):
                    raise ValueError("release archive contains a non-file entry")
            source.extractall(unpack)
    else:
        with tarfile.open(archive, "r:gz") as source:
            for member in source.getmembers():
                path = PurePosixPath(member.name)
                if (not member.name.startswith(prefix) or member.issym() or member.islnk()
                        or not member.isfile() or path.is_absolute() or ".." in path.parts
                        or "\\" in member.name):
                    raise ValueError("release archive contains an invalid entry")
            source.extractall(unpack)
    root = unpack / prefix.rstrip("/")
    manifest = json.loads((root / "RELEASE-MANIFEST.json").read_text(encoding="utf-8"))
    if (manifest.get("schema_version") != "acs-release-manifest/1" or
            manifest.get("version") != version.lstrip("v") or
            not isinstance(manifest.get("files"), dict)):
        raise ValueError("release manifest version differs")
    for name, record in manifest.get("files", {}).items():
        path = root / name
        if (not path.is_file() or path.is_symlink() or path.stat().st_size != record.get("bytes")
                or digest(path) != record.get("sha256")):
            raise ValueError(f"release file digest differs: {name}")
    generated = {"DEPENDENCIES.json", "LICENSES.md", "RELEASE-MANIFEST.json"}
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if actual != set(manifest["files"]) | generated:
        raise ValueError("release file inventory differs from manifest")
    return root, manifest


def write_state(root: Path, value: dict) -> None:
    target = root / "state.json"
    temporary = target.with_suffix(".tmp")
    if target.is_symlink() or temporary.is_symlink():
        raise ValueError("installation_state_path_is_unsafe")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if os.name == "posix":
        temporary.chmod(0o600)
    os.replace(temporary, target)


def installed_manifest(target: Path) -> dict:
    manifest = json.loads((target / "RELEASE-MANIFEST.json").read_text(encoding="utf-8"))
    for name, record in manifest["files"].items():
        path = target / name
        if (path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(target.resolve())
                or path.stat().st_size != record["bytes"] or digest(path) != record["sha256"]):
            raise ValueError("installed_release_bytes_changed")
    return manifest


def helper_files(root: Path, target: Path, previous_state: dict) -> dict:
    digests = {}
    for name in ("acs_bootstrap.py", "acs_update.py", "acs_launcher.py", "install_skill.py"):
        source, dest = target / "scripts" / name, root / name
        expected = digest(source)
        if dest.is_symlink() or (dest.exists() and digest(dest) not in
                {expected, previous_state.get("helper_digests", {}).get(name)}):
            raise ValueError("installation_helper_requires_ownership_review")
        digests[name] = expected
    for name in digests:
        temporary = root / (name + ".tmp")
        if temporary.is_symlink():
            raise ValueError("installation_helper_path_is_unsafe")
        temporary.write_bytes((target / "scripts" / name).read_bytes())
        os.replace(temporary, root / name)
    return digests


def activation(root: Path, state: dict) -> None:
    # One atomic JSON record controls activation; the text file is a legacy mirror.
    write_state(root, state)
    try:
        temporary = root / "current.tmp"
        if temporary.is_symlink() or (root / "current").is_symlink():
            return
        temporary.write_text(state["current"], encoding="utf-8")
        os.replace(temporary, root / "current")
    except OSError:
        pass


def update_module(root: Path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("acs_update", root / "acs_update.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def refresh_skills(helper_root: Path, source: Path, prior: Path | None, harnesses: list[str]) -> None:
    helper = install_root() / "install_skill.py"
    if not helper.is_file():
        helper = helper_root / "scripts/install_skill.py"
    command = [sys.executable, str(helper),
               "--source", str(source), "--harness", *harnesses, "--knowledge"]
    if prior:
        command.extend(["--previous-source", str(prior)])
    subprocess.run(command, cwd=helper_root, capture_output=True, text=True, check=True, timeout=1200)


def _install(version: str, *, apply: bool, project: Path | None, project_id: str | None,
            runtime_host: str | None = None, ssh_target: str | None = None,
            wsl_distribution: str | None = None, expected_machine_id: str | None = None,
            harnesses: list[str] | None = None, runtime_only: bool = False,
            expected_account: str | None = None, expected_user_home: str | None = None,
            chatgpt_web: str | None = None, tunnel_id: str | None = None,
            automatic_updates: bool | None = None, automatic: bool = False) -> dict:
    if runtime_host is None:
        if apply:
            raise ValueError("confirm --runtime-host local, ssh or wsl before installation")
        return {"schema_version": "acs-install-plan/3", "state": "needs_machine_selection",
                "choices": ["local", "ssh", "wsl"], "project_setup": "optional_after_machine_setup"}
    if (runtime_host not in {"local", "ssh", "wsl"} or
            (ssh_target is not None and runtime_host != "ssh") or
            (wsl_distribution is not None and runtime_host != "wsl")):
        raise ValueError("machine selection and transport arguments differ")
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("release version must be an explicit vMAJOR.MINOR.PATCH tag")
    if (project is None) != (project_id is None):
        raise ValueError("optional project setup requires both project and project_id")
    harnesses = harnesses or ["codex", "opencode"]
    if not set(harnesses) <= {"codex", "opencode"}:
        raise ValueError("unsupported Harness selection")
    locator = ssh_target if runtime_host == "ssh" else wsl_distribution
    machine = observe_machine(runtime_host, locator)
    check_machine(machine, expected_machine_id, expected_account, expected_user_home)
    web = chatgpt_setup(chatgpt_web, tunnel_id=tunnel_id)
    if chatgpt_web is None:
        if apply:
            raise ValueError("confirm --chatgpt-web enable, skip or later before installation")
        return {"schema_version": "acs-install-plan/3", "state": "needs_web_choice",
                "machine": machine, "web_setup": web, "project_setup": "optional_after_machine_setup"}
    if runtime_host != "local":
        result = {"schema_version": "acs-install-plan/3", "state": "planned",
                  "version": version, "machine": machine, "client_machine": observe_machine(),
                  "harnesses": harnesses, "web_setup": web,
                  "project_setup": "optional_after_machine_setup"}
        if not apply:
            return result
        source = Path(__file__).read_bytes()
        request = {"bootstrap": base64.b64encode(source).decode("ascii"),
                   "sha256": hashlib.sha256(source).hexdigest(), "version": version,
                   "machine_id": machine["machine_id"], "project": str(project) if project else None,
                   "project_id": project_id, "harnesses": harnesses,
                   "chatgpt_web": chatgpt_web, "tunnel_id": tunnel_id, "automatic_updates": automatic_updates,
                   "machine_binding": machine_binding(machine)}
        transferred = subprocess.run(transport_command(runtime_host, locator, REMOTE_INSTALL),
                                     input=json.dumps(request), capture_output=True, text=True,
                                     check=True, timeout=1200)
        lines = [line.removeprefix("ACS_INSTALL_RECEIPT=") for line in transferred.stdout.splitlines()
                 if line.startswith("ACS_INSTALL_RECEIPT=")]
        if len(lines) != 1:
            raise ValueError("selected host did not return one installation receipt")
        receipt = json.loads(lines[0])
        if machine_binding(receipt["machine"]) != machine_binding(machine):
            raise ValueError("installation receipt machine or account differs from the selected host")
        final = observe_machine(runtime_host, locator)
        if machine_binding(final) != machine_binding(machine):
            raise ValueError("selected host changed during installation; client connection withheld")
        return {**receipt, "machine": machine, "client_machine": result["client_machine"],
                "client_connection": client_connection(runtime_host, locator, receipt)}
    if project is not None:
        project = project.expanduser().resolve()
        if not project.is_dir():
            raise ValueError("project path is not a directory on the selected Runtime host")
    metadata = release_metadata(version)
    wanted = f"agent-collaboration-{version}"
    asset = next((item for item in metadata["assets"] if item.get("name") == wanted + ".zip"), None)
    sums = next((item for item in metadata["assets"] if item.get("name") == "SHA256SUMS.txt"), None)
    if not asset or not sums:
        raise ValueError("release does not contain the required archive and digest manifest")
    root = install_root()
    stored = {}
    if (root / "state.json").is_file():
        stored = json.loads((root / "state.json").read_text(encoding="utf-8"))
        if stored.get("machine") and machine_binding(stored["machine"]) != machine_binding(machine):
            raise ValueError("existing installation is bound to a different machine or account")
    if automatic_updates is None:
        automatic_updates = stored.get("auto_update", {}).get("enabled", True)
    result = {"schema_version": "acs-install-plan/3", "version": version,
              "release_url": metadata.get("html_url"), "install_root": str(root),
              "archive": asset["name"], "state": "planned", "machine": machine,
              "harnesses": harnesses, "runtime_only": runtime_only,
              "web_setup": web,
              "project_setup": "optional_after_machine_setup"}
    if not apply:
        return result
    root = ensure_install_root()
    staging = Path(tempfile.mkdtemp(prefix=".acs-install-", dir=root))
    snapshots = {name: (root / name).read_bytes() if (root / name).is_file() else None
                 for name in ("acs_bootstrap.py", "acs_update.py", "acs_launcher.py", "install_skill.py")}
    activated = False
    skills_refreshed = False
    try:
        archive = staging / asset["name"]
        checksums = staging / "SHA256SUMS.txt"
        fetch(asset["browser_download_url"], archive)
        fetch(sums["browser_download_url"], checksums)
        expected = next((line.split()[0] for line in checksums.read_text(encoding="ascii").splitlines()
                         if line.endswith(asset["name"])), None)
        if not expected:
            raise ValueError("published digest manifest does not cover the archive")
        verified, manifest = verify_archive(archive, version, expected, staging)
        previous = stored.get("current")
        if previous:
            old_target = Path(previous)
            if old_target.parent != root / "versions" or old_target.is_symlink():
                raise ValueError("active_release_path_is_unsafe")
            old_manifest = installed_manifest(old_target)
            if automatic and not update_module(root).compatible(old_manifest, manifest):
                raise UpdateReviewRequired("automatic_update_compatibility_requires_review")
        versions = root / "versions"
        if versions.is_symlink() or (versions.exists() and getattr(versions.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("installation_versions_path_is_unsafe")
        versions.mkdir(exist_ok=True)
        target = versions / version.lstrip("v")
        if target.exists():
            if target.is_symlink() or not target.is_dir():
                raise ValueError("existing version path is unsafe")
            current_manifest = json.loads((target / "RELEASE-MANIFEST.json").read_text(encoding="utf-8"))
            if current_manifest != manifest:
                raise ValueError("existing version contains different release bytes")
            installed_manifest(target)
        else:
            shutil.copytree(verified, target)
        if previous == str(target):
            previous = stored.get("previous")
        installer = target / "scripts" / "acs_install.py"
        if not installer.is_file():
            raise ValueError("verified release is missing its installer")
        if runtime_only and "--runtime-only" not in installer.read_text(encoding="utf-8"):
            raise ValueError("selected Release requires an updated Runtime installer supporting --runtime-only")
        rechecked = observe_machine()
        if machine_binding(rechecked) != machine_binding(machine):
            raise ValueError("Runtime machine or account changed before installation")
        helpers = helper_files(root, target, stored)
        environment = dict(os.environ, ACS_INSTALL_MACHINE_ID=machine["machine_id"],
                           ACS_INSTALL_ACCOUNT=machine["account"], ACS_INSTALL_USER_HOME=machine["user_home"],
                           ACS_INSTALL_CHATGPT_WEB=chatgpt_web, ACS_INSTALL_ROOT=str(root),
                           ACS_LAUNCHER_PYTHON=sys.executable)
        environment.pop("ACS_AUTOMATIC_UPDATE", None)
        environment.pop("ACS_PREVIOUS_RELEASE", None)
        if stored.get("current"):
            environment["ACS_PREVIOUS_RELEASE"] = stored["current"]
        if automatic:
            environment["ACS_AUTOMATIC_UPDATE"] = "1"
        environment.pop("ACS_INSTALL_TUNNEL_ID", None)
        if tunnel_id:
            environment["ACS_INSTALL_TUNNEL_ID"] = tunnel_id
        executed = subprocess.run(runtime_command(target, project, project_id, harnesses, runtime_only),
                                  cwd=target, env=environment, capture_output=True, text=True, check=True, timeout=1200)
        receipts = []
        decoder = json.JSONDecoder()
        for offset in re.finditer(r"(?m)^\{", executed.stdout):
            try:
                receipt, _ = decoder.raw_decode(executed.stdout[offset.start():])
            except ValueError:
                continue
            if receipt.get("schema_version") == "acs-install-plan/1":
                receipts.append(receipt)
        if len(receipts) != 1 or receipts[0].get("state") not in {"local_authority_ready", "project_registered"}:
            raise ValueError("Runtime installer did not report machine setup readiness")
        runtime = receipts[0]
        if runtime.get("readback", {}).get("runtime", {}).get("state") != "authorized":
            raise ValueError("Runtime authorization readback failed; active version retained")
        if automatic and not runtime_only:
            refresh_skills(target, target, Path(stored["current"]), harnesses)
            skills_refreshed = True
        web = chatgpt_setup(chatgpt_web, str(target), runtime.get("runtime_config_ref"), tunnel_id)
        if chatgpt_web == "enable":
            stable = {"host": "selected_runtime_machine", "cwd": str(root), "command": sys.executable,
                      "args": [str(root / "acs_launcher.py"), "--installation-root", str(root)],
                      "config_ref": runtime.get("runtime_config_ref")}
            web["runtime_process"] = stable
            if web["commands"]["init"]:
                web["commands"]["init"][-1] = shlex.join([stable["command"], *stable["args"]])
        activation(root, {"schema_version": SCHEMA, "version": version,
                           "current": str(target), "previous": previous, "machine": machine,
                           "harnesses": harnesses, "runtime_only": runtime_only, "launcher_python": sys.executable,
                           "helper_digests": helpers,
                           "auto_update": {**stored.get("auto_update", {}), "enabled": automatic_updates,
                                           "next_check": stored.get("auto_update", {}).get("next_check", time.time() + 86400)},
                           "chatgpt_web": chatgpt_web, "web_setup": web,
                           "runtime_config_ref": runtime.get("runtime_config_ref"),
                           "commit": manifest["commit"], "tree": manifest["tree"]})
        activated = True
        if not automatic:
            policy_state = json.loads((root / "state.json").read_text())
            try:
                schedule = update_module(root).configure_schedule(root, automatic_updates, sys.executable)
            except (OSError, ValueError, subprocess.SubprocessError):
                schedule = {"enabled": automatic_updates, "backend": "connection", "state": "active" if automatic_updates else "disabled",
                            "schedule_issue": "background_scheduler_requires_setup"}
            policy_state["auto_update"]["schedule"] = schedule
            write_state(root, policy_state)
        result.update({"state": "machine_ready", "commit": manifest["commit"], "tree": manifest["tree"],
                       "launcher_python": sys.executable, "auto_update": json.loads((root / "state.json").read_text())["auto_update"],
                       "current": str(target), "rollback": previous, "runtime": runtime,
                       "web_setup": web,
                       "next_action": (web["next_action"] if chatgpt_web == "enable" else
                           "Use the setup Skill in a chosen project to create or adopt its Management Root.")})
        return result
    finally:
        if not activated:
            if skills_refreshed:
                refresh_skills(target, Path(stored["current"]), target, harnesses)
            for name, content in snapshots.items():
                helper = root / name
                if helper.is_symlink():
                    continue
                if content is None:
                    helper.unlink(missing_ok=True)
                else:
                    temporary = root / (name + ".restore.tmp")
                    if not temporary.is_symlink():
                        temporary.write_bytes(content)
                        os.replace(temporary, helper)
        shutil.rmtree(staging, ignore_errors=True)


install = serialized(_install)


@serialized
def rollback() -> dict:
    root = ensure_install_root()
    state_path = root / "state.json"
    if not state_path.is_file():
        raise ValueError("no installation state is available")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    machine = observe_machine()
    if state.get("machine") and machine_binding(state["machine"]) != machine_binding(machine):
        raise ValueError("rollback installation belongs to a different machine or account")
    previous = state.get("previous")
    if not isinstance(previous, str) or not Path(previous).is_dir():
        raise ValueError("no verified previous version is available")
    current = state.get("current")
    if Path(previous).parent != root / "versions" or Path(previous).is_symlink():
        raise ValueError("rollback_release_path_is_unsafe")
    manifest = installed_manifest(Path(previous))
    if not state.get("runtime_only", True):
        refresh_skills(Path(current), Path(previous), Path(current), state["harnesses"])
    original_web = state.get("web_setup") or {}
    config_ref = state.get("runtime_config_ref") or (original_web.get("runtime_process") or {}).get("config_ref")
    web = chatgpt_setup(state.get("chatgpt_web"), previous, config_ref, original_web.get("tunnel_id"))
    if web.get("runtime_process") and (root / "acs_launcher.py").is_file():
        stable = {"host": "selected_runtime_machine", "cwd": str(root), "command": state["launcher_python"],
                  "args": [str(root / "acs_launcher.py"), "--installation-root", str(root)], "config_ref": config_ref}
        web["runtime_process"] = stable
        if web["commands"]["init"]:
            web["commands"]["init"][-1] = shlex.join([stable["command"], *stable["args"]])
    try:
        activation(root, {**state, "schema_version": SCHEMA, "version": "v" + manifest["version"],
                       "current": previous, "previous": current, "machine": machine,
                       "chatgpt_web": state.get("chatgpt_web"), "web_setup": web,
                       "runtime_config_ref": config_ref,
                       "auto_update": {**state.get("auto_update", {}), "enabled": state.get("auto_update", {}).get("enabled", True),
                                       "held_version": state["version"]},
                           "commit": manifest["commit"], "tree": manifest["tree"]})
    except (OSError, ValueError):
        if not state.get("runtime_only", True):
            refresh_skills(Path(current), Path(current), Path(previous), state["harnesses"])
        raise
    return {"schema_version": "acs-install-plan/2", "state": "rolled_back",
            "current": previous, "commit": manifest["commit"], "tree": manifest["tree"],
            "web_setup": web}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--update", action="store_true", help="check or apply the latest compatible stable Release")
    parser.add_argument("--force-check", action="store_true")
    parser.add_argument("--set-auto-update", choices=["on", "off", "status"])
    updates = parser.add_mutually_exclusive_group()
    updates.add_argument("--auto-update", dest="automatic_updates", action="store_true", default=None)
    updates.add_argument("--no-auto-update", dest="automatic_updates", action="store_false", help="disable automatic upgrades for this installation")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--project-id")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--runtime-host", choices=["local", "ssh", "wsl"])
    parser.add_argument("--ssh-target")
    parser.add_argument("--wsl-distribution")
    parser.add_argument("--expected-machine-id")
    parser.add_argument("--expected-account")
    parser.add_argument("--expected-user-home")
    parser.add_argument("--harness", nargs="+", choices=["codex", "opencode"],
                        default=["codex", "opencode"])
    parser.add_argument("--runtime-only", action="store_true")
    parser.add_argument("--chatgpt-web", choices=WEB_CHOICES)
    parser.add_argument("--tunnel-id")
    args = parser.parse_args()
    try:
        if args.update or args.set_auto_update:
            root = install_root()
            module = update_module(root) if (root / "acs_update.py").is_file() else update_module(Path(__file__).parent)
            if args.set_auto_update:
                with installation_lock(root):
                    state = json.loads((root / "state.json").read_text())
                    if machine_binding(observe_machine()) != machine_binding(state["machine"]):
                        raise ValueError("installation_machine_binding_changed")
                    if args.set_auto_update != "status":
                        enabled = args.set_auto_update == "on"
                        state.setdefault("auto_update", {})["enabled"] = enabled
                        write_state(root, state)
                        state["auto_update"]["schedule"] = module.configure_schedule(root, enabled, state["launcher_python"])
                        write_state(root, state)
                    policy = state.get("auto_update", {"enabled": True})
                    print(json.dumps({**policy, "schedule": module.schedule_status(root, policy)}, indent=2))
                    return 0
            result = module.run_update(root, apply=args.apply, force=args.force_check)
            print(json.dumps(result, indent=2))
            return 2 if result["state"] == "failed" else 0
        if args.rollback:
            if not args.apply:
                raise ValueError("rollback requires --apply")
            print(json.dumps(rollback(), indent=2))
        else:
            print(json.dumps(install(args.version, apply=args.apply, project=args.project,
                                     project_id=args.project_id, runtime_host=args.runtime_host,
                                     ssh_target=args.ssh_target, wsl_distribution=args.wsl_distribution,
                                     expected_machine_id=args.expected_machine_id,
                                     expected_account=args.expected_account,
                                     expected_user_home=args.expected_user_home,
                                     chatgpt_web=args.chatgpt_web, tunnel_id=args.tunnel_id,
                                     harnesses=args.harness, runtime_only=args.runtime_only,
                                     automatic_updates=args.automatic_updates), indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, urllib.error.URLError, subprocess.SubprocessError) as error:
        print(json.dumps({"schema_version": "acs-install-plan/2", "state": "blocked",
                          "reason": str(error)[:300]}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
