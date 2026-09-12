"""Executable real-resource P1 probe profile; never writes a formal Gate."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import re
import sqlite3
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

SOURCE_ROOT = Path(__file__).resolve().parents[2]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from runtime.delivery import DeliveryDispatcher, DeliveryService
from runtime.delivery_models import DeliveryPacket, EndpointBindingRequest
from runtime.delivery_node import LocalNodeEndpoint
from runtime.domain import DomainAuthority
from runtime.errors import IdempotencyConflict
from runtime.models import CommandEnvelope
from runtime.node import NodeJournal
from runtime.temporal import TemporalAdapter
from runtime_tests.test_delivery import FixtureDriver

SCHEMA = "acs-p1-loopback-probe-profile/1"
RESULT_SCHEMA = "acs-p1-gate-probe-result/1"
KINDS = ("command_output", "postgresql", "sqlite", "temporal", "driver", "os")
EVIDENCE_FIELDS = {
    "command_output": ("raw_outputs", "fault_injection"),
    "postgresql": ("receipts",),
    "sqlite": ("artifact_readback",),
    "temporal": ("recovery_trace",),
    "driver": ("effect_readback",),
    "os": ("source_readback",),
}
SECRET_PATTERN = re.compile(
    rb"(?i)(password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|authorization)\s*[:=]"
)


class ProbeUnavailable(RuntimeError):
    pass


class ProbeRejected(RuntimeError):
    pass


class ScenarioCatalog:
    LINEAGE_BOUND: ClassVar[frozenset[str]] = frozenset({"P1-DOMAIN-TRANSACTION"})
    TESTS: ClassVar[dict[str, tuple[str, ...]]] = {
        "P1-DOMAIN-TRANSACTION": (
            "runtime_tests/test_postgres_integration.py::test_real_postgres_retry_revocation_and_incomplete_evidence_guards",
        ),
        "P1-AUTH-REVOCATION": (
            "runtime_tests/test_surface_delivery.py::test_operator_authorization_cannot_replace_revoked_sender",
            "runtime_tests/test_domain_ledger.py::test_legacy_replay_still_rejects_revoked_grant",
        ),
        "P1-COMMAND-DEDUP": (
            "runtime_tests/test_domain_ledger.py::test_same_command_id_with_different_keys_is_transactionally_serialized",
            "runtime_tests/test_delivery.py::test_ack_loss_retries_same_identity_without_second_fixture_invoke",
        ),
        "P1-INBOX-ACK-LOSS": (
            "runtime_tests/test_node.py::test_mailbox_and_distinct_lifecycle_receipts_survive_ack_loss",
            "runtime_tests/test_delivery.py::test_ack_loss_retries_same_identity_without_second_fixture_invoke",
        ),
        "P1-CORE-RESTART": (
            "runtime_tests/test_delivery.py::test_real_core_process_crash_after_committed_attempt_recovers",
        ),
        "P1-NODE-RESTART": (
            "runtime_tests/test_delivery.py::test_real_node_boot_restart_and_authorized_rebind_preserve_logical_inbox",
            "runtime_tests/test_systemd_supervisor.py::test_bidirectional_stdio_grandchild_root_exit_and_isolated_cleanup",
        ),
        "P1-PROVIDER-RESTART": (
            "runtime_tests/test_temporal.py::test_temporal_replay_survives_new_adapter_instance",
            "runtime_tests/test_human_bridge_file_provider.py::test_actual_process_restart_recovers_same_effect_without_second_file",
        ),
        "P1-HARNESS-REPLACEMENT": (
            "runtime_tests/test_codex_driver.py::test_shared_attach_is_read_only",
            "runtime_tests/test_opencode_driver.py::test_shared_attach_is_read_only",
            "runtime_tests/test_delivery.py::test_replacement_node_cannot_repeat_an_unreconciled_native_activation",
        ),
        "P1-LEASE-FENCING": (
            "runtime_tests/test_lease_gateway_integration.py::test_real_history_reads_after_lease_termination",
            "runtime_tests/test_file_effect_gateway.py::test_fence_rechecked_immediately_before_target_replace",
        ),
        "P1-UNCERTAIN-EFFECT": (
            "runtime_tests/test_effect_registration.py::test_actual_prepared_readback_registers_uncertain_and_cannot_accept",
            "runtime_tests/test_effect_registration.py::test_real_resume_explicit_reconciliation_and_acceptance",
        ),
        "P1-STALE-BASELINE": (
            "runtime_tests/test_domain_evidence.py::test_forged_evidence_rolls_back_all_writes",
            "runtime_tests/test_domain_evidence.py::test_ready_does_not_freeze_authorization_or_cas_verification",
        ),
        "P1-PARTIAL-ARTIFACT": (
            "runtime_tests/test_artifact_store.py::test_fsync_order_and_failed_write_cleanup",
            "runtime_tests/test_domain_evidence.py::test_final_acceptance_requires_complete_matching_effect_readback_proof",
        ),
        "P1-SURFACE-PARITY": (
            "runtime_tests/test_surfaces.py::test_real_mcp_cli_http_share_pg_identity_and_conflicts",
            "runtime_tests/test_recovery_surfaces.py::test_recovery_status_uses_same_actual_cli_mcp_and_http_surface",
        ),
        "P1-CODEX-LIFECYCLE": (
            "runtime_tests/test_codex_driver.py::test_spawn_records_intent_and_effective_profile",
            "runtime_tests/test_codex_driver.py::test_owned_process_can_be_terminated_after_session_ack_loss",
        ),
        "P1-OPENCODE-LIFECYCLE": (
            "runtime_tests/test_response_collector_integration.py::test_delayed_opencode_response_is_collected_once_and_projection_only_retries",
        ),
        "P1-NATIVE-MULTIAGENT-OFF": (
            "runtime_tests/test_codex_driver.py::test_native_delegation_enablement_is_rejected",
            "runtime_tests/test_opencode_driver.py::test_no_tools_agent_or_file_override_surface",
        ),
        "P1-IDENTITY-CONTINUITY": (
            "runtime_tests/test_receiver_protocol.py::test_actual_tls13_two_process_signed_delivery_and_readback",
            "runtime_tests/test_enrollment.py::test_fresh_authentication_cannot_replace_same_command_business_input",
        ),
        "P1-INTEGRATED-ACCEPTANCE": (
            "runtime_tests/test_acceptance_gateway_integration.py::test_real_ready_publication_historical_callback_and_acceptance",
        ),
    }
    MODEL_REQUIREMENTS: ClassVar[dict[str, str]] = {
        "P1-CODEX-LIFECYCLE": "codex_model_evidence",
        "P1-OPENCODE-LIFECYCLE": "opencode_model_evidence",
        "P1-INTEGRATED-ACCEPTANCE": "all_model_scenarios",
    }


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value):
        raise ProbeRejected("identity is outside the reviewed bound")
    return value


def _secure_profile(path: Path) -> tuple[dict[str, Any], str, tuple[bytes, ...]]:
    if os.name != "posix" or not path.is_absolute():
        raise ProbeRejected("P1 loopback provider profile requires an absolute POSIX path")
    parent = path.parent
    parent_info = parent.stat(follow_symlinks=False)
    if (not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != os.geteuid()
            or stat.S_IMODE(parent_info.st_mode) != 0o700):
        raise ProbeRejected("P1 profile directory must be owner-only")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                or info.st_size > 65_536):
            raise ProbeRejected("P1 profile file must be one owner-only regular file")
        data = os.read(descriptor, 65_537)
    finally:
        os.close(descriptor)
    try:
        value = json.loads(data)
    except (UnicodeError, ValueError):
        raise ProbeRejected("P1 profile JSON is invalid") from None
    required = {
        "schema_version", "profile", "source_root", "python", "postgres_dsn",
        "sandbox_python",
        "temporal_endpoint", "temporal_namespace", "versions", "node_id",
        "direction", "codex_model_evidence", "opencode_model_evidence",
    }
    if not isinstance(value, dict) or set(value) != required or value["schema_version"] != SCHEMA:
        raise ProbeRejected("P1 profile fields are invalid")
    connection = conninfo_to_dict(value["postgres_dsn"])
    if (connection.get("host") != "127.0.0.1" or connection.get("port") != "54329"
            or not connection.get("password") or value["temporal_endpoint"] != "127.0.0.1:7239"):
        raise ProbeRejected("P1 providers must be the declared loopback targets")
    secrets = tuple(
        item.encode() for item in (connection.get("password"),)
        if isinstance(item, str) and item
    )
    return value, _sha(data), secrets


def _source_identity(root: Path) -> tuple[str, str]:
    def git(ref: str) -> str:
        result = subprocess.run(
            ["git", "rev-parse", ref], cwd=root, capture_output=True, text=True,
            timeout=30, check=False,
        )
        if result.returncode:
            raise ProbeUnavailable("source Git identity is unavailable")
        return result.stdout.strip()

    return git("HEAD"), git("HEAD^{tree}")


def _model_evidence_current(profile: dict[str, Any], field: str, commit: str) -> bool:
    name = profile.get(field)
    if not isinstance(name, str) or not name:
        return False
    path = Path(name)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (
        value.get("result") == "pass"
        and value.get("source_baseline") == commit
        and value.get("prompt_count") == 1
        and value.get("termination", {}).get("supervisor_proof", {}).get("remaining_pids") == []
    )


def availability(profile: dict[str, Any], commit: str) -> dict[str, dict[str, Any]]:
    codex = _model_evidence_current(profile, "codex_model_evidence", commit)
    opencode = _model_evidence_current(profile, "opencode_model_evidence", commit)
    values = {}
    for scenario in ScenarioCatalog.TESTS:
        requirement = ScenarioCatalog.MODEL_REQUIREMENTS.get(scenario)
        resource_ready = requirement is None or requirement == "codex_model_evidence" and codex \
            or requirement == "opencode_model_evidence" and opencode \
            or requirement == "all_model_scenarios" and codex and opencode
        ready = scenario in ScenarioCatalog.LINEAGE_BOUND and resource_ready
        if ready:
            reason = "ready"
        elif not resource_ready:
            reason = (
                "Codex actual model/login evidence is NOT_RUN"
                if requirement == "codex_model_evidence"
                else "OpenCode actual model evidence is absent or stale"
                if requirement == "opencode_model_evidence"
                else "integrated acceptance waits for both actual model lifecycle scenarios"
            )
        else:
            reason = "scenario adapter is not yet bound to one actual Runtime lineage"
        values[scenario] = {
            "available": bool(ready),
            "reason": reason,
            "tests": ScenarioCatalog.TESTS[scenario],
        }
    return values


class ProbeLedger:
    def __init__(self, root: Path) -> None:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root.chmod(0o700)
        self.root = root
        self.path = root / "p1-probe.sqlite"
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS scenario_runs(
                    scenario_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,operation_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,event_id TEXT NOT NULL,receipt_id TEXT NOT NULL,
                    test_digest TEXT NOT NULL,raw_path TEXT NOT NULL,pg_schema TEXT NOT NULL,
                    temporal_workflow_id TEXT NOT NULL,temporal_run_id TEXT NOT NULL,
                    lineage_json TEXT NOT NULL,
                    source_commit TEXT NOT NULL,source_tree TEXT NOT NULL,status TEXT NOT NULL,
                    created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS evidence_reads(
                    scenario_id TEXT NOT NULL,kind TEXT NOT NULL,digest TEXT NOT NULL,
                    observed_at TEXT NOT NULL,PRIMARY KEY(scenario_id,kind));
                CREATE TABLE IF NOT EXISTS schema_reservations(
                    pg_schema TEXT PRIMARY KEY,created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scenario_claims(
                    scenario_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,suffix TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('pending','completed')),
                    started_at TEXT NOT NULL,updated_at TEXT NOT NULL);
            """)
        self.path.chmod(0o600)

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def get(self, scenario: str):
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT r.* FROM scenario_runs AS r JOIN scenario_claims AS c "
                "ON c.scenario_id=r.scenario_id WHERE r.scenario_id=? AND c.state='completed'",
                (scenario,),
            ).fetchone()
        return dict(row) if row else None

    def put(self, value: dict[str, Any]) -> None:
        columns = tuple(value)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM scenario_runs WHERE scenario_id=?", (value["scenario_id"],),
            ).fetchone()
            if existing is not None:
                if dict(existing) != value:
                    raise ProbeRejected("scenario result identity changed")
            else:
                connection.execute(
                    f"INSERT INTO scenario_runs({','.join(columns)}) "
                    f"VALUES ({','.join('?' for _ in columns)})",
                    tuple(value[name] for name in columns),
                )
            changed = connection.execute(
                "UPDATE scenario_claims SET state='completed',updated_at=? "
                "WHERE scenario_id=? AND run_id=?",
                (datetime.now(UTC).isoformat(), value["scenario_id"], value["run_id"]),
            ).rowcount
            if changed != 1:
                raise ProbeRejected("scenario claim is unavailable")

    def read(self, scenario: str, kind: str, evidence: dict[str, Any]) -> None:
        digest = _sha(_canonical(evidence))
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO evidence_reads VALUES (?,?,?,?) ON CONFLICT(scenario_id,kind) "
                "DO UPDATE SET digest=excluded.digest,observed_at=excluded.observed_at",
                (scenario, kind, digest, datetime.now(UTC).isoformat()),
            )

    def reserve_schema(self, pg_schema: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO schema_reservations VALUES (?,?)",
                (pg_schema, datetime.now(UTC).isoformat()),
            )

    def claim(self, scenario: str, run_id: str) -> tuple[str, datetime]:
        suffix = _sha(f"{run_id}:{scenario}".encode())[:24]
        started_at = datetime.now(UTC)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT run_id,suffix,started_at FROM scenario_claims WHERE scenario_id=?",
                (scenario,),
            ).fetchone()
            if row is not None:
                if (row["run_id"], row["suffix"]) != (run_id, suffix):
                    raise ProbeRejected("scenario claim identity changed")
                return suffix, datetime.fromisoformat(row["started_at"])
            stamp = started_at.isoformat()
            connection.execute(
                "INSERT INTO scenario_claims VALUES (?,?,?,'pending',?,?)",
                (scenario, run_id, suffix, stamp, stamp),
            )
        return suffix, started_at


def _no_secret(data: bytes, secrets: tuple[bytes, ...]) -> None:
    if SECRET_PATTERN.search(data) or any(secret in data for secret in secrets):
        raise ProbeRejected("probe output contained secret-like material")


async def _temporal_marker(profile: dict[str, Any], operation_id: str, scenario: str):
    adapter = TemporalAdapter(
        profile["temporal_endpoint"], namespace=profile["temporal_namespace"],
        task_queue="p1-probe-" + hashlib.sha256(operation_id.encode()).hexdigest()[:16],
    )
    await adapter.connect(start_worker=True)
    try:
        operation = await adapter.submit_operation(
            operation_id, {"scenario_id": scenario, "operation_id": operation_id},
        )
        readback = await adapter.readback(operation_id)
        if readback.get("status") != "committed":
            raise ProbeUnavailable("Temporal marker readback is incomplete")
        return operation.workflow_id, operation.run_id
    finally:
        await adapter.close()


def _domain_command(authority: DomainAuthority, command_type: str, target_kind: str,
                    target_id: str, suffix: str, issued_at: datetime,
                    *, revision: int = 0) -> CommandEnvelope:
    return CommandEnvelope(
        command_id=f"p1:{suffix}:{command_type}",
        idempotency_key=f"p1:{suffix}:{command_type}:key",
        correlation_id=f"p1:{suffix}", command_type=command_type,
        tenant_id=authority.tenant_id, authority_id=authority.context.authority_id,
        authority_incarnation=authority.context.authority_incarnation,
        principal_ref=authority.context.principal_ref, grant_ref=authority.context.grant_ref,
        target_kind=target_kind, target_id=target_id, expected_revision=revision,
        issued_at=issued_at, deadline=issued_at + timedelta(minutes=30), payload={},
    )


def _run_domain_transaction(
    profile: dict[str, Any], scenario: str, ledger: ProbeLedger,
    commit: str, tree: str, run_id: str, suffix: str, issued_at: datetime,
    fault: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    pg_schema = "p1_probe_" + suffix
    with psycopg.connect(profile["postgres_dsn"], autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(pg_schema)))
    ledger.reserve_schema(pg_schema)
    if fault is not None:
        fault("after_schema_reserved")
    scoped_dsn = make_conninfo(
        profile["postgres_dsn"], options=f"-c search_path={pg_schema}",
    )
    authority = DomainAuthority(scoped_dsn)
    authority.initialize()
    authority.bootstrap_local_grant((
        "work_item.create", "delivery.manage", "message.send", "message.read",
        "runtime.invoke",
    ))
    work_id = "work-" + suffix
    create = _domain_command(
        authority, "work_item.create", "work_item", work_id, suffix, issued_at,
    )
    authority.create_work_item(create, "local-scope", "local-slot", commit)
    node = NodeJournal(
        ledger.root / (scenario + "-node.sqlite"),
        machine_id="machine-" + suffix, node_id=profile["node_id"],
        boot_incarnation="boot-" + suffix,
    )
    Path(node._path).chmod(0o600)
    driver = FixtureDriver()
    endpoint_id = "endpoint-" + suffix
    endpoint = LocalNodeEndpoint(node, "local-scope", "local-slot", driver)
    service = DeliveryService(authority, {endpoint_id: endpoint})
    bind = _domain_command(
        authority, "message.bind", "message", endpoint_id, suffix, issued_at,
    )
    service.bind_endpoint(bind, EndpointBindingRequest(
        scope_id="local-scope", agent_slot_id="local-slot",
        expires_at=bind.deadline,
    ))
    message_id = "message-" + suffix
    send = _domain_command(
        authority, "message.send", "message", message_id, suffix, issued_at,
    )
    packet = DeliveryPacket(
        work_item_id=work_id, target_scope_id="local-scope",
        target_agent_slot_id="local-slot", accepted_revision=0,
        goal="P1 Domain transaction probe", accepted_state_summary="revision zero",
        request="Return the fixed fixture response", source_baseline=commit,
        expected_response="layered receipt", activation="invoke",
        deadline=send.deadline,
    )
    sent = service.send_message(send, packet, endpoint_id=endpoint_id, binding_revision=1)
    identity = {
        "tenant_id": authority.tenant_id,
        "message_id": message_id,
        "operation_id": sent.operation_id,
    }
    delivered = DeliveryDispatcher(service).dispatch(identity)
    replay = service.send_message(send, packet, endpoint_id=endpoint_id, binding_revision=1)
    changed_packet = packet.model_copy(update={"request": "changed conflicting request"})
    try:
        service.send_message(send, changed_packet, endpoint_id=endpoint_id, binding_revision=1)
    except IdempotencyConflict:
        conflict_rejected = True
    else:
        conflict_rejected = False
    if not replay.duplicate or delivered["status"] != "delivered":
        raise ProbeRejected("Domain delivery transaction/replay result is incomplete")
    if not conflict_rejected:
        raise ProbeRejected("Domain command conflict was not rejected")
    with node._transaction() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS p1_driver_calls(operation_id TEXT PRIMARY KEY)"
        )
        for call in driver.calls:
            connection.execute("INSERT OR IGNORE INTO p1_driver_calls VALUES (?)", (call,))
        driver_calls = [
            item[0] for item in connection.execute(
                "SELECT operation_id FROM p1_driver_calls ORDER BY operation_id"
            )
        ]
    if driver_calls != [sent.operation_id]:
        raise ProbeRejected("Driver call lineage is incomplete")
    if fault is not None:
        fault("after_domain_dispatch")
    with authority._connect() as connection:
        attempt = connection.execute(
            "SELECT attempt_id,dispatch_id FROM delivery_attempts WHERE message_id=%s",
            (message_id,),
        ).fetchone()
        receipts = connection.execute(
            "SELECT receipt_id,layer FROM delivery_receipts WHERE message_id=%s ORDER BY observed_at",
            (message_id,),
        ).fetchall()
        events = connection.execute(
            "SELECT event_id FROM domain_events WHERE command_id=%s ORDER BY event_id",
            (send.command_id,),
        ).fetchall()
    if attempt is None or attempt[1] is None or not receipts or not events:
        raise ProbeRejected("Domain delivery lineage rows are incomplete")
    workflow_id, temporal_run_id = asyncio.run(
        _temporal_marker(profile, sent.operation_id + ":temporal", scenario),
    )
    lineage = {
        "tenant_id": authority.tenant_id, "command_id": send.command_id,
        "message_id": message_id, "operation_id": sent.operation_id,
        "attempt_id": attempt[0], "dispatch_id": attempt[1],
        "event_ids": [str(item[0]) for item in events],
        "receipts": [{"receipt_id": item[0], "layer": item[1]} for item in receipts],
        "driver_calls": driver_calls, "node_journal": scenario + "-node.sqlite",
        "conflict_rejected": conflict_rejected,
    }
    raw = ledger.root / (scenario + "-runtime.json")
    raw.write_bytes(_canonical({
        "scenario_id": scenario, "lineage": lineage,
        "result": "passed", "fault": "exact replay and conflicting identity guarded",
    }))
    raw.chmod(0o600)
    value = {
        "scenario_id": scenario, "run_id": run_id,
        "operation_id": sent.operation_id, "message_id": message_id,
        "event_id": str(events[-1][0]), "receipt_id": receipts[-1][0],
        "test_digest": _sha(raw.read_bytes()), "raw_path": raw.name,
        "pg_schema": pg_schema, "temporal_workflow_id": workflow_id,
        "temporal_run_id": temporal_run_id,
        "lineage_json": json.dumps(lineage, sort_keys=True),
        "source_commit": commit, "source_tree": tree, "status": "passed",
        "created_at": datetime.now(UTC).isoformat(),
    }
    ledger.put(value)
    return value


def _run_tests(profile: dict[str, Any], scenario: str, ledger: ProbeLedger,
               commit: str, tree: str, secrets: tuple[bytes, ...],
               fault: Callable[[str], None] | None = None) -> dict[str, Any]:
    if ledger.get(scenario) is not None:
        return ledger.get(scenario)
    run_id = os.environ.get("ACS_GATE_RUN_ID", "standalone-" + _sha(os.urandom(16))[:24])
    suffix, issued_at = ledger.claim(scenario, run_id)
    if scenario == "P1-DOMAIN-TRANSACTION":
        return _run_domain_transaction(
            profile, scenario, ledger, commit, tree, run_id, suffix, issued_at, fault,
        )
    tests = ScenarioCatalog.TESTS[scenario]
    command = [profile["python"], "-m", "pytest", "-o", "addopts=", "-q", *tests]
    environment = dict(os.environ)
    environment.update({
        "ACS_P1_DSN": profile["postgres_dsn"],
        "ACS_P1_TEMPORAL_ENDPOINT": profile["temporal_endpoint"],
        "ACS_P1_TEMPORAL_NAMESPACE": profile["temporal_namespace"],
        "ACS_SURFACE_TEST_PYTHON": profile["python"],
    })
    started = time.monotonic()
    result = subprocess.run(
        command, cwd=profile["source_root"], env=environment, capture_output=True,
        timeout=900, check=False,
    )
    output = result.stdout + b"\n" + result.stderr
    _no_secret(output, secrets)
    if result.returncode or b" skipped" in output or b" failed" in output:
        raise ProbeUnavailable("scenario tests did not produce complete real evidence")
    operation_id = f"p1-probe-operation:{suffix}"
    message_id = f"p1-probe-message:{suffix}"
    event_id = f"p1-probe-event:{suffix}"
    receipt_id = f"p1-probe-receipt:{suffix}"
    pg_schema = "p1_probe_" + suffix.replace("-", "_")
    with psycopg.connect(profile["postgres_dsn"], autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(pg_schema)))
        ledger.reserve_schema(pg_schema)
        connection.execute(sql.SQL(
            "CREATE TABLE {}.scenario_evidence(scenario_id TEXT PRIMARY KEY,operation_id TEXT,"
            "message_id TEXT,event_id TEXT,receipt_id TEXT,test_digest TEXT,elapsed_ms BIGINT)"
        ).format(sql.Identifier(pg_schema)))
        connection.execute(sql.SQL(
            "INSERT INTO {}.scenario_evidence VALUES (%s,%s,%s,%s,%s,%s,%s)"
        ).format(sql.Identifier(pg_schema)), (
            scenario, operation_id, message_id, event_id, receipt_id,
            _sha(output), int((time.monotonic() - started) * 1000),
        ))
    workflow_id, temporal_run_id = asyncio.run(
        _temporal_marker(profile, operation_id + ":temporal", scenario),
    )
    raw = ledger.root / (scenario + "-pytest.json")
    raw_value = {
        "scenario_id": scenario, "argv": command[1:], "exit_code": result.returncode,
        "stdout_sha256": _sha(result.stdout), "stderr_sha256": _sha(result.stderr),
        "output_sha256": _sha(output), "tests": tests,
    }
    raw.write_bytes(_canonical(raw_value))
    raw.chmod(0o600)
    value = {
        "scenario_id": scenario, "run_id": run_id, "operation_id": operation_id,
        "message_id": message_id, "event_id": event_id, "receipt_id": receipt_id,
        "test_digest": _sha(output), "raw_path": raw.name, "pg_schema": pg_schema,
        "temporal_workflow_id": workflow_id, "temporal_run_id": temporal_run_id,
        "lineage_json": "{}",
        "source_commit": commit, "source_tree": tree, "status": "passed",
        "created_at": datetime.now(UTC).isoformat(),
    }
    ledger.put(value)
    return value


def _read_layer(profile: dict[str, Any], scenario: str, kind: str,
                ledger: ProbeLedger, row: dict[str, Any]) -> dict[str, Any]:
    lineage = json.loads(row["lineage_json"])
    required_lineage = {
        "tenant_id", "command_id", "message_id", "operation_id", "attempt_id",
        "dispatch_id", "event_ids", "receipts", "driver_calls", "node_journal",
    }
    if set(lineage) < required_lineage:
        raise ProbeRejected("marker-only evidence is not an actual Runtime lineage")
    if kind == "postgresql":
        scoped = make_conninfo(
            profile["postgres_dsn"], options=f"-c search_path={row['pg_schema']}",
        )
        with psycopg.connect(scoped) as connection:
            command_row = connection.execute(
                "SELECT command_id FROM command_dedup WHERE command_id=%s",
                (lineage["command_id"],),
            ).fetchone()
            operation_row = connection.execute(
                "SELECT operation_id FROM operations WHERE operation_id=%s",
                (lineage["operation_id"],),
            ).fetchone()
            event_rows = connection.execute(
                "SELECT event_id FROM domain_events WHERE command_id=%s ORDER BY event_id",
                (lineage["command_id"],),
            ).fetchall()
            outbox_row = connection.execute(
                "SELECT operation_id FROM outbox WHERE operation_id=%s",
                (lineage["operation_id"],),
            ).fetchone()
            message_row = connection.execute(
                "SELECT operation_id FROM delivery_messages WHERE message_id=%s",
                (lineage["message_id"],),
            ).fetchone()
            attempt_row = connection.execute(
                "SELECT attempt_id,dispatch_id FROM delivery_attempts WHERE message_id=%s",
                (lineage["message_id"],),
            ).fetchone()
            receipt_rows = connection.execute(
                "SELECT receipt_id,layer FROM delivery_receipts WHERE message_id=%s "
                "ORDER BY observed_at",
                (lineage["message_id"],),
            ).fetchall()
        expected_receipts = [(item["receipt_id"], item["layer"]) for item in lineage["receipts"]]
        if (
            command_row != (lineage["command_id"],)
            or operation_row != (lineage["operation_id"],)
            or [str(item[0]) for item in event_rows] != lineage["event_ids"]
            or outbox_row != (lineage["operation_id"],)
            or message_row != (lineage["operation_id"],)
            or attempt_row != (lineage["attempt_id"], lineage["dispatch_id"])
            or receipt_rows != expected_receipts
        ):
            raise ProbeRejected("PostgreSQL Runtime lineage changed")
        return {"postgresql_readback": True, "lineage_digest": _sha(_canonical(lineage))}
    if kind == "sqlite":
        replay = ledger.get(scenario)
        if replay != row:
            raise ProbeRejected("SQLite scenario journal changed")
        node_path = ledger.root / lineage["node_journal"]
        with sqlite3.connect(node_path) as connection:
            journal = connection.execute(
                "SELECT command_id,message_id FROM journal WHERE operation_id=?",
                (lineage["operation_id"],),
            ).fetchone()
            mailbox = connection.execute(
                "SELECT operation_id FROM mailbox WHERE message_id=?",
                (lineage["message_id"],),
            ).fetchone()
            node_receipts = connection.execute(
                "SELECT receipt_id FROM lifecycle_receipts WHERE operation_id=?",
                (lineage["operation_id"],),
            ).fetchall()
        if (journal != (lineage["command_id"], lineage["message_id"])
                or mailbox != (lineage["operation_id"],) or not node_receipts):
            raise ProbeRejected("SQLite Node lineage changed")
        return {"sqlite_readback": True, "journal_sha256": _sha(node_path.read_bytes()),
                "node_receipt_ids": [item[0] for item in node_receipts]}
    if kind == "temporal":
        async def read():
            adapter = TemporalAdapter(
                profile["temporal_endpoint"], namespace=profile["temporal_namespace"],
            )
            await adapter.connect(start_worker=False)
            try:
                return await adapter.readback(row["temporal_workflow_id"])
            finally:
                await adapter.close()
        value = asyncio.run(read())
        if value.get("status") != "committed":
            raise ProbeRejected("Temporal scenario marker changed")
        return {"temporal_readback": True, "workflow_id": row["temporal_workflow_id"],
                "run_id": row["temporal_run_id"]}
    if kind == "driver":
        raw = ledger.root / row["raw_path"]
        value = json.loads(raw.read_text())
        if (value.get("lineage") != lineage
                or lineage["driver_calls"] != [lineage["operation_id"]]
                or _sha(raw.read_bytes()) != row["test_digest"]):
            raise ProbeRejected("Driver/raw test evidence changed")
        return {"driver_readback": True, "driver_calls": lineage["driver_calls"],
                "raw_sha256": _sha(raw.read_bytes())}
    if kind == "os":
        systemd = subprocess.run(
            ["systemctl", "--user", "show-environment"], capture_output=True,
            timeout=10, check=False,
        )
        if systemd.returncode:
            raise ProbeUnavailable("systemd --user manager is unavailable")
        current_commit = os.environ.get("ACS_GATE_SOURCE_COMMIT")
        current_tree = os.environ.get("ACS_GATE_SOURCE_TREE")
        if not current_commit or not current_tree:
            current_commit, current_tree = _source_identity(Path(profile["source_root"]))
        if (current_commit, current_tree) != (row["source_commit"], row["source_tree"]):
            raise ProbeRejected("source identity changed during scenario evidence")
        return {"os_readback": True, "platform": platform.platform(),
                "systemd_user_exit": systemd.returncode}
    raw = ledger.root / row["raw_path"]
    if _sha(raw.read_bytes()) != row["test_digest"] or not lineage["conflict_rejected"]:
        raise ProbeRejected("command output does not bind the Runtime transaction")
    return {"command_output": True, "test_digest": row["test_digest"],
            "lineage_digest": _sha(_canonical(lineage))}


def _runner_result(profile: dict[str, Any], scenario: str, kind: str,
                   row: dict[str, Any], layer: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(UTC)
    facts = {"layer": layer}
    fields = EVIDENCE_FIELDS[kind]
    if "fault_injection" in fields:
        facts["fault_injected"] = True
    if "source_readback" in fields:
        facts["source_readback_verified"] = True
    if "artifact_readback" in fields:
        facts["artifact_readback_verified"] = True
    if "effect_readback" in fields:
        facts["effect_readback_verified"] = True
    if "recovery_trace" in fields:
        facts["recovery_verified"] = True
    return {
        "schema_version": RESULT_SCHEMA, "status": "passed",
        "run_id": os.environ.get("ACS_GATE_RUN_ID", row["run_id"]),
        "scenario_id": scenario,
        "command_id": os.environ.get("ACS_GATE_COMMAND_ID", f"{scenario}:{kind}"),
        "evidence_kind": os.environ.get("ACS_GATE_EVIDENCE_KIND", kind),
        "source_commit": os.environ.get("ACS_GATE_SOURCE_COMMIT", row["source_commit"]),
        "source_tree": os.environ.get("ACS_GATE_SOURCE_TREE", row["source_tree"]),
        "binding_sha256": os.environ.get("ACS_GATE_BINDING_SHA256", profile["binding_sha256"]),
        "profile": os.environ.get("ACS_GATE_PROFILE", profile["profile"]),
        "machine_id": os.environ.get("ACS_GATE_MACHINE_ID", profile["machine_id"]),
        "node_id": os.environ.get("ACS_GATE_NODE_ID", profile["node_id"]),
        "direction": os.environ.get("ACS_GATE_DIRECTION", profile["direction"]),
        "versions": json.loads(os.environ.get("ACS_GATE_VERSIONS_JSON", json.dumps(profile["versions"]))),
        "observed_at": now.isoformat(),
        "expires_at": os.environ.get("ACS_GATE_EXPIRES_AT", (now + timedelta(minutes=5)).isoformat()),
        "operation_ids": [row["operation_id"], row["temporal_workflow_id"]],
        "message_ids": [row["message_id"]], "event_ids": [row["event_id"]],
        "receipt_ids": [row["receipt_id"]], "observer": "p1-profile-probe",
        "owner": "runtime-domain", "facts": facts,
    }


def execute(
    profile_path: Path, scenario: str, kind: str, output: Path,
    *, fault: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    _safe_name(scenario)
    if scenario not in ScenarioCatalog.TESTS or kind not in KINDS:
        raise ProbeRejected("unknown P1 scenario or evidence kind")
    profile, profile_digest, secrets = _secure_profile(profile_path)
    root = Path(os.environ.get("ACS_GATE_SOURCE_SNAPSHOT", profile["source_root"])).resolve(
        strict=True,
    )
    profile["source_root"] = str(root)
    output = output.resolve(strict=False)
    if output == root or output.is_relative_to(root):
        raise ProbeRejected("probe output must remain outside source")
    commit = os.environ.get("ACS_GATE_SOURCE_COMMIT")
    tree = os.environ.get("ACS_GATE_SOURCE_TREE")
    if not commit or not tree:
        commit, tree = _source_identity(root)
    available = availability(profile, commit)[scenario]
    if not available["available"]:
        raise ProbeUnavailable(available["reason"])
    profile["profile_digest"] = profile_digest
    profile.setdefault("machine_id", "machine-" + _sha(platform.node().encode())[:20])
    profile.setdefault("binding_sha256", _sha(_canonical({
        "profile": profile["profile"], "machine_id": profile["machine_id"],
        "node_id": profile["node_id"], "versions": profile["versions"],
    })))
    ledger = ProbeLedger(output)
    row = _run_tests(profile, scenario, ledger, commit, tree, secrets, fault) \
        if kind == "command_output" else ledger.get(scenario)
    if row is None or row["status"] != "passed":
        raise ProbeUnavailable("scenario command evidence has not completed")
    layer = _read_layer(profile, scenario, kind, ledger, row)
    ledger.read(scenario, kind, layer)
    result = _runner_result(profile, scenario, kind, row, layer)
    _no_secret(_canonical(result), secrets)
    return result


def cleanup(profile_path: Path, output: Path) -> None:
    profile, _digest, _secrets = _secure_profile(profile_path)
    ledger = ProbeLedger(output.resolve(strict=True))
    with closing(ledger._connect()) as connection:
        schemas = {
            row[0] for row in connection.execute("SELECT pg_schema FROM scenario_runs")
        } | {
            row[0] for row in connection.execute("SELECT pg_schema FROM schema_reservations")
        }
    with psycopg.connect(profile["postgres_dsn"], autocommit=True) as connection:
        for schema in schemas:
            connection.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                sql.Identifier(schema),
            ))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--profile", type=Path, required=True)
    run.add_argument("--scenario", required=True)
    run.add_argument("--kind", choices=KINDS, required=True)
    run.add_argument("--output", type=Path, required=True)
    clean = commands.add_parser("cleanup")
    clean.add_argument("--profile", type=Path, required=True)
    clean.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            value = execute(args.profile, args.scenario, args.kind, args.output)
        else:
            cleanup(args.profile, args.output)
            value = {"status": "cleaned"}
        print(json.dumps(value, sort_keys=True, separators=(",", ":")))
        return 0
    except ProbeUnavailable as error:
        print(json.dumps({"status": "not_run", "reason": str(error)}, sort_keys=True))
        return 3
    except Exception as error:  # noqa: BLE001 - bounded command boundary
        print(json.dumps({"status": "blocked", "error": type(error).__name__}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
