"""Explicit old project storage, only for historical data/transition fixtures."""
from __future__ import annotations

import hashlib
from pathlib import Path


def initialize_legacy_project_schema(authority):
    with authority._connect() as connection:
        assert connection.execute("SELECT to_regclass('work_items')").fetchone()[0] is not None
        for filename, name in (("legacy_project_schema.sql", "acs-project-runtime"),
                               ("legacy_project_control_schema.sql", "acs-project-control")):
            schema = Path(__file__).with_name(filename).read_bytes().replace(b"\r\n", b"\n")
            connection.execute(schema)
            connection.execute("INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) "
                "VALUES (%s,'1',%s) ON CONFLICT DO NOTHING", (name, hashlib.sha256(schema).hexdigest()))
