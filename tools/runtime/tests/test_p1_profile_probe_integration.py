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


@pytest.mark.parametrize("mutated_layer", ["file", "marker", "postgresql"])
def test_replacement_readback_precedes_old_owner_and_late_mutation_is_fenced(
    tmp_path, monkeypatch, mutated_layer,
):
    profile = _profile(tmp_path)
    output = tmp_path / "output"
    run_id = "late-fence-negative-" + uuid.uuid4().hex
    monkeypatch.setenv("ACS_GATE_RUN_ID", run_id)
    original_write = probe.LocalFileEffectGateway.write

    def compromised_late_write(self, *args, **kwargs):
        if str(kwargs.get("operation_id", "")).startswith("late-old-owner:"):
            effect_root = output / "P1-LEASE-FENCING-effects"
            if mutated_layer == "file":
                (effect_root / "output.txt").write_bytes(b"forged late bytes")
            elif mutated_layer == "marker":
                marker = next((effect_root / ".acs-effect-markers" / "current").glob("*.json"))
                marker.write_bytes(marker.read_bytes() + b" ")
            else:
                suffix = probe._sha(f"{run_id}:P1-LEASE-FENCING".encode())[:24]
                scoped = make_conninfo(
                    json.loads(profile.read_text())["postgres_dsn"],
                    options=f"-c search_path=p1_probe_{suffix}",
                )
                with psycopg.connect(scoped) as connection:
                    connection.execute(
                        "UPDATE leases SET owner_runtime_id=%s "
                        "WHERE resource_id=%s AND generation=2",
                        ("forged-replacement-runtime", kwargs["resource_id"]),
                    )
            raise probe.FencingRejected(kwargs["resource_id"])
        return original_write(self, *args, **kwargs)

    monkeypatch.setattr(probe.LocalFileEffectGateway, "write", compromised_late_write)
    try:
        with pytest.raises(
            probe.ProbeRejected, match="old owner changed replacement file, marker or PG Lease",
        ):
            probe.execute(profile, "P1-LEASE-FENCING", "command_output", output)
    finally:
        if output.exists():
            probe.cleanup(profile, output)


@pytest.mark.parametrize("scenario,stage", [
    ("P1-DOMAIN-TRANSACTION", "after_schema_reserved"),
    ("P1-DOMAIN-TRANSACTION", "after_domain_dispatch"),
    ("P1-CORE-RESTART", "after_domain_dispatch"),
    ("P1-NODE-RESTART", "after_domain_dispatch"),
    ("P1-NODE-RESTART", "after_node_child_result"),
    ("P1-PROVIDER-RESTART", "after_provider_crash_record"),
    ("P1-PROVIDER-RESTART", "after_provider_child_result"),
    ("P1-LEASE-FENCING", "after_domain_dispatch"),
    ("P1-UNCERTAIN-EFFECT", "after_domain_dispatch"),
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
    ("P1-DOMAIN-TRANSACTION", "delivered", 1, 1),
    ("P1-AUTH-REVOCATION", "blocked", 0, 0),
    ("P1-COMMAND-DEDUP", "delivered", 1, 1),
    ("P1-INBOX-ACK-LOSS", "delivered", 1, 2),
    ("P1-CORE-RESTART", "delivered", 1, 1),
    ("P1-NODE-RESTART", "delivered", 0, 2),
    ("P1-PROVIDER-RESTART", "delivered", 0, 1),
    ("P1-LEASE-FENCING", "delivered", 1, 1),
    ("P1-UNCERTAIN-EFFECT", "delivered", 1, 1),
])
def test_fixed_scenario_lineage_six_kinds_and_tamper_fence(
    tmp_path, monkeypatch, scenario, expected_state, driver_count, attempt_count,
):
    profile = _profile(tmp_path)
    output = tmp_path / "output"
    monkeypatch.setenv("ACS_GATE_RUN_ID", "p1-fixed-" + uuid.uuid4().hex)
    gate_machine = "machine-" + uuid.uuid4().hex[:20]
    monkeypatch.setenv("ACS_GATE_MACHINE_ID", gate_machine)
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
        assert {item["machine_id"] for item in results} == {lineage["machine_id"]}
        assert lineage["machine_id"] == gate_machine
        assert lineage["node_id"] == results[0]["node_id"]
        assert all(item["selection_machine"] == gate_machine for item in lineage["attempts"])
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
        if scenario == "P1-LEASE-FENCING":
            proof = lineage["lease_proof"]
            assert proof["delivery_operation_id"] == lineage["operation_id"]
            assert proof["machine_id"] == lineage["machine_id"]
            assert proof["stale_fence_rejected"]
            assert proof["late_old_owner_rejected"]
            assert proof["replacement_readback_before_late"]
            assert proof["pre_late_snapshot"] == proof["post_late_snapshot"]
            assert proof["pre_late_snapshot"]["file_sha256"] == proof["effect_sha256"]
            assert proof["pre_late_snapshot"]["file_identity"] == proof["effect_file_identity"]
            assert proof["replacement_generation"] == proof["generation"] + 1
            assert proof["replacement_attempt_id"] != proof["attempt_id"]
            assert proof["replacement_producer_grant_ref"] != proof["producer_grant_ref"]
            assert len(results[0]["operation_ids"]) == 6
            effect_file = output / "P1-LEASE-FENCING-effects" / "output.txt"
            original = effect_file.read_bytes()
            effect_file.write_bytes(b"tampered file effect")
            with pytest.raises(probe.ProbeRejected, match="Lease file effect identity/content"):
                probe.execute(profile, scenario, "driver", output)
            effect_file.write_bytes(original)
            marker = next(
                (output / "P1-LEASE-FENCING-effects" / ".acs-effect-markers"
                 / "current").glob("*.json")
            )
            marker_original = marker.read_bytes()
            marker.write_bytes(marker_original + b" ")
            with pytest.raises(probe.ProbeRejected, match="Lease file effect marker history"):
                probe.execute(profile, scenario, "driver", output)
            marker.write_bytes(marker_original)
        if scenario == "P1-UNCERTAIN-EFFECT":
            proof = lineage["uncertain_effect_proof"]
            assert proof["attempt_id"] == lineage["attempt_id"]
            assert proof["message_id"] == lineage["message_id"]
            assert proof["dispatch_id"] == lineage["dispatch_id"]
            assert proof["machine_id"] == gate_machine
            assert proof["domain_record_absent_at_fault"]
            assert proof["initial_status"] == "uncertain"
            assert proof["initial_completion_state"] == "prepared"
            assert proof["final_status"] == "verified"
            assert proof["final_completion_state"] == "completed"
            assert proof["target_write_count"] == 1
            assert proof["fault_file_identity"] == proof["effect_file_identity"]
            assert proof["fault_file_sha256"] == proof["effect_file_sha256"]
            assert proof["completion_basis"] == "observed_target"
            assert proof["pending_new_operation_rejected"]
            assert proof["acceptance_blocked_while_uncertain"]
            assert proof["late_old_owner_rejected"]
            assert len(results[0]["operation_ids"]) == 6
            effect_file = output / "P1-UNCERTAIN-EFFECT-effects" / "output.txt"
            original = effect_file.read_bytes()
            effect_file.write_bytes(b"forged second effect")
            with pytest.raises(probe.ProbeRejected, match="uncertain Effect file or marker"):
                probe.execute(profile, scenario, "driver", output)
            effect_file.write_bytes(original)
            marker = next(
                (output / "P1-UNCERTAIN-EFFECT-effects" / ".acs-effect-markers"
                 / "current").glob("*.json")
            )
            marker_original = marker.read_bytes()
            marker.write_bytes(marker_original + b" ")
            with pytest.raises(probe.ProbeRejected, match="uncertain Effect file or marker"):
                probe.execute(profile, scenario, "driver", output)
            marker.write_bytes(marker_original)
        assert (output.stat().st_mode & 0o777) == 0o700
        for private_file in output.iterdir():
            if private_file.is_file():
                assert (private_file.stat().st_mode & 0o777) == 0o600
        secret = psycopg.conninfo.conninfo_to_dict(
            json.loads(profile.read_text())["postgres_dsn"]
        )["password"].encode()
        assert not any(
            secret in path.read_bytes() for path in output.rglob("*") if path.is_file()
        )
        schema = row["pg_schema"]
        scoped = make_conninfo(
            json.loads(profile.read_text())["postgres_dsn"],
            options=f"-c search_path={schema}",
        )
        if scenario in ("P1-COMMAND-DEDUP", "P1-LEASE-FENCING"):
            with psycopg.connect(scoped) as connection:
                selected = connection.execute(
                    "SELECT selection_json FROM delivery_attempts WHERE message_id=%s",
                    (lineage["message_id"],),
                ).fetchone()[0]
                changed = {**selected, "machine_id": "forged-machine"}
                connection.execute(
                    "UPDATE delivery_attempts SET selection_json=%s WHERE message_id=%s",
                    (json.dumps(changed), lineage["message_id"]),
                )
            with pytest.raises(probe.ProbeRejected, match="PostgreSQL Runtime lineage changed"):
                probe.execute(profile, scenario, "postgresql", output)
            with psycopg.connect(scoped) as connection:
                connection.execute(
                    "UPDATE delivery_attempts SET selection_json=%s WHERE message_id=%s",
                    (json.dumps(selected), lineage["message_id"]),
                )
            if scenario == "P1-LEASE-FENCING":
                with psycopg.connect(scoped) as connection:
                    connection.execute(
                        "UPDATE leases SET owner_attempt_id=%s WHERE lease_id=%s",
                        ("forged-replacement-attempt",
                         lineage["lease_proof"]["replacement_lease_id"]),
                    )
                with pytest.raises(probe.ProbeRejected, match="Lease PG authority/enrollment/fence"):
                    probe.execute(profile, scenario, "postgresql", output)
                with psycopg.connect(scoped) as connection:
                    connection.execute(
                        "UPDATE leases SET owner_attempt_id=%s WHERE lease_id=%s",
                        (lineage["lease_proof"]["replacement_attempt_id"],
                         lineage["lease_proof"]["replacement_lease_id"]),
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
            elif scenario == "P1-LEASE-FENCING":
                connection.execute(
                    "UPDATE leases SET status='granted' WHERE lease_id=%s",
                    (lineage["lease_proof"]["lease_id"],),
                )
            elif scenario == "P1-UNCERTAIN-EFFECT":
                connection.execute(
                    "UPDATE outbox SET topic='forged.effect' WHERE operation_id=%s",
                    (lineage["uncertain_effect_proof"]["reconciliation_operation_id"],),
                )
            else:
                connection.execute(
                    "UPDATE delivery_attempts SET status='interrupted' "
                    "WHERE message_id=%s AND ordinal=1",
                    (lineage["message_id"],),
                )
        error = (
            "Lease PG authority/enrollment/fence lineage changed"
            if scenario == "P1-LEASE-FENCING"
            else "uncertain Effect PG/Delivery/Attempt lineage changed"
            if scenario == "P1-UNCERTAIN-EFFECT"
            else "PostgreSQL Runtime lineage changed"
        )
        with pytest.raises(probe.ProbeRejected, match=error):
            probe.execute(profile, scenario, "postgresql", output)
    finally:
        if output.exists():
            probe.cleanup(profile, output)
    if schema is not None:
        with psycopg.connect(json.loads(profile.read_text())["postgres_dsn"]) as connection:
            assert connection.execute(
                "SELECT count(*) FROM pg_namespace WHERE nspname=%s", (schema,),
            ).fetchone() == (0,)
