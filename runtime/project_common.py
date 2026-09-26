"""Canonical project identities shared by typed Domain adapters."""
from __future__ import annotations

import hashlib
import json
import re

IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def handle(kind: str, project_id: str, identifier: str) -> str:
    if not IDENTIFIER.fullmatch(project_id) or not IDENTIFIER.fullmatch(identifier):
        raise ValueError("invalid project handle identity")
    return f"{kind}:{project_id}:{identifier}"


def parse_handle(value: str, kind: str, project_id: str) -> str:
    fields = value.split(":")
    if (len(fields) != 3 or fields[:2] != [kind, project_id]
            or not IDENTIFIER.fullmatch(fields[2])):
        raise ValueError("project handle mismatch")
    return fields[2]
