"""Operator dry run and additive historical message index adoption.

Credentials are read from a named environment variable, never command arguments.
This tool never deletes records, converts messages, or starts a Native receiver.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.communication_archive import adopt_legacy_index, archive_plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn-env", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--project-id")
    parser.add_argument("--apply", action="store_true", help="Adopt known associations into an explicitly installed archive schema")
    parser.add_argument("--expected-plan-sha256")
    args = parser.parse_args(argv)
    try:
        with psycopg.connect(os.environ[args.dsn_env]) as connection, connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ " + ("READ WRITE" if args.apply else "READ ONLY"))
            cursor.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (args.schema,))
            if cursor.fetchone() is None:
                raise ValueError("schema does not exist")
            cursor.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(args.schema)))
            result = (adopt_legacy_index(cursor, args.tenant_id, args.project_id,
                expected_plan_sha256=args.expected_plan_sha256) if args.apply else archive_plan(cursor, args.tenant_id, args.project_id))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (KeyError, ValueError, psycopg.Error) as error:
        # No DSN, credential, SQL text or private packet body in error output.
        print(json.dumps({"ok": False, "code": "archive_inventory_unavailable", "error_type": type(error).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
