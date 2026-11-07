"""Explicit adoption of real viewer-projection event producers."""
from __future__ import annotations

import re

from runtime.communication_storage import schema_definition
from runtime.errors import SchemaAdoptionError

NAME, FILE, VERSION = "acs-communication-projection-events", "communication_projection_event_schema.sql", "1"
TRIGGERS = {"acs_projection_conversation_event": ("communication_conversation_versions", 21),
    "acs_projection_notice_event": ("communication_notice_view_versions", 21),
    "acs_projection_notice_created": ("communication_notices", 5)}


def _shape(connection, checksum):
    bodies = dict(re.findall(r"CREATE FUNCTION ([a-z_]+)\(\) RETURNS trigger LANGUAGE plpgsql AS \$\$(.*?)\$\$;",
                            schema_definition(FILE, VERSION)[0].decode(), re.DOTALL))
    for name, (table, kind) in TRIGGERS.items():
        row = connection.execute("SELECT t.tgtype,t.tgenabled,t.tgfoid=to_regprocedure(%s),p.prosrc,p.prosecdef,p.provolatile,"
            "cardinality(t.tgattr::smallint[]) FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid "
            "WHERE t.tgname=%s AND t.tgrelid=to_regclass(%s) AND NOT t.tgisinternal", (name + "()", name, table)).fetchone()
        if (row is None or row[0] != kind or row[1] not in {"O", "A"} or row[2] is not True
                or row[3].strip() != bodies[name].strip() or row[4:] != (False, "v", 0)):
            raise SchemaAdoptionError(NAME, checksum, "damaged projection event source")


def adopt_projection_event_storage(connection):
    source, checksum, equivalents = schema_definition(FILE, VERSION)
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('acs-projection-events:'||current_schema(),0))")
    row = connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s FOR UPDATE", (NAME,)).fetchone()
    if row is None:
        for trigger, (table, _kind) in TRIGGERS.items():
            if connection.execute("SELECT 1 FROM pg_trigger WHERE tgname=%s AND tgrelid=to_regclass(%s) AND NOT tgisinternal",
                                  (trigger, table)).fetchone():
                raise SchemaAdoptionError(NAME, checksum, "unversioned projection event trigger")
        connection.execute(source)
        connection.execute("INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) VALUES (%s,%s,%s)", (NAME, VERSION, checksum))
    elif row not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "explicit projection event migration required")
    _shape(connection, checksum)


def verify_projection_event_storage(connection):
    _source, checksum, equivalents = schema_definition(FILE, VERSION)
    if connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone() not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "projection event adoption required")
    _shape(connection, checksum)
