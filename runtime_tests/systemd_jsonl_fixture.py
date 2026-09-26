"""Synthetic bidirectional JSONL root process with a setsid grandchild."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time


def emit(value, *, stream=sys.stdout) -> None:
    stream.write(json.dumps(value, sort_keys=True) + "\n")
    stream.flush()


def grandchild() -> None:
    while True:
        time.sleep(1)


def server() -> None:
    child = None
    for raw in sys.stdin:
        request = json.loads(raw)
        command = request.get("command")
        if command == "ping":
            emit({"kind": "pong", "value": request.get("value"), "pid": os.getpid()})
            emit({"kind": "stderr", "value": request.get("value")}, stream=sys.stderr)
        elif command == "spawn":
            child = subprocess.Popen(
                [sys.executable, os.path.abspath(__file__), "--grandchild"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, close_fds=True,
            )
            emit({"kind": "spawned", "pid": child.pid})
        elif command == "env-digest":
            name = request.get("name")
            value = os.environ.get(name, "") if isinstance(name, str) else ""
            emit({"kind": "env-digest", "name": name,
                  "sha256": hashlib.sha256(value.encode()).hexdigest()})
        elif command == "exit-clean":
            emit({"kind": "root-exiting-clean"})
            os._exit(0)
        elif command == "exit-root":
            emit({"kind": "root-exiting", "child_pid": child.pid if child else None})
            os._exit(0)
        else:
            emit({"kind": "error", "reason": "unknown command"})


if __name__ == "__main__":
    grandchild() if sys.argv[1:] == ["--grandchild"] else server()
