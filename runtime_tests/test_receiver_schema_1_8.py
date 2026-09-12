"""Exact a97d Runtime 1.7 to receiver-owned 1.8 migration."""
from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from runtime.domain import DomainAuthority

BASELINE_SHA256 = "a3eb11f7afdccfedab5e7f7c41c861f3b9d8f4853460cdd948b8fc77e23d8132"


def test_exact_1_7_to_1_8_repeat_safe_and_preserves_rows():
    dsn = os.getenv("ACS_P1_DSN")
    if not dsn:
        pytest.skip("ACS_P1_DSN required")
    baseline = Path(__file__).with_name("fixtures") / "schema-1.7-a97d.sql"
    assert hashlib.sha256(baseline.read_bytes()).hexdigest() == BASELINE_SHA256
    schema = "receiver_integration_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(dsn, options=f"-c search_path={schema}")
    try:
        with psycopg.connect(isolated) as connection:
            connection.execute(baseline.read_bytes())
            connection.execute(
                "INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) "
                "VALUES ('acs-p1-runtime','1.7',%s)",
                (BASELINE_SHA256,),
            )
            connection.execute(
                "INSERT INTO scopes(scope_id,tenant_id,policy,status) "
                "VALUES ('migration-sentinel','local-tenant','{}','active')"
            )
        authority = DomainAuthority(isolated)
        authority.initialize()
        authority.initialize()
        with psycopg.connect(isolated) as connection:
            assert connection.execute(
                "SELECT schema_version FROM runtime_schema_metadata WHERE schema_name='acs-p1-runtime'"
            ).fetchone() == ("1.8",)
            assert connection.execute(
                "SELECT status FROM scopes WHERE scope_id='migration-sentinel'"
            ).fetchone() == ("active",)
            tables = {row[0] for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()"
            )}
            assert {
                "authority_transport_keys", "deployment_connection_refs",
                "delivery_endpoint_registrations", "delivery_transport_admissions",
                "delivery_receiver_receipts",
            } <= tables
            assert not any("human_bridge" in name or "async_response" in name for name in tables)
    finally:
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
