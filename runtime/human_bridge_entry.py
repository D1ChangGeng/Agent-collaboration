"""Owner-only local Human Bridge provider administration entry point."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from runtime.human_bridge_dispatch import provision_local_provider
from runtime.human_bridge_file_provider import LocalHumanBridgeTransport


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("provision")
    snapshot = commands.add_parser("snapshot")
    snapshot.add_argument("--effect-id")
    args = parser.parse_args(argv)
    try:
        if args.command == "provision":
            root = provision_local_provider(args.root)
            result = {"status": "provisioned", "root": str(root)}
        else:
            provider = LocalHumanBridgeTransport(args.root)
            try:
                result = (
                    provider.readback(args.effect_id)
                    if args.effect_id else provider.journal_snapshot()
                )
            finally:
                provider.close()
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)[:300]}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
