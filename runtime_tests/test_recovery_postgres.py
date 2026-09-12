from __future__ import annotations

# ruff: noqa: I001 -- standalone candidate and repository classify local imports differently.

import hashlib
import json
import os
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg import sql
from psycopg.conninfo import make_conninfo

from runtime.schema_upgrade import apply_candidate_schema
from runtime.recovery import (
    AuthoritySnapshot,
    BridgeAuthoritySnapshot,
    IncidentOpenCommand,
    PostgresDelayedResponseAuthority,
    PostgresHumanBridgeAuthority,
)
from runtime.recovery_models import (
    BoundaryRejected,
    DispatchIdentity,
    ManualPacket,
    NativeResponseObservation,
    NormalReceipt,
    RecoveryPath,
    StateConflict,
    canonical_digest,
    response_receipt_id,
)

DIGEST = "a" * 64
RECEIVER_18_BYTES_SHA256 = "b8554614d9923ae43a653371c4445c33fdfe189c219b3376f29e23c476ee7614"


@pytest.fixture
def postgres_dsn():
    base = os.environ.get("ACS_P1_DSN")
    if not base:
        pytest.skip("ACS_P1_DSN is not configured; PostgreSQL candidate is NOT_RUN")
    schema = "async_bridge_candidate_" + uuid.uuid4().hex
    with psycopg.connect(base, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(
        base, options=f"-csearch_path={schema} -cstatement_timeout=15000 -clock_timeout=10000",
    )
    try:
        with psycopg.connect(dsn) as connection:
            connection.execute(
                "CREATE TABLE delivery_messages("
                "tenant_id TEXT NOT NULL,message_id TEXT NOT NULL,operation_id TEXT NOT NULL,"
                "deadline TIMESTAMPTZ NOT NULL,accepted_state_digest TEXT NOT NULL,"
                "receipt_high_water TEXT NOT NULL DEFAULT 'runtime_dispatched',"
                "PRIMARY KEY(tenant_id,message_id))"
            )
            connection.execute(
                "CREATE TABLE delivery_attempts("
                "tenant_id TEXT NOT NULL,message_id TEXT NOT NULL,ordinal INTEGER NOT NULL,"
                "attempt_id TEXT NOT NULL,operation_id TEXT NOT NULL,dispatch_id TEXT,"
                "runtime_dispatched_receipt_id TEXT,"
                "PRIMARY KEY(tenant_id,message_id,ordinal),UNIQUE(attempt_id))"
            )
            connection.execute(
                "CREATE TABLE delivery_receipts("
                "tenant_id TEXT NOT NULL,message_id TEXT NOT NULL,receipt_id TEXT NOT NULL,"
                "layer TEXT NOT NULL,evidence_json JSONB NOT NULL,attempt_id TEXT,dispatch_id TEXT,"
                "PRIMARY KEY(tenant_id,message_id,layer),UNIQUE(tenant_id,receipt_id))"
            )
            connection.execute(
                "CREATE TABLE outbox("
                "outbox_id BIGSERIAL PRIMARY KEY,tenant_id TEXT NOT NULL,message_id TEXT NOT NULL,"
                "operation_id TEXT NOT NULL,topic TEXT NOT NULL,payload JSONB NOT NULL,"
                "delivered_at TIMESTAMPTZ,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
                "UNIQUE(tenant_id,message_id))"
            )
            connection.execute(
                "CREATE TABLE runtime_schema_metadata("
                "schema_name TEXT PRIMARY KEY,schema_version TEXT NOT NULL,"
                "schema_checksum TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO runtime_schema_metadata VALUES "
                "('acs-p1-runtime','1.8',%s)", (RECEIVER_18_BYTES_SHA256,),
            )
            apply_candidate_schema(connection, standalone_fixture=True)
        yield dsn
    finally:
        with psycopg.connect(base, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def exact_schema_dsn():
    base = os.environ.get("ACS_P1_DSN")
    if not base:
        pytest.skip("ACS_P1_DSN is not configured")
    receiver_path = Path(__file__).with_name("fixtures") / "schema-1.8-a942.sql"
    receiver_bytes = receiver_path.read_bytes()
    assert hashlib.sha256(receiver_bytes).hexdigest() == RECEIVER_18_BYTES_SHA256
    schema = "async_bridge_exact_" + uuid.uuid4().hex
    with psycopg.connect(base, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(
        base, options=f"-csearch_path={schema} -cstatement_timeout=15000 -clock_timeout=10000",
    )
    try:
        with psycopg.connect(dsn) as connection:
            connection.execute(receiver_bytes)
            connection.execute(
                "INSERT INTO runtime_schema_metadata(schema_name,schema_version,schema_checksum) "
                "VALUES ('acs-p1-runtime','1.8',%s)",
                (RECEIVER_18_BYTES_SHA256,),
            )
        yield dsn
    finally:
        with psycopg.connect(base, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def identity(**changes):
    value = DispatchIdentity(
        "tenant", "message", "operation", "invocation", "attempt", "dispatch",
        "endpoint", 1, "machine", "node", "boot", 7, DIGEST,
    )
    return replace(value, **changes)


def observation(**changes):
    dispatch = changes.get("identity", identity())
    projection_id = changes.get("projection_id", "projection")
    value = NativeResponseObservation(
        projection_id, response_receipt_id(dispatch, projection_id), dispatch,
        "native-response", "completed",
        "artifact:response", "c" * 64, "b" * 64, datetime.now(UTC),
    )
    return replace(value, **changes)


def projection_snapshot(_cursor, item):
    return AuthoritySnapshot(
        committed_identity=item.identity, producer_authenticated=True,
        current_authority_valid=True, task_valid=True,
        current_attempt_id=item.identity.attempt_id,
        current_accepted_revision=item.identity.accepted_revision,
        current_accepted_state_digest=item.identity.accepted_state_digest,
        deadline=datetime.now(UTC) + timedelta(minutes=5), principal_ref="node:1",
        grant_ref="grant:node", policy_version="policy-1",
    )


def bridge_snapshot(_cursor, _action, _incident_id):
    return BridgeAuthoritySnapshot(
        authenticated=True, current_authority_valid=True, task_valid=True,
        send_authorized=True, current_accepted_revision=7,
        current_accepted_state_digest=DIGEST,
        deadline=datetime.now(UTC) + timedelta(minutes=5), principal_ref="agent:manager",
        grant_ref="grant:bridge", policy_version="policy-1",
    )


def seed_message(dsn):
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "INSERT INTO delivery_messages("
            "tenant_id,message_id,operation_id,deadline,accepted_state_digest) "
            "VALUES ('tenant','message','operation',clock_timestamp()+interval '5 minutes',%s)",
            (DIGEST,),
        )
        connection.execute(
            "INSERT INTO delivery_attempts("
            "tenant_id,message_id,ordinal,attempt_id,operation_id,dispatch_id,"
            "runtime_dispatched_receipt_id) "
            "VALUES ('tenant','message',1,'attempt','operation','dispatch','dispatch-receipt')"
        )
        connection.execute(
            "INSERT INTO delivery_receipts(tenant_id,message_id,receipt_id,layer,evidence_json,"
            "attempt_id,dispatch_id) VALUES "
            "('tenant','message','dispatch-receipt','runtime_dispatched','{}','attempt','dispatch')"
        )


def fetchall(dsn, statement, params=()):
    with psycopg.connect(dsn) as connection:
        return connection.execute(statement, params).fetchall()


def open_command():
    return IncidentOpenCommand(
        "incident", 3, "tenant", "message", "operation", "source", "target", 7,
        DIGEST, datetime.now(UTC) + timedelta(minutes=5), ("native", "switch"),
        (RecoveryPath("native", "failed", ("attempt-a",), ("evidence-a",)),
         RecoveryPath("switch", "budget_exhausted", ("attempt-b",), ("evidence-b",))),
        "command-open",
    )


def test_postgres_schema_migrates_only_from_18_to_19(postgres_dsn):
    with psycopg.connect(postgres_dsn) as connection:
        apply_candidate_schema(connection, integrated_schema_checksum="9" * 64)
    assert fetchall(
        postgres_dsn,
        "SELECT schema_version,schema_checksum FROM runtime_schema_metadata",
    ) == [("1.9", "9" * 64)]


def test_exact_receiver_18_to_19_repeat_preserves_rows(exact_schema_dsn):
    with psycopg.connect(exact_schema_dsn) as connection:
        connection.execute(
            "INSERT INTO scopes(scope_id,tenant_id,policy,status) "
            "VALUES ('preserved','tenant','{}','active')"
        )
        before = connection.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema=current_schema()"
        ).fetchone()[0]
        apply_candidate_schema(connection, integrated_schema_checksum="9" * 64)
        after = connection.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema=current_schema()"
        ).fetchone()[0]
        assert after == before + 10
        apply_candidate_schema(connection, integrated_schema_checksum="9" * 64)
        repeated = connection.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema=current_schema()"
        ).fetchone()[0]
        assert repeated == after
        assert connection.execute(
            "SELECT status FROM scopes WHERE scope_id='preserved'"
        ).fetchone() == ("active",)
        assert connection.execute(
            "SELECT schema_version,schema_checksum FROM runtime_schema_metadata "
            "WHERE schema_name='acs-p1-runtime'"
        ).fetchone() == ("1.9", "9" * 64)


@pytest.mark.parametrize("version,checksum", [
    ("1.7", RECEIVER_18_BYTES_SHA256), ("1.8", "8" * 64),
])
def test_exact_receiver_predecessor_mismatch_refuses_without_candidate_tables(
    exact_schema_dsn, version, checksum,
):
    with psycopg.connect(exact_schema_dsn) as connection:
        connection.execute(
            "UPDATE runtime_schema_metadata SET schema_version=%s,schema_checksum=%s "
            "WHERE schema_name='acs-p1-runtime'", (version, checksum),
        )
        with pytest.raises(RuntimeError):
            apply_candidate_schema(connection, integrated_schema_checksum="9" * 64)
        assert connection.execute("SELECT to_regclass('native_response_observations')").fetchone() == (None,)
        assert connection.execute("SELECT to_regclass('delivery_receiver_receipts')").fetchone()[0] is not None


def manual(**changes):
    value = ManualPacket(
        "packet", "incident", 3, "tenant", "message", "operation", "attempt", "dispatch",
        "source", "target", "response", 7, DIGEST, "c" * 64,
        datetime.now(UTC) + timedelta(minutes=5),
    )
    return replace(value, **changes)


def test_postgres_delayed_projection_is_atomic_and_idempotent(postgres_dsn):
    seed_message(postgres_dsn)
    authority = PostgresDelayedResponseAuthority(postgres_dsn, projection_snapshot)
    item = observation()
    first = authority.project(item)
    second = authority.project(item)
    assert first.disposition == "applied"
    with pytest.raises(StateConflict):
        authority.project(observation(evidence_digest="d" * 64))
    assert fetchall(postgres_dsn, "SELECT count(*) FROM native_response_observations") == [(1,)]
    assert fetchall(postgres_dsn, "SELECT receipt_high_water FROM delivery_messages") == [
        ("response_received",),
    ]
    assert second.disposition == "applied"


def test_postgres_receipt_conflict_rolls_back_observation(postgres_dsn):
    seed_message(postgres_dsn)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "INSERT INTO delivery_receipts("
            "tenant_id,message_id,receipt_id,layer,evidence_json,attempt_id,dispatch_id) "
            "VALUES ('tenant','message','other','response_received','{}','attempt','dispatch')"
        )
    with pytest.raises(StateConflict):
        PostgresDelayedResponseAuthority(postgres_dsn, projection_snapshot).project(observation())
    assert fetchall(postgres_dsn, "SELECT count(*) FROM native_response_observations") == [(0,)]


def test_postgres_fenced_old_attempt_does_not_block_current_receipt(postgres_dsn):
    seed_message(postgres_dsn)
    current_attempt = {"id": "attempt-2"}

    def snapshot(_cursor, item):
        value = projection_snapshot(_cursor, item)
        return replace(value, current_attempt_id=current_attempt["id"])

    authority = PostgresDelayedResponseAuthority(postgres_dsn, snapshot)
    old = observation()
    assert authority.project(old).disposition == "fenced_late"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
                "INSERT INTO delivery_attempts("
                "tenant_id,message_id,ordinal,attempt_id,operation_id,dispatch_id,"
                "runtime_dispatched_receipt_id) VALUES "
                "('tenant','message',2,'attempt-2','operation','dispatch-2','dispatch-receipt-2')"
        )
        connection.execute(
                "INSERT INTO delivery_receipts(tenant_id,message_id,receipt_id,layer,evidence_json,"
                "attempt_id,dispatch_id) VALUES ('tenant','message','dispatch-receipt-2',"
                "'runtime_dispatched','{}','attempt-2','dispatch-2') "
                "ON CONFLICT(tenant_id,message_id,layer) DO UPDATE SET "
                "receipt_id=EXCLUDED.receipt_id,attempt_id=EXCLUDED.attempt_id,"
                "dispatch_id=EXCLUDED.dispatch_id"
        )
    current_identity = identity(
        invocation_id="invocation-2", attempt_id="attempt-2", dispatch_id="dispatch-2",
    )
    current = observation(
        projection_id="projection-2", identity=current_identity,
        native_response_ref="native-response-2",
    )
    assert old.receipt_id != current.receipt_id
    assert authority.project(current).disposition == "applied"
    assert fetchall(
        postgres_dsn,
        "SELECT disposition FROM native_response_observations ORDER BY projection_id",
    ) == [("fenced_late",), ("applied",)]
    assert fetchall(
        postgres_dsn, "SELECT receipt_id FROM delivery_receipts WHERE layer='response_received'",
    ) == [(current.receipt_id,)]


@pytest.mark.parametrize("change", ["revoked", "attempt", "revision", "digest", "deadline"])
def test_postgres_projection_final_locked_recheck_fences_expired_authority(
    postgres_dsn, change,
):
    seed_message(postgres_dsn)
    calls = {"count": 0}

    def changes_after_lock(cursor, item):
        calls["count"] += 1
        value = projection_snapshot(cursor, item)
        if calls["count"] == 2:
            updates = {
                "revoked": {"current_authority_valid": False},
                "attempt": {"current_attempt_id": "replacement"},
                "revision": {"current_accepted_revision": 8},
                "digest": {"current_accepted_state_digest": "e" * 64},
                "deadline": {"deadline": datetime.now(UTC) - timedelta(seconds=1)},
            }[change]
            return replace(value, **updates)
        return value

    result = PostgresDelayedResponseAuthority(postgres_dsn, changes_after_lock).project(observation())
    assert calls["count"] == 2
    assert result.disposition == "fenced_late"
    assert fetchall(
        postgres_dsn,
        "SELECT count(*) FROM delivery_receipts WHERE layer='response_received'",
    ) == [(0,)]
    assert fetchall(postgres_dsn, "SELECT receipt_high_water FROM delivery_messages") == [
        ("runtime_dispatched",),
    ]


def test_postgres_human_bridge_old_generation_fenced_and_current_resolved(postgres_dsn):
    seed_message(postgres_dsn)
    authority = PostgresHumanBridgeAuthority(postgres_dsn, bridge_snapshot)
    opened = open_command()
    assert authority.open_incident(opened) == "open"
    assert authority.open_incident(opened) == "open"
    assert authority.request_human(
        tenant_id="tenant", incident_id="incident", request_id="request", command_id="command-request",
    ) == "human_requested"
    assert authority.receive_manual(
        manual(packet_id="old", incident_generation=2), command_id="command-old",
    ) == "fenced_late"
    packet = manual()
    assert authority.receive_manual(packet, command_id="command-packet") == "committed"
    evidence = {"source": "unrelated-normal-delivery"}
    actual = {
        "receipt_id": "normal-response", "layer": "response_received",
        "message_id": "message", "evidence": evidence,
        "attempt_id": "attempt", "dispatch_id": "dispatch",
    }
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "INSERT INTO delivery_receipts("
            "tenant_id,message_id,receipt_id,layer,evidence_json,attempt_id,dispatch_id) "
            "VALUES ('tenant','message','normal-response','response_received',%s,'attempt','dispatch')",
            (json.dumps(evidence),),
        )
    receipt = NormalReceipt(
        "normal-response", "response_received", "tenant", "message", "operation",
        "incident", 3, "packet", "attempt", "dispatch", "response",
        packet.payload_digest, canonical_digest(actual),
    )
    with pytest.raises(BoundaryRejected):
        authority.confirm_manual(receipt, command_id="command-unrelated-confirm")
    assert fetchall(postgres_dsn, "SELECT state FROM recovery_incidents") == [
        ("manual_packet_committed",),
    ]
    bridge_evidence = {
        "incident_id": "incident", "incident_generation": 3, "packet_id": "packet",
        "message_id": "message", "operation_id": "operation", "attempt_id": "attempt",
        "dispatch_id": "dispatch", "direction": "response", "layer": "response_received",
        "payload_digest": packet.payload_digest,
    }
    evidence = {"human_bridge": bridge_evidence}
    actual["evidence"] = evidence
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE delivery_receipts SET evidence_json=%s WHERE receipt_id='normal-response'",
            (json.dumps(evidence),),
        )
    receipt = replace(receipt, evidence_digest=canonical_digest(actual))
    assert authority.confirm_manual(receipt, command_id="command-confirm") == "resolved_manual"
    assert fetchall(postgres_dsn, "SELECT state FROM recovery_incidents") == [
        ("resolved_manual",),
    ]


def test_postgres_successful_reprobe_fences_late_manual_packet(postgres_dsn):
    seed_message(postgres_dsn)
    authority = PostgresHumanBridgeAuthority(postgres_dsn, bridge_snapshot)
    authority.open_incident(open_command())
    authority.request_human(
        tenant_id="tenant", incident_id="incident", request_id="request", command_id="command-request",
    )
    assert authority.reprobe(
        tenant_id="tenant", incident_id="incident", reprobe_id="reprobe",
        observation_ref="automatic-path-restored", succeeded=True, command_id="command-reprobe",
    ) == "resolved_automatic"
    assert authority.receive_manual(manual(), command_id="command-late") == "fenced_late"
    assert fetchall(postgres_dsn, "SELECT count(*) FROM outbox") == [(1,)]


def test_postgres_terminal_incident_fences_new_reprobe_and_replay(postgres_dsn):
    seed_message(postgres_dsn)
    authority = PostgresHumanBridgeAuthority(postgres_dsn, bridge_snapshot)
    authority.open_incident(open_command())
    authority.request_human(
        tenant_id="tenant", incident_id="incident", request_id="request",
        command_id="command-request",
    )
    assert authority.reprobe(
        tenant_id="tenant", incident_id="incident", reprobe_id="winner",
        observation_ref="automatic-restored", succeeded=True, command_id="winner-command",
    ) == "resolved_automatic"
    late = {
        "tenant_id": "tenant", "incident_id": "incident", "reprobe_id": "late",
        "observation_ref": "later-observation", "succeeded": True,
        "command_id": "late-command",
    }
    assert authority.reprobe(**late) == "fenced_late"
    assert authority.reprobe(**late) == "fenced_late"
    assert fetchall(postgres_dsn, "SELECT state FROM recovery_incidents") == [
        ("resolved_automatic",),
    ]
    assert fetchall(
        postgres_dsn, "SELECT reprobe_id,disposition FROM recovery_reprobes ORDER BY reprobe_id",
    ) == [("late", "fenced_late"), ("winner", "observed")]


def test_postgres_manual_receive_final_deadline_is_fenced(postgres_dsn):
    seed_message(postgres_dsn)

    def snapshot(cursor, action, incident_id):
        value = bridge_snapshot(cursor, action, incident_id)
        if action == "manual.receive.final":
            return replace(value, deadline=datetime.now(UTC) - timedelta(seconds=1))
        return value

    authority = PostgresHumanBridgeAuthority(postgres_dsn, snapshot)
    authority.open_incident(open_command())
    authority.request_human(
        tenant_id="tenant", incident_id="incident", request_id="request",
        command_id="command-request",
    )
    assert authority.receive_manual(manual(), command_id="command-packet") == "fenced_late"
    assert fetchall(postgres_dsn, "SELECT state FROM recovery_incidents") == [
        ("human_requested",),
    ]
    assert fetchall(postgres_dsn, "SELECT count(*) FROM outbox") == [(1,)]


@pytest.mark.parametrize("change", [
    {"attempt_id": "missing"}, {"dispatch_id": "missing"},
])
def test_postgres_manual_receive_requires_real_delivery_attempt(postgres_dsn, change):
    seed_message(postgres_dsn)
    authority = PostgresHumanBridgeAuthority(postgres_dsn, bridge_snapshot)
    authority.open_incident(open_command())
    authority.request_human(
        tenant_id="tenant", incident_id="incident", request_id="request",
        command_id="command-request",
    )
    with pytest.raises(BoundaryRejected):
        authority.receive_manual(manual(**change), command_id="command-packet")
    assert fetchall(postgres_dsn, "SELECT count(*) FROM human_bridge_packets") == [(0,)]


def test_postgres_confirm_requires_original_delivery_attempt_to_still_exist(postgres_dsn):
    seed_message(postgres_dsn)
    authority = PostgresHumanBridgeAuthority(postgres_dsn, bridge_snapshot)
    authority.open_incident(open_command())
    authority.request_human(
        tenant_id="tenant", incident_id="incident", request_id="request",
        command_id="command-request",
    )
    packet = manual()
    assert authority.receive_manual(packet, command_id="command-packet") == "committed"
    bridge_evidence = {
        "incident_id": "incident", "incident_generation": 3, "packet_id": "packet",
        "message_id": "message", "operation_id": "operation", "attempt_id": "attempt",
        "dispatch_id": "dispatch", "direction": "response", "layer": "response_received",
        "payload_digest": packet.payload_digest,
    }
    evidence = {"human_bridge": bridge_evidence}
    actual = {
        "receipt_id": "normal-response", "layer": "response_received",
        "message_id": "message", "evidence": evidence,
        "attempt_id": "attempt", "dispatch_id": "dispatch",
    }
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "INSERT INTO delivery_receipts("
            "tenant_id,message_id,receipt_id,layer,evidence_json,attempt_id,dispatch_id) "
            "VALUES ('tenant','message','normal-response','response_received',%s,'attempt','dispatch')",
            (json.dumps(evidence),),
        )
        connection.execute("DELETE FROM delivery_attempts WHERE attempt_id='attempt'")
    receipt = NormalReceipt(
        "normal-response", "response_received", "tenant", "message", "operation",
        "incident", 3, "packet", "attempt", "dispatch", "response",
        packet.payload_digest, canonical_digest(actual),
    )
    with pytest.raises(BoundaryRejected):
        authority.confirm_manual(receipt, command_id="confirm")
    assert fetchall(postgres_dsn, "SELECT state FROM recovery_incidents") == [
        ("manual_packet_committed",),
    ]


@pytest.mark.parametrize("change", ["revoked", "task_invalid", "revision", "digest", "deadline"])
def test_postgres_request_final_locked_authority_change_rejects(postgres_dsn, change):
    seed_message(postgres_dsn)

    def snapshot(cursor, action, incident_id):
        value = bridge_snapshot(cursor, action, incident_id)
        if action == "human.request.final":
            updates = {
                "revoked": {"current_authority_valid": False},
                "task_invalid": {"task_valid": False},
                "revision": {"current_accepted_revision": 8},
                "digest": {"current_accepted_state_digest": "e" * 64},
                "deadline": {"deadline": datetime.now(UTC) - timedelta(seconds=1)},
            }[change]
            return replace(value, **updates)
        return value

    authority = PostgresHumanBridgeAuthority(postgres_dsn, snapshot)
    authority.open_incident(open_command())
    with pytest.raises(BoundaryRejected):
        authority.request_human(
            tenant_id="tenant", incident_id="incident", request_id="request",
            command_id="command-request",
        )
    assert fetchall(postgres_dsn, "SELECT state FROM recovery_incidents") == [("open",)]
    assert fetchall(postgres_dsn, "SELECT count(*) FROM human_bridge_requests") == [(0,)]
    assert fetchall(postgres_dsn, "SELECT count(*) FROM outbox") == [(0,)]


@pytest.mark.parametrize("change", ["revoked", "task_invalid", "revision", "digest", "deadline"])
def test_postgres_reprobe_final_locked_authority_change_is_fenced(postgres_dsn, change):
    seed_message(postgres_dsn)
    mutable = {"reprobe": False}

    def snapshot(cursor, action, incident_id):
        value = bridge_snapshot(cursor, action, incident_id)
        if mutable["reprobe"] and action == "automatic.reprobe.final":
            updates = {
                "revoked": {"current_authority_valid": False},
                "task_invalid": {"task_valid": False},
                "revision": {"current_accepted_revision": 8},
                "digest": {"current_accepted_state_digest": "e" * 64},
                "deadline": {"deadline": datetime.now(UTC) - timedelta(seconds=1)},
            }[change]
            return replace(value, **updates)
        return value

    authority = PostgresHumanBridgeAuthority(postgres_dsn, snapshot)
    authority.open_incident(open_command())
    authority.request_human(
        tenant_id="tenant", incident_id="incident", request_id="request",
        command_id="command-request",
    )
    mutable["reprobe"] = True
    assert authority.reprobe(
        tenant_id="tenant", incident_id="incident", reprobe_id="reprobe",
        observation_ref="observed-restored", succeeded=True, command_id="command-reprobe",
    ) == "fenced_late"
    assert fetchall(postgres_dsn, "SELECT state FROM recovery_incidents") == [
        ("human_requested",),
    ]
    assert fetchall(postgres_dsn, "SELECT disposition FROM recovery_reprobes") == [
        ("fenced_late",),
    ]


def test_postgres_unauthenticated_or_cross_incident_packet_is_rejected(postgres_dsn):
    seed_message(postgres_dsn)
    mutable = {"authenticated": True}

    def snapshot(cursor, action, incident_id):
        value = bridge_snapshot(cursor, action, incident_id)
        return replace(value, authenticated=mutable["authenticated"])

    authority = PostgresHumanBridgeAuthority(postgres_dsn, snapshot)
    authority.open_incident(open_command())
    authority.request_human(
        tenant_id="tenant", incident_id="incident", request_id="request", command_id="command-request",
    )
    mutable["authenticated"] = False
    with pytest.raises(BoundaryRejected):
        authority.receive_manual(manual(), command_id="unauthenticated")
    mutable["authenticated"] = True
    with pytest.raises(BoundaryRejected):
        authority.receive_manual(manual(incident_id="other"), command_id="cross-incident")
    assert fetchall(postgres_dsn, "SELECT count(*) FROM human_bridge_packets") == [(0,)]
