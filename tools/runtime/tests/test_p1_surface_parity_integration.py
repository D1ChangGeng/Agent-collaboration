"""Real PG + MCP/CLI/HTTP component proof for one Domain command identity."""
from __future__ import annotations

import os
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from runtime.domain import DomainAuthority
from tools.runtime.p1_surface_parity import exercise


def test_three_actual_surfaces_share_one_domain_operation():
    base = os.environ.get("ACS_P1_DSN")
    if not base or os.name != "posix":
        pytest.skip("real POSIX PostgreSQL surface profile is required")
    schema = "p1_surface_" + uuid.uuid4().hex
    source = Path(__file__).resolve().parents[3]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        authority = DomainAuthority(make_conninfo(base, options=f"-c search_path={schema}"))
        authority.initialize()
        authority.bootstrap_local_grant(("work_item.create", "work_item.read"))
        suffix = uuid.uuid4().hex
        proof = exercise(
            authority, source_root=source, work_item_id="surface-work-" + suffix,
            source_baseline=commit, command_id="surface-create-" + suffix,
            idempotency_key="surface-key-" + suffix, issued_at=datetime.now(UTC),
        )
        assert proof["source_baseline"] == commit
        assert proof["domain_row_count"] == 1
        assert proof["mcp_created"] and proof["cli_exact_replay"]
        assert proof["http_exact_replay"] and proof["http_conflict_rejected"]
        assert proof["active_http_processes"] == 0
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
