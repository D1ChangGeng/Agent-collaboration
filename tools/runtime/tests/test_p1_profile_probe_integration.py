from __future__ import annotations

import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from tools.runtime import p1_profile_probe as probe

pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("ACS_P1_PROFILE")
        or (
            os.environ.get("ACS_P1_DSN")
            and os.environ.get("ACS_P1_TEMPORAL_ENDPOINT")
        )
    ),
    reason="real loopback PostgreSQL and Temporal profile was not provided",
)


class InjectedCrash(RuntimeError):
    pass


def _profile(tmp_path: Path) -> Path:
    directory = tmp_path / "profile"
    directory.mkdir(mode=0o700)
    source = Path(__file__).resolve().parents[3]
    path = directory / "profile.json"
    supplied = {}
    if os.environ.get("ACS_P1_PROFILE"):
        supplied = json.loads(Path(os.environ["ACS_P1_PROFILE"]).read_text())
    value = {
        "schema_version": probe.SCHEMA,
        "profile": "p1-loopback-provider",
        "source_root": str(source),
        "python": sys.executable,
        "sandbox_python": "/run/acs-p1/runtime/bin/python",
        "postgres_dsn": supplied.get("postgres_dsn", os.environ.get("ACS_P1_DSN")),
        "temporal_endpoint": supplied.get(
            "temporal_endpoint", os.environ.get("ACS_P1_TEMPORAL_ENDPOINT"),
        ),
        "temporal_namespace": supplied.get(
            "temporal_namespace", os.environ.get("ACS_P1_TEMPORAL_NAMESPACE", "default"),
        ),
        "versions": {
            "core": "0.1.0/schema-1.9", "protocol": "2026-09-11.1",
            "provider": {"temporal": "actual"},
            "database": {"postgresql": "actual", "sqlite": sqlite3.sqlite_version},
            "harness": {"codex": "not-run", "opencode": "not-run"},
            "driver": {"fixture": "actual"}, "os": {"linux": "actual"},
        },
        "node_id": "p1-profile-test-node",
        "direction": "local-bidirectional",
        "codex_model_evidence": None,
        "opencode_model_evidence": None,
    }
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return path


@pytest.mark.parametrize("scenario,stage", [
    ("P1-DOMAIN-TRANSACTION", "after_schema_reserved"),
    ("P1-DOMAIN-TRANSACTION", "after_domain_dispatch"),
    ("P1-CORE-RESTART", "after_domain_dispatch"),
    ("P1-NODE-RESTART", "after_domain_dispatch"),
    ("P1-NODE-RESTART", "after_node_child_result"),
    ("P1-PROVIDER-RESTART", "after_provider_crash_record"),
    ("P1-PROVIDER-RESTART", "after_provider_child_result"),
])
def test_domain_crash_reuses_claim_and_cleans_schema(tmp_path, monkeypatch, scenario, stage):
    profile = _profile(tmp_path)
    output = tmp_path / "output"
    run_id = "crash-recovery-" + scenario + stage
    monkeypatch.setenv("ACS_GATE_RUN_ID", run_id)
    fired = False

    def crash(point: str) -> None:
        nonlocal fired
        if point == stage and not fired:
            fired = True
            raise InjectedCrash(point)

    try:
        with pytest.raises(InjectedCrash, match=stage):
            probe.execute(
                profile, scenario, "command_output", output,
                fault=crash,
            )
        results = [
            probe.execute(profile, scenario, kind, output)
            for kind in probe.KINDS
        ]
        assert {item["status"] for item in results} == {"passed"}
        ledger = probe.ProbeLedger(output)
        row = ledger.get(scenario)
        assert row is not None
        lineage = json.loads(row["lineage_json"])
        assert lineage["driver_calls"] == (
            [] if scenario in ("P1-NODE-RESTART", "P1-PROVIDER-RESTART")
            else [lineage["operation_id"]]
        )
        with sqlite3.connect(output / lineage["node_journal"]) as connection:
            assert connection.execute("SELECT count(*) FROM p1_driver_calls").fetchone() == (
                0 if scenario in ("P1-NODE-RESTART", "P1-PROVIDER-RESTART") else 1,
            )
    finally:
        if output.exists():
            probe.cleanup(profile, output)
    suffix = probe._sha(
        f"{run_id}:{scenario}".encode()
    )[:24]
    supplied = json.loads(profile.read_text())
    with psycopg.connect(supplied["postgres_dsn"]) as connection:
        assert connection.execute(
            "SELECT count(*) FROM pg_namespace WHERE nspname=%s", ("p1_probe_" + suffix,),
        ).fetchone() == (0,)


@pytest.mark.parametrize("scenario,expected_state,driver_count,attempt_count", [
    ("P1-AUTH-REVOCATION", "blocked", 0, 0),
    ("P1-COMMAND-DEDUP", "delivered", 1, 1),
    ("P1-INBOX-ACK-LOSS", "delivered", 1, 2),
    ("P1-CORE-RESTART", "delivered", 1, 1),
    ("P1-NODE-RESTART", "delivered", 0, 2),
    ("P1-PROVIDER-RESTART", "delivered", 0, 1),
])
def test_fixed_scenario_lineage_six_kinds_and_tamper_fence(
    tmp_path, monkeypatch, scenario, expected_state, driver_count, attempt_count,
):
    profile = _profile(tmp_path)
    output = tmp_path / "output"
    monkeypatch.setenv("ACS_GATE_RUN_ID", "p1-fixed-" + uuid.uuid4().hex)
    scoped = None
    schema = None
    try:
        results = [probe.execute(profile, scenario, kind, output) for kind in probe.KINDS]
        assert {item["status"] for item in results} == {"passed"}
        assert {item["message_ids"][0] for item in results} == {
            results[0]["message_ids"][0]
        }
        assert {item["operation_ids"][0] for item in results} == {
            results[0]["operation_ids"][0]
        }
        ledger = probe.ProbeLedger(output)
        row = ledger.get(scenario)
        assert row is not None
        lineage = json.loads(row["lineage_json"])
        assert lineage["message_state"] == expected_state
        assert len(lineage["driver_calls"]) == driver_count
        assert len(lineage["attempts"]) == attempt_count
        assert lineage["exact_replay"] and lineage["conflict_rejected"]
        assert lineage["ack_loss_observed"] == (scenario == "P1-INBOX-ACK-LOSS")
        if scenario == "P1-CORE-RESTART":
            assert lineage["core_crash_proof"]["exit_code"] == 83
            assert (lineage["core_crash_proof"]["prepared_attempt_id"]
                    == lineage["attempts"][0]["attempt_id"])
            context = output / "P1-CORE-RESTART-context.json"
            original = context.read_bytes()
            context.write_bytes(original + b" ")
            with pytest.raises(probe.ProbeRejected, match="Core crash process"):
                probe.execute(profile, scenario, "os", output)
            context.write_bytes(original)
        if scenario == "P1-NODE-RESTART":
            proof = lineage["node_restart_proof"]
            assert proof["old_boot"] != proof["new_boot"]
            assert [item["selection_revision"] for item in lineage["attempts"]] == [1, 2]
            context = output / "P1-NODE-RESTART-context.json"
            original = context.read_bytes()
            context.write_bytes(original + b" ")
            with pytest.raises(probe.ProbeRejected, match="Node replacement process"):
                probe.execute(profile, scenario, "os", output)
            context.write_bytes(original)
        if scenario == "P1-PROVIDER-RESTART":
            proof = lineage["provider_restart_proof"]
            assert proof["crash_exit"] == 84 and proof["recovery_exit"] == 0
            assert proof["workflow_id"] == row["temporal_workflow_id"]
            context = output / "P1-PROVIDER-RESTART-context.json"
            original = context.read_bytes()
            context.write_bytes(original + b" ")
            with pytest.raises(probe.ProbeRejected, match="Temporal Worker processes"):
                probe.execute(profile, scenario, "os", output)
            context.write_bytes(original)
        assert (output.stat().st_mode & 0o777) == 0o700
        for private_file in output.iterdir():
            if private_file.is_file():
                assert (private_file.stat().st_mode & 0o777) == 0o600
        secret = psycopg.conninfo.conninfo_to_dict(
            json.loads(profile.read_text())["postgres_dsn"]
        )["password"].encode()
        assert not any(
            secret in path.read_bytes() for path in output.iterdir() if path.is_file()
        )
        schema = row["pg_schema"]
        scoped = make_conninfo(
            json.loads(profile.read_text())["postgres_dsn"],
            options=f"-c search_path={schema}",
        )
        with psycopg.connect(scoped) as connection:
            if scenario == "P1-AUTH-REVOCATION":
                connection.execute(
                    "UPDATE grants SET revoked_at=NULL WHERE grant_ref=%s",
                    (lineage["grant_ref"],),
                )
            elif scenario == "P1-COMMAND-DEDUP":
                connection.execute(
                    "UPDATE command_dedup SET canonical_hash=%s WHERE command_id=%s",
                    ("0" * 64, lineage["command_id"]),
                )
            elif scenario in ("P1-INBOX-ACK-LOSS", "P1-NODE-RESTART"):
                connection.execute(
                    "UPDATE delivery_attempts SET status='blocked' "
                    "WHERE message_id=%s AND ordinal=1",
                    (lineage["message_id"],),
                )
            elif scenario == "P1-PROVIDER-RESTART":
                connection.execute(
                    "UPDATE operations SET provider_run_id=%s WHERE operation_id=%s",
                    ("changed-run", lineage["operation_id"]),
                )
            else:
                connection.execute(
                    "UPDATE delivery_attempts SET status='interrupted' "
                    "WHERE message_id=%s AND ordinal=1",
                    (lineage["message_id"],),
                )
        with pytest.raises(probe.ProbeRejected, match="PostgreSQL Runtime lineage changed"):
            probe.execute(profile, scenario, "postgresql", output)
    finally:
        if output.exists():
            probe.cleanup(profile, output)
    if schema is not None:
        with psycopg.connect(json.loads(profile.read_text())["postgres_dsn"]) as connection:
            assert connection.execute(
                "SELECT count(*) FROM pg_namespace WHERE nspname=%s", (schema,),
            ).fetchone() == (0,)
