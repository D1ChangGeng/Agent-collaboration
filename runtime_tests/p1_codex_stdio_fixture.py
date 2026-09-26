#!/usr/bin/env python3
"""No-model Codex-shaped JSON-RPC peer for a real hosted process boundary."""

from __future__ import annotations

import json
import os
import sys

turns = []


def thread():
    return {
        "id": "fixture-thread-1",
        "sessionId": "fixture-session-1",
        "turns": [],
        "status": {"type": "active" if turns else "idle"},
    }


def respond(request):
    method = request["method"]
    params = request.get("params", {})
    if method == "initialize":
        return {"userAgent": "codex/0.153.2", "codexHome": os.environ["CODEX_HOME"]}
    if method == "thread/start":
        return {
            "thread": thread(),
            "cwd": os.getcwd(),
            "approvalPolicy": "never",
            "activePermissionProfile": {"id": "test-profile"},
        }
    if method == "experimentalFeature/list":
        return {
            "data": [
                {"name": "multi_agent", "enabled": False},
                {"name": "multi_agent_v2", "enabled": False},
            ]
        }
    if method == "thread/read":
        return {"thread": thread()}
    if method == "thread/turns/list":
        return {"data": turns}
    if method == "turn/start":
        turn = {
            "id": "fixture-turn-1",
            "status": "inProgress",
            "items": [
                {
                    "id": "fixture-item-1",
                    "type": "userMessage",
                    "clientId": params["clientUserMessageId"],
                    "content": params["input"],
                }
            ],
        }
        turns.append(turn)
        return {"turn": turn}
    return {"unsupported": method}


for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    result = respond(request)
    sys.stdout.write(json.dumps({"id": request["id"], "result": result}) + "\n")
    sys.stdout.flush()
