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
import tarfile
import tempfile
from collections.abc import Callable
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import psycopg
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

SOURCE_ROOT = Path(__file__).resolve().parents[2]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from runtime.artifacts import ArtifactError, LocalArtifactStore
from runtime.delivery import DeliveryDispatcher, DeliveryService
from runtime.delivery_models import DeliveryPacket, EndpointBindingRequest
from runtime.delivery_node import DeliveryTransportError, LocalNodeEndpoint
from runtime.delivery_temporal import submit_delivery
from runtime.domain import DomainAuthority
from runtime.effects import LocalFileEffectGateway
from runtime.enrollment import EnrollmentAuthority
from runtime.enrollment_models import (
    AttemptRegistration,
    NodeChallengeRequest,
    NodeCommandProof,
    NodeEnrollment,
    RuntimeRegistration,
)
from runtime.errors import (
    AcceptanceGuardFailed,
    EffectUnavailable,
    FencingRejected,
    IdempotencyConflict,
)
from runtime.models import (
    ArtifactRef,
    CommandEnvelope,
    EvidenceBundle,
    EvidenceRecord,
    ExecutionReceipt,
    LeaseRequest,
    TransitionRequest,
    WorkItemState,
)
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
    LINEAGE_BOUND: ClassVar[frozenset[str]] = frozenset({
        "P1-DOMAIN-TRANSACTION", "P1-COMMAND-DEDUP", "P1-INBOX-ACK-LOSS",
        "P1-AUTH-REVOCATION", "P1-CORE-RESTART", "P1-NODE-RESTART",
        "P1-PROVIDER-RESTART", "P1-LEASE-FENCING", "P1-UNCERTAIN-EFFECT",
        "P1-STALE-BASELINE",
    })
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


def _private_json(path: Path, value: dict[str, Any]) -> bytes:
    data = _canonical(value)
    try:
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600,
        )
    except FileExistsError:
        if path.read_bytes() != data:
            raise ProbeRejected("private fault context identity changed") from None
        return data
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return data


def _probe_child_env() -> dict[str, str]:
    environment = {}
    for key in ("PATH", "HOME", "LANG", "LC_ALL", "TZ"):
        value = os.environ.get(key)
        if value is not None:
            environment[key] = value
    environment["PYTHONNOUSERSITE"] = "1"
    if os.environ.get("ACS_GATE_RUNTIME_ROOT") == "/run/acs-p1/runtime":
        reviewed_site = "/run/acs-p1/runtime/site"
        if os.environ.get("PYTHONPATH") != reviewed_site:
            raise ProbeRejected("reviewed runtime site is unavailable to child")
        environment["PYTHONPATH"] = reviewed_site
    return environment


def _core_crash_child(profile_path: Path, context_path: Path, expected_hash: str) -> None:
    profile, _digest, _secrets = _secure_profile(profile_path)
    data = context_path.read_bytes()
    if _sha(data) != expected_hash:
        raise ProbeRejected("Core crash context digest changed")
    context = json.loads(data)
    if set(context) != {"pg_schema", "identity", "endpoint_id", "descriptor"}:
        raise ProbeRejected("Core crash context fields changed")
    schema = context["pg_schema"]
    if not re.fullmatch(r"p1_probe_[0-9a-f]{24}", schema):
        raise ProbeRejected("Core crash schema identity changed")
    authority = DomainAuthority(make_conninfo(
        profile["postgres_dsn"], options=f"-c search_path={schema}",
    ))
    endpoint = SimpleNamespace(descriptor=lambda: context["descriptor"])
    dispatcher = DeliveryDispatcher(DeliveryService(
        authority, {context["endpoint_id"]: endpoint},
    ))
    dispatcher.after_claim = lambda _identity: os._exit(83)
    dispatcher.dispatch(context["identity"])
    raise ProbeRejected("Core crash seam was not reached")


def _core_restart(
    profile: dict[str, Any], ledger: ProbeLedger, pg_schema: str,
    service: DeliveryService, endpoint: LocalNodeEndpoint,
    identity: dict[str, str], message_id: str, operation_id: str,
    node: NodeJournal, driver: FixtureDriver,
) -> tuple[dict[str, Any], dict[str, Any]]:
    context_path = ledger.root / "P1-CORE-RESTART-context.json"
    context = {
        "pg_schema": pg_schema, "identity": identity,
        "endpoint_id": next(iter(service.endpoints)),
        "descriptor": endpoint.descriptor(),
    }
    context_digest = _sha(_private_json(context_path, context))
    proof_path = ledger.root / "P1-CORE-RESTART-crash.json"
    if proof_path.exists():
        proof = json.loads(proof_path.read_text())
        if proof.get("context_digest") != context_digest or proof.get("exit_code") != 83:
            raise ProbeRejected("Core crash proof identity changed")
    else:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "core-crash",
             "--profile", profile["_profile_path"], "--context", str(context_path),
             "--context-sha256", context_digest],
            cwd=ledger.root, env=_probe_child_env(),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            exit_code = process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            raise ProbeRejected("Core crash child did not exit on its bounded seam") from None
        if exit_code != 83 or Path(f"/proc/{process.pid}").exists():
            raise ProbeRejected("Core crash child did not stop at the prepared attempt")
        with service.authority._connect() as connection:
            prepared = connection.execute(
                "SELECT attempt_id,status,finished_at FROM delivery_attempts "
                "WHERE message_id=%s AND ordinal=1", (message_id,),
            ).fetchone()
            inbox_count = connection.execute(
                "SELECT count(*) FROM inbox_messages WHERE message_id=%s",
                (message_id,),
            ).fetchone()[0]
        if (prepared is None or prepared[1:] != ("prepared", None)
                or inbox_count != 0 or node.get_message(message_id) is not None
                or driver.calls):
            raise ProbeRejected("Core crash crossed the native/Node boundary")
        proof = {
            "context_digest": context_digest,
            "child_pid": process.pid, "exit_code": exit_code,
            "prepared_attempt_id": prepared[0], "node_before": 0,
            "driver_before": 0,
        }
        _private_json(proof_path, proof)
    delivered = DeliveryDispatcher(service, worker_id="replacement-core").dispatch(identity)
    if delivered["status"] != "delivered":
        raise ProbeRejected("replacement Core did not resume the prepared attempt")
    with service.authority._connect() as connection:
        attempts = connection.execute(
            "SELECT ordinal,attempt_id,status FROM delivery_attempts WHERE message_id=%s",
            (message_id,),
        ).fetchall()
    if attempts != [(1, proof["prepared_attempt_id"], "delivered")]:
        raise ProbeRejected("replacement Core did not retain the prepared attempt")
    return delivered, proof


def _node_receipts(path: Path, operation_id: str) -> list[list[str]]:
    with sqlite3.connect(path) as connection:
        return [list(item) for item in connection.execute(
            "SELECT receipt_id,layer,evidence_json FROM lifecycle_receipts "
            "WHERE operation_id=? ORDER BY layer", (operation_id,),
        ).fetchall()]


def _node_restart_child(
    profile_path: Path, context_path: Path, expected_hash: str, result_path: Path,
) -> None:
    profile, _digest, _secrets = _secure_profile(profile_path)
    data = context_path.read_bytes()
    if _sha(data) != expected_hash:
        raise ProbeRejected("Node restart context digest changed")
    context = json.loads(data)
    required = {
        "pg_schema", "identity", "endpoint_id", "machine_id", "node_id",
        "old_boot", "new_boot", "node_file", "suffix", "issued_at",
        "old_receipts",
    }
    if set(context) != required or not re.fullmatch(r"p1_probe_[0-9a-f]{24}", context["pg_schema"]):
        raise ProbeRejected("Node restart context fields changed")
    node_path = context_path.parent / context["node_file"]
    if (context["node_file"] != "P1-NODE-RESTART-node.sqlite"
            or not node_path.is_file() or node_path.is_symlink()):
        raise ProbeRejected("Node restart journal path changed")
    authority = DomainAuthority(make_conninfo(
        profile["postgres_dsn"], options=f"-c search_path={context['pg_schema']}",
    ))
    node = NodeJournal(
        node_path, machine_id=context["machine_id"], node_id=context["node_id"],
        boot_incarnation=context["new_boot"],
    )
    driver = FixtureDriver()
    endpoint = LocalNodeEndpoint(node, "local-scope", "local-slot", driver)
    service = DeliveryService(authority, {context["endpoint_id"]: endpoint})
    issued_at = datetime.fromisoformat(context["issued_at"])
    rebind = _domain_command(
        authority, "message.bind", "message", context["endpoint_id"],
        context["suffix"] + ":rebind", issued_at, revision=1,
    )
    service.bind_endpoint(rebind, EndpointBindingRequest(
        scope_id="local-scope", agent_slot_id="local-slot",
        expires_at=rebind.deadline,
    ))
    with authority._connect() as connection:
        connection.execute(
            "UPDATE delivery_messages SET next_attempt_at=clock_timestamp() "
            "WHERE message_id=%s", (context["identity"]["message_id"],),
        )
    delivered = DeliveryDispatcher(service, worker_id="replacement-node-core").dispatch(
        context["identity"],
    )
    receipts = _node_receipts(node_path, context["identity"]["operation_id"])
    if (delivered["status"] != "delivered" or driver.calls
            or receipts != context["old_receipts"]
            or node.get_message(context["identity"]["message_id"]) is None):
        raise ProbeRejected("replacement Node changed the logical Inbox or receipts")
    _private_json(result_path, {
        "context_digest": expected_hash, "child_pid": os.getpid(),
        "new_boot": context["new_boot"], "status": delivered["status"],
        "node_receipt_digest": _sha(_canonical(receipts)),
        "driver_calls": [],
    })


def _node_restart(
    profile: dict[str, Any], ledger: ProbeLedger, pg_schema: str,
    service: DeliveryService, endpoint: LocalNodeEndpoint,
    identity: dict[str, str], suffix: str, issued_at: datetime,
    node: NodeJournal, driver: FixtureDriver,
    fault: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], NodeJournal]:
    context_path = ledger.root / "P1-NODE-RESTART-context.json"
    result_path = ledger.root / "P1-NODE-RESTART-child-result.json"
    proof_path = ledger.root / "P1-NODE-RESTART-proof.json"
    if proof_path.exists():
        proof = json.loads(proof_path.read_text())
        result = json.loads(result_path.read_text())
        if (_sha(context_path.read_bytes()) != proof["context_digest"]
                or _sha(result_path.read_bytes()) != proof["result_digest"]
                or result["child_pid"] != proof["child_pid"]):
            raise ProbeRejected("Node restart proof identity changed")
    elif result_path.exists():
        context = json.loads(context_path.read_text())
        result = json.loads(result_path.read_text())
        context_digest = _sha(context_path.read_bytes())
        with service.authority._connect() as connection:
            current = connection.execute(
                "SELECT state FROM delivery_messages WHERE message_id=%s "
                "AND operation_id=%s", (identity["message_id"], identity["operation_id"]),
            ).fetchone()
        if (
            context["pg_schema"] != pg_schema or context["identity"] != identity
            or context["suffix"] != suffix or context["new_boot"] != node.boot_incarnation
            or result["context_digest"] != context_digest
            or result["new_boot"] != context["new_boot"]
            or result["status"] != "delivered" or result["driver_calls"]
            or Path(f"/proc/{result['child_pid']}").exists()
            or current != ("delivered",)
            or result["node_receipt_digest"] != _sha(_canonical(
                _node_receipts(Path(node._path), identity["operation_id"]),
            ))
        ):
            raise ProbeRejected("Node child result cannot be recovered by readback")
        proof = {
            "context_digest": context_digest,
            "result_digest": _sha(result_path.read_bytes()),
            "child_pid": result["child_pid"], "exit_code": None,
            "recovered_from_readback": True,
            "old_boot": context["old_boot"], "new_boot": context["new_boot"],
            "node_receipt_digest": result["node_receipt_digest"],
        }
        _private_json(proof_path, proof)
    else:
        original = endpoint.deliver

        def lose_ack(*args: Any, **kwargs: Any) -> dict[str, Any]:
            original(*args, **kwargs)
            raise DeliveryTransportError("injected ACK loss before Node process replacement")

        endpoint.deliver = lose_ack
        first = DeliveryDispatcher(service).dispatch(identity)
        endpoint.deliver = original
        with service.authority._connect() as connection:
            inbox_count = connection.execute(
                "SELECT count(*) FROM inbox_messages WHERE message_id=%s",
                (identity["message_id"],),
            ).fetchone()[0]
        if (first["status"] != "retry_wait" or inbox_count != 0
                or node.get_message(identity["message_id"]) is None
                or driver.calls):
            raise ProbeRejected("Node replacement seam did not isolate committed Inbox")
        old_receipts = _node_receipts(Path(node._path), identity["operation_id"])
        context = {
            "pg_schema": pg_schema, "identity": identity,
            "endpoint_id": next(iter(service.endpoints)),
            "machine_id": node.machine_id, "node_id": node.node_id,
            "old_boot": node.boot_incarnation,
            "new_boot": "reboot-" + suffix,
            "node_file": "P1-NODE-RESTART-node.sqlite", "suffix": suffix,
            "issued_at": issued_at.isoformat(), "old_receipts": old_receipts,
        }
        context_digest = _sha(_private_json(context_path, context))
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "node-restart",
             "--profile", profile["_profile_path"], "--context", str(context_path),
             "--context-sha256", context_digest, "--result", str(result_path)],
            cwd=ledger.root, env=_probe_child_env(),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            exit_code = process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            raise ProbeRejected("replacement Node child exceeded its deadline") from None
        if exit_code != 0 or Path(f"/proc/{process.pid}").exists() or not result_path.exists():
            raise ProbeRejected("replacement Node child did not complete bounded recovery")
        result = json.loads(result_path.read_text())
        if (result["context_digest"] != context_digest
                or result["child_pid"] != process.pid or result["status"] != "delivered"
                or result["new_boot"] != context["new_boot"]):
            raise ProbeRejected("replacement Node result identity changed")
        if fault is not None:
            fault("after_node_child_result")
        proof = {
            "context_digest": context_digest,
            "result_digest": _sha(result_path.read_bytes()),
            "child_pid": process.pid, "exit_code": exit_code,
            "recovered_from_readback": False,
            "old_boot": context["old_boot"], "new_boot": context["new_boot"],
            "node_receipt_digest": result["node_receipt_digest"],
        }
        _private_json(proof_path, proof)
    reopened = NodeJournal(
        Path(node._path), machine_id=node.machine_id, node_id=node.node_id,
        boot_incarnation=proof["new_boot"],
    )
    if (proof["old_boot"] == proof["new_boot"]
            or _sha(_canonical(_node_receipts(Path(node._path), identity["operation_id"])))
            != proof["node_receipt_digest"]):
        raise ProbeRejected("replacement Node journal did not retain original receipts")
    return {"status": "delivered"}, proof, reopened


def _provider_worker_child(
    profile_path: Path, context_path: Path, expected_hash: str,
    mode: str, result_path: Path,
) -> None:
    profile, _digest, _secrets = _secure_profile(profile_path)
    data = context_path.read_bytes()
    if _sha(data) != expected_hash or mode not in ("crash", "recover"):
        raise ProbeRejected("Temporal worker context identity changed")
    context = json.loads(data)
    required = {
        "pg_schema", "identity", "endpoint_id", "machine_id", "node_id",
        "boot_incarnation", "node_file", "workflow_id", "run_id", "task_queue",
    }
    if set(context) != required or not re.fullmatch(r"p1_probe_[0-9a-f]{24}", context["pg_schema"]):
        raise ProbeRejected("Temporal worker context fields changed")
    node_path = context_path.parent / context["node_file"]
    if (context["node_file"] != "P1-PROVIDER-RESTART-node.sqlite"
            or not node_path.is_file() or node_path.is_symlink()):
        raise ProbeRejected("Temporal worker Node journal path changed")
    authority = DomainAuthority(make_conninfo(
        profile["postgres_dsn"], options=f"-c search_path={context['pg_schema']}",
    ))
    node = NodeJournal(
        node_path, machine_id=context["machine_id"], node_id=context["node_id"],
        boot_incarnation=context["boot_incarnation"],
    )
    driver = FixtureDriver()
    endpoint = LocalNodeEndpoint(node, "local-scope", "local-slot", driver)
    dispatcher = DeliveryDispatcher(DeliveryService(
        authority, {context["endpoint_id"]: endpoint},
    ), worker_id="temporal-" + mode)
    if mode == "crash":
        dispatcher.after_claim = lambda _identity: os._exit(84)

    async def run() -> None:
        adapter = TemporalAdapter(
            profile["temporal_endpoint"], namespace=profile["temporal_namespace"],
            task_queue=context["task_queue"], delivery_dispatcher=dispatcher,
        )
        await adapter.connect(start_worker=True)
        try:
            if mode == "crash":
                await asyncio.sleep(120)
                raise ProbeRejected("Temporal worker crash seam was not reached")
            handle = adapter.client.get_workflow_handle(
                context["workflow_id"], run_id=context["run_id"],
            )
            result = await asyncio.wait_for(handle.result(), timeout=95)
            receipts = _node_receipts(node_path, context["identity"]["operation_id"])
            if (result.get("status") != "delivered" or driver.calls
                    or node.get_message(context["identity"]["message_id"]) is None):
                raise ProbeRejected("replacement Temporal worker changed delivery outcome")
            _private_json(result_path, {
                "context_digest": expected_hash, "child_pid": os.getpid(),
                "workflow_id": context["workflow_id"], "run_id": context["run_id"],
                "status": result["status"], "node_receipt_digest": _sha(_canonical(receipts)),
                "driver_calls": [],
            })
        finally:
            await adapter.close()

    asyncio.run(run())


def _provider_restart(
    profile: dict[str, Any], ledger: ProbeLedger, pg_schema: str,
    service: DeliveryService, endpoint: LocalNodeEndpoint,
    identity: dict[str, str], suffix: str, node: NodeJournal, driver: FixtureDriver,
    fault: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    queue = "p1-provider-" + suffix

    async def submit() -> tuple[str, str]:
        adapter = TemporalAdapter(
            profile["temporal_endpoint"], namespace=profile["temporal_namespace"],
        )
        await adapter.connect(start_worker=False)
        try:
            handle = await submit_delivery(
                adapter.client, queue, DeliveryDispatcher(service), identity,
            )
            description = await handle.describe()
            return handle.id, description.run_id
        finally:
            await adapter.close()

    workflow_id, run_id = asyncio.run(submit())
    context_path = ledger.root / "P1-PROVIDER-RESTART-context.json"
    crash_path = ledger.root / "P1-PROVIDER-RESTART-crash.json"
    result_path = ledger.root / "P1-PROVIDER-RESTART-child-result.json"
    proof_path = ledger.root / "P1-PROVIDER-RESTART-proof.json"
    context = {
        "pg_schema": pg_schema, "identity": identity,
        "endpoint_id": next(iter(service.endpoints)),
        "machine_id": node.machine_id, "node_id": node.node_id,
        "boot_incarnation": node.boot_incarnation,
        "node_file": "P1-PROVIDER-RESTART-node.sqlite",
        "workflow_id": workflow_id, "run_id": run_id, "task_queue": queue,
    }
    context_digest = _sha(_private_json(context_path, context))
    if proof_path.exists():
        proof = json.loads(proof_path.read_text())
        if (proof["context_digest"] != context_digest
                or proof["result_digest"] != _sha(result_path.read_bytes())
                or proof["crash_digest"] != _sha(crash_path.read_bytes())):
            raise ProbeRejected("Temporal worker restart proof identity changed")
        return {"status": "delivered"}, proof, workflow_id, run_id

    if not crash_path.exists():
        with service.authority._connect() as connection:
            prior_attempt = connection.execute(
                "SELECT status FROM delivery_attempts WHERE message_id=%s AND ordinal=1",
                (identity["message_id"],),
            ).fetchone()
        if prior_attempt is not None:
            raise ProbeUnavailable("Temporal crash exit evidence is missing; recovery fenced")
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "provider-worker",
             "--mode", "crash", "--profile", profile["_profile_path"],
             "--context", str(context_path), "--context-sha256", context_digest,
             "--result", str(result_path)],
            cwd=ledger.root, env=_probe_child_env(),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            exit_code = process.wait(timeout=45)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            raise ProbeRejected("first Temporal worker did not reach crash seam") from None
        with service.authority._connect() as connection:
            prepared = connection.execute(
                "SELECT attempt_id,status,finished_at FROM delivery_attempts "
                "WHERE message_id=%s AND ordinal=1", (identity["message_id"],),
            ).fetchone()
            inbox_count = connection.execute(
                "SELECT count(*) FROM inbox_messages WHERE message_id=%s",
                (identity["message_id"],),
            ).fetchone()[0]
        if (exit_code != 84 or Path(f"/proc/{process.pid}").exists()
                or prepared is None or prepared[1:] != ("prepared", None)
                or inbox_count != 0 or node.get_message(identity["message_id"]) is not None
                or driver.calls):
            raise ProbeRejected("first Temporal worker crossed Node/native boundary")
        _private_json(crash_path, {
            "context_digest": context_digest, "child_pid": process.pid,
            "exit_code": exit_code, "prepared_attempt_id": prepared[0],
            "node_before": 0, "driver_before": 0,
        })
        if fault is not None:
            fault("after_provider_crash_record")
    crash = json.loads(crash_path.read_text())
    if (crash["context_digest"] != context_digest or crash["exit_code"] != 84
            or Path(f"/proc/{crash['child_pid']}").exists()):
        raise ProbeRejected("first Temporal worker crash record changed")
    recovery_exit = None
    if not result_path.exists():
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "provider-worker",
             "--mode", "recover", "--profile", profile["_profile_path"],
             "--context", str(context_path), "--context-sha256", context_digest,
             "--result", str(result_path)],
            cwd=ledger.root, env=_probe_child_env(),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            exit_code = process.wait(timeout=110)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            raise ProbeRejected("replacement Temporal worker exceeded deadline") from None
        if exit_code != 0 or Path(f"/proc/{process.pid}").exists():
            raise ProbeRejected("replacement Temporal worker did not stop cleanly")
        recovery_exit = exit_code
    result = json.loads(result_path.read_text())
    if (result["context_digest"] != context_digest or result["status"] != "delivered"
            or result["workflow_id"] != workflow_id or result["run_id"] != run_id
            or result["driver_calls"] or Path(f"/proc/{result['child_pid']}").exists()
            or result["node_receipt_digest"] != _sha(_canonical(
                _node_receipts(Path(node._path), identity["operation_id"]),
            ))):
        raise ProbeRejected("replacement Temporal worker readback changed")
    with service.authority._connect() as connection:
        attempts = connection.execute(
            "SELECT ordinal,attempt_id,status FROM delivery_attempts WHERE message_id=%s",
            (identity["message_id"],),
        ).fetchall()
        message_state = connection.execute(
            "SELECT state FROM delivery_messages WHERE message_id=%s",
            (identity["message_id"],),
        ).fetchone()
    if (attempts != [(1, crash["prepared_attempt_id"], "delivered")]
            or message_state != ("delivered",)):
        raise ProbeRejected("Temporal retry did not preserve original prepared attempt")
    if fault is not None:
        fault("after_provider_child_result")
    proof = {
        "context_digest": context_digest,
        "crash_digest": _sha(crash_path.read_bytes()),
        "result_digest": _sha(result_path.read_bytes()),
        "crash_pid": crash["child_pid"], "crash_exit": 84,
        "recovery_pid": result["child_pid"], "recovery_exit": recovery_exit,
        "recovered_from_readback": recovery_exit is None,
        "prepared_attempt_id": crash["prepared_attempt_id"],
        "workflow_id": workflow_id, "run_id": run_id,
        "node_receipt_digest": result["node_receipt_digest"],
    }
    _private_json(proof_path, proof)
    return {"status": "delivered"}, proof, workflow_id, run_id


def _register_lease_execution(
    authority: DomainAuthority, node: NodeJournal, work_id: str,
    commit: str, tree: str, suffix: str, issued_at: datetime,
    *, execution_attempt_id: str | None = None,
    artifact_store: LocalArtifactStore | None = None,
) -> tuple[dict[str, Any], DomainAuthority, Callable[[CommandEnvelope, Any, str], NodeCommandProof]]:
    node_id = node.node_id
    runtime_id = "lease-runtime-" + suffix
    attempt_id = execution_attempt_id or "lease-attempt-" + suffix
    operator = DomainAuthority(authority._dsn, context=replace(
        authority.context,
        principal_ref="p1-enrollment-operator:" + suffix,
        grant_ref="grant:p1-enrollment-operator:" + suffix,
    ))
    observer = DomainAuthority(authority._dsn, context=replace(
        authority.context,
        principal_ref="p1-node-observer:" + suffix,
        grant_ref="grant:p1-node-observer:" + suffix,
    ), artifact_store=artifact_store)
    operator.bootstrap_local_grant(("enrollment.manage", "work_item.read"))
    observer.bootstrap_local_grant((
        "runtime.register", "attempt.register", "execution.record", "work_item.read",
    ))
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    ).hex()
    enroll = _domain_command(
        operator, "node.enroll", "node", node_id, suffix + ":node-enroll", issued_at,
    )
    operator.enroll_node(enroll, NodeEnrollment(
        scope_id="local-scope", agent_slot_id="local-slot",
        observer_grant_ref=observer.context.grant_ref,
        machine_id=node.machine_id, boot_incarnation=node.boot_incarnation,
        public_key=public, expires_at=issued_at + timedelta(hours=1),
    ))

    def signed(command: CommandEnvelope, request: Any, purpose: str) -> NodeCommandProof:
        field = "receipt" if purpose == "receipt" else "request"
        input_value = {field: request.model_dump(mode="json")}
        challenge_command = _domain_command(
            observer, "node.challenge", "node", node_id,
            suffix + ":challenge:" + purpose, issued_at, revision=1,
        )
        challenge = observer.challenge_node(
            challenge_command,
            NodeChallengeRequest(
                purpose=command.command_type,
                purpose_command_id=command.command_id,
                purpose_hash=EnrollmentAuthority.signing_hash(command, input_value),
                ttl_seconds=300,
            ),
        )
        return NodeCommandProof(
            challenge_id=challenge.challenge_id,
            signature=private.sign(bytes.fromhex(challenge.message_hex)).hex(),
        )

    runtime_command = _domain_command(
        observer, "runtime.register", "runtime", runtime_id,
        suffix + ":runtime-register", issued_at,
    )
    runtime_request = RuntimeRegistration(
        node_id=node_id, node_binding_revision=1,
        provider="p1-local-lease-probe",
        producer_grant_ref=authority.context.grant_ref,
        expires_at=issued_at + timedelta(minutes=45),
    )
    observer.register_runtime(
        runtime_command, runtime_request, signed(runtime_command, runtime_request, "runtime"),
    )
    with observer._connect() as connection:
        observed_started_at = connection.execute("SELECT clock_timestamp()").fetchone()[0]
    attempt_command = _domain_command(
        observer, "attempt.register", "attempt", attempt_id,
        suffix + ":attempt-register", issued_at,
    )
    attempt_request = AttemptRegistration(
        runtime_id=runtime_id, work_item_id=work_id,
        expected_work_item_revision=0, source_baseline=commit,
        source_commit=commit, source_tree=tree,
        candidate_ref="p1-candidate-" + suffix,
        observed_started_at=observed_started_at,
    )
    enrolled_attempt = observer.register_attempt(
        attempt_command, attempt_request, signed(attempt_command, attempt_request, "attempt"),
    )
    owner = {
        "node_id": node_id, "runtime_id": runtime_id, "attempt_id": attempt_id,
        "operator_grant_ref": operator.context.grant_ref,
        "observer_grant_ref": observer.context.grant_ref,
        "execution_binding": enrolled_attempt.binding,
    }
    return owner, observer, signed


def _register_replacement_lease_owner(
    authority: DomainAuthority, observer: DomainAuthority,
    signed: Callable[[CommandEnvelope, Any, str], NodeCommandProof],
    node: NodeJournal, work_id: str, commit: str, tree: str,
    suffix: str, issued_at: datetime,
) -> tuple[DomainAuthority, dict[str, str]]:
    producer = DomainAuthority(authority._dsn, context=replace(
        authority.context,
        principal_ref="p1-lease-replacement:" + suffix,
        grant_ref="grant:p1-lease-replacement:" + suffix,
    ))
    producer.bootstrap_local_grant((
        "lease.acquire", "lease.release", "lease.inspect",
        "effect.write", "effect.read", "work_item.read",
    ))
    runtime_id = "lease-replacement-runtime-" + suffix
    attempt_id = "lease-replacement-attempt-" + suffix
    runtime_command = _domain_command(
        observer, "runtime.register", "runtime", runtime_id,
        suffix + ":replacement-runtime-register", issued_at,
    )
    runtime_request = RuntimeRegistration(
        node_id=node.node_id, node_binding_revision=1,
        provider="p1-local-lease-replacement",
        producer_grant_ref=producer.context.grant_ref,
        expires_at=issued_at + timedelta(minutes=45),
    )
    observer.register_runtime(
        runtime_command, runtime_request,
        signed(runtime_command, runtime_request, "replacement-runtime"),
    )
    with observer._connect() as connection:
        observed_started_at = connection.execute("SELECT clock_timestamp()").fetchone()[0]
    attempt_command = _domain_command(
        observer, "attempt.register", "attempt", attempt_id,
        suffix + ":replacement-attempt-register", issued_at,
    )
    attempt_request = AttemptRegistration(
        runtime_id=runtime_id, work_item_id=work_id,
        expected_work_item_revision=0, source_baseline=commit,
        source_commit=commit, source_tree=tree,
        candidate_ref="p1-candidate-replacement-" + suffix,
        observed_started_at=observed_started_at,
    )
    observer.register_attempt(
        attempt_command, attempt_request,
        signed(attempt_command, attempt_request, "replacement-attempt"),
    )
    return producer, {"runtime_id": runtime_id, "attempt_id": attempt_id,
                      "grant_ref": producer.context.grant_ref,
                      "principal_ref": producer.context.principal_ref}



def _effect_marker_digest(effect_root: Path) -> str:
    marker_root = effect_root / LocalFileEffectGateway.MARKER_DIR
    entries = []
    for path in sorted(marker_root.rglob("*")):
        if path.is_file() and path.name != "lock":
            info = path.stat(follow_symlinks=False)
            entries.append([
                str(path.relative_to(marker_root)), _sha(path.read_bytes()),
                info.st_dev, info.st_ino, info.st_uid,
                info.st_mode & 0o777, info.st_nlink,
            ])
    return _sha(_canonical(entries))


def _lease_fencing(
    authority: DomainAuthority, node: NodeJournal, ledger: ProbeLedger,
    work_id: str, delivery_operation_id: str,
    commit: str, tree: str, suffix: str, issued_at: datetime,
) -> dict[str, Any]:
    proof_path = ledger.root / "P1-LEASE-FENCING-proof.json"
    if proof_path.exists():
        proof = json.loads(proof_path.read_text())
        if proof.get("delivery_operation_id") != delivery_operation_id:
            raise ProbeRejected("Lease fence proof belongs to another delivery operation")
        return proof
    owner, node_observer, sign_node_command = _register_lease_execution(
        authority, node, work_id, commit, tree, suffix, issued_at,
    )
    resource_id = "lease-resource-" + suffix
    acquire_command = _domain_command(
        authority, "lease.acquire", "lease", resource_id, suffix + ":lease-acquire",
        issued_at,
    )
    request = LeaseRequest(
        resource_id=resource_id, owner_attempt_id=owner["attempt_id"],
        owner_runtime_id=owner["runtime_id"], grant_ref=authority.context.grant_ref,
        authority_incarnation=authority.context.authority_incarnation,
        scope_id="local-scope", work_item_id=work_id, ttl_seconds=300,
    )
    lease = authority.leases.acquire_lease(acquire_command, request)
    args = {
        "lease_id": lease["lease_id"], "resource_id": resource_id,
        "generation": lease["generation"], "fencing_token": lease["fencing_token"],
        "caller": authority.context, "attempt_id": owner["attempt_id"],
        "runtime_id": owner["runtime_id"], "scope_id": "local-scope",
        "grant_ref": authority.context.grant_ref,
        "authority_incarnation": authority.context.authority_incarnation,
    }
    effect_root = ledger.root / "P1-LEASE-FENCING-effects"
    effect_operation_id = "file-effect:" + delivery_operation_id
    payload = ("P1 lease file effect for " + delivery_operation_id).encode()
    with LocalFileEffectGateway(
        authority.leases, effect_root, scope_id="local-scope",
        resource_paths={resource_id: "output.txt"},
    ) as writer:
        result = writer.write(
            **args, relative_path="output.txt", payload=payload,
            operation_id=effect_operation_id,
        )
        release_command = _domain_command(
            authority, "lease.release", "lease", resource_id,
            suffix + ":lease-release", issued_at,
        )
        released = authority.leases.release_lease(
            release_command, lease["lease_id"], resource_id,
            lease["generation"], lease["fencing_token"],
        )
        try:
            writer.write(
                **args, relative_path="output.txt", payload=b"forbidden stale owner write",
                operation_id="stale:" + delivery_operation_id,
            )
        except FencingRejected:
            stale_rejected = True
        else:
            stale_rejected = False
    reader = DomainAuthority(authority._dsn, context=replace(
        authority.context,
        principal_ref="p1-effect-reader:" + suffix,
        grant_ref="grant:p1-effect-reader:" + suffix,
    ))
    reader.bootstrap_local_grant(("effect.read",))
    with LocalFileEffectGateway(
        reader.leases, effect_root, scope_id="local-scope",
        resource_paths={resource_id: "output.txt"},
    ) as observer:
        historical = observer.historical_readback(
            lease["lease_id"], resource_id, lease["generation"],
            lease["fencing_token"], "output.txt",
            caller=reader.context, scope_id="local-scope",
            grant_ref=reader.context.grant_ref,
            authority_incarnation=reader.context.authority_incarnation,
            expected_operation_id=effect_operation_id,
        )
    output = effect_root / "output.txt"
    if (released["status"] != "released" or not stale_rejected
            or historical["status"] != "verified"
            or historical["sha256"] != result["sha256"]
            or historical["completion_state"] != "completed"
            or not historical["completion_sha256"]
            or output.read_bytes() != payload):
        raise ProbeRejected("released Lease did not fence stale writer and retain file effect")
    replacement, next_owner = _register_replacement_lease_owner(
        authority, node_observer, sign_node_command, node,
        work_id, commit, tree, suffix, issued_at,
    )
    acquire_replacement = _domain_command(
        replacement, "lease.acquire", "lease", resource_id,
        suffix + ":replacement-lease-acquire", issued_at,
    )
    replacement_request = LeaseRequest(
        resource_id=resource_id, owner_attempt_id=next_owner["attempt_id"],
        owner_runtime_id=next_owner["runtime_id"],
        grant_ref=replacement.context.grant_ref,
        authority_incarnation=replacement.context.authority_incarnation,
        scope_id="local-scope", work_item_id=work_id, ttl_seconds=300,
    )
    next_lease = replacement.leases.acquire_lease(
        acquire_replacement, replacement_request,
    )
    if (next_lease["generation"] != lease["generation"] + 1
            or next_owner["attempt_id"] == owner["attempt_id"]
            or next_owner["grant_ref"] == authority.context.grant_ref):
        raise ProbeRejected("replacement owner did not acquire the next Lease generation")
    next_args = {
        "lease_id": next_lease["lease_id"], "resource_id": resource_id,
        "generation": next_lease["generation"],
        "fencing_token": next_lease["fencing_token"],
        "caller": replacement.context, "attempt_id": next_owner["attempt_id"],
        "runtime_id": next_owner["runtime_id"], "scope_id": "local-scope",
        "grant_ref": replacement.context.grant_ref,
        "authority_incarnation": replacement.context.authority_incarnation,
    }
    next_effect_operation_id = "file-effect-replacement:" + delivery_operation_id
    next_payload = ("P1 replacement lease file effect for " + delivery_operation_id).encode()
    with LocalFileEffectGateway(
        replacement.leases, effect_root, scope_id="local-scope",
        resource_paths={resource_id: "output.txt"},
    ) as next_writer:
        next_effect = next_writer.write(
            **next_args, relative_path="output.txt", payload=next_payload,
            operation_id=next_effect_operation_id,
        )
    with LocalFileEffectGateway(
        reader.leases, effect_root, scope_id="local-scope",
        resource_paths={resource_id: "output.txt"},
    ) as pre_late_observer:
        pre_late_readback = pre_late_observer.historical_readback(
            next_lease["lease_id"], resource_id, next_lease["generation"],
            next_lease["fencing_token"], "output.txt",
            caller=reader.context, scope_id="local-scope",
            grant_ref=reader.context.grant_ref,
            authority_incarnation=reader.context.authority_incarnation,
            expected_operation_id=next_effect_operation_id,
        )
    if (pre_late_readback["status"] != "verified"
            or pre_late_readback["sha256"] != next_effect["sha256"]
            or pre_late_readback["completion_state"] != "completed"
            or not pre_late_readback["completion_sha256"]
            or output.read_bytes() != next_payload):
        raise ProbeRejected("replacement owner effect was not independently verified before late write")

    def effect_snapshot() -> dict[str, Any]:
        info = output.stat(follow_symlinks=False)
        with authority._connect() as connection:
            lease_rows = connection.execute(
                "SELECT lease_id,resource_id,generation,fencing_token,status,"
                "owner_attempt_id,owner_runtime_id,grant_ref,command_id,scope_id,"
                "authority_incarnation FROM leases "
                "WHERE tenant_id=%s AND resource_id=%s ORDER BY generation",
                (authority.tenant_id, resource_id),
            ).fetchall()
        if len(lease_rows) != 2:
            raise ProbeRejected("replacement Lease rows are incomplete")
        return {
            "file_sha256": _sha(output.read_bytes()),
            "file_identity": [info.st_dev, info.st_ino, info.st_uid,
                              info.st_mode & 0o777, info.st_nlink],
            "marker_sha256": _effect_marker_digest(effect_root),
            "pg_lease_identity_sha256": _sha(_canonical([list(item) for item in lease_rows])),
        }

    before_late = effect_snapshot()
    with LocalFileEffectGateway(
        authority.leases, effect_root, scope_id="local-scope",
        resource_paths={resource_id: "output.txt"},
    ) as late_writer:
        try:
            late_writer.write(
                **args, relative_path="output.txt", payload=b"late old owner overwrite",
                operation_id="late-old-owner:" + delivery_operation_id,
            )
        except FencingRejected:
            late_old_owner_rejected = True
        else:
            late_old_owner_rejected = False
    after_late = effect_snapshot()
    if not late_old_owner_rejected or before_late != after_late:
        raise ProbeRejected("old owner changed replacement file, marker or PG Lease")
    release_replacement = _domain_command(
        replacement, "lease.release", "lease", resource_id,
        suffix + ":replacement-lease-release", issued_at,
    )
    next_released = replacement.leases.release_lease(
        release_replacement, next_lease["lease_id"], resource_id,
        next_lease["generation"], next_lease["fencing_token"],
    )
    with LocalFileEffectGateway(
        reader.leases, effect_root, scope_id="local-scope",
        resource_paths={resource_id: "output.txt"},
    ) as next_observer:
        next_historical = next_observer.historical_readback(
            next_lease["lease_id"], resource_id, next_lease["generation"],
            next_lease["fencing_token"], "output.txt",
            caller=reader.context, scope_id="local-scope",
            grant_ref=reader.context.grant_ref,
            authority_incarnation=reader.context.authority_incarnation,
            expected_operation_id=next_effect_operation_id,
        )
    if (next_released["status"] != "released"
            or next_historical["status"] != "verified"
            or next_historical["sha256"] != pre_late_readback["sha256"]
            or next_historical["intent_sha256"] != pre_late_readback["intent_sha256"]
            or next_historical["completion_sha256"] != pre_late_readback["completion_sha256"]
            or next_historical["sha256"] != next_effect["sha256"]
            or next_historical["completion_state"] != "completed"
            or not next_historical["completion_sha256"]
            or output.read_bytes() != next_payload):
        raise ProbeRejected("replacement Lease did not fence late old owner and commit new effect")
    output_stat = output.stat(follow_symlinks=False)
    with authority._connect() as connection:
        lease_events = connection.execute(
            "SELECT command_id,event_id,canonical_hash FROM domain_events "
            "WHERE command_id IN (%s,%s,%s,%s) ORDER BY event_id",
            (acquire_command.command_id, release_command.command_id,
             acquire_replacement.command_id, release_replacement.command_id),
        ).fetchall()
        lease_dedup = connection.execute(
            "SELECT command_id,canonical_hash FROM command_dedup "
            "WHERE command_id IN (%s,%s,%s,%s) ORDER BY command_id",
            (acquire_command.command_id, release_command.command_id,
             acquire_replacement.command_id, release_replacement.command_id),
        ).fetchall()
    if len(lease_events) != 4 or len(lease_dedup) != 4:
        raise ProbeRejected("two-owner Lease Domain journal is incomplete")
    proof = {
        "delivery_operation_id": delivery_operation_id,
        "work_item_id": work_id, "source_commit": commit, "source_tree": tree,
        "node_id": node.node_id, "node_boot": node.boot_incarnation,
        "machine_id": node.machine_id,
        "runtime_id": owner["runtime_id"], "attempt_id": owner["attempt_id"],
        "acquire_command_id": acquire_command.command_id,
        "acquire_operation_id": lease["operation_id"],
        "release_command_id": release_command.command_id,
        "release_operation_id": released["operation_id"],
        "lease_id": lease["lease_id"], "resource_id": resource_id,
        "generation": lease["generation"],
        "fencing_token_sha256": _sha(lease["fencing_token"].encode()),
        "original_effect_operation_id": effect_operation_id,
        "original_effect_sha256": result["sha256"],
        "original_effect_intent_sha256": historical["intent_sha256"],
        "original_effect_completion_sha256": historical["completion_sha256"],
        "effect_operation_id": next_effect_operation_id,
        "effect_sha256": next_effect["sha256"],
        "effect_size": len(next_payload),
        "effect_file_identity": [output_stat.st_dev, output_stat.st_ino,
                                 output_stat.st_uid, output_stat.st_mode & 0o777,
                                 output_stat.st_nlink],
        "effect_intent_sha256": next_historical["intent_sha256"],
        "effect_completion_sha256": next_historical["completion_sha256"],
        "lease_events": [
            {"command_id": item[0], "event_id": str(item[1]),
             "canonical_hash": item[2]} for item in lease_events
        ],
        "lease_dedup": [
            {"command_id": item[0], "canonical_hash": item[1]}
            for item in lease_dedup
        ],
        "historical_readback": next_historical["status"],
        "original_historical_readback": historical["status"],
        "stale_fence_rejected": stale_rejected,
        "late_old_owner_rejected": late_old_owner_rejected,
        "replacement_readback_before_late": pre_late_readback["status"] == "verified",
        "pre_late_snapshot": before_late,
        "post_late_snapshot": after_late,
        "replacement_runtime_id": next_owner["runtime_id"],
        "replacement_attempt_id": next_owner["attempt_id"],
        "replacement_producer_grant_ref": next_owner["grant_ref"],
        "replacement_producer_principal_ref": next_owner["principal_ref"],
        "replacement_lease_id": next_lease["lease_id"],
        "replacement_generation": next_lease["generation"],
        "replacement_fencing_token_sha256": _sha(next_lease["fencing_token"].encode()),
        "replacement_acquire_command_id": acquire_replacement.command_id,
        "replacement_acquire_operation_id": next_lease["operation_id"],
        "replacement_release_command_id": release_replacement.command_id,
        "replacement_release_operation_id": next_released["operation_id"],
        "reader_grant_ref": reader.context.grant_ref,
        "reader_principal_ref": reader.context.principal_ref,
        "producer_grant_ref": authority.context.grant_ref,
    }
    _private_json(proof_path, proof)
    return proof


def _uncertain_effect(
    authority: DomainAuthority, node: NodeJournal, ledger: ProbeLedger,
    work_id: str, message_id: str, delivery_operation_id: str,
    commit: str, tree: str, suffix: str, issued_at: datetime,
) -> dict[str, Any]:
    proof_path = ledger.root / "P1-UNCERTAIN-EFFECT-proof.json"
    if proof_path.exists():
        proof = json.loads(proof_path.read_text())
        if (proof.get("delivery_operation_id") != delivery_operation_id
                or proof.get("message_id") != message_id):
            raise ProbeRejected("uncertain Effect proof belongs to another delivery")
        return proof
    with authority._connect() as connection:
        delivery_attempts = connection.execute(
            "SELECT attempt_id,dispatch_id,status FROM delivery_attempts "
            "WHERE message_id=%s ORDER BY ordinal", (message_id,),
        ).fetchall()
    if len(delivery_attempts) != 1 or delivery_attempts[0][2] != "delivered":
        raise ProbeRejected("uncertain Effect must bind one delivered Attempt")
    delivery_attempt_id, dispatch_id, _ = delivery_attempts[0]
    payload = ("P1 uncertain file effect for " + delivery_operation_id).encode()
    cas_root = ledger.root / "P1-UNCERTAIN-EFFECT-cas"
    effect_root = ledger.root / "P1-UNCERTAIN-EFFECT-effects"
    resource_id = "uncertain-resource-" + suffix
    effect_id = "uncertain-effect-" + suffix
    operation_id = "file-effect:" + delivery_operation_id
    with LocalArtifactStore(cas_root) as store:
        producer = DomainAuthority(
            authority._dsn, context=authority.context, artifact_store=store,
        )
        producer.bootstrap_local_grant((
            "work_item.create", "delivery.manage", "message.send", "message.read",
            "runtime.invoke", "lease.acquire", "lease.release", "lease.inspect",
            "effect.write", "effect.read", "effect.register", "evidence.record",
            "work_item.read",
        ))
        owner, observer, signed = _register_lease_execution(
            producer, node, work_id, commit, tree, suffix, issued_at,
            execution_attempt_id=delivery_attempt_id, artifact_store=store,
        )
        binding = owner["execution_binding"]
        if (binding["attempt_id"] != delivery_attempt_id
                or binding["work_item_id"] != work_id
                or binding["source_commit"] != commit
                or binding["source_tree"] != tree):
            raise ProbeRejected("signed Effect execution differs from Delivery Attempt")
        output_ref = store.put_bytes(payload, kind="output")
        readback_ref = store.put_bytes(
            ("independent source readback:" + delivery_operation_id).encode(),
            kind="readback",
        )
        observed_at = datetime.now(UTC)
        receipt = ExecutionReceipt(
            receipt_id="uncertain-execution-receipt-" + suffix,
            work_item_id=work_id, attempt_id=delivery_attempt_id,
            runtime_id=owner["runtime_id"], provider=binding["provider"],
            command_id=binding["execution_command_id"],
            operation_id=binding["execution_operation_id"],
            event_id=binding["execution_event_id"],
            source_baseline=commit, candidate_ref=binding["candidate_ref"],
            source_commit=commit, source_tree=tree,
            test_commands=("P1-UNCERTAIN-EFFECT fixed local execution",),
            test_exit_codes=(0,), test_exit_code=0,
            os="linux", toolchain="P1 local delivery and file Effect Gateway",
            artifact_refs=(output_ref,), readback_refs=(readback_ref,),
            source_sync="committed-private-probe-source",
            status="succeeded", observed_at=observed_at,
        )
        receipt_command = _domain_command(
            observer, "execution.record", "work_item", work_id,
            suffix + ":effect-execution-receipt", issued_at,
        )
        observer.record_execution_receipt(
            receipt_command, receipt,
            node_proof=signed(receipt_command, receipt, "receipt"),
        )
        evidence_id = "uncertain-evidence-" + suffix
        bundle = EvidenceBundle(
            evidence_id=evidence_id, work_item_id=work_id,
            source_baseline=commit, candidate_ref=binding["candidate_ref"],
            producer_ref=producer.context.principal_ref,
            observer_ref=observer.context.principal_ref,
            source_class="directly_verified", evidence_state="complete",
            execution_receipt=receipt, artifact_refs=(output_ref,),
            readback_refs=(readback_ref,), command_id=receipt.command_id,
            operation_id=receipt.operation_id, event_id=receipt.event_id,
            observed_at=observed_at,
        )
        evidence = EvidenceRecord(
            evidence_id=evidence_id, work_item_id=work_id,
            observer_ref=observer.context.principal_ref,
            source_class="directly_verified", baseline_ref=commit,
            artifact_sha256=output_ref.sha256,
            summary="Signed same-attempt local output and independent CAS readback",
            bundle_ref=evidence_id, candidate_ref=binding["candidate_ref"],
            execution_receipt_ref=receipt.receipt_id,
            evidence_state="complete", producer_ref=producer.context.principal_ref,
            attempt_id=delivery_attempt_id, test_exit_code=0,
            artifact_refs=(output_ref,), readback_refs=(readback_ref,),
        )
        evidence_command = _domain_command(
            producer, "evidence.record", "work_item", work_id,
            suffix + ":effect-evidence", issued_at,
        )
        producer.record_evidence(evidence_command, evidence, bundle)
        reviewer = DomainAuthority(authority._dsn, context=replace(
            authority.context, principal_ref="p1-effect-reviewer:" + suffix,
            grant_ref="grant:p1-effect-reviewer:" + suffix,
        ), artifact_store=store)
        finalizer = DomainAuthority(authority._dsn, context=replace(
            authority.context, principal_ref="p1-effect-finalizer:" + suffix,
            grant_ref="grant:p1-effect-finalizer:" + suffix,
        ), artifact_store=store)
        reviewer.bootstrap_local_grant(("review.record", "work_item.read"))
        finalizer.bootstrap_local_grant((
            "review.assign", "work_item.transition", "acceptance.finalize",
            "effect.read", "effect.register", "work_item.read",
        ))
        review_id = "uncertain-review-" + suffix
        assign_command = _domain_command(
            finalizer, "review.assign", "work_item", work_id,
            suffix + ":effect-review-assign", issued_at,
        )
        finalizer.assign_reviewer(
            assign_command, work_id, reviewer.context.principal_ref,
            reviewer.context.grant_ref,
        )
        review_command = _domain_command(
            reviewer, "review.record", "work_item", work_id,
            suffix + ":effect-review", issued_at,
        )
        reviewer.record_review(
            review_command, review_id, work_id, "pass", evidence_id, commit,
        )
        ready_command = _domain_command(
            finalizer, "work_item.transition", "work_item", work_id,
            suffix + ":effect-ready", issued_at,
        )
        ready = finalizer.transition_work_item(
            ready_command, TransitionRequest(
                to_state=WorkItemState.ACCEPTANCE_READY,
                evidence_refs=(evidence_id,), review_ref=review_id,
            ),
        )
        if ready.revision != 1:
            raise ProbeRejected("Effect candidate did not reach ready revision")
        acquire_command = _domain_command(
            producer, "lease.acquire", "lease", resource_id,
            suffix + ":uncertain-lease-acquire", issued_at, revision=1,
        )
        lease = producer.leases.acquire_lease(
            acquire_command, LeaseRequest(
                resource_id=resource_id, owner_attempt_id=delivery_attempt_id,
                owner_runtime_id=owner["runtime_id"],
                grant_ref=producer.context.grant_ref,
                authority_incarnation=producer.context.authority_incarnation,
                scope_id="local-scope", work_item_id=work_id, ttl_seconds=300,
            ),
        )
        args = {
            "lease_id": lease["lease_id"], "resource_id": resource_id,
            "generation": lease["generation"], "fencing_token": lease["fencing_token"],
            "caller": producer.context, "attempt_id": delivery_attempt_id,
            "runtime_id": owner["runtime_id"], "scope_id": "local-scope",
            "grant_ref": producer.context.grant_ref,
            "authority_incarnation": producer.context.authority_incarnation,
        }
        with LocalFileEffectGateway(
            producer.leases, effect_root, scope_id="local-scope",
            resource_paths={resource_id: "output.txt"},
        ) as writer:
            producer._effect_registration_gateway = writer
            original_persist = writer._persist
            original_record = writer._record
            target_writes = 0
            crash_seen = False

            def counted_persist(parent, name, body, check, **kwargs):
                nonlocal target_writes
                if name == "output.txt":
                    target_writes += 1
                return original_persist(parent, name, body, check, **kwargs)

            def interrupt_completion(parent, name, body, check, **kwargs):
                nonlocal crash_seen
                if name.endswith(".completed") and not crash_seen:
                    crash_seen = True
                    raise OSError("injected completion marker crash after target fsync")
                return original_record(parent, name, body, check, **kwargs)

            writer._persist = counted_persist
            writer._record = interrupt_completion
            try:
                try:
                    writer.write(
                        **args, relative_path="output.txt", payload=payload,
                        operation_id=operation_id,
                    )
                except EffectUnavailable:
                    pass
                else:
                    raise ProbeRejected("injected completion crash did not interrupt Gateway")
            finally:
                writer._record = original_record
            output_path = effect_root / "output.txt"
            if not crash_seen or target_writes != 1 or output_path.read_bytes() != payload:
                raise ProbeRejected("external Effect did not occur exactly once before completion")
            fault_info = output_path.stat(follow_symlinks=False)
            fault_identity = [
                fault_info.st_dev, fault_info.st_ino, fault_info.st_uid,
                fault_info.st_mode & 0o777, fault_info.st_nlink,
            ]
            fault_sha = _sha(output_path.read_bytes())
            prepared = writer.historical_readback(
                lease["lease_id"], resource_id, lease["generation"],
                lease["fencing_token"], "output.txt",
                caller=producer.context, scope_id="local-scope",
                grant_ref=producer.context.grant_ref,
                authority_incarnation=producer.context.authority_incarnation,
                expected_operation_id=operation_id,
            )
            with producer._connect() as connection:
                missing_record = connection.execute(
                    "SELECT count(*) FROM effects WHERE effect_id=%s", (effect_id,),
                ).fetchone()[0] == 0
            if (
                prepared["completion_state"] != "prepared"
                or prepared["completion_sha256"] is not None
                or not missing_record
            ):
                raise ProbeRejected("external bytes preceded any Domain completion record")
            register_command = _domain_command(
                producer, "effect.register", "work_item", work_id,
                suffix + ":uncertain-effect-register", issued_at, revision=1,
            )
            registration = producer.register_effect(
                register_command, effect_id=effect_id,
                lease_id=lease["lease_id"], resource_id=resource_id,
                readback_ref="output.txt", operation_id=operation_id,
            )
            with producer._connect() as connection:
                initial_row = connection.execute(
                    "SELECT status,completion_state,completion_sha256,operation_id,"
                    "registration_command_id,registration_operation_id "
                    "FROM effects WHERE effect_id=%s", (effect_id,),
                ).fetchone()
            if initial_row != (
                "uncertain", "prepared", None, operation_id,
                register_command.command_id, registration.operation_id,
            ):
                raise ProbeRejected("Domain did not commit the prepared uncertain Effect")
            if not producer.register_effect(
                register_command, effect_id=effect_id,
                lease_id=lease["lease_id"], resource_id=resource_id,
                readback_ref="output.txt", operation_id=operation_id,
            ).duplicate:
                raise ProbeRejected("uncertain Effect registration replay was not idempotent")
            accept_while_uncertain = _domain_command(
                finalizer, "work_item.transition", "work_item", work_id,
                suffix + ":accept-while-uncertain", issued_at, revision=1,
            )
            try:
                finalizer.transition_work_item(
                    accept_while_uncertain, TransitionRequest(
                        to_state=WorkItemState.ACCEPTED,
                        evidence_refs=(evidence_id,), review_ref=review_id,
                        effect_refs=(effect_id,), readback_refs=("output.txt",),
                    ),
                )
            except AcceptanceGuardFailed as error:
                acceptance_blocked_while_uncertain = (
                    "every protected effect must be verified" in str(error)
                )
            else:
                acceptance_blocked_while_uncertain = False
            with producer._connect() as connection:
                failed_accept_dedup = connection.execute(
                    "SELECT count(*) FROM command_dedup WHERE command_id=%s",
                    (accept_while_uncertain.command_id,),
                ).fetchone()[0]
                ready_state = connection.execute(
                    "SELECT state,revision FROM work_items WHERE work_item_id=%s",
                    (work_id,),
                ).fetchone()
            if (
                not acceptance_blocked_while_uncertain
                or failed_accept_dedup != 0
                or ready_state != (WorkItemState.ACCEPTANCE_READY.value, 1)
            ):
                raise ProbeRejected("uncertain Effect was accepted or wrote partial Domain state")
            try:
                writer.write(
                    **args, relative_path="output.txt", payload=b"forbidden second effect",
                    operation_id="new-effect:" + delivery_operation_id,
                )
            except EffectUnavailable:
                pending_new_operation_rejected = True
            else:
                pending_new_operation_rejected = False
            if not pending_new_operation_rejected or target_writes != 1:
                raise ProbeRejected("new Effect bypassed unresolved original operation")
            resume = writer.reconcile(
                lease["lease_id"], resource_id, lease["generation"],
                lease["fencing_token"], "output.txt", operation_id=operation_id,
                caller=producer.context, attempt_id=delivery_attempt_id,
                runtime_id=owner["runtime_id"], scope_id="local-scope",
                grant_ref=producer.context.grant_ref,
                authority_incarnation=producer.context.authority_incarnation,
            )
            if (resume["status"] != "verified" or resume["sha256"] != output_ref.sha256
                    or target_writes != 1):
                raise ProbeRejected("original Effect could not be reconciled without reapplication")
            reconcile_command = _domain_command(
                producer, "effect.reconcile", "work_item", work_id,
                suffix + ":uncertain-effect-reconcile", issued_at, revision=1,
            )
            reconciled = producer.reconcile_effect(reconcile_command, effect_id=effect_id)
            if not producer.reconcile_effect(reconcile_command, effect_id=effect_id).duplicate:
                raise ProbeRejected("Effect reconciliation command replay was not idempotent")
            replay = writer.write(
                **args, relative_path="output.txt", payload=payload,
                operation_id=operation_id,
            )
            if replay["sha256"] != output_ref.sha256 or target_writes != 1:
                raise ProbeRejected("same operation retry reapplied protected bytes")
            completed = writer.historical_readback(
                lease["lease_id"], resource_id, lease["generation"],
                lease["fencing_token"], "output.txt",
                caller=producer.context, scope_id="local-scope",
                grant_ref=producer.context.grant_ref,
                authority_incarnation=producer.context.authority_incarnation,
                expected_operation_id=operation_id,
            )
            completion_marker = writer._load(
                writer._ops, _sha(operation_id.encode()) + ".completed",
            )
            if (completion_marker is None
                    or completion_marker.get("completion_basis") != "observed_target"):
                raise ProbeRejected("completion did not arise from observed original bytes")
            output_info = output_path.stat(follow_symlinks=False)
            output_identity = [
                output_info.st_dev, output_info.st_ino, output_info.st_uid,
                output_info.st_mode & 0o777, output_info.st_nlink,
            ]
            marker_sha = _effect_marker_digest(effect_root)
        release_command = _domain_command(
            producer, "lease.release", "lease", resource_id,
            suffix + ":uncertain-lease-release", issued_at, revision=1,
        )
        released = producer.leases.release_lease(
            release_command, lease["lease_id"], resource_id,
            lease["generation"], lease["fencing_token"],
        )
        with LocalFileEffectGateway(
            producer.leases, effect_root, scope_id="local-scope",
            resource_paths={resource_id: "output.txt"},
        ) as late_writer:
            try:
                late_writer.write(
                    **args, relative_path="output.txt", payload=payload,
                    operation_id=operation_id,
                )
            except FencingRejected:
                late_rejected = True
            else:
                late_rejected = False
        reader = DomainAuthority(authority._dsn, context=replace(
            authority.context,
            principal_ref="p1-uncertain-reader:" + suffix,
            grant_ref="grant:p1-uncertain-reader:" + suffix,
        ))
        reader.bootstrap_local_grant(("effect.read",))
        with LocalFileEffectGateway(
            reader.leases, effect_root, scope_id="local-scope",
            resource_paths={resource_id: "output.txt"},
        ) as independent_reader:
            independent = independent_reader.historical_readback(
                lease["lease_id"], resource_id, lease["generation"],
                lease["fencing_token"], "output.txt",
                caller=reader.context, scope_id="local-scope",
                grant_ref=reader.context.grant_ref,
                authority_incarnation=reader.context.authority_incarnation,
                expected_operation_id=operation_id,
            )
        with producer._connect() as connection:
            final_row = connection.execute(
                "SELECT status,completion_state,completion_sha256,operation_id,"
                "registration_command_id,registration_operation_id,"
                "reconciliation_command_id,reconciliation_operation_id "
                "FROM effects WHERE effect_id=%s", (effect_id,),
            ).fetchone()
            lease_row = connection.execute(
                "SELECT owner_attempt_id,owner_runtime_id,generation,status "
                "FROM leases WHERE lease_id=%s", (lease["lease_id"],),
            ).fetchone()
            domain_events = connection.execute(
                "SELECT command_id,event_id FROM domain_events "
                "WHERE command_id IN (%s,%s,%s,%s) ORDER BY event_id",
                (acquire_command.command_id, release_command.command_id,
                 register_command.command_id, reconcile_command.command_id),
            ).fetchall()
            domain_outbox = connection.execute(
                "SELECT operation_id,topic FROM outbox "
                "WHERE operation_id IN (%s,%s,%s,%s) ORDER BY operation_id",
                (lease["operation_id"], released["operation_id"],
                 registration.operation_id, reconciled.operation_id),
            ).fetchall()
        if (released["status"] != "released" or not late_rejected
                or target_writes != 1 or output_path.read_bytes() != payload
                or output_identity != fault_identity
                or _sha(output_path.read_bytes()) != fault_sha
                or _effect_marker_digest(effect_root) != marker_sha
                or completed["status"] != "verified"
                or completed["completion_state"] != "completed"
                or independent["sha256"] != completed["sha256"]
                or independent["completion_sha256"] != completed["completion_sha256"]
                or final_row != (
                    "verified", "completed", completed["completion_sha256"],
                    operation_id, register_command.command_id,
                    registration.operation_id, reconcile_command.command_id,
                    reconciled.operation_id,
                )
                or lease_row != (delivery_attempt_id, owner["runtime_id"],
                                 lease["generation"], "released")
                or len(domain_events) != 4
                or set(domain_outbox) != {
                    (lease["operation_id"], "lease.acquired"),
                    (released["operation_id"], "lease.release"),
                    (registration.operation_id, "effect.registered"),
                    (reconciled.operation_id, "effect.reconciled"),
                }):
            raise ProbeRejected("uncertain Effect recovery or late fencing changed its lineage")
        proof = {
            "delivery_operation_id": delivery_operation_id,
            "message_id": message_id, "dispatch_id": dispatch_id,
            "work_item_id": work_id, "attempt_id": delivery_attempt_id,
            "runtime_id": owner["runtime_id"], "node_id": node.node_id,
            "machine_id": node.machine_id, "source_commit": commit,
            "source_tree": tree, "effect_id": effect_id,
            "effect_operation_id": operation_id, "resource_id": resource_id,
            "lease_id": lease["lease_id"], "generation": lease["generation"],
            "fencing_token_sha256": _sha(lease["fencing_token"].encode()),
            "acquire_command_id": acquire_command.command_id,
            "acquire_operation_id": lease["operation_id"],
            "release_command_id": release_command.command_id,
            "release_operation_id": released["operation_id"],
            "registration_command_id": register_command.command_id,
            "registration_operation_id": registration.operation_id,
            "reconciliation_command_id": reconcile_command.command_id,
            "reconciliation_operation_id": reconciled.operation_id,
            "domain_event_ids": [
                {"command_id": command_id, "event_id": str(event_id)}
                for command_id, event_id in domain_events
            ],
            "receipt_id": receipt.receipt_id,
            "evidence_id": evidence_id, "review_id": review_id,
            "candidate_ref": binding["candidate_ref"],
            "artifact_sha256": output_ref.sha256,
            "artifact_ref": output_ref.model_dump(mode="json"),
            "source_readback_ref": readback_ref.model_dump(mode="json"),
            "reader_grant_ref": reader.context.grant_ref,
            "reader_principal_ref": reader.context.principal_ref,
            "producer_grant_ref": producer.context.grant_ref,
            "producer_principal_ref": producer.context.principal_ref,
            "domain_record_absent_at_fault": missing_record,
            "initial_status": initial_row[0],
            "initial_completion_state": initial_row[1],
            "final_status": final_row[0],
            "final_completion_state": final_row[1],
            "completion_sha256": completed["completion_sha256"],
            "completion_basis": completion_marker["completion_basis"],
            "intent_sha256": completed["intent_sha256"],
            "effect_file_sha256": _sha(output_path.read_bytes()),
            "effect_file_identity": output_identity,
            "fault_file_sha256": fault_sha,
            "fault_file_identity": fault_identity,
            "effect_marker_sha256": marker_sha,
            "target_write_count": target_writes,
            "pending_new_operation_rejected": pending_new_operation_rejected,
            "acceptance_blocked_while_uncertain": acceptance_blocked_while_uncertain,
            "failed_accept_dedup_count": failed_accept_dedup,
            "late_old_owner_rejected": late_rejected,
            "original_operation_replay": True,
        }
        _private_json(proof_path, proof)
        return proof





_SOURCE_EXECUTABLE_PATHS = (
    "runtime_tests/p1_codex_stdio_fixture.py",
    "tools/runtime/acs-bwrap-package/install.sh",
    "tools/runtime/acs-bwrap-package/manage.py",
    "tools/runtime/acs-bwrap-package/uninstall.sh",
)


def _private_source_drift(
    source_root: Path, expected_tree: str, issued_at: datetime,
) -> tuple[dict[str, Any], bytes]:
    """Rebuild two real Git commits in owner-private ephemeral storage."""
    with tempfile.TemporaryDirectory(prefix="p1-source-baseline-", dir="/tmp") as temporary:
        checkout = Path(temporary) / "checkout"
        checkout.mkdir(mode=0o700)
        copied = 0
        if (source_root / ".git").exists():
            archive = subprocess.run(
                ["git", "-C", str(source_root), "archive", "--format=tar", "HEAD"],
                env={
                    "PATH": "/usr/bin:/bin", "HOME": temporary, "LC_ALL": "C",
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                },
                capture_output=True, check=True, timeout=60,
            ).stdout
            with tarfile.open(fileobj=BytesIO(archive), mode="r:") as bundle:
                for member in bundle.getmembers():
                    relative = Path(member.name)
                    if relative.is_absolute() or ".." in relative.parts or member.issym() or member.islnk():
                        raise ProbeRejected("source archive cannot enter private Git checkout")
                    target = checkout / relative
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        stream = bundle.extractfile(member)
                        if stream is None:
                            raise ProbeRejected("source archive file is unreadable")
                        target.write_bytes(stream.read())
                        copied += 1
                    else:
                        raise ProbeRejected("source archive has unsupported entry")
        else:
            for source in sorted(source_root.rglob("*")):
                relative = source.relative_to(source_root)
                if source.is_symlink():
                    raise ProbeRejected("Gate source snapshot contains a symlink")
                target = checkout / relative
                if source.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                elif source.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.read_bytes())
                    copied += 1
                else:
                    raise ProbeRejected("Gate source snapshot contains unsupported file")
        if not 0 < copied <= 20_000:
            raise ProbeRejected("private Gate source copy is empty or unbounded")
        for path in sorted(checkout.rglob("*")):
            path.chmod(0o700 if path.is_dir() else 0o600)
        for relative in _SOURCE_EXECUTABLE_PATHS:
            path = checkout / relative
            if not path.is_file():
                raise ProbeRejected("reviewed executable source path is missing")
            path.chmod(0o700)
        stamp = issued_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S +0000")
        git_env = {
            "PATH": "/usr/bin:/bin", "HOME": temporary, "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_AUTHOR_NAME": "P1 Private Source Probe",
            "GIT_AUTHOR_EMAIL": "p1-private@example.invalid",
            "GIT_COMMITTER_NAME": "P1 Private Source Probe",
            "GIT_COMMITTER_EMAIL": "p1-private@example.invalid",
            "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp,
        }

        def git(*args: str) -> str:
            result = subprocess.run(
                ["git", "-C", str(checkout), *args],
                env=git_env, capture_output=True, text=True,
                check=True, timeout=60,
            )
            return result.stdout.strip()

        git("init", "-q", "-b", "p1-source-baseline")
        git("-c", "core.autocrlf=false", "add", "-A", "-f")
        git("-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "Copy fixed Gate source")
        copied_commit = git("rev-parse", "HEAD")
        copied_tree = git("rev-parse", "HEAD^{tree}")
        if copied_tree != expected_tree or git("status", "--porcelain"):
            raise ProbeRejected("private source copy does not match fixed Gate tree")
        changed_path = "docs/runtime/P1-PROBE-PROFILE.md"
        target = checkout / changed_path
        target.write_bytes(
            target.read_bytes() + b"\n<!-- isolated P1 integration baseline revision -->\n",
        )
        git("add", changed_path)
        git("-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "Integrate private stale source revision")
        second_commit = git("rev-parse", "HEAD")
        second_tree = git("rev-parse", "HEAD^{tree}")
        if (
            second_tree == copied_tree
            or git("rev-parse", "HEAD^") != copied_commit
            or git("diff", "--name-only", copied_commit, second_commit) != changed_path
            or git("status", "--porcelain")
        ):
            raise ProbeRejected("second private source commit is not one clean integration change")
        patch = subprocess.run(
            ["git", "-C", str(checkout), "diff", "--binary", copied_commit, second_commit],
            env=git_env, capture_output=True, check=True, timeout=60,
        ).stdout
        return {
            "copied_source_commit": copied_commit,
            "copied_source_tree": copied_tree,
            "stale_git_commit": second_commit,
            "stale_git_tree": second_tree,
            "stale_diff_sha256": _sha(patch),
            "stale_changed_path": changed_path,
            "copied_file_count": copied,
            "git_timestamp": stamp,
        }, patch


def _stale_baseline(
    authority: DomainAuthority, node: NodeJournal, ledger: ProbeLedger,
    work_id: str, message_id: str, delivery_operation_id: str,
    commit: str, tree: str, suffix: str, issued_at: datetime,
    *, source_root: Path,
) -> dict[str, Any]:
    proof_path = ledger.root / "P1-STALE-BASELINE-proof.json"
    if proof_path.exists():
        proof = json.loads(proof_path.read_text())
        if (proof.get("delivery_operation_id") != delivery_operation_id
                or proof.get("message_id") != message_id):
            raise ProbeRejected("stale baseline proof belongs to another delivery")
        return proof
    with authority._connect() as connection:
        attempts = connection.execute(
            "SELECT attempt_id,dispatch_id,status FROM delivery_attempts "
            "WHERE message_id=%s ORDER BY ordinal", (message_id,),
        ).fetchall()
    if len(attempts) != 1 or attempts[0][2] != "delivered":
        raise ProbeRejected("stale baseline requires one delivered Attempt")
    delivery_attempt_id, dispatch_id, _ = attempts[0]
    source_drift, source_patch = _private_source_drift(
        source_root, tree, issued_at,
    )
    patch_path = ledger.root / "P1-STALE-BASELINE-source.diff"
    descriptor = os.open(
        patch_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600,
    )
    try:
        os.write(descriptor, source_patch)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    stale_baseline = source_drift["stale_git_commit"]
    cas_root = ledger.root / "P1-STALE-BASELINE-cas"
    with LocalArtifactStore(cas_root) as store:
        producer = DomainAuthority(
            authority._dsn, context=authority.context, artifact_store=store,
        )
        producer.bootstrap_local_grant((
            "work_item.create", "delivery.manage", "message.send", "message.read",
            "runtime.invoke", "evidence.record", "work_item.read",
        ))
        owner, observer, signed = _register_lease_execution(
            producer, node, work_id, commit, tree, suffix, issued_at,
            execution_attempt_id=delivery_attempt_id, artifact_store=store,
        )
        binding = owner["execution_binding"]
        if (binding["attempt_id"] != delivery_attempt_id
                or binding["work_item_id"] != work_id
                or binding["source_baseline"] != commit
                or binding["source_commit"] != commit
                or binding["source_tree"] != tree):
            raise ProbeRejected("stale baseline execution differs from Delivery Attempt")
        output_ref = store.put_bytes(
            ("P1 stale candidate output for " + delivery_operation_id).encode(),
            kind="output",
        )
        readback_ref = store.put_bytes(
            ("independent stale source readback:" + delivery_operation_id).encode(),
            kind="readback",
        )
        observed_at = datetime.now(UTC)
        receipt = ExecutionReceipt(
            receipt_id="stale-execution-receipt-" + suffix,
            work_item_id=work_id, attempt_id=delivery_attempt_id,
            runtime_id=owner["runtime_id"], provider=binding["provider"],
            command_id=binding["execution_command_id"],
            operation_id=binding["execution_operation_id"],
            event_id=binding["execution_event_id"],
            source_baseline=commit, candidate_ref=binding["candidate_ref"],
            source_commit=commit, source_tree=tree,
            test_commands=("P1-STALE-BASELINE fixed local execution",),
            test_exit_codes=(0,), test_exit_code=0,
            os="linux", toolchain="P1 local delivery and source CAS",
            artifact_refs=(output_ref,), readback_refs=(readback_ref,),
            source_sync="committed-private-probe-source",
            status="succeeded", observed_at=observed_at,
        )
        receipt_command = _domain_command(
            observer, "execution.record", "work_item", work_id,
            suffix + ":stale-execution-receipt", issued_at,
        )
        recorded = observer.record_execution_receipt(
            receipt_command, receipt,
            node_proof=signed(receipt_command, receipt, "receipt"),
        )
        evidence_id = "stale-evidence-" + suffix
        bundle = EvidenceBundle(
            evidence_id=evidence_id, work_item_id=work_id,
            source_baseline=commit, candidate_ref=binding["candidate_ref"],
            producer_ref=producer.context.principal_ref,
            observer_ref=observer.context.principal_ref,
            source_class="directly_verified", evidence_state="complete",
            execution_receipt=receipt, artifact_refs=(output_ref,),
            readback_refs=(readback_ref,), command_id=receipt.command_id,
            operation_id=receipt.operation_id, event_id=receipt.event_id,
            observed_at=observed_at,
        )
        evidence = EvidenceRecord(
            evidence_id=evidence_id, work_item_id=work_id,
            observer_ref=observer.context.principal_ref,
            source_class="directly_verified", baseline_ref=commit,
            artifact_sha256=output_ref.sha256,
            summary="Signed same-attempt source output and independent CAS readback",
            bundle_ref=evidence_id, candidate_ref=binding["candidate_ref"],
            execution_receipt_ref=receipt.receipt_id,
            evidence_state="complete", producer_ref=producer.context.principal_ref,
            attempt_id=delivery_attempt_id, test_exit_code=0,
            artifact_refs=(output_ref,), readback_refs=(readback_ref,),
        )
        evidence_command = _domain_command(
            producer, "evidence.record", "work_item", work_id,
            suffix + ":stale-evidence", issued_at,
        )
        evidence_result = producer.record_evidence(
            evidence_command, evidence, bundle,
        )
        reviewer = DomainAuthority(authority._dsn, context=replace(
            authority.context, principal_ref="p1-stale-reviewer:" + suffix,
            grant_ref="grant:p1-stale-reviewer:" + suffix,
        ), artifact_store=store)
        finalizer = DomainAuthority(authority._dsn, context=replace(
            authority.context, principal_ref="p1-stale-finalizer:" + suffix,
            grant_ref="grant:p1-stale-finalizer:" + suffix,
        ), artifact_store=store)
        reviewer.bootstrap_local_grant(("review.record", "work_item.read"))
        finalizer.bootstrap_local_grant((
            "review.assign", "work_item.transition", "acceptance.finalize",
            "work_item.read",
        ))
        review_id = "stale-review-" + suffix
        assign_command = _domain_command(
            finalizer, "review.assign", "work_item", work_id,
            suffix + ":stale-review-assign", issued_at,
        )
        assigned = finalizer.assign_reviewer(
            assign_command, work_id, reviewer.context.principal_ref,
            reviewer.context.grant_ref,
        )
        review_command = _domain_command(
            reviewer, "review.record", "work_item", work_id,
            suffix + ":stale-review", issued_at,
        )
        reviewed = reviewer.record_review(
            review_command, review_id, work_id, "pass", evidence_id, commit,
        )
        ready_command = _domain_command(
            finalizer, "work_item.transition", "work_item", work_id,
            suffix + ":stale-ready", issued_at,
        )
        ready = finalizer.transition_work_item(
            ready_command, TransitionRequest(
                to_state=WorkItemState.ACCEPTANCE_READY,
                evidence_refs=(evidence_id,), review_ref=review_id,
            ),
        )
        if ready.revision != 1:
            raise ProbeRejected("stale baseline candidate did not reach ready revision")
        cas_file = cas_root / output_ref.path
        original_bytes = cas_file.read_bytes()
        original_mode = stat.S_IMODE(cas_file.stat(follow_symlinks=False).st_mode)
        cas_file.chmod(0o600)
        cas_file.write_bytes(b"x" * len(original_bytes))
        cas_accept_command = _domain_command(
            finalizer, "work_item.transition", "work_item", work_id,
            suffix + ":stale-cas-accept", issued_at, revision=1,
        )
        try:
            try:
                finalizer.transition_work_item(
                    cas_accept_command, TransitionRequest(
                        to_state=WorkItemState.ACCEPTED,
                        evidence_refs=(evidence_id,), review_ref=review_id,
                    ),
                )
            except AcceptanceGuardFailed as error:
                cas_rejection_reason = str(error)
            else:
                raise ProbeRejected("invalidated prepared CAS evidence was accepted")
        finally:
            cas_file.write_bytes(original_bytes)
            cas_file.chmod(original_mode)
        store.verify(output_ref)
        with producer._connect() as connection:
            cas_denied_counts = {
                table: connection.execute(
                    f"SELECT count(*) FROM {table} WHERE command_id=%s",
                    (cas_accept_command.command_id,),
                ).fetchone()[0]
                for table in ("command_dedup", "domain_events", "operations")
            }
        if (
            "receipt artifact bytes are not verified" not in cas_rejection_reason
            or any(cas_denied_counts.values())
        ):
            raise ProbeRejected("prepared CAS invalidation did not fail atomically")
        with producer._connect() as connection:
            original = connection.execute(
                "SELECT source_baseline FROM work_items WHERE work_item_id=%s",
                (work_id,),
            ).fetchone()
            snapshot = connection.execute(
                "SELECT baseline_ref,readiness_snapshot FROM accepted_state_revisions "
                "WHERE work_item_id=%s AND revision=1",
                (work_id,),
            ).fetchone()
            connection.execute(
                "UPDATE work_items SET source_baseline=%s WHERE work_item_id=%s "
                "AND state='acceptance_ready' AND revision=1",
                (stale_baseline, work_id),
            )
            changed = connection.execute(
                "SELECT state,revision,source_baseline FROM work_items WHERE work_item_id=%s",
                (work_id,),
            ).fetchone()
        if (
            original != (commit,) or snapshot != (commit, True)
            or changed != ("acceptance_ready", 1, stale_baseline)
        ):
            raise ProbeRejected("injected source baseline did not differ from ready evidence")
        accept_command = _domain_command(
            finalizer, "work_item.transition", "work_item", work_id,
            suffix + ":stale-accept", issued_at, revision=1,
        )
        rejection_reasons = []
        for _ in range(2):
            try:
                finalizer.transition_work_item(
                    accept_command, TransitionRequest(
                        to_state=WorkItemState.ACCEPTED,
                        evidence_refs=(evidence_id,), review_ref=review_id,
                    ),
                )
            except AcceptanceGuardFailed as error:
                rejection_reasons.append(str(error))
            else:
                raise ProbeRejected("stale baseline was accepted")
        if len(set(rejection_reasons)) != 1:
            raise ProbeRejected("stale acceptance retry changed its denial")
        committed = {
            receipt_command.command_id: recorded.operation_id,
            evidence_command.command_id: evidence_result.operation_id,
            assign_command.command_id: assigned.operation_id,
            review_command.command_id: reviewed.operation_id,
            ready_command.command_id: ready.operation_id,
        }
        with producer._connect() as connection:
            final_work = connection.execute(
                "SELECT state,revision,source_baseline FROM work_items "
                "WHERE work_item_id=%s", (work_id,),
            ).fetchone()
            accepted_count = connection.execute(
                "SELECT count(*) FROM accepted_state_revisions "
                "WHERE work_item_id=%s AND readiness_snapshot=FALSE",
                (work_id,),
            ).fetchone()[0]
            effect_count = connection.execute(
                "SELECT count(*) FROM effects WHERE work_item_id=%s",
                (work_id,),
            ).fetchone()[0]
            denied_counts = {
                table: connection.execute(
                    f"SELECT count(*) FROM {table} WHERE command_id=%s",
                    (accept_command.command_id,),
                ).fetchone()[0]
                for table in ("command_dedup", "domain_events", "operations")
            }
            events = connection.execute(
                "SELECT command_id,event_id FROM domain_events "
                "WHERE command_id IN (%s,%s,%s,%s,%s) ORDER BY event_id",
                tuple(committed),
            ).fetchall()
            outbox = connection.execute(
                "SELECT operation_id,topic FROM outbox "
                "WHERE operation_id IN (%s,%s,%s,%s,%s)",
                tuple(committed.values()),
            ).fetchall()
        if (
            final_work != changed or accepted_count != 0 or effect_count != 0
            or any(denied_counts.values()) or len(events) != 5
            or len(outbox) != 5
        ):
            raise ProbeRejected("stale denial left accepted state or partial effects")
        proof = {
            "delivery_operation_id": delivery_operation_id,
            "message_id": message_id, "dispatch_id": dispatch_id,
            "work_item_id": work_id, "attempt_id": delivery_attempt_id,
            "runtime_id": owner["runtime_id"], "node_id": node.node_id,
            "machine_id": node.machine_id, "source_commit": commit,
            "source_tree": tree, "ready_baseline": commit,
            "stale_baseline": stale_baseline, "ready_revision": 1,
            "source_drift": source_drift,
            "candidate_ref": binding["candidate_ref"],
            "artifact_ref": output_ref.model_dump(mode="json"),
            "readback_ref": readback_ref.model_dump(mode="json"),
            "receipt_id": receipt.receipt_id, "evidence_id": evidence_id,
            "review_id": review_id, "committed_operations": committed,
            "committed_event_ids": [
                {"command_id": command_id, "event_id": str(event_id)}
                for command_id, event_id in events
            ],
            "cas_accept_command_id": cas_accept_command.command_id,
            "cas_rejection_reason": cas_rejection_reason,
            "cas_denied_command_counts": cas_denied_counts,
            "accept_command_id": accept_command.command_id,
            "rejection_reason": rejection_reasons[0],
            "denied_replay_count": len(rejection_reasons),
            "denied_command_counts": denied_counts,
            "accepted_revision_count": accepted_count,
            "protected_effect_count": effect_count,
        }
        _private_json(proof_path, proof)
        return proof



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
        "runtime.invoke", "lease.acquire", "lease.release", "lease.inspect",
        "effect.write", "effect.read",
    ))
    work_id = "work-" + suffix
    create = _domain_command(
        authority, "work_item.create", "work_item", work_id, suffix, issued_at,
    )
    authority.create_work_item(create, "local-scope", "local-slot", commit)
    resume_node_restart = scenario == "P1-NODE-RESTART" and any(
        (ledger.root / name).exists() for name in (
            "P1-NODE-RESTART-proof.json", "P1-NODE-RESTART-child-result.json",
        )
    )
    node = NodeJournal(
        ledger.root / (scenario + "-node.sqlite"),
        machine_id=profile["machine_id"], node_id=profile["node_id"],
        boot_incarnation=("reboot-" if resume_node_restart else "boot-") + suffix,
    )
    Path(node._path).chmod(0o600)
    driver = FixtureDriver()
    endpoint_id = "endpoint-" + suffix
    endpoint = LocalNodeEndpoint(node, "local-scope", "local-slot", driver)
    service = DeliveryService(authority, {endpoint_id: endpoint})
    bind = _domain_command(
        authority, "message.bind", "message", endpoint_id, suffix, issued_at,
    )
    message_id = "message-" + suffix
    send = _domain_command(
        authority, "message.send", "message", message_id, suffix, issued_at,
    )
    packet = DeliveryPacket(
        work_item_id=work_id, target_scope_id="local-scope",
        target_agent_slot_id="local-slot", accepted_revision=0,
        goal=f"{scenario} lineage probe", accepted_state_summary="revision zero",
        request="Return the fixed fixture response", source_baseline=commit,
        expected_response="layered receipt",
        activation="message_only" if scenario in (
            "P1-NODE-RESTART", "P1-PROVIDER-RESTART",
        ) else "invoke",
        deadline=send.deadline,
    )
    if resume_node_restart:
        with authority._connect() as connection:
            current = connection.execute(
                "SELECT operation_id,state FROM delivery_messages "
                "WHERE command_id=%s AND message_id=%s AND tenant_id=%s",
                (send.command_id, message_id, authority.tenant_id),
            ).fetchone()
        if current is None or current[1] != "delivered":
            raise ProbeRejected("Node restart checkpoint is not a terminal Runtime message")
        sent = SimpleNamespace(operation_id=current[0])
    else:
        service.bind_endpoint(bind, EndpointBindingRequest(
            scope_id="local-scope", agent_slot_id="local-slot",
            expires_at=bind.deadline,
        ))
        sent = service.send_message(send, packet, endpoint_id=endpoint_id, binding_revision=1)
    identity = {
        "tenant_id": authority.tenant_id,
        "message_id": message_id,
        "operation_id": sent.operation_id,
    }
    if resume_node_restart:
        replay = SimpleNamespace(duplicate=True, operation_id=sent.operation_id)
        conflict_rejected = True
    else:
        replay = service.send_message(send, packet, endpoint_id=endpoint_id, binding_revision=1)
        changed_packet = packet.model_copy(update={"request": "changed conflicting request"})
        try:
            service.send_message(send, changed_packet, endpoint_id=endpoint_id, binding_revision=1)
        except IdempotencyConflict:
            conflict_rejected = True
        else:
            conflict_rejected = False
    if not replay.duplicate or replay.operation_id != sent.operation_id:
        raise ProbeRejected("Domain exact command replay did not retain its identity")
    if not conflict_rejected:
        raise ProbeRejected("Domain command conflict was not rejected")
    ack_loss_observed = False
    core_crash_proof = None
    node_restart_proof = None
    provider_restart_proof = None
    provider_workflow = None
    lease_proof = None
    uncertain_effect_proof = None
    stale_baseline_proof = None
    if scenario == "P1-AUTH-REVOCATION":
        with authority._connect() as connection:
            connection.execute(
                "UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                (authority.context.grant_ref,),
            )
        delivered = DeliveryDispatcher(service).dispatch(identity)
        if delivered["status"] != "blocked":
            raise ProbeRejected("revoked Grant still dispatched the queued command")
    elif scenario == "P1-CORE-RESTART":
        delivered, core_crash_proof = _core_restart(
            profile, ledger, pg_schema, service, endpoint, identity,
            message_id, sent.operation_id, node, driver,
        )
    elif scenario == "P1-NODE-RESTART":
        delivered, node_restart_proof, node = _node_restart(
            profile, ledger, pg_schema, service, endpoint, identity,
            suffix, issued_at, node, driver, fault,
        )
    elif scenario == "P1-PROVIDER-RESTART":
        delivered, provider_restart_proof, provider_workflow, provider_run = _provider_restart(
            profile, ledger, pg_schema, service, endpoint, identity, suffix, node, driver,
            fault,
        )
    elif scenario == "P1-INBOX-ACK-LOSS":
        original_deliver = endpoint.deliver
        first_delivery = True

        def lose_ack(*args: Any, **kwargs: Any) -> dict[str, Any]:
            nonlocal first_delivery
            observation = original_deliver(*args, **kwargs)
            if first_delivery:
                first_delivery = False
                raise DeliveryTransportError("injected ACK loss after Node commit")
            return observation

        endpoint.deliver = lose_ack
        first_result = DeliveryDispatcher(service).dispatch(identity)
        endpoint.deliver = original_deliver
        with authority._connect() as connection:
            interim_inbox_count = connection.execute(
                "SELECT count(*) FROM inbox_messages WHERE message_id=%s",
                (message_id,),
            ).fetchone()[0]
        node_after_loss = node.get_message(message_id)
        ack_loss_observed = (
            first_result["status"] == "retry_wait" and interim_inbox_count == 0
            and node_after_loss is not None
            and node_after_loss.state == "response_received"
        )
        if not ack_loss_observed:
            raise ProbeRejected("ACK loss did not separate Node commit from Core projection")
        with authority._connect() as connection:
            connection.execute(
                "UPDATE delivery_messages SET next_attempt_at=clock_timestamp() "
                "WHERE message_id=%s", (message_id,),
            )
        delivered = DeliveryDispatcher(service).dispatch(identity)
        if delivered["status"] != "delivered":
            raise ProbeRejected("ACK loss retry did not project the same Node response")
    else:
        delivered = DeliveryDispatcher(service).dispatch(identity)
        if delivered["status"] != "delivered":
            raise ProbeRejected("Domain delivery did not reach its terminal receipt")
    if scenario == "P1-LEASE-FENCING":
        lease_proof = _lease_fencing(
            authority, node, ledger, work_id, sent.operation_id,
            commit, tree, suffix, issued_at,
        )
    if scenario == "P1-UNCERTAIN-EFFECT":
        uncertain_effect_proof = _uncertain_effect(
            authority, node, ledger, work_id, message_id, sent.operation_id,
            commit, tree, suffix, issued_at,
        )
    if scenario == "P1-STALE-BASELINE":
        stale_baseline_proof = _stale_baseline(
            authority, node, ledger, work_id, message_id, sent.operation_id,
            commit, tree, suffix, issued_at,
            source_root=Path(profile["source_root"]),
        )
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
    expected_driver_calls = (
        [] if scenario in (
            "P1-AUTH-REVOCATION", "P1-NODE-RESTART", "P1-PROVIDER-RESTART",
        )
        else [sent.operation_id]
    )
    if driver_calls != expected_driver_calls:
        raise ProbeRejected("Driver call lineage is incomplete")
    if fault is not None:
        fault("after_domain_dispatch")
    with authority._connect() as connection:
        attempts = connection.execute(
            "SELECT ordinal,attempt_id,dispatch_id,status,selection_revision,"
            "selection_json->>'boot_incarnation',selection_json->>'machine_id' "
            "FROM delivery_attempts "
            "WHERE message_id=%s ORDER BY ordinal",
            (message_id,),
        ).fetchall()
        receipts = connection.execute(
            "SELECT receipt_id,layer FROM delivery_receipts WHERE message_id=%s ORDER BY observed_at",
            (message_id,),
        ).fetchall()
        events = connection.execute(
            "SELECT event_id FROM domain_events WHERE command_id=%s ORDER BY event_id",
            (send.command_id,),
        ).fetchall()
        message_state = connection.execute(
            "SELECT state,last_error FROM delivery_messages WHERE message_id=%s",
            (message_id,),
        ).fetchone()
        inbox_count = connection.execute(
            "SELECT count(*) FROM inbox_messages WHERE message_id=%s", (message_id,),
        ).fetchone()[0]
        grant_revoked = connection.execute(
            "SELECT revoked_at IS NOT NULL FROM grants WHERE grant_ref=%s",
            (authority.context.grant_ref,),
        ).fetchone()[0]
        dedup_details = connection.execute(
            "SELECT canonical_hash,hash_version FROM command_dedup WHERE command_id=%s",
            (send.command_id,),
        ).fetchone()
        operation_details = connection.execute(
            "SELECT status,provider FROM operations WHERE operation_id=%s",
            (sent.operation_id,),
        ).fetchone()
        provider_refs = connection.execute(
            "SELECT provider_workflow_id,provider_run_id FROM operations WHERE operation_id=%s",
            (sent.operation_id,),
        ).fetchone()
        outbox_details = connection.execute(
            "SELECT topic,delivered_at IS NOT NULL FROM outbox WHERE operation_id=%s",
            (sent.operation_id,),
        ).fetchone()
        message_hashes = connection.execute(
            "SELECT canonical_hash,envelope_hash FROM delivery_messages WHERE message_id=%s",
            (message_id,),
        ).fetchone()
        event_hashes = connection.execute(
            "SELECT canonical_hash FROM domain_events WHERE command_id=%s ORDER BY event_id",
            (send.command_id,),
        ).fetchall()
        operation_count = connection.execute(
            "SELECT count(*) FROM operations WHERE command_id=%s",
            (send.command_id,),
        ).fetchone()[0]
        outbox_count = connection.execute(
            "SELECT count(*) FROM outbox WHERE operation_id=%s",
            (sent.operation_id,),
        ).fetchone()[0]
    if (not receipts or not events
            or (scenario not in ("P1-NODE-RESTART", "P1-PROVIDER-RESTART")
                and any(item[2] is None for item in attempts))
            or (scenario == "P1-AUTH-REVOCATION" and attempts)
            or (scenario != "P1-AUTH-REVOCATION" and not attempts)):
        raise ProbeRejected("Domain delivery lineage rows are incomplete")
    expected_state = "blocked" if scenario == "P1-AUTH-REVOCATION" else "delivered"
    if message_state[0] != expected_state or grant_revoked != (scenario == "P1-AUTH-REVOCATION"):
        raise ProbeRejected("scenario authority state disagrees with the expected fault")
    if inbox_count != (0 if scenario == "P1-AUTH-REVOCATION" else 1):
        raise ProbeRejected("scenario Inbox projection count changed")
    if (not all((dedup_details, operation_details, provider_refs,
                outbox_details, message_hashes))
            or len(events) != 1 or operation_count != 1 or outbox_count != 1):
        raise ProbeRejected("Domain command/operation/outbox hashes are incomplete")
    if scenario == "P1-PROVIDER-RESTART" and provider_refs != (provider_workflow, provider_run):
        raise ProbeRejected("Temporal Workflow reference did not commit to Domain")
    if scenario == "P1-INBOX-ACK-LOSS" and (
        len(attempts) != 2 or [item[3] for item in attempts] != ["retry_wait", "delivered"]
    ):
        raise ProbeRejected("ACK loss did not retain both delivery attempts")
    if scenario == "P1-NODE-RESTART" and (
        len(attempts) != 2 or [item[3] for item in attempts] != ["retry_wait", "delivered"]
        or [item[4] for item in attempts] != [1, 2]
        or [item[5] for item in attempts] != [node_restart_proof["old_boot"],
                                             node_restart_proof["new_boot"]]
    ):
        raise ProbeRejected("Node restart did not preserve two selected boot attempts")
    if scenario == "P1-PROVIDER-RESTART":
        if (len(attempts) != 1 or attempts[0][3] != "delivered"
                or attempts[0][1] != provider_restart_proof["prepared_attempt_id"]):
            raise ProbeRejected("Temporal replacement did not preserve prepared attempt")
        workflow_id, temporal_run_id = provider_workflow, provider_run
    else:
        workflow_id, temporal_run_id = asyncio.run(
            _temporal_marker(profile, sent.operation_id + ":temporal", scenario),
        )
    lineage = {
        "tenant_id": authority.tenant_id, "grant_ref": authority.context.grant_ref,
        "machine_id": node.machine_id, "node_id": node.node_id,
        "command_id": send.command_id,
        "message_id": message_id, "operation_id": sent.operation_id,
        "attempt_id": attempts[-1][1] if attempts else None,
        "dispatch_id": attempts[-1][2] if attempts else None,
        "attempts": [{"ordinal": item[0], "attempt_id": item[1],
                      "dispatch_id": item[2], "status": item[3],
                      "selection_revision": item[4], "selection_boot": item[5],
                      "selection_machine": item[6]}
                     for item in attempts],
        "event_ids": [str(item[0]) for item in events],
        "receipts": [{"receipt_id": item[0], "layer": item[1]} for item in receipts],
        "driver_calls": driver_calls, "node_journal": scenario + "-node.sqlite",
        "conflict_rejected": conflict_rejected, "exact_replay": replay.duplicate,
        "dispatch_status": delivered["status"], "message_state": message_state[0],
        "last_error": message_state[1], "inbox_count": inbox_count,
        "grant_revoked": grant_revoked, "ack_loss_observed": ack_loss_observed,
        "core_crash_proof": core_crash_proof,
        "node_restart_proof": node_restart_proof,
        "provider_restart_proof": provider_restart_proof,
        "lease_proof": lease_proof,
        "uncertain_effect_proof": uncertain_effect_proof,
        "stale_baseline_proof": stale_baseline_proof,
        "dedup_details": list(dedup_details),
        "operation_details": list(operation_details),
        "provider_refs": list(provider_refs),
        "outbox_details": list(outbox_details),
        "message_hashes": list(message_hashes),
        "event_hashes": [item[0] for item in event_hashes],
    }
    raw = ledger.root / (scenario + "-runtime.json")
    raw.write_bytes(_canonical({
        "scenario_id": scenario, "lineage": lineage,
        "result": "passed", "fault": scenario,
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
               commit: str, tree: str,
               fault: Callable[[str], None] | None = None) -> dict[str, Any]:
    if ledger.get(scenario) is not None:
        return ledger.get(scenario)
    run_id = os.environ.get("ACS_GATE_RUN_ID", "standalone-" + _sha(os.urandom(16))[:24])
    suffix, issued_at = ledger.claim(scenario, run_id)
    if scenario not in ScenarioCatalog.LINEAGE_BOUND:
        raise ProbeUnavailable("scenario has no real Runtime lineage adapter")
    return _run_domain_transaction(
        profile, scenario, ledger, commit, tree, run_id, suffix, issued_at, fault,
    )


def _lease_pg_readback(profile: dict[str, Any], row: dict[str, Any], proof: dict[str, Any]) -> dict[str, Any]:
    scoped = make_conninfo(
        profile["postgres_dsn"], options=f"-c search_path={row['pg_schema']}",
    )
    with psycopg.connect(scoped) as connection:
        node = connection.execute(
            "SELECT machine_id,boot_incarnation,status FROM enrolled_node_bindings "
            "WHERE node_id=%s AND binding_revision=1", (proof["node_id"],),
        ).fetchone()
        runtime = connection.execute(
            "SELECT node_id,node_boot_incarnation,status,producer_grant_ref "
            "FROM enrolled_runtimes WHERE runtime_id=%s", (proof["runtime_id"],),
        ).fetchone()
        attempt = connection.execute(
            "SELECT work_item_id,runtime_id,source_baseline,source_commit,source_tree,status,"
            "enrollment_boot_incarnation FROM attempts WHERE attempt_id=%s",
            (proof["attempt_id"],),
        ).fetchone()
        replacement_runtime = connection.execute(
            "SELECT node_id,node_boot_incarnation,status,producer_grant_ref "
            "FROM enrolled_runtimes WHERE runtime_id=%s",
            (proof["replacement_runtime_id"],),
        ).fetchone()
        replacement_attempt = connection.execute(
            "SELECT work_item_id,runtime_id,source_baseline,source_commit,source_tree,status,"
            "enrollment_boot_incarnation FROM attempts WHERE attempt_id=%s",
            (proof["replacement_attempt_id"],),
        ).fetchone()
        lease = connection.execute(
            "SELECT resource_id,generation,fencing_token,status,owner_attempt_id,"
            "owner_runtime_id,command_id FROM leases WHERE lease_id=%s",
            (proof["lease_id"],),
        ).fetchone()
        replacement_lease = connection.execute(
            "SELECT resource_id,generation,fencing_token,status,owner_attempt_id,"
            "owner_runtime_id,command_id,grant_ref FROM leases WHERE lease_id=%s",
            (proof["replacement_lease_id"],),
        ).fetchone()
        events = connection.execute(
            "SELECT command_id,event_id,canonical_hash FROM domain_events "
            "WHERE command_id IN (%s,%s,%s,%s) ORDER BY event_id",
            (proof["acquire_command_id"], proof["release_command_id"],
             proof["replacement_acquire_command_id"],
             proof["replacement_release_command_id"]),
        ).fetchall()
        dedup = connection.execute(
            "SELECT command_id,canonical_hash FROM command_dedup "
            "WHERE command_id IN (%s,%s,%s,%s) ORDER BY command_id",
            (proof["acquire_command_id"], proof["release_command_id"],
             proof["replacement_acquire_command_id"],
             proof["replacement_release_command_id"]),
        ).fetchall()
        operations = connection.execute(
            "SELECT command_id,operation_id,provider,status FROM operations "
            "WHERE command_id IN (%s,%s,%s,%s) ORDER BY command_id",
            (proof["acquire_command_id"], proof["release_command_id"],
             proof["replacement_acquire_command_id"],
             proof["replacement_release_command_id"]),
        ).fetchall()
        outboxes = connection.execute(
            "SELECT operation_id,topic FROM outbox "
            "WHERE operation_id IN (%s,%s,%s,%s) ORDER BY topic,operation_id",
            (proof["acquire_operation_id"], proof["release_operation_id"],
             proof["replacement_acquire_operation_id"],
             proof["replacement_release_operation_id"]),
        ).fetchall()
        work = connection.execute(
            "SELECT source_baseline FROM work_items WHERE work_item_id=%s",
            (proof["work_item_id"],),
        ).fetchone()
    expected_events = [
        (item["command_id"], item["event_id"], item["canonical_hash"])
        for item in proof["lease_events"]
    ]
    expected_dedup = [
        (item["command_id"], item["canonical_hash"]) for item in proof["lease_dedup"]
    ]
    expected_operations = sorted([
        (proof["acquire_command_id"], proof["acquire_operation_id"], "local-lease", "committed"),
        (proof["release_command_id"], proof["release_operation_id"], "local-lease", "committed"),
        (proof["replacement_acquire_command_id"], proof["replacement_acquire_operation_id"],
         "local-lease", "committed"),
        (proof["replacement_release_command_id"], proof["replacement_release_operation_id"],
         "local-lease", "committed"),
    ])
    expected_outboxes = sorted([
        (proof["acquire_operation_id"], "lease.acquired"),
        (proof["release_operation_id"], "lease.release"),
        (proof["replacement_acquire_operation_id"], "lease.acquired"),
        (proof["replacement_release_operation_id"], "lease.release"),
    ], key=lambda item: (item[1], item[0]))
    if (
        node != (proof["machine_id"], proof["node_boot"], "active")
        or runtime != (proof["node_id"], proof["node_boot"], "active",
                       proof["producer_grant_ref"])
        or attempt != (
            proof["work_item_id"], proof["runtime_id"], proof["source_commit"],
            proof["source_commit"], proof["source_tree"], "running", proof["node_boot"],
        )
        or replacement_runtime != (
            proof["node_id"], proof["node_boot"], "active",
            proof["replacement_producer_grant_ref"],
        )
        or replacement_attempt != (
            proof["work_item_id"], proof["replacement_runtime_id"],
            proof["source_commit"], proof["source_commit"], proof["source_tree"],
            "running", proof["node_boot"],
        )
        or lease is None
        or lease[0:2] != (proof["resource_id"], proof["generation"])
        or _sha(lease[2].encode()) != proof["fencing_token_sha256"]
        or lease[3:] != (
            "released", proof["attempt_id"], proof["runtime_id"],
            proof["acquire_command_id"],
        )
        or replacement_lease is None
        or replacement_lease[0:2] != (
            proof["resource_id"], proof["replacement_generation"],
        )
        or _sha(replacement_lease[2].encode()) != proof["replacement_fencing_token_sha256"]
        or replacement_lease[3:] != (
            "released", proof["replacement_attempt_id"],
            proof["replacement_runtime_id"], proof["replacement_acquire_command_id"],
            proof["replacement_producer_grant_ref"],
        )
        or proof["replacement_generation"] != proof["generation"] + 1
        or proof["replacement_attempt_id"] == proof["attempt_id"]
        or [(item[0], str(item[1]), item[2]) for item in events] != expected_events
        or dedup != expected_dedup
        or operations != expected_operations
        or outboxes != expected_outboxes
        or work != (proof["source_commit"],)
    ):
        raise ProbeRejected("Lease PG authority/enrollment/fence lineage changed")
    return {"lease_pg_readback": True, "lease_id": proof["lease_id"],
            "lease_event_ids": [item["event_id"] for item in proof["lease_events"]]}


def _lease_effect_readback(
    profile: dict[str, Any], ledger: ProbeLedger,
    row: dict[str, Any], proof: dict[str, Any],
) -> dict[str, Any]:
    effect_root = ledger.root / "P1-LEASE-FENCING-effects"
    output = effect_root / "output.txt"
    info = output.stat(follow_symlinks=False)
    identity = [info.st_dev, info.st_ino, info.st_uid, info.st_mode & 0o777, info.st_nlink]
    if (identity != proof["effect_file_identity"]
            or _sha(output.read_bytes()) != proof["effect_sha256"]
            or info.st_size != proof["effect_size"]):
        raise ProbeRejected("Lease file effect identity/content changed")
    if (_effect_marker_digest(effect_root)
            != proof["pre_late_snapshot"]["marker_sha256"]):
        raise ProbeRejected("Lease file effect marker history changed")
    scoped = make_conninfo(
        profile["postgres_dsn"], options=f"-c search_path={row['pg_schema']}",
    )
    authority = DomainAuthority(scoped)
    with authority._connect() as connection:
        old_token_row = connection.execute(
            "SELECT fencing_token FROM leases WHERE lease_id=%s", (proof["lease_id"],),
        ).fetchone()
        new_token_row = connection.execute(
            "SELECT fencing_token FROM leases WHERE lease_id=%s",
            (proof["replacement_lease_id"],),
        ).fetchone()
    if (old_token_row is None or new_token_row is None
            or _sha(old_token_row[0].encode()) != proof["fencing_token_sha256"]
            or _sha(new_token_row[0].encode()) != proof["replacement_fencing_token_sha256"]):
        raise ProbeRejected("Lease token digest changed")
    reader = DomainAuthority(scoped, context=replace(
        authority.context,
        principal_ref=proof["reader_principal_ref"],
        grant_ref=proof["reader_grant_ref"],
    ))
    with LocalFileEffectGateway(
        reader.leases, effect_root, scope_id="local-scope",
        resource_paths={proof["resource_id"]: "output.txt"},
    ) as observer:
        old_key = _sha(proof["original_effect_operation_id"].encode())
        old_intent = observer._load(observer._ops, old_key + ".intent")
        old_completion = observer._load(observer._ops, old_key + ".completed")
        if (old_intent is None or old_completion is None
                or old_intent["new"]["sha256"] != proof["original_effect_sha256"]
                or observer._digest(observer._encode(old_intent))
                != proof["original_effect_intent_sha256"]
                or observer._digest(observer._encode(old_completion))
                != proof["original_effect_completion_sha256"]):
            raise ProbeRejected("original owner file effect marker history changed")
        observed = observer.historical_readback(
            proof["replacement_lease_id"], proof["resource_id"],
            proof["replacement_generation"], new_token_row[0], "output.txt",
            caller=reader.context, scope_id="local-scope",
            grant_ref=reader.context.grant_ref,
            authority_incarnation=reader.context.authority_incarnation,
            expected_operation_id=proof["effect_operation_id"],
        )
    if (
        observed["status"] != "verified"
        or observed["sha256"] != proof["effect_sha256"]
        or observed["intent_sha256"] != proof["effect_intent_sha256"]
        or observed["completion_sha256"] != proof["effect_completion_sha256"]
        or observed["completion_state"] != "completed"
    ):
        raise ProbeRejected("historical file effect readback changed")
    try:
        authority.leases.verify_fence(
            proof["lease_id"], proof["resource_id"], proof["generation"],
            old_token_row[0], caller=authority.context,
            attempt_id=proof["attempt_id"], runtime_id=proof["runtime_id"],
            scope_id="local-scope", grant_ref=authority.context.grant_ref,
            authority_incarnation=authority.context.authority_incarnation,
        )
    except FencingRejected:
        pass
    else:
        raise ProbeRejected("released Lease still grants a current write fence")
    return {"lease_effect_readback": True, "effect_sha256": observed["sha256"],
            "completion_sha256": observed["completion_sha256"],
            "original_marker_verified": True, "late_old_owner_fenced": True}


def _uncertain_pg_readback(profile, row, proof):
    scoped = make_conninfo(
        profile["postgres_dsn"], options=f"-c search_path={row['pg_schema']}",
    )
    with psycopg.connect(scoped) as connection:
        effect = connection.execute(
            "SELECT work_item_id,lease_id,resource_id,operation_id,status,"
            "completion_state,expected_sha256,intent_sha256,completion_sha256,"
            "registration_command_id,registration_operation_id,"
            "reconciliation_command_id,reconciliation_operation_id,"
            "registered_readback,reconciled_readback FROM effects WHERE effect_id=%s",
            (proof["effect_id"],),
        ).fetchone()
        lease = connection.execute(
            "SELECT owner_attempt_id,owner_runtime_id,generation,status,fencing_token "
            "FROM leases WHERE lease_id=%s", (proof["lease_id"],),
        ).fetchone()
        delivery = connection.execute(
            "SELECT message_id,dispatch_id,status FROM delivery_attempts "
            "WHERE attempt_id=%s", (proof["attempt_id"],),
        ).fetchone()
        attempt = connection.execute(
            "SELECT work_item_id,runtime_id,source_commit,source_tree,candidate_ref "
            "FROM attempts WHERE attempt_id=%s", (proof["attempt_id"],),
        ).fetchone()
        receipt = connection.execute(
            "SELECT attempt_id,work_item_id FROM execution_receipts WHERE receipt_id=%s",
            (proof["receipt_id"],),
        ).fetchone()
        evidence = connection.execute(
            "SELECT attempt_id,candidate_ref FROM evidence WHERE evidence_id=%s",
            (proof["evidence_id"],),
        ).fetchone()
        review = connection.execute(
            "SELECT verdict,candidate_ref FROM reviews WHERE review_id=%s",
            (proof["review_id"],),
        ).fetchone()
        events = connection.execute(
            "SELECT command_id,event_id FROM domain_events "
            "WHERE command_id IN (%s,%s,%s,%s) ORDER BY event_id",
            (proof["acquire_command_id"], proof["release_command_id"],
             proof["registration_command_id"], proof["reconciliation_command_id"]),
        ).fetchall()
        outbox = connection.execute(
            "SELECT operation_id,topic FROM outbox "
            "WHERE operation_id IN (%s,%s,%s,%s)",
            (proof["acquire_operation_id"], proof["release_operation_id"],
             proof["registration_operation_id"], proof["reconciliation_operation_id"]),
        ).fetchall()
        ready = connection.execute(
            "SELECT revision,readiness_snapshot FROM accepted_state_revisions "
            "WHERE work_item_id=%s AND revision=1", (proof["work_item_id"],),
        ).fetchone()
    if (
        effect is None
        or effect[:13] != (
            proof["work_item_id"], proof["lease_id"], proof["resource_id"],
            proof["effect_operation_id"], "verified", "completed",
            proof["artifact_sha256"], proof["intent_sha256"],
            proof["completion_sha256"], proof["registration_command_id"],
            proof["registration_operation_id"], proof["reconciliation_command_id"],
            proof["reconciliation_operation_id"],
        )
        or not isinstance(effect[13], dict) or not isinstance(effect[14], dict)
        or effect[13].get("completion_state") != "prepared"
        or effect[13].get("completion_sha256") is not None
        or effect[14].get("completion_state") != "completed"
        or effect[14].get("completion_sha256") != proof["completion_sha256"]
        or lease is None
        or lease[:4] != (proof["attempt_id"], proof["runtime_id"],
                         proof["generation"], "released")
        or _sha(lease[4].encode()) != proof["fencing_token_sha256"]
        or delivery != (proof["message_id"], proof["dispatch_id"], "delivered")
        or attempt != (
            proof["work_item_id"], proof["runtime_id"], proof["source_commit"],
            proof["source_tree"], proof["candidate_ref"],
        )
        or receipt != (proof["attempt_id"], proof["work_item_id"])
        or evidence != (proof["attempt_id"], proof["candidate_ref"])
        or review != ("pass", proof["candidate_ref"])
        or ready != (1, True)
        or [{"command_id": item[0], "event_id": str(item[1])} for item in events]
        != proof["domain_event_ids"]
        or set(outbox) != {
            (proof["acquire_operation_id"], "lease.acquired"),
            (proof["release_operation_id"], "lease.release"),
            (proof["registration_operation_id"], "effect.registered"),
            (proof["reconciliation_operation_id"], "effect.reconciled"),
        }
    ):
        raise ProbeRejected("uncertain Effect PG/Delivery/Attempt lineage changed")
    return {"uncertain_effect_pg_readback": True, "effect_id": proof["effect_id"]}


def _uncertain_effect_readback(profile, ledger, row, proof):
    root = ledger.root / "P1-UNCERTAIN-EFFECT-effects"
    output = root / "output.txt"
    info = output.stat(follow_symlinks=False)
    identity = [info.st_dev, info.st_ino, info.st_uid,
                info.st_mode & 0o777, info.st_nlink]
    if (
        identity != proof["effect_file_identity"]
        or _sha(output.read_bytes()) != proof["effect_file_sha256"]
        or _effect_marker_digest(root) != proof["effect_marker_sha256"]
        or info.st_mode & 0o777 != 0o600 or info.st_nlink != 1
    ):
        raise ProbeRejected("uncertain Effect file or marker readback changed")
    key = _sha(proof["effect_operation_id"].encode())
    operations = root / ".acs-effect-markers" / "operations"
    if (
        not (operations / (key + ".intent")).is_file()
        or not (operations / (key + ".completed")).is_file()
        or any(not item.name.startswith(key + ".") for item in operations.iterdir())
    ):
        raise ProbeRejected("uncertain Effect admitted another operation marker")
    completion = json.loads((operations / (key + ".completed")).read_text())
    if completion.get("body", {}).get("completion_basis") != "observed_target":
        raise ProbeRejected("uncertain Effect completion was not readback-only")
    with LocalArtifactStore(ledger.root / "P1-UNCERTAIN-EFFECT-cas") as store:
        artifact = ArtifactRef.model_validate(proof["artifact_ref"])
        readback = ArtifactRef.model_validate(proof["source_readback_ref"])
        if store.read(artifact) != output.read_bytes():
            raise ProbeRejected("uncertain Effect differs from ready candidate CAS bytes")
        store.verify(readback)
    scoped = make_conninfo(
        profile["postgres_dsn"], options=f"-c search_path={row['pg_schema']}",
    )
    authority = DomainAuthority(scoped)
    with authority._connect() as connection:
        token = connection.execute(
            "SELECT fencing_token FROM leases WHERE lease_id=%s", (proof["lease_id"],),
        ).fetchone()
    if token is None or _sha(token[0].encode()) != proof["fencing_token_sha256"]:
        raise ProbeRejected("uncertain Effect Lease token changed")
    reader = DomainAuthority(scoped, context=replace(
        authority.context,
        principal_ref=proof["reader_principal_ref"],
        grant_ref=proof["reader_grant_ref"],
    ))
    with LocalFileEffectGateway(
        reader.leases, root, scope_id="local-scope",
        resource_paths={proof["resource_id"]: "output.txt"},
    ) as gateway:
        observed = gateway.historical_readback(
            proof["lease_id"], proof["resource_id"], proof["generation"],
            token[0], "output.txt", caller=reader.context, scope_id="local-scope",
            grant_ref=reader.context.grant_ref,
            authority_incarnation=reader.context.authority_incarnation,
            expected_operation_id=proof["effect_operation_id"],
        )
    if (
        observed["status"] != "verified"
        or observed["sha256"] != proof["artifact_sha256"]
        or observed["intent_sha256"] != proof["intent_sha256"]
        or observed["completion_sha256"] != proof["completion_sha256"]
        or observed["completion_state"] != "completed"
    ):
        raise ProbeRejected("uncertain Effect original operation no longer reads back")
    return {"uncertain_effect_file_readback": True,
            "effect_sha256": observed["sha256"],
            "completion_sha256": observed["completion_sha256"],
            "target_write_count": proof["target_write_count"]}



def _stale_pg_readback(profile, row, proof):
    scoped = make_conninfo(
        profile["postgres_dsn"], options=f"-c search_path={row['pg_schema']}",
    )
    with psycopg.connect(scoped) as connection:
        work = connection.execute(
            "SELECT state,revision,source_baseline FROM work_items "
            "WHERE work_item_id=%s", (proof["work_item_id"],),
        ).fetchone()
        ready = connection.execute(
            "SELECT baseline_ref,readiness_snapshot FROM accepted_state_revisions "
            "WHERE work_item_id=%s AND revision=1", (proof["work_item_id"],),
        ).fetchone()
        accepted = connection.execute(
            "SELECT count(*) FROM accepted_state_revisions "
            "WHERE work_item_id=%s AND readiness_snapshot=FALSE",
            (proof["work_item_id"],),
        ).fetchone()[0]
        attempt = connection.execute(
            "SELECT work_item_id,runtime_id,source_baseline,source_commit,source_tree "
            "FROM attempts WHERE attempt_id=%s", (proof["attempt_id"],),
        ).fetchone()
        delivery = connection.execute(
            "SELECT message_id,dispatch_id,status,selection_json->>'machine_id' "
            "FROM delivery_attempts WHERE attempt_id=%s", (proof["attempt_id"],),
        ).fetchone()
        receipt = connection.execute(
            "SELECT work_item_id,attempt_id,source_baseline FROM execution_receipts "
            "WHERE receipt_id=%s", (proof["receipt_id"],),
        ).fetchone()
        evidence = connection.execute(
            "SELECT work_item_id,attempt_id,baseline_ref,candidate_ref FROM evidence "
            "WHERE evidence_id=%s", (proof["evidence_id"],),
        ).fetchone()
        review = connection.execute(
            "SELECT verdict,baseline_ref,candidate_ref FROM reviews WHERE review_id=%s",
            (proof["review_id"],),
        ).fetchone()
        effects = connection.execute(
            "SELECT count(*) FROM effects WHERE work_item_id=%s",
            (proof["work_item_id"],),
        ).fetchone()[0]
        denied = {
            table: connection.execute(
                f"SELECT count(*) FROM {table} WHERE command_id=%s",
                (proof["accept_command_id"],),
            ).fetchone()[0]
            for table in ("command_dedup", "domain_events", "operations")
        }
        cas_denied = {
            table: connection.execute(
                f"SELECT count(*) FROM {table} WHERE command_id=%s",
                (proof["cas_accept_command_id"],),
            ).fetchone()[0]
            for table in ("command_dedup", "domain_events", "operations")
        }
        events = connection.execute(
            "SELECT command_id,event_id FROM domain_events "
            "WHERE command_id IN (%s,%s,%s,%s,%s) ORDER BY event_id",
            tuple(proof["committed_operations"]),
        ).fetchall()
        outbox = connection.execute(
            "SELECT operation_id,topic FROM outbox "
            "WHERE operation_id IN (%s,%s,%s,%s,%s)",
            tuple(proof["committed_operations"].values()),
        ).fetchall()
    if (
        work != ("acceptance_ready", 1, proof["stale_baseline"])
        or ready != (proof["ready_baseline"], True)
        or accepted != 0 or effects != 0 or any(denied.values())
        or any(cas_denied.values())
        or denied != proof["denied_command_counts"]
        or cas_denied != proof["cas_denied_command_counts"]
        or attempt != (
            proof["work_item_id"], proof["runtime_id"], proof["ready_baseline"],
            proof["source_commit"], proof["source_tree"],
        )
        or delivery != (
            proof["message_id"], proof["dispatch_id"], "delivered",
            proof["machine_id"],
        )
        or receipt != (
            proof["work_item_id"], proof["attempt_id"], proof["ready_baseline"],
        )
        or evidence != (
            proof["work_item_id"], proof["attempt_id"], proof["ready_baseline"],
            proof["candidate_ref"],
        )
        or review != ("pass", proof["ready_baseline"], proof["candidate_ref"])
        or [{"command_id": item[0], "event_id": str(item[1])} for item in events]
        != proof["committed_event_ids"]
        or len(outbox) != len(proof["committed_operations"])
        or {item[0] for item in outbox}
        != set(proof["committed_operations"].values())
    ):
        raise ProbeRejected("stale baseline PG acceptance/readiness lineage changed")
    return {"stale_baseline_pg_readback": True,
            "denied_command_id": proof["accept_command_id"],
            "accepted_revision_count": accepted}


def _verify_private_git_drift(
    source_root: Path, ledger: ProbeLedger, proof: dict[str, Any],
) -> dict[str, Any]:
    drift = proof["source_drift"]
    patch_path = ledger.root / "P1-STALE-BASELINE-source.diff"
    if (
        not patch_path.is_file() or patch_path.is_symlink()
        or patch_path.stat(follow_symlinks=False).st_mode & 0o777 != 0o600
        or _sha(patch_path.read_bytes()) != drift["stale_diff_sha256"]
    ):
        raise ProbeRejected("stale private Git diff identity changed")
    try:
        stamp = datetime.strptime(drift["git_timestamp"], "%Y-%m-%dT%H:%M:%S %z")
        reproduced, patch = _private_source_drift(
            source_root, proof["source_tree"], stamp,
        )
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        raise ProbeRejected("stale private Git reconstruction failed") from error
    if reproduced != drift or patch != patch_path.read_bytes():
        raise ProbeRejected("stale private Git HEAD/tree/parent/diff readback changed")
    return {
        "copied_source_commit": drift["copied_source_commit"],
        "copied_source_tree": drift["copied_source_tree"],
        "stale_git_commit": drift["stale_git_commit"],
        "stale_git_tree": drift["stale_git_tree"],
        "stale_diff_sha256": drift["stale_diff_sha256"],
    }


def _stale_source_readback(profile, ledger, row, proof):
    source_commit = os.environ.get("ACS_GATE_SOURCE_COMMIT")
    source_tree = os.environ.get("ACS_GATE_SOURCE_TREE")
    if not source_commit or not source_tree:
        source_commit, source_tree = _source_identity(Path(profile["source_root"]))
    if (
        (source_commit, source_tree) != (proof["source_commit"], proof["source_tree"])
        or proof["stale_baseline"] == source_commit
        or (ledger.root / "P1-STALE-BASELINE-effects").exists()
    ):
        raise ProbeRejected("stale baseline source or protected Effect boundary changed")
    git_readback = _verify_private_git_drift(Path(profile["source_root"]), ledger, proof)
    if git_readback["stale_git_commit"] != proof["stale_baseline"]:
        raise ProbeRejected("stale WorkItem baseline is not the private Git HEAD")
    proof_file = ledger.root / "P1-STALE-BASELINE-proof.json"
    if (
        json.loads(proof_file.read_text()) != proof
        or proof_file.stat(follow_symlinks=False).st_mode & 0o777 != 0o600
    ):
        raise ProbeRejected("stale baseline private fault proof changed")
    try:
        with LocalArtifactStore(ledger.root / "P1-STALE-BASELINE-cas") as store:
            artifact = ArtifactRef.model_validate(proof["artifact_ref"])
            readback = ArtifactRef.model_validate(proof["readback_ref"])
            store.verify(artifact)
            store.verify(readback)
    except (ArtifactError, ValueError):
        raise ProbeRejected("stale candidate CAS bytes changed") from None
    scoped = make_conninfo(
        profile["postgres_dsn"], options=f"-c search_path={row['pg_schema']}",
    )
    with psycopg.connect(scoped) as connection:
        work = connection.execute(
            "SELECT source_baseline,state,revision FROM work_items "
            "WHERE work_item_id=%s", (proof["work_item_id"],),
        ).fetchone()
        effects = connection.execute(
            "SELECT count(*) FROM effects WHERE work_item_id=%s",
            (proof["work_item_id"],),
        ).fetchone()[0]
    if work != (proof["stale_baseline"], "acceptance_ready", 1) or effects:
        raise ProbeRejected("stale baseline source readback no longer denies acceptance")
    return {"stale_source_readback": True,
            "actual_source_commit": source_commit,
            "ready_baseline": proof["ready_baseline"],
            "stale_baseline": proof["stale_baseline"],
            "protected_effect_count": effects, **git_readback}



def _read_layer(profile: dict[str, Any], scenario: str, kind: str,
                ledger: ProbeLedger, row: dict[str, Any]) -> dict[str, Any]:
    lineage = json.loads(row["lineage_json"])
    required_lineage = {
        "tenant_id", "command_id", "message_id", "operation_id", "attempt_id",
        "dispatch_id", "attempts", "event_ids", "receipts", "driver_calls",
        "node_journal", "grant_ref", "machine_id", "node_id", "message_state",
        "inbox_count", "grant_revoked",
        "ack_loss_observed", "exact_replay", "conflict_rejected",
        "core_crash_proof", "node_restart_proof", "provider_restart_proof",
        "lease_proof", "uncertain_effect_proof", "stale_baseline_proof",
        "dedup_details", "operation_details", "outbox_details", "message_hashes",
        "event_hashes", "provider_refs",
    }
    if set(lineage) < required_lineage:
        raise ProbeRejected("marker-only evidence is not an actual Runtime lineage")
    if (
        lineage["machine_id"] != profile["machine_id"]
        or lineage["node_id"] != profile["node_id"]
        or any(item["selection_machine"] != lineage["machine_id"]
               for item in lineage["attempts"])
    ):
        raise ProbeRejected("Node/Attempt machine identity differs from Gate Machine")
    expected_auth_failure = scenario == "P1-AUTH-REVOCATION"
    if (
        lineage["message_state"] != ("blocked" if expected_auth_failure else "delivered")
        or lineage["inbox_count"] != (0 if expected_auth_failure else 1)
        or lineage["grant_revoked"] != expected_auth_failure
        or lineage["driver_calls"] != (
            [] if scenario in (
                "P1-AUTH-REVOCATION", "P1-NODE-RESTART", "P1-PROVIDER-RESTART",
            )
            else [lineage["operation_id"]]
        )
        or not lineage["exact_replay"] or not lineage["conflict_rejected"]
        or lineage["ack_loss_observed"] != (scenario == "P1-INBOX-ACK-LOSS")
        or (lineage["core_crash_proof"] is not None) != (scenario == "P1-CORE-RESTART")
        or (lineage["node_restart_proof"] is not None) != (scenario == "P1-NODE-RESTART")
        or (lineage["provider_restart_proof"] is not None)
        != (scenario == "P1-PROVIDER-RESTART")
        or (lineage["lease_proof"] is not None) != (scenario == "P1-LEASE-FENCING")
        or (lineage["uncertain_effect_proof"] is not None)
        != (scenario == "P1-UNCERTAIN-EFFECT")
        or (lineage["stale_baseline_proof"] is not None)
        != (scenario == "P1-STALE-BASELINE")
    ):
        raise ProbeRejected("scenario lineage does not prove its required fault")
    if scenario == "P1-CORE-RESTART":
        proof = lineage["core_crash_proof"]
        if (
            not isinstance(proof, dict) or proof.get("exit_code") != 83
            or proof.get("node_before") != 0 or proof.get("driver_before") != 0
            or len(lineage["attempts"]) != 1
            or proof.get("prepared_attempt_id") != lineage["attempts"][0]["attempt_id"]
            or lineage["attempts"][0]["status"] != "delivered"
        ):
            raise ProbeRejected("Core crash recovery lineage is incomplete")
    if scenario == "P1-NODE-RESTART":
        proof = lineage["node_restart_proof"]
        if (
            proof.get("exit_code") not in (0, None)
            or (proof.get("exit_code") is None) != proof.get("recovered_from_readback")
            or proof.get("old_boot") == proof.get("new_boot")
            or len(lineage["attempts"]) != 2
            or [item["status"] for item in lineage["attempts"]] != ["retry_wait", "delivered"]
            or [item["selection_revision"] for item in lineage["attempts"]] != [1, 2]
            or [item["selection_boot"] for item in lineage["attempts"]]
            != [proof["old_boot"], proof["new_boot"]]
        ):
            raise ProbeRejected("Node boot replacement lineage is incomplete")
    if scenario == "P1-PROVIDER-RESTART":
        proof = lineage["provider_restart_proof"]
        if (
            proof.get("crash_exit") != 84
            or proof.get("recovery_exit") not in (0, None)
            or (proof.get("recovery_exit") is None) != proof.get("recovered_from_readback")
            or len(lineage["attempts"]) != 1
            or lineage["attempts"][0]["attempt_id"] != proof.get("prepared_attempt_id")
            or lineage["attempts"][0]["status"] != "delivered"
            or proof.get("workflow_id") != row["temporal_workflow_id"]
            or proof.get("run_id") != row["temporal_run_id"]
            or lineage["provider_refs"] != [proof["workflow_id"], proof["run_id"]]
        ):
            raise ProbeRejected("Temporal worker replacement lineage is incomplete")
    if scenario == "P1-LEASE-FENCING":
        proof = lineage["lease_proof"]
        if (
            proof.get("delivery_operation_id") != lineage["operation_id"]
            or proof.get("source_commit") != row["source_commit"]
            or proof.get("source_tree") != row["source_tree"]
            or proof.get("machine_id") != profile["machine_id"]
            or proof.get("node_id") != profile["node_id"]
            or proof.get("historical_readback") != "verified"
            or proof.get("original_historical_readback") != "verified"
            or proof.get("stale_fence_rejected") is not True
            or proof.get("late_old_owner_rejected") is not True
            or proof.get("replacement_readback_before_late") is not True
            or not isinstance(proof.get("pre_late_snapshot"), dict)
            or proof.get("pre_late_snapshot") != proof.get("post_late_snapshot")
            or proof["pre_late_snapshot"].get("file_sha256") != proof.get("effect_sha256")
            or proof["pre_late_snapshot"].get("file_identity")
            != proof.get("effect_file_identity")
            or proof.get("replacement_generation") != proof.get("generation", -1) + 1
            or proof.get("replacement_attempt_id") == proof.get("attempt_id")
            or not proof.get("effect_completion_sha256")
        ):
            raise ProbeRejected("Lease fence source/Node/effect lineage is incomplete")
    if scenario == "P1-UNCERTAIN-EFFECT":
        proof = lineage["uncertain_effect_proof"]
        if (
            proof.get("delivery_operation_id") != lineage["operation_id"]
            or proof.get("message_id") != lineage["message_id"]
            or proof.get("dispatch_id") != lineage["dispatch_id"]
            or proof.get("attempt_id") != lineage["attempt_id"]
            or proof.get("source_commit") != row["source_commit"]
            or proof.get("source_tree") != row["source_tree"]
            or proof.get("machine_id") != profile["machine_id"]
            or proof.get("node_id") != profile["node_id"]
            or proof.get("domain_record_absent_at_fault") is not True
            or proof.get("initial_status") != "uncertain"
            or proof.get("initial_completion_state") != "prepared"
            or proof.get("final_status") != "verified"
            or proof.get("final_completion_state") != "completed"
            or proof.get("target_write_count") != 1
            or proof.get("completion_basis") != "observed_target"
            or proof.get("pending_new_operation_rejected") is not True
            or proof.get("acceptance_blocked_while_uncertain") is not True
            or proof.get("failed_accept_dedup_count") != 0
            or proof.get("late_old_owner_rejected") is not True
            or proof.get("original_operation_replay") is not True
            or proof.get("effect_file_sha256") != proof.get("artifact_sha256")
            or proof.get("effect_file_sha256") != proof.get("fault_file_sha256")
            or proof.get("effect_file_identity") != proof.get("fault_file_identity")
        ):
            raise ProbeRejected("uncertain Effect same-lineage recovery proof is incomplete")
    if scenario == "P1-STALE-BASELINE":
        proof = lineage["stale_baseline_proof"]
        if (
            proof.get("delivery_operation_id") != lineage["operation_id"]
            or proof.get("message_id") != lineage["message_id"]
            or proof.get("dispatch_id") != lineage["dispatch_id"]
            or proof.get("attempt_id") != lineage["attempt_id"]
            or proof.get("source_commit") != row["source_commit"]
            or proof.get("source_tree") != row["source_tree"]
            or proof.get("machine_id") != profile["machine_id"]
            or proof.get("node_id") != profile["node_id"]
            or proof.get("ready_baseline") != row["source_commit"]
            or proof.get("stale_baseline") == proof.get("ready_baseline")
            or proof.get("source_drift", {}).get("copied_source_tree") != row["source_tree"]
            or proof.get("source_drift", {}).get("stale_git_commit")
            != proof.get("stale_baseline")
            or proof.get("source_drift", {}).get("stale_git_tree") == row["source_tree"]
            or proof.get("ready_revision") != 1
            or proof.get("denied_replay_count") != 2
            or "receipt artifact bytes are not verified"
            not in proof.get("cas_rejection_reason", "")
            or any(proof.get("cas_denied_command_counts", {}).values())
            or any(proof.get("denied_command_counts", {}).values())
            or proof.get("accepted_revision_count") != 0
            or proof.get("protected_effect_count") != 0
            or not proof.get("rejection_reason")
        ):
            raise ProbeRejected("stale source acceptance denial proof is incomplete")
    if kind == "postgresql":
        scoped = make_conninfo(
            profile["postgres_dsn"], options=f"-c search_path={row['pg_schema']}",
        )
        with psycopg.connect(scoped) as connection:
            command_row = connection.execute(
                "SELECT command_id,canonical_hash,hash_version FROM command_dedup "
                "WHERE command_id=%s",
                (lineage["command_id"],),
            ).fetchone()
            operation_row = connection.execute(
                "SELECT operation_id,status,provider,provider_workflow_id,provider_run_id "
                "FROM operations WHERE operation_id=%s",
                (lineage["operation_id"],),
            ).fetchone()
            event_rows = connection.execute(
                "SELECT event_id,canonical_hash FROM domain_events WHERE command_id=%s "
                "ORDER BY event_id",
                (lineage["command_id"],),
            ).fetchall()
            outbox_row = connection.execute(
                "SELECT operation_id,topic,delivered_at IS NOT NULL FROM outbox "
                "WHERE operation_id=%s",
                (lineage["operation_id"],),
            ).fetchone()
            message_row = connection.execute(
                "SELECT operation_id,canonical_hash,envelope_hash FROM delivery_messages "
                "WHERE message_id=%s",
                (lineage["message_id"],),
            ).fetchone()
            attempt_rows = connection.execute(
                "SELECT ordinal,attempt_id,dispatch_id,status,selection_revision,"
                "selection_json->>'boot_incarnation',selection_json->>'machine_id' "
                "FROM delivery_attempts "
                "WHERE message_id=%s ORDER BY ordinal",
                (lineage["message_id"],),
            ).fetchall()
            receipt_rows = connection.execute(
                "SELECT receipt_id,layer FROM delivery_receipts WHERE message_id=%s "
                "ORDER BY observed_at",
                (lineage["message_id"],),
            ).fetchall()
            message_state = connection.execute(
                "SELECT state,last_error FROM delivery_messages WHERE message_id=%s",
                (lineage["message_id"],),
            ).fetchone()
            inbox_count = connection.execute(
                "SELECT count(*) FROM inbox_messages WHERE message_id=%s",
                (lineage["message_id"],),
            ).fetchone()[0]
            grant_revoked = connection.execute(
                "SELECT revoked_at IS NOT NULL FROM grants WHERE grant_ref=%s",
                (lineage["grant_ref"],),
            ).fetchone()[0]
            dedup_count = connection.execute(
                "SELECT count(*) FROM command_dedup WHERE command_id=%s",
                (lineage["command_id"],),
            ).fetchone()[0]
            operation_count = connection.execute(
                "SELECT count(*) FROM operations WHERE command_id=%s",
                (lineage["command_id"],),
            ).fetchone()[0]
            outbox_count = connection.execute(
                "SELECT count(*) FROM outbox WHERE operation_id=%s",
                (lineage["operation_id"],),
            ).fetchone()[0]
        expected_receipts = [(item["receipt_id"], item["layer"]) for item in lineage["receipts"]]
        expected_attempts = [
            (item["ordinal"], item["attempt_id"], item["dispatch_id"], item["status"],
             item["selection_revision"], item["selection_boot"],
             item["selection_machine"])
            for item in lineage["attempts"]
        ]
        if (
            operation_row != (lineage["operation_id"], *lineage["operation_details"],
                              *lineage["provider_refs"])
            or [str(item[0]) for item in event_rows] != lineage["event_ids"]
            or [item[1] for item in event_rows] != lineage["event_hashes"]
            or outbox_row != (lineage["operation_id"], *lineage["outbox_details"])
            or message_row != (lineage["operation_id"], *lineage["message_hashes"])
            or command_row != (lineage["command_id"], *lineage["dedup_details"])
            or attempt_rows != expected_attempts
            or receipt_rows != expected_receipts
            or message_state != (lineage["message_state"], lineage["last_error"])
            or inbox_count != lineage["inbox_count"]
            or grant_revoked != lineage["grant_revoked"]
            or dedup_count != 1
            or operation_count != 1 or outbox_count != 1 or len(event_rows) != 1
        ):
            raise ProbeRejected("PostgreSQL Runtime lineage changed")
        extra = (
            _lease_pg_readback(profile, row, lineage["lease_proof"])
            if scenario == "P1-LEASE-FENCING"
            else _uncertain_pg_readback(profile, row, lineage["uncertain_effect_proof"])
            if scenario == "P1-UNCERTAIN-EFFECT"
            else _stale_pg_readback(profile, row, lineage["stale_baseline_proof"])
            if scenario == "P1-STALE-BASELINE" else {}
        )
        return {"postgresql_readback": True, "lineage_digest": _sha(_canonical(lineage)),
                **extra}
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
            journal_node = connection.execute(
                "SELECT machine_id,node_id FROM journal WHERE operation_id=?",
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
            boot_rows = connection.execute(
                "SELECT boot_incarnation,machine_id,node_id FROM node_boots "
                "ORDER BY started_at,boot_incarnation",
            ).fetchall()
            lease_node = (
                connection.execute(
                    "SELECT machine_id,node_id,boot_incarnation FROM journal "
                    "WHERE operation_id=?", (lineage["operation_id"],),
                ).fetchone()
                if scenario == "P1-LEASE-FENCING" else None
            )
        if not boot_rows or any(
            (item[1], item[2]) != (lineage["machine_id"], lineage["node_id"])
            for item in boot_rows
        ):
            raise ProbeRejected("SQLite Node boot differs from Gate Machine")
        if expected_auth_failure:
            if any(item is not None for item in (journal, journal_node, mailbox)) or node_receipts:
                raise ProbeRejected("revoked command reached the Node")
        elif (journal != (lineage["command_id"], lineage["message_id"])
              or journal_node != (lineage["machine_id"], lineage["node_id"])
              or mailbox != (lineage["operation_id"],) or not node_receipts):
            raise ProbeRejected("SQLite Node lineage changed")
        if scenario == "P1-NODE-RESTART":
            proof = lineage["node_restart_proof"]
            boots = {item[0] for item in boot_rows}
            if (boots != {proof["old_boot"], proof["new_boot"]}
                    or len(boot_rows) != 2
                    or len({(item[1], item[2]) for item in boot_rows}) != 1
                    or _sha(_canonical(_node_receipts(node_path, lineage["operation_id"])))
                    != proof["node_receipt_digest"]):
                raise ProbeRejected("SQLite Node boot/receipt lineage changed")
        if scenario == "P1-LEASE-FENCING" and lease_node != (
            lineage["lease_proof"]["machine_id"],
            lineage["lease_proof"]["node_id"],
            lineage["lease_proof"]["node_boot"],
        ):
            raise ProbeRejected("SQLite Node differs from signed Lease execution owner")
        return {"sqlite_readback": True, "journal_sha256": _sha(node_path.read_bytes()),
                "node_receipt_ids": [item[0] for item in node_receipts]}
    if kind == "temporal":
        async def read():
            adapter = TemporalAdapter(
                profile["temporal_endpoint"], namespace=profile["temporal_namespace"],
            )
            await adapter.connect(start_worker=False)
            try:
                value = await adapter.readback(row["temporal_workflow_id"])
                if scenario == "P1-PROVIDER-RESTART":
                    description = await adapter.client.get_workflow_handle(
                        row["temporal_workflow_id"],
                    ).describe()
                    return value, description.run_id, await description.memo()
                return value, None, None
            finally:
                await adapter.close()
        value, temporal_run, memo = asyncio.run(read())
        if scenario == "P1-PROVIDER-RESTART":
            identity = {key: lineage[key] for key in ("tenant_id", "message_id", "operation_id")}
            expected_hash = _sha(json.dumps(
                identity, sort_keys=True, separators=(",", ":"),
            ).encode())
            if (
                value.get("status") != "delivered"
                or value.get("message_id") != lineage["message_id"]
                or row["temporal_workflow_id"] != "acs-delivery/" + lineage["operation_id"]
                or temporal_run != row["temporal_run_id"]
                or memo.get("acs_delivery_identity_hash") != expected_hash
            ):
                raise ProbeRejected("Temporal delivery Workflow lineage changed")
        elif (
            value.get("status") != "committed"
            or row["temporal_workflow_id"] != lineage["operation_id"] + ":temporal"
            or value.get("payload", {}).get("operation_id") != row["temporal_workflow_id"]
            or value.get("payload", {}).get("scenario_id") != scenario
        ):
            raise ProbeRejected("Temporal scenario marker changed")
        return {"temporal_readback": True, "workflow_id": row["temporal_workflow_id"],
                "run_id": row["temporal_run_id"]}
    if kind == "driver":
        raw = ledger.root / row["raw_path"]
        value = json.loads(raw.read_text())
        if (value.get("lineage") != lineage
                or _sha(raw.read_bytes()) != row["test_digest"]):
            raise ProbeRejected("Driver/raw test evidence changed")
        extra = (
            _lease_effect_readback(profile, ledger, row, lineage["lease_proof"])
            if scenario == "P1-LEASE-FENCING"
            else _uncertain_effect_readback(
                profile, ledger, row, lineage["uncertain_effect_proof"],
            ) if scenario == "P1-UNCERTAIN-EFFECT"
            else _stale_source_readback(
                profile, ledger, row, lineage["stale_baseline_proof"],
            ) if scenario == "P1-STALE-BASELINE" else {}
        )
        return {"driver_readback": True, "driver_calls": lineage["driver_calls"],
                "raw_sha256": _sha(raw.read_bytes()), **extra}
    if kind == "os":
        if scenario == "P1-CORE-RESTART":
            proof = lineage["core_crash_proof"]
            context_path = ledger.root / "P1-CORE-RESTART-context.json"
            proof_path = ledger.root / "P1-CORE-RESTART-crash.json"
            if (
                Path(f"/proc/{proof['child_pid']}").exists()
                or _sha(context_path.read_bytes()) != proof["context_digest"]
                or json.loads(proof_path.read_text()) != proof
                or any((path.stat().st_mode & 0o777) != 0o600
                       for path in (context_path, proof_path))
            ):
                raise ProbeRejected("Core crash process is not conclusively stopped")
        if scenario == "P1-NODE-RESTART":
            proof = lineage["node_restart_proof"]
            context_path = ledger.root / "P1-NODE-RESTART-context.json"
            result_path = ledger.root / "P1-NODE-RESTART-child-result.json"
            proof_path = ledger.root / "P1-NODE-RESTART-proof.json"
            if (
                Path(f"/proc/{proof['child_pid']}").exists()
                or _sha(context_path.read_bytes()) != proof["context_digest"]
                or _sha(result_path.read_bytes()) != proof["result_digest"]
                or json.loads(proof_path.read_text()) != proof
                or any((path.stat().st_mode & 0o777) != 0o600
                       for path in (context_path, result_path, proof_path))
            ):
                raise ProbeRejected("Node replacement process is not conclusively stopped")
        if scenario == "P1-PROVIDER-RESTART":
            proof = lineage["provider_restart_proof"]
            paths = {
                "context_digest": ledger.root / "P1-PROVIDER-RESTART-context.json",
                "crash_digest": ledger.root / "P1-PROVIDER-RESTART-crash.json",
                "result_digest": ledger.root / "P1-PROVIDER-RESTART-child-result.json",
            }
            proof_path = ledger.root / "P1-PROVIDER-RESTART-proof.json"
            if (
                Path(f"/proc/{proof['crash_pid']}").exists()
                or Path(f"/proc/{proof['recovery_pid']}").exists()
                or any(_sha(path.read_bytes()) != proof[key] for key, path in paths.items())
                or json.loads(proof_path.read_text()) != proof
                or any((path.stat().st_mode & 0o777) != 0o600
                       for path in (*paths.values(), proof_path))
            ):
                raise ProbeRejected("Temporal Worker processes are not conclusively stopped")
        if os.environ.get("ACS_GATE_RUNTIME_ROOT") == "/run/acs-p1/runtime":
            if os.environ.get("ACS_GATE_HOST_OS_ATTESTATION") != "/run/acs-p1/host-os.json":
                raise ProbeRejected("trusted host OS attestation is missing")
            host_sha = os.environ.get("ACS_GATE_HOST_OS_SHA256", "")
            host_path = Path("/run/acs-p1/host-os.json")
            try:
                host_bytes = host_path.read_bytes()
                host = json.loads(host_bytes)
                host_info = host_path.stat(follow_symlinks=False)
            except (OSError, ValueError):
                raise ProbeRejected("trusted host OS attestation is unreadable") from None
            if (not isinstance(host, dict) or not 0 < len(host_bytes) <= 65_536
                    or not re.fullmatch(r"[0-9a-f]{64}", host_sha)
                    or _sha(host_bytes) != host_sha
                    or not stat.S_ISREG(host_info.st_mode)
                    or host_info.st_uid != os.geteuid()
                    or stat.S_IMODE(host_info.st_mode) != 0o600
                    or host_info.st_nlink != 1
                    or host.get("schema_version") != "acs-p1-host-os-attestation/1"
                    or host.get("run_id") != os.environ.get("ACS_GATE_RUN_ID")
                    or host.get("scenario_id") != scenario
                    or host.get("command_id") != os.environ.get("ACS_GATE_COMMAND_ID")
                    or host.get("source_commit") != row["source_commit"]
                    or host.get("source_tree") != row["source_tree"]
                    or host.get("binding_sha256") != os.environ.get("ACS_GATE_BINDING_SHA256")
                    or host.get("host_uid") != os.geteuid()
                    or host.get("bus_peer_uid") != os.geteuid()
                    or host.get("systemd_user_exit") != 0):
                raise ProbeRejected("trusted host OS attestation differs from scenario")
            systemd_exit = 0
        else:
            systemd = subprocess.run(
                ["systemctl", "--user", "show-environment"], capture_output=True,
                timeout=10, check=False,
            )
            if systemd.returncode:
                raise ProbeUnavailable("systemd --user manager is unavailable")
            systemd_exit = systemd.returncode
        current_commit = os.environ.get("ACS_GATE_SOURCE_COMMIT")
        current_tree = os.environ.get("ACS_GATE_SOURCE_TREE")
        if not current_commit or not current_tree:
            current_commit, current_tree = _source_identity(Path(profile["source_root"]))
        if (current_commit, current_tree) != (row["source_commit"], row["source_tree"]):
            raise ProbeRejected("source identity changed during scenario evidence")
        extra = (
            _lease_effect_readback(profile, ledger, row, lineage["lease_proof"])
            if scenario == "P1-LEASE-FENCING"
            else _uncertain_effect_readback(
                profile, ledger, row, lineage["uncertain_effect_proof"],
            ) if scenario == "P1-UNCERTAIN-EFFECT"
            else _stale_source_readback(
                profile, ledger, row, lineage["stale_baseline_proof"],
            ) if scenario == "P1-STALE-BASELINE" else {}
        )
        return {"os_readback": True, "platform": platform.platform(),
                "systemd_user_exit": systemd_exit, **extra}
    raw = ledger.root / row["raw_path"]
    if (_sha(raw.read_bytes()) != row["test_digest"] or not lineage["conflict_rejected"]
            or (scenario == "P1-LEASE-FENCING" and (
                not lineage["lease_proof"]["stale_fence_rejected"]
                or not lineage["lease_proof"]["late_old_owner_rejected"]
            ))
            or (scenario == "P1-UNCERTAIN-EFFECT" and (
                lineage["uncertain_effect_proof"]["target_write_count"] != 1
                or not lineage["uncertain_effect_proof"]["late_old_owner_rejected"]
            ))
            or (scenario == "P1-STALE-BASELINE" and (
                lineage["stale_baseline_proof"]["accepted_revision_count"] != 0
                or lineage["stale_baseline_proof"]["protected_effect_count"] != 0
            ))):
        raise ProbeRejected("command output does not bind the Runtime transaction")
    return {"command_output": True, "test_digest": row["test_digest"],
            "lineage_digest": _sha(_canonical(lineage))}


def _runner_result(profile: dict[str, Any], scenario: str, kind: str,
                   row: dict[str, Any], layer: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(UTC)
    facts = {"layer": layer}
    fields = EVIDENCE_FIELDS[kind]
    lineage = json.loads(row["lineage_json"])
    lease = lineage.get("lease_proof")
    uncertain = lineage.get("uncertain_effect_proof")
    stale = lineage.get("stale_baseline_proof")
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
        "machine_id": profile["machine_id"],
        "node_id": os.environ.get("ACS_GATE_NODE_ID", profile["node_id"]),
        "direction": os.environ.get("ACS_GATE_DIRECTION", profile["direction"]),
        "versions": json.loads(os.environ.get("ACS_GATE_VERSIONS_JSON", json.dumps(profile["versions"]))),
        "observed_at": now.isoformat(),
        "expires_at": os.environ.get("ACS_GATE_EXPIRES_AT", (now + timedelta(minutes=5)).isoformat()),
        "operation_ids": [row["operation_id"], row["temporal_workflow_id"]]
        + ([
            lease["acquire_operation_id"], lease["release_operation_id"],
            lease["replacement_acquire_operation_id"],
            lease["replacement_release_operation_id"],
        ] if lease else [])
        + ([
            uncertain["acquire_operation_id"], uncertain["release_operation_id"],
            uncertain["registration_operation_id"],
            uncertain["reconciliation_operation_id"],
        ] if uncertain else [])
        + (list(stale["committed_operations"].values()) if stale else []),
        "message_ids": [row["message_id"]],
        "event_ids": [row["event_id"]]
        + ([item["event_id"] for item in lease["lease_events"]] if lease else [])
        + ([item["event_id"] for item in uncertain["domain_event_ids"]]
           if uncertain else [])
        + ([item["event_id"] for item in stale["committed_event_ids"]]
           if stale else []),
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
    profile["_profile_path"] = str(profile_path)
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
    gate_machine = os.environ.get("ACS_GATE_MACHINE_ID")
    profile["machine_id"] = (
        _safe_name(gate_machine) if gate_machine is not None
        else "machine-" + _sha(platform.node().encode())[:20]
    )
    gate_node = os.environ.get("ACS_GATE_NODE_ID")
    if gate_node is not None and gate_node != profile["node_id"]:
        raise ProbeRejected("Gate Node identity differs from reviewed profile")
    profile.setdefault("binding_sha256", _sha(_canonical({
        "profile": profile["profile"], "machine_id": profile["machine_id"],
        "node_id": profile["node_id"], "versions": profile["versions"],
    })))
    ledger = ProbeLedger(output)
    row = _run_tests(profile, scenario, ledger, commit, tree, fault) \
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
    crash = commands.add_parser("core-crash")
    crash.add_argument("--profile", type=Path, required=True)
    crash.add_argument("--context", type=Path, required=True)
    crash.add_argument("--context-sha256", required=True)
    node_restart = commands.add_parser("node-restart")
    node_restart.add_argument("--profile", type=Path, required=True)
    node_restart.add_argument("--context", type=Path, required=True)
    node_restart.add_argument("--context-sha256", required=True)
    node_restart.add_argument("--result", type=Path, required=True)
    provider_worker = commands.add_parser("provider-worker")
    provider_worker.add_argument("--profile", type=Path, required=True)
    provider_worker.add_argument("--context", type=Path, required=True)
    provider_worker.add_argument("--context-sha256", required=True)
    provider_worker.add_argument("--mode", choices=("crash", "recover"), required=True)
    provider_worker.add_argument("--result", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "core-crash":
            _core_crash_child(args.profile, args.context, args.context_sha256)
            raise ProbeRejected("Core crash child returned unexpectedly")
        if args.command == "node-restart":
            _node_restart_child(args.profile, args.context, args.context_sha256, args.result)
            return 0
        if args.command == "provider-worker":
            _provider_worker_child(
                args.profile, args.context, args.context_sha256, args.mode, args.result,
            )
            return 0
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
