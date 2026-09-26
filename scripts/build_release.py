"""Build a source-bound ACS distribution archive and digest manifest."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import stat
import subprocess
import tarfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDE_ROOTS = {
    ".github",
    "assets",
    "docs",
    "references",
    "runtime",
    "runtime_deployment",
    "scripts",
    "tests",
    "runtime_tests",
    "tools/runtime",
    "tools/bootstrap",
    "README.md",
    "README.zh-CN.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "LICENSE",
    "SKILL.md",
    "VERSION",
    "pyproject.toml",
    "uv.lock",
    "docker-compose.acs-p1.yml",
    "docker-compose.acs-local.yml",
    "AGENTS.md",
}
EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", "dist", ".venv", ".tmp"}


def git(*args: str) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=True)
    return result.stdout.decode("utf-8").strip()


def included(relative: str) -> bool:
    path = Path(relative)
    if any(part in EXCLUDE_PARTS for part in path.parts):
        return False
    return any(relative == root or relative.startswith(root + "/") for root in INCLUDE_ROOTS)


def tracked_payload() -> dict[str, bytes]:
    if git("status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("release source worktree must be clean")
    names = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True
    ).stdout.split(b"\0")
    payload: dict[str, bytes] = {}
    for encoded in names:
        if not encoded:
            continue
        relative = encoded.decode("utf-8")
        if not included(relative):
            continue
        path = ROOT / relative
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode):
            raise ValueError(f"release entry is not a regular file: {relative}")
        payload[relative] = path.read_bytes()
    for required in ("LICENSE", "README.md", "SKILL.md", "pyproject.toml", "uv.lock"):
        if required not in payload:
            raise ValueError(f"release entry missing: {required}")
    return dict(sorted(payload.items()))


def build(output: Path, version: str) -> dict:
    if not version or any(char not in "0123456789." for char in version):
        raise ValueError("version must be a numeric dotted release")
    payload = tracked_payload()
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("release output directory must be empty")
    output.mkdir(parents=True, exist_ok=True)
    prefix = f"agent-collaboration-v{version}"
    manifest = {
        "schema_version": "acs-release-manifest/1",
        "version": version,
        "commit": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "files": {
            name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in payload.items()
        },
    }
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    dependencies = [
        {
            "name": item["name"],
            "version": item["version"],
            "source": item["source"].get("registry", "local"),
        }
        for item in lock["package"]
    ]
    payload["DEPENDENCIES.json"] = (
        json.dumps(
            {"schema_version": "acs-locked-dependencies/1", "packages": dependencies},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode()
    payload["LICENSES.md"] = (
        b"# Distribution licenses\n\n"
        b"ACS source: see LICENSE for Sustainable Use License 1.0.\n\n"
        b"Python dependencies: see DEPENDENCIES.json for the exact locked package "
        b"versions and uv.lock for artifact digests. Their upstream license texts "
        b"remain with the respective packages.\n\n"
        b"Service images: see docker-compose.acs-local.yml for exact image tags "
        b"and verify their upstream license notices before publication.\n"
    )
    payload["RELEASE-MANIFEST.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode()
    zip_path = output / f"{prefix}.zip"
    tar_path = output / f"{prefix}.tar.gz"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in payload.items():
            archive_name = f"{prefix}/{name}"
            info = zipfile.ZipInfo(archive_name, date_time=(2020, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    with (
        tar_path.open("wb") as stream,
        gzip.GzipFile(fileobj=stream, mode="wb", mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as archive,
    ):
        for name, data in payload.items():
            archive_name = f"{prefix}/{name}"
            info = tarfile.TarInfo(archive_name)
            info.size = len(data)
            info.mode = 0o644
            info.mtime = 0
            archive.addfile(info, io.BytesIO(data))
    sums = output / "SHA256SUMS.txt"
    sums.write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            for path in (zip_path, tar_path)
        ),
        encoding="ascii",
    )
    return {
        "commit": manifest["commit"],
        "tree": manifest["tree"],
        "file_count": len(payload),
        "archives": [str(zip_path), str(tar_path)],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.version), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
