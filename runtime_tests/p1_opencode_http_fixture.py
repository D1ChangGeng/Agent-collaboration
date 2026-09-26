"""A no-model OpenCode-shaped HTTP process for Systemd/Domain tests."""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from runtime_tests.test_opencode_driver import NativeHttpPeer


def main() -> int:
    argv = sys.argv[1:]
    if argv[:2] != ["--pure", "serve"] or "--port" not in argv:
        return 2
    port = int(argv[argv.index("--port") + 1])
    password = os.environ["OPENCODE_SERVER_PASSWORD"]
    config_root = Path(os.environ["XDG_CONFIG_HOME"])
    profile = SimpleNamespace(
        config_path=config_root / "opencode" / "opencode.json",
        schema_path=Path(os.environ["ACS_P1_FIXTURE_SCHEMA"]),
        cwd=os.getcwd(),
    )
    peer = NativeHttpPeer(port, password, profile)
    handler = peer.server.RequestHandlerClass
    original_answer = handler.answer
    original_post = handler.do_POST

    def answer(self, status, value=None):
        if urlsplit(self.path).path == "/global/health":
            value = {"healthy": True, "version": "1.18.30"}
        return original_answer(self, status, value)

    def post(self):
        result = original_post(self)
        if urlsplit(self.path).path.endswith("/prompt_async") and peer.busy:
            peer.finish()
        return result

    handler.answer = answer
    handler.do_POST = post

    def stop(_signal, _frame):
        peer.close()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    while True:
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
