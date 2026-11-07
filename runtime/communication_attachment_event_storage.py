"""Atomic owner-only ready metadata intents; blob bytes never enter events."""
from runtime.communication_storage import schema_definition
from runtime.errors import SchemaAdoptionError

NAME, FILE, VERSION = "acs-communication-attachment-events", "communication_attachment_event_schema.sql", "1"
TRIGGER = "acs_attachment_ready_event"


def _shape(connection, checksum):
    source = schema_definition(FILE, VERSION)[0].decode()
    body = source.split("AS $$", 1)[1].split("$$;", 1)[0].strip()
    row = connection.execute("SELECT t.tgtype,t.tgenabled,t.tgfoid=to_regprocedure('acs_attachment_ready_event()'),"
        "p.prosrc,p.prosecdef,p.provolatile,cardinality(t.tgattr::smallint[]) FROM pg_trigger t "
        "JOIN pg_proc p ON p.oid=t.tgfoid WHERE t.tgname=%s AND t.tgrelid=to_regclass('communication_attachments') "
        "AND NOT t.tgisinternal", (TRIGGER,)).fetchone()
    if (row is None or row[0] != 21 or row[1] not in {"O", "A"} or row[2] is not True
            or row[3].strip() != body or row[4:] != (False, "v", 0)):
        raise SchemaAdoptionError(NAME, checksum, "damaged attachment ready event source")


def adopt_attachment_event_storage(connection):
    from runtime.communication_attachment_storage import verify_attachment_storage
    from runtime.communication_event_storage import verify_event_storage

    verify_attachment_storage(connection)
    verify_event_storage(connection)
    source, checksum, equivalents = schema_definition(FILE, VERSION)
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('acs-attachment-events:'||current_schema(),0))")
    row = connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s FOR UPDATE", (NAME,)).fetchone()
    if row is None:
        if connection.execute("SELECT 1 FROM pg_trigger WHERE tgname=%s AND tgrelid=to_regclass('communication_attachments') AND NOT tgisinternal", (TRIGGER,)).fetchone():
            raise SchemaAdoptionError(NAME, checksum, "unversioned attachment ready event source")
        connection.execute(source)
        connection.execute("INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) VALUES (%s,%s,%s)", (NAME, VERSION, checksum))
    elif row not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "explicit attachment event migration required")
    _shape(connection, checksum)


def verify_attachment_event_storage(connection):
    _source, checksum, equivalents = schema_definition(FILE, VERSION)
    if connection.execute("SELECT schema_version,schema_checksum FROM runtime_schema_metadata WHERE schema_name=%s", (NAME,)).fetchone() not in equivalents:
        raise SchemaAdoptionError(NAME, checksum, "attachment event adoption required")
    _shape(connection, checksum)
