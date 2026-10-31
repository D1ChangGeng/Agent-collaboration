"""Read-only startup validation; schema adoption remains an operator action."""
from __future__ import annotations

import psycopg

from runtime.communication_storage import (
    adopt_core,
    missing_relation,
    schema_definition,
    verify_core,
)
from runtime.errors import SchemaAdoptionError

SCHEMAS = (
    ("project_schema.sql", "acs-project-runtime", "project"),
    ("communication_schema.sql", "acs-communication", "communication"),
    ("communication_notice_schema.sql", "acs-communication-notices", "communication notice"),
    ("communication_archive_schema.sql", "acs-communication-archives", "communication archive"),
)
SCHEMA_VERSIONS = {"project_schema.sql": "2"}
PREVIOUS_SCHEMAS = {"acs-project-runtime": {
    ("1", "6fedb1731cde6224c0ec4770d7d5b18580d60554e9ef7b82739679b9bcfc0440"),
    ("1", "ccad2138f9ed4cddbe2e7e30ed797b4ead75d3c1359e4401997906e1233bfa3a"),
}}
SCHEMA_RELATIONS = {
    "project_schema.sql": ("collaboration_projects", "collaboration_memberships", "collaboration_routes", "collaboration_route_grants",
        "collaboration_commands", "collaboration_sources", "collaboration_source_snapshots", "collaboration_teams",
        "collaboration_team_members", "collaboration_notification_sessions"),
    "communication_schema.sql": ("communication_clients", "communication_messages", "communication_replies",
        "communication_waits", "communication_notices"),
    "communication_notice_schema.sql": ("communication_supervisors", "communication_notice_routes"),
    "communication_archive_schema.sql": ("communication_archives",),
}
CORE_RELATIONS = tuple(name for names in SCHEMA_RELATIONS.values() for name in names)


class ProjectSchemaAdoptionRequired(RuntimeError):
    pass


def definition(filename):
    return schema_definition(filename, SCHEMA_VERSIONS.get(filename, "1"))


def adopt_project_schema(connection):
    """Explicit operator transaction, shared by setup and the adoption CLI."""
    adopt_core(connection)
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('acs-project-schema:' || current_schema(),0))")
    for filename, name, label in SCHEMAS:
        schema, checksum, equivalent = definition(filename)
        current = connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata "
                                     "WHERE schema_name=%s FOR UPDATE", (name,)).fetchone()
        if current is not None:
            if current not in equivalent | PREVIOUS_SCHEMAS.get(name, set()):
                raise ValueError(f"{label} schema requires explicit migration")
            missing = missing_relation(connection, SCHEMA_RELATIONS[filename])
            if missing is not None:
                raise ValueError(f"{label} storage is incomplete: {missing[0]}")
        elif connection.execute("SELECT name FROM unnest(%s::text[]) AS name "
                "WHERE to_regclass(name) IS NOT NULL LIMIT 1", (list(SCHEMA_RELATIONS[filename]),)).fetchone():
            raise ValueError(f"{label} storage is unversioned")
        connection.execute(schema)
        connection.execute("INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) "
            "VALUES (%s,%s,%s) ON CONFLICT(schema_name) DO UPDATE SET "
            "schema_version=EXCLUDED.schema_version,schema_checksum=EXCLUDED.schema_checksum",
            (name, SCHEMA_VERSIONS.get(filename, "1"), checksum))


def verify_project_schema(authority):
    if not callable(getattr(authority, "_connect", None)):
        return False  # A metadata-only facade has no storage capability to verify.
    try:
        with authority._connect() as connection:
            verify_core(connection)
            for filename, name, _label in SCHEMAS:
                current = connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s", (name,)).fetchone()
                if current not in definition(filename)[2]:
                    raise ProjectSchemaAdoptionRequired("project_schema_adoption_required")
            for name in CORE_RELATIONS:
                if connection.execute("SELECT to_regclass(%s)", (name,)).fetchone()[0] is None:
                    raise ProjectSchemaAdoptionRequired("project_schema_adoption_required")
    except (psycopg.Error, SchemaAdoptionError) as error:
        raise ProjectSchemaAdoptionRequired("project_schema_adoption_required") from error
    return True
