from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.runtime import p2_codex_resource_scenarios as probe


def test_query_authority_requires_real_attempt_lease_and_delivery(monkeypatch):
    proof = {
        "work_item_id": "work", "message_id": "message", "dispatch_id": "dispatch",
        "resource_id": "resource", "attempt_id": "attempt", "runtime_id": "runtime",
        "source_commit": "a" * 40, "source_tree": "b" * 40,
        "replacement_attempt_id": "next-attempt", "replacement_runtime_id": "next-runtime",
        "generation": 1, "replacement_generation": 2,
    }

    class Result:
        def __init__(self, rows): self.rows = rows
        def fetchall(self): return self.rows
        def fetchone(self): return self.rows[0]

    class Connection:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def execute(self, statement, _params):
            text = str(statement)
            if "FROM attempts" in text:
                return Result([
                    ("attempt", "work", "runtime", "a" * 40, "b" * 40, "candidate"),
                    ("next-attempt", "work", "next-runtime", "a" * 40, "b" * 40, "candidate-next"),
                ])
            if "FROM delivery_attempts" in text:
                return Result([("attempt", "dispatch", "delivered")])
            if "FROM leases" in text:
                return Result([
                    ("lease-1", "resource", "attempt", "runtime", 1, "released", "grant", "inc"),
                    ("lease-2", "resource", "next-attempt", "next-runtime", 2, "released", "grant-2", "inc"),
                ])
            if "FROM effects" in text:
                return Result([])
            return Result([(3,)])

    monkeypatch.setattr(probe.psycopg, "connect", lambda *_a, **_k: Connection())
    value = probe._query_authority(
        {"postgres_dsn": "postgresql://fixture"}, "p2_codex_schema", proof,
        "P2-CODEX-STALE-OWNER",
    )
    assert len(value["attempts"]) == 2
    assert [row[4] for row in value["leases"]] == [1, 2]


def test_audit_rejects_source_identity_change(tmp_path, monkeypatch):
    output = tmp_path / "run"
    output.mkdir()
    evidence = {
        "schema_version": probe.RESULT_SCHEMA, "status": "passed",
        "scenario_id": "P2-CODEX-STALE-OWNER", "source_commit": "a" * 40,
        "source_tree": "b" * 40,
    }
    (output / "P2-CODEX-STALE-OWNER-evidence.json").write_text(json.dumps(evidence))
    monkeypatch.setattr(probe.engine, "_secure_profile", lambda _path: (
        {"source_root": str(tmp_path), "postgres_dsn": "postgresql://fixture"}, "digest", (),
    ))
    monkeypatch.setattr(probe, "_git", lambda _root, ref: "c" * 40 if ref == "HEAD" else "b" * 40)
    with pytest.raises(probe.ScenarioRejected, match="source or scenario identity"):
        probe.audit(Path("profile.json"), output)
