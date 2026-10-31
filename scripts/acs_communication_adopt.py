"""Preview or explicitly adopt current communication storage without deleting data.

The default transaction is read-only. --apply requires the reviewed plan hash.
Private connection data comes only from the named environment variable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.communication_storage import CORE_FILE, CORE_NAME, CORE_VERSION, schema_definition
from runtime.errors import SchemaAdoptionError
from runtime.project_schema_state import SCHEMA_VERSIONS, SCHEMAS, adopt_project_schema


def plan(connection):
    schema = connection.execute("SELECT current_schema()").fetchone()[0]
    metadata = []
    if connection.execute("SELECT to_regclass('runtime_schema_metadata')").fetchone()[0] is not None:
        metadata = connection.execute("SELECT schema_name,schema_version,schema_checksum FROM runtime_schema_metadata "
                                      "ORDER BY schema_name").fetchall()
    tables = [row[0] for row in connection.execute("SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename", (schema,))]
    targets = [(CORE_NAME, CORE_VERSION, schema_definition(CORE_FILE, CORE_VERSION)[1])]
    targets += [(name, SCHEMA_VERSIONS.get(filename, "1"), schema_definition(filename, SCHEMA_VERSIONS.get(filename, "1"))[1])
                for filename, name, _label in SCHEMAS]
    facts = {"schema": schema, "current_metadata": metadata, "present_tables": tables, "target_metadata": targets}
    encoded = json.dumps(facts, sort_keys=True, separators=(",", ":")).encode()
    return {**facts, "plan_sha256": hashlib.sha256(encoded).hexdigest()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn-env", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-plan-sha256")
    args = parser.parse_args(argv)
    if args.apply and (not args.expected_plan_sha256 or len(args.expected_plan_sha256) != 64
                      or any(char not in "0123456789abcdef" for char in args.expected_plan_sha256)):
        parser.error("--apply requires --expected-plan-sha256 from the read-only preview")
    try:
        with psycopg.connect(os.environ[args.dsn_env]) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL " + ("READ COMMITTED READ WRITE" if args.apply else "REPEATABLE READ READ ONLY"))
            if connection.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (args.schema,)).fetchone() is None:
                raise ValueError("schema does not exist")
            connection.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(args.schema)))
            if args.apply:
                connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('acs-core-schema:' || current_schema(),0))")
                connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('acs-project-schema:' || current_schema(),0))")
            result = plan(connection)
            if args.apply:
                if result["plan_sha256"] != args.expected_plan_sha256:
                    raise ValueError("schema state or candidate SQL changed after the preview")
                adopt_project_schema(connection)
            result.update(mode="applied" if args.apply else "dry_run", data_cleanup="none",
                          identity_bootstrap="unchanged", native_started=False)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (KeyError, ValueError, SchemaAdoptionError, psycopg.Error) as error:
        print(json.dumps({"ok": False, "code": "communication_adoption_unavailable", "error_type": type(error).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
