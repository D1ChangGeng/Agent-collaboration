"""Exact a942 receiver-owned Runtime 1.8 to recovery-owned 1.9 migration."""
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

BASELINE_SHA256 = "b8554614d9923ae43a653371c4445c33fdfe189c219b3376f29e23c476ee7614"


def test_exact_1_8_to_1_9_repeat_safe_and_preserves_rows():
    dsn = os.getenv("ACS_P1_DSN")
    if not dsn:
        pytest.skip("ACS_P1_DSN required")
    baseline = Path(__file__).with_name("fixtures") / "schema-1.8-a942.sql"
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
                "VALUES ('acs-p1-runtime','1.8',%s)",
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
            ).fetchone() == ("1.9",)
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
            assert {
                "native_response_observations", "recovery_incidents",
                "human_bridge_requests", "human_bridge_packets",
                "human_bridge_normal_receipts", "recovery_audit_events",
            } <= tables
    finally:
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
