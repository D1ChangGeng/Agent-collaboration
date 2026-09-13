"""Actual no-model native inventory component; formal scene remains NOT_RUN."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from tools.runtime import p1_profile_probe as probe
from tools.runtime.tests.test_p1_profile_probe_integration import _profile

NATIVE_PATH_ENV = (
    "ACS_P1_CODEX_NATIVE_PATH",
    "ACS_P1_CODEX_CATALOG_PATH",
    "ACS_P1_OPENCODE_NATIVE_PATH",
)
pytestmark = pytest.mark.skipif(
    not (os.environ.get("ACS_P1_PROFILE") or (
        os.environ.get("ACS_P1_DSN") and os.environ.get("ACS_P1_TEMPORAL_ENDPOINT")
    )) or any(not os.environ.get(name) for name in NATIVE_PATH_ENV),
    reason="real PG/Temporal and reviewed no-model native paths were not supplied",
)


def test_actual_no_model_native_inventory_and_current_host_fences(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    scenario = "P1-NATIVE-MULTIAGENT-OFF"
    profile_path = _profile(tmp_path)
    with pytest.raises(probe.ProbeUnavailable, match="actual native delegation request"):
        probe.execute(profile_path, scenario, "command_output", tmp_path / "formal-gap")
    assert not (tmp_path / "formal-gap").exists()

    output = tmp_path / "component"
    monkeypatch.setenv("ACS_GATE_RUN_ID", "native-inventory-" + uuid.uuid4().hex)
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
        layers = [probe._read_layer(profile, scenario, kind, ledger, row)
                  for kind in probe.KINDS]
        assert len(layers) == 6 and all(layers)
        lineage = json.loads(row["lineage_json"])
        proof = lineage["native_multiagent_proof"]
        assert proof["message_id"] == lineage["message_id"]
        assert proof["attempt_id"] == lineage["attempt_id"]
        assert proof["source_commit"] == commit and proof["source_tree"] == tree
        assert proof["summaries"]["codex"]["multi_agent"] is False
        assert proof["summaries"]["codex"]["multi_agent_v2"] is False
        assert proof["summaries"]["codex"]["model_turn_count"] == 0
        assert proof["summaries"]["opencode"]["model_prompt_count"] == 0
        assert proof["summaries"]["opencode"]["effective_tool_count"] > 0
        assert all(proof["host_denials"][name]["slot_and_policy_rejected"]
                   for name in ("codex", "opencode"))
        assert all(proof["terminations"][name]["remaining_pids"] == []
                   for name in ("codex", "opencode"))
        assert layers[1]["current_policy_slot_readback"]
        assert layers[2]["node_inventory_count"] == 2
        assert layers[4]["native_config_and_inventory_rechecked"]
        assert layers[5]["native_processes_stopped"]

        scoped = make_conninfo(profile["postgres_dsn"],
                               options=f"-c search_path={row['pg_schema']}")
        with psycopg.connect(scoped) as connection:
            original_policy = connection.execute(
                "SELECT policy FROM scopes WHERE scope_id='local-scope'",
            ).fetchone()[0]
            connection.execute(
                "UPDATE scopes SET policy=%s WHERE scope_id='local-scope'",
                (json.dumps({"changed": True}),),
            )
        with pytest.raises(probe.ProbeRejected, match="PostgreSQL native delegation"):
            probe._read_layer(profile, scenario, "postgresql", ledger, row)
        with psycopg.connect(scoped) as connection:
            connection.execute(
                "UPDATE scopes SET policy=%s WHERE scope_id='local-scope'",
                (json.dumps(original_policy),),
            )

        node_path = output / lineage["node_journal"]
        with sqlite3.connect(node_path) as connection:
            connection.execute(
                "UPDATE p1_native_inventory SET summary_sha256=? WHERE kind='codex'",
                ("0" * 64,),
            )
        with pytest.raises(probe.ProbeRejected, match="Node native inventory"):
            probe._read_layer(profile, scenario, "sqlite", ledger, row)
        with sqlite3.connect(node_path) as connection:
            connection.execute(
                "UPDATE p1_native_inventory SET summary_sha256=? WHERE kind='codex'",
                (probe._sha(probe._canonical(proof["summaries"]["codex"])),),
            )

        witness = output / f"{scenario}-native/codex/inventory.json"
        original = witness.read_bytes()
        witness.write_bytes(original + b" ")
        with pytest.raises(probe.ProbeRejected, match="inventory witness"):
            probe._read_layer(profile, scenario, "driver", ledger, row)
        witness.write_bytes(original)
    finally:
        if output.exists():
            probe.cleanup(profile_path, output)
    assert row is not None
    with psycopg.connect(profile["postgres_dsn"]) as connection:
        assert connection.execute(
            "SELECT count(*) FROM pg_namespace WHERE nspname=%s",
            (row["pg_schema"],),
        ).fetchone() == (0,)
