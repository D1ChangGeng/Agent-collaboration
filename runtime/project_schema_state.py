"""Read-only startup validation; schema adoption remains an operator action."""
from __future__ import annotations

import hashlib
from pathlib import Path

import psycopg

SCHEMAS = (
    ("project_schema.sql", "acs-project-runtime", "project"),
    ("project_control_schema.sql", "acs-project-control", "project control"),
    ("communication_schema.sql", "acs-communication", "communication"),
    ("communication_notice_schema.sql", "acs-communication-notices", "communication notice"),
    ("communication_archive_schema.sql", "acs-communication-archives", "communication archive"),
)
CORE_RELATIONS = ("communication_clients", "communication_messages", "communication_replies", "communication_waits",
                  "communication_notices", "communication_supervisors", "communication_notice_routes", "communication_archives")


class ProjectSchemaAdoptionRequired(RuntimeError):
    pass


def definition(filename):
    raw = Path(__file__).with_name(filename).read_bytes()
    schema = raw.replace(b"\r\n", b"\n")
    checksum = hashlib.sha256(schema).hexdigest()
    equivalents = {("1", hashlib.sha256(data).hexdigest()) for data in (raw, schema, schema.replace(b"\n", b"\r\n"))}
    return schema, checksum, equivalents


def verify_project_schema(authority):
    if not callable(getattr(authority, "_connect", None)):
        return False  # A metadata-only facade has no storage capability to verify.
    try:
        with authority._connect() as connection:
            for filename, name, _label in SCHEMAS:
                current = connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s", (name,)).fetchone()
                if current not in definition(filename)[2]:
                    raise ProjectSchemaAdoptionRequired("project_schema_adoption_required")
            for name in CORE_RELATIONS:
                if connection.execute("SELECT to_regclass(%s)", (name,)).fetchone()[0] is None:
                    raise ProjectSchemaAdoptionRequired("project_schema_adoption_required")
    except psycopg.Error as error:
        raise ProjectSchemaAdoptionRequired("project_schema_adoption_required") from error
    return True
