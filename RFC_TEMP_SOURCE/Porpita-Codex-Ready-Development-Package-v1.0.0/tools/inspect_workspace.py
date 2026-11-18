#!/usr/bin/env python3
"""Read-only local workspace inventory. No fetch, checkout, install or mutation."""
from __future__ import annotations
import argparse
import json
import subprocess
from pathlib import Path

def git(root: Path, *args: str) -> dict:
    try:
        result = subprocess.run(["git", "-C", str(root), *args], text=True, encoding="utf-8",
                                errors="replace", capture_output=True, timeout=20, check=False)
        return {"exit_code": result.returncode, "stdout": result.stdout[:20000],
                "stderr": result.stderr[:2000], "truncated": len(result.stdout) > 20000}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}

def inspect(root: Path) -> dict:
    root = root.expanduser().resolve()
    out = {"path": str(root), "exists": root.is_dir()}
    if not root.is_dir():
        return out
    out["head"] = git(root, "rev-parse", "HEAD")
    out["status"] = git(root, "status", "--short", "--untracked-files=normal")
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            obj = json.loads(pkg.read_text(encoding="utf-8"))
            out["package"] = {k: obj.get(k) for k in ("name", "version", "packageManager", "engines")}
            out["scripts"] = {k: v for k, v in obj.get("scripts", {}).items()
                              if k in {"dev", "typecheck", "build:desktop", "build:win", "build:linux", "build:mac", "test:e2e", "test:e2e:headful"}}
        except (OSError, ValueError) as exc:
            out["package_error"] = str(exc)
    probes = ["sdk/communication-client.ts", "sdk/orca-receiver-port.ts", "runtime/orca_receiver_backend.py",
              "config/electron-builder.config.cjs", "src/main/runtime/rpc/methods/orchestration/messaging/send-methods.ts",
              "src/main/native-chat/agent-session-wire/delivery/structured-agent-session-input-handover.ts",
              "src/renderer/src/components/native-chat/NativeChatView.tsx"]
    out["known_paths"] = {p: (root / p).is_file() for p in probes}
    return out

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--acs", type=Path, required=True)
    p.add_argument("--client", type=Path, required=True)
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    result = {"kind": "read_only_inventory_not_acceptance", "acs": inspect(a.acs), "client": inspect(a.client)}
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
