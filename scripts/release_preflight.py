"""Read-only checks binding a release candidate, source commit and GitHub CI."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "D1ChangGeng/Agent-collaboration"


def run(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def build_and_verify(version: str) -> dict:
    from build_release import build

    with tempfile.TemporaryDirectory(prefix="acs-release-preflight-") as directory:
        result = build(Path(directory), version)
        archives = {}
        for name in (f"agent-collaboration-v{version}.zip", f"agent-collaboration-v{version}.tar.gz"):
            path = Path(directory) / name
            archives[name] = {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        with zipfile.ZipFile(Path(directory) / f"agent-collaboration-v{version}.zip") as archive:
            prefix = f"agent-collaboration-v{version}/"
            manifest = json.loads(archive.read(prefix + "RELEASE-MANIFEST.json"))
            if (manifest["commit"], manifest["tree"]) != (result["commit"], result["tree"]):
                raise ValueError("archive source identity differs from candidate")
            for name, expected in manifest["files"].items():
                data = archive.read(prefix + name)
                if len(data) != expected["bytes"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
                    raise ValueError("archive file differs from manifest: " + name)
        return {**result, "archives": archives}


def verify_ci(runs, commit):
    current = [item for item in runs if item["headSha"] == commit and item.get("workflowName") == "Validate ACS"]
    if not current or any(item["status"] != "completed" or item["conclusion"] != "success" for item in current):
        raise ValueError("candidate needs successful Validate ACS runs with no pending or failed run")
    return [item["databaseId"] for item in current]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--pull-request", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        parser.error("version must be a stable numeric major.minor.patch")
    if run("git", "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("release candidate worktree must be clean")
    commit, tree = run("git", "rev-parse", "HEAD"), run("git", "rev-parse", "HEAD^{tree}")
    if run("git", "branch", "--show-current") != args.branch:
        raise ValueError("checked-out branch differs from selected candidate")
    remote = run("git", "ls-remote", "origin", "refs/heads/" + args.branch).split()
    if not remote or remote[0] != commit:
        raise ValueError("candidate branch is not pushed at this commit")
    if args.pull_request:
        pull = json.loads(run("gh", "pr", "view", str(args.pull_request), "--repo", REPOSITORY,
                              "--json", "state,isDraft,headRefOid"))
        if pull["state"] != "OPEN" or pull["isDraft"] or pull["headRefOid"] != commit:
            raise ValueError("release pull request is not ready at this exact commit")
    runs = json.loads(run("gh", "run", "list", "--repo", REPOSITORY, "--commit", commit,
                         "--limit", "30", "--json", "databaseId,headSha,status,conclusion,workflowName"))
    successful = verify_ci(runs, commit)
    tag = "v" + args.version
    if run("git", "ls-remote", "origin", "refs/tags/" + tag):
        raise ValueError("release tag already exists; inspect instead of overwriting")
    existing = subprocess.run(["gh", "release", "view", tag, "--repo", REPOSITORY],
                              cwd=ROOT, capture_output=True, check=False)
    if existing.returncode == 0:
        raise ValueError("release exists; this check never replaces published assets")
    payload = {"branch": args.branch, "commit": commit, "tree": tree, "version": args.version,
               "ci_runs": successful, "release": build_and_verify(args.version), "publish_state": "ready_to_publish"}
    print(json.dumps(payload, indent=2) if args.json else "release preflight passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
