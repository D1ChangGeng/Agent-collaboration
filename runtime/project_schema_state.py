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
    ("1", "2a5a388410369b1c0c37a6a803d2dbb60df451b879fba50d54711f84e4902305"),
    ("1", "89d5e958bcd75d4b7faf901b297ad63cc208ef45196bac6217afa32d5f6973c9"),
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
            has_wait_storage = connection.execute("SELECT 1 FROM runtime_schema_metadata WHERE schema_name='acs-communication-wait-ingress'").fetchone() is not None
            authority._wait_ingress_storage_available = has_wait_storage
            if getattr(authority, "_wait_ingress_recovery_enabled", False) or has_wait_storage:
                from runtime.communication_wait_ingress import verify_wait_ingress

                verify_wait_ingress(connection)
            if getattr(authority, "_notification_frontiers_enabled", False):
                from runtime.communication_notifications import verify_notification_frontiers

                verify_notification_frontiers(connection)
            has_client_storage = connection.execute("SELECT 1 FROM runtime_schema_metadata WHERE schema_name='acs-communication-client-storage'").fetchone() is not None
            if getattr(authority, "_communication_client_api_enabled", False) or has_client_storage:
                from runtime.communication_client_storage import verify_client_storage

                verify_client_storage(connection)
            has_viewer_storage = connection.execute("SELECT 1 FROM runtime_schema_metadata WHERE schema_name='acs-client-viewer-ownership'").fetchone() is not None
            if getattr(authority, "_communication_client_api_enabled", False) or has_viewer_storage:
                from runtime.communication_client_viewer_storage import verify_viewer_storage

                verify_viewer_storage(connection)
            has_notice_storage = connection.execute("SELECT 1 FROM runtime_schema_metadata WHERE schema_name='acs-communication-client-notices'").fetchone() is not None
            if getattr(authority, "_communication_client_api_enabled", False) or has_notice_storage:
                from runtime.communication_client_notice_storage import verify_notice_storage

                verify_notice_storage(connection)
            has_event_storage = connection.execute("SELECT 1 FROM runtime_schema_metadata WHERE schema_name='acs-communication-events'").fetchone() is not None
            has_native_link_storage = connection.execute("SELECT 1 FROM runtime_schema_metadata WHERE schema_name='acs-communication-native-links'").fetchone() is not None
            authority._communication_native_link_storage_available = has_native_link_storage
            if has_native_link_storage or getattr(authority, "_communication_native_link_settings", None) is not None:
                from runtime.communication_native_link_storage import verify_native_link_storage

                verify_native_link_storage(connection)
            has_attachment_storage = connection.execute("SELECT 1 FROM runtime_schema_metadata WHERE schema_name='acs-communication-attachments'").fetchone() is not None
            authority._communication_attachment_storage_available = has_attachment_storage
            if getattr(authority, "_communication_attachment_settings", None) is not None or has_attachment_storage:
                from runtime.communication_attachment_storage import verify_attachment_storage

                verify_attachment_storage(connection)
            has_attachment_events = connection.execute("SELECT 1 FROM runtime_schema_metadata WHERE schema_name='acs-communication-attachment-events'").fetchone() is not None
            authority._communication_attachment_event_storage_available = has_attachment_events
            if has_attachment_events or getattr(authority, "_communication_attachment_settings", None) is not None and has_event_storage:
                from runtime.communication_attachment_event_storage import (
                    verify_attachment_event_storage,
                )

                verify_attachment_event_storage(connection)
            for schema_name, attribute, module_name, function_name in (
                ("acs-conversation-view-versions", "_communication_conversation_storage_available", "runtime.communication_conversation_storage", "verify_conversation_storage"),
                ("acs-notice-projections", "_communication_notice_projection_available", "runtime.communication_notice_projection_storage", "verify_notice_projection_storage"),
                ("acs-receiver-observations", "_communication_receiver_observation_available", "runtime.communication_receiver_observation_storage", "verify_receiver_observation_storage"),
                ("acs-communication-projection-events", "_communication_projection_events_available", "runtime.communication_projection_event_storage", "verify_projection_event_storage"),
            ):
                present = connection.execute("SELECT 1 FROM runtime_schema_metadata WHERE schema_name=%s", (schema_name,)).fetchone() is not None
                setattr(authority, attribute, present)
                if getattr(authority, "_communication_events_enabled", False) or present:
                    from importlib import import_module

                    getattr(import_module(module_name), function_name)(connection)
            authority._communication_event_storage_available = has_event_storage
            if getattr(authority, "_communication_events_enabled", False) or has_event_storage:
                from runtime.communication_event_storage import verify_event_storage

                verify_event_storage(connection)
            has_snapshot_storage = connection.execute("SELECT 1 FROM runtime_schema_metadata WHERE schema_name='acs-communication-snapshots'").fetchone() is not None
            authority._communication_snapshot_storage_available = has_snapshot_storage
            if getattr(authority, "_communication_events_enabled", False) or has_snapshot_storage:
                from runtime.communication_snapshot_storage import verify_snapshot_storage

                verify_snapshot_storage(connection)
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
