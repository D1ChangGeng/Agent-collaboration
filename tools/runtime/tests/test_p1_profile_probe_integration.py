from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

import psycopg
import pytest

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


@pytest.mark.parametrize("stage", ["after_schema_reserved", "after_domain_dispatch"])
def test_domain_crash_reuses_claim_and_cleans_schema(tmp_path, monkeypatch, stage):
    profile = _profile(tmp_path)
    output = tmp_path / "output"
    monkeypatch.setenv("ACS_GATE_RUN_ID", "crash-recovery-" + stage)
    fired = False

    def crash(point: str) -> None:
        nonlocal fired
        if point == stage and not fired:
            fired = True
            raise InjectedCrash(point)

    try:
        with pytest.raises(InjectedCrash, match=stage):
            probe.execute(
                profile, "P1-DOMAIN-TRANSACTION", "command_output", output,
                fault=crash,
            )
        results = [
            probe.execute(profile, "P1-DOMAIN-TRANSACTION", kind, output)
            for kind in probe.KINDS
        ]
        assert {item["status"] for item in results} == {"passed"}
        ledger = probe.ProbeLedger(output)
        row = ledger.get("P1-DOMAIN-TRANSACTION")
        assert row is not None
        lineage = json.loads(row["lineage_json"])
        assert lineage["driver_calls"] == [lineage["operation_id"]]
        with sqlite3.connect(output / lineage["node_journal"]) as connection:
            assert connection.execute("SELECT count(*) FROM p1_driver_calls").fetchone() == (1,)
    finally:
        if output.exists():
            probe.cleanup(profile, output)
    suffix = probe._sha(
        f"crash-recovery-{stage}:P1-DOMAIN-TRANSACTION".encode()
    )[:24]
    supplied = json.loads(profile.read_text())
    with psycopg.connect(supplied["postgres_dsn"]) as connection:
        assert connection.execute(
            "SELECT count(*) FROM pg_namespace WHERE nspname=%s", ("p1_probe_" + suffix,),
        ).fetchone() == (0,)
