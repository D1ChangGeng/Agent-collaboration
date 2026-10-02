"""Print an ACS ChatGPT connection plan for AI-guided private Tunnel setup."""
from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path

from acs_bootstrap import WEB_CHOICES, chatgpt_setup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--choice", choices=WEB_CHOICES)
    parser.add_argument("--runtime-root")
    parser.add_argument("--installation-root", help="verified installation using the stable MCP launcher")
    parser.add_argument("--config")
    parser.add_argument("--tunnel-id")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        plan = chatgpt_setup(args.choice, args.runtime_root, args.config, args.tunnel_id)
        if args.installation_root and plan.get("runtime_process"):
            root = Path(args.installation_root)
            state = json.loads((root / "state.json").read_text())
            if (not root.is_absolute() or root.is_symlink() or state.get("current") != args.runtime_root
                    or state.get("runtime_config_ref") != args.config or not (root / "acs_launcher.py").is_file()):
                raise ValueError("web plan requires the matching verified installation")
            runtime = {"host": "selected_runtime_machine", "cwd": str(root), "command": state["launcher_python"],
                       "args": [str(root / "acs_launcher.py"), "--installation-root", str(root)], "config_ref": args.config}
            plan["runtime_process"] = runtime
            if plan["commands"]["init"]:
                plan["commands"]["init"][-1] = shlex.join([runtime["command"], *runtime["args"]])
        print(json.dumps(plan, indent=2))
        return 0
    except (ValueError, OSError, KeyError):
        print(json.dumps({"schema_version": "acs-chatgpt-setup/1", "state": "blocked",
                          "reason": "web_setup_inputs_or_installation_require_review"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
