"""Execute the real P2 Codex protected-resource fault scenarios.

This adapter deliberately reuses the reviewed P1 profile engine for its private
Domain setup helpers.  The retained authority schema, evidence ledger, files,
and result identity are P2-specific and are independently read back here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sqlite3
import stat
import subprocess
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

SOURCE_ROOT = Path(__file__).resolve().parents[2]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from tools.runtime import p1_profile_probe as engine


SCENARIOS = {
    "P2-CODEX-STALE-OWNER": "P1-LEASE-FENCING",
    "P2-CODEX-UNCERTAIN-EFFECT": "P1-UNCERTAIN-EFFECT",
}
RESULT_SCHEMA = "acs-p2-codex-resource-scenario/1"
LEDGER_SCHEMA = "acs-p2-codex-resource-ledger/1"


class ScenarioRejected(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(root: Path, ref: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", ref], cwd=root, capture_output=True, text=True,
        timeout=30, check=False,
    )
    if result.returncode:
        raise ScenarioRejected("source Git identity is unavailable")
    value = result.stdout.strip()
    if len(value) != 40:
        raise ScenarioRejected("source Git identity is invalid")
    return value


def _machine_fingerprint() -> str:
    machine = ""
    for path in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
        try:
            machine = path.read_text(encoding="ascii").strip()
            if machine:
                break
        except OSError:
            continue
    return _sha(_canonical({
        "hostname": platform.node(), "machine_id": machine,
        "architecture": platform.machine(), "platform": platform.platform(),
    }))


def _private_json(path: Path, value: object) -> None:
    path.write_bytes(json.dumps(value, indent=2, sort_keys=True).encode() + b"\n")
    path.chmod(0o600)


def _effect_inventory(root: Path) -> dict[str, Any]:
    output = root / "output.txt"
    info = output.stat(follow_symlinks=False)
    if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1):
        raise ScenarioRejected("P2 protected Effect output is not one private regular file")
    markers = []
    marker_root = root / engine.LocalFileEffectGateway.MARKER_DIR
    for path in sorted(marker_root.rglob("*")):
        if path.is_file() and path.name != "lock":
            marker_info = path.stat(follow_symlinks=False)
            markers.append({
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha(path.read_bytes()),
                "mode": stat.S_IMODE(marker_info.st_mode),
                "links": marker_info.st_nlink,
            })
    if not markers or any(item["mode"] != 0o600 or item["links"] != 1 for item in markers):
        raise ScenarioRejected("P2 protected Effect marker inventory is incomplete")
    return {
        "path": output.relative_to(root.parent).as_posix(),
        "sha256": _sha(output.read_bytes()), "size_bytes": info.st_size,
        "file_identity": [info.st_dev, info.st_ino, info.st_uid,
                          stat.S_IMODE(info.st_mode), info.st_nlink],
        "marker_count": len(markers),
        "marker_inventory_sha256": _sha(_canonical(markers)),
    }


def _query_authority(profile: dict[str, Any], schema: str, proof: dict[str, Any],
                     scenario: str) -> dict[str, Any]:
    scoped = make_conninfo(
        profile["postgres_dsn"], options=f"-c search_path={schema} -c lock_timeout=5000",
    )
    with psycopg.connect(scoped) as connection:
        attempts = connection.execute(
            "SELECT attempt_id,work_item_id,runtime_id,source_commit,source_tree,"
            "candidate_ref FROM attempts WHERE work_item_id=%s ORDER BY attempt_id",
            (proof["work_item_id"],),
        ).fetchall()
        delivery = connection.execute(
            "SELECT attempt_id,dispatch_id,status FROM delivery_attempts "
            "WHERE message_id=%s ORDER BY ordinal", (proof["message_id"],),
        ).fetchall()
        leases = connection.execute(
            "SELECT lease_id,resource_id,owner_attempt_id,owner_runtime_id,generation,status,"
            "grant_ref,authority_incarnation FROM leases WHERE resource_id=%s ORDER BY generation",
            (proof["resource_id"],),
        ).fetchall()
        effects = connection.execute(
            "SELECT effect_id,lease_id,resource_id,operation_id,status,completion_state,"
            "expected_sha256,intent_sha256,completion_sha256,registration_operation_id,"
            "reconciliation_operation_id FROM effects WHERE work_item_id=%s ORDER BY effect_id",
            (proof["work_item_id"],),
        ).fetchall()
        events = connection.execute(
            "SELECT count(*) FROM domain_events WHERE work_item_id=%s",
            (proof["work_item_id"],),
        ).fetchone()[0]
        outbox = connection.execute(
            "SELECT count(*) FROM outbox WHERE operation_id IN ("
            "SELECT operation_id FROM operations WHERE command_id IN ("
            "SELECT command_id FROM domain_events WHERE work_item_id=%s))",
            (proof["work_item_id"],),
        ).fetchone()[0]
    attempt_rows = [list(row) for row in attempts]
    lease_rows = [list(row) for row in leases]
    effect_rows = [list(row) for row in effects]
    expected_attempts = {proof["attempt_id"]}
    if scenario == "P2-CODEX-STALE-OWNER":
        expected_attempts.add(proof["replacement_attempt_id"])
        valid = (
            len(lease_rows) == 2
            and [row[4] for row in lease_rows] == [proof["generation"], proof["replacement_generation"]]
            and lease_rows[0][5] == "released"
            and lease_rows[1][2] == proof["replacement_attempt_id"]
            and lease_rows[1][3] == proof["replacement_runtime_id"]
            and not effect_rows
        )
    else:
        valid = (
            len(lease_rows) == 1 and lease_rows[0][2] == proof["attempt_id"]
            and lease_rows[0][3] == proof["runtime_id"] and lease_rows[0][5] == "released"
            and len(effect_rows) == 1
            and effect_rows[0][0] == proof["effect_id"]
            and effect_rows[0][4:6] == ["verified", "completed"]
            and effect_rows[0][6] == proof["artifact_sha256"]
            and effect_rows[0][8] == proof["completion_sha256"]
        )
    if ({row[0] for row in attempt_rows} != expected_attempts
            or delivery != [(proof["delivery_attempt_id"], proof["dispatch_id"], "delivered")]
            or any(row[3] != proof["source_commit"] or row[4] != proof["source_tree"]
                   for row in attempt_rows)
            or not valid or events < 1 or outbox < 1):
        raise ScenarioRejected("P2 PostgreSQL Attempt/Lease/Effect lineage changed")
    return {
        "attempts": attempt_rows, "delivery_attempts": [list(row) for row in delivery],
        "leases": lease_rows, "effects": effect_rows,
        "domain_event_count": events, "outbox_count": outbox,
    }


def _rename_schema(profile: dict[str, Any], old: str, new: str) -> None:
    with psycopg.connect(profile["postgres_dsn"], autocommit=True) as connection:
        exists = connection.execute(
            "SELECT count(*) FROM pg_namespace WHERE nspname=%s", (new,),
        ).fetchone()[0]
        if exists:
            raise ScenarioRejected("P2 PostgreSQL schema already exists")
        connection.execute(sql.SQL("ALTER SCHEMA {} RENAME TO {}").format(
            sql.Identifier(old), sql.Identifier(new),
        ))


def _write_ledger(output: Path, report: dict[str, Any]) -> None:
    ledger = output / "p2-codex-resource.sqlite"
    with closing(sqlite3.connect(ledger)) as connection:
        connection.execute(
            "CREATE TABLE scenario_evidence("
            "scenario_id TEXT PRIMARY KEY,schema_version TEXT NOT NULL,run_id TEXT NOT NULL,"
            "source_commit TEXT NOT NULL,source_tree TEXT NOT NULL,machine_id TEXT NOT NULL,"
            "node_id TEXT NOT NULL,pg_schema TEXT NOT NULL,evidence_sha256 TEXT NOT NULL,"
            "observed_at TEXT NOT NULL)"
        )
        digest = _sha(_canonical(report))
        connection.execute(
            "INSERT INTO scenario_evidence VALUES (?,?,?,?,?,?,?,?,?,?)",
            (report["scenario_id"], LEDGER_SCHEMA, report["run_id"],
             report["source_commit"], report["source_tree"], report["machine_id"],
             report["node_id"], report["postgresql"]["schema"], digest,
             report["observed_at"]),
        )
        connection.commit()
    ledger.chmod(0o600)


def execute(profile_path: Path, scenario: str, output: Path, machine_id: str,
            source_root: Path) -> dict[str, Any]:
    if scenario not in SCENARIOS or not machine_id or "/" in machine_id or "\\" in machine_id:
        raise ScenarioRejected("P2 resource scenario identity is invalid")
    profile, profile_sha, secrets = engine._secure_profile(profile_path)
    source = source_root.resolve(strict=True)
    profile = dict(profile, source_root=str(source))
    output = output.resolve(strict=False)
    if output == source or output.is_relative_to(source) or output.exists():
        raise ScenarioRejected("P2 output must be a new directory outside source")
    commit, tree = _git(source, "HEAD"), _git(source, "HEAD^{tree}")
    output.mkdir(mode=0o700, parents=True)
    output.chmod(0o700)
    private = output / ".p2-private-engine"
    run_id = "p2-codex-resource-" + _sha(os.urandom(32))[:24]
    mapped = SCENARIOS[scenario]
    previous = {name: os.environ.get(name) for name in (
        "ACS_GATE_RUN_ID", "ACS_GATE_MACHINE_ID", "ACS_GATE_SOURCE_COMMIT",
        "ACS_GATE_SOURCE_TREE",
    )}
    os.environ.update({
        "ACS_GATE_RUN_ID": run_id, "ACS_GATE_MACHINE_ID": machine_id,
        "ACS_GATE_SOURCE_COMMIT": commit, "ACS_GATE_SOURCE_TREE": tree,
    })
    old_schema = None
    renamed = False
    try:
        layers = [engine.execute(profile_path, mapped, kind, private) for kind in engine.KINDS]
        row = engine.ProbeLedger(private).get(mapped)
        if row is None:
            raise ScenarioRejected("P2 private Runtime execution did not retain a lineage")
        lineage = json.loads(row["lineage_json"])
        proof = (lineage["lease_proof"] if scenario == "P2-CODEX-STALE-OWNER"
                 else lineage["uncertain_effect_proof"])
        if proof is None or proof["machine_id"] != machine_id:
            raise ScenarioRejected("P2 fault proof is not bound to the requested Machine")
        old_schema = row["pg_schema"]
        schema = "p2_codex_" + _sha(f"{run_id}:{scenario}:{commit}:{tree}".encode())[:32]
        _rename_schema(profile, old_schema, schema)
        renamed = True
        effect_source = private / (mapped + "-effects")
        effect_root = output / (scenario + "-effects")
        shutil.move(str(effect_source), effect_root)
        effect = _effect_inventory(effect_root)
        proof = {**proof, "message_id": lineage["message_id"],
                 "delivery_attempt_id": lineage["attempts"][0]["attempt_id"],
                 "dispatch_id": lineage["dispatch_id"]}
        authority = _query_authority(profile, schema, proof, scenario)
        layer_status = {
            item["evidence_kind"]: {
                "status": item["status"],
                "command_id": scenario + ":" + item["evidence_kind"],
                "operation_ids": item["operation_ids"],
                "event_ids": item["event_ids"],
                "receipt_ids": item["receipt_ids"],
            }
            for item in layers
        }
        if set(layer_status) != set(engine.KINDS) or any(
            item["status"] != "passed" for item in layer_status.values()
        ):
            raise ScenarioRejected("P2 six-layer readback is incomplete")
        if scenario == "P2-CODEX-STALE-OWNER":
            fault = {
                "replacement_generation": proof["replacement_generation"],
                "original_attempt_id": proof["attempt_id"],
                "replacement_attempt_id": proof["replacement_attempt_id"],
                "stale_fence_rejected": proof["stale_fence_rejected"],
                "late_old_owner_rejected": proof["late_old_owner_rejected"],
                "replacement_readback_before_late": proof["replacement_readback_before_late"],
                "pre_late_snapshot_sha256": _sha(_canonical(proof["pre_late_snapshot"])),
                "post_late_snapshot_sha256": _sha(_canonical(proof["post_late_snapshot"])),
            }
            if (not all((fault["stale_fence_rejected"], fault["late_old_owner_rejected"],
                         fault["replacement_readback_before_late"]))
                    or fault["pre_late_snapshot_sha256"] != fault["post_late_snapshot_sha256"]):
                raise ScenarioRejected("P2 stale owner changed the replacement resource")
        else:
            fault = {
                "domain_record_absent_at_fault": proof["domain_record_absent_at_fault"],
                "initial_status": proof["initial_status"],
                "final_status": proof["final_status"],
                "completion_basis": proof["completion_basis"],
                "target_write_count": proof["target_write_count"],
                "acceptance_blocked_while_uncertain": proof["acceptance_blocked_while_uncertain"],
                "pending_new_operation_rejected": proof["pending_new_operation_rejected"],
                "late_old_owner_rejected": proof["late_old_owner_rejected"],
            }
            if (not fault["domain_record_absent_at_fault"] or fault["initial_status"] != "uncertain"
                    or fault["final_status"] != "verified" or fault["completion_basis"] != "observed_target"
                    or fault["target_write_count"] != 1
                    or not all((fault["acceptance_blocked_while_uncertain"],
                                fault["pending_new_operation_rejected"],
                                fault["late_old_owner_rejected"]))):
                raise ScenarioRejected("P2 uncertain Effect recovery invariants changed")
        report = {
            "schema_version": RESULT_SCHEMA, "status": "passed",
            "scenario_id": scenario, "run_id": run_id,
            "observer": "p2-codex-resource-probe", "owner": "runtime-domain",
            "source_commit": commit, "source_tree": tree,
            "machine_id": machine_id, "node_id": profile["node_id"],
            "machine_fingerprint_sha256": _machine_fingerprint(),
            "platform": platform.platform(), "profile_sha256": profile_sha,
            "versions": profile["versions"], "observed_at": datetime.now(UTC).isoformat(),
            "postgresql": {"schema": schema, "authority_readback": authority},
            "effect_readback": effect, "fault_injection": fault,
            "layers": layer_status, "unresolved_items": [],
        }
        encoded = _canonical(report)
        if any(secret and secret in encoded for secret in secrets):
            raise ScenarioRejected("P2 evidence contains a provider secret")
        _private_json(output / (scenario + "-evidence.json"), report)
        _write_ledger(output, report)
        return report
    except Exception:
        if old_schema is not None:
            target = schema if renamed else old_schema
            with psycopg.connect(profile["postgres_dsn"], autocommit=True) as connection:
                connection.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(target),
                ))
        raise
    finally:
        shutil.rmtree(private, ignore_errors=True)
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def audit(profile_path: Path, output: Path, source_root: Path) -> dict[str, Any]:
    profile, _profile_sha, _secrets = engine._secure_profile(profile_path)
    profile = dict(profile, source_root=str(source_root.resolve(strict=True)))
    evidence_files = list(output.glob("P2-CODEX-*-evidence.json"))
    if len(evidence_files) != 1:
        raise ScenarioRejected("one P2 resource evidence file is required")
    report = json.loads(evidence_files[0].read_text())
    if (report.get("schema_version") != RESULT_SCHEMA or report.get("status") != "passed"
            or report.get("scenario_id") not in SCENARIOS
            or report.get("source_commit") != _git(Path(profile["source_root"]), "HEAD")
            or report.get("source_tree") != _git(Path(profile["source_root"]), "HEAD^{tree}")):
        raise ScenarioRejected("P2 evidence source or scenario identity changed")
    schema = report["postgresql"]["schema"]
    proof_rows = report["postgresql"]["authority_readback"]
    with psycopg.connect(
        make_conninfo(profile["postgres_dsn"], options=f"-c search_path={schema}"),
    ) as connection:
        attempts = connection.execute(
            "SELECT attempt_id,work_item_id,runtime_id,source_commit,source_tree,candidate_ref "
            "FROM attempts WHERE work_item_id=%s ORDER BY attempt_id",
            (proof_rows["attempts"][0][1],),
        ).fetchall()
        leases = connection.execute(
            "SELECT lease_id,resource_id,owner_attempt_id,owner_runtime_id,generation,status,"
            "grant_ref,authority_incarnation FROM leases WHERE resource_id=%s ORDER BY generation",
            (proof_rows["leases"][0][1],),
        ).fetchall()
    if [list(row) for row in attempts] != proof_rows["attempts"] or [list(row) for row in leases] != proof_rows["leases"]:
        raise ScenarioRejected("P2 PostgreSQL readback changed after execution")
    effect = _effect_inventory(output / (report["scenario_id"] + "-effects"))
    if effect != report["effect_readback"]:
        raise ScenarioRejected("P2 file Effect readback changed after execution")
    with sqlite3.connect(output / "p2-codex-resource.sqlite") as connection:
        row = connection.execute(
            "SELECT scenario_id,source_commit,source_tree,machine_id,node_id,pg_schema,evidence_sha256 "
            "FROM scenario_evidence",
        ).fetchone()
    if row != (
        report["scenario_id"], report["source_commit"], report["source_tree"],
        report["machine_id"], report["node_id"], schema, _sha(_canonical(report)),
    ):
        raise ScenarioRejected("P2 evidence ledger changed")
    return {"status": "passed", "scenario_id": report["scenario_id"],
            "source_commit": report["source_commit"], "source_tree": report["source_tree"],
            "machine_id": report["machine_id"], "pg_schema": schema}


def cleanup(profile_path: Path, output: Path) -> dict[str, Any]:
    profile, _digest, _secrets = engine._secure_profile(profile_path)
    evidence_files = list(output.glob("P2-CODEX-*-evidence.json"))
    schemas = []
    for path in evidence_files:
        value = json.loads(path.read_text())
        schema = value.get("postgresql", {}).get("schema")
        if isinstance(schema, str) and schema.startswith("p2_codex_"):
            schemas.append(schema)
    with psycopg.connect(profile["postgres_dsn"], autocommit=True) as connection:
        for schema in schemas:
            connection.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                sql.Identifier(schema),
            ))
    return {"status": "cleaned", "schemas": schemas}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    run = sub.add_parser("run")
    run.add_argument("--profile", type=Path, required=True)
    run.add_argument("--scenario", choices=tuple(SCENARIOS), required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--machine-id", required=True)
    run.add_argument("--source-root", type=Path, required=True)
    check = sub.add_parser("audit")
    check.add_argument("--profile", type=Path, required=True)
    check.add_argument("--output", type=Path, required=True)
    check.add_argument("--source-root", type=Path, required=True)
    clean = sub.add_parser("cleanup")
    clean.add_argument("--profile", type=Path, required=True)
    clean.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = (
            execute(args.profile, args.scenario, args.output, args.machine_id, args.source_root)
            if args.action == "run" else audit(args.profile, args.output, args.source_root)
            if args.action == "audit" else cleanup(args.profile, args.output)
        )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as error:  # noqa: BLE001 - bounded scenario command
        print(json.dumps({"status": "blocked", "error": type(error).__name__,
                          "reason": str(error)[:400]}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
