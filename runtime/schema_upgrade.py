"""Guarded helper for applying the isolated candidate SQL to a disposable schema."""
from __future__ import annotations

import hashlib
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema_1_9.sql")
REQUIRED_BASE_TABLES = ("delivery_messages", "delivery_attempts", "delivery_receipts", "outbox")
SCHEMA_NAME = "acs-p1-runtime"
FROM_SCHEMA_VERSION = "1.8"
TO_SCHEMA_VERSION = "1.9"
FROM_SCHEMA_CHECKSUM = "b8554614d9923ae43a653371c4445c33fdfe189c219b3376f29e23c476ee7614"


def schema_bytes() -> bytes:
    return SCHEMA_PATH.read_bytes()


def schema_sha256() -> str:
    return hashlib.sha256(schema_bytes()).hexdigest()


def apply_candidate_schema(
    connection,
    *,
    integrated_schema_checksum: str | None = None,
    standalone_fixture: bool = False,
) -> str:
    """Apply 1.9 after 1.8, or explicitly prepare a disposable standalone fixture."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT required.name,to_regclass(required.name) "
            "FROM unnest(%s::text[]) AS required(name)",
            (list(REQUIRED_BASE_TABLES),),
        )
        missing = [name for name, relation in cursor.fetchall() if relation is None]
        if missing:
            raise RuntimeError("candidate base tables missing: " + ",".join(sorted(missing)))
        if not standalone_fixture:
            if (integrated_schema_checksum is None or len(integrated_schema_checksum) != 64
                    or any(value not in "0123456789abcdef"
                           for value in integrated_schema_checksum)):
                raise RuntimeError("integrated Runtime 1.9 schema checksum is required")
            cursor.execute(
                "SELECT schema_version,schema_checksum FROM runtime_schema_metadata "
                "WHERE schema_name=%s FOR UPDATE",
                (SCHEMA_NAME,),
            )
            metadata = cursor.fetchone()
            if metadata == (TO_SCHEMA_VERSION, integrated_schema_checksum):
                cursor.execute(schema_bytes())
                return schema_sha256()
            if metadata is not None and metadata[0] == TO_SCHEMA_VERSION:
                raise RuntimeError("Runtime schema 1.9 checksum differs")
            if metadata != (FROM_SCHEMA_VERSION, FROM_SCHEMA_CHECKSUM):
                raise RuntimeError("Runtime schema 1.9 requires receiver transport schema 1.8")
        cursor.execute(schema_bytes())
        if not standalone_fixture:
            cursor.execute(
                "UPDATE runtime_schema_metadata SET schema_version=%s,schema_checksum=%s "
                "WHERE schema_name=%s",
                (TO_SCHEMA_VERSION, integrated_schema_checksum, SCHEMA_NAME),
            )
    return schema_sha256()
