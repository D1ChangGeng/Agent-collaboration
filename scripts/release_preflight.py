"""Read-only v1.0.0 publication preflight for the frozen release candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "D1ChangGeng/Agent-collaboration"
BRANCH = "codex/p2-v1-release"
VERSION = "1.0.0"


def run(*args: str, cwd: Path = ROOT) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def git_value(*args: str) -> str:
    return run("git", *args)


def gh_json(*args: str) -> dict:
    return json.loads(run("gh", *args))


def build_and_verify() -> dict:
    from build_release import build

    with tempfile.TemporaryDirectory(prefix="acs-release-preflight-") as directory:
        result = build(Path(directory), VERSION)
        output = Path(directory)
        archives = {}
        for name in (f"agent-collaboration-v{VERSION}.zip", f"agent-collaboration-v{VERSION}.tar.gz"):
            path = output / name
            archives[name] = {
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        with zipfile.ZipFile(output / f"agent-collaboration-v{VERSION}.zip") as archive:
            prefix = f"agent-collaboration-v{VERSION}/"
            manifest = json.loads(archive.read(prefix + "RELEASE-MANIFEST.json"))
            if manifest["commit"] != result["commit"] or manifest["tree"] != result["tree"]:
                raise RuntimeError("release manifest identity differs from candidate")
            if b"Sustainable Use License" not in archive.read(prefix + "LICENSE"):
                raise RuntimeError("release archive does not contain the selected license")
        return {**result, "archives": archives}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    commit = git_value("rev-parse", "HEAD")
    tree = git_value("rev-parse", "HEAD^{tree}")
    if git_value("status", "--porcelain=v1", "--untracked-files=all"):
        raise SystemExit("release candidate working tree is not clean")
    if git_value("branch", "--show-current") != BRANCH:
        raise SystemExit(f"release candidate branch must be {BRANCH}")
    remote = run("git", "ls-remote", "origin", f"refs/heads/{BRANCH}").split()[0]
    if remote != commit:
        raise SystemExit("candidate branch is not pushed at the checked-out commit")
    repository = gh_json("api", f"repos/{REPOSITORY}")
    if repository.get("visibility") != "public":
        raise SystemExit("GitHub repository is not public")
    pull = gh_json("pr", "view", "1", "--json", "state,isDraft,headRefOid,baseRefOid")
    base = run("git", "ls-remote", "origin", f"refs/heads/{repository.get('default_branch', 'main')}").split()[0]
    if pull["state"] != "OPEN" or pull["headRefOid"] != commit or pull["baseRefOid"] != base:
        raise SystemExit("release PR does not point to the frozen candidate")
    runs = json.loads(run("gh", "run", "list", "--branch", BRANCH, "--limit", "10", "--json", "databaseId,headSha,status,conclusion"))
    successful = [item for item in runs if item["headSha"] == commit and item["status"] == "completed" and item["conclusion"] == "success"]
    if not successful:
        raise SystemExit("no successful CI run exists for the frozen candidate")
    tags = run("git", "ls-remote", "origin", f"refs/tags/v{VERSION}")
    if tags:
        raise SystemExit("v1.0.0 tag already exists before product-owner release approval")
    release = subprocess.run(["gh", "release", "view", f"v{VERSION}"], cwd=ROOT, capture_output=True, text=True, check=False)
    if release.returncode == 0:
        raise SystemExit("v1.0.0 GitHub Release already exists before product-owner release approval")
    payload = {
        "repository_visibility": repository.get("visibility"),
        "branch": BRANCH,
        "commit": commit,
        "tree": tree,
        "ci_run": successful[0]["databaseId"],
        "pr": pull,
        "license_file": "Sustainable Use License 1.0",
        "release": build_and_verify(),
        "publish_state": "awaiting_product_owner_release_approval",
    }
    print(json.dumps(payload, indent=2, sort_keys=True) if args.json else "release preflight passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
