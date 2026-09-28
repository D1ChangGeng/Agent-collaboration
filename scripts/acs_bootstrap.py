"""Install ACS from a verified GitHub Release asset.

The bootstrapper owns distribution acquisition and versioned installation. It
does not modify a project checkout until the selected release is verified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

REPOSITORY = "D1ChangGeng/Agent-collaboration"
DEFAULT_VERSION = "v1.1.0"
SCHEMA = "acs-bootstrap-state/1"


def install_root() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AgentCollaboration"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "agent-collaboration"


def ensure_install_root() -> Path:
    root = install_root()
    if root.exists() and root.is_symlink():
        raise ValueError("installation root must not be a symlink")
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
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if os.name == "posix":
        temporary.chmod(0o600)
    os.replace(temporary, target)


def install(version: str, *, apply: bool, project: Path | None, project_id: str | None) -> dict:
    metadata = release_metadata(version)
    wanted = f"agent-collaboration-{version}"
    asset = next((item for item in metadata["assets"] if item.get("name") == wanted + ".zip"), None)
    sums = next((item for item in metadata["assets"] if item.get("name") == "SHA256SUMS.txt"), None)
    if not asset or not sums:
        raise ValueError("release does not contain the required archive and digest manifest")
    root = ensure_install_root()
    result = {"schema_version": "acs-install-plan/2", "version": version,
              "release_url": metadata.get("html_url"), "install_root": str(root),
              "archive": asset["name"], "state": "planned"}
    if not apply:
        return result
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix=".acs-install-", dir=root))
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
        versions = root / "versions"
        versions.mkdir(exist_ok=True)
        target = versions / version.lstrip("v")
        if target.exists():
            if target.is_symlink() or not target.is_dir():
                raise ValueError("existing version path is unsafe")
            current_manifest = json.loads((target / "RELEASE-MANIFEST.json").read_text(encoding="utf-8"))
            if current_manifest != manifest:
                raise ValueError("existing version contains different release bytes")
        else:
            shutil.copytree(verified, target)
        previous = (root / "current").read_text(encoding="utf-8").strip() if (root / "current").is_file() else None
        installer = target / "scripts" / "acs_install.py"
        if not installer.is_file():
            raise ValueError("verified release is missing its installer")
        if project is not None:
            project = project.expanduser().resolve()
            if not project.is_dir():
                raise ValueError("project path is not a directory")
            command = [sys.executable, str(installer), "--apply", "--harness", "codex", "opencode"]
            if not project_id:
                raise ValueError("project_id is required when --project is supplied")
            command.extend(["--project", str(project), "--project-id", project_id])
            subprocess.run(command, cwd=target, check=True)
        (root / "current.tmp").write_text(str(target), encoding="utf-8")
        os.replace(root / "current.tmp", root / "current")
        write_state(root, {"schema_version": SCHEMA, "version": version,
                           "current": str(target), "previous": previous,
                           "commit": manifest["commit"], "tree": manifest["tree"]})
        result.update({"state": "installed", "commit": manifest["commit"], "tree": manifest["tree"],
                       "current": str(target), "rollback": previous})
        return result
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def rollback() -> dict:
    root = ensure_install_root()
    state_path = root / "state.json"
    if not state_path.is_file():
        raise ValueError("no installation state is available")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    previous = state.get("previous")
    if not isinstance(previous, str) or not Path(previous).is_dir():
        raise ValueError("no verified previous version is available")
    current = state.get("current")
    manifest = json.loads((Path(previous) / "RELEASE-MANIFEST.json").read_text(encoding="utf-8"))
    temporary = root / "current.tmp"
    temporary.write_text(previous, encoding="utf-8")
    os.replace(temporary, root / "current")
    write_state(root, {"schema_version": SCHEMA, "version": "v" + manifest["version"],
                       "current": previous, "previous": current,
                       "commit": manifest["commit"], "tree": manifest["tree"]})
    return {"schema_version": "acs-install-plan/2", "state": "rolled_back",
            "current": previous, "commit": manifest["commit"], "tree": manifest["tree"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--project-id")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    try:
        if args.rollback:
            print(json.dumps(rollback(), indent=2))
        else:
            print(json.dumps(install(args.version, apply=args.apply, project=args.project,
                                     project_id=args.project_id), indent=2))
        return 0
    except (OSError, ValueError, TypeError, urllib.error.URLError, subprocess.CalledProcessError) as error:
        print(json.dumps({"schema_version": "acs-install-plan/2", "state": "blocked",
                          "reason": str(error)[:300]}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
