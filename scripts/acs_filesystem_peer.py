#!/usr/bin/env python3
"""Launch an admitted read-only SSH peer against the verified active Release."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--installation-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--machine-id", required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--read-root", type=Path, action="append", required=True)
    args = parser.parse_args(argv)
    launcher = args.installation_root / "acs_launcher.py"
    info = launcher.stat(follow_symlinks=False)
    if (launcher.is_symlink() or not launcher.is_file() or info.st_uid != os.getuid()
            or info.st_mode & 0o022):
        raise ValueError("installed launcher ownership differs")
    specification = importlib.util.spec_from_file_location("acs_bound_file_launcher", launcher)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    active, command = module.resolve_launch(args.installation_root, args.profile)
    manifest = json.loads((active / "RELEASE-MANIFEST.json").read_bytes())
    module.verify_file(active, manifest, "runtime/filesystem_peer_entry.py")
    config = module.exact_path(args.config, private=True, file=True)
    selected = [command[0], "-m", "runtime.filesystem_peer_entry", "--config", str(config),
                "--catalog", str(active / "docs/runtime/p2-mcp-tool-contract.json"),
                "--project-id", args.project_id, "--profile", args.profile,
                "--machine-id", args.machine_id, "--cwd", str(args.cwd)]
    for root in args.read_root:
        selected.extend(["--read-root", str(root)])
    os.chdir(active)
    os.execv(selected[0], selected)


if __name__ == "__main__":
    raise SystemExit(main())
