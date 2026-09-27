"""Bounded native JSON shared by command and transport schemas."""

from __future__ import annotations

import json
import math

MAX_COMMAND_BYTES = 1024 * 1024
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 20000


def bounded_payload(value):
    if not isinstance(value, dict):
        raise TypeError("payload must be an object")
    pending = [(value, 0)]
    visited = 0
    while pending:
        item, depth = pending.pop()
        visited += 1
        if depth > MAX_JSON_DEPTH or visited > MAX_JSON_NODES:
            raise ValueError("payload exceeds structural limits")
        if isinstance(item, dict):
            if len(item) > MAX_JSON_NODES or any(not isinstance(key, str) for key in item):
                raise ValueError("payload object keys are invalid")
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, (list, tuple)):
            if len(item) > MAX_JSON_NODES:
                raise ValueError("payload array exceeds limits")
            pending.extend((child, depth + 1) for child in item)
        elif item is not None and type(item) not in (str, bool, int, float):
            raise ValueError("payload contains a non-JSON value")
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError("payload contains a non-finite number")
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_COMMAND_BYTES:
        raise ValueError("payload exceeds byte limit")
    # Legacy tuple[str, ...] values retain exactly the same JSON array encoding.
    return json.loads(encoded)
