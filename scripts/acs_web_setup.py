"""Print an ACS ChatGPT connection plan for AI-guided private Tunnel setup."""
from __future__ import annotations

import argparse
import json

from acs_bootstrap import WEB_CHOICES, chatgpt_setup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--choice", choices=WEB_CHOICES)
    parser.add_argument("--runtime-root")
    parser.add_argument("--config")
    parser.add_argument("--tunnel-id")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        plan = chatgpt_setup(args.choice, args.runtime_root, args.config, args.tunnel_id)
        print(json.dumps(plan, indent=2))
        return 0
    except ValueError as error:
        print(json.dumps({"schema_version": "acs-chatgpt-setup/1", "state": "blocked",
                          "reason": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
