"""Bounded no-model Harness adapter test; the formal scenario stays NOT_RUN."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from tools.runtime import p1_profile_probe as probe
from tools.runtime.tests.test_p1_profile_probe_integration import _profile

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ACS_P1_PROFILE") or (
        os.environ.get("ACS_P1_DSN") and os.environ.get("ACS_P1_TEMPORAL_ENDPOINT")
    )),
    reason="real loopback PostgreSQL and Temporal profile was not provided",
)


def test_same_attempt_replacement_fences_old_result_and_projects_one_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    scenario = "P1-HARNESS-REPLACEMENT"
    profile_path = _profile(tmp_path)
    disabled = tmp_path / "formal-unavailable"
    with pytest.raises(probe.ProbeUnavailable, match="actual native Harness replacement"):
        probe.execute(profile_path, scenario, "command_output", disabled)
    assert not disabled.exists()

    output = tmp_path / "candidate-output"
    monkeypatch.setenv("ACS_GATE_RUN_ID", "harness-fixture-" + uuid.uuid4().hex)
    profile, profile_digest, _secrets = probe._secure_profile(profile_path)
    source = Path(profile["source_root"])
    commit, tree = probe._source_identity(source)
    profile["profile_digest"] = profile_digest
    profile["machine_id"] = "machine-" + uuid.uuid4().hex[:20]
    profile["binding_sha256"] = probe._sha(probe._canonical({
        "profile": profile["profile"], "machine_id": profile["machine_id"],
        "node_id": profile["node_id"], "versions": profile["versions"],
    }))
    ledger = probe.ProbeLedger(output)
    row = None
    try:
        row = probe._run_tests(profile, scenario, ledger, commit, tree)
        assert row["status"] == "passed"
        results = [
            probe._runner_result(
                profile, scenario, kind, row,
                probe._read_layer(profile, scenario, kind, ledger, row),
            ) for kind in probe.KINDS
        ]
        assert len(results) == 6 and {item["status"] for item in results} == {"passed"}
        assert {item["message_ids"][0] for item in results} == {row["message_id"]}
        assert {item["operation_ids"][0] for item in results} == {row["operation_id"]}
        lineage = json.loads(row["lineage_json"])
        proof = lineage["harness_replacement_proof"]
        assert proof["attempt_id"] == lineage["attempt_id"]
        assert proof["dispatch_id"] == lineage["dispatch_id"]
        assert proof["old_result_disposition"] == "fenced_late"
        assert proof["new_result_disposition"] == "current"
        assert results[1]["facts"]["layer"]["response_received_count"] == 1
        assert results[2]["facts"]["layer"]["node_terminal_count"] == 1
        assert results[4]["facts"]["layer"]["model_calls"] == 0

        scoped = make_conninfo(profile["postgres_dsn"],
                               options=f"-c search_path={row['pg_schema']}")
        with psycopg.connect(scoped) as connection:
            connection.execute(
                "UPDATE harness_session_bindings SET attached_event_id=attached_event_id+1 "
                "WHERE binding_id=%s",
                (proof["old_binding_id"],),
            )
        with pytest.raises(probe.ProbeRejected, match="PostgreSQL Harness replacement"):
            probe._read_layer(profile, scenario, "postgresql", ledger, row)
        with psycopg.connect(scoped) as connection:
            connection.execute(
                "UPDATE harness_session_bindings SET attached_event_id=attached_event_id-1 "
                "WHERE binding_id=%s",
                (proof["old_binding_id"],),
            )

        node_path = output / lineage["node_journal"]
        import sqlite3

        with sqlite3.connect(node_path) as connection:
            connection.execute(
                "UPDATE native_response_observations SET state='fenced_late' "
                "WHERE projection_id=?", (proof["projection_id"],),
            )
        with pytest.raises(probe.ProbeRejected, match="Node response Outbox"):
            probe._read_layer(profile, scenario, "sqlite", ledger, row)
        with sqlite3.connect(node_path) as connection:
            connection.execute(
                "UPDATE native_response_observations SET state='applied' "
                "WHERE projection_id=?", (proof["projection_id"],),
            )

        proof_path = output / f"{scenario}-proof.json"
        original = proof_path.read_bytes()
        proof_path.write_bytes(original + b" ")
        with pytest.raises(probe.ProbeRejected, match="Harness replacement proof"):
            probe._read_layer(profile, scenario, "driver", ledger, row)
        proof_path.write_bytes(original)
    finally:
        if output.exists():
            probe.cleanup(profile_path, output)
    assert row is not None
    with psycopg.connect(profile["postgres_dsn"]) as connection:
        assert connection.execute(
            "SELECT count(*) FROM pg_namespace WHERE nspname=%s",
            (row["pg_schema"],),
        ).fetchone() == (0,)
