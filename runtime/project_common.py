"""Canonical project identities shared by typed Domain adapters."""
from __future__ import annotations

import hashlib
import json
import re

IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
ARTIFACT_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{65,383}\Z")


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def handle(kind: str, project_id: str, identifier: str) -> str:
    identity = ARTIFACT_IDENTIFIER if kind == "artifact" else IDENTIFIER
    if not IDENTIFIER.fullmatch(project_id) or not identity.fullmatch(identifier):
        raise ValueError("invalid project handle identity")
    return f"{kind}:{project_id}:{identifier}"


def parse_handle(value: str, kind: str, project_id: str) -> str:
    fields = value.split(":")
    identity = ARTIFACT_IDENTIFIER if kind == "artifact" else IDENTIFIER
    if (len(fields) != 3 or fields[:2] != [kind, project_id]
            or not identity.fullmatch(fields[2])):
        raise ValueError("project handle mismatch")
    return fields[2]


def page_result(project_id, rows, args, identity):
    """Bounded metadata pagination, independent of any business domain."""
    limit = args.get("limit", 50)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("invalid page size")
    rows = sorted(rows, key=lambda row: row[identity])
    rows = [row for row in rows if not args.get("cursor") or row[identity] > args["cursor"]]
    return "observed", {"project_id": project_id, "items": rows[:limit],
                        "next_cursor": rows[limit-1][identity] if len(rows) > limit else None}, []
